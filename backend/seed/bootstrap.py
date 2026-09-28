"""Seed the database on first start (used by the Docker image). Safe to run repeatedly."""
import os
import sys

import psycopg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import config, db  # noqa: E402
from seed.load import reset_database  # noqa: E402


def already_seeded():
    try:
        with psycopg.connect(config.DATABASE_URL) as conn:
            return conn.execute("SELECT COUNT(*) FROM lb.customers").fetchone()[0] > 0
    except Exception:  # noqa: BLE001 - schema not created yet
        return False


if __name__ == "__main__":
    if os.getenv("SEED_ON_START", "true").lower() != "true":
        print("SEED_ON_START is false - skipping seed")
    elif already_seeded():
        print("Database already seeded - skipping (POST /api/v1/admin/reset to re-seed)")
    else:
        db.open_pool()
        print(reset_database())
        db.close_pool()
