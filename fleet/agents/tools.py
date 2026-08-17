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


class Snapshot:
    """Lazy reader over one snapshot directory."""

    def __init__(self, snapshot_dir: Path):
        self.dir = Path(snapshot_dir)
        self._hts: list[dict] | None = None
        self._notes: dict[str, str] | None = None

    @property
    def hts(self) -> list[dict]:
        if self._hts is None:
            with (self.dir / "hts.jsonl").open(encoding="utf-8") as fh:
                self._hts = [json.loads(line) for line in fh if line.strip()]
        return self._hts

    @property
    def notes(self) -> dict[str, str]:
        if self._notes is None:
            self._notes = {}
            with (self.dir / "notes.jsonl").open(encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        row = json.loads(line)
                        self._notes[row["chapter"]] = row["notes"]
        return self._notes


def get_chapter_notes(snapshot: Snapshot, chapter: str) -> str:
    """Legal notes for one chapter, given as 2 digits ("85") or any longer code."""
    key = _digits(chapter)[:2].zfill(2)
    notes = snapshot.notes.get(key)
    if notes is None:
        return f"No chapter {key} in this snapshot."
    if not notes:
        return f"Chapter {key} carries no legal notes."
    return notes


def get_tariff_lines(snapshot: Snapshot, prefix: str, limit: int = 120) -> list[TariffLine]:
    """Every tariff line under a 4-, 6- or 8-digit prefix, in schedule order.

    Header rows carry no code of their own; they are skipped rather than returned,
    because a citation has to name something the verifier can resolve.
    """
    want = _digits(prefix)
    if len(want) < 4:
        raise ValueError("prefix must be at least 4 digits")
    lines = []
    for row in snapshot.hts:
        code = _digits(row.get("htsno"))
        if not code or not code.startswith(want):
            continue
        lines.append(TariffLine(
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
        ))
        if len(lines) >= limit:
            break
    return lines


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
        terms = tokenize(query)
        if not terms:
            return []
        prefix = _digits(tariff_prefix) if tariff_prefix else None
        hits: list[Precedent] = []
        for row in self.rulings:
            if since and (row.get("ruling_date") or "") < since:
                continue
            codes = tuple(_digits(t) for t in row["tariffs"])
            if prefix and not any(c.startswith(prefix) for c in codes):
                continue
            overlap = terms & row["_tokens"]
            if not overlap:
                continue
            # Favour rulings that match on more distinct terms, then on a tighter
            # subject: a short subject matching three terms is about those goods,
            # a long one matching three terms may merely mention them.
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
