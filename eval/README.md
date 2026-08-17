# The frozen evaluation set

`eval_ids.txt` is 500 CBP ruling numbers, drawn 2026-08-17 and not changed since.
`EVAL_SAMPLING.json` records the seed, the quota per stratum, and every reason an
item was excluded. `build_frozen_eval.py` reproduces the draw from the same inputs.

The ruling text itself is not committed: it is public domain under 17 U.S.C. §105
and can be re-fetched from `rulings.cbp.gov/api/ruling/<number>`, so shipping the
list rather than the corpus keeps the repository free of bulk third-party data
without costing anyone reproducibility.

## What the set is

Each item is a CBP ruling issued on or after 2022-01-01, which is to say after the
current nomenclature took effect. The code CBP assigned is the answer key: it is
the one place a defensible answer exists, since no third party publishes "correct"
reclassifications. The input handed to the system is the code the goods would have
been filed under beforehand, recovered from the official correlation table, plus
the merchandise description taken verbatim from the ruling.

## Strata, and what each one can prove

    DEAD_CODE      288   the prior HS6 no longer exists
    SCOPE_REVIEW    90   the prior HS6 survives but maps to several current ones
    SURVIVED       122   the prior HS6 survives, one-to-one

**Only DEAD_CODE tests reclassification.** In the other two strata the prior code
and the answer share their first six digits by construction, because a heading
that survived a revision keeps its number. Those strata test a different and
narrower thing: given the right heading, does the system pick the right 8-digit
line, which is the level duty rates hang on. Reporting one blended accuracy across
all three would hide that.

## Eligibility was decided before the draw

An earlier draw took 500 rulings and then found 30 with no extractable
description. Removing them afterwards means changing the denominator with the
answers already visible. Here the whole pool was fetched first, eligibility
settled against the cached text, and only then was the sample taken, so the
frozen 500 is 500 usable items.

The filter has a cost worth stating rather than discovering: extraction keys off
the NY-letter template, so HQ rulings and revocation notices are under-represented.

## Leakage

The agent searches the same ruling corpus these items come from. The precedent
index is built with these 500 ruling numbers and their `relatedRulings` removed;
without that the agent can retrieve its own answer key.
