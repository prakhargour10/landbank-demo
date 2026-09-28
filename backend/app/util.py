"""Small shared helpers."""
from datetime import date, timedelta

from fastapi import HTTPException

from . import config
from .db import q_one


def as_of() -> date:
    return config.AS_OF_DATE


def new_id(conn, prefix: str, table: str, column: str, width: int = 4) -> str:
    """Sequential human-readable IDs such as ALERT-0007 (demo-scale, not for high concurrency)."""
    row = q_one(
        conn,
        f"SELECT COALESCE(MAX(CAST(SUBSTRING({column} FROM %(pos)s) AS INT)), 0) AS n "
        f"FROM {table} WHERE {column} LIKE %(like)s",
        {"pos": len(prefix) + 2, "like": f"{prefix}-%"},
    )
    return f"{prefix}-{int(row['n']) + 1:0{width}d}"


def not_found(what: str, key: str):
    raise HTTPException(status_code=404, detail=f"{what} '{key}' not found")


def peso(amount: float) -> str:
    """Format pesos the way people read them: ₱1.25M, ₱850K, ₱4,500."""
    a = float(amount or 0)
    if abs(a) >= 1_000_000:
        return f"₱{a / 1_000_000:.2f}M"
    if abs(a) >= 100_000:
        return f"₱{a / 1_000:.0f}K"
    return f"₱{a:,.0f}"


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def last_complete_month_end(ref: date) -> date:
    return month_start(ref) - timedelta(days=1)


def pct_change(new: float, old: float):
    if not old:
        return None
    return round((new - old) / old * 100, 1)
