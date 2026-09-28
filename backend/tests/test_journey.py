"""End-to-end journey test (runs against a real PostgreSQL in DATABASE_URL; it RESETS the demo data).

    cd backend && pytest -q tests/test_journey.py      (or: python tests/test_journey.py)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from starlette.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

AGENT = {k: {"X-API-Key": v} for k, v in {
    "application": "lbk_agent_application", "financial": "lbk_agent_financial", "case": "lbk_agent_creditcase",
    "portfolio": "lbk_agent_portfolio", "growth": "lbk_agent_growth"}.items()}
HUMAN = {k: {"X-API-Key": v} for k, v in {
    "applicant": "lbk_human_applicant", "officer": "lbk_human_credit_officer", "rm": "lbk_human_rm",
    "ops": "lbk_human_loan_ops", "admin": "lbk_human_admin"}.items()}


def ok(resp, code=200):
    assert resp.status_code == code, f"{resp.request.method} {resp.request.url} -> {resp.status_code}: {resp.text[:400]}"
    return resp.json()


def test_full_journey():
    with TestClient(app) as c:
        ok(c.post("/api/v1/admin/reset", headers=HUMAN["admin"]))
        assert c.get("/api/v1/customers").status_code == 401  # no key

        # Journey A - eligibility
        e = ok(c.post("/api/v1/customers/LB-MSME-0001/eligibility-check", json={"amount": 5000000}, headers=AGENT["application"]))
        assert e["indicatively_eligible"] is True

        # Journey B - consent, fetch, validate
        cons = ok(c.post("/api/v1/consents", json={"customer_id": "LB-MSME-0001", "purpose": "Loan application APP-2026-0001",
                                                   "application_id": "APP-2026-0001"}, headers=AGENT["application"]))
        assert c.post(f"/api/v1/consents/{cons['consent_id']}/grant", headers=AGENT["application"]).status_code == 403
        ok(c.post(f"/api/v1/consents/{cons['consent_id']}/grant", headers=HUMAN["applicant"]))
        f = ok(c.post("/api/v1/applications/APP-2026-0001/documents/fetch", headers=AGENT["application"]))
        assert set(f["fetched"]) == {"BUSINESS_REGISTRATION", "BANK_STATEMENTS_12M", "VAT_RETURNS", "CREDIT_REPORT"}
        v = ok(c.post("/api/v1/applications/APP-2026-0001/documents/validate", headers=AGENT["application"]))
        assert v["documents_complete"] is False
        ok(c.post("/api/v1/applications/APP-2026-0001/documents/request", json={"doc_type": "ITR_ANNUAL", "reason": "Please upload FY2025 ITR"}, headers=AGENT["application"]))
        for dt in ["MAYORS_PERMIT", "BIR_COR", "ITR_ANNUAL", "AUDITED_FS"]:
            ok(c.post("/api/v1/applications/APP-2026-0001/documents/upload", data={"doc_type": dt},
                      files={"file": (f"{dt}.pdf", b"%PDF-1.4 demo", "application/pdf")}, headers=HUMAN["applicant"]))
        v = ok(c.post("/api/v1/applications/APP-2026-0001/documents/validate", headers=AGENT["application"]))
        assert v["documents_complete"] is True, v

        # Journey C/D - analysis and credit case
        fa = ok(c.post("/api/v1/applications/APP-2026-0001/financial-analysis", headers=AGENT["financial"]))
        assert fa["metrics"]["dscr_pro_forma"] > 1
        case = ok(c.post("/api/v1/applications/APP-2026-0001/credit-case", json={"narrative": "Test memo"}, headers=AGENT["case"]))
        assert 0 < case["readiness_score"] <= 100
        assert c.post("/api/v1/applications/APP-2026-0001/submit", headers=AGENT["case"]).status_code == 403
        ok(c.post("/api/v1/applications/APP-2026-0001/submit", headers=HUMAN["applicant"]))

        # Journey E - agents can NEVER decide
        d = c.post("/api/v1/applications/APP-2026-0001/decision", json={"decision": "RECOMMEND_APPROVAL", "reason": "x"}, headers=AGENT["case"])
        assert d.status_code == 403
        ok(c.post("/api/v1/applications/APP-2026-0001/open", headers=HUMAN["officer"]))
        ok(c.post("/api/v1/applications/APP-2026-0001/decision", json={"decision": "RECOMMEND_APPROVAL", "reason": "Strong cash flows"}, headers=HUMAN["officer"]))
        ok(c.post("/api/v1/applications/APP-2026-0001/decision", json={"decision": "APPROVE", "reason": "Sanctioned"}, headers=HUMAN["officer"]))
        # Journey F - activation
        act = ok(c.post("/api/v1/applications/APP-2026-0001/activate", json={}, headers=HUMAN["ops"]))
        assert act["application"]["status"] == "ACTIVE"

        # Mismatch scenario
        v3 = ok(c.post("/api/v1/applications/APP-2026-0003/documents/validate", headers=AGENT["application"]))
        assert v3["sales_cross_check"]["gap_pct"] > 15, v3["sales_cross_check"]
        # Missing docs scenario
        v2 = ok(c.post("/api/v1/applications/APP-2026-0002/documents/validate", headers=AGENT["application"]))
        assert v2["documents_complete"] is False

        # Journey G/H - monitoring, alert, task
        run = ok(c.post("/api/v1/portfolio/monitoring-run", headers=AGENT["portfolio"]))
        needs = {n["customer_id"] for n in run["needs_attention"]}
        assert {"LB-MSME-0015", "LB-MSME-0016", "LB-MSME-0017"} <= needs
        sig = ok(c.get("/api/v1/customers/LB-MSME-0017/signals", headers=AGENT["portfolio"]))
        alert = ok(c.post("/api/v1/alerts", json={"customer_id": "LB-MSME-0017", "severity": "HIGH",
                                                  "summary": "Receipts down sharply, repayment 41 days late.",
                                                  "recommended_action": "RM outreach within 2 business days", "signals": sig["signals"]}, headers=AGENT["portfolio"]))
        task = ok(c.post("/api/v1/rm-tasks", json={"customer_id": "LB-MSME-0017", "task_type": "RISK_OUTREACH", "title": "Call the owner",
                                                   "details": alert["summary"], "related_alert_id": alert["alert_id"]}, headers=AGENT["growth"]))
        assert c.patch(f"/api/v1/rm-tasks/{task['task_id']}", json={"status": "DONE"}, headers=AGENT["growth"]).status_code == 403
        ok(c.patch(f"/api/v1/rm-tasks/{task['task_id']}", json={"status": "DONE", "note": "Owner expects DPWH payment next week"}, headers=HUMAN["rm"]))

        # Journey I - growth
        opps = ok(c.get("/api/v1/customers/LB-MSME-0002/opportunities", headers=AGENT["growth"]))
        assert opps["opportunities"][0]["product_code"] == "INVOICE_FINANCING"
        blocked = ok(c.get("/api/v1/customers/LB-MSME-0015/opportunities", headers=AGENT["growth"]))
        assert blocked["opportunities"] == []
        lead = ok(c.post("/api/v1/leads", json={"customer_id": "LB-MSME-0002", "product_code": "INVOICE_FINANCING",
                                                "reason": "Growing café receivables", "opportunity_id": opps["opportunities"][0]["opportunity_id"]}, headers=AGENT["growth"]))
        assert c.post("/api/v1/leads", json={"customer_id": "LB-MSME-0015", "product_code": "WORKING_CAPITAL", "reason": "x"}, headers=AGENT["growth"]).status_code == 409
        q = ok(c.get("/api/v1/rm/work-queue", headers=HUMAN["rm"]))
        assert any(l["lead_id"] == lead["lead_id"] for l in q["open_leads"])

        # Demo stress turns a healthy customer into HIGH_ATTENTION
        ok(c.post("/api/v1/admin/customers/LB-MSME-0005/apply-stress", json={"severity": "HIGH"}, headers=HUMAN["admin"]))
        s5 = ok(c.post("/api/v1/customers/LB-MSME-0005/signals", headers=AGENT["portfolio"]))
        assert s5["health_status"] == "HIGH_ATTENTION", s5

        # Everything is visible everywhere
        summ = ok(c.get("/api/v1/portfolio/summary", headers=HUMAN["admin"]))
        assert summ["open_alerts"] >= 3
        c360 = ok(c.get("/api/v1/customers/LB-MSME-0017/360", headers=HUMAN["rm"]))
        assert c360["open_alerts"] and c360["health"]["status"] == "HIGH_ATTENTION"
        evs = ok(c.get("/api/v1/events?application_id=APP-2026-0001&limit=100", headers=HUMAN["admin"]))
        types = {e["event_type"] for e in evs}
        assert {"CONSENT_GIVEN", "DOCUMENTS_COMPLETE", "CREDIT_CASE_GENERATED", "RECOMMENDED_APPROVAL", "LOAN_ACTIVATED"} <= types
        aud = ok(c.get("/api/v1/audit?limit=500", headers=HUMAN["admin"]))
        assert any(a["tool_name"] == "recordHumanDecision" and a["status_code"] == 403 and a["actor_type"] == "AGENT" for a in aud)
        pdf = c.get("/api/v1/documents/DOC-0005/file", headers=HUMAN["officer"])
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
        for kind in ["products", "ews-rules", "document-checklist", "relationship-managers", "event-types"]:
            ok(c.get(f"/api/v1/reference/{kind}", headers=AGENT["growth"]))
        ok(c.post("/api/v1/webhooks", json={"target_url": "https://example.invalid/hook", "event_types": ["RISK_ALERT_CREATED"]}, headers=HUMAN["admin"]))
        ok(c.post("/api/v1/admin/reset", headers=HUMAN["admin"]))


if __name__ == "__main__":
    test_full_journey()
    print("journey test passed")
