"""The compliance officer's screen, and the API behind it.

There is deliberately no chat box. The officer does not converse with this
system: a batch arrives, the deterministic layer settles what it can, agents work
the rest, and she approves once. Everything she sees is a state the workers wrote,
so the screen is a view of the database rather than a place where work happens.

Three roles, because the interesting part of the demo is what each cannot do:

    operator      creates batches and watches       cannot approve
    contributor   supplies a missing fact           cannot approve, cannot see other product lines
    approver      signs the batch off              can do all of it

The role arrives as a header here. In deployment it comes from the identity
layer, and the check moves into the database as row-level security; the shape of
the rule does not change, only who enforces it.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import re
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fleet.workflow.store import (CaseState, IllegalTransition, Store,
                                  UndecidedFinding)
from fleet.verify.faultinject import NothingToInject, inject
from fleet.workflow.roundtrip import batch as roundtrip_batch
from fleet.workflow.roundtrip import card as roundtrip_card
from fleet.workflow.timeline import band as timeline_band
from fleet.workflow.worker import Worker

HERE = Path(__file__).parent
REPO = HERE.parent.parent
DB_PATH = Path(os.environ.get("FLEET_DB", REPO / "data" / "cases.db"))
SNAPSHOT = Path(os.environ.get("FLEET_SNAPSHOT", REPO / "data" / "snapshots" / "2026-08-18"))

store = Store(DB_PATH)
worker = Worker(store, SNAPSHOT)
app = FastAPI(title="Tariff Reclassification Fleet")

ROLES = {"operator", "contributor", "approver"}


def identity(role: str | None, tenant: str | None) -> tuple[str, str]:
    role = (role or "operator").lower()
    if role not in ROLES:
        raise HTTPException(403, f"unknown role {role}")
    return role, (tenant or "plant-a")


def require(role: str, *allowed: str) -> None:
    if role not in allowed:
        raise HTTPException(
            403, f"role '{role}' cannot do this; allowed: {', '.join(allowed)}")


class NewBatch(BaseModel):
    label: str
    items: list[dict]


class Fact(BaseModel):
    value: str


class Decision(BaseModel):
    #: cleared or held. Both are decisions; neither is the machine's to make.
    decision: str
    note: str = ""


class Approval(BaseModel):
    #: Omitted means the whole batch. A list means exactly those.
    case_ids: list[str] | None = None


@app.get("/api/batches")
def list_batches(x_role: str = Header(None), x_tenant: str = Header(None)):
    _, tenant = identity(x_role, x_tenant)
    out = []
    for batch in store.batches(tenant):
        batch["counts"] = store.counts(batch["batch_id"])
        out.append(batch)
    return out


@app.post("/api/batches")
async def create_batch(body: NewBatch, x_role: str = Header(None),
                       x_tenant: str = Header(None)):
    role, tenant = identity(x_role, x_tenant)
    require(role, "operator", "approver")
    batch_id = store.create_batch(tenant, body.label, SNAPSHOT.name, body.items)
    # The officer's part is over; the run happens on its own from here.
    asyncio.create_task(asyncio.to_thread(worker.run_batch, batch_id))
    return {"batch_id": batch_id}


#: What a catalog export has to contain. Everything else in the file is ignored,
#: because an ERP export carries thirty columns and only three of them matter here.
#: The filed code is not one of them: a line nobody has ever classified is the
#: ordinary case in a broker's inbox, and triage routes it to the agent to be
#: classified from first principles rather than turning it away at the door.
REQUIRED_COLUMNS = ("item_id", "description")
COLUMN_ALIASES = {
    "item_id": {"item", "sku", "part", "part_number", "item_number", "material"},
    "prior_code": {"code", "hts", "hts_code", "tariff", "tariff_code", "hs_code",
                   "current_code", "filed_code"},
    "description": {"goods", "product", "product_description", "text", "name"},
    # Optional, and only optional until the line turns out to be charged by
    # weight, at which point the duty cannot be stated without them.
    "quantity": {"qty", "net_quantity", "net_weight", "weight", "units"},
    "quantity_unit": {"unit", "uom", "quantity_uom", "weight_unit"},
    "country_of_origin": {"origin", "coo", "country"},
    "supplier": {"vendor", "manufacturer", "shipper", "seller"},
}


def read_catalog_csv(raw: bytes) -> list[dict]:
    """Parse an exported catalog, and say plainly what is wrong when it will not.

    A compliance officer's catalog arrives as a spreadsheet export, so the reader
    has to survive a byte-order mark, whatever the export tool called its columns,
    and a description field with line breaks inside it.
    """
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(400, "the file has no header row")

    # Map whatever the export called its columns onto the three that are needed.
    found: dict[str, str] = {}
    for name in reader.fieldnames:
        key = (name or "").strip().lower().replace(" ", "_")
        for wanted, aliases in COLUMN_ALIASES.items():
            if key == wanted or key in aliases:
                found.setdefault(wanted, name)
    missing = [c for c in REQUIRED_COLUMNS if c not in found]
    if missing:
        raise HTTPException(400, f"missing column(s): {', '.join(missing)}. "
                                 f"The file has: {', '.join(reader.fieldnames)}")

    items, skipped = [], 0
    for row in reader:
        raw_code = row.get(found["prior_code"]) if "prior_code" in found else ""
        code = re.sub(r"\D", "", raw_code or "")
        description = (row.get(found["description"]) or "").strip()
        item_id = (row.get(found["item_id"]) or "").strip()
        if not description or not item_id:
            skipped += 1
            continue
        # A code shorter than a subheading cannot be looked up in the correlation
        # table, and a half-code would send triage looking for a heading that was
        # never filed. Dropping it says the same thing more honestly: nothing to
        # carry forward, classify it.
        row_out = {"item_id": item_id, "prior_code": code if len(code) >= 6 else "",
                   "description": description[:4000]}
        for extra in ("quantity_unit", "country_of_origin", "supplier"):
            if extra in found:
                row_out[extra] = (row.get(found[extra]) or "").strip() or None
        if "quantity" in found:
            try:
                row_out["quantity"] = float(re.sub(r"[^\d.]", "",
                                                   row.get(found["quantity"]) or "") or 0) or None
            except ValueError:
                row_out["quantity"] = None
        items.append(row_out)
    if not items:
        raise HTTPException(400, f"no usable rows: every line was missing an item "
                                 f"or a description ({skipped} skipped)")
    return items


@app.post("/api/batches/import")
async def import_catalog(file: UploadFile = File(...), label: str = Form(None),
                         x_role: str = Header(None), x_tenant: str = Header(None)):
    """Take a catalog export and start work on it."""
    role, tenant = identity(x_role, x_tenant)
    require(role, "operator", "approver")
    items = read_catalog_csv(await file.read())
    batch_id = store.create_batch(tenant, label or f"Imported {file.filename}",
                                  SNAPSHOT.name, items)
    asyncio.create_task(asyncio.to_thread(worker.run_batch, batch_id))
    return {"batch_id": batch_id, "items": len(items)}


@app.get("/api/sample.csv")
def sample_csv():
    """A ready-made export, so anyone can try the import without inventing data."""
    path = REPO / "fleet" / "app" / "sample-catalog.csv"
    return FileResponse(path, media_type="text/csv", filename="catalog-sample.csv")


@app.get("/api/batches/{batch_id}")
def get_batch(batch_id: str, x_role: str = Header(None), x_tenant: str = Header(None)):
    _, tenant = identity(x_role, x_tenant)
    batch = store.batch(batch_id)
    if not batch or batch["tenant"] != tenant:
        raise HTTPException(404, "no such batch for this product line")
    cases = store.cases(batch_id, tenant)
    return {
        "batch": batch,
        "counts": store.counts(batch_id),
        "cases": [
            {"case_id": c.case_id, "item_id": c.item_id, "state": str(c.state),
             "route": c.route, "bucket": c.bucket, "selected_code": c.selected_code,
             "confidence": c.confidence, "duty_rate": c.duty_rate,
             "missing_property": c.missing_property, "ask_department": c.ask_department,
             "description": c.description[:160], "prior_code": c.prior_code,
             "findings": c.findings}
            for c in cases
        ],
    }


#: Row counts read from the snapshot's own manifests, so the diagram states the
#: size of what the agent reached into rather than a number somebody typed. They
#: were hardcoded in `flow.js` under a comment claiming they came from here, and
#: a snapshot revision would have quietly turned them into fiction on a screen
#: whose entire purpose is being checkable.
def corpus_sizes() -> dict:
    out = {}
    for source in ("hts", "notes", "cross", "csl", "correlation"):
        path = SNAPSHOT / f"{source}.manifest.json"
        if path.exists():
            manifest = json.loads(path.read_text(encoding="utf-8"))
            out[source] = {"rows": manifest.get("row_count"),
                           "revision": manifest.get("revision")}
    # Not a fetched source: the full ruling texts are a file, not a manifest.
    texts = SNAPSHOT / "ruling_text.jsonl"
    if texts.exists():
        out["ruling_text"] = {"rows": sum(1 for line in
                                          texts.open(encoding="utf-8") if line.strip()),
                              "revision": None}
    return out


@app.get("/api/batches/{batch_id}/flow")
def get_flow(batch_id: str, since: int = 0,
             x_role: str = Header(None), x_tenant: str = Header(None)):
    """The pipeline as a graph: node occupancy, edge traffic, and what it cost."""
    _, tenant = identity(x_role, x_tenant)
    batch = store.batch(batch_id)
    if not batch or batch["tenant"] != tenant:
        raise HTTPException(404, "no such batch for this product line")
    flow = store.flow(batch_id)
    # Transitions since the client last looked. The view fires one dot per actual
    # move rather than animating every edge forever: most cases are parked, and a
    # diagram that shows them all flowing is describing a system that does not exist.
    events = [e for e in store.timeline(batch_id) if e["event_id"] > since]
    flow["moves"] = [{"event_id": e["event_id"], "from": e["from_state"],
                      "to": e["to_state"], "item_id": e["item_id"]} for e in events]
    flow["corpus"] = corpus_sizes()
    # Every question this batch has asked, open ones first. The finished round
    # trip is the better story; the open one is the more honest picture, and a
    # screen that drew only the finished ones would show a system that never waits.
    flow["roundtrips"] = roundtrip_batch(
        [{"case": store.case(c.case_id).__dict__ | {"case_id": c.case_id},
          "facts": store.facts(c.case_id), "attempts": store.attempts(c.case_id),
          "events": store.events(c.case_id)}
         for c in store.cases(batch_id, tenant)])
    flow["last_event_id"] = max((e["event_id"] for e in store.timeline(batch_id)),
                                default=0)
    flow["active"] = [dict(v, case_id=k) for k, v in worker.active.items()]
    flow["cases"] = [
        {"case_id": c.case_id, "item_id": c.item_id, "state": str(c.state),
         "route": c.route, "bucket": c.bucket, "tool_calls": c.tool_calls,
         "seconds": c.seconds, "selected_code": c.selected_code,
         "missing_property": c.missing_property, "ask_department": c.ask_department,
         # The transcript travels with the case rather than behind another
         # request: the feed has to append a case's lines the moment it lands,
         # and a second round trip per case would arrive after the animation.
         "steps": c.steps}
        for c in store.cases(batch_id, tenant)]
    return flow


@app.get("/api/batches/{batch_id}/timeline")
def get_timeline(batch_id: str, x_role: str = Header(None), x_tenant: str = Header(None)):
    """The recorded run, for replay. Real events, replayed at the viewer's pace."""
    _, tenant = identity(x_role, x_tenant)
    batch = store.batch(batch_id)
    if not batch or batch["tenant"] != tenant:
        raise HTTPException(404, "no such batch for this product line")
    events = store.timeline(batch_id)
    return {"batch": batch, "total_cases": len(store.cases(batch_id, tenant)),
            "events": events}


