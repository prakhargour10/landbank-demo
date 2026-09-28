"""RM & Growth: product opportunities, RM leads and RM tasks."""
from datetime import timedelta

from fastapi import HTTPException

from .. import events
from ..db import execute, jsonb, q_all, q_one
from ..util import as_of, new_id, not_found, peso
from .customers import get_customer
from .monitoring import calculate_signals

# Sector-specific preference order for next-best product (first product not already held wins)
SECTOR_PREFS = [
    ("export", ["TRADE_FINANCE", "WORKING_CAPITAL", "CASH_MANAGEMENT"]),
    ("trading", ["INVOICE_FINANCING", "WORKING_CAPITAL", "QRPH_MERCHANT"]),
    ("cacao", ["EQUIPMENT_FINANCING", "AGRI_INSURANCE", "WORKING_CAPITAL"]),
    ("poultry", ["AGRI_INSURANCE", "EQUIPMENT_FINANCING", "PAYROLL_SERVICE"]),
    ("vegetable", ["PAYROLL_SERVICE", "AGRI_INSURANCE", "WORKING_CAPITAL"]),
    ("fisheries", ["CASH_MANAGEMENT", "WORKING_CAPITAL", "QRPH_MERCHANT"]),
    ("food manufacturing", ["QRPH_MERCHANT", "WORKING_CAPITAL", "EQUIPMENT_FINANCING"]),
    ("bakery", ["QRPH_MERCHANT", "EQUIPMENT_FINANCING", "PAYROLL_SERVICE"]),
    ("", ["WORKING_CAPITAL", "EQUIPMENT_FINANCING", "CASH_MANAGEMENT", "PAYROLL_SERVICE", "QRPH_MERCHANT", "BUSINESS_CREDIT_CARD"]),
]


def _prefs(sector):
    s = sector.lower()
    for key, prefs in SECTOR_PREFS:
        if key and key in s:
            return prefs + [p for p in SECTOR_PREFS[-1][1] if p not in prefs]
    return SECTOR_PREFS[-1][1]


def opportunities_for(conn, customer_id, actor):
    c = get_customer(conn, customer_id)
    sig = calculate_signals(conn, customer_id, actor, persist=False)
    if sig["health_status"] != "HEALTHY":
        return {"customer_id": customer_id, "health_status": sig["health_status"], "opportunities": [],
                "note": "No growth offers while the account needs attention. Route to risk outreach (create a risk alert / RM task)."}
    held = {p["product_code"] for p in q_all(conn, "SELECT product_code FROM product_holdings WHERE customer_id=%(c)s", {"c": customer_id})}
    m = sig["metrics"]
    annual = m["avg_monthly_receipts_last2"] * 12
    out = []
    for rank, code in enumerate(_prefs(c["sector"])):
        if code in held:
            continue
        prod = q_one(conn, "SELECT * FROM products WHERE product_code=%(p)s", {"p": code})
        conf = round(max(0.6, 0.92 - rank * 0.04 - (0.03 if (m["inflow_change_pct"] or 0) < 2 else 0)), 2)
        value = round(min(prod["max_amount"] or annual * 0.15, annual * 0.15), -4) if prod["is_credit"] else round(annual * 0.004, -3)
        reasons = [f"Customer receipts {m['inflow_change_pct']:+}% (last 2 vs prior 3 months).",
                   "No repayment delays; no early-warning signals.",
                   f"Does not hold {prod['name']} today (holds: {', '.join(sorted(held))})."]
        oid = q_one(conn, "SELECT opportunity_id FROM opportunities WHERE customer_id=%(c)s AND product_code=%(p)s AND status IN ('OPEN','LEAD_CREATED')",
                    {"c": customer_id, "p": code})
        if oid:
            opp_id = oid["opportunity_id"]
            execute(conn, "UPDATE opportunities SET confidence=%(cf)s, estimated_value=%(v)s, reasons=%(r)s WHERE opportunity_id=%(o)s",
                    {"cf": conf, "v": value, "r": jsonb(reasons), "o": opp_id})
        else:
            opp_id = new_id(conn, "OPP", "opportunities", "opportunity_id")
            execute(conn, """INSERT INTO opportunities (opportunity_id, customer_id, product_code, confidence, estimated_value, reasons)
                             VALUES (%(o)s, %(c)s, %(p)s, %(cf)s, %(v)s, %(r)s)""",
                    {"o": opp_id, "c": customer_id, "p": code, "cf": conf, "v": value, "r": jsonb(reasons)})
            events.emit(conn, "OPPORTUNITY_IDENTIFIED", actor, customer_id=customer_id,
                        payload={"opportunity_id": opp_id, "product_code": code, "confidence": conf}, confidence=conf)
        out.append({"opportunity_id": opp_id, "product_code": code, "product_name": prod["name"], "confidence": conf,
                    "estimated_value": value, "value_basis": "facility size" if prod["is_credit"] else "annual fee/float income",
                    "reasons": reasons})
        if len(out) == 2:
            break
    return {"customer_id": customer_id, "business_name": c["business_name"], "health_status": "HEALTHY", "opportunities": out}


