"""Tests for the sync layer and the health gate (contract section 3.3).

Everything here runs offline. The gate tests read the committed fixture
snapshot under `tests/fixtures/snapshot`; the fetcher tests drive the real
`fetch()` entry points with a stub HTTP session, so what is asserted is what
the fetcher writes to disk, not how it is written.

The three traps from contract section 2 each have a test:

* HTTP 200 with an empty body: rejected at fetch time, and a snapshot carrying
  the resulting empty file fails the gate;
* a row count under the floor: fails the gate;
* a lower-case CROSS ruling number: comes out upper-case.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fleet.sync import cross, csl, hts, http  # noqa: E402
from fleet.sync.gate import DataSourceUnhealthy, assert_healthy, load_manifest  # noqa: E402
from fleet.sync.manifest import (  # noqa: E402
    ALL_SOURCES,
    Manifest,
    data_path,
    manifest_path,
    sha256_file,
    write_manifest,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "snapshot"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_throttle(monkeypatch):
    """The fetchers sleep between requests; tests do not need the politeness."""
    monkeypatch.setattr(http, "MIN_REQUEST_INTERVAL", 0)


@pytest.fixture
def snapshot(tmp_path) -> Path:
    """A writable copy of the committed fixture snapshot."""
    target = tmp_path / "snapshot"
    shutil.copytree(FIXTURE, target)
    return target


def rewrite_manifest(snapshot_dir: Path, source: str, **changes) -> Manifest:
    manifest = load_manifest(snapshot_dir, source)
    updated = Manifest(**{**manifest.to_dict(), **changes})
    write_manifest(snapshot_dir, updated)
    return updated


class FakeResponse:
    def __init__(self, url, body: bytes, status_code=200, headers=None):
        self.url = url
        self.content = body
        self.status_code = status_code
        self.headers = headers or {}


class FakeSession:
    """Stands in for requests.Session, one queued response per call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None, allow_redirects=True, timeout=None):
        self.calls.append({"url": url, "params": params, "allow_redirects": allow_redirects})
        if not self._responses:
            raise AssertionError(f"unexpected extra request to {url}")
        body = self._responses.pop(0)
        if isinstance(body, FakeResponse):
            return body
        return FakeResponse(url, body)


def json_body(payload) -> bytes:
    return json.dumps(payload).encode("utf-8")


def search_payload(hits, total=None) -> bytes:
    return json_body({"rulings": hits, "totalHits": total if total is not None else len(hits)})


# ---------------------------------------------------------------------------
# the gate, happy path
# ---------------------------------------------------------------------------


def test_fixture_snapshot_passes_the_gate(snapshot):
    assert_healthy(snapshot)


def test_load_manifest_reads_every_source(snapshot):
    for source in ALL_SOURCES:
        manifest = load_manifest(snapshot, source)
        assert manifest.source == source
        assert manifest.row_count >= manifest.min_rows
        assert manifest.sha256 == sha256_file(data_path(snapshot, source))


def test_load_manifest_raises_for_a_missing_manifest(snapshot):
    manifest_path(snapshot, "hts").unlink()
    with pytest.raises(DataSourceUnhealthy, match="manifest missing"):
        load_manifest(snapshot, "hts")


def test_gate_checks_only_the_requested_sources(snapshot):
    """Track B asks for the sources it reads; a broken one it never touches
    must not be able to halt it."""
    data_path(snapshot, "csl").write_text("", encoding="utf-8")
    assert_healthy(snapshot, ["hts", "correlation"])
    with pytest.raises(DataSourceUnhealthy):
        assert_healthy(snapshot, ["csl"])


# ---------------------------------------------------------------------------
# trap 1: HTTP 200 with an empty body
# ---------------------------------------------------------------------------


