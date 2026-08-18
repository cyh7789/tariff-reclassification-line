"""Put one bad citation into a real answer, so the checker can be seen working.

A checker that has never been watched failing is a claim. The recording needs one
item where a citation does not hold up and the line stops in front of the viewer,
and the honest way to get it is not to wait for the model to hallucinate on cue.

What this does and does not touch
---------------------------------
It takes an answer the model really produced, on a run that really happened, and
alters one quote by inserting a single word. Nothing else moves: the snapshot is
untouched, no ruling number is invented, the code and the reasoning stay as the
model wrote them, and the altered answer goes through the same
`CitationVerifier.check` as every other case. The fault is in the claim, which is
where a hallucinated citation would be.

Why an inserted word rather than a changed one
-----------------------------------------------
`normalize_words` folds punctuation, case, line breaks and footnote markers,
because those are transcription and not word choice. An inserted word survives
all of that folding and still fails the substring check, which is exactly the
shape the checker exists to catch: a model filling in a reference it never opened
adds and rewords rather than merely repunctuating.

Rulings are not eligible. The corpus carries subjects rather than full text, so a
quote attributed to a ruling is reported as not checkable; injecting there would
produce a fault that passes, which would demonstrate the opposite of the point.
"""

from __future__ import annotations

import copy

#: Reads as a qualifier a paraphraser would add, so the screen shows a plausible
#: citation rather than obvious damage. Its own words are not what matters: any
#: inserted word fails, and the demo is better for the fault being subtle.
INSERTED_WORD = "solely"

#: A ruling's quote is not compared against anything, so a fault placed there
#: would sail through the check it is meant to demonstrate.
CHECKED_KINDS = ("chapter_note", "tariff_line")


class NothingToInject(Exception):
    """The answer carries no quote that the checker would actually compare."""


def inject(answer: dict) -> tuple[dict, dict]:
    """Return a copy of `answer` with one quote altered, and what was altered.

    Deterministic: the same answer always yields the same fault, so the demo is
    a fixture and not a coin toss.
    """
    for index, citation in enumerate(answer.get("citations") or []):
        quote = (citation.get("quote") or "").strip()
        if citation.get("kind") not in CHECKED_KINDS or len(quote.split()) < 4:
            continue
        words = quote.split()
        at = len(words) // 2
        altered = " ".join(words[:at] + [INSERTED_WORD] + words[at:])
        faulted = copy.deepcopy(answer)
        faulted["citations"][index]["quote"] = altered
        return faulted, {
            "kind": "citation fault injection",
            "ref": citation.get("ref", ""),
            "original": quote,
            "altered": altered,
            "change": f"inserted the word {INSERTED_WORD!r} at position {at}",
        }
    raise NothingToInject(
        "no chapter note or tariff line quote long enough to alter; "
        "a ruling quote is not compared and would pass")
