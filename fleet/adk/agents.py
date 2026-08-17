"""The two specialists, as ADK agents, so they can run on the Agent Platform.

Two agents, because they answer different questions from different evidence and
fail in different ways. A third that only orchestrated would be a model doing set
arithmetic, which is slower, dearer and worse than the code already doing it.

They run in sequence and do not talk back, and that is deliberate rather than
unfinished. The compliance pass knows things the classifier does not: in 408
six-digit subheadings some eight-digit lines carry a chapter 99 footnote and
their siblings do not, so the classification decides whether the Section 301
add-on is owed. Letting that flow backwards would let the tax result choose the
legal answer. The exposure raises the review priority instead, and the classifier
is never shown a rate, a chapter 99 reference or a finding, which is a property
of what render_item builds rather than a rule anybody has to remember.

So the accurate description is an orchestrated two-agent workflow with
deterministic control gates, not a fleet of agents negotiating an answer.

    classifier  which current 8-digit code do these goods belong to
    compliance  given that code, what else is owed and who must be checked

The tools are the same plain functions the rest of the system uses; ADK takes
callables directly, so nothing about them changes to run here. What changes is
that the run emits events, and an event stream is exactly the record this project
kept trying to reconstruct by hand: every tool call, every argument, every result,
in order, with no extra instrumentation to drift out of date.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from google.adk.agents import LlmAgent

from fleet.agents import tools as T
from fleet.agents.tools import PrecedentIndex, Snapshot

MODEL = "gemini-3.7-flash"
PROMPTS = Path(__file__).parent.parent / "agents" / "prompts"


def _section(path: Path, heading: str, until: str) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index(heading) + len(heading)
    return text[start:text.index(until, start)].strip()


def classifier_instruction() -> str:
    return _section(PROMPTS / "classifier.md", "## System prompt", "\n## Tools")


COMPLIANCE_INSTRUCTION = """
You work out what an import owes and who has to be looked at, once its tariff code
is settled. Somebody else chose the code; that decision is not yours to revisit.

Two questions, and they are not the same kind of question.

**What else is owed.** A tariff line can carry a footnote pointing into chapter 99.
For goods of the wrong origin that add-on is larger than the base rate, so a duty
figure that omits it is wrong rather than incomplete. Look up the line, read its
footnotes, and say plainly whether an additional duty applies to goods of this
origin and under which subheading. This part has a right answer; find it.

**Who has to be looked at.** A supplier name may resemble a party on a screening
list. Resemblance is not identity: companies share names, transliterations vary,
and a screening list holds tens of thousands of entries. You do not decide this.
What you do is brief the person who will: state what matched, what differs, what
would settle it, and how confident you are that the two names denote one party.
A brief that says "probably the same, because the address in the listing matches
the one in the request" is worth having. A verdict is not yours to give.

Say when you found nothing. "No additional duty applies and no party resembles a
listed one" is a finding, and an officer who cannot tell the difference between
"checked, clear" and "not checked" cannot sign anything.

Cite what you relied on: the tariff line for a footnote, the screening entry for a
match. Every citation is re-resolved by a program afterwards, so quote only what
you actually read.
""".strip()


def build_tools(snapshot_dir: Path, excluded: set[str] | None = None):
    """Bind the tools to a snapshot, keeping the model-facing signatures clean.

    ADK derives a tool's schema from its signature, so the snapshot has to be
    closed over rather than passed as an argument. That is also the right shape:
    which snapshot to read is not the model's decision.
    """
    snapshot = Snapshot(snapshot_dir)
    index = PrecedentIndex(snapshot_dir, excluded=excluded)

    def get_chapter_notes(chapter: str) -> str:
        """Legal notes of one HTS chapter, preceded by the notes of its section.

        Args:
            chapter: Two digits, for example "85".
        """
        return T.get_chapter_notes(snapshot, chapter)

    def get_tariff_lines(prefix: str) -> str:
        """Every tariff line under a 4- to 8-digit prefix, with its ancestors.

        Args:
            prefix: 4 to 8 digits, no dots.
        """
        lines = T.get_tariff_lines(snapshot, prefix)
        return json.dumps([{
            "code": line.code, "indent": line.indent, "heading": line.is_heading,
            "description": line.description, "general": line.general,
            "footnotes": list(line.footnotes),
        } for line in lines], ensure_ascii=False)

    def search_precedents(query: str = "", tariff_prefix: str = "",
                          since: str = "") -> str:
        """Find prior CBP rulings by keywords, by tariff prefix, or by both.

        A prefix on its own answers "what has actually been classified here",
        which is often the only way to see a practice the schedule text does not
        imply.

        Args:
            query: Merchandise keywords. May be empty if a prefix is given.
            tariff_prefix: 4 to 8 digits. May be empty if keywords are given.
            since: Optional earliest ruling date, as YYYY-MM-DD.
        """
        hits = index.search(query, tariff_prefix=tariff_prefix or None,
                            since=since or None)
        return json.dumps([{
            "ruling": h.ruling_number, "date": h.ruling_date, "subject": h.subject,
            "tariffs": list(h.tariffs),
        } for h in hits], ensure_ascii=False)

    def get_ruling(ruling_number: str) -> str:
        """What the goods in a prior ruling actually were.

        Args:
            ruling_number: For example "N337247" or "NY N337247".
        """
        return T.get_ruling(snapshot, index, ruling_number)

    def screening_list_lookup(name: str) -> str:
        """Entries on the consolidated screening list resembling a party name.

        Returns candidates, not verdicts: the question of whether two names denote
        one party is settled by a person.

        Args:
            name: The supplier or consignee name as it appears on the request.
        """
        return json.dumps(T.screening_candidates(snapshot, name), ensure_ascii=False)

    return {
        "classifier": [get_chapter_notes, get_tariff_lines, search_precedents, get_ruling],
        "compliance": [get_tariff_lines, screening_list_lookup, get_ruling],
    }


def build_fleet(snapshot_dir: Path, excluded: set[str] | None = None
                ) -> dict[str, LlmAgent]:
    bound = build_tools(snapshot_dir, excluded)
    return {
        "classifier": LlmAgent(
            name="tariff_classifier",
            model=MODEL,
            description="Chooses the current 8-digit tariff code for goods whose "
                        "filed code was affected by a nomenclature revision, and "
                        "cites the notes and rulings it relied on.",
            instruction=classifier_instruction(),
            tools=bound["classifier"],
        ),
        "compliance": LlmAgent(
            name="import_compliance",
            model=MODEL,
            description="Given a settled tariff code, determines any additional "
                        "duty owed and briefs a person on any party that resembles "
                        "one on a screening list.",
            instruction=COMPLIANCE_INSTRUCTION,
            tools=bound["compliance"],
        ),
    }
