"""The background worker: triage, classify, verify, and record what happened.

Nobody watches this run. It is started by a batch arriving and it works through
the cases on its own, which is the whole point of the product: the officer's
attention is spent on the one item that needs a human, not on the nineteen that
do not.

The order is deliberate and it is where the autonomy number comes from:

1. `assert_healthy` on the snapshot. A bad snapshot halts the line rather than
   producing nineteen confident answers from stale law.
2. Triage. A code that still exists is settled here. A dead code with exactly one
   correlation candidate is settled here too, and never reaches an agent, because
   feeding table-lookup items to a model inflates the autonomy denominator with
   free wins.
3. The agent, for what is left.
4. The verifier. A classification whose citations do not resolve does not ship,
   whatever the model's confidence said.
"""

from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fleet.agents.classifier import Item, Runner, load_candidates
from fleet.agents.tools import Snapshot
from fleet.findings.engine import Severity, assess
from fleet.sync.gate import DataSourceUnhealthy, assert_healthy
from fleet.triage.duty import resolve
from fleet.triage.engine import triage
from fleet.triage.types import LineItem, Route
from fleet.verify.citations import CitationVerifier
from fleet.verify.grounding import fact_source
from fleet.workflow.store import CaseState, Store
from fleet.workflow.transcript import steps as transcript_steps


