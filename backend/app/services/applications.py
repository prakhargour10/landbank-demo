"""Consent, applications, documents, submission and human decisions."""
import os
from datetime import timedelta

from fastapi import HTTPException

from .. import config, events
from ..db import execute, jsonb, q_all, q_one
from ..util import as_of, new_id, not_found, peso
from .customers import get_customer

REQUIRED_DOCS = ["BUSINESS_REGISTRATION", "MAYORS_PERMIT", "BIR_COR", "BANK_STATEMENTS_12M", "VAT_RETURNS",
                 "ITR_ANNUAL", "AUDITED_FS", "CREDIT_REPORT"]
FETCHABLE = {  # doc_type -> consent scope needed
    "BUSINESS_REGISTRATION": "BUSINESS_REGISTRATION",
    "BANK_STATEMENTS_12M": "BANK_TRANSACTIONS",
    "VAT_RETURNS": "TAX_FILINGS",
    "CREDIT_REPORT": "CREDIT_REPORT",
}
ALL_SCOPES = ["BANK_TRANSACTIONS", "TAX_FILINGS", "CREDIT_REPORT", "BUSINESS_REGISTRATION"]
MISMATCH_TOLERANCE_PCT = 15.0


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------
def request_consent(conn, actor, customer_id, purpose, scopes=None, application_id=None):
    get_customer(conn, customer_id)
    scopes = scopes or ALL_SCOPES
    bad = [s for s in scopes if s not in ALL_SCOPES]
    if bad:
        raise HTTPException(422, f"Unknown scopes {bad}. Allowed: {ALL_SCOPES}")
    cid = new_id(conn, "CNS", "consents", "consent_id")
    execute(conn, """INSERT INTO consents (consent_id, customer_id, purpose, data_scopes, status, requested_by)
                     VALUES (%(id)s, %(c)s, %(p)s, %(s)s, 'REQUESTED', %(by)s)""",
            {"id": cid, "c": customer_id, "p": purpose, "s": scopes, "by": actor.actor_name})
    if application_id:
        execute(conn, "UPDATE applications SET consent_id=%(cid)s, updated_at=now() WHERE application_id=%(a)s AND customer_id=%(c)s",
                {"cid": cid, "a": application_id, "c": customer_id})
    events.emit(conn, "CONSENT_REQUESTED", actor, customer_id=customer_id, application_id=application_id,
                payload={"consent_id": cid, "scopes": scopes, "purpose": purpose})
    return get_consent(conn, cid)


def get_consent(conn, consent_id):
    c = q_one(conn, "SELECT * FROM consents WHERE consent_id=%(c)s", {"c": consent_id})
    if not c:
        not_found("Consent", consent_id)
    c["message_to_customer"] = ("LANDBANK will read the data listed in data_scopes, read-only, for the stated purpose, "
                                "for 90 days. We will never ask for your password, PIN or OTP.")
    return c


def decide_consent(conn, actor, consent_id, grant: bool):
    c = get_consent(conn, consent_id)
    if c["status"] != "REQUESTED":
        raise HTTPException(409, f"Consent is already {c['status']}")
    execute(conn, """UPDATE consents SET status=%(s)s, decided_at=now(),
                     expires_at=CASE WHEN %(s)s='GRANTED' THEN now() + interval '90 days' ELSE NULL END
                     WHERE consent_id=%(c)s""", {"s": "GRANTED" if grant else "DECLINED", "c": consent_id})
    app = q_one(conn, "SELECT application_id FROM applications WHERE consent_id=%(c)s", {"c": consent_id})
    events.emit(conn, "CONSENT_GIVEN" if grant else "CONSENT_DECLINED", actor, customer_id=c["customer_id"],
                application_id=app["application_id"] if app else None, payload={"consent_id": consent_id})
    return get_consent(conn, consent_id)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
