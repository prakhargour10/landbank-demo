"""Thin PostgreSQL layer (psycopg 3 + connection pool).

All helpers return plain Python values: NUMERIC -> float, DATE/TIMESTAMP -> ISO string,
so results can be returned from the API as JSON without further conversion.
"""
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from . import config

pool = ConnectionPool(
    config.DATABASE_URL,
    kwargs={"row_factory": dict_row, "options": f"-c search_path={config.DB_SCHEMA},public"},
    min_size=1,
    max_size=10,
    open=False,
)


def open_pool():
    pool.open(wait=True)


def close_pool():
    pool.close()


@contextmanager
def get_conn():
    """One transaction per block: committed on success, rolled back on error."""
    with pool.connection() as conn:
        yield conn


def _clean_value(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _clean(row):
    if row is None:
        return None
    return {k: _clean_value(v) for k, v in row.items()}


def q_all(conn, sql, params=None):
    return [_clean(r) for r in conn.execute(sql, params or {}).fetchall()]


def q_one(conn, sql, params=None):
    return _clean(conn.execute(sql, params or {}).fetchone())


def execute(conn, sql, params=None):
    conn.execute(sql, params or {})


def jsonb(value):
    """Wrap a Python object for a JSONB column."""
    return Jsonb(value)
