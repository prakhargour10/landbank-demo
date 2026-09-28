"""Generate the AgenticOrg API catalog, Grantex manifests and docs from the live router.

    cd backend && python -m tools.export_api_catalog

Writes:
  frontend/api_catalog.json                 (shown in the console under "APIs for AgenticOrg")
  docs/AGENTICORG_API_LIST.md               (hand this to the developer / AgenticOrg admin)
  grantex_manifests/<agent>.json            (one tool-permission manifest per agent)
It fails if a route exists that is not mapped below, so the list can never drift from the code.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.routers.api import r as router  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

A_APP, A_FIN, A_CASE, A_PORT, A_GROW, A_ORCH = ("MSME Application Agent", "Financial Analysis Agent", "Credit Case Agent",
                                                  "Portfolio Intelligence Agent", "RM & Growth Agent", "Orchestrator")
HUMAN, ADMIN = "Human only (web console / bank systems)", "Admin & integration (not for agents)"

# tool -> (permission, [agents], purpose)
TOOLS = {
    # customers & relationship data
    "listCustomers": ("READ", [A_PORT, A_ORCH], "List MSMEs; filter by health status, region, sector, RM or name."),
    "getCustomer": ("READ", [A_APP, A_FIN, A_CASE, A_PORT, A_GROW, A_ORCH], "Profile, KYC status, vintage, RM."),
    "getCustomer360": ("READ", [A_APP, A_PORT, A_GROW, A_ORCH], "Everything about a customer in one call (loans, health, signals, open work)."),
    "getAccounts": ("READ", [A_APP, A_FIN], "Deposit accounts and balances."),
    "getTransactions": ("READ", [A_FIN, A_PORT], "Categorised bank transactions (12 months)."),
    "getMonthlyCashflow": ("READ", [A_FIN, A_PORT], "Monthly inflow / outflow / receipts / repayments summary."),
    "getTaxFilings": ("READ", [A_FIN, A_PORT], "BIR quarterly VAT (2550Q) / percentage tax (2551Q) and annual ITR (1701/1702)."),
    "getCreditReport": ("READ", [A_FIN, A_CASE], "CIC-style credit report (score, facilities, max DPD)."),
    "getLoans": ("READ", [A_FIN, A_PORT], "Loans with repayment schedule and utilisation."),
    "getProductHoldings": ("READ", [A_APP, A_GROW], "Products the customer already holds."),
    "checkEligibility": ("READ", [A_APP], "Indicative eligibility and max amount from data the bank already holds (not an approval)."),
    # consent & application
    "requestConsent": ("WRITE", [A_APP], "Ask the MSME for read-only, time-bound data consent."),
    "getConsent": ("READ", [A_APP], "Check whether consent was granted."),
    "grantConsent": ("HUMAN ONLY", [HUMAN], "MSME grants consent."),
    "declineConsent": ("HUMAN ONLY", [HUMAN], "MSME declines consent."),
    "createApplication": ("WRITE", [A_APP], "Start a loan application (amount in full pesos)."),
    "listApplications": ("READ", [A_APP, A_CASE, A_ORCH], "List applications by status or customer."),
    "getApplication": ("READ", [A_APP, A_FIN, A_CASE], "Application with consent, documents and timeline."),
    "listDocuments": ("READ", [A_APP, A_CASE], "Document checklist with status and issues."),
    "fetchDocuments": ("WRITE", [A_APP], "Pull bank statements, VAT returns, credit report and registration via consent."),
    "validateDocuments": ("WRITE", [A_APP], "Validate documents; find missing pages; cross-check declared sales vs bank receipts."),
    "requestDocument": ("WRITE", [A_APP], "Ask the MSME for a missing or corrected document."),
    "uploadDocument": ("HUMAN ONLY", [HUMAN], "MSME uploads a document (multipart)."),
    "getDocument": ("READ", [A_APP, A_FIN, A_CASE], "Document metadata, issues and extracted values."),
    "downloadDocument": ("READ", [A_APP, A_FIN, A_CASE], "Document as PDF (for OCR / reading)."),
    # analysis & credit case
    "runFinancialAnalysis": ("WRITE", [A_FIN], "Compute revenue, surplus, DSCR (current and with new loan), cash-gap pattern, product fit."),
    "getFinancialAnalysis": ("READ", [A_FIN, A_CASE], "Latest stored financial analysis."),
    "prepareCreditCase": ("WRITE", [A_CASE], "Store readiness score, factor scores, evidence, strengths, risks, review questions and the agent's memo."),
    "getCreditCase": ("READ", [A_CASE, A_ORCH], "Latest credit case."),
    "submitApplication": ("HUMAN ONLY", [HUMAN], "MSME (or RM on their behalf) submits to a credit officer."),
    "openCreditCase": ("HUMAN ONLY", [HUMAN], "Credit officer opens the case."),
    "recordHumanDecision": ("HUMAN ONLY", [HUMAN], "Credit officer / sanction authority records a decision. NEVER give this to an agent."),
    "activateLoan": ("HUMAN ONLY", [HUMAN], "Loan operations books and disburses an approved loan."),
    # monitoring
    "getPortfolioSummary": ("READ", [A_PORT, A_ORCH], "Exposure, health mix, regions, sectors, queues."),
    "runPortfolioMonitoring": ("WRITE", [A_PORT], "Recalculate signals for every active borrower; returns who needs attention (daily workflow)."),
    "getEarlyWarningSignals": ("READ", [A_PORT, A_GROW, A_ORCH], "Current metrics and fired signals for one customer (nothing stored)."),
    "calculateEarlyWarningSignals": ("WRITE", [A_PORT], "Recalculate, store a snapshot and update health status (emits HEALTH_STATUS_CHANGED)."),
    "createRiskAlert": ("WRITE", [A_PORT], "Raise an early-warning alert with evidence and a recommended human action."),
    "listRiskAlerts": ("READ", [A_PORT, A_GROW, A_ORCH], "List alerts."),
    "getRiskAlert": ("READ", [A_PORT, A_GROW], "One alert."),
    "updateRiskAlert": ("HUMAN ONLY", [HUMAN], "RM / credit resolves or escalates an alert."),
    # growth & RM
    "getProductOpportunities": ("WRITE", [A_GROW], "Next-best products for one healthy customer, with reasons (stores the opportunity)."),
    "listOpportunities": ("WRITE", [A_GROW, A_ORCH], "Best opportunity per customer across the book (stores opportunities)."),
    "createRMLead": ("WRITE", [A_GROW], "Create a lead in the RM work queue (blocked for credit offers to HIGH_ATTENTION customers)."),
    "listRMLeads": ("READ", [A_GROW, A_ORCH], "List leads."),
    "updateRMLead": ("HUMAN ONLY", [HUMAN], "RM records the lead outcome."),
    "createRMTask": ("WRITE", [A_GROW, A_PORT, A_APP], "Create a task for the customer's RM (risk outreach, document follow-up, growth)."),
    "listRMTasks": ("READ", [A_GROW, A_ORCH], "List RM tasks."),
    "updateRMTask": ("HUMAN ONLY", [HUMAN], "RM records the task outcome."),
    "getRMWorkQueue": ("READ", [A_GROW, A_ORCH], "Open tasks and leads for an RM."),
    # reference, events, admin
    "getReferenceData": ("READ", [A_APP, A_FIN, A_CASE, A_PORT, A_GROW, A_ORCH], "Products, early-warning rules, document checklist, RMs, event types."),
    "listEvents": ("READ", [A_ORCH, ADMIN], "Event log; poll with since_id if webhooks are not used."),
    "getAuditTrail": ("ADMIN", [ADMIN], "Every API call with actor, tool and HTTP result."),
    "createWebhookSubscription": ("ADMIN", [ADMIN], "Push events to a URL, e.g. an AgenticOrg workflow webhook trigger."),
    "listWebhookSubscriptions": ("ADMIN", [ADMIN], "List subscriptions and recent deliveries."),
    "deleteWebhookSubscription": ("ADMIN", [ADMIN], "Deactivate a subscription."),
    "resetDemoData": ("ADMIN", [ADMIN], "Wipe and re-seed all synthetic data."),
    "applyDemoStress": ("ADMIN", [ADMIN], "Demo: make a customer deteriorate before a live demo."),
}
AGENT_KEYS = {A_APP: "lbk_agent_application", A_FIN: "lbk_agent_financial", A_CASE: "lbk_agent_creditcase",
              A_PORT: "lbk_agent_portfolio", A_GROW: "lbk_agent_growth", A_ORCH: "lbk_agent_orchestrator"}
ORDER = [A_APP, A_FIN, A_CASE, A_PORT, A_GROW, A_ORCH, HUMAN, ADMIN]


def routes():
    out = {}
    for rt in router.routes:
        op = getattr(rt, "operation_id", None)
        methods = sorted(m for m in (getattr(rt, "methods", None) or []) if m != "HEAD")
        out[op] = {"method": methods[0] if methods else "GET", "path": rt.path}
    return out


def main():
    live = routes()
    missing = set(live) - set(TOOLS)
    stale = set(TOOLS) - set(live)
    if missing or stale:
        raise SystemExit(f"Catalog out of sync. Unmapped routes: {sorted(missing)}; mapped but not in code: {sorted(stale)}")
    catalog = []
    for agent in ORDER:
        for tool, (perm, agents, purpose) in TOOLS.items():
            if agent in agents:
                catalog.append({"agent": agent, "tool": tool, "permission": perm, "purpose": purpose, **live[tool]})
    os.makedirs(os.path.join(ROOT, "frontend"), exist_ok=True)
    with open(os.path.join(ROOT, "frontend", "api_catalog.json"), "w", encoding="utf-8") as fh:
        json.dump(catalog, fh, indent=1, ensure_ascii=False)

    # Grantex-style manifests (one per agent). Adapt field names to your Grantex manifest schema if it differs.
    mdir = os.path.join(ROOT, "grantex_manifests")
    os.makedirs(mdir, exist_ok=True)
    for agent in ORDER[:6]:
        tools = [{"name": t["tool"], "method": t["method"], "path": t["path"], "permission": t["permission"].lower(),
                  "description": t["purpose"]} for t in catalog if t["agent"] == agent]
        manifest = {
            "manifest_version": "1.0", "connector": "landbank_msme_demo_data", "agent": agent,
            "auth": {"type": "api_key", "header": "X-API-Key", "value_ref": f"secret://landbank/{AGENT_KEYS[agent]}"},
            "tools": tools,
            "denied_tools": sorted(t for t, v in TOOLS.items() if v[0] in ("HUMAN ONLY", "ADMIN")),
            "human_approval_required_for": ["recordHumanDecision", "activateLoan"],
        }
        fname = agent.lower().replace(" & ", "_").replace(" ", "_") + ".json"
        with open(os.path.join(mdir, fname), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)

    # Markdown list
    lines = ["# LANDBANK MSME Lending – APIs to register in AgenticOrg", "",
             "Generated by `backend/tools/export_api_catalog.py` from the live code. Do not edit by hand.", "",
             "**Connector:** one custom connector, `base_url` = where this service runs (e.g. `https://landbank-demo.example.com`), "
             "`auth_type` = API key in header `X-API-Key` (one key per agent). OpenAPI spec: `GET /openapi.json` "
             "(each operationId = tool name).", "",
             "Permissions: **READ** reads data · **WRITE** creates/updates workflow records (never money or credit decisions) · "
             "**HUMAN ONLY** must never be given to an agent (the service returns 403 for agent keys) · **ADMIN** integration/demo setup.", ""]
    for agent in ORDER:
        rows = [t for t in catalog if t["agent"] == agent]
        if not rows:
            continue
        key = f" — API key `{AGENT_KEYS[agent]}`" if agent in AGENT_KEYS else ""
        lines += [f"## {agent}{key}", "", "| # | Tool (operationId) | Method | Path | Permission | What it does |", "|---|---|---|---|---|---|"]
        for i, t in enumerate(rows, 1):
            lines.append(f"| {i} | `{t['tool']}` | {t['method']} | `{t['path']}` | {t['permission']} | {t['purpose']} |")
        lines.append("")
    with open(os.path.join(ROOT, "docs", "AGENTICORG_API_LIST.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"{len(TOOLS)} tools, {len(catalog)} agent-tool rows written")


if __name__ == "__main__":
    main()
