"""Synthetic data generator for the LANDBANK MSME demo.

Everything here is invented. Business names, people, TINs, registration numbers and account
numbers are fictitious. The generator is deterministic (fixed random seed) so every reset
produces exactly the same data.

Usage:
    python -m seed.generate > ../db/seed.sql          # write SQL
    (or use `python -m seed.load` to create schema + seed + post-seed steps in one go)
"""
import math
import random
import sys
from datetime import date, timedelta

AS_OF = date(2026, 9, 15)
FIRST_MONTH = date(2025, 9, 1)       # month index 0
N_MONTHS = 12                        # Sep 2025 .. Aug 2026 are complete months; Sep 2026 is partial
RNG = random.Random(20260915)


def month_date(m: int) -> date:
    y, mm = divmod(FIRST_MONTH.month - 1 + m, 12)
    return date(FIRST_MONTH.year + y, mm + 1, 1)


def days_in_month(d: date) -> int:
    nxt = month_date_from(d, 1)
    return (nxt - d).days


def month_date_from(d: date, n: int) -> date:
    y, mm = divmod(d.month - 1 + n, 12)
    return date(d.year + y, mm + 1, 1)


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
RMS = [
    ("RM-001", "Jose Reyes", "Luzon", "jose.reyes@landbank-demo.ph", "+63 917 000 1101"),
    ("RM-002", "Ana Villanueva", "Luzon", "ana.villanueva@landbank-demo.ph", "+63 917 000 1102"),
    ("RM-003", "Carlo Mendoza", "Visayas", "carlo.mendoza@landbank-demo.ph", "+63 917 000 1103"),
    ("RM-004", "Liza Bautista", "Mindanao", "liza.bautista@landbank-demo.ph", "+63 917 000 1104"),
]

PRODUCTS = [
    # code, name, category, is_credit, description, min, max, rate
    ("CURRENT_ACCOUNT", "Business Current Account", "DEPOSITS", False, "Checking account for daily business collections and payments.", None, None, None),
    ("SAVINGS_ACCOUNT", "Business Savings Account", "DEPOSITS", False, "Interest-earning account for business reserves.", None, None, None),
    ("WORKING_CAPITAL", "Working Capital Credit Line", "CREDIT", True, "Revolving line for inventory, receivables and seasonal cash gaps.", 300000, 20000000, 8.50),
    ("TERM_LOAN", "Business Term Loan", "CREDIT", True, "Fixed-tenure loan for expansion, renovation or fixed assets.", 500000, 30000000, 9.00),
    ("AGRI_PRODUCTION_LOAN", "Agri-Production Loan", "CREDIT", True, "Seasonal financing for crop, livestock and fisheries production.", 100000, 10000000, 7.50),
    ("EQUIPMENT_FINANCING", "Equipment Financing", "CREDIT", True, "Financing for machinery, vehicles and processing equipment.", 300000, 15000000, 8.75),
    ("INVOICE_FINANCING", "Invoice Financing", "CREDIT", True, "Advance against receivables from established buyers.", 200000, 10000000, 9.50),
    ("TRADE_FINANCE", "Trade Finance & FX", "CREDIT", True, "Letters of credit, export packing credit and foreign-exchange services.", 500000, 25000000, 8.25),
    ("QRPH_MERCHANT", "QR Ph Merchant Acquiring", "PAYMENTS", False, "Accept QR Ph and card payments in-store and online.", None, None, None),
    ("CASH_MANAGEMENT", "Cash Management Services", "SERVICES", False, "Collections, bulk payments and liquidity tools.", None, None, None),
    ("PAYROLL_SERVICE", "Payroll Service", "SERVICES", False, "Automated payroll credit to employee accounts.", None, None, None),
    ("BUSINESS_CREDIT_CARD", "Business Credit Card", "CREDIT", True, "Card for business purchases and supplier payments.", 50000, 2000000, 24.00),
    ("AGRI_INSURANCE", "Crop & Livestock Insurance (partner)", "INSURANCE", False, "Protection against typhoon, flood, drought and disease losses.", None, None, None),
]

EWS_RULES = [
    ("INFLOW_DECLINE", "Bank inflow decline", "Average monthly customer receipts in the last 2 complete months vs the 3 months before.", "inflow_change_pct", -10, -25, "BELOW"),
    ("TAX_SALES_DECLINE", "Declared sales decline (BIR VAT return)", "Gross sales in the latest quarterly VAT return vs the previous quarter.", "tax_sales_change_pct", -10, -25, "BELOW"),
    ("BALANCE_DECLINE", "Average balance decline", "Average account balance in the last 2 complete months vs the 3 months before.", "avg_balance_change_pct", -15, -35, "BELOW"),
    ("DAYS_PAST_DUE", "Repayment delay", "Maximum days past due across all loans.", "days_past_due", 1, 30, "ABOVE"),
    ("LIMIT_UTILISATION", "High credit-line utilisation", "Outstanding / sanctioned limit on working-capital lines (%).", "utilisation_pct", 85, 95, "ABOVE"),
    ("RETURNED_CHECKS", "Returned checks", "Number of returned (bounced) checks in the last 90 days.", "returned_checks_90d", 2, 3, "ABOVE"),
    ("CASHFLOW_MARGIN", "Thin operating cash margin", "(Inflows - outflows) / inflows in the last 2 complete months (%).", "cash_margin_pct", 8, 3, "BELOW"),
]

