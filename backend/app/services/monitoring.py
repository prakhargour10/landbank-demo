"""Portfolio Intelligence: metrics, early-warning signals, health status, alerts."""
from datetime import timedelta

from fastapi import HTTPException

from .. import events
from ..db import execute, jsonb, q_all, q_one
from ..util import add_months, as_of, month_start, new_id, not_found, pct_change, peso


def windows():
    """last2 = last 2 complete months; prior3 = the 3 months before that."""
    cur = month_start(as_of())
    return {"last2_start": add_months(cur, -2), "last2_end": cur, "prior3_start": add_months(cur, -5),
            "prior3_end": add_months(cur, -2)}


def compute_metrics(conn, customer_id):
    w = windows()
    p = {"c": customer_id, **w, "d90": as_of() - timedelta(days=90), "asof": as_of()}
    t = q_one(conn, """
        SELECT
          SUM(amount) FILTER (WHERE category='CUSTOMER_RECEIPT' AND txn_date >= %(last2_start)s AND txn_date < %(last2_end)s) AS rec_last2,
          SUM(amount) FILTER (WHERE category='CUSTOMER_RECEIPT' AND txn_date >= %(prior3_start)s AND txn_date < %(prior3_end)s) AS rec_prior3,
          SUM(amount) FILTER (WHERE direction='CREDIT' AND txn_date >= %(last2_start)s AND txn_date < %(last2_end)s) AS in_last2,
          SUM(amount) FILTER (WHERE direction='DEBIT'  AND txn_date >= %(last2_start)s AND txn_date < %(last2_end)s) AS out_last2,
          AVG(balance_after) FILTER (WHERE txn_date >= %(last2_start)s AND txn_date < %(last2_end)s) AS bal_last2,
          AVG(balance_after) FILTER (WHERE txn_date >= %(prior3_start)s AND txn_date < %(prior3_end)s) AS bal_prior3,
          COUNT(*) FILTER (WHERE category='RETURNED_CHECK' AND txn_date > %(d90)s) AS returned_checks_90d
        FROM transactions WHERE customer_id = %(c)s""", p)
    dpd = q_one(conn, """
        SELECT COALESCE(MAX(%(asof)s::date - r.due_date), 0) AS dpd
        FROM repayments r JOIN loans l ON l.loan_id = r.loan_id
        WHERE l.customer_id = %(c)s AND l.status='ACTIVE' AND r.status='OVERDUE' AND r.due_date <= %(asof)s""", p)
    util = q_one(conn, """
        SELECT MAX(outstanding / NULLIF(sanctioned_amount,0) * 100) AS u
        FROM loans WHERE customer_id=%(c)s AND status='ACTIVE' AND product_code='WORKING_CAPITAL'""", p)
    tax = q_all(conn, """
        SELECT period_label, declared_gross_sales, status FROM tax_filings
        WHERE customer_id=%(c)s AND form_code IN ('2550Q','2551Q') ORDER BY period_end DESC LIMIT 2""", p)
    rec_last2_avg = (t["rec_last2"] or 0) / 2
    rec_prior3_avg = (t["rec_prior3"] or 0) / 3
    in_last2 = t["in_last2"] or 0
    return {
        "as_of": as_of().isoformat(),
        "window_last2": f"{w['last2_start']} to {w['last2_end'] - timedelta(days=1)}",
        "window_prior3": f"{w['prior3_start']} to {w['prior3_end'] - timedelta(days=1)}",
        "avg_monthly_receipts_last2": round(rec_last2_avg, 2),
        "avg_monthly_receipts_prior3": round(rec_prior3_avg, 2),
        "inflow_change_pct": pct_change(rec_last2_avg, rec_prior3_avg),
        "tax_sales_change_pct": pct_change(tax[0]["declared_gross_sales"], tax[1]["declared_gross_sales"]) if len(tax) == 2 else None,
        "latest_tax_period": tax[0]["period_label"] if tax else None,
        "latest_tax_filing_status": tax[0]["status"] if tax else None,
        "avg_balance_last2": round(t["bal_last2"] or 0, 2),
        "avg_balance_change_pct": pct_change(t["bal_last2"] or 0, t["bal_prior3"] or 0),
        "days_past_due": int(dpd["dpd"] or 0),
        "utilisation_pct": round(util["u"], 1) if util and util["u"] is not None else None,
        "returned_checks_90d": int(t["returned_checks_90d"] or 0),
        "cash_margin_pct": round((in_last2 - (t["out_last2"] or 0)) / in_last2 * 100, 1) if in_last2 else None,
    }


def evaluate_signals(conn, metrics):
    rules = q_all(conn, "SELECT * FROM ews_rules ORDER BY rule_code")
    fired = []
    for r in rules:
        v = metrics.get(r["metric"])
        if v is None:
            continue
        if r["direction"] == "BELOW":
            level = "HIGH" if v <= r["high_threshold"] else "WATCH" if v <= r["watch_threshold"] else None
        else:
            level = "HIGH" if v >= r["high_threshold"] else "WATCH" if v >= r["watch_threshold"] else None
        if level:
            fired.append({"rule_code": r["rule_code"], "name": r["name"], "level": level, "metric": r["metric"],
                          "value": v, "watch_threshold": r["watch_threshold"], "high_threshold": r["high_threshold"],
                          "explanation": _explain(r["rule_code"], v, metrics)})
    return fired


