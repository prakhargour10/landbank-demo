"""API-key authentication.

Every caller sends `X-API-Key`. The key identifies the actor (an AgenticOrg agent or a human
role in the web console). Consequential actions are restricted to human roles *in the service
itself*, so an agent cannot approve, decline or disburse even if it is mis-configured in
AgenticOrg / Grantex.
"""
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

from . import config


@dataclass
class Actor:
    actor_type: str  # AGENT | HUMAN | SYSTEM
    actor_name: str
    role: str  # agent | applicant | rm | credit_officer | loan_ops | admin


def get_actor(x_api_key: str = Header(default="", alias="X-API-Key")) -> Actor:
    info = config.API_KEYS.get(x_api_key)
    if not info:
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key")
    return Actor(info["actor_type"], info["actor_name"], info["role"])


def require_roles(*roles: str):
    """Dependency factory: only the listed human roles (and admin) may call the endpoint."""

    def _check(actor: Actor = Depends(get_actor)) -> Actor:
        if actor.role not in roles and actor.role != "admin":
            raise HTTPException(
                status_code=403,
                detail=f"'{actor.actor_name}' ({actor.role}) is not allowed to perform this action. "
                f"Allowed roles: {', '.join(roles)}. AI agents cannot take consequential decisions.",
            )
        return actor

    return _check