@app.get("/api/batches/{batch_id}/band")
def get_band(batch_id: str, x_role: str = Header(None), x_tenant: str = Header(None)):
    """The batch on a clock: which stretches were worked, which were waited out.

    Reads the same event list replay does, grouped per case. A batch's own run
    takes minutes and the weeks come from cases that stopped and were picked up
    days later, so both have to be drawn against the same axis to read as the
    different things they are.
    """
    _, tenant = identity(x_role, x_tenant)
    batch = store.batch(batch_id)
    if not batch or batch["tenant"] != tenant:
        raise HTTPException(404, "no such batch for this product line")
    lanes: dict[str, dict] = {}
    for event in store.timeline(batch_id):
        lane = lanes.setdefault(event["case_id"],
                                {"case_id": event["case_id"],
                                 "item_id": event.get("item_id", "?"), "events": []})
        lane["events"].append(event)
    return timeline_band(list(lanes.values()))


@app.get("/api/batches/{batch_id}/audit")
def get_audit(batch_id: str, x_role: str = Header(None), x_tenant: str = Header(None)):
    """Everything that happened to this batch, newest first, with who did it.

    This is the record the officer's signature sits on top of, so it includes the
    attempts that failed: a trail that only shows successes is not a trail. It is
    read-only for every role, because an audit trail somebody can curate is not
    one either.
    """
    _, tenant = identity(x_role, x_tenant)
    batch = store.batch(batch_id)
    if not batch or batch["tenant"] != tenant:
        raise HTTPException(404, "no such batch for this product line")
    return {"batch": batch, "events": store.audit(batch_id)}