def _explain(code, v, m):
    return {
        "INFLOW_DECLINE": f"Customer receipts averaged {peso(m['avg_monthly_receipts_last2'])}/month in the last 2 months, {v}% vs the 3 months before.",
        "TAX_SALES_DECLINE": f"Declared sales in the {m['latest_tax_period']} VAT return changed {v}% vs the previous quarter.",
        "BALANCE_DECLINE": f"Average account balance changed {v}% ({peso(m['avg_balance_last2'])} in the last 2 months).",
        "DAYS_PAST_DUE": f"A loan repayment is {v} days past due.",
        "LIMIT_UTILISATION": f"Working-capital line is {v}% used.",
        "RETURNED_CHECKS": f"{v} returned checks in the last 90 days.",
        "CASHFLOW_MARGIN": f"Operating cash margin is only {v}% in the last 2 months.",
    }[code]


def health_from_signals(metrics, signals):
    highs = [s for s in signals if s["level"] == "HIGH"]
    if metrics["days_past_due"] >= 30 or len(highs) >= 2:
        return "HIGH_ATTENTION"
    if signals:
        return "WATCH"
    return "HEALTHY"


def calculate_signals(conn, customer_id, actor, persist=True):
    cust = q_one(conn, "SELECT customer_id, business_name, health_status FROM customers WHERE customer_id=%(c)s", {"c": customer_id})
    if not cust:
        not_found("Customer", customer_id)
    metrics = compute_metrics(conn, customer_id)
    signals = evaluate_signals(conn, metrics)
    health = health_from_signals(metrics, signals)
    result = {"customer_id": customer_id, "business_name": cust["business_name"], "metrics": metrics,
              "signals": signals, "health_status": health, "previous_health_status": cust["health_status"],
              "health_changed": health != cust["health_status"]}
    if persist:
        execute(conn, """INSERT INTO signal_snapshots (customer_id, as_of, metrics, signals, health_status, created_by)
                         VALUES (%(c)s, %(d)s, %(m)s, %(s)s, %(h)s, %(by)s)""",
                {"c": customer_id, "d": as_of(), "m": jsonb(metrics), "s": jsonb(signals), "h": health, "by": actor.actor_name})
        events.emit(conn, "SIGNALS_CALCULATED", actor, customer_id=customer_id,
                    payload={"health_status": health, "signals": [s["rule_code"] + ":" + s["level"] for s in signals]})
        if health != cust["health_status"]:
            execute(conn, "UPDATE customers SET health_status=%(h)s WHERE customer_id=%(c)s", {"h": health, "c": customer_id})
            events.emit(conn, "HEALTH_STATUS_CHANGED", actor, customer_id=customer_id,
                        payload={"from": cust["health_status"], "to": health, "signals": signals})
    return result


def monitoring_run(conn, actor):
    """Recalculate every customer with an active loan. Returns who needs attention."""
    custs = q_all(conn, """SELECT DISTINCT c.customer_id FROM customers c JOIN loans l ON l.customer_id=c.customer_id
                           WHERE l.status='ACTIVE' ORDER BY c.customer_id""")
    results = [calculate_signals(conn, c["customer_id"], actor) for c in custs]
    open_alerts = {r["customer_id"] for r in q_all(conn, "SELECT customer_id FROM risk_alerts WHERE status IN ('OPEN','IN_PROGRESS')")}
    needs = [
        {"customer_id": r["customer_id"], "business_name": r["business_name"], "health_status": r["health_status"],
         "signals": [s["rule_code"] + ":" + s["level"] for s in r["signals"]], "has_open_alert": r["customer_id"] in open_alerts,
         "suggested_next_step": "Create a risk alert and RM task" if r["customer_id"] not in open_alerts else "Alert already open - update if worse"}
        for r in results if r["health_status"] != "HEALTHY"
    ]
    return {"as_of": as_of().isoformat(), "customers_checked": len(results),
            "health_changes": [{"customer_id": r["customer_id"], "from": r["previous_health_status"], "to": r["health_status"]}
                               for r in results if r["health_changed"]],
            "needs_attention": needs}