def create_application(conn, actor, customer_id, product_code, amount, tenure_months, purpose):
    get_customer(conn, customer_id)
    p = q_one(conn, "SELECT * FROM products WHERE product_code=%(p)s AND is_credit", {"p": product_code})
    if not p:
        raise HTTPException(422, f"{product_code} is not a credit product")
    if p["min_amount"] and amount < p["min_amount"] or p["max_amount"] and amount > p["max_amount"]:
        raise HTTPException(422, f"Amount must be between {peso(p['min_amount'])} and {peso(p['max_amount'])} for {p['name']}")
    year = as_of().year
    app_id = new_id(conn, f"APP-{year}", "applications", "application_id")
    execute(conn, """INSERT INTO applications (application_id, customer_id, product_code, amount_requested, tenure_months, purpose, status)
                     VALUES (%(id)s, %(c)s, %(p)s, %(a)s, %(t)s, %(pu)s, 'DRAFT')""",
            {"id": app_id, "c": customer_id, "p": product_code, "a": amount, "t": tenure_months, "pu": purpose})
    events.emit(conn, "APPLICATION_STARTED", actor, customer_id=customer_id, application_id=app_id,
                payload={"product_code": product_code, "amount": amount, "tenure_months": tenure_months, "purpose": purpose})
    return get_application(conn, app_id)


def _set_status(conn, app_id, status):
    execute(conn, "UPDATE applications SET status=%(s)s, updated_at=now() WHERE application_id=%(a)s", {"s": status, "a": app_id})


def get_application(conn, application_id):
    a = q_one(conn, """SELECT a.*, c.business_name, c.owner_name, c.rm_id, p.name AS product_name
                       FROM applications a JOIN customers c USING (customer_id) JOIN products p USING (product_code)
                       WHERE application_id=%(a)s""", {"a": application_id})
    if not a:
        not_found("Application", application_id)
    a["consent"] = get_consent(conn, a["consent_id"]) if a["consent_id"] else None
    a["documents"] = list_documents(conn, application_id)
    a["latest_financial_analysis"] = q_one(conn, "SELECT analysis_id, confidence, created_at FROM financial_analyses WHERE application_id=%(a)s ORDER BY created_at DESC LIMIT 1", {"a": application_id})
    a["latest_credit_case"] = q_one(conn, "SELECT case_id, readiness_score, confidence, created_at FROM credit_cases WHERE application_id=%(a)s ORDER BY created_at DESC LIMIT 1", {"a": application_id})
    a["timeline"] = q_all(conn, "SELECT event_id, event_type, occurred_at, actor_type, actor_name, payload FROM events WHERE application_id=%(a)s ORDER BY event_id", {"a": application_id})
    return a


def list_applications(conn, status=None, customer_id=None):
    return q_all(conn, """SELECT a.application_id, a.customer_id, c.business_name, a.product_code, p.name AS product_name,
                                 a.amount_requested, a.tenure_months, a.status, a.assigned_officer, a.created_at, a.updated_at,
                                 (SELECT readiness_score FROM credit_cases cc WHERE cc.application_id=a.application_id ORDER BY created_at DESC LIMIT 1) AS readiness_score
                          FROM applications a JOIN customers c USING (customer_id) JOIN products p USING (product_code)
                          WHERE (%(s)s::text IS NULL OR a.status=%(s)s) AND (%(c)s::text IS NULL OR a.customer_id=%(c)s)
                          ORDER BY a.updated_at DESC""", {"s": status, "c": customer_id})


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
def list_documents(conn, application_id):
    docs = q_all(conn, """SELECT d.document_id, d.doc_type, t.name AS doc_name, d.source, d.status, d.file_name,
                                 d.pages_expected, d.pages_received, d.issues, d.requested_reason, d.received_at, d.validated_at
                          FROM documents d JOIN document_types t USING (doc_type)
                          WHERE application_id=%(a)s ORDER BY array_position(%(order)s, d.doc_type::text)""",
                 {"a": application_id, "order": REQUIRED_DOCS})
    have = {d["doc_type"] for d in docs}
    for dt in REQUIRED_DOCS:
        if dt not in have:
            t = q_one(conn, "SELECT name FROM document_types WHERE doc_type=%(d)s", {"d": dt})
            docs.append({"document_id": None, "doc_type": dt, "doc_name": t["name"], "status": "NOT_PROVIDED",
                         "source": None, "issues": [], "file_name": None})
    return docs


