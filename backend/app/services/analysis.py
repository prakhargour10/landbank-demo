"""Financial Analysis Agent + Credit Case Agent data services.

The service does the arithmetic (one calculation, reused everywhere). The agents add the
narrative on top and must quote these numbers rather than re-computing them.
"""
from fastapi import HTTPException

from .. import events
from ..db import execute, jsonb, q_all, q_one
from ..util import as_of, new_id, not_found, peso
from .applications import get_application, list_documents
from .customers import get_credit_report, get_customer, get_loans, monthly_cashflow


def _cash_gap_window(conn, customer_id):
    """Day-of-month profile of net cash flow; returns the 10-day window with the largest net outflow."""
    prof = q_all(conn, """SELECT EXTRACT(DAY FROM txn_date)::int AS d,
                                 SUM(CASE WHEN direction='CREDIT' THEN amount ELSE -amount END) AS net
                          FROM transactions WHERE customer_id=%(c)s GROUP BY 1 ORDER BY 1""", {"c": customer_id})
    net = {r["d"]: r["net"] for r in prof}
    best, start = None, 1
    for s in range(1, 22):
        v = sum(net.get(d, 0) for d in range(s, s + 10))
        if best is None or v < best:
            best, start = v, s
    return {"from_day": start, "to_day": start + 9, "net_flow_in_window": round(best or 0, 2)}


