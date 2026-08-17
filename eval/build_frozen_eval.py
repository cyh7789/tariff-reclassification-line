#!/usr/bin/env python3
"""Draw the frozen evaluation set from a pool that is already known to be usable.

Why this replaces the eval half of build_sets.py
------------------------------------------------
The first draw took 500 rulings and then discovered that 30 of them (6.0%) carry
no extractable merchandise description. Dropping those afterwards means changing
the denominator once the answers are visible, which `SPEC.md:279` forbids and
which a reviewer is right to distrust.

Here the whole 2022+ pool is fetched first (`fetch_pool.py`), eligibility is
decided against the cached text, and only then is the sample drawn. The frozen
500 is 500 usable items, and nothing is removed after the fact.

What the pre-filter costs, stated rather than discovered
--------------------------------------------------------
Extraction keys off the NY-letter template: a salutation, then "The applicable
subheading". HQ rulings and revocation notices do not follow it. Filtering first
therefore narrows the population to the ruling formats the extractor handles, and
the write-up says so. The alternative, a wider extractor, is a bigger change than
the evaluation needs and would move the population again.

Disjointness from the development set
-------------------------------------
The dev set was drawn first by `build_sets.py` and its ruling numbers are read
from `dev_ids.txt` and excluded here. The check is mechanical and the script
refuses to write anything if it fails.

Outputs: eval_ids.txt, eval.jsonl, EVAL_SAMPLING.json, build_eval.log
"""
import collections
import csv
import json
import pathlib
import random
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
FRAME = HERE.parent / "holdout" / "cross_frame.jsonl"
CORRELATION = HERE.parent / "correlation" / "hs2017_hs2022.csv"
POOL_TEXT = HERE / "pool_text.jsonl"
DEV_IDS = HERE / "dev_ids.txt"

SEED = 20260817
EVAL_N = 500

DIGITS = re.compile(r"\D")
DEAR_RE = re.compile(r"Dear\s+[^\n\r]{0,120}?:", re.IGNORECASE)
SUBHEADING_RE = re.compile(r"The applicable subheading", re.IGNORECASE)


def normalize(code):
    return DIGITS.sub("", code or "")


def parse_description(text):
    """Return (description, status). Identical to the dev-set extractor."""
    if not text:
        return None, "no_text"
    flat = text.replace("\r\n", "\n").replace("\r", "\n")
    m_dear = DEAR_RE.search(flat)
    m_sub = SUBHEADING_RE.search(flat)
    if not m_dear and not m_sub:
        return None, "no_dear_no_subheading"
    if not m_dear:
        return None, "no_dear_salutation"
    if not m_sub:
        return None, "no_applicable_subheading"
    if m_sub.start() <= m_dear.end():
        return None, "subheading_before_salutation"
    body = flat[m_dear.end():m_sub.start()]
    body = re.sub(r"[ \t]+", " ", body)
    body = "\n".join(line.strip() for line in body.split("\n"))
    body = re.sub(r"\n{2,}", "\n\n", body).strip()
    if len(body) < 40:
        return None, "body_too_short"
    return body, "ok"


def load_correlation():
    forward = collections.defaultdict(set)
    reverse = collections.defaultdict(set)
    has_ex = collections.defaultdict(bool)
    for row in csv.DictReader(CORRELATION.open()):
        forward[row["hs2017"]].add(row["hs2022"])
        reverse[row["hs2022"]].add(row["hs2017"])
        if row["is_ex"] == "1":
            has_ex[row["hs2017"]] = True
    return forward, reverse, has_ex


def classify(hs6, forward, reverse, has_ex, rng):
    if hs6 in forward:
        candidates = forward[hs6]
        if len(candidates) == 1 and not has_ex[hs6]:
            return "SURVIVED", hs6, 1
        return "SCOPE_REVIEW", hs6, len(candidates)
    if hs6 in reverse:
        priors = sorted(reverse[hs6])
        prior = priors[0] if len(priors) == 1 else rng.choice(priors)
        return "DEAD_CODE", prior, len(forward[prior])
    return None