def portfolio_summary(conn):
    k = q_one(conn, """
        SELECT COUNT(DISTINCT c.customer_id) AS customers,
               COALESCE(SUM(l.outstanding),0) AS total_exposure,
               COUNT(l.loan_id) AS active_loans
        FROM customers c LEFT JOIN loans l ON l.customer_id=c.customer_id AND l.status='ACTIVE'""")
    by_health = q_all(conn, """
        SELECT c.health_status, COUNT(DISTINCT c.customer_id) AS customers, COALESCE(SUM(l.outstanding),0) AS exposure
        FROM customers c LEFT JOIN loans l ON l.customer_id=c.customer_id AND l.status='ACTIVE'
        GROUP BY c.health_status""")
    by_region = q_all(conn, """
        SELECT c.region, COUNT(DISTINCT c.customer_id) AS customers, COALESCE(SUM(l.outstanding),0) AS exposure
        FROM customers c LEFT JOIN loans l ON l.customer_id=c.customer_id AND l.status='ACTIVE'
        GROUP BY c.region ORDER BY exposure DESC""")
    by_sector = q_all(conn, """
        SELECT c.sector, COUNT(DISTINCT c.customer_id) AS customers, COALESCE(SUM(l.outstanding),0) AS exposure
        FROM customers c LEFT JOIN loans l ON l.customer_id=c.customer_id AND l.status='ACTIVE'
        GROUP BY c.sector ORDER BY exposure DESC""")
    apps = q_all(conn, "SELECT status, COUNT(*) AS n FROM applications GROUP BY status")
    counts = q_one(conn, """SELECT
        (SELECT COUNT(*) FROM risk_alerts WHERE status IN ('OPEN','IN_PROGRESS')) AS open_alerts,
        (SELECT COUNT(*) FROM rm_tasks WHERE status IN ('OPEN','IN_PROGRESS')) AS open_rm_tasks,
        (SELECT COUNT(*) FROM rm_leads WHERE status IN ('NEW','CONTACTED')) AS open_leads,
        (SELECT COUNT(*) FROM (SELECT DISTINCT customer_id FROM opportunities WHERE status='OPEN') x) AS open_opportunities,
        (SELECT COALESCE(SUM(estimated_value),0) FROM (SELECT DISTINCT ON (customer_id) estimated_value FROM opportunities
            WHERE status='OPEN' ORDER BY customer_id, confidence DESC) x) AS opportunity_value,
        (SELECT COUNT(*) FROM applications WHERE status IN ('SUBMITTED_FOR_REVIEW','UNDER_REVIEW')) AS pending_credit_reviews""")
    return {"as_of": as_of().isoformat(), **k, "by_health": by_health, "by_region": by_region, "by_sector": by_sector,
            "applications_by_status": apps, **counts}


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
def create_alert(conn, actor, customer_id, severity, summary, recommended_action, signals=None):
    cust = q_one(conn, "SELECT customer_id, health_status FROM customers WHERE customer_id=%(c)s", {"c": customer_id})
    if not cust:
        not_found("Customer", customer_id)
    if severity not in ("WATCH", "HIGH"):
        raise HTTPException(422, "severity must be WATCH or HIGH")
    if signals is None:
        signals = calculate_signals(conn, customer_id, actor, persist=False)["signals"]
    alert_id = new_id(conn, "ALERT", "risk_alerts", "alert_id")
    execute(conn, """INSERT INTO risk_alerts (alert_id, customer_id, severity, signals, summary, recommended_action, created_by)
                     VALUES (%(id)s, %(c)s, %(sev)s, %(sig)s, %(sum)s, %(rec)s, %(by)s)""",
            {"id": alert_id, "c": customer_id, "sev": severity, "sig": jsonb(signals), "sum": summary,
             "rec": recommended_action, "by": actor.actor_name})
    events.emit(conn, "RISK_ALERT_CREATED", actor, customer_id=customer_id,
                payload={"alert_id": alert_id, "severity": severity, "signals": [s.get("rule_code") for s in signals]})
    return get_alert(conn, alert_id)


def get_alert(conn, alert_id):
    a = q_one(conn, """SELECT a.*, c.business_name, c.rm_id FROM risk_alerts a JOIN customers c USING (customer_id)
                       WHERE alert_id=%(a)s""", {"a": alert_id})
    if not a:
        not_found("Alert", alert_id)
    return a


def list_alerts(conn, status=None, customer_id=None):
    return q_all(conn, """SELECT a.*, c.business_name, c.rm_id FROM risk_alerts a JOIN customers c USING (customer_id)
                          WHERE (%(s)s::text IS NULL OR a.status=%(s)s) AND (%(c)s::text IS NULL OR a.customer_id=%(c)s)
                          ORDER BY CASE a.severity WHEN 'HIGH' THEN 0 ELSE 1 END, a.created_at DESC""",
                 {"s": status, "c": customer_id})


def update_alert(conn, actor, alert_id, status, note):
    get_alert(conn, alert_id)
    if status not in ("IN_PROGRESS", "RESOLVED", "ESCALATED", "OPEN"):
        raise HTTPException(422, "status must be OPEN, IN_PROGRESS, RESOLVED or ESCALATED")
    execute(conn, """UPDATE risk_alerts SET status=%(s)s, resolution_note=COALESCE(%(n)s, resolution_note),
                     resolved_by=CASE WHEN %(s)s IN ('RESOLVED','ESCALATED') THEN %(by)s ELSE resolved_by END,
                     resolved_at=CASE WHEN %(s)s IN ('RESOLVED','ESCALATED') THEN now() ELSE resolved_at END
                     WHERE alert_id=%(a)s""", {"s": status, "n": note, "by": actor.actor_name, "a": alert_id})
    a = get_alert(conn, alert_id)
    events.emit(conn, "RISK_ALERT_UPDATED", actor, customer_id=a["customer_id"], payload={"alert_id": alert_id, "status": status, "note": note})
    return a