def _upsert_doc(conn, app, doc_type, source, status, file_name=None, pages=None, reason=None):
    existing = q_one(conn, "SELECT document_id FROM documents WHERE application_id=%(a)s AND doc_type=%(d)s",
                     {"a": app["application_id"], "d": doc_type})
    pages_expected = 8 if doc_type == "AUDITED_FS" else None
    if existing:
        execute(conn, """UPDATE documents SET source=%(src)s, status=%(st)s, file_name=COALESCE(%(f)s, file_name),
                         pages_expected=%(pe)s, pages_received=COALESCE(%(pr)s, pages_received),
                         issues='[]'::jsonb, requested_reason=%(r)s,
                         received_at=CASE WHEN %(st)s='RECEIVED' THEN now() ELSE received_at END, validated_at=NULL
                         WHERE document_id=%(id)s""",
                {"src": source, "st": status, "f": file_name, "pe": pages_expected, "pr": pages, "r": reason, "id": existing["document_id"]})
        return existing["document_id"]
    doc_id = new_id(conn, "DOC", "documents", "document_id")
    execute(conn, """INSERT INTO documents (document_id, application_id, customer_id, doc_type, source, status, file_name,
                     pages_expected, pages_received, requested_reason, received_at)
                     VALUES (%(id)s, %(a)s, %(c)s, %(d)s, %(src)s, %(st)s, %(f)s, %(pe)s, %(pr)s, %(r)s,
                             CASE WHEN %(st)s='RECEIVED' THEN now() ELSE NULL END)""",
            {"id": doc_id, "a": app["application_id"], "c": app["customer_id"], "d": doc_type, "src": source, "st": status,
             "f": file_name, "pe": pages_expected, "pr": pages, "r": reason})
    return doc_id


def fetch_documents(conn, actor, application_id):
    """Pull documents from consented sources (bank data, BIR, CIC, registry)."""
    app = get_application(conn, application_id)
    consent = app["consent"]
    if not consent or consent["status"] != "GRANTED":
        raise HTTPException(409, "Consent not granted. Call request_consent and wait for the MSME to grant it.")
    fetched = []
    for doc_type, scope in FETCHABLE.items():
        if scope not in consent["data_scopes"]:
            continue
        doc_id = _upsert_doc(conn, app, doc_type, "CONSENT_FETCH", "RECEIVED", file_name=f"{app['customer_id']}_{doc_type}.pdf")
        events.emit(conn, "DOCUMENT_FETCHED", actor, customer_id=app["customer_id"], application_id=application_id,
                    payload={"document_id": doc_id, "doc_type": doc_type, "consent_id": consent["consent_id"]})
        fetched.append(doc_type)
    if app["status"] == "DRAFT":
        _set_status(conn, application_id, "WAITING_FOR_DOCUMENTS")
    return {"application_id": application_id, "fetched": fetched,
            "still_needed_from_msme": [d["doc_type"] for d in list_documents(conn, application_id) if d["status"] in ("NOT_PROVIDED", "REQUESTED")]}


def request_document(conn, actor, application_id, doc_type, reason):
    app = get_application(conn, application_id)
    if doc_type not in REQUIRED_DOCS:
        raise HTTPException(422, f"Unknown doc_type. Use one of {REQUIRED_DOCS}")
    doc_id = _upsert_doc(conn, app, doc_type, "UPLOAD", "REQUESTED", reason=reason)
    if app["status"] not in ("WAITING_FOR_DOCUMENTS", "MORE_INFO_REQUESTED"):
        _set_status(conn, application_id, "WAITING_FOR_DOCUMENTS")
    events.emit(conn, "DOCUMENT_REQUESTED", actor, customer_id=app["customer_id"], application_id=application_id,
                payload={"document_id": doc_id, "doc_type": doc_type, "reason": reason})
    return {"document_id": doc_id, "doc_type": doc_type, "status": "REQUESTED", "reason": reason}


