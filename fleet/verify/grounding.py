"""Where the deciding fact came from: the goods, or the schedule text.

Two 8-digit lines under one subheading are separated by a property of the
merchandise. Sometimes the description states it and the classification rests on
something the importer actually said. Sometimes it does not, and the agent got
there by reading the schedule and inferring what the goods must be. Both ship.
Only one of them is something the person signing can check against the entry.

This is not a gate, and the measurement is why. Requiring a quote before
shipping was tried and killed: on the development set the deciding fact is
present in the description 57.1% of the time (28/49 correct tie cases), against
the 85% the escalation ceiling needs, so a mandatory version would have sent
23 more cases to a person than the product allows. Flagging costs nothing and
tells the signer the same thing.

The normaliser is deliberately shallow. An earlier attempt at this measurement
dropped stopwords and short tokens, which discards exactly the content that
separates 8-digit lines: `20 liters`, `not over`, `kg`. Case, whitespace and the
shape of a quote mark are noise. Nothing else is.
"""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum

#: A span this short is a fragment of the article's name, not the fact that
#: decides between two lines: `horticultural sprayer` resolves against the
#: description while separating nothing. Quantities are the exception and get
#: one word fewer, because `600-liter tank` is the whole discriminator and the
#: schedule splits on exactly that kind of threshold.
MIN_WORDS = 3
MIN_WORDS_WITH_QUANTITY = 2

_QUOTES = str.maketrans({
    "‘": "'", "’": "'", "‛": "'",
    "“": '"', "”": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
})
_SPACE = re.compile(r"\s+")


class FactSource(StrEnum):
    DESCRIPTION = "description"              # the importer stated it
    SCHEDULE_INFERENCE = "schedule_inference"  # read out of the tariff text


def normalise(text: str) -> str:
    """Fold away what a quote can differ in without meaning anything else."""
    folded = unicodedata.normalize("NFKC", text or "").translate(_QUOTES)
    return _SPACE.sub(" ", folded).strip().casefold()


def fact_source(quote: str | None, description: str) -> FactSource:
    """DESCRIPTION when the quote is a continuous run of the description.

    Continuous, because an omission inside a quote is how a citation misleads
    without stating anything false, and the same holds for the goods.
    """
    span = normalise(quote or "")
    floor = MIN_WORDS_WITH_QUANTITY if any(c.isdigit() for c in span) else MIN_WORDS
    if len(span.split()) < floor:
        return FactSource.SCHEDULE_INFERENCE
    return (FactSource.DESCRIPTION if span in normalise(description)
            else FactSource.SCHEDULE_INFERENCE)
