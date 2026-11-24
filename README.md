# CheXpert golden test for Claude Opus 5.5

A blinded, repeatable benchmark harness. **SPEC.md is the source of truth**; DATASET_ANALYSIS.md explains the data.

## Setup (Python 3.11+)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # add pydicom for DICOM input, redivis + pandas for Step 0
cp .env.example .env                     # then fill in ANTHROPIC_API_KEY and REDIVIS_API_TOKEN
python tests/test_pipeline.py            # self-test: synthetic data + mock model, no API calls
```

## Runbook (SPEC §13)
| Step | Command |
|---|---|
| 0 Data | Starter prompt B in SPEC.md §0 (Redivis checks, then validation DICOMs into `data/images/`, radiologist labels into `data/valid_labels.csv`) |
| 1 Golden set | `python -m harness.prepare_golden --labels data/valid_labels.csv --image-root data/images --out golden --name chexpert-valid-200 --expect-studies 200 --expect-images 234` |
| 2 Audit blinding | `python -m harness.run_eval --show-request` |
| 3 Smoke run | `python -m harness.run_eval --limit 5` then `python -m harness.score runs/<id>` |
| 4 Pass line | Write O1 into SPEC.md §2 **before** the full run |
| 5 Full run | `python -m harness.run_eval --mode batch` (retry failures: `--mode sync --run-dir runs/<id>`) |
| 6 Consistency | `python -m harness.run_eval --limit 50 --repeats 3` |
| 7 Score | `python -m harness.score runs/<id> --consistency-run runs/<rep_id>` |
| 8 Compare | `python -m harness.compare runs/<A> runs/<B>` (exit 1 = a primary finding got worse) |

## Layout
- `harness/prepare_golden.py` builds `golden/` (opaque PNGs, manifest, sealed reference, hash lock)
- `harness/run_eval.py` blinded runner (sync, batch, mock; resumable; never opens `golden/_sealed/`)
- `harness/score.py` metrics, gates, `report.md`, `misses.csv`
- `harness/compare.py` paired-bootstrap regression gate
- `harness/fetch_redivis.py` Step 0 helper (**unverified** Redivis client calls)
- `tests/output/` example outputs from the self-test (synthetic data, mock model: not real results)
