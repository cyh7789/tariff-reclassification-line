"""Tools the classifier agent calls. Every one reads the frozen snapshot.

Two properties matter more than convenience here.

**Nothing is invented.** Each tool returns rows that exist in the snapshot, and the
verifier later re-resolves every citation against the same files. A tool that
guessed, padded, or paraphrased would produce citations that resolve and claims
that are false, which is worse than an empty result.

**The precedent index is filtered before the agent sees it.** The evaluation set is
drawn from the same ruling corpus the agent searches, so an unfiltered index lets
it retrieve the answer key and score itself. `PrecedentIndex` takes the excluded
ruling numbers at construction and there is no code path that reaches around it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

TOKEN = re.compile(r"[a-z0-9]+")

# Words that appear in most ruling subjects and separate nothing.
STOPWORDS = frozenset("""
a an the of and or for from to in on with without by classification tariff ruling
country origin request applicable subheading merchandise goods article articles
united states its their this that these those is are was were be been
""".split())


def tokenize(text: str) -> set[str]:
    return {t for t in TOKEN.findall((text or "").lower()) if t not in STOPWORDS and len(t) > 2}


def _digits(code: str | None) -> str:
    return re.sub(r"\D", "", code or "")


@dataclass(frozen=True)
class TariffLine:
    code: str
    indent: int
    description: str
    general: str | None
    special: str | None
    other: str | None
    footnotes: tuple[str, ...]
    #: An interior row of the schedule that carries no code of its own. It states
    #: what the coded lines beneath it are, and it cannot be cited as an answer.
    is_heading: bool = False


class Snapshot:
    """Lazy reader over one snapshot directory."""

    def __init__(self, snapshot_dir: Path):
        self.dir = Path(snapshot_dir)
        self._hts: list[dict] | None = None
        self._notes: dict[str, str] | None = None
        self._section_notes: dict[str, str] | None = None
        self._chapter_sections: dict[str, str] | None = None

    @property
    def hts(self) -> list[dict]:
        if self._hts is None:
            with (self.dir / "hts.jsonl").open(encoding="utf-8") as fh:
                self._hts = [json.loads(line) for line in fh if line.strip()]
        return self._hts

    def _load_notes(self) -> None:
        self._notes, self._section_notes, self._chapter_sections = {}, {}, {}
        with (self.dir / "notes.jsonl").open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                self._notes[row["chapter"]] = row["notes"]
                section = row.get("section")
                if section:
                    self._chapter_sections[row["chapter"]] = section
                    # Only the opening chapter of a section carries its notes.
                    if row.get("section_notes"):
                        self._section_notes[section] = row["section_notes"]

    @property
    def notes(self) -> dict[str, str]:
        if self._notes is None:
            self._load_notes()
        return self._notes

    @property
    def section_notes(self) -> dict[str, str]:
        if self._section_notes is None:
            self._load_notes()
        return self._section_notes

    @property
    def chapter_sections(self) -> dict[str, str]:
        if self._chapter_sections is None:
            self._load_notes()
        return self._chapter_sections


def get_chapter_notes(snapshot: Snapshot, chapter: str) -> str:
    """Legal notes for one chapter, preceded by its section's notes.

    A section note binds every chapter under it, and section XVI (chapters 84 and
    85) decides a large share of machinery questions on its own. Returning the
    chapter alone would make the agent argue from half the law.
    """
    key = _digits(chapter)[:2].zfill(2)
    notes = snapshot.notes.get(key)
    if notes is None:
        return f"No chapter {key} in this snapshot."

    section = snapshot.chapter_sections.get(key)
    section_notes = snapshot.section_notes.get(section, "") if section else ""

    parts = []
    if section_notes:
        parts.append(f"NOTES TO SECTION {section} (these bind chapter {key} as well)\n\n"
                     f"{section_notes}")
    parts.append(f"NOTES TO CHAPTER {key}\n\n{notes}" if notes
                 else f"Chapter {key} carries no legal notes of its own.")
    return "\n\n".join(parts)


def _to_line(row: dict) -> TariffLine:
    code = _digits(row.get("htsno"))
    return TariffLine(
        code=code,
        indent=int(row.get("indent") or 0),
        description=(row.get("description") or "").strip(),
        general=(row.get("general") or "").strip() or None,
        special=(row.get("special") or "").strip() or None,
        other=(row.get("other") or "").strip() or None,
        footnotes=tuple(
            (f.get("value") or "").strip()
            for f in (row.get("footnotes") or [])
            if (f.get("value") or "").strip()
        ),
        is_heading=not code,
    )


def get_tariff_lines(snapshot, prefix: str, limit: int = 120) -> list[TariffLine]:
    """The subtree under a 4-, 6- or 8-digit prefix, preceded by its ancestors.

    Roughly a third of the schedule's interior nodes carry no code: `842441
    Portable sprayers` sits under an uncoded `Agricultural or horticultural
    sprayers:`. Returning only coded rows leaves the two lines under a heading
    looking like a free-standing pair, and the choice between them then gets made
    without the qualifier that governs both.

    Ancestors come first and are flagged `is_heading` when they carry no code, so
    they can inform the reasoning without being mistaken for a citable answer.
    """
    rows = snapshot.hts
    want = _digits(prefix)
    if len(want) < 4:
        raise ValueError("prefix must be at least 4 digits")

    first = next(
        (i for i, row in enumerate(rows) if _digits(row.get("htsno")).startswith(want)),
        None,
    )
    if first is None:
        return []

    ancestors = []
    ceiling = int(rows[first].get("indent") or 0)
    for i in range(first - 1, -1, -1):
        indent = int(rows[i].get("indent") or 0)
        if indent >= ceiling:
            continue
        ceiling = indent
        ancestors.append(_to_line(rows[i]))
        if ceiling == 0:
            break
    ancestors.reverse()

    subtree = []
    for row in rows[first:]:
        code = _digits(row.get("htsno"))
        if code and not code.startswith(want):
            break
        if not code and subtree and int(row.get("indent") or 0) <= int(rows[first].get("indent") or 0):
            break
        subtree.append(_to_line(row))
        if len(subtree) >= limit:
            break

    return ancestors + subtree


@dataclass(frozen=True)
class Precedent:
    ruling_number: str
    ruling_date: str
    subject: str
    tariffs: tuple[str, ...]
    url: str
    score: float


class PrecedentIndex:
    """Ruling search over the snapshot, with the evaluation set removed.

    `excluded` is the frozen evaluation ruling numbers; their `related_rulings` are
    removed too, because a related ruling on the same merchandise leaks the answer
    just as directly as the ruling itself.
    """

    def __init__(self, snapshot_dir: Path, excluded: set[str] | None = None):
        excluded = {r.upper() for r in (excluded or set())}
        self.rulings: list[dict] = []
        related_of_excluded: set[str] = set()

        with (Path(snapshot_dir) / "cross.jsonl").open(encoding="utf-8") as fh:
            raw = [json.loads(line) for line in fh if line.strip()]

        for row in raw:
            if row["ruling_number"].upper() in excluded:
                related_of_excluded.update(r.upper() for r in (row.get("related_rulings") or []))

        self.excluded = excluded | related_of_excluded
        for row in raw:
            if row["ruling_number"].upper() in self.excluded:
                continue
            if not row.get("tariffs"):
                continue  # nothing to cite a classification against
            row["_tokens"] = tokenize(row.get("subject"))
            self.rulings.append(row)

    def search(self, query: str, tariff_prefix: str | None = None,
               since: str | None = None, limit: int = 8) -> list[Precedent]:
        """Rulings matching keywords, or everything filed under a tariff prefix.

        A prefix is a question on its own: what has this heading been used for?
        Answering it requires no keyword, and a keyword that happens to match no
        title must not turn the answer into silence. Heading 0309 is the case that
        forced this: its five rulings are titled after the species (whitefish,
        cod, shrimp), so `0309` plus `crustaceans` matched nothing and the agent
        was left to reason from the schedule text alone.

        With both, the prefix selects and the keyword ranks. With neither a prefix
        nor a usable keyword there is nothing to answer.
        """
        terms = tokenize(query)
        prefix = _digits(tariff_prefix) if tariff_prefix else None
        if not terms and not prefix:
            return []

        hits: list[Precedent] = []
        for row in self.rulings:
            if since and (row.get("ruling_date") or "") < since:
                continue
            codes = tuple(_digits(t) for t in row["tariffs"])
            if prefix and not any(c.startswith(prefix) for c in codes):
                continue
            overlap = terms & row["_tokens"]
            if not overlap and not prefix:
                continue
            # Favour rulings matching more distinct terms, then a tighter subject:
            # a short title matching three terms is about those goods, a long one
            # matching three may merely mention them.
            score = len(overlap) + len(overlap) / (1 + len(row["_tokens"]))
            hits.append(Precedent(
                ruling_number=row["ruling_number"],
                ruling_date=row.get("ruling_date") or "",
                subject=row.get("subject") or "",
                tariffs=codes,
                url=row.get("url") or "",
                score=round(score, 3),
            ))
        hits.sort(key=lambda p: (-p.score, p.ruling_date < "2022", p.ruling_number))
        return hits[:limit]