def test_empty_screening_list_fails_the_gate(snapshot):
    """A 200-with-no-body fetch leaves an empty file and an honest manifest.
    The gate must still refuse it: an empty screening list clears everyone."""
    path = data_path(snapshot, "csl")
    path.write_text("", encoding="utf-8")
    rewrite_manifest(snapshot, "csl", row_count=0, bytes=0, sha256=sha256_file(path))

    with pytest.raises(DataSourceUnhealthy) as excinfo:
        assert_healthy(snapshot)
    assert "csl" in str(excinfo.value)


def test_csl_fetch_refuses_http_200_with_an_empty_body(tmp_path):
    session = FakeSession([b""])
    with pytest.raises(DataSourceUnhealthy, match="HTTP 200 with 0 bytes"):
        csl.fetch(tmp_path, session=session)
    assert not data_path(tmp_path, "csl").exists()


def test_hts_fetch_refuses_a_truncated_export(tmp_path):
    """Valid JSON, HTTP 200, over a megabyte on the wire, three rows: still a
    broken schedule. Size alone does not clear a payload either."""
    fat_row = {
        "htsno": "0101",
        "indent": "0",
        "description": "Live horses, asses, mules and hinnies:" + "x" * 400_000,
    }
    session = FakeSession(
        [json_body({"name": "2026HTSRev16"}), json_body([fat_row] * 3)]
    )
    with pytest.raises(DataSourceUnhealthy, match="3 rows, below the floor 30000"):
        hts.fetch(tmp_path, session=session)


# ---------------------------------------------------------------------------
# trap 2: a row count under the floor
# ---------------------------------------------------------------------------


def test_row_count_below_the_floor_fails_the_gate(snapshot):
    path = data_path(snapshot, "hts")
    kept = path.read_text(encoding="utf-8").splitlines(keepends=True)[:5]
    path.write_text("".join(kept), encoding="utf-8")
    rewrite_manifest(
        snapshot, "hts", row_count=5, bytes=path.stat().st_size, sha256=sha256_file(path)
    )

    with pytest.raises(DataSourceUnhealthy, match="row_count 5 is below the floor"):
        assert_healthy(snapshot)


def test_byte_count_below_the_floor_fails_the_gate(snapshot):
    """Row count intact, payload gutted: the byte floor is the second net."""
    path = data_path(snapshot, "correlation")
    path.write_text("hs2017,hs2022\n", encoding="utf-8")
    rewrite_manifest(snapshot, "correlation", sha256=sha256_file(path), bytes=path.stat().st_size)

    with pytest.raises(DataSourceUnhealthy, match="below the floor"):
        assert_healthy(snapshot)


# ---------------------------------------------------------------------------
# trap 3: CROSS ruling-number casing
# ---------------------------------------------------------------------------


def test_cross_fetch_upper_cases_ruling_numbers(tmp_path):
    """The detail endpoint answers in lower case and every join key elsewhere
    is upper case, so the sync layer normalizes on write."""
    session = FakeSession(
        [
            search_payload(
                [
                    {
                        "rulingNumber": "n317442",
                        "rulingDate": "2021-03-08T00:00:00",
                        "tariffs": ["8543.70.9860"],
                        "subject": "The tariff classification of a widget",
                        "categories": "Classification",
                        "relatedRulings": ["n301122"],
                    }
                ]
            )
        ]
    )
    cross.fetch(tmp_path, session=session, full=True, page_size=1000, min_rows=1, min_bytes=1)

    written = [
        json.loads(line)
        for line in data_path(tmp_path, "cross").read_text(encoding="utf-8").splitlines()
    ]
    assert [r["ruling_number"] for r in written] == ["N317442"]
    assert written[0]["related_rulings"] == ["N301122"]
    assert written[0]["url"].endswith("/N317442")
    assert written[0]["tariffs"] == ["8543709860"]
    assert written[0]["category"] == "Classification"


# ---------------------------------------------------------------------------
# the remaining gate conditions
# ---------------------------------------------------------------------------