def upload_document(conn, actor, application_id, doc_type, filename, content: bytes, pages=None):
    app = get_application(conn, application_id)
    if doc_type not in REQUIRED_DOCS:
        raise HTTPException(422, f"Unknown doc_type. Use one of {REQUIRED_DOCS}")
    os.makedirs(config.UPLOAD_DIR, exist_ok=True)
    safe = f"{application_id}_{doc_type}_{os.path.basename(filename or 'upload.pdf')}".replace(" ", "_")
    with open(os.path.join(config.UPLOAD_DIR, safe), "wb") as fh:
        fh.write(content)
    if pages is None and doc_type == "AUDITED_FS":
        pages = 8
    doc_id = _upsert_doc(conn, app, doc_type, "UPLOAD", "RECEIVED", file_name=safe, pages=pages)
    events.emit(conn, "DOCUMENT_RECEIVED", actor, customer_id=app["customer_id"], application_id=application_id,
                payload={"document_id": doc_id, "doc_type": doc_type, "file_name": safe})
    return {"document_id": doc_id, "doc_type": doc_type, "status": "RECEIVED"}


def document_extract(conn, doc):
    """Structured values 'read' from a document. Derived from the synthetic source data so every screen agrees."""
    cid, dt = doc["customer_id"], doc["doc_type"]
    if dt == "BANK_STATEMENTS_12M":
        r = q_one(conn, """SELECT MIN(txn_date) AS period_start, MAX(txn_date) AS period_end, COUNT(*) AS transactions,
                                  SUM(amount) FILTER (WHERE direction='CREDIT') AS total_credits,
                                  SUM(amount) FILTER (WHERE direction='DEBIT') AS total_debits,
                                  SUM(amount) FILTER (WHERE category='CUSTOMER_RECEIPT') AS customer_receipts
                           FROM transactions WHERE customer_id=%(c)s AND txn_date >= %(s)s AND txn_date < %(e)s""",
                  {"c": cid, "s": as_of().replace(day=1) - timedelta(days=365), "e": as_of().replace(day=1)})
        return r
    if dt == "VAT_RETURNS":
        return {"filings": q_all(conn, """SELECT form_code, period_label, declared_gross_sales, tax_due, status, filed_on
                                          FROM tax_filings WHERE customer_id=%(c)s AND form_code IN ('2550Q','2551Q')
                                          ORDER BY period_end""", {"c": cid})}
    if dt == "ITR_ANNUAL":
        return q_one(conn, "SELECT form_code, period_label, declared_gross_sales, tax_due, filed_on FROM tax_filings WHERE customer_id=%(c)s AND form_code IN ('1701','1702') ORDER BY period_end DESC LIMIT 1", {"c": cid})
    if dt == "CREDIT_REPORT":
        return q_one(conn, "SELECT bureau, score, score_band, active_facilities, total_outstanding, max_dpd_12m, report_date FROM credit_reports WHERE customer_id=%(c)s", {"c": cid})
    if dt == "BUSINESS_REGISTRATION":
        return q_one(conn, "SELECT business_name, legal_form, registration_body, registration_no, business_start FROM customers WHERE customer_id=%(c)s", {"c": cid})
    if dt == "BIR_COR":
        return q_one(conn, "SELECT business_name, tin, CASE WHEN EXISTS (SELECT 1 FROM tax_filings t WHERE t.customer_id=c.customer_id AND form_code='2550Q') THEN 'VAT' ELSE 'NON-VAT' END AS tax_type FROM customers c WHERE customer_id=%(c)s", {"c": cid})
    if dt == "MAYORS_PERMIT":
        return q_one(conn, "SELECT business_name, city, '2026' AS permit_year, 'VALID' AS permit_status FROM customers WHERE customer_id=%(c)s", {"c": cid})
    if dt == "AUDITED_FS":
        itr = q_one(conn, "SELECT declared_gross_sales FROM tax_filings WHERE customer_id=%(c)s AND form_code IN ('1701','1702') ORDER BY period_end DESC LIMIT 1", {"c": cid})
        sales = itr["declared_gross_sales"] if itr else 0
        return {"fiscal_year": "FY2025", "revenue": sales, "net_income": round(sales * 0.08, 2), "total_assets": round(sales * 0.55, 2),
                "total_liabilities": round(sales * 0.25, 2), "pages_expected": doc.get("pages_expected"), "pages_received": doc.get("pages_received")}
    return {}


