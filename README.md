# Tariff Reclassification Line

Re-classifies a manufacturer's product catalog after a Harmonized System nomenclature revision, and hands the compliance officer a signable evidence pack instead of a list of guesses.

One bounded classification agent runs under a deterministic control plane. A code the official correlation table maps one-to-one is settled by a program and never reaches the model; what is left is real judgment, and that is all the agent is asked for. Every citation it returns is re-resolved against a frozen snapshot by a checker the agent cannot influence.

Built for the All Things Agentic Hackathon. Architecture starts at [`docs/INTERFACES.md`](docs/INTERFACES.md).

## Spin-up

### Run it locally

```bash
pip install -r requirements.txt
brew install poppler                                  # pdftotext, for the PDF sources

python -m fleet.sync.snapshot --out data/snapshots/2026-08-18   # a few minutes
PYTHONPATH=. python -m uvicorn fleet.app.main:app --port 8080
```

Open `http://localhost:8080`. The model is off by default; nothing here calls a paid endpoint unless `FLEET_ALLOW_API=1` is set for that command. With it off the UI runs and the deterministic half of the work still happens.

To let it call Gemini, authenticate to a project with Vertex AI enabled and switch it on:

```bash
gcloud auth application-default login
FLEET_ALLOW_API=1 FLEET_VERTEX_PROJECT=<your-project> \
  PYTHONPATH=. python -m uvicorn fleet.app.main:app --port 8080
```

Case history goes to SQLite at `data/cases.db` unless `FLEET_PG_DSN` names a Postgres.

### Deploy it to Google Cloud

```bash
PROJECT=<your-project> bash deploy/cloudrun.sh
```

The script enables the APIs, creates a `db-f1-micro` Postgres 17 instance on Cloud SQL, grants the runtime service account `roles/aiplatform.user`, and deploys the container to Cloud Run with the Cloud SQL socket attached. It prints the service URL when it finishes. The snapshot ships inside the image on purpose: the frozen legal text and the revision that read it are one artifact.

Three flags on the deploy step are load-bearing rather than tuning, and the reasons are written at the top of `deploy/cloudrun.sh`: `--no-cpu-throttling`, `--max-instances=1`, `--min-instances=1`.

## Data sources

Every source is a public endpoint. None needs an API key, an account, or page scraping.

| Source | Endpoint | Measured 2026-08-17 |
|---|---|---|
| CBP customs rulings (CROSS) | `rulings.cbp.gov/api/search`, `/api/ruling/<number>` | 218,606 rulings, 62.9 MB |
| Current tariff schedule (USITC) | `hts.usitc.gov/reststop/exportList` | 35,791 rows, 7.1 MB, revision `2026HTSRev16` |
| Chapter legal notes (USITC) | `hts.usitc.gov/reststop/file?release=currentRelease&filename=Chapter%20<n>` | 98 chapters, 616,847 characters extracted |
| Consolidated Screening List (ITA) | `data.trade.gov` consolidated screening list | 25,939 entries, 30.9 MB |
| HS2017 to HS2022 correlation | UNSD conversion tables (xlsx) plus WCO Table II (PDF) | 15,656 code pairs |

### Licensing, and why this repository ships no data

The four US government sources are uncopyrighted. 17 U.S.C. §105: *"Copyright protection under this title is not available for any work of the United States Government."* They may be used and redistributed freely.

The correlation tables may not. The UN terms grant use *"for the User's personal, non-commercial use, without any right to resell or redistribute them or to compile or create derivative works therefrom."*

So the repository contains **fetch scripts only, and no third-party data**. `make data` rebuilds a snapshot from the original sources, which also makes the build reproducible from scratch rather than from a checked-in copy of someone else's file.

The WCO publishes the correlation tables with the statement that they *"have no legal status"* and *"constitute a guide only"*. The architecture takes that literally: the table decides where to look, and never what to conclude.

### Two traps these endpoints set

Both were hit for real during development, and both are guarded by tests.

**A wrong filename returns HTTP 200 with an empty body, not a 404.** An empty screening list means every party passes screening, which is the most dangerous failure available here. Status codes are never sufficient; the health gate checks byte and row floors, and re-checks the sha256 of what landed on disk.

**Government hosts redirect.** Every fetch follows redirects. Without that you get zero bytes and a 200.

## Rebuilding a snapshot

```bash
pip install -r requirements.txt      # requests, openpyxl, google-genai, pytest
brew install poppler                 # pdftotext, for the WCO and chapter-notes PDFs

python -m fleet.sync.snapshot --out data/snapshots/$(date +%F)
```

A snapshot takes a few minutes, most of it the ruling enumeration. `SNAPSHOT.json` is written last and its presence is the only signal that a snapshot is complete; every consumer calls `fleet.sync.gate.assert_healthy` before reading a byte.

## Tests

```bash
PYTHONPATH=. python -m pytest -q tests/
```

Offline against trimmed fixtures, no network. Two fixtures, on purpose: `tests/fixtures/snapshot` is cut from a real snapshot and is what the health gate is tested against; `tests/fixtures/triage` is hand-built from codes chosen to exercise each routing rule.