def test_missing_snapshot_marker_fails_the_gate(snapshot):
    (snapshot / "SNAPSHOT.json").unlink()
    with pytest.raises(DataSourceUnhealthy, match="SNAPSHOT.json missing"):
        assert_healthy(snapshot)


def test_snapshot_marker_not_ok_fails_the_gate(snapshot):
    marker = json.loads((snapshot / "SNAPSHOT.json").read_text(encoding="utf-8"))
    marker["status"] = "partial"
    (snapshot / "SNAPSHOT.json").write_text(json.dumps(marker), encoding="utf-8")
    with pytest.raises(DataSourceUnhealthy, match="status is 'partial'"):
        assert_healthy(snapshot)


def test_missing_manifest_fails_the_gate(snapshot):
    manifest_path(snapshot, "correlation").unlink()
    with pytest.raises(DataSourceUnhealthy, match="manifest missing"):
        assert_healthy(snapshot)


def test_edited_data_file_fails_the_sha256_check(snapshot):
    """The row and byte counts still hold; only the content moved."""
    path = data_path(snapshot, "cross")
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    record = json.loads(lines[0])
    record["tariffs"] = ["9999999999"]
    lines[0] = json.dumps(record) + "\n"
    path.write_text("".join(lines), encoding="utf-8")

    with pytest.raises(DataSourceUnhealthy, match="sha256 mismatch"):
        assert_healthy(snapshot)


def test_missing_data_file_fails_the_gate(snapshot):
    data_path(snapshot, "hts").unlink()
    with pytest.raises(DataSourceUnhealthy, match="data file missing"):
        assert_healthy(snapshot)


def test_stale_source_fails_the_gate(snapshot):
    rewrite_manifest(snapshot, "csl", staleness_days=31)
    with pytest.raises(DataSourceUnhealthy, match="31 days stale"):
        assert_healthy(snapshot)


def test_manifest_status_not_ok_fails_the_gate(snapshot):
    rewrite_manifest(snapshot, "hts", status="degraded")
    with pytest.raises(DataSourceUnhealthy, match="manifest status is 'degraded'"):
        assert_healthy(snapshot)


# ---------------------------------------------------------------------------
# incremental CROSS: the default path
# ---------------------------------------------------------------------------


def test_cross_incremental_extends_the_previous_snapshot(tmp_path):
    """A full re-enumeration is 219 paged requests, so the default run copies
    the previous snapshot forward and asks only for rulings from its newest
    date onward."""
    base = tmp_path / "2026-08-16"
    base.mkdir()
    held = [
        {
            "ruling_number": "N000001",
            "ruling_date": "2026-08-01",
            "tariffs": ["8543709860"],
            "subject": "old one",
            "category": "Classification",
            "related_rulings": [],
            "url": "https://rulings.cbp.gov/ruling/N000001",
        },
        {
            "ruling_number": "N000002",
            "ruling_date": "2026-08-06",
            "tariffs": [],
            "subject": "newest held",
            "category": "Classification",
            "related_rulings": [],
            "url": "https://rulings.cbp.gov/ruling/N000002",
        },
    ]
    data_path(base, "cross").write_text(
        "".join(json.dumps(r) + "\n" for r in held), encoding="utf-8"
    )

    out = tmp_path / "2026-08-18"
    session = FakeSession(
        [
            search_payload(
                [
                    {
                        "rulingNumber": "N000003",
                        "rulingDate": "2026-08-14T00:00:00",
                        "tariffs": ["4202.92.9026"],
                        "subject": "brand new",
                        "categories": "Classification",
                        "relatedRulings": [],
                    }
                ]
            )
        ]
    )
    manifest = cross.fetch(out, session=session, min_rows=1, min_bytes=1)

    assert session.calls[0]["params"]["fromDate"] == "2026-08-06"
    written = [
        json.loads(line)
        for line in data_path(out, "cross").read_text(encoding="utf-8").splitlines()
    ]
    assert [r["ruling_number"] for r in written] == ["N000001", "N000002", "N000003"]
    assert manifest.row_count == 3
    assert manifest.revision == "2026-08-14"