def validate_documents(conn, actor, application_id):
    app = get_application(conn, application_id)
    results, blocking = [], False
    bank = None
    for d in list_documents(conn, application_id):
        if d["status"] in ("NOT_PROVIDED", "REQUESTED"):
            blocking = True
            results.append({"doc_type": d["doc_type"], "status": d["status"], "issues": [
                {"severity": "BLOCKING", "code": "MISSING", "message": f"{d['doc_name']} has not been provided."}]})
            continue
        full = q_one(conn, "SELECT * FROM documents WHERE document_id=%(d)s", {"d": d["document_id"]})
        issues = []
        extracted = document_extract(conn, full)
        if full["pages_expected"] and (full["pages_received"] or 0) < full["pages_expected"]:
            issues.append({"severity": "BLOCKING", "code": "MISSING_PAGES",
                           "message": f"{d['doc_name']}: only {full['pages_received']} of {full['pages_expected']} pages received."})
        if d["doc_type"] == "BANK_STATEMENTS_12M":
            bank = extracted
        results.append({"doc_type": d["doc_type"], "document_id": d["document_id"], "issues": issues, "extracted": extracted})

    # Cross-check declared sales (BIR) against actual bank receipts.
    comparison = None
    vat = next((r for r in results if r["doc_type"] == "VAT_RETURNS" and "extracted" in r), None)
    if vat and bank and bank.get("customer_receipts"):
        filings = vat["extracted"]["filings"][-4:]
        declared = sum(f["declared_gross_sales"] for f in filings)
        start_q = q_one(conn, "SELECT MIN(period_start) AS s, MAX(period_end) AS e FROM tax_filings WHERE customer_id=%(c)s AND period_label = ANY(%(l)s)",
                        {"c": app["customer_id"], "l": [f["period_label"] for f in filings]})
        rec = q_one(conn, "SELECT SUM(amount) AS r FROM transactions WHERE customer_id=%(c)s AND category='CUSTOMER_RECEIPT' AND txn_date BETWEEN %(s)s AND %(e)s",
                    {"c": app["customer_id"], "s": max(start_q["s"], bank["period_start"]), "e": start_q["e"]})
        months_bank = q_one(conn, "SELECT COUNT(DISTINCT date_trunc('month', txn_date)) AS m FROM transactions WHERE customer_id=%(c)s AND category='CUSTOMER_RECEIPT' AND txn_date BETWEEN %(s)s AND %(e)s",
                            {"c": app["customer_id"], "s": max(start_q["s"], bank["period_start"]), "e": start_q["e"]})
        declared_same_period = declared * months_bank["m"] / 12
        gap = round((declared_same_period - (rec["r"] or 0)) / (rec["r"] or 1) * 100, 1)
        comparison = {"declared_sales_same_period": round(declared_same_period, 2), "bank_customer_receipts": rec["r"],
                      "months_compared": months_bank["m"], "gap_pct": gap, "tolerance_pct": MISMATCH_TOLERANCE_PCT}
        if abs(gap) > MISMATCH_TOLERANCE_PCT:
            vat["issues"].append({"severity": "WARNING", "code": "SALES_MISMATCH",
                                  "message": f"Declared sales in BIR VAT returns are {gap}% {'higher' if gap > 0 else 'lower'} than customer receipts in bank statements for the same months."})

    for r in results:
        if "document_id" not in r:
            continue
        status = "ISSUE_FOUND" if r["issues"] else "VALIDATED"
        if any(i["severity"] == "BLOCKING" for i in r["issues"]):
            blocking = True
        execute(conn, """UPDATE documents SET status=%(s)s, issues=%(i)s, extracted=%(x)s, validated_at=now() WHERE document_id=%(d)s""",
                {"s": status, "i": jsonb(r["issues"]), "x": jsonb(r.get("extracted") or {}), "d": r["document_id"]})
        r["status"] = status
        events.emit(conn, "DOCUMENT_ISSUE_FOUND" if r["issues"] else "DOCUMENT_VALIDATED", actor,
                    customer_id=app["customer_id"], application_id=application_id,
                    payload={"document_id": r["document_id"], "doc_type": r["doc_type"], "issues": r["issues"]})
    complete = not blocking
    if complete and app["status"] in ("DRAFT", "WAITING_FOR_DOCUMENTS", "MORE_INFO_REQUESTED", "DOCUMENTS_COMPLETE"):
        _set_status(conn, application_id, "DOCUMENTS_COMPLETE")
        events.emit(conn, "DOCUMENTS_COMPLETE", actor, customer_id=app["customer_id"], application_id=application_id,
                    payload={"warnings": [i for r in results for i in r["issues"] if i["severity"] == "WARNING"]})
    elif not complete and app["status"] in ("DRAFT", "DOCUMENTS_COMPLETE"):
        _set_status(conn, application_id, "WAITING_FOR_DOCUMENTS")
    for r in results:
        r.pop("extracted", None)
    return {"application_id": application_id, "documents_complete": complete, "sales_cross_check": comparison,
            "results": results,
            "plain_english_summary": _doc_summary(results, comparison, complete)}


