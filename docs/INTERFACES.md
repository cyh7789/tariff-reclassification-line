# Frozen interface contract (v1.1, 2026-08-17)

Every parallel track builds against this file. **Nothing here changes without a version bump
and a note in the changelog at the bottom.** Tracks do not share mutable JSON conventions;
if a track needs a field that is not here, it asks first.

Language: all code, identifiers, log messages, comments, docstrings and user-facing strings
are English. Chinese appears nowhere in this repository.

Python 3.11. No network access anywhere outside `fleet.sync`.

---

## 0. Vocabulary

| Term | Meaning |
|---|---|
| **HTS code** | US tariff code. 10 digits, dot-formatted `8543.70.9860`. Duty rates hang off the **8-digit** level; the last two digits are a statistical suffix. |
| **HS6** | First 6 digits, internationally harmonized. The correlation table works at HS6 only. |
| **dead code** | An HS2017-era code that has no entry in the current HTS revision. |
| **scope reduction** | The code still exists, but the goods it covers shrank (chapter-note revision). A set difference cannot see this. |
| **snapshot** | One dated, immutable directory of fetched source data plus manifests. |

Codes are carried **as strings, digits only, no dots** (`8543709860`). Formatting is a
presentation concern. Any function accepting a code accepts 6, 8, or 10 digits and says
in its signature which lengths are meaningful.

---

## 1. Snapshot layout (produced by track A, consumed by everyone)

```
data/snapshots/<YYYY-MM-DD>/
  hts.jsonl          + hts.manifest.json
  cross.jsonl        + cross.manifest.json
  csl.jsonl          + csl.manifest.json
  correlation.csv    + correlation.manifest.json
  SNAPSHOT.json
```

`data/` is git-ignored in full. The repository ships fetch scripts only, because the
UN/WCO correlation tables may not be redistributed. `make data` rebuilds a snapshot from
the original sources.

`SNAPSHOT.json` is written last and its presence is the only signal that a snapshot is
complete:

```json
{
  "snapshot_id": "2026-08-18",
  "created_at": "2026-08-18T04:12:07Z",
  "sources": ["hts", "cross", "csl", "correlation"],
  "status": "ok"
}
```

### 1.1 Manifest (identical shape for every source)

```json
{
  "source": "hts",
  "url": "https://hts.usitc.gov/reststop/exportList?from=0100&to=9999&format=JSON&styles=false",
  "fetched_at": "2026-08-18T04:09:55Z",
  "revision": "2026HTSRev16",
  "row_count": 35791,
  "bytes": 7117481,
  "sha256": "…",
  "min_rows": 30000,
  "min_bytes": 1000000,
  "status": "ok",
  "staleness_days": 0
}
```

`revision` is `null` when the source does not publish one. `row_count`, `bytes` and `sha256` all describe the file that was written to disk, never the upstream payload, because the file is the only thing the gate can re-measure.

`staleness_days` records how far behind the source already was at fetch time: the gap between its own `Last-Modified` and `fetched_at`, or `0` when it sends no such header. It says nothing about how old the snapshot is now. Age is the gate's job, per §2.

### 1.2 Record shapes

`hts.jsonl` holds one line per HTS row, in file order. Order carries meaning: `indent`
resolution walks upward through preceding rows.

```json
{"htsno": "8543709860", "indent": 3, "description": "Other",
 "general": "2.6%", "special": "Free (A,AU,…)", "other": "35%", "units": ["No."],
 "footnotes": [{"columns": ["desc"], "value": "See 9903.88.15.", "type": "endnote"}],
 "additional_duties": null, "row_index": 28104}
```

`htsno` is `null` for header rows that carry only a description. Rate fields are the raw strings as published; parsing them is not this layer's job.

`footnotes` is where an extra duty actually hangs. 783 rows point at a chapter 99 subheading (`9903.90` on 680 of them, the Section 301 China list `9903.88` on 6), and for goods of the wrong origin that add-on dwarfs the base rate, so a duty comparison that ignores it is wrong rather than incomplete. `additional_duties` is populated on only 512 rows, all agricultural safeguards in chapter 9904; it is carried because it is free to carry, not because it is the 301 hook. The upstream export also ships a misspelt `addiitionalDuties` field that is null on every row; ignore it.

