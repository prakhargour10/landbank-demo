"""All /api/v1 endpoints.

`operation_id` on every route = the tool name AgenticOrg will see when it imports the OpenAPI
spec (GET /openapi.json). Keep them stable.
Endpoints marked HUMAN ONLY check the caller's role inside this service as well.
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response

from ..auth import Actor, get_actor, require_roles
from ..db import get_conn, q_one
from ..pdf import render_document_pdf
from ..schemas import (ActivateIn, AlertIn, ApplicationIn, ConsentIn, CreditCaseIn, DecisionIn, DocumentRequestIn,
                       EligibilityIn, LeadIn, StatusUpdateIn, StressIn, TaskIn, WebhookIn)
from ..services import admin, analysis, applications as apps, customers as cust, growth, monitoring
from ..util import not_found

r = APIRouter(prefix="/api/v1")


# ----------------------------------------------------------------- Customers (READ)
@r.get("/customers", operation_id="listCustomers", tags=["Customers"], summary="List MSME customers (filter by health, region, sector, RM)")
def list_customers(health_status: Optional[str] = None, region: Optional[str] = None, sector: Optional[str] = None,
                   rm_id: Optional[str] = None, search: Optional[str] = None, actor: Actor = Depends(get_actor)):
    """Search/browse the customer book. Use this first when you don't have a customer_id yet -
    filter by health_status (healthy/watch/stressed/npl), region, sector, or assigned RM.
    Returns a summary row per matching customer, not full detail - follow up with getCustomer
    or getCustomer360 for one customer's specifics."""
    with get_conn() as c:
        return cust.list_customers(c, health_status, region, sector, rm_id, search)


@r.get("/customers/{customer_id}", operation_id="getCustomer", tags=["Customers"], summary="Customer profile & KYC status")
def get_customer(customer_id: str, actor: Actor = Depends(get_actor)):
    """Fetch one customer's core profile and KYC status by customer_id. Use when you already
    have the ID and need identity/registration details, not transactions or loans."""
    with get_conn() as c:
        return cust.get_customer(c, customer_id)


@r.get("/customers/{customer_id}/360", operation_id="getCustomer360", tags=["Customers"], summary="Everything about one customer in one call")
def customer_360(customer_id: str, actor: Actor = Depends(get_actor)):
    """The single best call when you need a full picture of one MSME: profile, accounts,
    recent transactions summary, loans, products and risk signals in one response. Prefer this
    over calling getCustomer + getAccounts + getLoans separately when you need a broad
    understanding before deeper analysis."""
    with get_conn() as c:
        return cust.customer_360(c, customer_id)


@r.get("/customers/{customer_id}/accounts", operation_id="getAccounts", tags=["Customers"], summary="Deposit accounts and balances")
def accounts(customer_id: str, actor: Actor = Depends(get_actor)):
    """Deposit account balances for one customer. Use for a quick liquidity check without
    pulling full transaction history."""
    with get_conn() as c:
        return cust.get_accounts(c, customer_id)


@r.get("/customers/{customer_id}/transactions", operation_id="getTransactions", tags=["Customers"], summary="Bank transactions (12 months, categorised)")
def transactions(customer_id: str, date_from: Optional[str] = None, date_to: Optional[str] = None, category: Optional[str] = None,
                 direction: Optional[str] = None, limit: int = 500, offset: int = 0, actor: Actor = Depends(get_actor)):
    """Bank transaction history for one customer over up to 12 months, filterable by date
    range, category and direction (credit/debit). Use for cash-flow analysis, verifying
    declared income/sales, or spotting irregular activity. Can return a large volume - use
    limit/offset for paging, or getMonthlyCashflow if you only need aggregated totals."""
    with get_conn() as c:
        return cust.get_transactions(c, customer_id, date_from, date_to, category, direction, limit, offset)


@r.get("/customers/{customer_id}/cashflow", operation_id="getMonthlyCashflow", tags=["Customers"], summary="Monthly inflow/outflow summary")
def cashflow(customer_id: str, months: int = 12, actor: Actor = Depends(get_actor)):
    """Pre-aggregated monthly inflow/outflow totals for a customer. Use instead of
    getTransactions when you only need the cash-flow trend/summary, not line-item detail."""
    with get_conn() as c:
        return cust.monthly_cashflow(c, customer_id, months)