def _doc_summary(results, comparison, complete):
    msgs = [i["message"] for r in results for i in r["issues"]]
    if complete and not msgs:
        return "All required documents are present and consistent."
    if complete:
        return "All required documents are present. Please note: " + " ".join(msgs)
    return "Some items need the MSME's attention: " + " ".join(msgs)


# ---------------------------------------------------------------------------
# Submission, human review, activation
# ---------------------------------------------------------------------------
def submit_application(conn, actor, application_id):
    app = get_application(conn, application_id)
    if app["status"] not in ("CREDIT_CASE_READY", "MORE_INFO_REQUESTED", "SENT_BACK"):
        raise HTTPException(409, f"Application is {app['status']}; a credit case must be generated before submission.")
    officer = "Maria Santos, Credit Officer"
    execute(conn, """UPDATE applications SET status='SUBMITTED_FOR_REVIEW', submitted_at=now(), assigned_officer=%(o)s, updated_at=now()
                     WHERE application_id=%(a)s""", {"o": officer, "a": application_id})
    events.emit(conn, "APPLICATION_SUBMITTED", actor, customer_id=app["customer_id"], application_id=application_id)
    events.emit(conn, "CREDIT_REVIEW_TASK_CREATED", actor, customer_id=app["customer_id"], application_id=application_id,
                payload={"assigned_officer": officer})
    return get_application(conn, application_id)


def open_case(conn, actor, application_id):
    app = get_application(conn, application_id)
    if app["status"] == "SUBMITTED_FOR_REVIEW":
        _set_status(conn, application_id, "UNDER_REVIEW")
        events.emit(conn, "CREDIT_CASE_OPENED", actor, customer_id=app["customer_id"], application_id=application_id)
    return get_application(conn, application_id)


DECISIONS = {
    "REQUEST_MORE_INFO": ("MORE_INFO_REQUESTED", "MORE_INFO_REQUESTED"),
    "SEND_BACK": ("SENT_BACK", "APPLICATION_SENT_BACK"),
    "RECOMMEND_APPROVAL": ("RECOMMENDED_APPROVAL", "RECOMMENDED_APPROVAL"),
    "RECOMMEND_DECLINE": ("RECOMMENDED_DECLINE", "RECOMMENDED_DECLINE"),
    "APPROVE": ("APPROVED", "APPLICATION_APPROVED"),
    "DECLINE": ("DECLINED", "APPLICATION_DECLINED"),
}