DOC_TYPES = [
    ("BUSINESS_REGISTRATION", "DTI / SEC / CDA registration certificate", "Registry (consent fetch)", True, "Proof the business is legally registered."),
    ("MAYORS_PERMIT", "Mayor's / Business Permit (current year)", "Upload by MSME", True, "Local government permit to operate."),
    ("BIR_COR", "BIR Certificate of Registration (Form 2303)", "Upload by MSME", True, "Tax registration and tax type (VAT / non-VAT)."),
    ("BANK_STATEMENTS_12M", "Bank statements - last 12 months", "Bank data (consent fetch)", True, "Used to rebuild cash flows."),
    ("VAT_RETURNS", "BIR quarterly VAT returns (Form 2550Q) - last 4 quarters", "Tax data (consent fetch)", True, "Declared sales, compared with bank inflows."),
    ("ITR_ANNUAL", "Annual Income Tax Return (BIR 1701 / 1702)", "Upload by MSME", True, "Declared annual income."),
    ("AUDITED_FS", "Audited financial statements (8 pages)", "Upload by MSME", True, "Balance sheet and income statement."),
    ("CREDIT_REPORT", "Credit report (CIC)", "Credit bureau (consent fetch)", True, "Existing obligations and repayment history."),
]

# ---------------------------------------------------------------------------
# The 20 synthetic MSMEs and their scenarios
# ---------------------------------------------------------------------------
# decline: 0 = none. Otherwise strength of the drop in the last 4 months.
# stick: how much supplier payments stay at "normal" levels when sales fall (squeezes margin).
C = [
    # id, business, owner, legal, sector, region, province, city, annual_rev, growth/mo, decline, stick, scenario, note, rm, holdings(extra), since, start
    ("0001", "Dela Cruz Rice Mill Corp.", "Ramon Dela Cruz", "CORPORATION", "Rice milling", "Region III - Central Luzon", "Nueva Ecija", "Cabanatuan City", 38_000_000, 0.020, 0, 0.0, "HEALTHY_GROWTH", "Strong growth, no working-capital line. Full end-to-end application demo (APP-2026-0001).", "RM-001", ["TERM_LOAN"], "2016-03-14", "2009-06-01"),
    ("0002", "Batangas Barako Coffee Traders", "Liza Macaraig", "SOLE_PROPRIETOR", "Coffee trading", "Region IV-A - CALABARZON", "Batangas", "Lipa City", 21_000_000, 0.018, 0, 0.0, "HEALTHY_GROWTH", "Growing sales to cafes on 30-day terms; invoice financing fit.", "RM-002", ["TERM_LOAN", "QRPH_MERCHANT"], "2018-01-22", "2013-04-01"),
    ("0003", "Visayas Dried Mango Co.", "Paolo Uy", "CORPORATION", "Food processing (export)", "Region VII - Central Visayas", "Cebu", "Mandaue City", 55_000_000, 0.017, 0, 0.0, "HEALTHY_GROWTH", "Export growth to Korea and Japan; trade finance & FX fit.", "RM-003", ["WORKING_CAPITAL", "TERM_LOAN"], "2012-07-09", "2004-02-01"),
    ("0004", "Davao Cacao Growers Cooperative", "Evelyn Dumalagan", "COOPERATIVE", "Cacao farming & fermentation", "Region XI - Davao Region", "Davao del Sur", "Davao City", 17_000_000, 0.021, 0, 0.0, "HEALTHY_GROWTH", "Cooperative expanding fermentation capacity; equipment financing fit.", "RM-004", ["AGRI_PRODUCTION_LOAN"], "2017-05-30", "2011-08-01"),
    ("0005", "Bicol Pili Nut Delicacies", "Marites Obias", "SOLE_PROPRIETOR", "Food manufacturing", "Region V - Bicol", "Albay", "Legazpi City", 9_500_000, 0.019, 0, 0.0, "HEALTHY_GROWTH", "Growing walk-in and tourist sales, mostly cash; QR Ph merchant fit.", "RM-002", ["TERM_LOAN"], "2019-09-12", "2015-01-01"),
    ("0006", "Pampanga Poultry Farms Inc.", "Arnel Manalo", "CORPORATION", "Poultry", "Region III - Central Luzon", "Pampanga", "San Fernando City", 46_000_000, 0.015, 0, 0.0, "HEALTHY_GROWTH", "Stable growth; no crop & livestock insurance cover.", "RM-001", ["WORKING_CAPITAL", "AGRI_PRODUCTION_LOAN"], "2014-11-03", "2006-05-01"),
    ("0007", "Iloilo Fisherfolk Supply Hub", "Rodel Tanaleon", "PARTNERSHIP", "Fisheries supplies trading", "Region VI - Western Visayas", "Iloilo", "Iloilo City", 26_000_000, 0.016, 0, 0.0, "HEALTHY_GROWTH", "High volume of small collections; cash management fit.", "RM-003", ["TERM_LOAN"], "2015-02-17", "2010-03-01"),
    ("0008", "Benguet Highland Vegetables", "Grace Pucay", "SOLE_PROPRIETOR", "Vegetable consolidation", "CAR - Cordillera", "Benguet", "La Trinidad", 14_000_000, 0.017, 0, 0.0, "HEALTHY_GROWTH", "Growing workforce paid in cash; payroll service fit.", "RM-001", ["AGRI_PRODUCTION_LOAN"], "2020-06-08", "2016-09-01"),
    ("0009", "Laguna Coconut Processing Inc.", "Benjie Alcantara", "CORPORATION", "Coconut processing", "Region IV-A - CALABARZON", "Laguna", "San Pablo City", 32_000_000, 0.014, 0, 0.0, "HEALTHY_GROWTH", "Healthy; seasonal copra purchases create a cash gap; working-capital fit.", "RM-002", ["TERM_LOAN", "PAYROLL_SERVICE"], "2013-10-21", "2007-01-01"),
    ("0010", "Quezon City Printing Press", "Dennis Tan", "CORPORATION", "Commercial printing", "NCR - Metro Manila", "Metro Manila", "Quezon City", 24_000_000, 0.004, 0.18, 0.55, "WATCH", "Inflows down after losing a school-supplies contract.", "RM-002", ["WORKING_CAPITAL", "TERM_LOAN"], "2011-04-11", "2002-01-01"),
    ("0011", "Tarlac Sugar Traders", "Josephine Aquino", "SOLE_PROPRIETOR", "Sugar trading", "Region III - Central Luzon", "Tarlac", "Tarlac City", 19_000_000, 0.003, 0.14, 0.45, "WATCH", "Softer sales and working-capital line almost fully used.", "RM-001", ["WORKING_CAPITAL"], "2016-08-15", "2012-02-01"),
    ("0012", "Cagayan Valley Hardware", "Mark Balisi", "SOLE_PROPRIETOR", "Hardware retail", "Region II - Cagayan Valley", "Isabela", "Ilagan City", 16_000_000, 0.003, 0.12, 0.40, "WATCH", "Declining sales and one late repayment this month.", "RM-001", ["TERM_LOAN"], "2018-03-19", "2014-06-01"),
    ("0013", "Zamboanga Sardines Canning", "Hadja Salim", "CORPORATION", "Fish canning", "Region IX - Zamboanga Peninsula", "Zamboanga del Sur", "Zamboanga City", 42_000_000, 0.004, 0.20, 0.50, "WATCH", "Lower catch volumes; two returned checks.", "RM-004", ["WORKING_CAPITAL", "TERM_LOAN"], "2010-12-06", "1998-03-01"),
    ("0014", "Palawan Island Tours & Transport", "Nestor Abrina", "PARTNERSHIP", "Tourism & transport", "MIMAROPA", "Palawan", "Puerto Princesa City", 12_000_000, 0.005, 0.17, 0.55, "WATCH", "Off-season plus weather cancellations.", "RM-003", ["TERM_LOAN"], "2019-01-28", "2016-11-01"),
    ("0015", "Mindoro Banana Exporters", "Rogelio Castillo", "CORPORATION", "Banana export", "MIMAROPA", "Oriental Mindoro", "Calapan City", 36_000_000, 0.002, 0.34, 0.80, "HIGH_ATTENTION", "Typhoon damage and a lost export buyer; repayment 41 days late; line fully used.", "RM-003", ["WORKING_CAPITAL", "TERM_LOAN"], "2014-05-12", "2008-07-01"),
    ("0016", "Negros Sugarcane Hauling Services", "Ricardo Lacson", "CORPORATION", "Logistics (hauling)", "Region VI - Western Visayas", "Negros Occidental", "Bacolod City", 28_000_000, 0.002, 0.30, 0.75, "HIGH_ATTENTION", "Milling delays cut hauling income; three returned checks; repayment late.", "RM-003", ["WORKING_CAPITAL", "TERM_LOAN"], "2015-09-07", "2009-10-01"),
    ("0017", "Leyte Construction Supplies", "Imelda Bacarro", "SOLE_PROPRIETOR", "Construction supplies", "Region VIII - Eastern Visayas", "Leyte", "Tacloban City", 22_000_000, 0.001, 0.36, 0.80, "HIGH_ATTENTION", "Government project payments delayed; inflows down sharply; repayment 41 days late.", "RM-003", ["WORKING_CAPITAL"], "2017-02-13", "2012-05-01"),
    ("0018", "Santos Bakery & Cafe", "Carmela Santos", "SOLE_PROPRIETOR", "Bakery & cafe", "NCR - Metro Manila", "Metro Manila", "Marikina City", 11_000_000, 0.015, 0, 0.0, "APPLICATION_MISSING_DOCS", "Applying for a second branch; ITR missing and financial statements pages 7-8 missing (APP-2026-0002).", "RM-002", ["QRPH_MERCHANT"], "2020-02-10", "2017-03-01"),
    ("0019", "Ilocos Garlic Traders", "Ferdinand Agbayani", "SOLE_PROPRIETOR", "Garlic & onion trading", "Region I - Ilocos", "Ilocos Norte", "Laoag City", 18_000_000, 0.012, 0, 0.0, "APPLICATION_TAX_MISMATCH", "Declared VAT sales are about 25% higher than bank receipts (APP-2026-0003).", "RM-001", ["TERM_LOAN"], "2018-06-25", "2013-09-01"),
    ("0020", "Bulacan Furniture Makers", "Rosario Galang", "CORPORATION", "Furniture manufacturing", "Region III - Central Luzon", "Bulacan", "Meycauayan City", 30_000_000, 0.013, 0, 0.0, "APPLICATION_UNDER_REVIEW", "Complete application submitted for equipment financing (APP-2026-0004).", "RM-002", ["WORKING_CAPITAL", "TERM_LOAN"], "2012-01-16", "2005-04-01"),
]

