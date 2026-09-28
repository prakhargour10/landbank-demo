# MSME Loan Document Checklist (demo)

> SYNTHETIC DEMO CONTENT for the LANDBANK x Pine Labs AgenticOrg demo. Not actual LANDBANK policy.

| Code | Document | Normal source | Required | Why we need it |
|---|---|---|---|---|
| `BUSINESS_REGISTRATION` | DTI / SEC / CDA registration certificate | Registry (consent fetch) | Yes | Proof the business is legally registered. |
| `MAYORS_PERMIT` | Mayor's / Business Permit (current year) | Upload by MSME | Yes | Local government permit to operate. |
| `BIR_COR` | BIR Certificate of Registration (Form 2303) | Upload by MSME | Yes | Tax registration and tax type (VAT / non-VAT). |
| `BANK_STATEMENTS_12M` | Bank statements - last 12 months | Bank data (consent fetch) | Yes | Used to rebuild cash flows. |
| `VAT_RETURNS` | BIR quarterly VAT returns (Form 2550Q) - last 4 quarters | Tax data (consent fetch) | Yes | Declared sales, compared with bank inflows. |
| `ITR_ANNUAL` | Annual Income Tax Return (BIR 1701 / 1702) | Upload by MSME | Yes | Declared annual income. |
| `AUDITED_FS` | Audited financial statements (8 pages) | Upload by MSME | Yes | Balance sheet and income statement. |
| `CREDIT_REPORT` | Credit report (CIC) | Credit bureau (consent fetch) | Yes | Existing obligations and repayment history. |

Validation rules: every required document present; audited financial statements must have all 8 pages;
BIR declared sales are compared with customer receipts in bank statements for the same months (tolerance ±15%).