@r.get("/customers/{customer_id}/tax-filings", operation_id="getTaxFilings", tags=["Customers"], summary="BIR VAT/percentage-tax returns and annual ITR")
def tax_filings(customer_id: str, actor: Actor = Depends(get_actor)):
    """BIR VAT/percentage-tax returns and annual ITR for a customer. Use to cross-check
    declared revenue against tax filings during financial analysis or document validation."""
    with get_conn() as c:
        return cust.get_tax_filings(c, customer_id)


@r.get("/customers/{customer_id}/credit-report", operation_id="getCreditReport", tags=["Customers"], summary="CIC-style credit report (synthetic)")
def credit_report(customer_id: str, actor: Actor = Depends(get_actor)):
    """Synthetic CIC-style credit bureau report for a customer (existing obligations,
    repayment history, bureau score). Use during eligibility checks, financial analysis, or
    credit case preparation to assess external credit risk."""
    with get_conn() as c:
        return cust.get_credit_report(c, customer_id)


@r.get("/customers/{customer_id}/loans", operation_id="getLoans", tags=["Customers"], summary="Loans with repayment schedule")
def loans(customer_id: str, include_schedule: bool = True, actor: Actor = Depends(get_actor)):
    """Existing loan(s) for a customer with repayment schedule and status. Use to check
    current exposure/repayment behaviour before extending new credit, or during portfolio
    monitoring."""
    with get_conn() as c:
        return cust.get_loans(c, customer_id, include_schedule)


@r.get("/customers/{customer_id}/products", operation_id="getProductHoldings", tags=["Customers"], summary="Products the customer already holds")
def products(customer_id: str, actor: Actor = Depends(get_actor)):
    """Which lending/deposit products a customer already holds. Use before cross-sell
    (getProductOpportunities) to avoid recommending a product they already have."""
    with get_conn() as c:
        return cust.get_products(c, customer_id)


@r.post("/customers/{customer_id}/eligibility-check", operation_id="checkEligibility", tags=["Application"], summary="Indicative eligibility (NOT an approval)")
def eligibility(customer_id: str, body: EligibilityIn, actor: Actor = Depends(get_actor)):
    """Indicative-only pre-screen for whether a customer likely qualifies for a given loan
    amount/product - NOT a formal approval or decision. Use early, before createApplication, to
    set expectations; the real decision always requires a human via recordHumanDecision."""
    with get_conn() as c:
        return cust.eligibility_check(c, actor, customer_id, body.amount, body.product_code)


# ----------------------------------------------------------------- Consent
@r.post("/consents", operation_id="requestConsent", tags=["Consent"], summary="Ask the MSME for read-only data consent")
def request_consent(body: ConsentIn, actor: Actor = Depends(get_actor)):
    """Ask the MSME (data subject) for consent to access specific data scopes for a stated
    purpose, optionally linked to an application. Required before pulling sensitive data on
    their behalf - call this first, then poll getConsent (agents cannot self-grant; only the
    applicant can via grantConsent/declineConsent)."""
    with get_conn() as c:
        return apps.request_consent(c, actor, body.customer_id, body.purpose, body.data_scopes, body.application_id)


@r.get("/consents/{consent_id}", operation_id="getConsent", tags=["Consent"], summary="Consent status")
def get_consent(consent_id: str, actor: Actor = Depends(get_actor)):
    """Check the current status of a previously requested consent (pending/granted/declined).
    Poll this after requestConsent before proceeding with data-dependent steps."""
    with get_conn() as c:
        return apps.get_consent(c, consent_id)


@r.post("/consents/{consent_id}/grant", operation_id="grantConsent", tags=["Consent"], summary="HUMAN ONLY (MSME): grant consent")
def grant_consent(consent_id: str, actor: Actor = Depends(require_roles("applicant"))):
    """HUMAN ONLY - the MSME applicant grants a pending consent request. Agents calling this
    will get a 403; it exists for the applicant-facing portal, not for agent automation."""
    with get_conn() as c:
        return apps.decide_consent(c, actor, consent_id, True)


@r.post("/consents/{consent_id}/decline", operation_id="declineConsent", tags=["Consent"], summary="HUMAN ONLY (MSME): decline consent")
def decline_consent(consent_id: str, actor: Actor = Depends(require_roles("applicant"))):
    """HUMAN ONLY - the MSME applicant declines a pending consent request. Agents calling this
    will get a 403."""
    with get_conn() as c:
        return apps.decide_consent(c, actor, consent_id, False)


