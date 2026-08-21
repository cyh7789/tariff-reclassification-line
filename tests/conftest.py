"""Both tracks have landed, so the real `fleet.sync` package is importable and
the triage tests exercise the real health gate against the fixture snapshot.
The gate stub that stood in for Track A is gone.
"""

import os

import pytest

from fleet.workflow.store import Store


@pytest.fixture
def make_store():
    return _make_store


def _make_store(tmp_path):
    """The store under test, on SQLite unless FLEET_TEST_PG_DSN points elsewhere.

    The suite was written against SQLite; pointing this env var at a Postgres
    database reruns the same assertions on the Cloud SQL path. Each test gets a
    clean schema, which on Postgres means dropping what the last test made.
    """
    dsn = os.environ.get("FLEET_TEST_PG_DSN")
    if not dsn:
        return Store(tmp_path / "cases.db")
    import psycopg2
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS case_facts, case_attempts, case_events,"
                    " cases, batches CASCADE")
    conn.close()
    return Store(dsn)
