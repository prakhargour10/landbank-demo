"""Customer & relationship data (read side of core banking, tax, bureau)."""
from .. import events
from ..db import q_all, q_one
from ..util import add_months, as_of, month_start, not_found, peso


def list_customers(conn, health_status=None, region=None, sector=None, rm_id=None, search=None):
    return q_all(conn, """
        SELECT c.customer_id, c.business_name, c.owner_name, c.sector, c.region, c.city, c.legal_form,
               c.health_status, c.rm_id, r.name AS rm_name, c.customer_since,
               COALESCE(SUM(l.outstanding) FILTER (WHERE l.status='ACTIVE'),0) AS total_outstanding,
               COUNT(l.loan_id) FILTER (WHERE l.status='ACTIVE') AS active_loans,
               MAX(l.days_past_due) AS max_days_past_due
        FROM customers c
        JOIN relationship_managers r ON r.rm_id=c.rm_id
        LEFT JOIN loans l ON l.customer_id=c.customer_id
        WHERE (%(h)s::text IS NULL OR c.health_status=%(h)s)
          AND (%(reg)s::text IS NULL OR c.region=%(reg)s)
          AND (%(sec)s::text IS NULL OR c.sector=%(sec)s)
          AND (%(rm)s::text IS NULL OR c.rm_id=%(rm)s)
          AND (%(q)s::text IS NULL OR c.business_name ILIKE '%%' || %(q)s || '%%' OR c.customer_id ILIKE '%%' || %(q)s || '%%')
        GROUP BY c.customer_id, r.name
        ORDER BY CASE c.health_status WHEN 'HIGH_ATTENTION' THEN 0 WHEN 'WATCH' THEN 1 ELSE 2 END, c.customer_id""",
                 {"h": health_status, "reg": region, "sec": sector, "rm": rm_id, "q": search})


def get_customer(conn, customer_id):
    c = q_one(conn, """SELECT c.*, r.name AS rm_name, r.email AS rm_email, r.mobile AS rm_mobile
                       FROM customers c JOIN relationship_managers r USING (rm_id) WHERE customer_id=%(c)s""",
              {"c": customer_id})
    if not c:
        not_found("Customer", customer_id)
    c["relationship_years"] = round((as_of().toordinal() - _d(c["customer_since"]).toordinal()) / 365.25, 1)
    c["business_vintage_years"] = round((as_of().toordinal() - _d(c["business_start"]).toordinal()) / 365.25, 1)
    return c


def _d(s):
    from datetime import date
    return date.fromisoformat(s[:10])


def get_accounts(conn, customer_id):
    get_customer(conn, customer_id)
    return q_all(conn, "SELECT * FROM accounts WHERE customer_id=%(c)s ORDER BY account_id", {"c": customer_id})


def get_transactions(conn, customer_id, date_from=None, date_to=None, category=None, direction=None, limit=500, offset=0):
    get_customer(conn, customer_id)
    rows = q_all(conn, """
        SELECT txn_id, account_id, txn_date, direction, amount, category, channel, counterparty, narration, balance_after
        FROM transactions WHERE customer_id=%(c)s
          AND (%(f)s::date IS NULL OR txn_date >= %(f)s::date) AND (%(t)s::date IS NULL OR txn_date <= %(t)s::date)
          AND (%(cat)s::text IS NULL OR category=%(cat)s) AND (%(dir)s::text IS NULL OR direction=%(dir)s)
        ORDER BY txn_date DESC, txn_id DESC LIMIT %(lim)s OFFSET %(off)s""",
                 {"c": customer_id, "f": date_from, "t": date_to, "cat": category, "dir": direction,
                  "lim": min(int(limit), 2000), "off": int(offset)})
    total = q_one(conn, """SELECT COUNT(*) AS n FROM transactions WHERE customer_id=%(c)s
          AND (%(f)s::date IS NULL OR txn_date >= %(f)s::date) AND (%(t)s::date IS NULL OR txn_date <= %(t)s::date)
          AND (%(cat)s::text IS NULL OR category=%(cat)s) AND (%(dir)s::text IS NULL OR direction=%(dir)s)""",
                  {"c": customer_id, "f": date_from, "t": date_to, "cat": category, "dir": direction})
    return {"customer_id": customer_id, "total": total["n"], "limit": limit, "offset": offset, "transactions": rows}


