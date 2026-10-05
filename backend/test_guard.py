"""
Tests for the SQL guard.

Run with: python test_guard.py

These exist because the guard is the only thing standing between a language
model's output and the database. A change that quietly weakens it should fail
here rather than in production.
"""

from sql_guard import validate, Rejected, MAX_ROWS

passed = failed = 0


def reject(sql, label):
    """The guard must refuse this."""
    global passed, failed
    try:
        out = validate(sql)
        print(f"  FAIL  {label}\n        allowed: {out}")
        failed += 1
    except Rejected:
        passed += 1


def allow(sql, label):
    """The guard must let this through."""
    global passed, failed
    try:
        out = validate(sql)
        if "limit" not in out.lower():
            print(f"  FAIL  {label}: no row cap applied")
            failed += 1
        else:
            passed += 1
    except Rejected as e:
        print(f"  FAIL  {label}\n        refused: {e}")
        failed += 1


print("writes")
reject("DELETE FROM permits.gold.fact_permits", "delete")
reject("UPDATE permits.gold.fact_permits SET status = 'x'", "update")
reject("INSERT INTO permits.gold.fact_permits VALUES (1)", "insert")
reject("DROP TABLE permits.gold.fact_permits", "drop")
reject("TRUNCATE TABLE permits.gold.fact_permits", "truncate")
reject("CREATE TABLE evil AS SELECT * FROM permits.gold.fact_permits", "create as select")
reject("ALTER TABLE permits.gold.fact_permits ADD COLUMN x INT", "alter")
reject("MERGE INTO permits.gold.fact_permits t USING x s ON t.a = s.a", "merge")

print("stacked statements")
reject("SELECT 1 FROM permits.gold.fact_permits; DROP TABLE permits.gold.fact_permits", "two statements")
reject("SELECT count(*) FROM permits.gold.fact_permits;DELETE FROM permits.gold.kpis", "two, no space")

print("hidden writes")
reject("WITH x AS (DELETE FROM permits.gold.fact_permits RETURNING 1) SELECT * FROM x", "delete in a cte")
reject("SELECT * FROM permits.gold.fact_permits INTO OUTFILE '/tmp/x'", "select into")

print("admin commands")
reject("GRANT SELECT ON permits.gold.fact_permits TO someone", "grant")
reject("SHOW TABLES IN permits.gold", "show")
reject("USE permits.bronze", "use")
reject("SET spark.sql.shuffle.partitions = 1", "set")
reject("VACUUM permits.gold.fact_permits", "vacuum")
reject("OPTIMIZE permits.gold.fact_permits", "optimize")
reject("DESCRIBE permits.gold.fact_permits", "describe")

print("tables outside gold")
reject("SELECT * FROM permits.bronze.active_permits", "bronze")
reject("SELECT * FROM permits.silver.permits", "silver")
reject("SELECT * FROM system.information_schema.tables", "system catalog")
reject("SELECT * FROM permits.gold.query_log", "log table, not exposed")
reject("SELECT a.permit_key FROM permits.gold.fact_permits a JOIN permits.silver.permits b ON a.permit_key = b.permit_key", "allowed joined to not allowed")
reject("SELECT * FROM permits.gold.fact_permits WHERE permit_key IN (SELECT permit_key FROM permits.bronze.active_permits)", "subquery on bronze")
reject("SELECT * FROM permits.gold.fact_permits UNION ALL SELECT * FROM permits.silver.permits", "union with silver")

print("file and function access")
reject("SELECT * FROM read_files('abfss://permits@permitsdata12.dfs.core.windows.net/raw/active')", "read_files")
reject("SELECT input_file_name() FROM permits.gold.fact_permits", "input_file_name")
reject("SELECT current_user() FROM permits.gold.fact_permits", "current_user")

print("nonsense")
reject("", "empty")
reject("CANNOT_ANSWER", "model declined")
reject("this is not sql at all", "not sql")
reject("SELECT 1", "no table")
reject("SELECT * FROM permits.gold.fact_permits " + "WHERE 1=1 " * 500, "too long")

print("valid queries")
allow("SELECT count(*) FROM permits.gold.fact_permits", "simple count")
allow("SELECT region, count(*) FROM permits.gold.fact_permits f JOIN permits.gold.dim_postal_area d ON f.postal_area = d.postal_area GROUP BY region", "join and group")
allow("WITH recent AS (SELECT * FROM permits.gold.fact_permits WHERE application_year = 2025) SELECT count(*) FROM recent", "cte")
allow("SELECT application_year, median_days_to_issue FROM permits.gold.approval_trend ORDER BY application_year", "trend table")
allow("SELECT * FROM permits.gold.fact_permits LIMIT 5", "its own small limit")
allow("SELECT percentile_approx(days_to_issue, 0.5) FROM permits.gold.fact_permits", "percentile")

print("row cap")
out = validate("SELECT * FROM permits.gold.fact_permits LIMIT 100000")
assert f"LIMIT {MAX_ROWS}" in out.upper(), f"big limit not reduced: {out}"
out = validate("SELECT * FROM permits.gold.fact_permits LIMIT 5")
assert "LIMIT 5" in out.upper(), f"small limit should be kept: {out}"
passed += 2

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
