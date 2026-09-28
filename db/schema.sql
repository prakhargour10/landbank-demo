-- LANDBANK MSME Lending · Demo Data Service
-- PostgreSQL schema. All data in this database is SYNTHETIC.
-- Amounts are in Philippine pesos (PHP), stored as NUMERIC(16,2).

DROP SCHEMA IF EXISTS lb CASCADE;
CREATE SCHEMA lb;
SET search_path TO lb, public;

-- ---------------------------------------------------------------------------
-- Reference data (also exported as knowledge-base documents)
-- ---------------------------------------------------------------------------
CREATE TABLE relationship_managers (
    rm_id        TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    region       TEXT NOT NULL,
    email        TEXT NOT NULL,
    mobile       TEXT NOT NULL
);

CREATE TABLE products (
    product_code  TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    category      TEXT NOT NULL,          -- CREDIT | PAYMENTS | DEPOSITS | SERVICES | INSURANCE
    is_credit     BOOLEAN NOT NULL DEFAULT FALSE,
    description   TEXT NOT NULL,
    min_amount    NUMERIC(16,2),
    max_amount    NUMERIC(16,2),
    indicative_rate_pct NUMERIC(5,2)
);

CREATE TABLE ews_rules (
    rule_code     TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL,
    metric        TEXT NOT NULL,
    watch_threshold  NUMERIC(10,2) NOT NULL,
    high_threshold   NUMERIC(10,2) NOT NULL,
    direction     TEXT NOT NULL CHECK (direction IN ('BELOW','ABOVE'))  -- signal fires when metric is BELOW/ABOVE threshold
);