def monthly_cashflow(conn, customer_id, months=12):
    get_customer(conn, customer_id)
    start = add_months(month_start(as_of()), -int(months))
    return q_all(conn, """
        SELECT to_char(date_trunc('month', txn_date), 'YYYY-MM') AS month,
               SUM(amount) FILTER (WHERE direction='CREDIT') AS inflow,
               SUM(amount) FILTER (WHERE direction='DEBIT') AS outflow,
               SUM(amount) FILTER (WHERE category='CUSTOMER_RECEIPT') AS customer_receipts,
               SUM(amount) FILTER (WHERE category='SUPPLIER_PAYMENT') AS supplier_payments,
               SUM(amount) FILTER (WHERE category='PAYROLL') AS payroll,
               SUM(amount) FILTER (WHERE category='LOAN_REPAYMENT') AS loan_repayments,
               SUM(amount) FILTER (WHERE category='TAXES') AS taxes,
               COUNT(*) FILTER (WHERE category='RETURNED_CHECK') AS returned_checks,
               (ARRAY_AGG(balance_after ORDER BY txn_date DESC, txn_id DESC))[1] AS closing_balance
        FROM transactions WHERE customer_id=%(c)s AND txn_date >= %(s)s AND txn_date < %(e)s
        GROUP BY 1 ORDER BY 1""", {"c": customer_id, "s": start, "e": month_start(as_of())})


def get_tax_filings(conn, customer_id):
    get_customer(conn, customer_id)
    return q_all(conn, "SELECT * FROM tax_filings WHERE customer_id=%(c)s ORDER BY period_end DESC, form_code", {"c": customer_id})


def get_credit_report(conn, customer_id):
    get_customer(conn, customer_id)
    r = q_one(conn, "SELECT * FROM credit_reports WHERE customer_id=%(c)s", {"c": customer_id})
    if not r:
        not_found("Credit report", customer_id)
    r["note"] = "Synthetic CIC-style report for demo purposes only."
    return r


def get_loans(conn, customer_id, include_schedule=True):
    get_customer(conn, customer_id)
    loans = q_all(conn, """SELECT l.*, p.name AS product_name FROM loans l JOIN products p USING (product_code)
                           WHERE customer_id=%(c)s ORDER BY loan_id""", {"c": customer_id})
    for ln in loans:
        ln["utilisation_pct"] = round(ln["outstanding"] / ln["sanctioned_amount"] * 100, 1) if ln["product_code"] == "WORKING_CAPITAL" else None
        if include_schedule:
            ln["repayments"] = q_all(conn, "SELECT due_date, amount_due, paid_date, amount_paid, status FROM repayments WHERE loan_id=%(l)s ORDER BY due_date",
                                     {"l": ln["loan_id"]})
    return loans


def get_products(conn, customer_id):
    get_customer(conn, customer_id)
    return q_all(conn, """SELECT h.product_code, p.name, p.category, p.is_credit, h.since
                          FROM product_holdings h JOIN products p USING (product_code)
                          WHERE customer_id=%(c)s ORDER BY p.category, p.name""", {"c": customer_id})