# ----------------------------------------------------------------- Applications & documents
@r.post("/applications", operation_id="createApplication", tags=["Application"], summary="Start a loan application")
def create_application(body: ApplicationIn, actor: Actor = Depends(get_actor)):
    """Start a new loan application for a customer (product, amount, tenure, purpose). This is
    the entry point of the lending workflow - call after checkEligibility, before requesting
    consent/documents."""
    with get_conn() as c:
        return apps.create_application(c, actor, body.customer_id, body.product_code, body.amount, body.tenure_months, body.purpose)


@r.get("/applications", operation_id="listApplications", tags=["Application"], summary="List applications")
def list_applications(status: Optional[str] = None, customer_id: Optional[str] = None, actor: Actor = Depends(get_actor)):
    """Browse/filter applications by status or customer. Use to find an application's ID when
    you only know the customer, or to see everything in a given stage (e.g. 'submitted')."""
    with get_conn() as c:
        return apps.list_applications(c, status, customer_id)


@r.get("/applications/{application_id}", operation_id="getApplication", tags=["Application"], summary="Application with consent, documents and timeline")
def get_application(application_id: str, actor: Actor = Depends(get_actor)):
    """Full application detail: consent status, documents and status timeline. Use once you
    have an application_id and need its complete current state before deciding the next
    action."""
    with get_conn() as c:
        return apps.get_application(c, application_id)


@r.get("/applications/{application_id}/documents", operation_id="listDocuments", tags=["Documents"], summary="Document checklist and status")
def list_documents(application_id: str, actor: Actor = Depends(get_actor)):
    """Checklist of documents required for an application and each one's status
    (missing/received/validated). Use to determine what to fetchDocuments or requestDocument for
    next."""
    with get_conn() as c:
        apps.get_application(c, application_id)
        return apps.list_documents(c, application_id)


@r.post("/applications/{application_id}/documents/fetch", operation_id="fetchDocuments", tags=["Documents"], summary="Pull documents from consented sources")
def fetch_documents(application_id: str, actor: Actor = Depends(get_actor)):
    """Pull documents from sources the customer has already consented to share (bank
    statements, tax filings, etc.) into the application. Requires an active consent - call
    after getConsent confirms 'granted'."""
    with get_conn() as c:
        return apps.fetch_documents(c, actor, application_id)


@r.post("/applications/{application_id}/documents/validate", operation_id="validateDocuments", tags=["Documents"], summary="Validate documents and cross-check declared sales vs bank receipts")
def validate_documents(application_id: str, actor: Actor = Depends(get_actor)):
    """Run automated validation on the application's documents: cross-checks declared
    sales/income against bank receipts and flags inconsistencies. Use after fetchDocuments (or
    human upload) and before financial analysis."""
    with get_conn() as c:
        return apps.validate_documents(c, actor, application_id)


@r.post("/applications/{application_id}/documents/request", operation_id="requestDocument", tags=["Documents"], summary="Ask the MSME for a missing/corrected document")
def request_document(application_id: str, body: DocumentRequestIn, actor: Actor = Depends(get_actor)):
    """Ask the MSME for a missing or corrected document, with a reason. Use when
    listDocuments/validateDocuments shows a gap the automated fetch couldn't fill."""
    with get_conn() as c:
        return apps.request_document(c, actor, application_id, body.doc_type, body.reason)


@r.post("/applications/{application_id}/documents/upload", operation_id="uploadDocument", tags=["Documents"], summary="HUMAN ONLY (MSME): upload a document (multipart)")
async def upload_document(application_id: str, doc_type: str = Form(...), pages: Optional[int] = Form(None),
                          file: UploadFile = File(...), actor: Actor = Depends(require_roles("applicant"))):
    """HUMAN ONLY (MSME applicant) - upload a document file via multipart form. Agents cannot
    upload on the applicant's behalf; use requestDocument to prompt them instead."""
    content = await file.read()
    with get_conn() as c:
        return apps.upload_document(c, actor, application_id, doc_type, file.filename, content, pages)


