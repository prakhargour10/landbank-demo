"""Write the knowledge-base documents that you upload to AgenticOrg (Knowledge Base / RAG).

    cd backend && python -m tools.export_knowledge_base

Products, early-warning rules and the document checklist are generated from the same constants
that seed the database, so what the agents read always matches what the APIs return.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from seed.generate import DOC_TYPES, EWS_RULES, PRODUCTS  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "..", "knowledge_base")
BANNER = "> SYNTHETIC DEMO CONTENT for the LANDBANK x Pine Labs AgenticOrg demo. Not actual LANDBANK policy.\n"


def peso(v):
    return "—" if v is None else f"PHP {v:,.0f}"


def main():
    os.makedirs(OUT, exist_ok=True)
    docs = {}
    docs["01_credit_policy.md"] = f"""# MSME Credit Policy (demo)

{BANNER}
## 1. Principles
- AI agents prepare, check and recommend. **Only named LANDBANK officers make credit decisions** (approve, decline, restructure, disburse).
- Customer data is read only with the MSME's consent, read-only, for the stated purpose, for up to 90 days (Data Privacy Act of 2012).
- Agents must never ask for passwords, PINs or OTPs.
- Every recommendation must show the data behind it and a confidence level.

## 2. Indicative eligibility (screening only)
| Check | Indicative guide |
|---|---|
| Business vintage | At least 2 years operating |
| Credit score (CIC) | 620 or higher |
| Account health | Not HIGH_ATTENTION (no repayment 30+ days late) |
| Debt-service coverage (DSCR) with the new facility | 1.25x or higher |
| Declared sales (BIR) vs bank receipts | Gap within ±15%; larger gaps need an explanation, not an automatic decline |

## 3. Required documents
See `04_document_checklist.md`. Missing pages or missing documents block submission. A sales mismatch is a **warning** that goes into the credit case as a risk and a review question.

## 4. Credit-readiness indicator (0–100)
Weighted: debt capacity 25%, cash-flow strength 20%, banking behaviour 20%, business stability 15%, documentation 10%, revenue consistency 10%.
It is a LANDBANK demo indicator, not a CIC or BSP-recognised score.

## 5. After disbursal
Every active borrower is monitored against the early-warning rules (`03_early_warning_rules.md`). Alerts lead to **human** outreach within 2 business days; agents never change loan terms.

## 6. Growth offers
Only for HEALTHY customers with no repayment delays. No new credit offers to HIGH_ATTENTION customers — route them to risk outreach instead.
"""
    rows = "\n".join(f"| `{p[0]}` | {p[1]} | {p[2]} | {'Yes' if p[3] else 'No'} | {peso(p[5])} – {peso(p[6])} | {p[7] or '—'} | {p[4]} |" for p in PRODUCTS)
    docs["02_product_catalogue.md"] = f"""# MSME Product Catalogue (demo)

{BANNER}
| Code | Product | Category | Credit | Amount range | Indicative rate % p.a. | Description |
|---|---|---|---|---|---|---|
{rows}
"""
    rows = "\n".join(f"| `{r[0]}` | {r[1]} | {r[2]} | `{r[3]}` | {r[4]} | {r[5]} | {'at or below' if r[6] == 'BELOW' else 'at or above'} |" for r in EWS_RULES)
    docs["03_early_warning_rules.md"] = f"""# Early-Warning Rules (demo)

{BANNER}
| Rule | Name | How it is measured | Metric | WATCH threshold | HIGH threshold | Fires when value is |
|---|---|---|---|---|---|---|
{rows}

**Health status**
- `HIGH_ATTENTION`: days past due of 30 or more, or two or more HIGH signals.
- `WATCH`: any signal fired.
- `HEALTHY`: no signals.

**Recommended human actions**
- HIGH_ATTENTION: RM outreach within 2 business days; understand the cash position before any restructuring discussion.
- WATCH: RM check-in within 7 days; review again after the next month's data.
"""
    rows = "\n".join(f"| `{d[0]}` | {d[1]} | {d[2]} | {'Yes' if d[3] else 'No'} | {d[4]} |" for d in DOC_TYPES)
    docs["04_document_checklist.md"] = f"""# MSME Loan Document Checklist (demo)

{BANNER}
| Code | Document | Normal source | Required | Why we need it |
|---|---|---|---|---|
{rows}

Validation rules: every required document present; audited financial statements must have all 8 pages;
BIR declared sales are compared with customer receipts in bank statements for the same months (tolerance ±15%).
"""
    docs["05_agent_playbook.md"] = f"""# Agent Playbook (demo)

{BANNER}
**MSME Application Agent** — check eligibility → request consent → fetch documents → validate → request anything missing, in plain language. Never reject.

**Financial Analysis Agent** — run the financial analysis once documents are complete. Quote the service's numbers; do not re-calculate. Explain patterns (e.g. the monthly cash gap) in simple words.

**Credit Case Agent** — prepare the credit case and write a short memo (5–6 sentences): who the business is, what they need, why the numbers support it, the main risks, and the one question the officer should ask. Always end with "Decision rests with the LANDBANK credit officer."

**Portfolio Intelligence Agent** — every day run portfolio monitoring. For each customer that needs attention and has no open alert: read the signals, write a 2–3 sentence brief with the actual numbers, create a risk alert and an RM task. Never recommend automatic loan actions.

**RM & Growth Agent** — for healthy customers only, turn the top opportunity into an RM lead with the reasons. For customers needing attention, create risk-outreach tasks instead of offers.
"""
    for name, text in docs.items():
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    print(f"{len(docs)} knowledge-base documents written to {os.path.abspath(OUT)}")


if __name__ == "__main__":
    main()