def all_opportunities(conn, actor):
    custs = q_all(conn, "SELECT customer_id FROM customers ORDER BY customer_id")
    res = []
    for cu in custs:
        r = opportunities_for(conn, cu["customer_id"], actor)
        for o in r["opportunities"][:1]:  # best opportunity per customer
            res.append({"customer_id": cu["customer_id"], "business_name": r.get("business_name"), **o})
    res.sort(key=lambda x: -x["confidence"])
    return {"count": len(res), "total_estimated_value": round(sum(o["estimated_value"] for o in res), 2), "opportunities": res}


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------
def create_lead(conn, actor, customer_id, product_code, reason, opportunity_id=None):
    c = get_customer(conn, customer_id)
    if c["health_status"] == "HIGH_ATTENTION" and q_one(conn, "SELECT is_credit FROM products WHERE product_code=%(p)s", {"p": product_code})["is_credit"]:
        raise HTTPException(409, "Credit offers are blocked for HIGH_ATTENTION customers. Create a risk alert / RM task instead.")
    lead_id = new_id(conn, "LEAD", "rm_leads", "lead_id")
    execute(conn, """INSERT INTO rm_leads (lead_id, customer_id, rm_id, product_code, opportunity_id, reason, created_by)
                     VALUES (%(l)s, %(c)s, %(rm)s, %(p)s, %(o)s, %(r)s, %(by)s)""",
            {"l": lead_id, "c": customer_id, "rm": c["rm_id"], "p": product_code, "o": opportunity_id, "r": reason, "by": actor.actor_name})
    if opportunity_id:
        execute(conn, "UPDATE opportunities SET status='LEAD_CREATED' WHERE opportunity_id=%(o)s", {"o": opportunity_id})
    events.emit(conn, "RM_LEAD_CREATED", actor, customer_id=customer_id,
                payload={"lead_id": lead_id, "product_code": product_code, "rm_id": c["rm_id"], "opportunity_id": opportunity_id})
    return get_lead(conn, lead_id)


def get_lead(conn, lead_id):
    r = q_one(conn, """SELECT l.*, c.business_name, p.name AS product_name, rm.name AS rm_name FROM rm_leads l
                       JOIN customers c USING (customer_id) JOIN products p USING (product_code) JOIN relationship_managers rm ON rm.rm_id=l.rm_id
                       WHERE lead_id=%(l)s""", {"l": lead_id})
    if not r:
        not_found("Lead", lead_id)
    return r


def list_leads(conn, rm_id=None, status=None):
    return q_all(conn, """SELECT l.*, c.business_name, p.name AS product_name, rm.name AS rm_name FROM rm_leads l
                          JOIN customers c USING (customer_id) JOIN products p USING (product_code) JOIN relationship_managers rm ON rm.rm_id=l.rm_id
                          WHERE (%(rm)s::text IS NULL OR l.rm_id=%(rm)s) AND (%(s)s::text IS NULL OR l.status=%(s)s)
                          ORDER BY l.created_at DESC""", {"rm": rm_id, "s": status})


def update_lead(conn, actor, lead_id, status, note):
    get_lead(conn, lead_id)
    if status not in ("NEW", "CONTACTED", "WON", "LOST", "LATER"):
        raise HTTPException(422, "status must be NEW, CONTACTED, WON, LOST or LATER")
    execute(conn, "UPDATE rm_leads SET status=%(s)s, outcome_note=COALESCE(%(n)s, outcome_note), updated_at=now() WHERE lead_id=%(l)s",
            {"s": status, "n": note, "l": lead_id})
    lead = get_lead(conn, lead_id)
    events.emit(conn, "RM_LEAD_UPDATED", actor, customer_id=lead["customer_id"], payload={"lead_id": lead_id, "status": status, "note": note})
    return lead


