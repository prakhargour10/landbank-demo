"""Runtime configuration (environment variables with demo-friendly defaults)."""
import json
import os
from datetime import date

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/landbank")
DB_SCHEMA = "lb"

# The synthetic data is generated "as of" this date. Monitoring windows are computed from it.
AS_OF_DATE = date.fromisoformat(os.getenv("AS_OF_DATE", "2026-09-15"))

# Demo mode exposes the human demo keys to the web console (/ui-config). Turn off outside demos.
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"

UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(os.path.dirname(__file__), "..", "data", "uploads"))

# ---------------------------------------------------------------------------
# API keys.  One key per AgenticOrg agent (actor_type AGENT) and one per human role.
# Override with API_KEYS='{"key": {"actor_type": "...", "actor_name": "...", "role": "..."}}'
# ---------------------------------------------------------------------------
DEFAULT_API_KEYS = {
    # --- AgenticOrg agents (register these as the connector credential for each agent) ---
    "lbk_agent_orchestrator": {"actor_type": "AGENT", "actor_name": "Orchestrator", "role": "agent"},
    "lbk_agent_application": {"actor_type": "AGENT", "actor_name": "MSME Application Agent", "role": "agent"},
    "lbk_agent_financial": {"actor_type": "AGENT", "actor_name": "Financial Analysis Agent", "role": "agent"},
    "lbk_agent_creditcase": {"actor_type": "AGENT", "actor_name": "Credit Case Agent", "role": "agent"},
    "lbk_agent_portfolio": {"actor_type": "AGENT", "actor_name": "Portfolio Intelligence Agent", "role": "agent"},
    "lbk_agent_growth": {"actor_type": "AGENT", "actor_name": "RM & Growth Agent", "role": "agent"},
    # --- Humans (used by the web console) ---
    "lbk_human_applicant": {"actor_type": "HUMAN", "actor_name": "MSME Owner (applicant)", "role": "applicant"},
    "lbk_human_rm": {"actor_type": "HUMAN", "actor_name": "Jose Reyes, Relationship Manager", "role": "rm"},
    "lbk_human_credit_officer": {"actor_type": "HUMAN", "actor_name": "Maria Santos, Credit Officer", "role": "credit_officer"},
    "lbk_human_loan_ops": {"actor_type": "HUMAN", "actor_name": "Loan Operations", "role": "loan_ops"},
    "lbk_human_admin": {"actor_type": "HUMAN", "actor_name": "Platform Admin", "role": "admin"},
}
API_KEYS = json.loads(os.getenv("API_KEYS")) if os.getenv("API_KEYS") else DEFAULT_API_KEYS

WEBHOOK_TIMEOUT_SECONDS = float(os.getenv("WEBHOOK_TIMEOUT_SECONDS", "5"))