@r.get("/documents/{document_id}", operation_id="getDocument", tags=["Documents"], summary="Document metadata, issues and extracted values")
def get_document(document_id: str, actor: Actor = Depends(get_actor)):
    """Metadata for one document plus any validation issues and extracted values (e.g. OCR'd
    figures). Use to inspect a single document's content/quality in detail."""
    with get_conn() as c:
        d = q_one(c, "SELECT * FROM documents WHERE document_id=%(d)s", {"d": document_id})
        if not d:
            not_found("Document", document_id)
        d["extracted"] = d["extracted"] or apps.document_extract(c, d)
        return d


@r.get("/documents/{document_id}/file", operation_id="downloadDocument", tags=["Documents"], summary="Document as PDF (synthetic rendering)")
def document_file(document_id: str, actor: Actor = Depends(get_actor)):
    """Render/download one document as a PDF (synthetic). Use only when you need the literal
    file, not its extracted data - for data, use getDocument instead."""
    with get_conn() as c:
        d = q_one(c, "SELECT * FROM documents WHERE document_id=%(d)s", {"d": document_id})
        if not d:
            not_found("Document", document_id)
        pdf = render_document_pdf(c, d)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{document_id}.pdf"'})


# ----------------------------------------------------------------- Financial analysis & credit case
@r.post("/applications/{application_id}/financial-analysis", operation_id="runFinancialAnalysis", tags=["Analysis"], summary="Build the financial picture from 12 months of data")
def run_fa(application_id: str, actor: Actor = Depends(get_actor)):
    """Compute the financial picture for an application from the last 12 months of
    transaction/tax data (income stability, cash flow, DSCR, etc.). Call once documents are
    validated; this is a prerequisite for prepareCreditCase."""
    with get_conn() as c:
        return analysis.run_financial_analysis(c, actor, application_id)


@r.get("/applications/{application_id}/financial-analysis", operation_id="getFinancialAnalysis", tags=["Analysis"], summary="Latest financial analysis")
def get_fa(application_id: str, actor: Actor = Depends(get_actor)):
    """Retrieve the most recently computed financial analysis for an application without
    recomputing it. Use to review prior results instead of re-running runFinancialAnalysis."""
    with get_conn() as c:
        return analysis.get_financial_analysis(c, application_id)


@r.post("/applications/{application_id}/credit-case", operation_id="prepareCreditCase", tags=["Credit case"], summary="Readiness score, evidence, strengths, risks, review questions")
def prepare_case(application_id: str, body: CreditCaseIn, actor: Actor = Depends(get_actor)):
    """Generate a structured credit case for human review: readiness score, supporting
    evidence, strengths, risks, and open review questions, given a narrative summary. Call
    after runFinancialAnalysis, before submitApplication."""
    with get_conn() as c:
        return analysis.generate_credit_case(c, actor, application_id, body.narrative)


@r.get("/applications/{application_id}/credit-case", operation_id="getCreditCase", tags=["Credit case"], summary="Latest credit case")
def get_case(application_id: str, actor: Actor = Depends(get_actor)):
    """Retrieve the latest generated credit case for an application. Use to review before
    submission or to hand off context to a human credit officer."""
    with get_conn() as c:
        return analysis.get_credit_case(c, application_id)


@r.post("/applications/{application_id}/submit", operation_id="submitApplication", tags=["Application"], summary="HUMAN ONLY (MSME): submit to a credit officer")
def submit(application_id: str, actor: Actor = Depends(require_roles("applicant", "rm"))):
    """HUMAN ONLY (MSME applicant or RM) - submit a prepared application to a credit officer
    for decisioning. Agents can prepare everything up to this point (analysis, credit case) but
    cannot submit; this hands control to a human."""
    with get_conn() as c:
        return apps.submit_application(c, actor, application_id)


@r.post("/applications/{application_id}/open", operation_id="openCreditCase", tags=["Human decision"], summary="HUMAN ONLY (credit officer): open the case for review")
def open_case(application_id: str, actor: Actor = Depends(require_roles("credit_officer"))):
    """HUMAN ONLY (credit officer) - open a submitted application's case for review. Marks the
    start of human review; agents cannot call this."""
    with get_conn() as c:
        return apps.open_case(c, actor, application_id)


@r.post("/applications/{application_id}/decision", operation_id="recordHumanDecision", tags=["Human decision"], summary="HUMAN ONLY (credit officer): record a credit decision. Never give this to an agent.")
def decision(application_id: str, body: DecisionIn, actor: Actor = Depends(require_roles("credit_officer"))):
    """HUMAN ONLY (credit officer) - record the actual approve/decline credit decision with a
    reason. This is the one consequential step agents must NEVER be given: it is enforced
    server-side and will 403 even if misconfigured elsewhere."""
    with get_conn() as c:
        return apps.record_decision(c, actor, application_id, body.decision, body.reason)


