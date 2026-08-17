"""Re-resolve every citation an answer rests on, against the same snapshot.

Why this is a program and not a second model
--------------------------------------------
On Vertex the Gemini Pro line stops at 3.1, below the 3.5 floor this project
targets, so "have a stronger model review it" is not an available design. What is
left is the part a language model cannot do by construction: take a claimed
reference and go and look. A citation either resolves in the snapshot or it does
not, and no amount of fluency changes the answer.

That makes the check cheap, deterministic, and impossible to talk out of. It also
bounds what it can prove: it establishes that a cited thing exists and that the
quoted words are really in it. It does not establish that the reasoning built on
top is sound. An answer that cites real notes and reasons badly still passes here,
which is why the confidence floor and the human sign-off both stay.

What fails a citation
---------------------
* a ruling number that is not in the corpus, or that was excluded from the index
* a tariff code with no row in the current schedule
* a chapter note pointing at a chapter with no notes, or a note number that
  chapter does not have
* a quote whose words are not in the source it is attributed to

The last one is the interesting case. A model that has read the note tends to
quote it; a model that is filling in a plausible-looking reference tends to
paraphrase, and a paraphrase does not survive a substring check.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from fleet.agents.tools import Snapshot, _digits

# "Note 2 to Chapter 84", "Note 5(b) to chapter 85", "U.S. Note 20 to Chapter 99",
# "Note 6(A) to Section XVI". Section notes are cited as often as chapter notes
# for machinery, because section XVI is what governs chapters 84 and 85.
NOTE_REF = re.compile(
    r"(?:additional\s+)?(?:u\.s\.\s+)?(?:statistical\s+|subheading\s+)?note\s+"
    r"(\d+)(?:\s*\([a-z0-9]+\))*\s+to\s+"
    r"(?:(?:chapter|ch\.?)\s*(\d{1,2})|section\s+([ivxl]+))",
    re.IGNORECASE,
)
# The numbered clause at the head of a note, e.g. a line beginning "2." or "2 ."
NOTE_NUMBER = r"^\s*{n}\s*[.)]"


@dataclass
class CitationResult:
    kind: str
    ref: str
    resolved: bool
    quote_found: bool | None      # None when the citation carried no quote
    detail: str


@dataclass
class VerificationResult:
    item_id: str
    passed: bool
    reason: str
    citations: list[CitationResult] = field(default_factory=list)

    @property
    def unresolved(self) -> list[CitationResult]:
        return [c for c in self.citations if not c.resolved]

    @property
    def misquoted(self) -> list[CitationResult]:
        return [c for c in self.citations if c.resolved and c.quote_found is False]


def normalize_words(text: str) -> str:
    """Collapse whitespace and flatten every quote mark to one character.

    PDF extraction breaks lines mid-sentence and the schedule uses typographic
    double quotes where a model tends to write straight single ones. Both are
    differences in how the same words were transcribed. Nothing else is
    normalized: dropping punctuation or case would start forgiving paraphrase.
    """
    text = re.sub(r"[\u201c\u201d\u2018\u2019\"']", "\u0022", text)
    return re.sub(r"\s+", " ", text).strip().lower()


# A fragment shorter than this carries too little to prove anything: "of other
# materials" appears all over the schedule.
MIN_FRAGMENT_WORDS = 5


def quote_fragments(quote: str) -> list[str]:
    """Split a quote where a quoter joins text the source keeps apart.

    A citation legitimately stitches a heading to its body, or one indent level to
    the next, with a colon or an ellipsis: `Copper alloys: Metallic substances
    other than unrefined copper ...`. The source has a paragraph break there, so
    the joined string appears nowhere in it while every piece appears verbatim.

    Requiring each substantial fragment to be present keeps the check honest.
    Paraphrase alters words inside a fragment, and an altered fragment is not
    found no matter where the splits fall.
    """
    parts = [p.strip() for p in re.split(r"[:;\u2026]|\.\.\.|\s\u2014\s", quote)]
    fragments = [p for p in parts if len(p.split()) >= MIN_FRAGMENT_WORDS]
    return fragments or [quote.strip()]


def quote_is_present(quote: str, source: str) -> bool:
    haystack = normalize_words(source)
    return all(normalize_words(f) in haystack for f in quote_fragments(quote))


class CitationVerifier:
    def __init__(self, snapshot_dir: Path | None = None, known_rulings: set[str] | None = None,
                 *, snapshot=None):
        self.snapshot = snapshot if snapshot is not None else Snapshot(snapshot_dir)
        if known_rulings is None:
            known_rulings = set()
            with (Path(snapshot_dir) / "cross.jsonl").open(encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        known_rulings.add(json.loads(line)["ruling_number"].upper())
        self.known_rulings = known_rulings
        self._codes = {
            _digits(row["htsno"]) for row in self.snapshot.hts if row.get("htsno")
        }

    def _check_ruling(self, ref: str, quote: str | None) -> CitationResult:
        number = ref.strip().upper()
        if number not in self.known_rulings:
            return CitationResult("ruling", ref, False, None,
                                  "no such ruling in the corpus")
        # The corpus carries subjects, not full text, so a quote attributed to a
        # ruling cannot be checked here. Saying so beats implying it passed.
        return CitationResult("ruling", ref, True, None,
                              "ruling exists; quote not checkable from the index")

    def _check_tariff_line(self, ref: str, quote: str | None) -> CitationResult:
        code = _digits(ref)
        if not code:
            return CitationResult("tariff_line", ref, False, None, "no digits in reference")
        if code in self._codes:
            detail = "exact row"
        elif any(c.startswith(code) for c in self._codes):
            detail = "prefix of existing rows"
        else:
            return CitationResult("tariff_line", ref, False, None,
                                  "no row in the current schedule")
        if not quote:
            return CitationResult("tariff_line", ref, True, None, detail)
        for text in self._description_paths(code):
            if quote_is_present(quote, text):
                return CitationResult("tariff_line", ref, True, True, detail)
        return CitationResult("tariff_line", ref, True, False,
                              "quote is not the description of that line")

    def _description_paths(self, code: str) -> list[str]:
        """Every full description a line under `code` could legitimately be quoted as.

        A tariff line's legal description is the chain of its ancestors' text plus
        its own, which is how CBP writes them in a ruling. The leaf row on its own
        usually reads `Other`, so comparing against that alone rejects the only
        form a customs professional would recognise.
        """
        rows = self.snapshot.hts
        paths = []
        for i, row in enumerate(rows):
            if not _digits(row.get("htsno")).startswith(code):
                continue
            chain = [(row.get("description") or "").strip()]
            ceiling = int(row.get("indent") or 0)
            for j in range(i - 1, -1, -1):
                indent = int(rows[j].get("indent") or 0)
                if indent >= ceiling:
                    continue
                ceiling = indent
                chain.append((rows[j].get("description") or "").strip())
                if ceiling == 0:
                    break
            paths.append(" ".join(reversed(chain)))
        return paths

    def _check_chapter_note(self, ref: str, quote: str | None) -> CitationResult:
        match = NOTE_REF.search(ref)
        if not match:
            return CitationResult("chapter_note", ref, False, None,
                                  "reference does not name a note and a chapter or section")
        number, chapter, section = match.group(1), match.group(2), match.group(3)

        if section:
            where = f"section {section.upper()}"
            notes = self._section_notes().get(section.upper())
        else:
            where = f"chapter {chapter.zfill(2)}"
            notes = self.snapshot.notes.get(chapter.zfill(2))

        if not notes:
            return CitationResult("chapter_note", ref, False, None,
                                  f"{where} carries no notes")
        if not re.search(NOTE_NUMBER.format(n=re.escape(number)), notes, re.MULTILINE):
            return CitationResult("chapter_note", ref, False, None,
                                  f"{where} has no note {number}")
        if not quote:
            return CitationResult("chapter_note", ref, True, None, "note exists")
        if quote_is_present(quote, notes):
            return CitationResult("chapter_note", ref, True, True, f"quote found in {where}")
        return CitationResult("chapter_note", ref, True, False,
                              f"quote is not in {where}'s notes")

    def _section_notes(self) -> dict[str, str]:
        return getattr(self.snapshot, "section_notes", {})

    def check(self, answer: dict) -> VerificationResult:
        item_id = answer.get("item_id", "?")

        if answer.get("status") == "NEEDS_INPUT":
            # Refusing is a designed outcome, not a claim, so there is nothing to
            # resolve. What it must not do is refuse and ship a code anyway.
            if answer.get("selected_code_8"):
                return VerificationResult(item_id, False,
                                          "NEEDS_INPUT but a code was still produced")
            if not answer.get("missing_property"):
                return VerificationResult(item_id, False,
                                          "NEEDS_INPUT without naming what is missing")
            return VerificationResult(item_id, True, "refused, nothing to verify")

        code = answer.get("selected_code_8")
        if not code:
            return VerificationResult(item_id, False, "CLASSIFIED without a code")
        if not any(c.startswith(code) for c in self._codes):
            return VerificationResult(item_id, False,
                                      f"selected code {code} is not in the schedule")

        results = [
            self._dispatch(c.get("kind", ""), c.get("ref", ""), c.get("quote"))
            for c in (answer.get("citations") or [])
        ]
        verdict = VerificationResult(item_id, True, "ok", results)

        if not results:
            verdict.passed, verdict.reason = False, "classified with no citations"
        elif verdict.unresolved:
            verdict.passed = False
            verdict.reason = (f"{len(verdict.unresolved)} citation(s) do not resolve: "
                              + "; ".join(f"{c.ref} ({c.detail})" for c in verdict.unresolved))
        elif verdict.misquoted:
            verdict.passed = False
            verdict.reason = (f"{len(verdict.misquoted)} quote(s) not found in the cited source: "
                              + "; ".join(c.ref for c in verdict.misquoted))
        return verdict

    def _dispatch(self, kind: str, ref: str, quote: str | None) -> CitationResult:
        if kind == "ruling":
            return self._check_ruling(ref, quote)
        if kind == "tariff_line":
            return self._check_tariff_line(ref, quote)
        if kind == "chapter_note":
            return self._check_chapter_note(ref, quote)
        return CitationResult(kind, ref, False, None, f"unknown citation kind {kind!r}")