BUYERS = {
    "default": ["Puregold Price Club", "SM Supermarket", "Robinsons Supermarket", "Local wholesaler", "Walk-in customers", "Online orders (QR Ph)", "Sari-sari store network"],
    "Food processing (export)": ["Hanyang Foods Co. (KR)", "Osaka Trading KK (JP)", "Duty-free distributor", "SM Supermarket"],
    "Banana export": ["Shanghai Fresh Imports (CN)", "Seoul Fruit Hub (KR)", "Local fruit wholesaler"],
    "Construction supplies": ["DPWH project contractor", "Municipal engineering office", "Local contractors"],
    "Logistics (hauling)": ["Victorias sugar mill", "La Carlota sugar mill", "Planters association"],
    "Tourism & transport": ["Tour operators", "Hotel partners", "Walk-in tourists"],
}
SUPPLIERS = ["Farm suppliers", "Palay farmers association", "Packaging supplier", "Fuel station", "Raw materials supplier", "Spare parts dealer", "Wholesale supplier"]


def q(v):
    """SQL literal."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(round(v, 2)) if isinstance(v, float) else str(v)
    if isinstance(v, date):
        return f"'{v.isoformat()}'"
    if isinstance(v, list):
        return "ARRAY[" + ",".join(q(x) for x in v) + "]::text[]"
    return "'" + str(v).replace("'", "''") + "'"


def insert(table, cols, rows, batch=400):
    out = []
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        vals = ",\n".join("(" + ",".join(q(r[c]) for c in cols) + ")" for r in chunk)
        out.append(f"INSERT INTO {table} ({','.join(cols)}) VALUES\n{vals};")
    return "\n".join(out)


def decline_mult(m, d):
    """Multiplier for month index m (0..12) given decline strength d. Drop starts in May 2026 (m=8)."""
    if d <= 0 or m < 8:
        return 1.0
    return {8: 1 - 0.2 * d, 9: 1 - 0.4 * d, 10: 1 - 1.0 * d, 11: 1 - 1.1 * d}.get(m, 1 - 1.15 * d)


def revenue(spec, m, noise=True):
    base = spec["annual"] / 12 * (1 + spec["g"]) ** (m - 5.5)
    season = 1 + 0.03 * math.sin((m + spec["phase"]) / 12 * 2 * math.pi)
    r = base * season * decline_mult(m, spec["decline"])
    if noise:
        r *= 1 + spec["noise"][m % len(spec["noise"])]
    return r


def amortization(principal, rate_pct, months):
    r = rate_pct / 100 / 12
    return principal * r / (1 - (1 + r) ** -months)


def build():
    rows = {k: [] for k in ["customers", "accounts", "transactions", "tax_filings", "credit_reports", "loans",
                            "repayments", "product_holdings"]}
    specs = []
    for (cid, name, owner, legal, sector, region, prov, city, annual, g, decline, stick, scen, note, rm, extra, since, start) in C:
        spec = dict(cid=f"LB-MSME-{cid}", name=name, owner=owner, legal=legal, sector=sector, region=region,
                    prov=prov, city=city, annual=annual, g=g, decline=decline, stick=stick, scenario=scen,
                    note=note, rm=rm, extra=extra, since=date.fromisoformat(since), start=date.fromisoformat(start),
                    phase=RNG.uniform(0, 12), noise=[RNG.uniform(-0.025, 0.025) for _ in range(13)])
        specs.append(spec)
        n = int(cid)
        reg_body = {"CORPORATION": "SEC", "COOPERATIVE": "CDA", "PARTNERSHIP": "SEC"}.get(legal, "DTI")
        employees = max(4, round(annual * 0.10 / 12 / 18000))
        spec["employees"] = employees
        rows["customers"].append(dict(
            customer_id=spec["cid"], business_name=name, trade_name=name.split(" Corp")[0].split(" Inc")[0],
            owner_name=owner, legal_form=legal, registration_body=reg_body,
            registration_no=f"{reg_body}-{2000000 + n * 7919}", tin=f"{100 + n:03d}-{400 + n * 3:03d}-{700 + n * 7:03d}-000",
            sector=sector, region=region, province=prov, city=city,
            address=f"{10 + n * 3} Rizal Avenue, {city}, {prov}", mobile=f"+63 9{17 + n % 3} 555 {1000 + n * 37:04d}",
            email=f"owner{n:02d}@{name.split()[0].lower()}-demo.ph", customer_since=spec["since"],
            business_start=spec["start"], employees=employees, rm_id=rm, kyc_status="VERIFIED",
            health_status={"WATCH": "WATCH", "HIGH_ATTENTION": "HIGH_ATTENTION"}.get(scen, "HEALTHY"),
            scenario=scen, scenario_note=note))

        acct = f"ACC-{spec['cid'][-4:]}-01"
        spec["account_id"] = acct
        # ------------------------------------------------------------------ loans
        loans = []
        if "TERM_LOAN" in extra:
            principal = round(annual * 0.18, -4)
            tenure = 48
            disb = date(2024, 3 + n % 6, 10)
            months_elapsed = (AS_OF.year - disb.year) * 12 + AS_OF.month - disb.month
            amort = amortization(principal, 9.0, tenure)
            r = 0.09 / 12
            outstanding = principal * (1 + r) ** months_elapsed - amort * (((1 + r) ** months_elapsed - 1) / r)
            loans.append(dict(loan_id=f"LN-{spec['cid'][-4:]}-TL", product="TERM_LOAN", sanctioned=principal,
                              outstanding=round(outstanding, 2), rate=9.0, tenure=tenure, amort=round(amort, 2),
                              disb=disb, maturity=month_date_from(disb, tenure)))
        for prod in ("AGRI_PRODUCTION_LOAN",):
            if prod in extra:
                principal = round(annual * 0.10, -4)
                amort = amortization(principal, 7.5, 24)
                loans.append(dict(loan_id=f"LN-{spec['cid'][-4:]}-AP", product=prod, sanctioned=principal,
                                  outstanding=round(principal * 0.55, 2), rate=7.5, tenure=24, amort=round(amort, 2),
                                  disb=date(2025, 6, 20), maturity=date(2027, 6, 20)))
        if "WORKING_CAPITAL" in extra:
            limit = round(annual * 0.15, -4)
            util = {"WATCH": 0.88, "HIGH_ATTENTION": 0.97}.get(scen, RNG.uniform(0.55, 0.72))
            if spec["cid"] == "LB-MSME-0010":
                util = 0.80
            if spec["cid"] == "LB-MSME-0013":
                util = 0.82
            outstanding = round(limit * util, 2)
            loans.append(dict(loan_id=f"LN-{spec['cid'][-4:]}-WC", product="WORKING_CAPITAL", sanctioned=limit,
                              outstanding=outstanding, rate=8.5, tenure=12, amort=round(outstanding * 0.085 / 12, 2),
                              disb=date(2025, 11, 5), maturity=date(2026, 11, 5)))
        spec["loans"] = loans

        # repayment behaviour
        overdue_from = None  # month index of the first unpaid due date
        late_months = set()
        if scen == "HIGH_ATTENTION":
            overdue_from = 11  # Aug 2026 due unpaid -> 41 DPD on 15 Sep
            late_months = {9, 10}
        elif spec["cid"] == "LB-MSME-0012":
            overdue_from = 12  # Sep 2026 due unpaid -> 10 DPD
            late_months = {10}
        elif scen == "WATCH":
            late_months = {10} if n % 2 else set()
        spec["overdue_from"], spec["late_months"] = overdue_from, late_months

        dpd = 0 if overdue_from is None else (AS_OF - (month_date(overdue_from) + timedelta(days=4))).days
        for ln in loans:
            rows["loans"].append(dict(loan_id=ln["loan_id"], customer_id=spec["cid"], product_code=ln["product"],
                                      sanctioned_amount=ln["sanctioned"], outstanding=ln["outstanding"],
                                      interest_rate_pct=ln["rate"], tenure_months=ln["tenure"],
                                      monthly_amortization=ln["amort"], disbursed_on=ln["disb"],
                                      maturity_date=ln["maturity"], days_past_due=dpd, status="ACTIVE",
                                      application_id=None))
            for m in range(0, 13):
                due = month_date(m) + timedelta(days=4)
                if due < ln["disb"] + timedelta(days=20):
                    continue
                if overdue_from is not None and m >= overdue_from:
                    status, paid, amt = "OVERDUE", None, 0
                elif m in late_months:
                    status, paid, amt = "PAID_LATE", due + timedelta(days=12 + n % 6), ln["amort"]
                else:
                    status, paid, amt = "PAID", due, ln["amort"]
                rows["repayments"].append(dict(loan_id=ln["loan_id"], due_date=due, amount_due=ln["amort"],
                                               paid_date=paid, amount_paid=amt, status=status))
            nxt = month_date(13) + timedelta(days=4)
            rows["repayments"].append(dict(loan_id=ln["loan_id"], due_date=nxt, amount_due=ln["amort"],
                                           paid_date=None, amount_paid=0, status="UPCOMING"))

        # ------------------------------------------------------------------ transactions
        buyers = BUYERS.get(sector, BUYERS["default"])
        opening = annual / 12 * 0.9
        balance = opening
        txns = []
        returned = {"LB-MSME-0013": [(11, 6), (12, 3)], "LB-MSME-0016": [(10, 22), (11, 14), (12, 8)]}.get(spec["cid"], [])
        vat_registered = annual > 3_000_000
        for m in range(0, 13):
            md = month_date(m)
            last_day = min(days_in_month(md), 14) if m == 12 else days_in_month(md)
            frac = last_day / days_in_month(md)
            rev = revenue(spec, m) * frac
            normal = revenue(spec, m, noise=False) / decline_mult(m, decline) * frac
            n_receipts = max(8, int(18 + annual / 3_000_000))
            weights = [RNG.uniform(0.5, 1.5) for _ in range(n_receipts)]
            tot = sum(weights)
            for w in weights:
                day = RNG.randint(1, last_day)
                ch = RNG.choice(["INSTAPAY", "PESONET", "QRPH", "CHECK", "CASH"] if "QRPH_MERCHANT" in extra or sector.startswith("Bakery") else ["INSTAPAY", "PESONET", "CHECK", "CASH"])
                txns.append((date(md.year, md.month, day), "CREDIT", rev * w / tot, "CUSTOMER_RECEIPT", ch, RNG.choice(buyers), "Collection from customer"))
            # suppliers: concentrated between the 8th and 18th (inventory purchases -> recurring cash gap)
            sup_total = 0.60 * (stick * normal + (1 - stick) * rev)
            n_sup = 6
            for k in range(n_sup):
                day = min(last_day, RNG.randint(8, 18) if k < 4 else RNG.randint(1, last_day))
                txns.append((date(md.year, md.month, day), "DEBIT", sup_total / n_sup * RNG.uniform(0.8, 1.2), "SUPPLIER_PAYMENT", RNG.choice(["PESONET", "INSTAPAY", "CHECK"]), RNG.choice(SUPPLIERS), "Supplier payment"))
            if last_day >= 15:
                txns.append((date(md.year, md.month, 15), "DEBIT", employees * 9000, "PAYROLL", "INSTAPAY", "Employees", "Payroll 1st half"))
            if last_day >= 28:
                txns.append((date(md.year, md.month, 28), "DEBIT", employees * 9000, "PAYROLL", "INSTAPAY", "Employees", "Payroll 2nd half"))
            txns.append((date(md.year, md.month, min(last_day, 3)), "DEBIT", annual / 12 * 0.035 * frac, "RENT_UTILITIES", "AUTO_DEBIT", "Landlord / utilities", "Rent, power and water"))
            if last_day >= 20:
                txns.append((date(md.year, md.month, 20), "DEBIT", annual / 12 * 0.04, "OWNER_DRAWINGS", "INSTAPAY", spec["owner"], "Owner drawings"))
            if md.month in (1, 4, 7, 10) and last_day >= 25:
                vat = (sum(revenue(spec, mm) for mm in range(m - 3, m)) / 1.12 * 0.12 * 0.30) if vat_registered else sum(revenue(spec, mm) for mm in range(m - 3, m)) * 0.03
                txns.append((date(md.year, md.month, 25), "DEBIT", vat, "TAXES", "PESONET", "Bureau of Internal Revenue", "BIR 2550Q VAT payment" if vat_registered else "BIR 2551Q percentage tax"))
            for ln in loans:
                due = md + timedelta(days=4)
                if due < ln["disb"] + timedelta(days=20):
                    continue
                if overdue_from is not None and m >= overdue_from:
                    continue
                pay_day = due + timedelta(days=12 + n % 6) if m in late_months else due
                if pay_day.month == md.month and pay_day.day <= last_day:
                    txns.append((pay_day, "DEBIT", ln["amort"], "LOAN_REPAYMENT", "AUTO_DEBIT", "LANDBANK Loans", f"Loan payment {ln['loan_id']}"))
            for (rm_, rd) in returned:
                if rm_ == m and rd <= last_day:
                    txns.append((date(md.year, md.month, rd), "DEBIT", 1000.0, "RETURNED_CHECK", "CHECK", "LANDBANK", "Returned check fee - DAIF (drawn against insufficient funds)"))
        txns.sort(key=lambda t: (t[0], 0 if t[1] == "CREDIT" else 1))
        for (d, direction, amt, cat, ch, cp, narr) in txns:
            amt = round(amt, 2)
            balance += amt if direction == "CREDIT" else -amt
            rows["transactions"].append(dict(account_id=acct, customer_id=spec["cid"], txn_date=d, direction=direction,
                                             amount=amt, category=cat, channel=ch, counterparty=cp, narration=narr,
                                             balance_after=round(balance, 2)))
        rows["accounts"].append(dict(account_id=acct, customer_id=spec["cid"], account_type="CURRENT",
                                     account_no_masked=f"XXXX-XXXX-{1000 + n * 17:04d}", opened_on=spec["since"],
                                     current_balance=round(balance, 2), status="ACTIVE"))

        # ------------------------------------------------------------------ BIR tax filings
        mismatch = 1.27 if scen == "APPLICATION_TAX_MISMATCH" else 1.0
        quarters = [("2025-Q3", -2), ("2025-Q4", 1), ("2026-Q1", 4), ("2026-Q2", 7)]  # (label, first month index)
        for i, (label, m0) in enumerate(quarters):
            sales = sum(revenue(spec, mm) for mm in range(m0, m0 + 3)) * mismatch * (1 + RNG.uniform(-0.01, 0.01))
            ps, pe = month_date(m0), month_date(m0 + 3) - timedelta(days=1)
            deadline = pe + timedelta(days=25)
            status, filed = "FILED", deadline - timedelta(days=RNG.randint(1, 10))
            if scen == "HIGH_ATTENTION" and i == 3:
                status, filed = "LATE", deadline + timedelta(days=18)
            rows["tax_filings"].append(dict(customer_id=spec["cid"], form_code="2550Q" if vat_registered else "2551Q",
                                            period_label=label, period_start=ps, period_end=pe,
                                            declared_gross_sales=round(sales, 2),
                                            tax_due=round(sales / 1.12 * 0.12 * 0.3 if vat_registered else sales * 0.03, 2),
                                            filed_on=filed, status=status))
        fy_sales = sum(revenue(spec, mm) for mm in range(-8, 4)) * mismatch
        rows["tax_filings"].append(dict(customer_id=spec["cid"], form_code="1702" if legal in ("CORPORATION", "COOPERATIVE", "PARTNERSHIP") else "1701",
                                        period_label="FY2025", period_start=date(2025, 1, 1), period_end=date(2025, 12, 31),
                                        declared_gross_sales=round(fy_sales, 2), tax_due=round(fy_sales * 0.12 * 0.25, 2),
                                        filed_on=date(2026, 4, 10), status="FILED"))

        # ------------------------------------------------------------------ credit report (CIC, synthetic)
        base_score = {"HEALTHY_GROWTH": 760, "WATCH": 668, "HIGH_ATTENTION": 574}.get(scen, 735)
        score = base_score + (n * 7) % 30
        band = "Excellent" if score >= 750 else "Good" if score >= 700 else "Fair" if score >= 640 else "Poor"
        rows["credit_reports"].append(dict(customer_id=spec["cid"], bureau="CIC (synthetic)", score=score, score_band=band,
                                           active_facilities=len(loans), total_outstanding=round(sum(l["outstanding"] for l in loans), 2),
                                           max_dpd_12m=dpd if dpd else (15 if late_months else 0), inquiries_6m=1 + n % 3,
                                           report_date=AS_OF))
        # ------------------------------------------------------------------ product holdings
        holdings = {"CURRENT_ACCOUNT"} | set(extra)
        for p in sorted(holdings):
            rows["product_holdings"].append(dict(customer_id=spec["cid"], product_code=p, since=spec["since"]))
    return rows, specs


def reference_sql():
    parts = [
        insert("relationship_managers", ["rm_id", "name", "region", "email", "mobile"],
               [dict(zip(["rm_id", "name", "region", "email", "mobile"], r)) for r in RMS]),
        insert("products", ["product_code", "name", "category", "is_credit", "description", "min_amount", "max_amount", "indicative_rate_pct"],
               [dict(zip(["product_code", "name", "category", "is_credit", "description", "min_amount", "max_amount", "indicative_rate_pct"], r)) for r in PRODUCTS]),
        insert("ews_rules", ["rule_code", "name", "description", "metric", "watch_threshold", "high_threshold", "direction"],
               [dict(zip(["rule_code", "name", "description", "metric", "watch_threshold", "high_threshold", "direction"], r)) for r in EWS_RULES]),
        insert("document_types", ["doc_type", "name", "source", "required", "description"],
               [dict(zip(["doc_type", "name", "source", "required", "description"], r)) for r in DOC_TYPES]),
    ]
    return "\n".join(parts)


def applications_sql():
    """Seed applications, consents and documents for the four application scenarios."""
    s = []
    s.append("""INSERT INTO consents (consent_id, customer_id, purpose, data_scopes, status, requested_by, requested_at, decided_at, expires_at) VALUES