def customer_360(conn, customer_id):
    from . import monitoring
    c = get_customer(conn, customer_id)
    sig = monitoring.calculate_signals(conn, customer_id, _system(), persist=False)
    return {
        "profile": c,
        "accounts": get_accounts(conn, customer_id),
        "loans": get_loans(conn, customer_id, include_schedule=False),
        "products": get_products(conn, customer_id),
        "credit_report": get_credit_report(conn, customer_id),
        "latest_tax_filings": get_tax_filings(conn, customer_id)[:5],
        "monthly_cashflow": monthly_cashflow(conn, customer_id, 6),
        "health": {"status": sig["health_status"], "metrics": sig["metrics"], "signals": sig["signals"]},
        "open_alerts": q_all(conn, "SELECT alert_id, severity, summary, status, created_at FROM risk_alerts WHERE customer_id=%(c)s AND status IN ('OPEN','IN_PROGRESS')", {"c": customer_id}),
        "open_tasks": q_all(conn, "SELECT task_id, task_type, title, priority, due_date, status FROM rm_tasks WHERE customer_id=%(c)s AND status IN ('OPEN','IN_PROGRESS')", {"c": customer_id}),
        "open_leads": q_all(conn, "SELECT lead_id, product_code, status, reason FROM rm_leads WHERE customer_id=%(c)s AND status IN ('NEW','CONTACTED')", {"c": customer_id}),
        "applications": q_all(conn, "SELECT application_id, product_code, amount_requested, status, updated_at FROM applications WHERE customer_id=%(c)s ORDER BY created_at DESC", {"c": customer_id}),
        "recent_events": q_all(conn, "SELECT event_id, event_type, occurred_at, actor_type, actor_name, payload FROM events WHERE customer_id=%(c)s ORDER BY event_id DESC LIMIT 15", {"c": customer_id}),
    }


def _system():
    from ..auth import Actor
    return Actor("SYSTEM", "LANDBANK Data Service", "system")


def eligibility_check(conn, actor, customer_id, amount=None, product_code="WORKING_CAPITAL"):
    """Indicative eligibility from data the bank already holds. NOT an approval."""
    c = get_customer(conn, customer_id)
    cf = monthly_cashflow(conn, customer_id, 12)
    rep = get_credit_report(conn, customer_id)
    loans = get_loans(conn, customer_id, include_schedule=False)
    receipts = [m["customer_receipts"] or 0 for m in cf]
    annual_receipts = sum(receipts)
    avg_in = sum((m["inflow"] or 0) for m in cf) / max(len(cf), 1)
    avg_out_ex_loans = sum((m["outflow"] or 0) - (m["loan_repayments"] or 0) for m in cf) / max(len(cf), 1)
    net_operating = avg_in - avg_out_ex_loans
    existing_service = sum(l["monthly_amortization"] for l in loans if l["status"] == "ACTIVE")
    # indicative capacity: keep DSCR >= 1.25 with the new facility at 9% over 12 months
    max_service = max(net_operating / 1.25 - existing_service, 0)
    indicative_max = round(max_service * 12 / 1.09, -4)
    reasons, ok = [], True
    if c["health_status"] == "HIGH_ATTENTION":
        ok = False
        reasons.append("Account currently needs attention (repayment delays or falling cash flows).")
    if rep["score"] < 620:
        ok = False
        reasons.append(f"Credit score {rep['score']} is below the indicative minimum of 620.")
    if c["business_vintage_years"] < 2:
        ok = False
        reasons.append("Business is less than 2 years old.")
    if ok:
        reasons.append(f"{c['business_vintage_years']} years in business, {c['relationship_years']} years with LANDBANK.")
        reasons.append(f"Customer receipts of {peso(annual_receipts)} in the last 12 months.")
        reasons.append(f"Credit score {rep['score']} ({rep['score_band']}).")
    result = {
        "customer_id": customer_id, "product_code": product_code, "indicatively_eligible": ok and indicative_max > 0,
        "indicative_max_amount": indicative_max if ok else 0, "requested_amount": amount,
        "requested_within_indicative_limit": (amount or 0) <= indicative_max if ok and amount else None,
        "readiness_hint": "HIGH" if ok and indicative_max >= (amount or 0) else "MEDIUM" if ok else "LOW",
        "reasons": reasons, "disclaimer": "Indicative only. This is not a loan approval; LANDBANK credit staff make the final decision.",
    }
    events.emit(conn, "ELIGIBILITY_CHECKED", actor, customer_id=customer_id,
                payload={k: result[k] for k in ("indicatively_eligible", "indicative_max_amount", "requested_amount")})
    return result