def main():
    log = (HERE / "build_eval.log").open("w")

    def say(msg):
        print(msg)
        log.write(msg + "\n")
        log.flush()

    if not POOL_TEXT.exists():
        raise SystemExit("pool_text.jsonl is missing; run fetch_pool.py first")
    dev_ids = {line.strip() for line in DEV_IDS.read_text().splitlines() if line.strip()}
    say(f"dev_ids_excluded={len(dev_ids)}")

    texts = {}
    with POOL_TEXT.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                texts[row["rulingNumber"]] = row
    say(f"pool_text_cached={len(texts)}")

    rng = random.Random(SEED)
    forward, reverse, has_ex = load_correlation()

    frame = [json.loads(line) for line in FRAME.read_text().splitlines() if line.strip()]
    eligible = []
    reasons = collections.Counter()

    for record in frame:
        number = record["rulingNumber"]
        if (record.get("rulingDate") or "")[:4] < "2022":
            continue
        codes = [normalize(t) for t in (record.get("tariffs") or [])]
        # Chapters 98 and 99 are special provisions, not classifications: 47.2% of
        # the pool names one and 1.71% name one first, so `tariffs[0]` would make
        # a Section 301 surcharge the answer key.
        codes = [c for c in codes if len(c) >= 8 and not c.startswith(("98", "99"))]
        if not codes:
            reasons["no_substantive_tariff"] += 1
            continue
        if number in dev_ids:
            reasons["in_dev_set"] += 1
            continue
        cached = texts.get(number)
        if cached is None:
            reasons["text_not_cached"] += 1
            continue
        description, status = parse_description(cached.get("text"))
        if status != "ok":
            reasons[status] += 1
            continue
        verdict = classify(codes[0][:6], forward, reverse, has_ex, rng)
        if verdict is None:
            reasons["unmapped_hs6"] += 1
            continue
        stratum, prior_hs6, n_candidates = verdict
        eligible.append({
            "ruling_number": number,
            "ruling_date": (record.get("rulingDate") or "")[:10],
            "stratum": stratum,
            "prior_hs6": prior_hs6,
            "n_hs2022_candidates": n_candidates,
            "truth_hts8": codes[0][:8],
            "truth_hts_full": codes[0],
            "subject": cached.get("subject") or record.get("subject"),
            "url": cached.get("url"),
            "description": description,
            "description_status": status,
        })

    eligible.sort(key=lambda item: item["ruling_number"])
    by_stratum = collections.defaultdict(list)
    for item in eligible:
        by_stratum[item["stratum"]].append(item)

    say(f"eligible_total={len(eligible)}")
    for stratum in sorted(by_stratum):
        say(f"  {stratum}={len(by_stratum[stratum])}")
    say("excluded=" + json.dumps(dict(reasons), sort_keys=True))

    # Every remaining dead code is taken: the stratum is small and it is where the
    # claim lives. The rest is split between the other two in proportion.
    dead = len(by_stratum["DEAD_CODE"])
    survived = len(by_stratum["SURVIVED"])
    scope = len(by_stratum["SCOPE_REVIEW"])
    take_dead = min(dead, EVAL_N)
    rest = EVAL_N - take_dead
    quota = {
        "DEAD_CODE": take_dead,
        "SURVIVED": round(rest * survived / max(survived + scope, 1)),
    }
    quota["SCOPE_REVIEW"] = rest - quota["SURVIVED"]
    say("quota=" + json.dumps(quota, sort_keys=True))

    drawn = []
    for stratum in sorted(quota):
        want = min(quota[stratum], len(by_stratum[stratum]))
        if want < quota[stratum]:
            say(f"⚠ {stratum}: wanted {quota[stratum]}, only {want} available")
        drawn.extend(rng.sample(by_stratum[stratum], want))
    drawn.sort(key=lambda item: item["ruling_number"])

    overlap = {item["ruling_number"] for item in drawn} & dev_ids
    if overlap:
        raise SystemExit(f"eval overlaps the dev set on {len(overlap)} rulings")
    say(f"drawn={len(drawn)} overlap_with_dev=0")

    unusable = [item for item in drawn if item["description_status"] != "ok"]
    if unusable:
        raise SystemExit(f"{len(unusable)} drawn items are unusable; the filter failed")
    say("all_drawn_items_usable=yes")

    (HERE / "eval_ids.txt").write_text(
        "\n".join(item["ruling_number"] for item in drawn) + "\n")
    with (HERE / "eval.jsonl").open("w", encoding="utf-8") as fh:
        for item in drawn:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    (HERE / "EVAL_SAMPLING.json").write_text(json.dumps({
        "seed": SEED,
        "n": len(drawn),
        "quota": quota,
        "eligible_by_stratum": {k: len(v) for k, v in sorted(by_stratum.items())},
        "excluded": dict(reasons),
        "drawn_by_stratum": dict(collections.Counter(i["stratum"] for i in drawn)),
        "dev_ids_excluded": len(dev_ids),
        "note": "Eligibility decided before drawing; no item is removed afterwards.",
    }, indent=2, sort_keys=True) + "\n")
    say("DONE")
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
