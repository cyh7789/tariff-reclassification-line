"""Score a classification run, at both digit levels, against both floors.

Reporting one digit level is enough to mislead in either direction. At six digits
a surviving code carries itself and the agent looks redundant; at eight the table
cannot answer at all and the agent looks unbeatable. Both are true, so both are
printed, side by side with the mechanical floors from `baselines.py`.

The three gates from the spec are computed here rather than asserted in prose:

* **escalation rate**, capped at 10%. Refusing is designed behaviour and does not
  count as intervention, but with no cap on it an agent can push every hard item
  to a person and report a beautiful autonomy number.
* **citation pass rate**, from the deterministic verifier. Items that fail do not
  ship, so the shipped set's citation pass rate is 100% by construction; the
  number worth reporting is how many were caught.
* **accuracy on what shipped**, which is the only accuracy a person would ever
  experience, and is not the same as accuracy over everything attempted.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from fleet.eval import baselines
from fleet.verify.citations import CitationVerifier


@dataclass
class StratumScore:
    stratum: str
    n: int = 0
    classified: int = 0
    refused: int = 0
    errored: int = 0
    hit8: int = 0
    hit6: int = 0
    shipped: int = 0
    shipped_hit8: int = 0
    citation_failures: int = 0

    def pct(self, num: int, den: int | None = None) -> str:
        den = self.n if den is None else den
        return f"{num / den * 100:5.1f}%" if den else "    . "


def score(run_path: Path, snapshot_dir: Path) -> tuple[dict[str, StratumScore], list[dict]]:
    verifier = CitationVerifier(snapshot_dir)
    scores: dict[str, StratumScore] = defaultdict(lambda: StratumScore("?"))
    failures = []

    with run_path.open(encoding="utf-8") as fh:
        answers = [json.loads(line) for line in fh if line.strip()]

    for answer in answers:
        for key in (answer.get("stratum") or "UNKNOWN", "ALL"):
            row = scores[key]
            row.stratum = key
            row.n += 1
            if answer.get("error"):
                row.errored += 1
                continue
            if answer.get("status") == "NEEDS_INPUT":
                row.refused += 1
                continue

            row.classified += 1
            got8 = answer.get("selected_code_8") or ""
            truth8 = answer.get("truth_hts8") or ""
            hit8 = got8 == truth8
            hit6 = got8[:6] == truth8[:6] and bool(got8)
            row.hit8 += hit8
            row.hit6 += hit6

            verdict = verifier.check(answer)
            if verdict.passed:
                row.shipped += 1
                row.shipped_hit8 += hit8
            else:
                row.citation_failures += 1
                if key == "ALL":
                    failures.append({"item_id": answer.get("item_id"),
                                     "reason": verdict.reason})
    return scores, failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--items", type=Path,
                        help="dev.jsonl / eval.jsonl, to print the mechanical floors alongside")
    args = parser.parse_args(argv)

    scores, failures = score(args.run, args.snapshot)

    header = (f"{'stratum':14}{'n':>4}{'8-digit':>15}{'6-digit':>15}"
              f"{'refused':>13}{'shipped':>13}{'cite fail':>11}")
    print(header)
    print("-" * len(header))
    for key in sorted(scores, key=lambda k: (k != "ALL", k)):
        row = scores[key]
        print(f"{row.stratum:14}{row.n:>4}"
              f"{row.hit8:>8} {row.pct(row.hit8)}"
              f"{row.hit6:>8} {row.pct(row.hit6)}"
              f"{row.refused:>7} {row.pct(row.refused)}"
              f"{row.shipped:>7} {row.pct(row.shipped)}"
              f"{row.citation_failures:>10}")

    overall = scores.get("ALL")
    if overall and overall.n:
        escalation = overall.refused / overall.n
        verdict = "within the 10% cap" if escalation <= 0.10 else "OVER the 10% cap"
        print(f"\nescalation rate {escalation*100:.1f}% ({verdict})")
        if overall.shipped:
            print(f"accuracy on what shipped: {overall.shipped_hit8}/{overall.shipped} "
                  f"= {overall.shipped_hit8/overall.shipped*100:.1f}% at 8 digits")
        if overall.errored:
            print(f"⚠ {overall.errored} item(s) errored and are counted in n")

    if failures:
        print(f"\ncitations that did not resolve ({len(failures)}):")
        for failure in failures[:12]:
            print(f"  {failure['item_id']}: {failure['reason'][:120]}")

    if args.items:
        print("\nmechanical floors on the same population (HS6):")
        items = []
        with args.items.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    row = json.loads(line)
                    if row.get("description_status") == "ok":
                        items.append(row)
        scored_ids = {a for a in scores if a != "ALL"}
        del scored_ids  # strata only; the floors are computed over the whole set
        for row in baselines.compute(items, args.snapshot):
            print(f"  {row.stratum:14}n={row.n:<5} carry forward {row.carry_forward*100:5.1f}%"
                  f"   first candidate {row.lower_bound*100:5.1f}%"
                  f"   ceiling {row.upper_bound*100:5.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