def record_decision(conn, actor, application_id, decision, reason):
    """HUMAN ONLY (enforced by the router's role check)."""
    app = get_application(conn, application_id)
    if decision not in DECISIONS:
        raise HTTPException(422, f"decision must be one of {list(DECISIONS)}")
    allowed_from = {"REQUEST_MORE_INFO": ("SUBMITTED_FOR_REVIEW", "UNDER_REVIEW"), "SEND_BACK": ("SUBMITTED_FOR_REVIEW", "UNDER_REVIEW"),
                    "RECOMMEND_APPROVAL": ("SUBMITTED_FOR_REVIEW", "UNDER_REVIEW"), "RECOMMEND_DECLINE": ("SUBMITTED_FOR_REVIEW", "UNDER_REVIEW"),
                    "APPROVE": ("RECOMMENDED_APPROVAL",), "DECLINE": ("RECOMMENDED_DECLINE", "RECOMMENDED_APPROVAL")}[decision]
    if app["status"] not in allowed_from:
        raise HTTPException(409, f"Cannot {decision} when application is {app['status']}")
    status, event = DECISIONS[decision]
    execute(conn, """UPDATE applications SET status=%(s)s, decision=%(d)s, decision_by=%(by)s, decision_reason=%(r)s,
                     decided_at=now(), updated_at=now() WHERE application_id=%(a)s""",
            {"s": status, "d": decision, "by": actor.actor_name, "r": reason, "a": application_id})
    events.emit(conn, event, actor, customer_id=app["customer_id"], application_id=application_id,
                payload={"decision": decision, "reason": reason, "decided_by": actor.actor_name})
    return get_application(conn, application_id)


def activate_loan(conn, actor, application_id, interest_rate_pct=None):
    app = get_application(conn, application_id)
    if app["status"] != "APPROVED":
        raise HTTPException(409, "Only APPROVED applications can be activated.")
    rate = interest_rate_pct or q_one(conn, "SELECT indicative_rate_pct FROM products WHERE product_code=%(p)s", {"p": app["product_code"]})["indicative_rate_pct"]
    r = rate / 100 / 12
    n = app["tenure_months"]
    amort = round(app["amount_requested"] * r / (1 - (1 + r) ** -n), 2)
    loan_id = f"LN-{app['customer_id'][-4:]}-{application_id[-4:]}"
    start = as_of()
    execute(conn, """INSERT INTO loans (loan_id, customer_id, product_code, sanctioned_amount, outstanding, interest_rate_pct, tenure_months,
                     monthly_amortization, disbursed_on, maturity_date, days_past_due, status, application_id)
                     VALUES (%(l)s, %(c)s, %(p)s, %(a)s, %(a)s, %(r)s, %(n)s, %(am)s, %(d)s, %(m)s, 0, 'ACTIVE', %(app)s)""",
            {"l": loan_id, "c": app["customer_id"], "p": app["product_code"], "a": app["amount_requested"], "r": rate, "n": n,
             "am": amort, "d": start, "m": start + timedelta(days=30 * n), "app": application_id})
    execute(conn, "INSERT INTO repayments (loan_id, due_date, amount_due, status) VALUES (%(l)s, %(d)s, %(a)s, 'UPCOMING')",
            {"l": loan_id, "d": start + timedelta(days=30), "a": amort})
    execute(conn, """INSERT INTO product_holdings (customer_id, product_code, since) VALUES (%(c)s, %(p)s, %(d)s)
                     ON CONFLICT DO NOTHING""", {"c": app["customer_id"], "p": app["product_code"], "d": start})
    _set_status(conn, application_id, "ACTIVE")
    events.emit(conn, "LOAN_ACTIVATED", actor, customer_id=app["customer_id"], application_id=application_id, loan_id=loan_id,
                payload={"amount": app["amount_requested"], "monthly_amortization": amort, "tenure_months": n})
    events.emit(conn, "MONITORING_STARTED", actor, customer_id=app["customer_id"], loan_id=loan_id)
    return {"loan_id": loan_id, "application": get_application(conn, application_id)}
