"""What a classification turns out to mean for the importer.

Picking the code is the judgment. What it costs follows from it, and following
from it is arithmetic, so the officer should not have to do that part by hand.

The division of labour here is the point of the module:

* **Computed and stated.** A rate gap, a chapter 99 add-on. The schedule answers
  these outright, so the finding is a fact with a number attached.
* **Raised for a person.** A name that resembles one on a screening list.
  Resemblance is not identity, and 25,939 entries produce plenty of resemblance.
  Deciding it is a person's job, and pretending otherwise would ship a system that
  is confidently wrong about who somebody is.

Nothing sits between those two. A finding is either something the data settles or
something a person settles, and the severity says which.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum

from fleet.triage.money import duty_owed, parse_rate

#: Ordered worst first, because that is the order they are shown in.
class Severity(IntEnum):
    HUMAN = 0    # a person has to decide; the machine will not
    ACTION = 1   # money is owed or a filing is wrong
    INFO = 2     # worth knowing, nothing to do


@dataclass(frozen=True)
class Finding:
    kind: str
    severity: Severity
    headline: str
    detail: str


#: Countries whose goods carry the Section 301 additional duties. The list is the
#: reason chapter 99 subheadings exist on a tariff line at all.
SECTION_301_ORIGINS = {"china", "hong kong", "macau"}

CH99 = re.compile(r"\b(99\d\d\.\d\d(?:\.\d\d)?)\b")
DIGITS = re.compile(r"\D")


def _rate(code: str, rows) -> tuple[float | None, dict | None]:
    """The general rate on a code's eight-digit level, and the row it came from.

    Returns `None` for a code shorter than eight digits: rates hang on the eighth
    digit, so six digits is not a rate that was left out, it is a rate that does
    not exist yet.
    """
    code = DIGITS.sub("", code or "")
    if len(code) < 8:
        return None, None
    want = code[:8]
    for row in rows:
        rc = DIGITS.sub("", row.get("htsno") or "")
        if rc.startswith(want):
            general = (row.get("general") or "").strip()
            if general:
                return _as_percent(general), row
    return None, None


def _as_percent(rate: str) -> float | None:
    """The ad valorem part of a rate, for comparing two lines against each other.

    A specific duty ("6.8¢/kg") has no percentage to compare, which is why the
    money difference is worked out separately by `fleet.triage.money` from the
    entry's own quantity rather than guessed at here.
    """
    if not rate:
        return None
    return parse_rate(rate).percent


def _money(value: float) -> str:
    return f"${value:,.0f}"


def _normalise(name: str) -> str:
    """Strip the corporate furniture that makes two spellings of one party differ."""
    name = re.sub(r"[^\w\s]", " ", (name or "").lower())
    drop = {"ltd", "limited", "llc", "inc", "incorporated", "co", "corp",
            "corporation", "gmbh", "sa", "bv", "pte", "plc", "company", "the"}
    return " ".join(w for w in name.split() if w not in drop)


def assess(case: dict, snapshot, screening_list) -> list[Finding]:
    """Everything this classification implies, worst first."""
    out: list[Finding] = []
    rows = snapshot.hts
    selected = case.get("selected_code")
    if not selected:
        return out

    new_rate, new_row = _rate(selected, rows)
    prior_rate, _ = _rate(case.get("prior_code"), rows)
    value = case.get("annual_value")

    # 1. What the choice was worth. Stated on every judged item, because "the
    #    runner-up was the same price" is as much a fact as a gap of twenty points.
    runner_rate, _ = _rate(case.get("runner_up_code"), rows)
    if new_rate is not None and runner_rate is not None:
        gap = abs(new_rate - runner_rate)
        if gap >= 0.05:
            out.append(Finding(
                "DECISION_STAKE", Severity.INFO,
                f"{gap:.1f} points rode on this decision",
                f"The chosen line is {new_rate:.1f}% and the runner-up "
                f"{runner_rate:.1f}%, a difference of {gap:.1f} percentage points"
                + (f", or {_money(value * gap / 100)} a year at the stated volume."
                   if value else ".")))

    # 2. The filed code against the correct one. Only when the filed code reaches
    #    eight digits, since below that there is no rate to compare.
    if new_rate is not None and prior_rate is not None:
        gap = new_rate - prior_rate
        if gap > 0.05:
            amount = f" That is {_money(value * gap / 100)} a year at the stated volume." if value else ""
            out.append(Finding(
                "UNDERPAID_DUTY", Severity.ACTION,
                f"Under-declared by {gap:.1f} points",
                f"Entries filed under {case['prior_code']} paid {prior_rate:.1f}%. "
                f"The correct line {selected[:8]} is {new_rate:.1f}%, so every entry "
                f"since the revision has underpaid by {gap:.1f} percentage points."
                + amount))
        elif gap < -0.05:
            amount = f" That is {_money(value * -gap / 100)} a year at the stated volume." if value else ""
            out.append(Finding(
                "OVERPAID_DUTY", Severity.INFO,
                f"Over-declared by {-gap:.1f} points",
                f"Entries filed under {case['prior_code']} paid {prior_rate:.1f}% "
                f"where the correct line {selected[:8]} is {new_rate:.1f}%."
                + amount))

    # 3. Lines that are not charged on value at all. Nearly a tenth of the
    #    schedule charges by weight or by head, and staying silent about those
    #    reads on screen as "nothing owed" rather than "I need the weight".
    if new_row:
        rate = parse_rate(str(new_row.get("general") or ""))
        if rate.needs_quantity or rate.prose:
            owed = duty_owed(rate, value, case.get("quantity"), case.get("quantity_unit"))
            if owed.known:
                out.append(Finding(
                    "DUTY_BY_QUANTITY", Severity.INFO,
                    f"Charged by {rate.unit}: {_money(owed.amount)}",
                    f"Line {selected[:8]} is charged at {owed.basis}, which is "
                    f"{_money(owed.amount)} on this entry rather than a percentage "
                    f"of its value."))
            else:
                part = (f"{_money(owed.subtotal)} of it is settled already "
                        f"({owed.subtotal_basis}), and " if owed.partial else "")
                out.append(Finding(
                    "DUTY_NOT_COMPUTABLE", Severity.HUMAN,
                    (f"{_money(owed.subtotal)} so far, and {owed.missing} to finish"
                     if owed.partial else f"Duty cannot be worked out: {owed.missing}"),
                    f"Line {selected[:8]} is charged at {owed.basis}. {part}"
                    f"nobody can state the rest until somebody supplies "
                    f"{owed.missing}, so the figure is incomplete rather than zero."))

    # 4. The chapter 99 add-on, which is where the real money usually is.
    origin = (case.get("country_of_origin") or "").strip().lower()
    if new_row and origin in SECTION_301_ORIGINS:
        for note in new_row.get("footnotes") or []:
            match = CH99.search(note.get("value") or "")
            if match:
                out.append(Finding(
                    "ADDITIONAL_DUTY", Severity.ACTION,
                    f"Section 301 applies: {match.group(1)}",
                    f"Goods of {case['country_of_origin']} under {selected[:8]} must "
                    f"also be reported under {match.group(1)}. The base rate of "
                    f"{new_rate:.1f}% is not the rate that will be charged."
                    if new_rate is not None else
                    f"Goods of {case['country_of_origin']} under {selected[:8]} must "
                    f"also be reported under {match.group(1)}."))
                break

    # 5. Screening. Raised, never decided.
    supplier = _normalise(case.get("supplier"))
    if supplier:
        for entry in screening_list:
            listed = _normalise(entry.get("name"))
            if not listed:
                continue
            if listed in supplier or supplier in listed:
                out.append(Finding(
                    "SCREENING_MATCH", Severity.HUMAN,
                    f"Possible match on the {entry.get('source_list', 'screening list')}",
                    f"“{case['supplier']}” resembles “{entry['name']}” on the "
                    f"{entry.get('source_list', 'screening list')}"
                    + (f" ({entry['license_requirement']})" if entry.get("license_requirement") else "")
                    + ". Names resemble each other for innocent reasons, so a person "
                      "must confirm whether this is the same party."))
                break

    out.sort(key=lambda f: f.severity)
    return out
