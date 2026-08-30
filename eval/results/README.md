# The run behind the numbers

One run, 2026-08-30, on the frozen 500. It is the only run of this set.

| File | What it is |
|---|---|
| `eval-frozen-0830.jsonl` | Every answer the agent produced, one line per item: selected code, runner-up, the citations, the tool calls it made, token usage, wall time. |
| `SCORE-2026-08-30.txt` | The output of `fleet.eval.score` on that file, including the mechanical floors computed on the same population. |

Reproduce the scoring without spending anything:

```bash
PYTHONPATH=. python -m fleet.eval.score \
  --run eval/results/eval-frozen-0830.jsonl \
  --snapshot data/snapshots/2026-08-18 \
  --items <your rebuilt eval.jsonl>
```

The item file is not committed: it holds ruling text, which is public domain and re-fetchable, but shipping the corpus is what `eval_ids.txt` exists to avoid. `build_frozen_eval.py` rebuilds it from the same 500 ruling numbers. The redacted set used for this run has sha256 `ae24efa637253ac265e97ba629e96db845d0f2a73b43afa95962a807632a488e`.

Command that produced the run:

```bash
PYTHONPATH=. FLEET_ALLOW_API=1 FLEET_VERTEX_PROJECT=<project> \
  python -m fleet.agents.classifier \
    --snapshot data/snapshots/2026-08-18 \
    --dev <eval.jsonl> --out runs/eval-frozen-0830.jsonl \
    --workers 16 --tier standard
```

Each item's own ruling is excluded from the precedent index before the item runs, so nothing can cite itself.