`cross.jsonl` holds one line per CBP ruling:

```json
{"ruling_number": "N317442", "ruling_date": "2021-03-08",
 "tariffs": ["8543709860"], "subject": "…", "category": "…",
 "related_rulings": ["N301122"], "url": "…"}
```

`url` is derived, not fetched: the search endpoint does not return one, and paying 218,606 single-ruling requests to collect them is not worth it. It is built as `https://rulings.cbp.gov/ruling/<RULING_NUMBER>`, verified to return 200.

⚠️ CROSS search returns ruling numbers **upper-case**, the detail endpoint returns them **lower-case**. Track A normalizes to upper-case on write. Any join key elsewhere in the
codebase is already upper-case and must not be re-cased.

`csl.jsonl` holds one line per Consolidated Screening List entry, with fields passed through
from the ITA API plus `source_list` and `license_requirement`.

`correlation.csv` carries these columns, in this order:

```
hs2017,hs2022,relationship,n_hs2022_candidates,is_ex,unsd_relationship,in_wco_table2,is_sweep
```

Already built and validated during research (15,656 rows, sha256 `d969990f…`). Track A ports the
existing `fetch_sources.sh` + `parse_wco_table2.py` + `build_correlation.py` into the
package unchanged in behavior; the byte-identical `hs2017_hs2022.csv` is the acceptance test.

---

## 2. Health gate (track A owns it, track B calls it)

```python
# fleet/sync/gate.py
class DataSourceUnhealthy(Exception):
    """Raised when a snapshot cannot be trusted. Callers must halt, never degrade."""

def assert_healthy(snapshot_dir: Path, sources: Sequence[str] = ALL_SOURCES) -> None: ...
def load_manifest(snapshot_dir: Path, source: str) -> Manifest: ...
```

`assert_healthy` raises if any of these hold for any requested source:

1. the manifest is missing, or `SNAPSHOT.json` is missing / `status != "ok"`
2. `row_count < min_rows` or `bytes < min_bytes`
3. `sha256` does not match the file on disk
4. `staleness_days > 30`, or the snapshot is more than 30 days old measured from `fetched_at` to `now`

A manifest value written at fetch time can never grow, so age has to be recomputed at every gate call or the check is decorative: a snapshot pulled in 2024 would still declare `staleness_days: 0` today. `assert_healthy` therefore takes `now: datetime | None = None`, defaulting to the current time, and the fixture tests pass a fixed value so a committed fixture does not turn the suite red on a calendar date.

The three known traps this gate exists for, all observed for real:

- **Government endpoints 302.** Every fetch uses `curl -L` / `allow_redirects=True`.
- **A wrong filename returns HTTP 200 with 0 bytes, not 404.** An empty screening list
  means everything passes screening, which is the most dangerous failure mode available
  here. Status code is never sufficient; the size and row-count floors are the real check.
- **Case mismatch on the CROSS join key**, per §1.2.

There is no partial mode. A failed gate halts the line and the UI shows a global banner.

---

## 3. Triage (track B)

Pure functions. No network, no LLM, no I/O beyond reading a snapshot.

```python
# fleet/triage/types.py
class Bucket(StrEnum):
    SURVIVED     = "SURVIVED"       # code still current
    DEAD_CODE    = "DEAD_CODE"      # code gone from the current HTS
    SCOPE_REVIEW = "SCOPE_REVIEW"   # code current, coverage shrank

class Route(StrEnum):
    DETERMINISTIC = "DETERMINISTIC" # settled by table lookup, agent never invoked
    AGENT         = "AGENT"         # needs judgment

@dataclass(frozen=True)
class LineItem:
    item_id: str
    description: str
    hs_code: str            # digits only, as filed (HS2017 era)
    product_line: str       # tenant-scoped grouping

@dataclass(frozen=True)
class Candidate:
    hs_code: str            # HS6, from the correlation table
    is_ex: bool             # partial coverage marker (WCO Table II)
    relationship: str       # UNSD relationship column, verbatim

@dataclass(frozen=True)
class TriageResult:
    item_id: str
    bucket: Bucket
    route: Route
    reason: str             # short English phrase, shown in the UI
    candidates: tuple[Candidate, ...]      # empty for SURVIVED
    selected_code: str | None              # set only for 1:1 deterministic resolution
    current_duty: DutyRate | None
    prior_duty: DutyRate | None
    snapshot_id: str
```

