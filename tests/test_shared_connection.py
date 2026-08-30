"""Drawing a batch has to cost one connection, not one per read.

Every accessor opening its own connection is invisible on SQLite and fatal on
Cloud SQL: a twenty-case batch asked for eighty at once and Postgres answered
"remaining connection slots are reserved", so the screen went blank while the
batch itself was fine.
"""

import pytest

import fleet.workflow.store as store_module


@pytest.fixture
def store(tmp_path, make_store):
    return make_store(tmp_path)


@pytest.fixture
def batch(store):
    return store.create_batch("plant-a", "b", "2026-08-18", [
        {"item_id": f"SKU-{i}", "prior_code": "610910", "description": "a shirt"}
        for i in range(5)])


def opened(store, monkeypatch) -> list:
    """Count connections the driver actually opens.

    Counted at the driver, not at `Store.connect`: a counter that decides for
    itself whether a call was borrowed passes even when the borrowing is deleted,
    which is exactly what the first version of this test did.
    """
    seen = []
    if store.pg:
        import psycopg2
        real = psycopg2.connect

        def counting(*a, **kw):
            seen.append(1)
            return real(*a, **kw)

        monkeypatch.setattr(psycopg2, "connect", counting)
    else:
        import sqlite3
        real = sqlite3.connect

        def counting(*a, **kw):
            seen.append(1)
            return real(*a, **kw)

        monkeypatch.setattr(store_module.sqlite3, "connect", counting)
    return seen


def test_reads_inside_shared_open_one_connection(store, batch, monkeypatch):
    seen = opened(store, monkeypatch)
    with store.shared():
        for case in store.cases(batch, "plant-a"):
            store.case(case.case_id)
            store.facts(case.case_id)
            store.attempts(case.case_id)
            store.events(case.case_id)
    assert len(seen) == 1, f"expected one connection, opened {len(seen)}"


def test_the_same_reads_without_shared_open_one_each(store, batch, monkeypatch):
    seen = opened(store, monkeypatch)
    for case in store.cases(batch, "plant-a"):
        store.case(case.case_id)
    assert len(seen) > 1, "without shared() each read must open its own"


def test_a_nested_shared_still_opens_only_one(store, batch, monkeypatch):
    seen = opened(store, monkeypatch)
    with store.shared():
        with store.shared():
            store.cases(batch, "plant-a")
        store.cases(batch, "plant-a")
    assert len(seen) == 1


def test_the_connection_is_released_when_the_block_ends(store, batch, monkeypatch):
    with store.shared():
        pass
    seen = opened(store, monkeypatch)
    store.cases(batch, "plant-a")
    assert len(seen) == 1, "a leaked handle would make this read borrow a closed one"
