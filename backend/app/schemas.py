"""Request bodies. Field descriptions appear in /docs and in the OpenAPI spec that AgenticOrg imports."""
from typing import List, Optional

from pydantic import BaseModel, Field


class EligibilityIn(BaseModel):
    amount: Optional[float] = Field(None, description="Requested amount in PHP")
    product_code: str = Field("WORKING_CAPITAL", description="Credit product code from /reference/products")


class ConsentIn(BaseModel):
    customer_id: str
    purpose: str = Field(..., description="Plain-English purpose shown to the MSME, e.g. 'Loan application APP-2026-0001'")
    data_scopes: Optional[List[str]] = Field(None, description="BANK_TRANSACTIONS, TAX_FILINGS, CREDIT_REPORT, BUSINESS_REGISTRATION (default: all)")
    application_id: Optional[str] = Field(None, description="Link the consent to this application")


class ApplicationIn(BaseModel):
    customer_id: str
    product_code: str = Field(..., description="Credit product code, e.g. WORKING_CAPITAL")
    amount: float = Field(..., gt=0, description="Requested amount in PHP (full pesos, e.g. 5000000 for ₱5M)")
    tenure_months: int = Field(..., gt=0, le=120)
    purpose: str


class DocumentRequestIn(BaseModel):
    doc_type: str = Field(..., description="Document type from /reference/document-checklist")
    reason: str = Field(..., description="Plain-English reason shown to the MSME")


class CreditCaseIn(BaseModel):
    narrative: Optional[str] = Field(None, description="Credit memo narrative written by the Credit Case Agent (optional)")


class DecisionIn(BaseModel):
    decision: str = Field(..., description="REQUEST_MORE_INFO | SEND_BACK | RECOMMEND_APPROVAL | RECOMMEND_DECLINE | APPROVE | DECLINE")
    reason: str


class ActivateIn(BaseModel):
    interest_rate_pct: Optional[float] = None


class AlertIn(BaseModel):
    customer_id: str
    severity: str = Field(..., description="WATCH or HIGH")
    summary: str = Field(..., description="Plain-English AI brief: what is happening and why it matters")
    recommended_action: str = Field(..., description="Human action, e.g. 'RM outreach within 2 business days'. Never an automatic loan action.")
    signals: Optional[list] = Field(None, description="Signals from calculateEarlyWarningSignals (optional - recalculated if omitted)")


class StatusUpdateIn(BaseModel):
    status: str
    note: Optional[str] = None


class LeadIn(BaseModel):
    customer_id: str
    product_code: str
    reason: str
    opportunity_id: Optional[str] = None


class TaskIn(BaseModel):
    customer_id: str
    task_type: str = Field(..., description="RISK_OUTREACH | DOCUMENT_FOLLOW_UP | GROWTH_CONVERSATION | OTHER")
    title: str
    details: str
    priority: str = Field("HIGH", description="HIGH | MEDIUM | LOW")
    due_in_days: int = 2
    related_alert_id: Optional[str] = None


class WebhookIn(BaseModel):
    target_url: str = Field(..., description="e.g. your AgenticOrg workflow webhook trigger URL")
    event_types: List[str] = Field(["*"], description="Event types to receive, or ['*'] for all")
    secret: Optional[str] = Field(None, description="HMAC-SHA256 secret; signature sent in X-Landbank-Signature")


class StressIn(BaseModel):
    severity: str = Field("HIGH", description="HIGH or WATCH")
