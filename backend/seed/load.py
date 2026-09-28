"""Create the schema, load synthetic data and run post-seed steps.

Usage (from backend/):
    python -m seed.load                  # uses DATABASE_URL
The API endpoint POST /api/v1/admin/reset calls reset_database() too.
"""
import os
import sys

import psycopg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import config  # noqa: E402
from app.auth import Actor  # noqa: E402
from app.db import get_conn, q_all  # noqa: E402
from seed.generate import build_sql  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
SCHEMA = os.path.join(ROOT, "db", "schema.sql")

SYSTEM = Actor("SYSTEM", "Seed loader", "admin")
APPLICANT = Actor("HUMAN", "Rosario Galang (MSME owner)", "applicant")
APP_AGENT = Actor("AGENT", "MSME Application Agent", "agent")
FIN_AGENT = Actor("AGENT", "Financial Analysis Agent", "agent")
CASE_AGENT = Actor("AGENT", "Credit Case Agent", "agent")
PORTFOLIO_AGENT = Actor("AGENT", "Portfolio Intelligence Agent", "agent")
GROWTH_AGENT = Actor("AGENT", "RM & Growth Agent", "agent")


def _run_sql(sql_text):
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        conn.execute(sql_text)  # no params -> no placeholder parsing


def post_seed():
    from app.services import analysis, applications, growth, monitoring
    with get_conn() as c:
        # 1) A complete application waiting for the credit officer (APP-2026-0004)
        applications.validate_documents(c, APP_AGENT, "APP-2026-0004")
        analysis.run_financial_analysis(c, FIN_AGENT, "APP-2026-0004")
        analysis.generate_credit_case(c, CASE_AGENT, "APP-2026-0004", narrative=(
            "Bulacan Furniture Makers (21 years in business, nearly 15 with LANDBANK) requests PHP 4.0M equipment financing for a CNC router "
            "and kiln dryer to serve export orders. Cash flows are stable with a healthy surplus and no repayment delays. "
            "Key question for the officer: confirm the export order pipeline supporting the added capacity."))
        applications.submit_application(c, APPLICANT, "APP-2026-0004")
    with get_conn() as c:
        # 2) Baseline monitoring snapshot for every customer
        for cu in q_all(c, "SELECT customer_id FROM customers ORDER BY customer_id"):
            monitoring.calculate_signals(c, cu["customer_id"], PORTFOLIO_AGENT, persist=True)
        # 3) Two alerts already raised by the Portfolio agent (others left for the agent to find)
        for cid, summary in [
            ("LB-MSME-0015", "Typhoon damage and a lost export buyer: receipts down ~29%, repayment 41 days late, credit line 97% used."),
            ("LB-MSME-0016", "Milling delays cut hauling income: receipts down ~26%, three returned checks, repayment 41 days late."),
        ]:
            a = monitoring.create_alert(c, PORTFOLIO_AGENT, cid, "HIGH", summary, "RM outreach within 2 business days; understand the cash position before any restructuring discussion.")
            growth.create_task(c, GROWTH_AGENT, cid, "RISK_OUTREACH", "Proactive risk outreach", summary, "HIGH", 2, a["alert_id"])
        growth.all_opportunities(c, GROWTH_AGENT)  # store today's evidence-backed opportunities
        growth.create_task(c, APP_AGENT, "LB-MSME-0018", "DOCUMENT_FOLLOW_UP", "Help Santos Bakery complete documents",
                           "ITR (BIR 1701) FY2025 missing; audited financial statements pages 7-8 missing.", "MEDIUM", 3)


def reset_database():
    _run_sql(open(SCHEMA, encoding="utf-8").read())
    _run_sql(build_sql())
    post_seed()
    with get_conn() as c:
        from app import events
        events.emit(c, "DEMO_DATA_RESET", SYSTEM, payload={"as_of": config.AS_OF_DATE.isoformat()})
        counts = q_all(c, """SELECT (SELECT COUNT(*) FROM customers) AS customers, (SELECT COUNT(*) FROM transactions) AS transactions,
                                    (SELECT COUNT(*) FROM loans) AS loans, (SELECT COUNT(*) FROM applications) AS applications""")[0]
    return {"status": "reset complete", **counts}


if __name__ == "__main__":
    from app import db
    db.open_pool()
    print(reset_database())
    db.close_pool()