class Worker:
    def __init__(self, store: Store, snapshot_dir: Path):
        self.store = store
        self.snapshot = Path(snapshot_dir)
        self._runner: Runner | None = None
        self._verifier: CitationVerifier | None = None
        self._candidates: dict | None = None
        self._snap: Snapshot | None = None
        #: Cases in flight right now, keyed by case id. In-memory on purpose: it
        #: is a view of this process's work, not a fact worth persisting, and it
        #: must be empty again the moment the process restarts.
        self.active: dict[str, dict] = {}

    # Built on first use: a worker that never runs should not pay to load a
    # 218,606-row index, and the web process imports this module at startup.
    @property
    def runner(self) -> Runner:
        if self._runner is None:
            self._runner = Runner(self.snapshot)
        return self._runner

    @property
    def verifier(self) -> CitationVerifier:
        if self._verifier is None:
            self._verifier = CitationVerifier(self.snapshot)
        return self._verifier

    @property
    def snap(self) -> Snapshot:
        """A reader over the snapshot that does not drag in the 218,606-row
        precedent index. Settling a case by lookup must not pay for the agent."""
        if self._snap is None:
            self._snap = Snapshot(self.snapshot)
        return self._snap

    def dispose(self, case, selected: str, runner_up: str | None = None) -> dict:
        """What this classification means for the importer, worked out at once.

        This is the part that decides how much of the compliance work a person
        still has to do. Money follows arithmetic, so the arithmetic is done and
        stated: the rate gap against what was filed, the chapter 99 add-on for
        goods of the wrong origin, the duty on lines charged by weight. Identity
        does not follow arithmetic, so a supplier resembling a listed party is
        raised and left for a person, with what matched and what differs.

        Returned as fields for the transition rather than written separately: a
        case reaching READY without its findings would be a case somebody could
        sign before the system finished saying what it costs.
        """
        payload = {
            "item_id": case.item_id, "prior_code": case.prior_code,
            "selected_code": selected, "runner_up_code": runner_up,
            "country_of_origin": case.country_of_origin, "supplier": case.supplier,
            "annual_value": case.annual_value,
            "quantity": getattr(case, "quantity", None),
            "quantity_unit": getattr(case, "quantity_unit", None),
        }
        findings = assess(payload, self.snap, self.snap.screening)
        return {
            "findings": [{"kind": f.kind, "severity": int(f.severity),
                          "headline": f.headline, "detail": f.detail} for f in findings],
            "steps_extra": [
                {"kind": "finding", "actor": "compliance",
                 "text": f.headline,
                 "detail": f.detail,
                 "ref": "for a person" if f.severity is Severity.HUMAN else "settled here"}
                for f in findings],
        }

    @property
    def candidates(self) -> dict:
        if self._candidates is None:
            self._candidates = load_candidates(self.snapshot)
        return self._candidates

    def run_batch(self, batch_id: str) -> None:
        try:
            assert_healthy(self.snapshot, sources=("hts", "correlation", "notes"))
        except DataSourceUnhealthy as exc:
            for case in self.store.cases(batch_id):
                self.store.transition(case.case_id, CaseState.BLOCKED, "gate",
                                      f"blocked:{case.case_id}", detail=str(exc))
            return

        cases = self.store.cases(batch_id)
        items = [LineItem(item_id=c.case_id, description=c.description,
                          hs_code=c.prior_code, product_line=c.tenant) for c in cases]
        results = {r.item_id: r for r in triage(items, self.snapshot)}

        for case in cases:
            result = results[case.case_id]
            if result.route is Route.DETERMINISTIC:
                settled_code = result.selected_code or case.prior_code
                # A case settled by lookup still owes money and still has a
                # supplier. Skipping the compliance pass for the easy half would
                # mean the cheap cases are the ones nobody checked.
                found = self.dispose(case, settled_code)
                self.store.transition(
                    case.case_id, CaseState.SETTLED, "triage", f"triage:{case.case_id}",
                    findings=found["findings"],
                    detail=result.reason, route=str(result.route), bucket=str(result.bucket),
                    selected_code=result.selected_code or case.prior_code,
                    duty_rate=result.current_duty.general if result.current_duty else None,
                    reasoning=result.reason,
                    candidates=[c.hs_code for c in result.candidates],
                    # A settled case gets a transcript too, saying what settled
                    # it. "Nothing to decide" is a finding, and an empty panel
                    # would read as a case nobody worked.
                    steps=[{"kind": "settle", "actor": "lookup",
                            "text": f"settled without a model: {result.bucket}",
                            "detail": result.reason}] + found["steps_extra"])
            else:
                self.store.transition(
                    case.case_id, CaseState.CLASSIFYING, "triage", f"triage:{case.case_id}",
                    detail=result.reason, route=str(result.route), bucket=str(result.bucket),
                    candidates=[c.hs_code for c in result.candidates])

        # Several at once, because a fleet that works one item at a time is not a
        # fleet, and the live view would show a single agent moving down a queue.
        queued = [c.case_id for c in self.store.cases(batch_id)
                  if c.state is CaseState.CLASSIFYING]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(self.run_case, queued))

    def run_case(self, case_id: str) -> None:
        """Classify one case and record the outcome, whatever it is.

        Facts somebody supplied are read from the store, not passed in. They used
        to arrive as an argument from the endpoint that triggered the re-run,
        which meant every other way of re-running a case, a failed citation check
        or a restart after a crash, showed the agent the original description and
        asked engineering a question it had already answered.
        """
        case = self.store.case(case_id)
        if case is None:
            return
        attempt = len(self.store.events(case_id))
        description = case.description
        supplied = self.store.facts(case_id)
        if supplied:
            answers = "\n".join(
                f"- {f['property']}: {f['value']}" if f["property"] else f"- {f['value']}"
                for f in supplied)
            description = (f"{description}\n\nAdditional information supplied by the "
                           f"company:\n{answers}")

        self.active[case_id] = {"item_id": case.item_id, "bucket": case.bucket,
                                "tool": "starting", "calls": 0}

        def progress(kind: str, payload: dict) -> None:
            if kind == "tool" and case_id in self.active:
                self.active[case_id].update(tool=payload["tool"], calls=payload["calls"])

        try:
            item = Item(item_id=case.item_id, description=description,
                        prior_hs6=case.prior_code[:6],
                        candidates=self.candidates.get(case.prior_code[:6], []))
            answer = self.runner.classify(item, on_event=progress)
        except Exception as exc:  # noqa: BLE001
            self.active.pop(case_id, None)
            self.store.transition(
                case_id, CaseState.NEEDS_INPUT, "worker", f"error:{case_id}:{attempt}",
                detail=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-400:]}",
                missing_property="the classifier could not complete; a person should look",
                ask_department="compliance",
                steps=[{"kind": "error", "actor": "worker",
                        "text": f"the run stopped: {type(exc).__name__}",
                        "detail": str(exc)[:200]}])
            return

        self.active.pop(case_id, None)
        answer["item_id"] = case.item_id
        verdict = self.verifier.check(answer)
        # How hard this one was, in the only units that are not guesswork.
        used: dict[str, int] = {}
        for call in answer.get("tool_calls") or []:
            used[call["name"]] = used.get(call["name"], 0) + 1
        effort = {"tool_calls": answer.get("tool_call_count", 0),
                  "tools_used": sorted(used.items()),
                  "seconds": answer.get("seconds", 0.0),
                  "attempts": attempt,
                  # A refusal produced no classification to check, so naming the
                  # checker there would credit it with work it never did.
                  "steps": transcript_steps(
                      answer, None if answer.get("status") == "NEEDS_INPUT" else verdict)}

        if answer.get("status") == "NEEDS_INPUT":
            self.store.transition(
                case_id, CaseState.NEEDS_INPUT, "classifier",
                f"needs-input:{case_id}:{attempt}", detail=answer.get("reasoning", "")[:400],
                missing_property=answer.get("missing_property"),
                ask_department=answer.get("ask_department"),
                confidence=answer.get("confidence"),
                reasoning=answer.get("reasoning", ""), **effort)
            return

        if not verdict.passed:
            self.store.transition(
                case_id, CaseState.VERIFY_FAILED, "verifier",
                f"verify-failed:{case_id}:{attempt}", detail=verdict.reason,
                verify_reason=verdict.reason, confidence=answer.get("confidence"),
                reasoning=answer.get("reasoning", ""),
                citations=answer.get("citations", []), **effort)
            return

        duty = resolve(answer["selected_code"], self.runner.snapshot.hts)
        prior = resolve(case.prior_code, self.runner.snapshot.hts) if len(case.prior_code) >= 8 else None
        found = self.dispose(case, answer["selected_code"], answer.get("runner_up_code"))
        effort["steps"] = effort["steps"] + found["steps_extra"]
        self.store.transition(
            case_id, CaseState.READY, "classifier", f"classified:{case_id}:{attempt}",
            findings=found["findings"],
            detail=f"selected {answer['selected_code']}",
            selected_code=answer["selected_code"],
            runner_up_code=answer.get("runner_up_code"),
            confidence=answer.get("confidence"),
            distinguishing_fact=answer.get("distinguishing_fact") or "",
            decisive_quote=answer.get("decisive_quote") or "",
            # Against the description the agent was shown, which includes facts
            # the company supplied afterwards: those are the importer speaking
            # too, and a case that went out for an answer and came back should
            # not read as an inference for having taken the long way.
            fact_source=str(fact_source(answer.get("decisive_quote"), description)),
            reasoning=answer.get("reasoning", ""),
            citations=answer.get("citations", []),
            duty_rate=duty.general if duty else None,
            prior_duty_rate=prior.general if prior else None,
            verify_reason="", **effort)