@r.post("/applications/{application_id}/activate", operation_id="activateLoan", tags=["Human decision"], summary="HUMAN ONLY (loan operations): book & disburse an approved loan")
def activate(application_id: str, body: ActivateIn, actor: Actor = Depends(require_roles("loan_ops"))):
    """HUMAN ONLY (loan operations) - book and disburse an approved loan at a given interest
    rate. Final step after recordHumanDecision approves; agents cannot call this."""
    with get_conn() as c:
        return apps.activate_loan(c, actor, application_id, body.interest_rate_pct)


# ----------------------------------------------------------------- Portfolio monitoring
@r.get("/portfolio/summary", operation_id="getPortfolioSummary", tags=["Portfolio"], summary="Exposure, health mix, regions, sectors, queues")
def portfolio_summary(actor: Actor = Depends(get_actor)):
    """Aggregate view of the whole loan book: total exposure, health-status mix, breakdown by
    region/sector, and queue sizes. Use for portfolio-level questions, not single-customer
    detail."""
    with get_conn() as c:
        return monitoring.portfolio_summary(c)


@r.post("/portfolio/monitoring-run", operation_id="runPortfolioMonitoring", tags=["Portfolio"], summary="Recalculate signals for every active borrower (daily workflow)")
def monitoring_run(actor: Actor = Depends(get_actor)):
    """Recalculate early-warning signals for every active borrower in one batch - the
    daily/periodic monitoring job. Use for a full portfolio sweep; for one customer use
    getEarlyWarningSignals/calculateEarlyWarningSignals instead."""
    with get_conn() as c:
        return monitoring.monitoring_run(c, actor)


@r.get("/customers/{customer_id}/signals", operation_id="getEarlyWarningSignals", tags=["Portfolio"], summary="Current metrics & signals (read-only, nothing stored)")
def get_signals(customer_id: str, actor: Actor = Depends(get_actor)):
    """Compute current risk metrics/signals for one customer without persisting anything - a
    cheap, read-only check. Use for an ad-hoc look; use calculateEarlyWarningSignals if the
    result should be stored and affect the customer's recorded health status."""
    with get_conn() as c:
        return monitoring.calculate_signals(c, customer_id, actor, persist=False)


@r.post("/customers/{customer_id}/signals", operation_id="calculateEarlyWarningSignals", tags=["Portfolio"], summary="Recalculate, store snapshot, update health status")
def calc_signals(customer_id: str, actor: Actor = Depends(get_actor)):
    """Recalculate signals for one customer, persist the snapshot, and update their health
    status. Use this (not the read-only variant) when the result should affect the customer's
    recorded health status or trigger alerting."""
    with get_conn() as c:
        return monitoring.calculate_signals(c, customer_id, actor, persist=True)


@r.post("/alerts", operation_id="createRiskAlert", tags=["Alerts"], summary="Raise an early-warning alert with evidence")
def create_alert(body: AlertIn, actor: Actor = Depends(get_actor)):
    """Raise an early-warning alert for a customer with severity, summary, recommended action,
    and supporting signals. Use after detecting a risk worth escalating (e.g. from
    getEarlyWarningSignals)."""
    with get_conn() as c:
        return monitoring.create_alert(c, actor, body.customer_id, body.severity, body.summary, body.recommended_action, body.signals)


@r.get("/alerts", operation_id="listRiskAlerts", tags=["Alerts"], summary="List alerts")
def list_alerts(status: Optional[str] = None, customer_id: Optional[str] = None, actor: Actor = Depends(get_actor)):
    """Browse/filter alerts by status or customer. Use to find existing alerts before creating
    a duplicate, or to see what's open for a customer."""
    with get_conn() as c:
        return monitoring.list_alerts(c, status, customer_id)


@r.get("/alerts/{alert_id}", operation_id="getRiskAlert", tags=["Alerts"], summary="One alert")
def get_alert(alert_id: str, actor: Actor = Depends(get_actor)):
    """Full detail for one alert. Use once you have an alert_id from listRiskAlerts and need
    its evidence/detail."""
    with get_conn() as c:
        return monitoring.get_alert(c, alert_id)


