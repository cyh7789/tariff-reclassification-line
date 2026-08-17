"""The two reference points every accuracy number is read against.

Neither calls a model. Both are properties of the correlation table and the
schedule, so they can be computed before a single classification runs, and they
do not move when the prompt does.

**Deterministic lower bound.** What the table alone gets you: a surviving code is
carried forward, a dead code takes the table's first candidate. This is not "what
the industry does" and must never be described that way in the write-up. A customs
professional uses reference tools and their own judgment; nobody takes candidate
one on faith. Calling the floor "current practice" invites one question that
collapses the whole comparison. It is the floor of the mechanical path, nothing
more.

**Correlation upper bound.** The share of items whose true answer is somewhere in
the candidate set. This is the ceiling on any method that only reads the table,
and it equals the expected score of guessing uniformly among the candidates only
when the set has one member. Reported both ways below: containment, and the
expected value of a uniform guess.

The gap between the agent and the upper bound is the part that judgment buys. The
gap between the upper bound and 100% is what the table cannot reach at all.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from fleet.agents.tools import _digits


@dataclass(frozen=True)
class BaselineRow:
    stratum: str
    n: int
    lower_bound_hits: int
    carry_forward_hits: int
    contained_in_candidates: int
    uniform_guess_expectation: float

    @property
    def lower_bound(self) -> float:
        return self.lower_bound_hits / self.n if self.n else 0.0

    @property
    def carry_forward(self) -> float:
        return self.carry_forward_hits / self.n if self.n else 0.0

    @property
    def upper_bound(self) -> float:
        return self.contained_in_candidates / self.n if self.n else 0.0


def load_correlation(snapshot_dir: Path) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    with (Path(snapshot_dir) / "correlation.csv").open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            grouped[row["hs2017"]].append(row)
    return grouped


def load_current_hts6(snapshot_dir: Path) -> set[str]:
    codes = set()
    with (Path(snapshot_dir) / "hts.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            code = _digits(json.loads(line).get("htsno"))
            if len(code) >= 6:
                codes.add(code[:6])
    return codes


def score_item(item: dict, correlation: dict[str, list[dict]],
               current_hs6: set[str]) -> tuple[bool, bool, bool, float]:
    """Return (first-candidate hit, carry-forward hit, containment, uniform expectation).

    Comparison is at HS6, not HS8. The correlation table has no opinion below six
    digits, so scoring the mechanical path at eight would charge it for a decision
    it was never able to make, and would flatter the agent by the same amount.
    """
    truth6 = item["truth_hts8"][:6]
    prior = item["prior_hs6"]
    rows = correlation.get(prior, [])
    candidates = [r["hs2022"] for r in rows]

    if prior in current_hs6 and prior not in candidates:
        candidates = [prior] + candidates

    # Carry-forward is the stronger floor and the fairer comparison: when the code
    # still exists, a mechanical path keeps it and only looks the table up when it
    # is gone. Scoring the agent against first-candidate alone would beat a floor
    # nobody would actually use.
    carry_hit = (prior == truth6) if prior in current_hs6 else (
        bool(candidates) and candidates[0] == truth6)

    if not candidates:
        return prior == truth6, carry_hit, False, 0.0

    first_hit = candidates[0] == truth6
    contained = truth6 in candidates
    expectation = (1.0 / len(candidates)) if contained else 0.0
    return first_hit, carry_hit, contained, expectation


def compute(items: list[dict], snapshot_dir: Path) -> list[BaselineRow]:
    correlation = load_correlation(snapshot_dir)
    current_hs6 = load_current_hts6(snapshot_dir)

    buckets: dict[str, list[tuple[bool, bool, bool, float]]] = defaultdict(list)
    for item in items:
        buckets[item["stratum"]].append(score_item(item, correlation, current_hs6))
        buckets["ALL"].append(buckets[item["stratum"]][-1])

    rows = []
    for stratum, scored in buckets.items():
        rows.append(BaselineRow(
            stratum=stratum,
            n=len(scored),
            lower_bound_hits=sum(1 for first, _, _, _ in scored if first),
            carry_forward_hits=sum(1 for _, carry, _, _ in scored if carry),
            contained_in_candidates=sum(1 for _, _, contained, _ in scored if contained),
            uniform_guess_expectation=sum(exp for _, _, _, exp in scored),
        ))
    rows.sort(key=lambda r: (r.stratum != "ALL", r.stratum))
    return rows


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--items", required=True, type=Path,
                        help="dev.jsonl or eval.jsonl")
    args = parser.parse_args(argv)

    items = []
    with args.items.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                if row.get("description_status") == "ok":
                    items.append(row)

    print(f"items={len(items)}  (HS6 comparison; the table says nothing below 6 digits)\n")
    header = (f"{'stratum':14}{'n':>5}{'first candidate':>17}{'carry forward':>16}"
              f"{'uniform guess':>16}{'in candidates':>16}")
    print(header)
    print("-" * len(header))
    for row in compute(items, args.snapshot):
        print(f"{row.stratum:14}{row.n:>5}"
              f"{row.lower_bound_hits:>9} {row.lower_bound*100:>5.1f}%"
              f"{row.carry_forward_hits:>9} {row.carry_forward*100:>5.1f}%"
              f"{row.uniform_guess_expectation:>10.1f} {row.uniform_guess_expectation/row.n*100:>4.1f}%"
              f"{row.contained_in_candidates:>9} {row.upper_bound*100:>5.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