CREATE TABLE document_types (
    doc_type      TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    source        TEXT NOT NULL,          -- where the data normally comes from
    required      BOOLEAN NOT NULL DEFAULT TRUE,
    description   TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Customers and relationship data
-- ---------------------------------------------------------------------------
CREATE TABLE customers (
    customer_id      TEXT PRIMARY KEY,               -- e.g. LB-MSME-0001
    business_name    TEXT NOT NULL,
    trade_name       TEXT,
    owner_name       TEXT NOT NULL,
    legal_form       TEXT NOT NULL,                  -- SOLE_PROPRIETOR | PARTNERSHIP | CORPORATION | COOPERATIVE
    registration_body TEXT NOT NULL,                 -- DTI | SEC | CDA
    registration_no  TEXT NOT NULL,
    tin              TEXT NOT NULL,                  -- BIR Tax Identification Number (synthetic)
    sector           TEXT NOT NULL,
    region           TEXT NOT NULL,
    province         TEXT NOT NULL,
    city             TEXT NOT NULL,
    address          TEXT NOT NULL,
    mobile           TEXT NOT NULL,
    email            TEXT NOT NULL,
    customer_since   DATE NOT NULL,
    business_start   DATE NOT NULL,
    employees        INT NOT NULL,
    rm_id            TEXT NOT NULL REFERENCES relationship_managers(rm_id),
    kyc_status       TEXT NOT NULL DEFAULT 'VERIFIED',
    health_status    TEXT NOT NULL DEFAULT 'HEALTHY' CHECK (health_status IN ('HEALTHY','WATCH','HIGH_ATTENTION')),
    scenario         TEXT NOT NULL,                  -- synthetic scenario tag (for testing/QA only)
    scenario_note    TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE accounts (
    account_id     TEXT PRIMARY KEY,
    customer_id    TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    account_type   TEXT NOT NULL,                    -- CURRENT | SAVINGS
    account_no_masked TEXT NOT NULL,
    opened_on      DATE NOT NULL,
    current_balance NUMERIC(16,2) NOT NULL,
    status         TEXT NOT NULL DEFAULT 'ACTIVE'
);

CREATE TABLE transactions (
    txn_id        BIGSERIAL PRIMARY KEY,
    account_id    TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    customer_id   TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    txn_date      DATE NOT NULL,
    direction     TEXT NOT NULL CHECK (direction IN ('CREDIT','DEBIT')),
    amount        NUMERIC(16,2) NOT NULL CHECK (amount > 0),
    category      TEXT NOT NULL,   -- CUSTOMER_RECEIPT | SUPPLIER_PAYMENT | PAYROLL | RENT_UTILITIES | TAXES | LOAN_REPAYMENT | OWNER_DRAWINGS | OTHER_INCOME | RETURNED_CHECK | OTHER_EXPENSE
    channel       TEXT NOT NULL,   -- INSTAPAY | PESONET | QRPH | CHECK | CASH | AUTO_DEBIT | CARD
    counterparty  TEXT NOT NULL,
    narration     TEXT NOT NULL,
    balance_after NUMERIC(16,2)
);
CREATE INDEX ix_txn_customer_date ON transactions(customer_id, txn_date);

CREATE TABLE tax_filings (   -- BIR returns (synthetic)
    filing_id      BIGSERIAL PRIMARY KEY,
    customer_id    TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    form_code      TEXT NOT NULL,        -- 2550Q (quarterly VAT) | 2551Q (percentage tax) | 1701 / 1702 (annual ITR)
    period_label   TEXT NOT NULL,        -- e.g. 2026-Q2 or FY2025
    period_start   DATE NOT NULL,
    period_end     DATE NOT NULL,
    declared_gross_sales NUMERIC(16,2) NOT NULL,
    tax_due        NUMERIC(16,2) NOT NULL,
    filed_on       DATE,
    status         TEXT NOT NULL         -- FILED | LATE | NOT_FILED
);

CREATE TABLE credit_reports (   -- CIC-style credit report (synthetic)
    customer_id        TEXT PRIMARY KEY REFERENCES customers(customer_id) ON DELETE CASCADE,
    bureau             TEXT NOT NULL DEFAULT 'CIC (synthetic)',
    score              INT NOT NULL,       -- 300..850
    score_band         TEXT NOT NULL,
    active_facilities  INT NOT NULL,
    total_outstanding  NUMERIC(16,2) NOT NULL,
    max_dpd_12m        INT NOT NULL,
    inquiries_6m       INT NOT NULL,
    report_date        DATE NOT NULL
);

CREATE TABLE loans (
    loan_id         TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    product_code    TEXT NOT NULL REFERENCES products(product_code),
    sanctioned_amount NUMERIC(16,2) NOT NULL,
    outstanding     NUMERIC(16,2) NOT NULL,
    interest_rate_pct NUMERIC(5,2) NOT NULL,
    tenure_months   INT NOT NULL,
    monthly_amortization NUMERIC(16,2) NOT NULL,
    disbursed_on    DATE NOT NULL,
    maturity_date   DATE NOT NULL,
    days_past_due   INT NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'ACTIVE',   -- ACTIVE | CLOSED
    application_id  TEXT
);

CREATE TABLE repayments (
    repayment_id   BIGSERIAL PRIMARY KEY,
    loan_id        TEXT NOT NULL REFERENCES loans(loan_id) ON DELETE CASCADE,
    due_date       DATE NOT NULL,
    amount_due     NUMERIC(16,2) NOT NULL,
    paid_date      DATE,
    amount_paid    NUMERIC(16,2) NOT NULL DEFAULT 0,
    status         TEXT NOT NULL      -- PAID | PAID_LATE | OVERDUE | UPCOMING
);

CREATE TABLE product_holdings (
    customer_id    TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    product_code   TEXT NOT NULL REFERENCES products(product_code),
    since          DATE NOT NULL,
    PRIMARY KEY (customer_id, product_code)
);

-- ---------------------------------------------------------------------------
-- Consent, applications and documents
-- ---------------------------------------------------------------------------
CREATE TABLE consents (
    consent_id     TEXT PRIMARY KEY,
    customer_id    TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    purpose        TEXT NOT NULL,
    data_scopes    TEXT[] NOT NULL,       -- BANK_TRANSACTIONS, TAX_FILINGS, CREDIT_REPORT, BUSINESS_REGISTRATION
    status         TEXT NOT NULL,         -- REQUESTED | GRANTED | DECLINED | REVOKED | EXPIRED
    requested_by   TEXT NOT NULL,
    requested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at     TIMESTAMPTZ,
    expires_at     TIMESTAMPTZ
);

CREATE TABLE applications (
    application_id   TEXT PRIMARY KEY,               -- e.g. APP-2026-0001
    customer_id      TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    product_code     TEXT NOT NULL REFERENCES products(product_code),
    amount_requested NUMERIC(16,2) NOT NULL,
    tenure_months    INT NOT NULL,
    purpose          TEXT NOT NULL,
    status           TEXT NOT NULL,
    consent_id       TEXT REFERENCES consents(consent_id),
    assigned_officer TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    submitted_at     TIMESTAMPTZ,
    decision         TEXT,
    decision_by      TEXT,
    decision_reason  TEXT,
    decided_at       TIMESTAMPTZ
);

CREATE TABLE documents (
    document_id     TEXT PRIMARY KEY,
    application_id  TEXT NOT NULL REFERENCES applications(application_id) ON DELETE CASCADE,
    customer_id     TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    doc_type        TEXT NOT NULL REFERENCES document_types(doc_type),
    source          TEXT NOT NULL,       -- CONSENT_FETCH | UPLOAD | SEED
    status          TEXT NOT NULL,       -- REQUESTED | RECEIVED | VALIDATED | ISSUE_FOUND
    file_name       TEXT,
    pages_expected  INT,
    pages_received  INT,
    extracted       JSONB NOT NULL DEFAULT '{}'::jsonb,   -- structured values "read" from the document
    issues          JSONB NOT NULL DEFAULT '[]'::jsonb,
    requested_reason TEXT,
    received_at     TIMESTAMPTZ,
    validated_at    TIMESTAMPTZ
);

CREATE TABLE financial_analyses (
    analysis_id     TEXT PRIMARY KEY,
    application_id  TEXT REFERENCES applications(application_id) ON DELETE CASCADE,
    customer_id     TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    metrics         JSONB NOT NULL,
    monthly         JSONB NOT NULL,
    insights        JSONB NOT NULL,
    product_fit     JSONB NOT NULL,
    confidence      NUMERIC(4,2) NOT NULL,
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE credit_cases (
    case_id         TEXT PRIMARY KEY,
    application_id  TEXT NOT NULL REFERENCES applications(application_id) ON DELETE CASCADE,
    readiness_score INT NOT NULL,
    factor_scores   JSONB NOT NULL,
    evidence        JSONB NOT NULL,
    strengths       JSONB NOT NULL,
    risks           JSONB NOT NULL,
    review_questions JSONB NOT NULL,
    narrative       TEXT,                -- written by the Credit Case Agent
    confidence      NUMERIC(4,2) NOT NULL,
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Monitoring, alerts, RM work
-- ---------------------------------------------------------------------------
CREATE TABLE signal_snapshots (
    snapshot_id     BIGSERIAL PRIMARY KEY,
    customer_id     TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    as_of           DATE NOT NULL,
    metrics         JSONB NOT NULL,
    signals         JSONB NOT NULL,
    health_status   TEXT NOT NULL,
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE risk_alerts (
    alert_id        TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    severity        TEXT NOT NULL CHECK (severity IN ('WATCH','HIGH')),
    signals         JSONB NOT NULL,
    summary         TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'OPEN',   -- OPEN | IN_PROGRESS | RESOLVED | ESCALATED
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_by     TEXT,
    resolution_note TEXT,
    resolved_at     TIMESTAMPTZ
);

CREATE TABLE opportunities (
    opportunity_id  TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    product_code    TEXT NOT NULL REFERENCES products(product_code),
    confidence      NUMERIC(4,2) NOT NULL,
    estimated_value NUMERIC(16,2) NOT NULL,
    reasons         JSONB NOT NULL,
    status          TEXT NOT NULL DEFAULT 'OPEN',   -- OPEN | LEAD_CREATED | DISMISSED
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE rm_tasks (
    task_id         TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    rm_id           TEXT NOT NULL REFERENCES relationship_managers(rm_id),
    task_type       TEXT NOT NULL,        -- RISK_OUTREACH | DOCUMENT_FOLLOW_UP | GROWTH_CONVERSATION | OTHER
    title           TEXT NOT NULL,
    details         TEXT NOT NULL,
    priority        TEXT NOT NULL,        -- HIGH | MEDIUM | LOW
    due_date        DATE NOT NULL,
    status          TEXT NOT NULL DEFAULT 'OPEN',   -- OPEN | IN_PROGRESS | DONE | CANCELLED
    related_alert_id TEXT REFERENCES risk_alerts(alert_id),
    outcome_note    TEXT,
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE rm_leads (
    lead_id         TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    rm_id           TEXT NOT NULL REFERENCES relationship_managers(rm_id),
    product_code    TEXT NOT NULL REFERENCES products(product_code),
    opportunity_id  TEXT REFERENCES opportunities(opportunity_id),
    reason          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'NEW',    -- NEW | CONTACTED | WON | LOST | LATER
    outcome_note    TEXT,
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Events, webhooks and audit (single source of truth for every state change)
-- ---------------------------------------------------------------------------
CREATE TABLE events (
    event_id        BIGSERIAL PRIMARY KEY,
    event_type      TEXT NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_type      TEXT NOT NULL,        -- AGENT | HUMAN | SYSTEM
    actor_name      TEXT NOT NULL,
    customer_id     TEXT,
    application_id  TEXT,
    loan_id         TEXT,
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence      NUMERIC(4,2)
);
CREATE INDEX ix_events_type ON events(event_type);
CREATE INDEX ix_events_customer ON events(customer_id);

CREATE TABLE webhook_subscriptions (
    subscription_id TEXT PRIMARY KEY,
    target_url      TEXT NOT NULL,
    event_types     TEXT[] NOT NULL,      -- use {'*'} for all
    secret          TEXT,
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    cursor_event_id BIGINT NOT NULL DEFAULT 0,     -- last event delivered (new subscriptions start at the current max)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE webhook_deliveries (
    delivery_id     BIGSERIAL PRIMARY KEY,
    subscription_id TEXT NOT NULL REFERENCES webhook_subscriptions(subscription_id) ON DELETE CASCADE,
    event_id        BIGINT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    status_code     INT,
    error           TEXT,
    delivered_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (
    audit_id        BIGSERIAL PRIMARY KEY,
    at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_type      TEXT NOT NULL,
    actor_name      TEXT NOT NULL,
    method          TEXT NOT NULL,
    path            TEXT NOT NULL,
    tool_name       TEXT,
    status_code     INT NOT NULL,
    customer_id     TEXT,
    application_id  TEXT,
    request_summary JSONB
);

CREATE TABLE sim_state (
    id              INT PRIMARY KEY DEFAULT 1,
    as_of_date      DATE NOT NULL,
    months_advanced INT NOT NULL DEFAULT 0
);