def test_cross_incremental_replaces_a_reissued_ruling(tmp_path):
    base = tmp_path / "2026-08-16"
    base.mkdir()
    data_path(base, "cross").write_text(
        json.dumps(
            {
                "ruling_number": "N000001",
                "ruling_date": "2026-08-01",
                "tariffs": [],
                "subject": "before",
                "category": "Classification",
                "related_rulings": [],
                "url": "https://rulings.cbp.gov/ruling/N000001",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    session = FakeSession(
        [
            search_payload(
                [
                    {
                        "rulingNumber": "N000001",
                        "rulingDate": "2026-08-01T00:00:00",
                        "tariffs": ["8543.70.9860"],
                        "subject": "after",
                        "categories": "Classification",
                        "relatedRulings": [],
                    }
                ]
            )
        ]
    )
    cross.fetch(tmp_path / "2026-08-18", session=session, min_rows=1, min_bytes=1)

    written = [
        json.loads(line)
        for line in data_path(tmp_path / "2026-08-18", "cross")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(written) == 1
    assert written[0]["subject"] == "after"
    assert written[0]["tariffs"] == ["8543709860"]


def test_cross_refuses_to_build_from_nothing(tmp_path):
    out = tmp_path / "2026-08-18"
    with pytest.raises(DataSourceUnhealthy, match="no previous snapshot"):
        cross.fetch(out, session=FakeSession([]), min_rows=1, min_bytes=1)


def test_cross_full_pages_until_the_hit_count_is_covered(tmp_path):
    """Pagination is what a full enumeration rides on, so it is driven here
    rather than trusted."""
    pages = [
        search_payload(
            [
                {
                    "rulingNumber": f"N00000{n}",
                    "rulingDate": "2026-08-0{}".format(n % 9 + 1),
                    "tariffs": [],
                    "subject": "",
                    "categories": "Classification",
                    "relatedRulings": [],
                }
            ],
            total=3,
        )
        for n in (1, 2, 3)
    ]
    session = FakeSession(pages)
    manifest = cross.fetch(
        tmp_path / "2026-08-18",
        session=session,
        full=True,
        page_size=1,
        min_rows=1,
        min_bytes=1,
    )
    assert [call["params"]["page"] for call in session.calls] == [1, 2, 3]
    assert manifest.row_count == 3


# ---------------------------------------------------------------------------
# record shapes written to disk
# ---------------------------------------------------------------------------


def test_hts_header_rows_carry_a_null_code_and_keep_file_order(snapshot):
    rows = [
        json.loads(line)
        for line in data_path(snapshot, "hts").read_text(encoding="utf-8").splitlines()
    ]
    assert [r["row_index"] for r in rows] == list(range(len(rows)))
    assert all(r["htsno"] is None or r["htsno"].isdigit() for r in rows)
    assert any(r["htsno"] is None for r in rows), "fixture should include a header row"

    # The duty rate hangs off the 8-digit line; the 10-digit statistical
    # suffix under it publishes nothing and has to inherit.
    statistical = next(r for r in rows if r["htsno"] == "0101210010")
    parent = next(r for r in rows if r["htsno"] == "01012100")
    assert statistical["general"] == ""
    assert parent["general"] != ""
    assert parent["row_index"] < statistical["row_index"]
    assert parent["indent"] < statistical["indent"]


def test_csl_records_carry_the_two_contract_fields(snapshot):
    records = [
        json.loads(line)
        for line in data_path(snapshot, "csl").read_text(encoding="utf-8").splitlines()
    ]
    assert records, "fixture should hold screening entries"
    for record in records:
        assert record["source_list"] == record["source"]
        assert "license_requirement" in record
    assert any(record["source_list"] for record in records)