@app.get("/api/cases/{case_id}")
def get_case(case_id: str, x_role: str = Header(None), x_tenant: str = Header(None)):
    _, tenant = identity(x_role, x_tenant)
    case = store.case(case_id, tenant)
    if not case:
        raise HTTPException(404, "no such case for this product line")
    facts, attempts = store.facts(case_id), store.attempts(case_id)
    return {"case": case.__dict__ | {"state": str(case.state)},
            "events": store.events(case_id),
            "facts": facts,
            # What the wait bought, stated rather than left for the reader to
            # work out by diffing two transcripts.
            "roundtrip": roundtrip_card(attempts, facts, case.selected_code),
            # Every attempt, not just the last one. The refusal and the decision
            # that followed it are two different pieces of reasoning and the
            # person signing is entitled to both.
            "attempts": attempts}


@app.post("/api/cases/{case_id}/inject-fault")
def inject_fault(case_id: str, x_role: str = Header(None), x_tenant: str = Header(None)):
    """Alter one word of one citation and let the real checker refuse it.

    A control nobody has watched fail is a claim. This takes the citations this
    case actually shipped with, inserts a single word into one quote, and runs
    the same `CitationVerifier.check` every case goes through. The snapshot is
    untouched, no ruling number is invented, and the stored case is not changed:
    the fault lives in the copy that is checked, which is where a hallucinated
    citation would live.

    It deliberately does not move the case to VERIFY_FAILED. `READY` has one
    legal exit and it is `APPROVED`; widening the state machine so a
    demonstration can reach a state the run never reached would be a worse lie
    than the one this is here to disprove.
    """
    role, tenant = identity(x_role, x_tenant)
    require(role, "operator", "approver")
    case = store.case(case_id, tenant)
    if not case:
        raise HTTPException(404, "no such case for this product line")
    if not case.citations:
        raise HTTPException(409, "this case shipped no citations, so there is nothing to alter")

    answer = {"item_id": case.item_id, "status": "CLASSIFIED",
              "selected_code_8": re.sub(r"\D", "", case.selected_code or "")[:8],
              "citations": [dict(c) for c in case.citations]}
    before = worker.verifier.check(answer)
    try:
        faulted, note = inject(answer)
    except NothingToInject as exc:
        raise HTTPException(409, str(exc))
    after = worker.verifier.check(faulted)
    return {"note": note, "passed_before": before.passed,
            "passed_after": after.passed, "reason": after.reason}


