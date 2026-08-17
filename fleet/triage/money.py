"""What a published rate actually costs on a shipment.

A rate in the schedule is a sentence, not a number. Of the 13,788 lines that
carry one: 45% are a plain percentage, 42% are free, 5.6% are charged per unit of
quantity ("1¢/kg", "68¢/head"), 2.9% are both at once ("$1.104/kg + 14.9%"), and
2.2% are prose pointing at another heading.

Only the first two can be costed from an invoice value alone. The rest need the
quantity, and until now the system said nothing at all about them, which reads on
screen as "no duty difference" rather than as "ask somebody for the weight". A
figure that is silently absent is worse than one that is refused out loud, so
every branch here either produces an amount or names what it is missing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Rate components. A compound rate is simply both of them.
AD_VALOREM = re.compile(r"(?<![\d.])([\d.]+)\s*%")
SPECIFIC = re.compile(r"(?:(\$)\s*([\d.]+)|([\d.]+)\s*¢)\s*/\s*([a-zA-Z.]+(?:\s*[a-zA-Z.]+)?)")
FREE = re.compile(r"^\s*free\s*$", re.I)


@dataclass(frozen=True)
class Rate:
    """A parsed rate. `percent` and `per_unit` can both apply; that is a compound."""
    percent: float | None = None
    per_unit: float | None = None      # in dollars
    unit: str | None = None            # "kg", "head", "liter", …
    prose: str = ""                    # set when the rate is not arithmetic at all

    @property
    def computable(self) -> bool:
        return not self.prose and (self.percent is not None or self.per_unit is not None)

    @property
    def needs_quantity(self) -> bool:
        return self.per_unit is not None


@dataclass(frozen=True)
class Duty:
    """What the shipment owes, or as much of it as the data supports.

    A compound rate is two charges, and losing the whole figure because one of
    them is missing throws away work that was already done. On a jacket at
    49.7¢/kg + 19.7% with an invoice but no weight, the officer can be told the
    19.7% part to the cent and exactly what is still owed on top.
    """
    amount: float | None
    basis: str                          # how it was worked out, for the officer
    missing: str = ""                   # what would settle it, when amount is None
    subtotal: float | None = None       # the part that could be worked out anyway
    subtotal_basis: str = ""

    @property
    def known(self) -> bool:
        return self.amount is not None

    @property
    def partial(self) -> bool:
        return self.amount is None and self.subtotal is not None


def parse_rate(text: str) -> Rate:
    """Turn a published rate into something arithmetic, or say it is not."""
    text = (text or "").strip()
    if not text:
        return Rate(prose="no rate published on this line")
    if FREE.match(text):
        return Rate(percent=0.0)

    percent = AD_VALOREM.search(text)
    specific = SPECIFIC.search(text)
    if not percent and not specific:
        # "The rate applicable to the natural juice in heading 2009" and friends.
        # These are real rates; they are just not a number until a person reads
        # the heading they point at.
        return Rate(prose=text)

    per_unit = unit = None
    if specific:
        dollars, dollar_amount, cents, unit = specific.groups()
        per_unit = float(dollar_amount) if dollars else float(cents) / 100
        unit = unit.strip().rstrip(".").lower()
    return Rate(percent=float(percent.group(1)) if percent else None,
                per_unit=per_unit, unit=unit)


def duty_owed(rate: Rate, value: float | None, quantity: float | None = None,
              unit: str | None = None) -> Duty:
    """The duty on one line, or a plain statement of what is missing.

    Quantity and unit come from the importer's own entry data. Guessing either
    would produce a confident number attached to nothing, which is the failure
    this module exists to prevent.
    """
    if rate.prose:
        return Duty(None, "the schedule states this rate in words",
                    missing=f"a person has to read: “{rate.prose}”")

    parts, total, done = [], 0.0, None
    if rate.percent is not None:
        if value is None:
            return Duty(None, f"{rate.percent:g}% of the customs value",
                        missing="the customs value of the shipment")
        total += value * rate.percent / 100
        parts.append(f"{rate.percent:g}% of ${value:,.0f}")
        done = (round(total, 2), parts[0])

    if rate.per_unit is not None:
        basis = f"${rate.per_unit:,.3f} per {rate.unit}"
        if quantity is None:
            missing = f"the quantity in {rate.unit}"
        elif unit and rate.unit and unit.lower().rstrip(".") != rate.unit:
            missing = f"a quantity in {rate.unit}; the entry states {unit}"
        else:
            missing = ""
        if missing:
            # Hand back what is settled along with what is not. "Unknown" and
            # "19.7% of the invoice, plus a per-kilo charge nobody can size yet"
            # are different messages, and only the second one can be acted on.
            return Duty(None, basis, missing=missing,
                        subtotal=done[0] if done else None,
                        subtotal_basis=done[1] if done else "")
        total += quantity * rate.per_unit
        parts.append(f"${rate.per_unit:,.3f} × {quantity:,g} {rate.unit}")

    return Duty(round(total, 2), " + ".join(parts))