# ---------------------------------------------------------------------------
# RM tasks
# ---------------------------------------------------------------------------
def create_task(conn, actor, customer_id, task_type, title, details, priority="HIGH", due_in_days=2, related_alert_id=None):
    c = get_customer(conn, customer_id)
    if task_type not in ("RISK_OUTREACH", "DOCUMENT_FOLLOW_UP", "GROWTH_CONVERSATION", "OTHER"):
        raise HTTPException(422, "task_type must be RISK_OUTREACH, DOCUMENT_FOLLOW_UP, GROWTH_CONVERSATION or OTHER")
    task_id = new_id(conn, "TASK", "rm_tasks", "task_id")
    execute(conn, """INSERT INTO rm_tasks (task_id, customer_id, rm_id, task_type, title, details, priority, due_date, related_alert_id, created_by)
                     VALUES (%(t)s, %(c)s, %(rm)s, %(ty)s, %(ti)s, %(d)s, %(p)s, %(due)s, %(al)s, %(by)s)""",
            {"t": task_id, "c": customer_id, "rm": c["rm_id"], "ty": task_type, "ti": title, "d": details, "p": priority,
             "due": as_of() + timedelta(days=int(due_in_days)), "al": related_alert_id, "by": actor.actor_name})
    if related_alert_id:
        execute(conn, "UPDATE risk_alerts SET status='IN_PROGRESS' WHERE alert_id=%(a)s AND status='OPEN'", {"a": related_alert_id})
    events.emit(conn, "RM_TASK_CREATED", actor, customer_id=customer_id,
                payload={"task_id": task_id, "task_type": task_type, "rm_id": c["rm_id"], "priority": priority, "related_alert_id": related_alert_id})
    return get_task(conn, task_id)


def get_task(conn, task_id):
    r = q_one(conn, """SELECT t.*, c.business_name, c.health_status, rm.name AS rm_name FROM rm_tasks t JOIN customers c USING (customer_id)
                       JOIN relationship_managers rm ON rm.rm_id=t.rm_id WHERE task_id=%(t)s""", {"t": task_id})
    if not r:
        not_found("Task", task_id)
    return r


def list_tasks(conn, rm_id=None, status=None):
    return q_all(conn, """SELECT t.*, c.business_name, c.health_status, rm.name AS rm_name FROM rm_tasks t JOIN customers c USING (customer_id)
                          JOIN relationship_managers rm ON rm.rm_id=t.rm_id
                          WHERE (%(rm)s::text IS NULL OR t.rm_id=%(rm)s) AND (%(s)s::text IS NULL OR t.status=%(s)s)
                          ORDER BY CASE t.priority WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END, t.due_date""",
                 {"rm": rm_id, "s": status})


def rm_work_queue(conn, rm_id=None):
    tasks = list_tasks(conn, rm_id)
    leads = list_leads(conn, rm_id)
    return {"rm_id": rm_id, "open_tasks": [t for t in tasks if t["status"] in ("OPEN", "IN_PROGRESS")],
            "open_leads": [l for l in leads if l["status"] in ("NEW", "CONTACTED")],
            "completed_tasks": [t for t in tasks if t["status"] == "DONE"][:20]}


def update_task(conn, actor, task_id, status, note):
    get_task(conn, task_id)
    if status not in ("OPEN", "IN_PROGRESS", "DONE", "CANCELLED"):
        raise HTTPException(422, "status must be OPEN, IN_PROGRESS, DONE or CANCELLED")
    execute(conn, "UPDATE rm_tasks SET status=%(s)s, outcome_note=COALESCE(%(n)s, outcome_note), updated_at=now() WHERE task_id=%(t)s",
            {"s": status, "n": note, "t": task_id})
    t = get_task(conn, task_id)
    events.emit(conn, "RM_TASK_UPDATED", actor, customer_id=t["customer_id"], payload={"task_id": task_id, "status": status, "note": note})
    return t