@app.post("/api/cases/{case_id}/fact")
async def supply_fact(case_id: str, body: Fact, x_role: str = Header(None),
                      x_tenant: str = Header(None)):
    """Answer the question the agent asked, and put the case back in the queue.

    This is the cross-department seam: engineering answers a materials question
    without being able to approve anything.
    """
    role, tenant = identity(x_role, x_tenant)
    require(role, "contributor", "operator", "approver")
    case = store.case(case_id, tenant)
    if not case:
        raise HTTPException(404, "no such case for this product line")
    if case.state is not CaseState.NEEDS_INPUT:
        raise HTTPException(409, f"case is {case.state}, not waiting for a fact")

    detail = f"{case.missing_property} -> {body.value}"
    # Stored before the re-run is scheduled, so every later run of this case sees
    # it too, not just the one this request kicked off.
    store.add_fact(case_id, case.missing_property or "", body.value, role)
    store.transition(case_id, CaseState.CLASSIFYING, role,
                     f"fact:{case_id}:{len(store.events(case_id))}", detail=detail)
    asyncio.create_task(asyncio.to_thread(worker.run_case, case_id))
    return {"ok": True}


@app.post("/api/cases/{case_id}/advance")
async def advance_case(case_id: str, x_role: str = Header(None),
                       x_tenant: str = Header(None)):
    """Move one case on, for the cases where that is the sensible thing to do.

    The batch signature stays the main action: approving row by row is the
    hand-holding this system exists to remove. What this is for is the straggler,
    the item that came back from engineering after the rest were signed, and the
    one whose citations failed and deserves another attempt. Neither is worth
    re-approving twenty items over.
    """
    role, tenant = identity(x_role, x_tenant)
    case = store.case(case_id, tenant)
    if not case:
        raise HTTPException(404, "no such case for this product line")

    if case.state in (CaseState.READY, CaseState.SETTLED):
        require(role, "approver")
        try:
            store.transition(case_id, CaseState.APPROVED, role,
                             f"approve-one:{case_id}", detail="approved individually")
        except UndecidedFinding as exc:
            raise HTTPException(409, str(exc))
        return {"state": "APPROVED"}

    # A case left CLASSIFYING by a worker that died is stranded: nothing will ever
    # pick it up again. Restarting it is the only honest recovery, and it is safe
    # because a fresh attempt writes under a new idempotency key.
    stranded = (case.state is CaseState.CLASSIFYING
                and case_id not in worker.active)
    if case.state is CaseState.VERIFY_FAILED or stranded:
        require(role, "operator", "approver")
        store.transition(case_id, CaseState.CLASSIFYING, role,
                         f"rerun:{case_id}:{len(store.events(case_id))}",
                         detail="re-run after a failed citation check"
                                if case.state is CaseState.VERIFY_FAILED
                                else "restarted; no worker was holding it")
        asyncio.create_task(asyncio.to_thread(worker.run_case, case_id))
        return {"state": "CLASSIFYING"}

    raise HTTPException(409, f"a case in {case.state} moves on its own or needs a fact, "
                             "not a nudge")


