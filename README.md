# LANDBANK MSME Lending — Agent Data Service

A Python (FastAPI) + PostgreSQL back end with a LANDBANK-themed web console. It holds **synthetic** data for 20 Philippine MSMEs and gives Pine Labs **AgenticOrg** agents every API they need for the MSME lending journeys: application, financial analysis, credit case, human decision, portfolio monitoring, early warning and growth.

> All data is synthetic. Names, TINs, registration numbers and account numbers are invented. Policies and thresholds are illustrative, not actual LANDBANK policy.

## What's inside

```
backend/
  app/            FastAPI service (routers/api.py = every endpoint; operationId = AgenticOrg tool name)
  seed/           synthetic data generator (20 MSMEs, 12 months of transactions) + loader
  tools/          export_api_catalog.py (API list + Grantex manifests), export_knowledge_base.py
  tests/          end-to-end journey test
db/schema.sql     PostgreSQL schema (schema "lb")
frontend/         LANDBANK-themed console (plain HTML/CSS/JS, served by the API at /)
docs/             AGENTICORG_API_LIST.md, AGENTICORG_SETUP.md
grantex_manifests/  one tool-permission manifest per agent
knowledge_base/   credit policy, products, early-warning rules, document checklist, agent playbook (upload to AgenticOrg)
```

## Run it

**Option A: Docker (easiest)**
```bash
docker compose up --build
# console: http://localhost:8000   API docs: http://localhost:8000/docs   OpenAPI: http://localhost:8000/openapi.json
```

**Option B: local Python 3.11+ and PostgreSQL 16**
```bash
createdb landbank
cd backend
pip install -r requirements.txt
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/landbank
python -m seed.load                      # creates schema + synthetic data
uvicorn app.main:app --reload --port 8000
```

Re-seed at any time: `POST /api/v1/admin/reset` (admin key) or `python -m seed.load`.
Run the journey test (it resets the data): `cd backend && pytest -q tests/test_journey.py`.

## Authentication

Every call sends `X-API-Key`. Default demo keys (override with the `API_KEYS` env var in any real deployment):

| Key | Actor | Used by |
|---|---|---|
| `lbk_agent_application` | MSME Application Agent | AgenticOrg |
| `lbk_agent_financial` | Financial Analysis Agent | AgenticOrg |
| `lbk_agent_creditcase` | Credit Case Agent | AgenticOrg |
| `lbk_agent_portfolio` | Portfolio Intelligence Agent | AgenticOrg |
| `lbk_agent_growth` | RM & Growth Agent | AgenticOrg |
| `lbk_agent_orchestrator` | Orchestrator | AgenticOrg |
| `lbk_human_applicant` / `_rm` / `_credit_officer` / `_loan_ops` / `_admin` | People | Web console |

**Human-only endpoints** (consent grant, upload, submit, credit decisions, loan activation, closing alerts/tasks/leads) return **403 for agent keys**, so "AI prepares, people decide" is enforced by the service itself, not only by Grantex.

## The 20 synthetic MSMEs

| Scenario | Customers | Use it to show |
|---|---|---|
| Healthy & growing (cross-sell) | 0001–0009 | Opportunities and RM leads (e.g. 0002 → invoice financing, 0003 → trade finance) |
| Watch (slow decline) | 0010–0014 | Early warning: falling inflows, thin margin, high utilisation, a late payment, returned checks |
| High attention | 0015–0017 | Repayment 41 days late, line 97% used, receipts down 26–34% |
| Application: missing documents | 0018 (APP-2026-0002) | ITR missing; audited FS pages 7–8 missing |
| Application: declared vs bank mismatch | 0019 (APP-2026-0003) | BIR VAT sales ~25% above bank receipts |
| Application: under review | 0020 (APP-2026-0004) | Complete credit case waiting for the credit officer |
| Full journey from scratch | 0001 (APP-2026-0001) | Draft → consent → documents → analysis → case → decision → loan |

Philippine context: amounts in PHP; BIR 2550Q/2551Q quarterly returns and 1701/1702 annual ITR; CIC-style credit report; DTI/SEC/CDA registration; InstaPay, PESONet, QR Ph and check channels.

Demo tip: `POST /api/v1/admin/customers/{id}/apply-stress` (or the "Demo: apply stress" button as Admin) makes a healthy customer deteriorate so the Portfolio agent can catch it live.

## For the AgenticOrg set-up

Read **docs/AGENTICORG_SETUP.md** and **docs/AGENTICORG_API_LIST.md**. Regenerate them after changing endpoints:
```bash
cd backend && python -m tools.export_api_catalog && python -m tools.export_knowledge_base
```
