# Early-Warning Rules (demo)

> SYNTHETIC DEMO CONTENT for the LANDBANK x Pine Labs AgenticOrg demo. Not actual LANDBANK policy.

| Rule | Name | How it is measured | Metric | WATCH threshold | HIGH threshold | Fires when value is |
|---|---|---|---|---|---|---|
| `INFLOW_DECLINE` | Bank inflow decline | Average monthly customer receipts in the last 2 complete months vs the 3 months before. | `inflow_change_pct` | -10 | -25 | at or below |
| `TAX_SALES_DECLINE` | Declared sales decline (BIR VAT return) | Gross sales in the latest quarterly VAT return vs the previous quarter. | `tax_sales_change_pct` | -10 | -25 | at or below |
| `BALANCE_DECLINE` | Average balance decline | Average account balance in the last 2 complete months vs the 3 months before. | `avg_balance_change_pct` | -15 | -35 | at or below |
| `DAYS_PAST_DUE` | Repayment delay | Maximum days past due across all loans. | `days_past_due` | 1 | 30 | at or above |
| `LIMIT_UTILISATION` | High credit-line utilisation | Outstanding / sanctioned limit on working-capital lines (%). | `utilisation_pct` | 85 | 95 | at or above |
| `RETURNED_CHECKS` | Returned checks | Number of returned (bounced) checks in the last 90 days. | `returned_checks_90d` | 2 | 3 | at or above |
| `CASHFLOW_MARGIN` | Thin operating cash margin | (Inflows - outflows) / inflows in the last 2 complete months (%). | `cash_margin_pct` | 8 | 3 | at or below |

**Health status**
- `HIGH_ATTENTION`: days past due of 30 or more, or two or more HIGH signals.
- `WATCH`: any signal fired.
- `HEALTHY`: no signals.

**Recommended human actions**
- HIGH_ATTENTION: RM outreach within 2 business days; understand the cash position before any restructuring discussion.
- WATCH: RM check-in within 7 days; review again after the next month's data.