@app.post("/api/batches/{batch_id}/restart-stranded")
async def restart_stranded(batch_id: str, x_role: str = Header(None),
                           x_tenant: str = Header(None)):
    """Pick up everything a dead worker left mid-flight."""
    role, tenant = identity(x_role, x_tenant)
    require(role, "operator", "approver")
    batch = store.batch(batch_id)
    if not batch or batch["tenant"] != tenant:
        raise HTTPException(404, "no such batch for this product line")
    restarted = []
    for case in store.cases(batch_id, tenant):
        if case.state is CaseState.CLASSIFYING and case.case_id not in worker.active:
            store.transition(case.case_id, CaseState.CLASSIFYING, role,
                             f"restart:{case.case_id}:{len(store.events(case.case_id))}",
                             detail="restarted; no worker was holding it")
            asyncio.create_task(asyncio.to_thread(worker.run_case, case.case_id))
            restarted.append(case.case_id)
    return {"restarted": len(restarted)}


@app.post("/api/cases/{case_id}/findings/{index}/decide")
def decide_finding(case_id: str, index: int, body: Decision,
                   x_role: str = Header(None), x_tenant: str = Header(None)):
    """Record what a person decided about the one thing a program will not.

    A screening match is a question about who somebody is, and the batch
    signature holds any case carrying an undecided one. Clearing it is a
    deliberate act with a name on it, which is the only form of clearance worth
    having.
    """
    role, tenant = identity(x_role, x_tenant)
    require(role, "approver")
    if not store.case(case_id, tenant):
        raise HTTPException(404, "no such case for this product line")
    try:
        return store.decide_finding(case_id, index, body.decision, role, body.note)
    except (ValueError, IndexError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/batches/{batch_id}/approve")
def approve(batch_id: str, body: Approval | None = None,
            x_role: str = Header(None), x_tenant: str = Header(None)):
    role, tenant = identity(x_role, x_tenant)
    require(role, "approver")
    batch = store.batch(batch_id)
    if not batch or batch["tenant"] != tenant:
        raise HTTPException(404, "no such batch for this product line")
    try:
        only = set(body.case_ids) if body and body.case_ids is not None else None
        return store.approve_batch(batch_id, role, only=only)
    except IllegalTransition as exc:
        raise HTTPException(409, str(exc))


@app.get("/api/catalog")
def catalog():
    """The demo catalog, so the operator has something to submit."""
    path = REPO / "fleet" / "app" / "catalog.json"
    return json.loads(path.read_text()) if path.exists() else []


@app.get("/health")
def health():
    return {"ok": True, "snapshot": SNAPSHOT.name, "db": str(DB_PATH)}


app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.get("/")
def index():
    """The page, with the module's version stamped into its import.

    A browser holds an ES module by URL, so an edited `flow.js` keeps rendering
    the old diagram until somebody thinks to hard-reload. That is a bad way to
    find out mid-recording, and worse when a judge is the one looking at a screen
    that disagrees with the description.
    """
    html = (HERE / "static" / "index.html").read_text(encoding="utf-8")
    version = int((HERE / "static" / "flow.js").stat().st_mtime)
    html = html.replace("/static/flow.js", f"/static/flow.js?v={version}")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.exception_handler(IllegalTransition)
def illegal(_, exc: IllegalTransition):
    return JSONResponse({"detail": str(exc)}, status_code=409)
