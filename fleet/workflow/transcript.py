"""One case's work, as the ordered lines a reviewer reads.

The screen used to show that an agent ran and what it concluded, which is exactly
the shape a scripted pipeline has: a spinner and an answer. What separates the two
is the middle, and the middle is a sequence nothing but a real run can produce —
each lookup with what it returned, then each candidate with the note or ruling
that killed it, then the citation check going through line by line.

This is a pure function of the answer, so the transcript cannot drift from the run
that produced it, and replay plays back the same rows rather than a re-enactment.
"""

from __future__ import annotations

ARG_ORDER = ("chapter", "prefix", "ruling_number", "query", "tariff_prefix", "since")


def _call_line(call: dict) -> str:
    args = call.get("args") or {}
    shown = [f"{k}={args[k]}" for k in ARG_ORDER if args.get(k)]
    return f"{call.get('name', '?')}({', '.join(shown)})"


def steps(answer: dict, verdict=None) -> list[dict]:
    """Every move in the order it happened: lookups, eliminations, the decision.

    `verdict` is the citation checker's result, which is a separate actor and is
    labelled as one. A transcript where the agent both decides and blesses its own
    citations would be describing the wrong system.
    """
    out: list[dict] = []
    for call in answer.get("tool_calls") or []:
        out.append({"kind": "tool", "actor": "agent", "text": _call_line(call),
                    "detail": call.get("result") or ""})

    selected = answer.get("selected_code_8") or answer.get("selected_code") or ""
    for entry in answer.get("rejected") or []:
        code = entry.get("code") or ""
        # A model that lists its own choice among the rejects is describing a
        # decision it did not make; dropping the line keeps the transcript from
        # contradicting the outcome below it.
        if code and selected and code[:8] == selected[:8]:
            continue
        out.append({"kind": "reject", "actor": "agent",
                    "text": f"{code} ruled out", "detail": entry.get("why") or "",
                    "ref": entry.get("ref") or ""})

    if answer.get("status") == "NEEDS_INPUT":
        out.append({"kind": "refuse", "actor": "agent",
                    "text": f"refused: {answer.get('missing_property') or 'a fact is missing'}",
                    "detail": f"asked {answer.get('ask_department') or 'a person'}"})
    elif selected:
        runner = answer.get("runner_up_code") or ""
        detail = answer.get("distinguishing_fact") or ""
        if runner:
            detail = f"over {runner}" + (f": {detail}" if detail else "")
        out.append({"kind": "select", "actor": "agent",
                    "text": f"selected {selected}", "detail": detail,
                    "ref": f"confidence {answer.get('confidence')}"})

    for citation in answer.get("citations") or []:
        out.append({"kind": "cite", "actor": "agent",
                    "text": citation.get("ref") or "", "detail": citation.get("quote") or ""})

    if verdict is not None:
        out.append({
            "kind": "verify", "actor": "checker",
            "text": "citations resolve" if verdict.passed else "citation check failed",
            "detail": verdict.reason or f"{len(answer.get('citations') or [])} checked "
                                        "against the snapshot",
        })
    return out
