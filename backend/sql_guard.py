"""
Checks the model's SQL before it is allowed near the database.

The rule is simple: one read only SELECT, against tables we chose to expose,
with a row cap. Everything else is refused.

Written as deny by default. A query has to pass every check to run, rather
than only failing if it matches something we happened to think of.
"""

import re
import sqlglot
from sqlglot import exp

# The only tables the model may touch. Bronze and silver are deliberately absent.
ALLOWED_TABLES = {
    "permits.gold.fact_permits",
    "permits.gold.dim_postal_area",
    "permits.gold.dim_status",
    "permits.gold.dim_permit_type",
    "permits.gold.dim_date",
    "permits.gold.approval_trend",
    "permits.gold.ui_summary",
    "permits.gold.kpis",
}

MAX_ROWS = 200
MAX_LENGTH = 4000

# Any of these in the query tree means it is not a plain read.
WRITE_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
    exp.TruncateTable, exp.Merge, exp.Grant, exp.Into, exp.Copy, exp.Set,
    exp.Use, exp.Describe, exp.Cache, exp.Uncache, exp.Analyze, exp.Pragma,
)

# Functions that can reach outside the allowed tables. Table functions are the
# real risk: read_files() would open any path the warehouse can see.
BLOCKED_FUNCTIONS = {
    "read_files", "cloud_files", "input_file_name", "input_file_block_start",
    "read_kafka", "read_kinesis", "read_pubsub", "read_statestore",
    "java_method", "reflect", "current_user", "session_user",
    "list_secrets", "secret", "ai_query", "ai_gen",
}


class Rejected(Exception):
    """Raised with a reason the user can be shown."""


def validate(sql: str) -> str:
    """Return the SQL that may be run, or raise Rejected with a reason."""

    if not sql or not sql.strip():
        raise Rejected("No query was produced.")

    sql = sql.strip()

    if sql == "CANNOT_ANSWER":
        raise Rejected("That question cannot be answered from this data.")

    if len(sql) > MAX_LENGTH:
        raise Rejected("That query is too long.")

    # Parse first. Anything sqlglot cannot read is refused rather than guessed at.
    try:
        statements = [s for s in sqlglot.parse(sql, read="databricks") if s]
    except Exception:
        raise Rejected("That query could not be parsed.")

    # One statement only. Two is how a second query gets smuggled in behind the first.
    if len(statements) != 1:
        raise Rejected("Only one statement is allowed.")

    tree = statements[0]

    # sqlglot wraps anything it does not recognise, such as SET, USE, SHOW,
    # EXECUTE IMMEDIATE or VACUUM, in a Command node. Refuse all of them.
    if isinstance(tree, exp.Command) or tree.find(exp.Command):
        raise Rejected("Only SELECT queries are allowed.")

    # The statement itself has to be a query.
    if not isinstance(tree, (exp.Select, exp.Union, exp.Subquery)):
        raise Rejected("Only SELECT queries are allowed.")

    # No write or admin node anywhere in the tree, including inside a CTE,
    # a subquery, or one side of a union.
    if isinstance(tree, WRITE_NODES) or any(tree.find_all(*WRITE_NODES)):
        raise Rejected("Only SELECT queries are allowed.")

    _check_functions(tree)
    _check_tables(tree)

    return _apply_limit(tree)


def _check_functions(tree) -> None:
    """Refuse functions that can read outside the allowed tables."""
    for node in tree.find_all(exp.Func):
        if isinstance(node, exp.Anonymous):
            name = str(node.this).lower()
        else:
            name = (node.sql_name() or "").lower()
        if name in BLOCKED_FUNCTIONS:
            raise Rejected(f"Function not available: {name}")


def _check_tables(tree) -> None:
    """Every table referenced has to be one we chose to expose."""
    cte_names = _cte_names(tree)
    found = False

    for table in tree.find_all(exp.Table):
        found = True

        # A table function such as read_files('path') appears here with
        # something other than a plain name. Refuse anything that is not a table.
        if not isinstance(table.this, (exp.Identifier, str)):
            raise Rejected("Table functions are not allowed.")

        parts = [p for p in (table.catalog, table.db, table.name) if p]
        if not parts:
            raise Rejected("Could not read the table name.")

        full = ".".join(parts).lower()

        # A bare name may be a CTE defined inside this query, which is fine.
        if len(parts) == 1 and parts[0].lower() in cte_names:
            continue

        if full not in ALLOWED_TABLES:
            raise Rejected(f"Table not available: {full}")

    if not found:
        raise Rejected("That query does not read any of the permit tables.")


def _cte_names(tree) -> set:
    names = set()
    for with_clause in tree.find_all(exp.With):
        for cte in with_clause.expressions:
            names.add(cte.alias_or_name.lower())
    return names


def _apply_limit(tree) -> str:
    """Add or tighten a LIMIT so one query cannot pull back the whole table."""
    limit = tree.args.get("limit")

    if limit is None:
        tree = tree.limit(MAX_ROWS)
    else:
        try:
            if int(limit.expression.this) > MAX_ROWS:
                tree.set("limit", None)
                tree = tree.limit(MAX_ROWS)
        except (AttributeError, ValueError, TypeError):
            # A limit we cannot read, such as LIMIT ?, gets replaced outright.
            tree.set("limit", None)
            tree = tree.limit(MAX_ROWS)

    out = tree.sql(dialect="databricks")

    # Last check in case the rendered SQL somehow lost the cap.
    if not re.search(r"\blimit\b", out, re.I):
        out = f"{out} LIMIT {MAX_ROWS}"

    return out
