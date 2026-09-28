"""Event log + outbound webhooks.

Every state change calls `emit()`. The event is stored in `events` (inside the caller's
transaction) and, after the transaction commits, `dispatch_pending()` posts it to every
matching webhook subscription (e.g. an AgenticOrg workflow webhook trigger).
"""
import hashlib
import hmac
import json
import logging
import threading

import httpx

from . import config
from .db import execute, get_conn, jsonb, q_all, q_one

log = logging.getLogger("landbank.events")

# Catalogue of events this service raises (also served at GET /api/v1/reference/event-types)
EVENT_TYPES = {
    "CONSENT_REQUESTED": "Agent asked the MSME for consent to read data",
    "CONSENT_GIVEN": "MSME granted consent (read-only, time-bound)",
    "CONSENT_DECLINED": "MSME declined consent",
    "ELIGIBILITY_CHECKED": "Preliminary eligibility calculated (indicative only)",
    "APPLICATION_STARTED": "New loan application created",
    "DOCUMENT_FETCHED": "Document pulled from a consented source",
    "DOCUMENT_RECEIVED": "Document uploaded by the MSME",
    "DOCUMENT_VALIDATED": "Document passed validation",
    "DOCUMENT_ISSUE_FOUND": "Document has an issue (missing pages, mismatch, stale period)",
    "DOCUMENT_REQUESTED": "Agent asked the MSME for a document",
    "DOCUMENTS_COMPLETE": "All required documents validated",
    "FINANCIAL_ANALYSIS_COMPLETED": "Financial analysis stored",
    "PRODUCT_FIT_SUGGESTED": "Product fit suggested (recommendation only)",
    "CREDIT_CASE_GENERATED": "Credit case / readiness score stored",
    "APPLICATION_SUBMITTED": "MSME submitted the application to the bank",
    "CREDIT_REVIEW_TASK_CREATED": "Application assigned to a credit officer",
    "CREDIT_CASE_OPENED": "Credit officer opened the case",
    "MORE_INFO_REQUESTED": "Credit officer asked for more information",
    "APPLICATION_SENT_BACK": "Credit officer sent the application back",
    "RECOMMENDED_APPROVAL": "Credit officer recommended approval (human decision)",
    "RECOMMENDED_DECLINE": "Credit officer recommended decline (human decision)",
    "APPLICATION_APPROVED": "Sanction authority approved",
    "APPLICATION_DECLINED": "Sanction authority declined",
    "LOAN_ACTIVATED": "Loan booked and disbursed by loan operations",
    "MONITORING_STARTED": "Customer added to portfolio monitoring",
    "SIGNALS_CALCULATED": "Early-warning signals recalculated for a customer",
    "HEALTH_STATUS_CHANGED": "Customer health status changed",
    "RISK_ALERT_CREATED": "Early-warning alert raised",
    "RISK_ALERT_UPDATED": "Alert status changed by a human",
    "RM_TASK_CREATED": "Task created in an RM work queue",
    "RM_TASK_UPDATED": "RM updated a task",
    "OPPORTUNITY_IDENTIFIED": "Evidence-backed product opportunity found",
    "RM_LEAD_CREATED": "Lead created for an RM",
    "RM_LEAD_UPDATED": "RM updated a lead",
    "DEMO_STRESS_APPLIED": "Demo: stress scenario applied to a customer",
    "DEMO_DATA_RESET": "Demo: database re-seeded",
}


def emit(conn, event_type, actor, *, customer_id=None, application_id=None, loan_id=None,
         payload=None, confidence=None):
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown event type {event_type}")
    row = q_one(
        conn,
        """INSERT INTO events (event_type, actor_type, actor_name, customer_id, application_id, loan_id, payload, confidence)
           VALUES (%(t)s, %(at)s, %(an)s, %(c)s, %(a)s, %(l)s, %(p)s, %(conf)s) RETURNING event_id""",
        {"t": event_type, "at": actor.actor_type, "an": actor.actor_name, "c": customer_id,
         "a": application_id, "l": loan_id, "p": jsonb(payload or {}), "conf": confidence},
    )
    return row["event_id"]


# ---------------------------------------------------------------------------
# Webhook dispatch (runs after the request's transaction has committed)
# ---------------------------------------------------------------------------
_lock = threading.Lock()


def _sign(secret, body: bytes):
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def dispatch_pending():
    """Deliver new events to every active subscription (each subscription keeps its own cursor)."""
    with _lock:
        try:
            with get_conn() as conn:
                for s in q_all(conn, "SELECT * FROM webhook_subscriptions WHERE active"):
                    evs = q_all(conn, "SELECT * FROM events WHERE event_id > %(id)s ORDER BY event_id LIMIT 200",
                                {"id": s["cursor_event_id"]})
                    for ev in evs:
                        if "*" in s["event_types"] or ev["event_type"] in s["event_types"]:
                            _deliver(conn, s, ev)
                        execute(conn, "UPDATE webhook_subscriptions SET cursor_event_id=%(e)s WHERE subscription_id=%(s)s",
                                {"e": ev["event_id"], "s": s["subscription_id"]})
        except Exception:  # noqa: BLE001
            log.exception("webhook dispatch failed")


def _deliver(conn, sub, ev):
    body = json.dumps(ev, default=str).encode()
    headers = {"Content-Type": "application/json", "X-Landbank-Event": ev["event_type"]}
    if sub.get("secret"):
        headers["X-Landbank-Signature"] = _sign(sub["secret"], body)
    code, err = None, None
    try:
        code = httpx.post(sub["target_url"], content=body, headers=headers, timeout=config.WEBHOOK_TIMEOUT_SECONDS).status_code
    except Exception as e:  # noqa: BLE001 - delivery failures are recorded, never raised
        err = str(e)[:500]
    execute(conn, """INSERT INTO webhook_deliveries (subscription_id, event_id, status_code, error)
                     VALUES (%(s)s, %(e)s, %(c)s, %(err)s)""",
            {"s": sub["subscription_id"], "e": ev["event_id"], "c": code, "err": err})


def dispatch_async():
    threading.Thread(target=dispatch_pending, daemon=True).start()
