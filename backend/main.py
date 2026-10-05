"""
Toronto building permits API.

Two endpoints:
  /data  numbers for the dashboard, straight from permits.gold.ui_summary
  /ask   a plain English question, answered by generating SQL and running it
"""

import os
import time
import datetime
import decimal
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from databricks import sql as dbsql

from prompt import build_prompt
from llm import generate_sql
from sql_guard import validate, Rejected

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("permits")

app = FastAPI(title="Toronto Permits API")

# Only these sites may call the API from a browser. Without this the page
# on GitHub Pages gets blocked by the browser before the request is sent.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class Question(BaseModel):
    question: str


def run_sql(sql: str) -> list[dict]:
    """Run a query on the SQL warehouse and return rows as dictionaries."""
    with dbsql.connect(
        server_hostname=os.environ["DATABRICKS_HOST"],
        http_path=os.environ["DATABRICKS_HTTP_PATH"],
        access_token=os.environ["DATABRICKS_TOKEN"],
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def clean(value):
    """Make Databricks types safe to send as JSON."""
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def describe(rows: list[dict]) -> str:
    """Turn the result into one readable line for the answer box."""
    if not rows:
        return "No matching permits."

    if len(rows) == 1 and len(rows[0]) == 1:
        value = list(rows[0].values())[0]
        if value is None:
            return "No value"
        if isinstance(value, (int, float, decimal.Decimal)):
            value = float(value)
            return f"{value:,.0f}" if value == int(value) else f"{value:,.1f}"
        return str(value)

    if len(rows) == 1:
        return " \u00b7 ".join(f"{k}: {clean(v)}" for k, v in rows[0].items())

    # Several rows. Results are usually sorted with the interesting one first,
    # so lead with that and say how many others there are.
    first = rows[0]
    label = next((str(v) for v in first.values() if isinstance(v, str)), None)
    number = next((v for v in first.values()
                   if isinstance(v, (int, float, decimal.Decimal))), None)

    if label and number is not None:
        number = float(number)
        shown = f"{number:,.0f}" if number == int(number) else f"{number:,.1f}"
        return f"{label}: {shown} ({len(rows)} rows)"

    return f"{len(rows)} rows"


def log_query(question, sql, provider, ms, ok, note):
    """
    Keep a record of every question. Useful for spotting which questions the
    model gets wrong, and it gives the dashboard a usage page later.
    Never allowed to break a request, hence the bare except.
    """
    if os.getenv("LOG_QUERIES", "").lower() != "true":
        return
    try:
        safe = lambda s: str(s).replace("'", "''")[:2000]
        run_sql(
            "INSERT INTO permits.gold.query_log VALUES ("
            f"current_timestamp(), '{safe(question)}', '{safe(sql)}', "
            f"'{safe(provider)}', {int(ms)}, {str(ok).lower()}, '{safe(note)}')"
        )
    except Exception as e:
        log.warning("could not write query log: %s", e)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/data")
def data():
    """Every number the dashboard needs, in one call."""
    rows = run_sql("SELECT * FROM permits.gold.ui_summary")
    return {"rows": [{k: clean(v) for k, v in r.items()} for r in rows]}


@app.post("/ask")
def ask(body: Question):
    question = body.question.strip()
    if not question:
        return {"error": "Ask a question first."}

    started = time.time()
    sql = ""
    provider = ""

    try:
        sql, provider = generate_sql(question, build_prompt(question))
        checked = validate(sql)
    except Rejected as e:
        ms = (time.time() - started) * 1000
        log_query(question, sql, provider, ms, False, str(e))
        return {"error": str(e), "sql": sql}
    except Exception as e:
        ms = (time.time() - started) * 1000
        log_query(question, sql, provider, ms, False, str(e))
        log.exception("model failed")
        return {"error": "The model could not be reached. Try again in a moment."}

    try:
        rows = run_sql(checked)
    except Exception as e:
        ms = (time.time() - started) * 1000
        log_query(question, checked, provider, ms, False, str(e))
        log.exception("query failed")
        return {"error": "That query did not run against the data.", "sql": checked}

    ms = (time.time() - started) * 1000
    log_query(question, checked, provider, ms, True, "")

    return {
        "answer": describe(rows),
        "sql": checked,
        "rows": len(rows),
        "data": [{k: clean(v) for k, v in r.items()} for r in rows[:50]],
        "model": provider,
        "ms": int(ms),
    }