('CNS-0001','LB-MSME-0018','Loan application APP-2026-0002',ARRAY['BANK_TRANSACTIONS','TAX_FILINGS','CREDIT_REPORT','BUSINESS_REGISTRATION']::text[],'GRANTED','MSME Application Agent','2026-09-08 09:10+08','2026-09-08 09:12+08','2026-12-07 09:12+08'),
('CNS-0002','LB-MSME-0019','Loan application APP-2026-0003',ARRAY['BANK_TRANSACTIONS','TAX_FILINGS','CREDIT_REPORT','BUSINESS_REGISTRATION']::text[],'GRANTED','MSME Application Agent','2026-09-10 14:00+08','2026-09-10 14:03+08','2026-12-09 14:03+08'),
('CNS-0003','LB-MSME-0020','Loan application APP-2026-0004',ARRAY['BANK_TRANSACTIONS','TAX_FILINGS','CREDIT_REPORT','BUSINESS_REGISTRATION']::text[],'GRANTED','MSME Application Agent','2026-09-02 10:00+08','2026-09-02 10:04+08','2026-12-01 10:04+08');""")
    s.append("""INSERT INTO applications (application_id, customer_id, product_code, amount_requested, tenure_months, purpose, status, consent_id, created_at, updated_at) VALUES
('APP-2026-0001','LB-MSME-0001','WORKING_CAPITAL',5000000,12,'Palay procurement for the main harvest season','DRAFT',NULL,'2026-09-14 08:30+08','2026-09-14 08:30+08'),
('APP-2026-0002','LB-MSME-0018','TERM_LOAN',2500000,36,'Open a second bakery & cafe branch in Pasig','WAITING_FOR_DOCUMENTS','CNS-0001','2026-09-08 09:05+08','2026-09-09 16:20+08'),
('APP-2026-0003','LB-MSME-0019','WORKING_CAPITAL',3000000,12,'Garlic and onion stock-up before the holiday season','DRAFT','CNS-0002','2026-09-10 13:55+08','2026-09-10 14:30+08'),
('APP-2026-0004','LB-MSME-0020','EQUIPMENT_FINANCING',4000000,36,'CNC router and kiln dryer for export orders','DOCUMENTS_COMPLETE','CNS-0003','2026-09-02 09:50+08','2026-09-04 11:00+08');""")
    docs = []
    full = ["BUSINESS_REGISTRATION", "MAYORS_PERMIT", "BIR_COR", "BANK_STATEMENTS_12M", "VAT_RETURNS", "ITR_ANNUAL", "AUDITED_FS", "CREDIT_REPORT"]
    src = {"BUSINESS_REGISTRATION": "CONSENT_FETCH", "BANK_STATEMENTS_12M": "CONSENT_FETCH", "VAT_RETURNS": "CONSENT_FETCH", "CREDIT_REPORT": "CONSENT_FETCH"}
    k = 0
    for app, cid, st_default in [("APP-2026-0002", "LB-MSME-0018", "VALIDATED"), ("APP-2026-0003", "LB-MSME-0019", "RECEIVED"), ("APP-2026-0004", "LB-MSME-0020", "VALIDATED")]:
        for dt in full:
            k += 1
            status, pages_exp, pages_rec, issues, reason = st_default, (8 if dt == "AUDITED_FS" else None), (8 if dt == "AUDITED_FS" else None), "[]", None
            if app == "APP-2026-0002" and dt == "ITR_ANNUAL":
                status, reason = "REQUESTED", "Annual ITR (BIR 1701) for FY2025 was not provided."
            if app == "APP-2026-0002" and dt == "AUDITED_FS":
                status, pages_rec = "ISSUE_FOUND", 6
                issues = '[{"severity":"BLOCKING","code":"MISSING_PAGES","message":"Audited financial statements: pages 7-8 of 8 are missing (notes to financial statements)."}]'
            received = None if status == "REQUESTED" else "'2026-09-0%d 10:00+08'" % (4 if app == "APP-2026-0004" else 9)
            validated = "'2026-09-09 16:20+08'" if status in ("VALIDATED", "ISSUE_FOUND") else "NULL"
            source = src.get(dt, "UPLOAD")
            fname = None if status == "REQUESTED" else f"{cid}_{dt}.pdf"
            docs.append(f"('DOC-{k:04d}','{app}','{cid}','{dt}','{source}','{status}',{q(fname)},{q(pages_exp)},{q(pages_rec)},'{issues}'::jsonb,{q(reason)},{received or 'NULL'},{validated})")
    s.append("INSERT INTO documents (document_id, application_id, customer_id, doc_type, source, status, file_name, pages_expected, pages_received, issues, requested_reason, received_at, validated_at) VALUES\n" + ",\n".join(docs) + ";")
    return "\n".join(s)


def build_sql():
    rows, _ = build()
    out = ["-- Synthetic seed data for LANDBANK MSME demo. Generated by seed/generate.py. DO NOT EDIT BY HAND.",
           "SET search_path TO lb, public;", reference_sql()]
    order = [
        ("customers", ["customer_id", "business_name", "trade_name", "owner_name", "legal_form", "registration_body", "registration_no", "tin", "sector", "region", "province", "city", "address", "mobile", "email", "customer_since", "business_start", "employees", "rm_id", "kyc_status", "health_status", "scenario", "scenario_note"]),
        ("accounts", ["account_id", "customer_id", "account_type", "account_no_masked", "opened_on", "current_balance", "status"]),
        ("transactions", ["account_id", "customer_id", "txn_date", "direction", "amount", "category", "channel", "counterparty", "narration", "balance_after"]),
        ("tax_filings", ["customer_id", "form_code", "period_label", "period_start", "period_end", "declared_gross_sales", "tax_due", "filed_on", "status"]),
        ("credit_reports", ["customer_id", "bureau", "score", "score_band", "active_facilities", "total_outstanding", "max_dpd_12m", "inquiries_6m", "report_date"]),
        ("loans", ["loan_id", "customer_id", "product_code", "sanctioned_amount", "outstanding", "interest_rate_pct", "tenure_months", "monthly_amortization", "disbursed_on", "maturity_date", "days_past_due", "status", "application_id"]),
        ("repayments", ["loan_id", "due_date", "amount_due", "paid_date", "amount_paid", "status"]),
        ("product_holdings", ["customer_id", "product_code", "since"]),
    ]
    for table, cols in order:
        out.append(insert(table, cols, rows[table]))
    out.append(applications_sql())
    out.append(f"INSERT INTO sim_state (id, as_of_date, months_advanced) VALUES (1, {q(AS_OF)}, 0);")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    sys.stdout.write(build_sql())