@r.patch("/alerts/{alert_id}", operation_id="updateRiskAlert", tags=["Alerts"], summary="HUMAN ONLY (RM / credit): resolve or escalate an alert")
def update_alert(alert_id: str, body: StatusUpdateIn, actor: Actor = Depends(require_roles("rm", "credit_officer"))):
    """HUMAN ONLY (RM or credit officer) - resolve or escalate an alert with a note. Agents can
    create/list/inspect alerts but the human decides the outcome."""
    with get_conn() as c:
        return monitoring.update_alert(c, actor, alert_id, body.status, body.note)


# ----------------------------------------------------------------- Growth, leads, RM tasks
@r.get("/customers/{customer_id}/opportunities", operation_id="getProductOpportunities", tags=["Growth"], summary="Next-best products with reasons (healthy customers only)")
def customer_opps(customer_id: str, actor: Actor = Depends(get_actor)):
    """Next-best-product suggestions with reasons for one customer - only meaningful for
    healthy customers (not watch/stressed/NPL). Use for cross-sell/upsell conversations."""
    with get_conn() as c:
        return growth.opportunities_for(c, customer_id, actor)


@r.get("/opportunities", operation_id="listOpportunities", tags=["Growth"], summary="Best opportunity per customer across the book")
def all_opps(actor: Actor = Depends(get_actor)):
    """Best single opportunity per customer across the entire book. Use for portfolio-wide
    growth/cross-sell targeting rather than one customer at a time."""
    with get_conn() as c:
        return growth.all_opportunities(c, actor)


@r.post("/leads", operation_id="createRMLead", tags=["Growth"], summary="Create a lead in the RM work queue")
def create_lead(body: LeadIn, actor: Actor = Depends(get_actor)):
    """Create a lead in the relationship manager's work queue from an opportunity, so a human
    RM can follow up. Use after identifying an opportunity worth acting on."""
    with get_conn() as c:
        return growth.create_lead(c, actor, body.customer_id, body.product_code, body.reason, body.opportunity_id)


@r.get("/leads", operation_id="listRMLeads", tags=["Growth"], summary="List leads")
def list_leads(rm_id: Optional[str] = None, status: Optional[str] = None, actor: Actor = Depends(get_actor)):
    """Browse/filter leads by RM or status. Use to check existing pipeline before creating a
    duplicate lead."""
    with get_conn() as c:
        return growth.list_leads(c, rm_id, status)


@r.patch("/leads/{lead_id}", operation_id="updateRMLead", tags=["Growth"], summary="HUMAN ONLY (RM): update lead outcome")
def update_lead(lead_id: str, body: StatusUpdateIn, actor: Actor = Depends(require_roles("rm"))):
    """HUMAN ONLY (RM) - update a lead's outcome/status with a note. Agents can create and list
    leads but the RM records the outcome."""
    with get_conn() as c:
        return growth.update_lead(c, actor, lead_id, body.status, body.note)


@r.post("/rm-tasks", operation_id="createRMTask", tags=["RM work queue"], summary="Create a task for the customer's RM")
def create_task(body: TaskIn, actor: Actor = Depends(get_actor)):
    """Create a task for a customer's relationship manager (type, title, details, priority, due
    date), optionally linked to an alert. Use to hand off a follow-up action to a human."""
    with get_conn() as c:
        return growth.create_task(c, actor, body.customer_id, body.task_type, body.title, body.details, body.priority,
                                  body.due_in_days, body.related_alert_id)


@r.get("/rm-tasks", operation_id="listRMTasks", tags=["RM work queue"], summary="List RM tasks")
def list_tasks(rm_id: Optional[str] = None, status: Optional[str] = None, actor: Actor = Depends(get_actor)):
    """Browse/filter RM tasks by RM or status. Use to see what's already queued before creating
    a duplicate task."""
    with get_conn() as c:
        return growth.list_tasks(c, rm_id, status)


@r.patch("/rm-tasks/{task_id}", operation_id="updateRMTask", tags=["RM work queue"], summary="HUMAN ONLY (RM): update task outcome")
def update_task(task_id: str, body: StatusUpdateIn, actor: Actor = Depends(require_roles("rm"))):
    """HUMAN ONLY (RM) - update a task's outcome/status with a note."""
    with get_conn() as c:
        return growth.update_task(c, actor, task_id, body.status, body.note)