def build_financial_analysis(conn, customer_id, amount=None, tenure=None, rate=9.0):
    get_customer(conn, customer_id)
    cf = monthly_cashflow(conn, customer_id, 12)
    if not cf:
        raise HTTPException(409, "No transaction history available")
    loans = get_loans(conn, customer_id, include_schedule=False)
    n = len(cf)
    receipts = [m["customer_receipts"] or 0 for m in cf]
    inflow = [m["inflow"] or 0 for m in cf]
    outflow = [m["outflow"] or 0 for m in cf]
    loan_pay = [m["loan_repayments"] or 0 for m in cf]
    annual_receipts = sum(receipts) * 12 / n
    avg_in, avg_out = sum(inflow) / n, sum(outflow) / n
    avg_out_ex_debt = (sum(outflow) - sum(loan_pay)) / n
    net_operating = avg_in - avg_out_ex_debt
    debt_service = sum(l["monthly_amortization"] for l in loans if l["status"] == "ACTIVE")
    first6, last6 = sum(receipts[: n // 2]) or 1, sum(receipts[n // 2:])
    growth = round((last6 - first6) / first6 * 100, 1)
    mean = sum(receipts) / n
    volatility = round((sum((r - mean) ** 2 for r in receipts) / n) ** 0.5 / mean * 100, 1) if mean else None
    new_service = 0
    if amount and tenure:
        r = rate / 100 / 12
        new_service = amount * r / (1 - (1 + r) ** -tenure)
    dscr_now = round(net_operating / debt_service, 2) if debt_service else None
    dscr_pro_forma = round(net_operating / (debt_service + new_service), 2) if (debt_service + new_service) else None
    tax = q_all(conn, "SELECT period_label, declared_gross_sales FROM tax_filings WHERE customer_id=%(c)s AND form_code IN ('2550Q','2551Q') ORDER BY period_end DESC LIMIT 4", {"c": customer_id})
    gap = _cash_gap_window(conn, customer_id)
    rep = get_credit_report(conn, customer_id)
    metrics = {
        "period": f"{cf[0]['month']} to {cf[-1]['month']}",
        "annual_customer_receipts": round(annual_receipts, 2),
        "receipts_growth_last6_vs_first6_pct": growth,
        "avg_monthly_inflow": round(avg_in, 2),
        "avg_monthly_outflow": round(avg_out, 2),
        "avg_monthly_surplus": round(avg_in - avg_out, 2),
        "surplus_pct_of_inflow": round((avg_in - avg_out) / avg_in * 100, 1) if avg_in else None,
        "net_operating_cash_flow_monthly": round(net_operating, 2),
        "existing_monthly_debt_service": round(debt_service, 2),
        "existing_outstanding": round(sum(l["outstanding"] for l in loans if l["status"] == "ACTIVE"), 2),
        "dscr_current": dscr_now,
        "requested_amount": amount, "requested_tenure_months": tenure,
        "proposed_monthly_amortization": round(new_service, 2) if new_service else None,
        "dscr_pro_forma": dscr_pro_forma,
        "receipts_volatility_pct": volatility,
        "credit_score": rep["score"], "credit_score_band": rep["score_band"],
        "latest_declared_quarterly_sales": tax[0]["declared_gross_sales"] if tax else None,
        "recurring_cash_gap": gap,
    }
    insights = [
        f"Customer receipts of {peso(annual_receipts)} a year; the last 6 months are {growth:+}% vs the first 6.",
        f"Average monthly surplus of {peso(avg_in - avg_out)} ({metrics['surplus_pct_of_inflow']}% of inflows).",
    ]
    if gap["net_flow_in_window"] < 0:
        insights.append(f"A cash gap recurs between day {gap['from_day']} and day {gap['to_day']} of each month, when supplier payments are concentrated.")
    if dscr_pro_forma:
        insights.append(f"Debt-service coverage would be {dscr_pro_forma}x with the requested facility (current {dscr_now}x).")
    fit = {"product_code": "WORKING_CAPITAL", "reason": "Recurring intra-month cash gap from inventory purchases."} if gap["net_flow_in_window"] < 0 else \
          {"product_code": "TERM_LOAN", "reason": "Stable cash flows suitable for fixed amortization."}
    fit["note"] = "Recommendation only - not an approval."
    return metrics, cf, insights, fit


def run_financial_analysis(conn, actor, application_id):
    app = get_application(conn, application_id)
    if app["status"] not in ("DOCUMENTS_COMPLETE", "IN_ASSESSMENT", "CREDIT_CASE_READY", "MORE_INFO_REQUESTED"):
        raise HTTPException(409, f"Application is {app['status']}; documents must be complete first.")
    execute(conn, "UPDATE applications SET status='IN_ASSESSMENT', updated_at=now() WHERE application_id=%(a)s", {"a": application_id})
    rate = q_one(conn, "SELECT indicative_rate_pct FROM products WHERE product_code=%(p)s", {"p": app["product_code"]})["indicative_rate_pct"]
    metrics, monthly, insights, fit = build_financial_analysis(conn, app["customer_id"], app["amount_requested"], app["tenure_months"], rate)
    confidence = 0.87
    aid = new_id(conn, "FA", "financial_analyses", "analysis_id")
    execute(conn, """INSERT INTO financial_analyses (analysis_id, application_id, customer_id, metrics, monthly, insights, product_fit, confidence, created_by)
                     VALUES (%(id)s, %(a)s, %(c)s, %(m)s, %(mo)s, %(i)s, %(f)s, %(conf)s, %(by)s)""",
            {"id": aid, "a": application_id, "c": app["customer_id"], "m": jsonb(metrics), "mo": jsonb(monthly), "i": jsonb(insights),
             "f": jsonb(fit), "conf": confidence, "by": actor.actor_name})
    events.emit(conn, "FINANCIAL_ANALYSIS_COMPLETED", actor, customer_id=app["customer_id"], application_id=application_id,
                payload={"analysis_id": aid, "dscr_pro_forma": metrics["dscr_pro_forma"], "annual_receipts": metrics["annual_customer_receipts"]},
                confidence=confidence)
    events.emit(conn, "PRODUCT_FIT_SUGGESTED", actor, customer_id=app["customer_id"], application_id=application_id, payload=fit)
    return get_financial_analysis(conn, application_id)


def get_financial_analysis(conn, application_id):
    r = q_one(conn, "SELECT * FROM financial_analyses WHERE application_id=%(a)s ORDER BY created_at DESC LIMIT 1", {"a": application_id})
    if not r:
        not_found("Financial analysis for application", application_id)
    return r


# ---------------------------------------------------------------------------
# Credit case
# ---------------------------------------------------------------------------
def _clamp(v):
    return int(max(0, min(100, round(v))))


def generate_credit_case(conn, actor, application_id, narrative=None):
    app = get_application(conn, application_id)
    if app["status"] not in ("IN_ASSESSMENT", "CREDIT_CASE_READY", "MORE_INFO_REQUESTED", "SENT_BACK"):
        raise HTTPException(409, f"Application is {app['status']}; run the financial analysis first.")
    fa = get_financial_analysis(conn, application_id)
    m = fa["metrics"]
    c = get_customer(conn, app["customer_id"])
    docs = list_documents(conn, application_id)
    rep = get_credit_report(conn, app["customer_id"])
    late = q_one(conn, """SELECT COUNT(*) FILTER (WHERE r.status='PAID_LATE') AS late, COUNT(*) FILTER (WHERE r.status='OVERDUE') AS overdue
                          FROM repayments r JOIN loans l USING (loan_id) WHERE l.customer_id=%(c)s""", {"c": app["customer_id"]})
    returned = q_one(conn, "SELECT COUNT(*) AS n FROM transactions WHERE customer_id=%(c)s AND category='RETURNED_CHECK'", {"c": app["customer_id"]})
    mismatch = next((i for d in docs for i in (d.get("issues") or []) if i.get("code") == "SALES_MISMATCH"), None)
    validated = sum(1 for d in docs if d["status"] == "VALIDATED")
    with_warnings = sum(1 for d in docs if d["status"] == "ISSUE_FOUND" and all(i["severity"] == "WARNING" for i in d["issues"]))

    factors = {
        "business_stability": _clamp(50 + c["business_vintage_years"] * 3 + min(c["employees"], 40) * 0.5),
        "cash_flow_strength": _clamp(40 + (m["surplus_pct_of_inflow"] or 0) * 3),
        "debt_capacity": _clamp(((m["dscr_pro_forma"] or 0) - 0.8) * 70),
        "documentation": _clamp((validated + with_warnings) / 8 * 100),
        "banking_behaviour": _clamp(95 - late["late"] * 6 - late["overdue"] * 25 - returned["n"] * 8 + min(c["relationship_years"], 10)),
        "revenue_consistency": _clamp(100 - (m["receipts_volatility_pct"] or 0) * 2 - (25 if mismatch else 0)),
    }
    weights = {"business_stability": 0.15, "cash_flow_strength": 0.20, "debt_capacity": 0.25, "documentation": 0.10,
               "banking_behaviour": 0.20, "revenue_consistency": 0.10}
    score = _clamp(sum(factors[k] * w for k, w in weights.items()))

    evidence = [
        {"item": "Bank statement analysis", "detail": f"{m['period']}: receipts {peso(m['annual_customer_receipts'])} a year, surplus {m['surplus_pct_of_inflow']}% of inflows", "source": "BANK_STATEMENTS_12M", "confidence": 0.9},
        {"item": "Debt-service coverage", "detail": f"Pro-forma DSCR {m['dscr_pro_forma']}x with {peso(m['proposed_monthly_amortization'] or 0)}/month new amortization", "source": "Computed", "confidence": 0.88},
        {"item": "Credit report", "detail": f"Score {rep['score']} ({rep['score_band']}), max DPD 12m: {rep['max_dpd_12m']}", "source": "CREDIT_REPORT", "confidence": 0.95},
        {"item": "Declared vs actual sales", "detail": mismatch["message"] if mismatch else "BIR declared sales are consistent with bank receipts", "source": "VAT_RETURNS + BANK_STATEMENTS_12M", "confidence": 0.84},
        {"item": "Existing obligations", "detail": f"{peso(m['existing_outstanding'])} outstanding, {peso(m['existing_monthly_debt_service'])}/month", "source": "Core banking", "confidence": 0.95},
    ]
    strengths, risks, questions = [], [], []
    if c["business_vintage_years"] >= 5:
        strengths.append(f"{c['business_vintage_years']} years in business; {c['relationship_years']} years with LANDBANK.")
    if (m["receipts_growth_last6_vs_first6_pct"] or 0) > 3:
        strengths.append(f"Receipts growing {m['receipts_growth_last6_vs_first6_pct']}% (last 6 vs first 6 months).")
    if (m["dscr_pro_forma"] or 0) >= 1.25:
        strengths.append(f"Comfortable pro-forma DSCR of {m['dscr_pro_forma']}x.")
    else:
        risks.append(f"Pro-forma DSCR of {m['dscr_pro_forma']}x is below 1.25x.")
        questions.append("Can the amount or tenure be adjusted to keep DSCR at or above 1.25x?")
    if rep["score"] >= 700:
        strengths.append(f"Good credit score ({rep['score']}).")
    if late["late"] or late["overdue"]:
        risks.append(f"{late['late']} late and {late['overdue']} overdue repayments on record.")
        questions.append("What caused the late repayments, and is it resolved?")
    if returned["n"]:
        risks.append(f"{returned['n']} returned checks in the last 12 months.")
    if mismatch:
        risks.append(mismatch["message"])
        questions.append("Why are declared sales higher than bank receipts? Are some sales collected in cash or through another bank?")
    if m["recurring_cash_gap"]["net_flow_in_window"] < 0:
        questions.append(f"Is the requested amount sized to the cash gap between day {m['recurring_cash_gap']['from_day']} and {m['recurring_cash_gap']['to_day']} of each month?")
    if not risks:
        risks.append("No material risks found in the data reviewed.")
    confidence = 0.82 if mismatch else 0.86
    case_id = new_id(conn, "CASE", "credit_cases", "case_id")
    execute(conn, """INSERT INTO credit_cases (case_id, application_id, readiness_score, factor_scores, evidence, strengths, risks,
                     review_questions, narrative, confidence, created_by)
                     VALUES (%(id)s, %(a)s, %(s)s, %(f)s, %(e)s, %(st)s, %(r)s, %(q)s, %(n)s, %(conf)s, %(by)s)""",
            {"id": case_id, "a": application_id, "s": score, "f": jsonb(factors), "e": jsonb(evidence), "st": jsonb(strengths),
             "r": jsonb(risks), "q": jsonb(questions), "n": narrative, "conf": confidence, "by": actor.actor_name})
    execute(conn, "UPDATE applications SET status='CREDIT_CASE_READY', updated_at=now() WHERE application_id=%(a)s", {"a": application_id})
    events.emit(conn, "CREDIT_CASE_GENERATED", actor, customer_id=app["customer_id"], application_id=application_id,
                payload={"case_id": case_id, "readiness_score": score, "risks": risks}, confidence=confidence)
    return get_credit_case(conn, application_id)


def get_credit_case(conn, application_id):
    r = q_one(conn, "SELECT * FROM credit_cases WHERE application_id=%(a)s ORDER BY created_at DESC LIMIT 1", {"a": application_id})
    if not r:
        not_found("Credit case for application", application_id)
    r["score_label"] = "LANDBANK demo credit-readiness indicator (not a CIC or BSP-recognised score)"
    r["human_decision_required"] = True
    return r