```python
# fleet/triage/engine.py
def triage(items: Sequence[LineItem], snapshot_dir: Path) -> list[TriageResult]: ...
```

### 3.1 Routing rules, in order

1. The 8-digit prefix exists in the current HTS → `SURVIVED` / `DETERMINISTIC`,
   `reason = "code unchanged in current revision"`.
2. Otherwise it is a dead code. Look up its HS6 in `correlation.csv`.
   - exactly one candidate **and** `is_ex is False` → `DEAD_CODE` / `DETERMINISTIC`,
     `selected_code` set, `reason = "one-to-one correlation, resolved by table lookup"`.
   - anything else (many candidates, or one candidate marked `ex`) → `DEAD_CODE` / `AGENT`.
   - no correlation row at all → `DEAD_CODE` / `AGENT`,
     `reason = "no correlation entry; requires reclassification from first principles"`.
3. A surviving code whose HS6 appears in the correlation table as a **source of a split**
   (its HS6 maps to more than one HS2022 code, or carries `is_ex`) → `SCOPE_REVIEW` /
   `AGENT`. This rule runs after rule 1 and reclassifies the result.

Rule 3 is the one a set difference cannot produce, and it is why the fan-out on screen is
three-way rather than two-way. It is deliberately over-inclusive: it flags codes whose
coverage *may* have shrunk, and the agent decides. Over-inclusion costs autonomy rate, so
the count it produces is reported honestly and never tuned to make a number look better.

**1:1 items must never enter the agent queue.** Feeding easy items to the agent inflates
the autonomy denominator. This is a correctness property of the triage layer, tested
directly.

### 3.2 Duty rate resolution

```python
# fleet/triage/duty.py
@dataclass(frozen=True)
class DutyRate:
    hts8: str
    general: str        # verbatim published string
    special: str | None
    other: str | None
    resolved_from_row: int      # row_index the value was actually taken from
    inherited: bool             # True when the value came from an ancestor row
```

```python
def resolve(hts_code: str, hts_rows: Sequence[dict]) -> DutyRate | None: ...
```

Rates are published sparsely: a row may leave `general` empty and inherit it from the
nearest preceding row with a smaller `indent`. Resolution walks upward from the matched
row until it finds a non-empty value, and records where it came from. `resolved_from_row`
exists so the evidence pack can cite the exact line the number came from; a rate with no
traceable row is not shipped.

Match at 8 digits. A 10-digit input is truncated to 8 first.

### 3.3 Test obligations

Both tracks ship `pytest` tests that assert runtime behavior, never source shape. Minimum:

- A snapshot fixture small enough to commit (a few hundred rows), built by trimming a real
  snapshot, so tests need no network.
- Track A: a test per trap. The first two make the gate raise (a 200-with-empty body, a row count under the floor); the case trap is tested at the fetch layer instead, because no gate check reads ruling numbers and adding one would mean scanning 218,606 lines on every open.
- Track B: one test per routing rule, plus the invariant that no `1:1` item is ever routed
  to `AGENT`, plus an inherited-rate case where `inherited is True` and
  `resolved_from_row` points at the ancestor.
- Prove one test bites: flip the guarded condition, watch it go red, revert.

---

## Changelog

- **v1, 2026-08-17.** Initial freeze. Covers tracks A (sync) and B (triage) only. Tracks C onward extend this file rather than inventing parallel conventions.
- **v1.1, 2026-08-17.** Written after both tracks delivered and reported back. Age is recomputed at gate time rather than read from a value that cannot grow; `hts.jsonl` carries `footnotes` and `additional_duties`, without which a duty comparison silently omits Section 301; the example manifest carried a row count taken from a different export format; `url` on a ruling is documented as derived; the correlation table's path no longer points at a directory that does not ship.
