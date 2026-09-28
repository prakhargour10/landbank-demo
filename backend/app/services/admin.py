"""Reference data, events, audit, webhooks and demo controls."""
import secrets
from datetime import timedelta

from fastapi import HTTPException

from .. import events
from ..db import execute, q_all, q_one
from ..util import as_of, month_start, new_id, not_found


def reference(conn, kind):
    if kind == "products":
        return q_all(conn, "SELECT * FROM products ORDER BY category, product_code")
    if kind == "ews-rules":
        return q_all(conn, "SELECT * FROM ews_rules ORDER BY rule_code")
    if kind == "document-checklist":
        return q_all(conn, "SELECT * FROM document_types ORDER BY doc_type")
    if kind == "relationship-managers":
        return q_all(conn, "SELECT * FROM relationship_managers ORDER BY rm_id")
    if kind == "event-types":
        return [{"event_type": k, "description": v} for k, v in events.EVENT_TYPES.items()]
    not_found("Reference list", kind)


def list_events(conn, since_id=0, event_type=None, customer_id=None, application_id=None, limit=100):
    return q_all(conn, """SELECT * FROM events WHERE event_id > %(s)s
                          AND (%(t)s::text IS NULL OR event_type=%(t)s) AND (%(c)s::text IS NULL OR customer_id=%(c)s)
                          AND (%(a)s::text IS NULL OR application_id=%(a)s)
                          ORDER BY event_id DESC LIMIT %(l)s""",
                 {"s": since_id, "t": event_type, "c": customer_id, "a": application_id, "l": min(int(limit), 1000)})


def list_audit(conn, actor_name=None, customer_id=None, limit=200):
    return q_all(conn, """SELECT * FROM audit_log WHERE (%(a)s::text IS NULL OR actor_name=%(a)s)
                          AND (%(c)s::text IS NULL OR customer_id=%(c)s) ORDER BY audit_id DESC LIMIT %(l)s""",
                 {"a": actor_name, "c": customer_id, "l": min(int(limit), 2000)})


def write_audit(conn, actor_type, actor_name, method, path, tool, status, customer_id, application_id, summary):
    from ..db import jsonb
    execute(conn, """INSERT INTO audit_log (actor_type, actor_name, method, path, tool_name, status_code, customer_id, application_id, request_summary)
                     VALUES (%(at)s, %(an)s, %(m)s, %(p)s, %(t)s, %(s)s, %(c)s, %(a)s, %(r)s)""",
            {"at": actor_type, "an": actor_name, "m": method, "p": path, "t": tool, "s": status, "c": customer_id,
             "a": application_id, "r": jsonb(summary or {})})


def create_webhook(conn, target_url, event_types, secret=None):
    if not target_url.startswith(("http://", "https://")):
        raise HTTPException(422, "target_url must be http(s)")
    known = set(events.EVENT_TYPES) | {"*"}
    bad = [e for e in event_types if e not in known]
    if bad:
        raise HTTPException(422, f"Unknown event types: {bad}")
    sid = new_id(conn, "WH", "webhook_subscriptions", "subscription_id")
    secret = secret or secrets.token_hex(16)
    execute(conn, """INSERT INTO webhook_subscriptions (subscription_id, target_url, event_types, secret, cursor_event_id)
                     VALUES (%(i)s, %(u)s, %(e)s, %(s)s, (SELECT COALESCE(MAX(event_id), 0) FROM events))""",
            {"i": sid, "u": target_url, "e": event_types, "s": secret})
    sub = q_one(conn, "SELECT * FROM webhook_subscriptions WHERE subscription_id=%(i)s", {"i": sid})
    sub["note"] = "Keep the secret: verify X-Landbank-Signature = HMAC-SHA256(secret, raw body). Only events after now are delivered."
    return sub


def list_webhooks(conn):
    subs = q_all(conn, "SELECT subscription_id, target_url, event_types, active, cursor_event_id, created_at FROM webhook_subscriptions ORDER BY created_at")
    for s in subs:
        s["recent_deliveries"] = q_all(conn, "SELECT event_id, status_code, error, delivered_at FROM webhook_deliveries WHERE subscription_id=%(s)s ORDER BY delivery_id DESC LIMIT 5",
                                       {"s": s["subscription_id"]})
    return subs


def delete_webhook(conn, subscription_id):
    execute(conn, "UPDATE webhook_subscriptions SET active=FALSE WHERE subscription_id=%(s)s", {"s": subscription_id})
    return {"subscription_id": subscription_id, "active": False}


def apply_stress(conn, actor, customer_id, severity="HIGH"):
    """Demo control: make a healthy customer deteriorate (last 2 months receipts drop, next due unpaid)."""
    c = q_one(conn, "SELECT customer_id, business_name FROM customers WHERE customer_id=%(c)s", {"c": customer_id})
    if not c:
        not_found("Customer", customer_id)
    drop = 0.62 if severity == "HIGH" else 0.82
    start = month_start(as_of()).replace(day=1)
    two_back = (start - timedelta(days=1)).replace(day=1)
    two_back = (two_back - timedelta(days=1)).replace(day=1)
    execute(conn, """UPDATE transactions SET amount = ROUND(amount * %(d)s, 2)
                     WHERE customer_id=%(c)s AND category='CUSTOMER_RECEIPT' AND txn_date >= %(s)s""",
            {"d": drop, "c": customer_id, "s": two_back})
    if severity == "HIGH":
        execute(conn, """UPDATE repayments SET status='OVERDUE', paid_date=NULL, amount_paid=0
                         WHERE loan_id IN (SELECT loan_id FROM loans WHERE customer_id=%(c)s AND status='ACTIVE')
                           AND due_date BETWEEN %(from)s AND %(asof)s""",
                {"c": customer_id, "from": as_of() - timedelta(days=45), "asof": as_of()})
        execute(conn, """UPDATE loans SET days_past_due = GREATEST(days_past_due, 41) WHERE customer_id=%(c)s AND status='ACTIVE'""", {"c": customer_id})
        execute(conn, """UPDATE tax_filings SET declared_gross_sales = ROUND(declared_gross_sales * 0.78, 2), status='LATE'
                         WHERE filing_id = (SELECT filing_id FROM tax_filings WHERE customer_id=%(c)s AND form_code IN ('2550Q','2551Q') ORDER BY period_end DESC LIMIT 1)""",
                {"c": customer_id})
    # recompute running balances so balance-based signals stay consistent
    execute(conn, """UPDATE transactions t SET balance_after = x.bal FROM (
                        SELECT txn_id, SUM(CASE WHEN direction='CREDIT' THEN amount ELSE -amount END)
                               OVER (ORDER BY txn_date, CASE WHEN direction='CREDIT' THEN 0 ELSE 1 END, txn_id) +
                               (SELECT balance_after + CASE WHEN direction='CREDIT' THEN -amount ELSE amount END FROM transactions
                                WHERE customer_id=%(c)s ORDER BY txn_date, txn_id LIMIT 1) AS bal
                        FROM transactions WHERE customer_id=%(c)s) x WHERE t.txn_id = x.txn_id""", {"c": customer_id})
    events.emit(conn, "DEMO_STRESS_APPLIED", actor, customer_id=customer_id, payload={"severity": severity})
    return {"customer_id": customer_id, "business_name": c["business_name"], "severity": severity,
            "next_step": "Call POST /api/v1/customers/{id}/signals (calculateEarlyWarningSignals) or run portfolio monitoring to see the effect."}
