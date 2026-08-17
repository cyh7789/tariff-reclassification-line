"""Case state, and the audit trail of how it got there.

A batch of line items arrives, the deterministic layer settles what it can, the
agent works the rest, and a person approves once. Every one of those steps is a
state transition, and the transitions are what the officer is signing off on, so
they are stored rather than derived.

Two properties are enforced here rather than trusted:

**Transitions are legal or refused.** `NEEDS_INPUT -> APPROVED` is not a path; an
item that never got its missing fact cannot be waved through by a UI bug.

**Work is idempotent.** A worker that retries after a timeout must not produce a
second classification or a second approval. Every transition carries an idempotency
key, and a repeat writes nothing.

SQLite locally, Postgres in Cloud SQL. The schema is plain SQL for that reason:
the only Postgres-specific piece is row-level security, which is added in the
deployment migration and has no SQLite equivalent.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path


class CaseState(StrEnum):
    RECEIVED = "RECEIVED"                  # in the batch, nothing done yet
    SETTLED = "SETTLED"                    # deterministic layer answered it
    CLASSIFYING = "CLASSIFYING"            # agent working
    NEEDS_INPUT = "NEEDS_INPUT"            # refused: a fact is missing
    VERIFY_FAILED = "VERIFY_FAILED"        # citations did not resolve
    READY = "READY"                        # verified, waiting for a person
    APPROVED = "APPROVED"                  # signed off
    BLOCKED = "BLOCKED"                    # data source unhealthy


#: The only moves that exist. Anything else is a bug somewhere upstream, and the
#: store's job is to make that bug loud rather than let it write a bad row.
LEGAL: dict[CaseState, frozenset[CaseState]] = {
    CaseState.RECEIVED: frozenset({CaseState.SETTLED, CaseState.CLASSIFYING,
                                   CaseState.BLOCKED}),
    # CLASSIFYING -> CLASSIFYING is a restart: a worker died holding the case and
    # nothing else will ever pick it up.
    CaseState.CLASSIFYING: frozenset({CaseState.READY, CaseState.NEEDS_INPUT,
                                      CaseState.VERIFY_FAILED, CaseState.BLOCKED,
                                      CaseState.CLASSIFYING}),
    CaseState.NEEDS_INPUT: frozenset({CaseState.CLASSIFYING}),
    CaseState.VERIFY_FAILED: frozenset({CaseState.CLASSIFYING}),
    CaseState.SETTLED: frozenset({CaseState.APPROVED}),
    CaseState.READY: frozenset({CaseState.APPROVED}),
    CaseState.BLOCKED: frozenset({CaseState.RECEIVED}),
    CaseState.APPROVED: frozenset(),
}


class IllegalTransition(Exception):
    """Raised when a move is not in `LEGAL`. Never caught to 'recover'."""


@dataclass
class Case:
    case_id: str
    batch_id: str
    tenant: str                 # the product line; the isolation boundary
    item_id: str
    description: str
    prior_code: str
    state: CaseState
    route: str = ""             # DETERMINISTIC or AGENT, from triage
    bucket: str = ""            # SURVIVED / DEAD_CODE / SCOPE_REVIEW
    selected_code: str | None = None
    runner_up_code: str | None = None
    confidence: float | None = None
    duty_rate: str | None = None
    prior_duty_rate: str | None = None
    reasoning: str = ""
    distinguishing_fact: str = ""
    citations: list = field(default_factory=list)
    missing_property: str | None = None
    ask_department: str | None = None
    verify_reason: str = ""
    candidates: list = field(default_factory=list)
    #: What the case cost to settle. Tool calls are the honest difficulty signal:
    #: an item the agent answered in three lookups is not the same work as one it
    #: took fourteen to pin down, and the flow view is where that shows.
    country_of_origin: str | None = None
    supplier: str | None = None
    annual_value: float | None = None
    #: Rates on 12% of the schedule are charged per kilo or per head, so the
    #: quantity is not an optional extra there: without it the duty is unknown.
    quantity: float | None = None
    quantity_unit: str | None = None
    findings: list = field(default_factory=list)
    tool_calls: int = 0
    #: The ordered record of how this case was worked: every lookup, every
    #: candidate ruled out, the decision, the citation check.
    steps: list = field(default_factory=list)
    tools_used: list = field(default_factory=list)
    seconds: float = 0.0
    attempts: int = 0
    updated_at: str = ""


SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    batch_id    TEXT PRIMARY KEY,
    tenant      TEXT NOT NULL,
    label       TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    case_id            TEXT PRIMARY KEY,
    batch_id           TEXT NOT NULL REFERENCES batches(batch_id),
    tenant             TEXT NOT NULL,
    item_id            TEXT NOT NULL,
    description        TEXT NOT NULL,
    prior_code         TEXT NOT NULL,
    state              TEXT NOT NULL,
    route              TEXT NOT NULL DEFAULT '',
    bucket             TEXT NOT NULL DEFAULT '',
    selected_code      TEXT,
    runner_up_code     TEXT,
    confidence         REAL,
    duty_rate          TEXT,
    prior_duty_rate    TEXT,
    reasoning          TEXT NOT NULL DEFAULT '',
    distinguishing_fact TEXT NOT NULL DEFAULT '',
    citations          TEXT NOT NULL DEFAULT '[]',
    candidates         TEXT NOT NULL DEFAULT '[]',
    missing_property   TEXT,
    ask_department     TEXT,
    verify_reason      TEXT NOT NULL DEFAULT '',
    country_of_origin  TEXT,
    supplier           TEXT,
    annual_value       REAL,
    quantity           REAL,
    quantity_unit      TEXT,
    findings           TEXT NOT NULL DEFAULT '[]',
    tool_calls         INTEGER NOT NULL DEFAULT 0,
    steps              TEXT NOT NULL DEFAULT '[]',
    tools_used         TEXT NOT NULL DEFAULT '[]',
    seconds            REAL NOT NULL DEFAULT 0,
    attempts           INTEGER NOT NULL DEFAULT 0,
    updated_at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS cases_by_batch ON cases(batch_id, state);

-- Append-only. The officer signs the outcome; this is the record of how it was
-- reached, including the attempts that failed verification.
CREATE TABLE IF NOT EXISTS case_events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         TEXT NOT NULL REFERENCES cases(case_id),
    at              TEXT NOT NULL,
    from_state      TEXT NOT NULL,
    to_state        TEXT NOT NULL,
    actor           TEXT NOT NULL,
    detail          TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS events_by_case ON case_events(case_id, event_id);

-- One row per attempt at a case, holding that attempt's transcript. The case row
-- keeps the latest for the live view; this keeps the rest. A case refused for a
-- missing product fact and re-run after engineering answered has two attempts,
-- and the first one is where the refusal was reasoned. Overwriting it leaves the
-- signature resting on a decision whose earlier half is gone.
CREATE TABLE IF NOT EXISTS case_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id    TEXT NOT NULL REFERENCES cases(case_id),
    at         TEXT NOT NULL,
    to_state   TEXT NOT NULL,
    actor      TEXT NOT NULL,
    steps      TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS attempts_by_case ON case_attempts(case_id, attempt_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


#: Columns added after the first database was created. `CREATE TABLE IF NOT
#: EXISTS` silently leaves an existing table alone, so a schema change that only
#: touches the DDL string works on a fresh database and 500s on a live one.
MIGRATIONS = [
    ("cases", "country_of_origin", "TEXT"),
    ("cases", "supplier", "TEXT"),
    ("cases", "annual_value", "REAL"),
    ("cases", "quantity", "REAL"),
    ("cases", "quantity_unit", "TEXT"),
    ("cases", "findings", "TEXT NOT NULL DEFAULT '[]'"),
    ("cases", "tool_calls", "INTEGER NOT NULL DEFAULT 0"),
    ("cases", "steps", "TEXT NOT NULL DEFAULT '[]'"),
    ("cases", "tools_used", "TEXT NOT NULL DEFAULT '[]'"),
    ("cases", "seconds", "REAL NOT NULL DEFAULT 0"),
    ("cases", "attempts", "INTEGER NOT NULL DEFAULT 0"),
]


class Store:
    def __init__(self, path: Path | str):
        self.path = str(path)
        with self.connect() as db:
            db.executescript(SCHEMA)
            self._migrate(db)

    @staticmethod
    def _migrate(db) -> None:
        for table, column, ddl in MIGRATIONS:
            have = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
            if column not in have:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
        finally:
            db.close()

    # ---- writing -----------------------------------------------------------

    def create_batch(self, tenant: str, label: str, snapshot_id: str,
                     items: list[dict]) -> str:
        batch_id = f"B-{uuid.uuid4().hex[:8]}"
        with self.connect() as db:
            db.execute("BEGIN")
            db.execute("INSERT INTO batches VALUES (?,?,?,?,?)",
                       (batch_id, tenant, label, snapshot_id, now()))
            for item in items:
                db.execute(
                    "INSERT INTO cases (case_id, batch_id, tenant, item_id, description,"
                    " prior_code, state, country_of_origin, supplier, annual_value,"
                    " quantity, quantity_unit, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f"C-{uuid.uuid4().hex[:10]}", batch_id, tenant, item["item_id"],
                     item["description"], item["prior_code"], CaseState.RECEIVED,
                     item.get("country_of_origin"), item.get("supplier"),
                     item.get("annual_value"), item.get("quantity"),
                     item.get("quantity_unit"), now()))
            db.execute("COMMIT")
        return batch_id

    def transition(self, case_id: str, to_state: CaseState, actor: str,
                   idempotency_key: str, detail: str = "", **fields) -> bool:
        """Move a case, or return False because this move was already made.

        The key is the caller's promise about what work this represents. A worker
        retrying the same classification passes the same key and writes nothing
        the second time.
        """
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                seen = db.execute(
                    "SELECT 1 FROM case_events WHERE idempotency_key = ?",
                    (idempotency_key,)).fetchone()
                if seen:
                    db.execute("ROLLBACK")
                    return False

                row = db.execute("SELECT state FROM cases WHERE case_id = ?",
                                 (case_id,)).fetchone()
                if row is None:
                    raise KeyError(f"no case {case_id}")
                current = CaseState(row["state"])
                if to_state not in LEGAL[current]:
                    raise IllegalTransition(f"{current} -> {to_state} is not a legal move")

                sets, values = ["state = ?", "updated_at = ?"], [to_state, now()]
                for column, value in fields.items():
                    sets.append(f"{column} = ?")
                    values.append(json.dumps(value, ensure_ascii=False)
                                  if isinstance(value, (list, dict)) else value)
                values.append(case_id)
                db.execute(f"UPDATE cases SET {', '.join(sets)} WHERE case_id = ?", values)
                db.execute(
                    "INSERT INTO case_events (case_id, at, from_state, to_state, actor,"
                    " detail, idempotency_key) VALUES (?,?,?,?,?,?,?)",
                    (case_id, now(), current, to_state, actor, detail, idempotency_key))
                if fields.get("steps"):
                    db.execute(
                        "INSERT INTO case_attempts (case_id, at, to_state, actor, steps)"
                        " VALUES (?,?,?,?,?)",
                        (case_id, now(), to_state, actor,
                         json.dumps(fields["steps"], ensure_ascii=False)))
                db.execute("COMMIT")
                return True
            except Exception:
                db.execute("ROLLBACK")
                raise

    def approve_batch(self, batch_id: str, actor: str,
                      only: set[str] | None = None) -> dict:
        """Approve what is ready, and say what was left behind.

        One action rather than one per item: signing each row separately is the
        hand-holding this system exists to remove. What a person cannot delegate is
        the decision to sign at all, and that stays one deliberate act whether it
        covers the whole batch or a chosen part of it.

        `only` narrows it to a selection. Reviewing a subset before signing is
        ordinary practice, and refusing to allow it would be a design opinion the
        officer never asked for.
        """
        approved, held = [], []
        with self.connect() as db:
            rows = db.execute(
                "SELECT case_id, state FROM cases WHERE batch_id = ?", (batch_id,)
            ).fetchall()
        for row in rows:
            if only is not None and row["case_id"] not in only:
                continue
            state = CaseState(row["state"])
            if state in (CaseState.READY, CaseState.SETTLED):
                self.transition(row["case_id"], CaseState.APPROVED, actor,
                                f"approve:{batch_id}:{row['case_id']}",
                                detail="batch approval")
                approved.append(row["case_id"])
            elif state != CaseState.APPROVED:
                held.append({"case_id": row["case_id"], "state": str(state)})
        return {"approved": len(approved), "held": held}

    # ---- reading -----------------------------------------------------------

    def _to_case(self, row: sqlite3.Row) -> Case:
        data = dict(row)
        data["state"] = CaseState(data["state"])
        data["citations"] = json.loads(data.get("citations") or "[]")
        data["candidates"] = json.loads(data.get("candidates") or "[]")
        data["tools_used"] = json.loads(data.get("tools_used") or "[]")
        data["steps"] = json.loads(data.get("steps") or "[]")
        data["findings"] = json.loads(data.get("findings") or "[]")
        return Case(**{k: v for k, v in data.items() if k in Case.__dataclass_fields__})

    def batch(self, batch_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM batches WHERE batch_id = ?",
                             (batch_id,)).fetchone()
            return dict(row) if row else None

    def batches(self, tenant: str | None = None) -> list[dict]:
        sql = "SELECT * FROM batches"
        args: tuple = ()
        if tenant:
            sql += " WHERE tenant = ?"
            args = (tenant,)
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql + " ORDER BY created_at DESC", args)]

    def cases(self, batch_id: str, tenant: str | None = None) -> list[Case]:
        sql = "SELECT * FROM cases WHERE batch_id = ?"
        args: list = [batch_id]
        if tenant:
            sql += " AND tenant = ?"
            args.append(tenant)
        with self.connect() as db:
            return [self._to_case(r) for r in db.execute(sql + " ORDER BY item_id", args)]

    def case(self, case_id: str, tenant: str | None = None) -> Case | None:
        sql = "SELECT * FROM cases WHERE case_id = ?"
        args: list = [case_id]
        if tenant:
            sql += " AND tenant = ?"
            args.append(tenant)
        with self.connect() as db:
            row = db.execute(sql, args).fetchone()
            return self._to_case(row) if row else None

    def events(self, case_id: str) -> list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM case_events WHERE case_id = ? ORDER BY event_id", (case_id,))]

    def attempts(self, case_id: str) -> list[dict]:
        """Every attempt at this case, oldest first, each with its own transcript."""
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM case_attempts WHERE case_id = ? ORDER BY attempt_id",
                (case_id,)).fetchall()
        out = []
        for r in rows:
            row = dict(r)
            row["steps"] = json.loads(row.get("steps") or "[]")
            out.append(row)
        return out

    def flow(self, batch_id: str) -> dict:
        """What the pipeline actually did, shaped for the flow view.

        Node occupancy comes from current state; edge traffic comes from the event
        log, because a case that passed through `NEEDS_INPUT` and came back has
        travelled an edge the current state no longer shows. The difference between
        those two readings is the whole point of the view.
        """
        with self.connect() as db:
            states = {r["state"]: r["n"] for r in db.execute(
                "SELECT state, COUNT(*) n FROM cases WHERE batch_id=? GROUP BY state",
                (batch_id,))}
            edges = {f'{r["from_state"]}->{r["to_state"]}': r["n"] for r in db.execute(
                "SELECT e.from_state, e.to_state, COUNT(*) n FROM case_events e"
                " JOIN cases c ON c.case_id = e.case_id WHERE c.batch_id = ?"
                " GROUP BY e.from_state, e.to_state", (batch_id,))}
            agg = db.execute(
                "SELECT COALESCE(SUM(tool_calls),0) tc, COALESCE(SUM(seconds),0) secs,"
                " COALESCE(MAX(tool_calls),0) worst, COUNT(*) n"
                " FROM cases WHERE batch_id=? AND route='AGENT'", (batch_id,)).fetchone()
            tools = db.execute(
                "SELECT tools_used FROM cases WHERE batch_id=? AND tools_used <> '[]'",
                (batch_id,)).fetchall()
            found = db.execute(
                "SELECT findings FROM cases WHERE batch_id=? AND findings <> '[]'",
                (batch_id,)).fetchall()
        # The compliance split, which is the claim this product makes: how much
        # of what an import owes was worked out and closed, and how much needed a
        # person. Counted per case, because a case raised for a person is raised
        # whatever else was settled on it.
        settled_here = for_a_person = 0
        for row in found:
            findings = json.loads(row["findings"] or "[]")
            if any(f.get("severity") == 0 for f in findings):
                for_a_person += 1
            elif findings:
                settled_here += 1
        used: dict[str, int] = {}
        for row in tools:
            for name, n in json.loads(row["tools_used"]):
                used[name] = used.get(name, 0) + n
        return {
            "states": {str(s): states.get(str(s), 0) for s in CaseState},
            "edges": edges,
            "agent": {"cases": agg["n"], "tool_calls": agg["tc"],
                      "seconds": round(agg["secs"], 1), "worst_case_tools": agg["worst"]},
            "tools_used": used,
            "dispositions": {"settled_here": settled_here, "for_a_person": for_a_person},
        }

    def timeline(self, batch_id: str) -> list[dict]:
        """Every transition in the batch, in the order it happened.

        This is what replay mode plays back. It is the real run's audit trail, not
        a scripted animation, which matters twice: the recording cannot drift from
        what the system does, and a one-take video does not have to gamble on API
        latency at the moment the camera is rolling.
        """
        with self.connect() as db:
            rows = db.execute(
                "SELECT e.event_id, e.case_id, e.at, e.from_state, e.to_state,"
                " e.actor, e.detail, c.item_id, c.bucket, c.route, c.tool_calls,"
                " c.seconds, c.selected_code, c.missing_property, c.ask_department,"
                " c.steps"
                " FROM case_events e JOIN cases c ON c.case_id = e.case_id"
                " WHERE c.batch_id = ? ORDER BY e.event_id", (batch_id,)).fetchall()
        out = []
        for r in rows:
            row = dict(r)
            row["steps"] = json.loads(row.get("steps") or "[]")
            out.append(row)
        return out

    def audit(self, batch_id: str) -> list[dict]:
        """Everything that happened to this batch, in order, with who did it.

        This is the record the officer's signature sits on top of. It is
        append-only and it includes the attempts that failed, because a trail that
        only records successes is not a trail.
        """
        with self.connect() as db:
            rows = db.execute(
                "SELECT e.event_id, e.at, e.from_state, e.to_state, e.actor, e.detail,"
                " c.item_id, c.case_id, c.bucket, c.route, c.tool_calls, c.tools_used,"
                " c.seconds, c.selected_code, c.confidence, c.findings"
                " FROM case_events e JOIN cases c ON c.case_id = e.case_id"
                " WHERE c.batch_id = ? ORDER BY e.event_id DESC", (batch_id,)).fetchall()
        out = []
        for r in rows:
            row = dict(r)
            row["tools_used"] = json.loads(row.get("tools_used") or "[]")
            row["findings"] = json.loads(row.get("findings") or "[]")
            out.append(row)
        return out

    def counts(self, batch_id: str) -> dict[str, int]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT state, COUNT(*) n FROM cases WHERE batch_id = ? GROUP BY state",
                (batch_id,)).fetchall()
            by_route = db.execute(
                "SELECT route, COUNT(*) n FROM cases WHERE batch_id = ? AND route <> ''"
                " GROUP BY route", (batch_id,)).fetchall()
        counts = {str(s): 0 for s in CaseState}
        counts.update({r["state"]: r["n"] for r in rows})
        counts["_deterministic"] = next(
            (r["n"] for r in by_route if r["route"] == "DETERMINISTIC"), 0)
        counts["_agent"] = next((r["n"] for r in by_route if r["route"] == "AGENT"), 0)
        counts["_total"] = sum(r["n"] for r in rows)
        return counts