@r.get("/rm/work-queue", operation_id="getRMWorkQueue", tags=["RM work queue"], summary="Open tasks and leads for an RM")
def work_queue(rm_id: Optional[str] = None, actor: Actor = Depends(get_actor)):
    """All open tasks and leads for one RM (or all RMs) in one call. Use to summarize an RM's
    workload."""
    with get_conn() as c:
        return growth.rm_work_queue(c, rm_id)


# ----------------------------------------------------------------- Reference, events, audit
@r.get("/reference/{kind}", operation_id="getReferenceData", tags=["Reference"],
       summary="products | ews-rules | document-checklist | relationship-managers | event-types")
def reference(kind: str, actor: Actor = Depends(get_actor)):
    """Static reference/lookup data by kind: products, ews-rules (early-warning rule
    definitions), document-checklist, relationship-managers, or event-types. Use to resolve
    valid codes/enums before using them elsewhere, not for customer-specific data."""
    with get_conn() as c:
        return admin.reference(c, kind)


@r.get("/events", operation_id="listEvents", tags=["Events & audit"], summary="Event log (poll with since_id)")
def list_events(since_id: int = 0, event_type: Optional[str] = None, customer_id: Optional[str] = None,
                application_id: Optional[str] = None, limit: int = 100, actor: Actor = Depends(get_actor)):
    """Poll the event log for state changes (new application, decision recorded, alert raised,
    etc.), optionally filtered by type/customer/application, using since_id for incremental
    polling. Use this to drive event-triggered agent workflows instead of constant re-polling of
    full resources."""
    with get_conn() as c:
        return admin.list_events(c, since_id, event_type, customer_id, application_id, limit)


@r.get("/audit", operation_id="getAuditTrail", tags=["Events & audit"], summary="Every API call with actor, tool and result")
def audit(actor_name: Optional[str] = None, customer_id: Optional[str] = None, limit: int = 200, actor: Actor = Depends(get_actor)):
    """Every API call made against this service with actor, tool name and result - the full
    compliance/audit record. Use for investigating who (which agent or human) did what, not for
    business data."""
    with get_conn() as c:
        return admin.list_audit(c, actor_name, customer_id, limit)


@r.post("/webhooks", operation_id="createWebhookSubscription", tags=["Events & audit"], summary="ADMIN: push events to a URL (e.g. AgenticOrg workflow trigger)")
def create_webhook(body: WebhookIn, actor: Actor = Depends(require_roles("admin"))):
    """ADMIN - register a URL (e.g. an AgenticOrg workflow trigger) to receive push
    notifications for given event types, instead of polling listEvents. Requires admin role."""
    with get_conn() as c:
        return admin.create_webhook(c, body.target_url, body.event_types, body.secret)


@r.get("/webhooks", operation_id="listWebhookSubscriptions", tags=["Events & audit"], summary="ADMIN: list webhook subscriptions")
def list_webhooks(actor: Actor = Depends(require_roles("admin"))):
    """ADMIN - list currently registered webhook subscriptions."""
    with get_conn() as c:
        return admin.list_webhooks(c)



@r.delete("/webhooks/{subscription_id}", operation_id="deleteWebhookSubscription", tags=["Events & audit"], summary="ADMIN: deactivate a subscription")
def delete_webhook(subscription_id: str, actor: Actor = Depends(require_roles("admin"))):
    """ADMIN - deactivate a webhook subscription."""
    with get_conn() as c:
        return admin.delete_webhook(c, subscription_id)


# ----------------------------------------------------------------- Demo controls
@r.post("/admin/reset", operation_id="resetDemoData", tags=["Demo controls"], summary="ADMIN: wipe and re-seed all synthetic data")
def reset(actor: Actor = Depends(require_roles("admin"))):
    """ADMIN - wipe and re-seed all synthetic demo data. Destructive; only for resetting the
    demo environment, never for real workflows."""
    from seed.load import reset_database
    return reset_database()


@r.post("/admin/customers/{customer_id}/apply-stress", operation_id="applyDemoStress", tags=["Demo controls"], summary="ADMIN: make a customer deteriorate (for live demos)")
def stress(customer_id: str, body: StressIn, actor: Actor = Depends(require_roles("admin"))):
    """ADMIN - artificially deteriorate one customer's data for a live demo (e.g. to showcase
    early-warning detection). Not a real business operation."""
    with get_conn() as c:
        return admin.apply_stress(c, actor, customer_id, body.severity)
