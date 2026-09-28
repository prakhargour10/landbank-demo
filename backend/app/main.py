"""LANDBANK MSME Lending - Demo Data Service (FastAPI).

Run:  uvicorn app.main:app --reload --port 8000        (from the backend/ folder)
Docs: http://localhost:8000/docs        OpenAPI for AgenticOrg: http://localhost:8000/openapi.json
UI:   http://localhost:8000/
"""
import logging
import os
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi_mcp import FastApiMCP
from starlette.routing import Match

from . import config, db, events
from .routers.api import r as api_router
from .services.admin import write_audit

log = logging.getLogger("landbank")
FRONTEND_DIR = os.getenv("FRONTEND_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))


@asynccontextmanager
async def lifespan(app):
    db.open_pool()
    yield
    db.close_pool()


app = FastAPI(
    title="LANDBANK MSME Lending - Demo Data Service",
    version="1.0.0",
    description=("Synthetic core-banking, tax (BIR), credit-bureau (CIC) and lending-workflow data for AgenticOrg agents. "
                 "Authenticate with the X-API-Key header. All data is synthetic."),
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router)

_ID = {"customer_id": re.compile(r"LB-MSME-\d{4}"), "application_id": re.compile(r"APP-\d{4}-\d{4}")}


def _tool_name(request):
    for route in app.routes:
        m, _ = route.matches(request.scope)
        if m == Match.FULL:
            return getattr(route, "operation_id", None) or getattr(route, "name", None)
    return None


@app.middleware("http")
async def audit_and_dispatch(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/api/v1"):
        key = config.API_KEYS.get(request.headers.get("X-API-Key", ""), {"actor_type": "UNKNOWN", "actor_name": "anonymous"})
        cid = _ID["customer_id"].search(path)
        aid = _ID["application_id"].search(path)
        try:
            with db.get_conn() as conn:
                write_audit(conn, key["actor_type"], key["actor_name"], request.method, path, _tool_name(request),
                            response.status_code, cid.group(0) if cid else None, aid.group(0) if aid else None,
                            {"query": dict(request.query_params)})
        except Exception:  # noqa: BLE001 - never fail a request because audit failed
            log.exception("audit write failed")
        if request.method != "GET" and not path.endswith("/admin/reset"):
            events.dispatch_async()
    return response


@app.get("/health", operation_id="health", tags=["Service"])
def health():
    """Liveness/readiness check: confirms the API and database are reachable and returns the
    customer count and demo as-of date. Use to verify the service is up, not for business data."""
    with db.get_conn() as conn:
        n = db.q_one(conn, "SELECT COUNT(*) AS n FROM customers")
    return {"status": "ok", "customers": n["n"], "as_of": config.AS_OF_DATE.isoformat()}


@app.get("/ui-config", operation_id="uiConfig", tags=["Service"])
def ui_config():
    """Demo-only: gives the web console the human role keys. Disabled when DEMO_MODE=false."""
    if not config.DEMO_MODE:
        return {"demo_mode": False, "roles": []}
    roles = [{"key": k, **v} for k, v in config.API_KEYS.items() if v["actor_type"] == "HUMAN"]
    # Agent keys let the console *simulate* an agent step when AgenticOrg is not connected yet.
    agents = [{"key": k, **v} for k, v in config.API_KEYS.items() if v["actor_type"] == "AGENT"]
    return {"demo_mode": True, "as_of": config.AS_OF_DATE.isoformat(), "roles": roles, "agents": agents}


if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

# Expose every route above (operation_id == AgenticOrg tool name) as an MCP tool at /mcp.
# Auth is unchanged: FastApiMCP dispatches tool calls in-process over ASGI, so the
# X-API-Key header sent by the MCP client passes straight through to `auth.get_actor`
# exactly as it does for a normal HTTP call - no separate credential wiring needed.
mcp = FastApiMCP(
    app,
    name="LANDBANK MSME MCP",
    description="MSME lending demo data tools (customers, applications, loans, bureau, tax) for AgenticOrg agents.",
    headers=["x-api-key"],
)
mcp.mount_http()
