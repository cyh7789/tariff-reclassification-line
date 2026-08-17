"""Run the classifier over one line item, or over a development batch.

Model is Gemini 3.7 Flash. The Pro line on Vertex stops at 3.1, below the 3.5
floor this project targets, so there is no stronger model to review the answer
with. Everything that makes an answer trustworthy therefore has to come from
outside the model: tools that only return rows that exist, and a verifier that
re-resolves every citation afterwards.

Usage:

    python -m fleet.agents.classifier --snapshot data/snapshots/2026-08-18 \\
        --dev internal/evalset/dev.jsonl --limit 20 --out runs/dev-01.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from google import genai
from google.genai import types

from fleet.agents import tools
from fleet.agents.tools import PrecedentIndex, Snapshot

MODEL = "gemini-3.7-flash"
PROJECT = "yuhina-496113"
LOCATION = "global"
MAX_TOOL_TURNS = 16
CONFIDENCE_FLOOR = 0.80

PROMPT_PATH = Path(__file__).parent / "prompts" / "classifier.md"

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "required": ["status", "reasoning", "citations", "confidence"],
    "properties": {
        "status": {"type": "STRING", "enum": ["CLASSIFIED", "NEEDS_INPUT"]},
        "selected_code": {"type": "STRING", "nullable": True},
        "selected_code_8": {"type": "STRING", "nullable": True},
        "runner_up_code": {"type": "STRING", "nullable": True},
        "distinguishing_fact": {"type": "STRING", "nullable": True},
        "reasoning": {"type": "STRING"},
        "citations": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "required": ["kind", "ref"],
                "properties": {
                    "kind": {"type": "STRING", "enum": ["chapter_note", "tariff_line", "ruling"]},
                    "ref": {"type": "STRING"},
                    "quote": {"type": "STRING", "nullable": True},
                },
            },
        },
        "confidence": {"type": "NUMBER"},
        "missing_property": {"type": "STRING", "nullable": True},
        "ask_department": {"type": "STRING", "nullable": True},
    },
}

TOOL_DECLARATIONS = [
    {
        "name": "get_chapter_notes",
        "description": (
            "Legal notes of one HTS chapter. Exclusion notes decide most cases, so read "
            "the chapter of every candidate before arguing about the goods."
        ),
        "parameters": {
            "type": "OBJECT",
            "required": ["chapter"],
            "properties": {"chapter": {"type": "STRING", "description": "Two digits, e.g. '85'"}},
        },
    },
    {
        "name": "get_tariff_lines",
        "description": (
            "Every tariff line under a 4-, 6- or 8-digit prefix, in schedule order, with "
            "duty rates and chapter 99 footnotes."
        ),
        "parameters": {
            "type": "OBJECT",
            "required": ["prefix"],
            "properties": {"prefix": {"type": "STRING", "description": "4 to 8 digits, no dots"}},
        },
    },
    {
        "name": "search_precedents",
        "description": (
            "Search CBP rulings by merchandise keywords, optionally restricted to a tariff "
            "prefix or a date. Returns ruling numbers that can be cited."
        ),
        "parameters": {
            "type": "OBJECT",
            "required": ["query"],
            "properties": {
                "query": {"type": "STRING", "description": "Merchandise keywords"},
                "tariff_prefix": {"type": "STRING", "nullable": True},
                "since": {"type": "STRING", "nullable": True, "description": "YYYY-MM-DD"},
            },
        },
    },
]


@dataclass
class Item:
    item_id: str
    description: str
    prior_hs6: str
    candidates: list[dict]
    truth_hts8: str | None = None
    stratum: str | None = None


def load_prompt() -> str:
    """The system prompt is the section of the prompt file under '## System prompt'."""
    text = PROMPT_PATH.read_text(encoding="utf-8")
    start = text.index("## System prompt") + len("## System prompt")
    end = text.index("\n## Tools")
    return text[start:end].strip()


def load_candidates(snapshot_dir: Path) -> dict[str, list[dict]]:
    import csv
    grouped: dict[str, list[dict]] = {}
    with (snapshot_dir / "correlation.csv").open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            grouped.setdefault(row["hs2017"], []).append({
                "hs_code": row["hs2022"],
                "is_ex": row["is_ex"] == "1",
                "relationship": row["unsd_relationship"],
                "is_sweep": row["is_sweep"] == "1",
            })
    return grouped


def render_item(item: Item) -> str:
    lines = [
        f"prior_code: {item.prior_hs6}",
        "",
        "candidates (from the official correlation table, which has no legal status):",
    ]
    for c in item.candidates:
        marks = []
        if c["is_ex"]:
            marks.append("ex, partial coverage")
        if c["is_sweep"]:
            marks.append("sweep heading")
        suffix = f"  [{'; '.join(marks)}]" if marks else ""
        lines.append(f"  {c['hs_code']}  ({c['relationship']}){suffix}")
    lines += ["", "description:", item.description]
    return "\n".join(lines)


class Runner:
    def __init__(self, snapshot_dir: Path, excluded: set[str] | None = None):
        self.snapshot = Snapshot(snapshot_dir)
        self.index = PrecedentIndex(snapshot_dir, excluded=excluded)
        self.client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
        self.system_prompt = load_prompt()

    def call_tool(self, name: str, args: dict) -> dict:
        if name == "get_chapter_notes":
            return {"notes": tools.get_chapter_notes(self.snapshot, args["chapter"])}
        if name == "get_tariff_lines":
            lines = tools.get_tariff_lines(self.snapshot, args["prefix"])
            return {"lines": [asdict(line) for line in lines]}
        if name == "search_precedents":
            hits = self.index.search(
                args["query"],
                tariff_prefix=args.get("tariff_prefix"),
                since=args.get("since"),
            )
            return {"rulings": [asdict(hit) for hit in hits]}
        return {"error": f"no tool named {name}"}

    def classify(self, item: Item) -> dict:
        contents = [types.Content(role="user", parts=[types.Part(text=render_item(item))])]
        config = types.GenerateContentConfig(
            system_instruction=self.system_prompt,
            tools=[types.Tool(function_declarations=TOOL_DECLARATIONS)],
            temperature=0.0,
        )
        tool_calls = []
        usage = {"prompt": 0, "output": 0, "total": 0, "billed_calls": 0}
        started = time.time()

        def record(response):
            """Accumulate what Vertex says it billed, not what we guess it sent.

            Cost here is dominated by re-sending the whole conversation each turn,
            so per-item spend grows with the square of the tool-call count rather
            than linearly. Estimating that from payload sizes is guesswork; the
            usage metadata is the invoice.
            """
            meta = getattr(response, "usage_metadata", None)
            if meta:
                usage["prompt"] += getattr(meta, "prompt_token_count", 0) or 0
                usage["output"] += getattr(meta, "candidates_token_count", 0) or 0
                # total exceeds prompt + candidates: reasoning tokens are billed
                # too and appear in neither of the other two counters.
                usage["total"] += getattr(meta, "total_token_count", 0) or 0
                usage["billed_calls"] += 1

        for turn in range(MAX_TOOL_TURNS):
            response = self.client.models.generate_content(
                model=MODEL, contents=contents, config=config
            )
            record(response)
            candidate = response.candidates[0]
            # A turn can come back with no parts at all (a safety stop, a token
            # limit, an empty thought). Appending it produces a Content with an
            # empty parts list, and the next request is rejected outright with
            # "must include at least one parts field", which reads like a bug in
            # the request rather than in the history.
            if not (candidate.content and candidate.content.parts):
                break
            contents.append(candidate.content)
            calls = [p.function_call for p in candidate.content.parts if p.function_call]
            if not calls:
                break
            parts = []
            for call in calls:
                args = dict(call.args or {})
                result = self.call_tool(call.name, args)
                tool_calls.append({"name": call.name, "args": args})
                parts.append(types.Part.from_function_response(name=call.name, response=result))
            contents.append(types.Content(role="user", parts=parts))

        # Running out of turns is not a reason to discard the research. The final
        # turn below asks for a conclusion either way; an item that genuinely
        # cannot be settled comes back as NEEDS_INPUT on its own merits rather
        # than because a counter ran out.
        exhausted = len(tool_calls) and turn == MAX_TOOL_TURNS - 1
        contents.append(types.Content(role="user", parts=[types.Part(
            text="Give your answer now, in the required JSON shape."
        )]))
        final = self.client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA,
                temperature=0.0,
            ),
        )
        record(final)
        try:
            answer = json.loads(final.text)
        except (ValueError, TypeError) as exc:
            return self._failure(item, f"unparseable answer: {exc}", tool_calls, started)

        # The floor is enforced here, not in the prompt: a model that reports 0.6
        # and classifies anyway must still be routed to a person.
        if answer.get("confidence", 0) < CONFIDENCE_FLOOR:
            answer["status"] = "NEEDS_INPUT"
            answer["selected_code"] = None
            answer["selected_code_8"] = None

        # The model returns codes both dotted and bare. Normalizing here rather
        # than asking the prompt for one form keeps a formatting slip from
        # reading as a wrong answer.
        for key in ("selected_code", "selected_code_8", "runner_up_code"):
            if answer.get(key):
                answer[key] = re.sub(r"\D", "", answer[key])
        if answer.get("selected_code") and not answer.get("selected_code_8"):
            answer["selected_code_8"] = answer["selected_code"][:8]
        if answer.get("selected_code_8"):
            answer["selected_code_8"] = answer["selected_code_8"][:8]

        answer["item_id"] = item.item_id
        answer["tool_budget_exhausted"] = bool(exhausted)
        answer["truth_hts8"] = item.truth_hts8
        answer["stratum"] = item.stratum
        answer["tool_calls"] = tool_calls
        answer["tool_call_count"] = len(tool_calls)
        answer["usage"] = usage
        answer["seconds"] = round(time.time() - started, 1)
        return answer

    @staticmethod
    def _failure(item: Item, reason: str, tool_calls: list, started: float) -> dict:
        return {
            "item_id": item.item_id, "status": "NEEDS_INPUT", "error": reason,
            "selected_code": None, "selected_code_8": None, "confidence": 0.0,
            "truth_hts8": item.truth_hts8, "stratum": item.stratum,
            "citations": [], "tool_calls": tool_calls, "tool_call_count": len(tool_calls),
            "seconds": round(time.time() - started, 1),
        }


def load_dev_items(path: Path, candidates: dict[str, list[dict]], limit: int | None,
                   seed: int = 20260817) -> list[Item]:
    """Load the development items, shuffled before any limit is applied.

    The file is ordered by ruling number, which correlates with date and so with
    stratum. Taking the first N would report an accuracy for whichever stratum
    happens to sit at the top of the file.
    """
    items = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("description_status") != "ok":
                continue
            items.append(Item(
                item_id=row["ruling_number"],
                description=row["description"],
                prior_hs6=row["prior_hs6"],
                candidates=candidates.get(row["prior_hs6"], []),
                truth_hts8=row["truth_hts8"],
                stratum=row["stratum"],
            ))
    random.Random(seed).shuffle(items)
    return items[:limit] if limit else items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--dev", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--exclude-ids", type=Path, default=None,
                        help="Ruling numbers kept out of the precedent index")
    args = parser.parse_args(argv)

    excluded = set()
    if args.exclude_ids:
        excluded = {line.strip() for line in args.exclude_ids.read_text().splitlines() if line.strip()}

    candidates = load_candidates(args.snapshot)
    items = load_dev_items(args.dev, candidates, args.limit)
    # A development item is its own answer key, so it has to leave the index too.
    runner = Runner(args.snapshot, excluded=excluded | {i.item_id for i in items})
    print(f"items={len(items)} precedent_index={len(runner.index.rulings)} "
          f"excluded={len(runner.index.excluded)}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    hits = 0
    with args.out.open("w", encoding="utf-8") as fh:
        for i, item in enumerate(items, 1):
            # One item that upsets the API must not cost the other fifty-nine.
            try:
                answer = runner.classify(item)
            except Exception as exc:  # noqa: BLE001
                answer = Runner._failure(item, f"{type(exc).__name__}: {exc}", [], time.time())
            fh.write(json.dumps(answer, ensure_ascii=False) + "\n")
            fh.flush()
            correct = answer.get("selected_code_8") == item.truth_hts8
            hits += correct
            print(f"{i:3}/{len(items)} {item.item_id} {item.stratum:12} "
                  f"{answer['status']:12} got={answer.get('selected_code_8')} "
                  f"want={item.truth_hts8} {'HIT' if correct else ''} "
                  f"conf={answer.get('confidence')} tools={answer.get('tool_call_count')} "
                  f"{answer.get('seconds')}s")
    print(f"\n8-digit hits: {hits}/{len(items)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
