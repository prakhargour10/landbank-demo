# Connecting the LANDBANK demo data service to AgenticOrg

Simple steps for the developer. Based on AgenticOrg's public documentation (custom connectors via `POST /connectors` with `base_url` + `auth_type`, Grantex tool manifests, RAGFlow knowledge base, workflows with schedule/webhook triggers, HITL approval nodes, shadow mode). Confirm field names against your internal AgenticOrg version.

## 1. Deploy the service
Run it somewhere AgenticOrg can reach over HTTPS (Cloud Run, a VM, or `docker compose up` behind a tunnel for a demo). Note the base URL, e.g. `https://landbank-demo.example.com`.
Set your own keys with the `API_KEYS` environment variable (JSON) — do not use the demo keys outside a demo.

## 2. Register ONE custom connector
- **Name:** `landbank_msme_demo_data`
- **base_url:** your service URL
- **auth_type:** API key → header `X-API-Key`
- **Tools:** import `GET {base_url}/openapi.json`. Every `operationId` is a tool name (`getCustomer360`, `createRiskAlert`, …).
- Store one key per agent in Secret Manager (the manifest files reference them as `secret://landbank/<key>`).

## 3. Give each agent only its tools (Grantex)
Load the files in `grantex_manifests/` (one per agent). Each lists allowed tools with `read` / `write` permission, plus `denied_tools`.
Never give any agent: `recordHumanDecision`, `activateLoan`, `grantConsent`, `declineConsent`, `uploadDocument`, `submitApplication`, `openCreditCase`, `updateRiskAlert`, `updateRMLead`, `updateRMTask`. (The service also returns 403 if an agent key calls them.)

## 4. Upload the knowledge base
Upload everything in `knowledge_base/` (credit policy, product catalogue, early-warning rules, document checklist, agent playbook). Agents find rules there instead of hard-coding them.

## 5. Create the agents (suggested instructions)
| Agent | Key | Core instruction |
|---|---|---|
| MSME Application Agent | `lbk_agent_application` | Check eligibility → request consent → fetch → validate → request missing items in plain language. Never reject. |
| Financial Analysis Agent | `lbk_agent_financial` | Run `runFinancialAnalysis` when documents are complete; explain the numbers it returns; do not recalculate. |
| Credit Case Agent | `lbk_agent_creditcase` | Call `prepareCreditCase` with a 5–6 sentence memo in `narrative`. End with "Decision rests with the LANDBANK credit officer." |
| Portfolio Intelligence Agent | `lbk_agent_portfolio` | Daily: `runPortfolioMonitoring`; for each customer needing attention without an open alert → `getEarlyWarningSignals` → `createRiskAlert` (+ `createRMTask`). |
| RM & Growth Agent | `lbk_agent_growth` | Healthy customers: `getProductOpportunities` → `createRMLead`. Others: risk-outreach `createRMTask`, never offers. |
| Orchestrator | `lbk_agent_orchestrator` | Read-only questions from leadership ("who needs attention today?"). Routes to the others for actions. |

## 6. Wire the events (workflows)
Option A — webhooks (recommended): create an AgenticOrg workflow with a webhook trigger, then register it here:
```http
POST /api/v1/webhooks            X-API-Key: <admin key>
{"target_url": "<AgenticOrg webhook URL>", "event_types": ["DOCUMENTS_COMPLETE","FINANCIAL_ANALYSIS_COMPLETED","APPLICATION_SUBMITTED","HEALTH_STATUS_CHANGED","CONSENT_GIVEN","DOCUMENT_RECEIVED"]}
```
Each delivery is signed: `X-Landbank-Signature = HMAC-SHA256(secret, raw body)`.

Option B — polling: `GET /api/v1/events?since_id=<last id>`.

| Event received | Start this agent / step |
|---|---|
| `CONSENT_GIVEN` | Application agent → `fetchDocuments`, `validateDocuments` |
| `DOCUMENT_RECEIVED` | Application agent → `validateDocuments` |
| `DOCUMENTS_COMPLETE` | Financial Analysis agent → `runFinancialAnalysis` |
| `FINANCIAL_ANALYSIS_COMPLETED` | Credit Case agent → `prepareCreditCase` |
| `APPLICATION_SUBMITTED` | HITL approval node → credit officer decides in the LANDBANK console |
| `HEALTH_STATUS_CHANGED` | Portfolio agent → alert + RM task (or Growth agent if it became HEALTHY) |
| Schedule: daily 07:00 PHT | Portfolio agent → `runPortfolioMonitoring` |
| Schedule: weekly | Growth agent → `listOpportunities` → `createRMLead` for the top items |

## 7. Test in shadow mode first
Run every agent in shadow mode against the 20 scenarios and compare with the expected outcomes in the README (e.g. 0015–0017 → HIGH alert; 0019 → mismatch flagged; 0002 → invoice financing). Switch to live only when they match.
Use `POST /api/v1/admin/reset` to start clean before each demo.
