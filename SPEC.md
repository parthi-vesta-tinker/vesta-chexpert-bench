# CheXpert Golden Test for Claude Opus 5.5: Handoff Spec

| | |
|---|---|
| Version | 1.2 |
| As of | 2026-11-24 |
| Changes in 1.2 | Harness built to this spec; self-test passes (§12). Build notes and interpretations in §11.3. §0 updated for the built kit. |
| Changes in 1.1 | Dataset findings from DATASET_ANALYSIS.md. Golden labels come from the 3-radiologist image labels, **not** the CheXpert Plus label files (which are machine-extracted from reports). Do-not-use list added (`report_fixed.json`). Image lookup by path stem. Step 0 checks rewritten. New open item O7. |
| Owner | Parthi Srinivasan |
| Status | **Harness built; self-test passes (31/31 assertions across the 13 checks), synthetic data and mock model only.** Not yet run on real data or against the real API. No data downloaded. Next: Step 0 (Starter prompt B). |
| Purpose of this file | The single source of truth for this project. It is written so that work can resume in a **different Claude account** with no access to the original chat or its memory. |

---

## 0. How to resume (read this first)

**This file is the only context that carries over.** A new Claude account has no chat history, no memory and no artifacts from the original account.

1. Unzip the kit (`chexpert-golden-eval.zip`) on your computer. It holds this file, `DATASET_ANALYSIS.md` and the built harness. If you only have the two markdown files, put them in a folder `chexpert-golden-eval/` and use the fallback prompt below.
2. Open Claude Code in that folder. On macOS, Windows or Ubuntu/Debian: Claude Desktop → **Code** tab → **Local** → **Open folder…**. On other Linux distributions (for example Arch/Omarchy), the desktop app isn't officially supported, so run `claude` in a terminal in the folder.
3. Create `.env` from `.env.example` with `ANTHROPIC_API_KEY=...` and `REDIVIS_API_TOKEN=...`. Never paste keys into chat. API calls are billed to the API key, separately from the Claude subscription.
4. Paste **Starter prompt A** (below). Run Starter prompt B only after the self-test passes on your machine.

**Starter prompt A: verify the built kit (no data, no API spend)**
```
Read SPEC.md in full. It is the only source of truth for this project; there is no prior chat history.
Rules: do not change anything listed under "Decided" in §2. Ask me before resolving anything listed under "Open". Use the "Proposed defaults" unless I say otherwise.
Task: the harness in §11 is already built. Create a virtualenv, install requirements.txt (plus pydicom), and run `python tests/test_pipeline.py`. Do not rewrite the harness; fix only what a failing check points to, and tell me what you changed. Then read §11.3 (build notes) and tell me anything you'd question.
```

**Fallback (markdown files only, no kit):** replace the Task line with: "Implement the harness in §11 and the self-test in §12 exactly as specified, using synthetic data and the mock model only. When the self-test passes, show me the test output, the mock report.md, and every place where you had to interpret the spec."

**Starter prompt B: get the real data (after A passes)**
```
Follow SPEC.md §13 Step 0. Use the Redivis Python client and the token in .env.
First only list what my CheXpert Plus access contains (tables, columns, row counts, file types) and answer the five checks in §13 Step 0. DATASET_ANALYSIS.md has background and SQL. Do not download images until I confirm.
```

**For the Claude app (not Code), to settle open decisions:** upload SPEC.md and ask: "Help me decide O1–O6 in §2. Keep the decisions log format."

---

## 1. Goal

**Question.** Given only the images of one chest X-ray study, how well does `claude-opus-5-5` detect five findings, compared with the radiologist reference standard?

**Output.** A blinded, repeatable "golden test". It is a fixed set of studies with a fixed prompt and a fixed scorer. Every run produces the same kind of report, and any two runs can be compared with a pass/fail regression verdict.

**Not in scope (v1):** report generation, localization or bounding boxes, CT (phase 2, §17), clinical use of any kind, and comparing other models. Other models can be added later just by changing the model name in the config.

---

## 2. Decisions log

### Decided (by Parthi; do not change without asking)
| Date | Decision |
|---|---|
| 2026-11-19 | Small-scale eval/bench study of Claude Opus 5.5's clinical performance on Stanford AIMI data hosted on Redivis (chest X-ray or CT). |
| 2026-11-19 | Execution via Claude Code (build and run). The Claude app is used for review and write-up. |
| 2026-11-19 | It must be a **blinded golden test**, **repeatable**, using the **simplest possible prompt**, and **fully implemented** as a harness, not just a document. |
| 2026-11-19 | Design from the **end result backwards**: the report in §3 is the target. |
| 2026-11-24 | Must be resumable from a different Claude account, which is why this file exists. |

### Proposed by Claude: Parthi went ahead on this basis but has not explicitly confirmed
| Item | Proposal |
|---|---|
| P1 | **Chest X-ray first** (CheXpert validation split, 200 studies). CT (Merlin) is phase 2. Reason: the CXR labels come from radiologists reading the images, the images are 2D, and published comparison numbers exist. Merlin labels come from reports, and turning 3D into 2D slices is a confound. |
| P2 | The report layout in §3. It was shown on 2026-11-19 and handoff happened before Parthi responded to it. |
| P3 | All statistical defaults in §8–§9 (bootstrap 1,000, seed 42, threshold 50, parse-failure gate 2%). |

### Open (ask Parthi)
| ID | Question | Notes |
|---|---|---|
| O1 | **Pass line.** "Worth a deeper POC if the lower bound of the average AUROC ≥ X and no primary finding has sensitivity < Y at threshold 50." What are X and Y? | Must be written down **before** the first real run. Setting it afterwards biases the decision. |
| O2 | Add a one-line "what I see" per finding to the model output? | Helps when reviewing misses, but lengthens the prompt and moves away from "simplest prompt". If yes, use `prompts/v1e.txt` (§6.2) as a separate prompt version. |
| O3 | Add a published-baseline column (from the original CheXpert paper) to the report? | The numbers have **not** been extracted yet. If yes, take them from the paper and record the table or figure number, plus whether they are validation-set or test-set numbers. |
| O4 | Use the CheXpert **test** split (500 studies) as a locked holdout? | The labels and images are public via Stanford AIMI CheXlocalize, not via CheXpert Plus. The images are not DICOM (format to check), so the holdout's rendering differs slightly from the validation set's. |
| O5 | Reasoning/effort setting for the model call. | Pick one setting from the current API docs, freeze it in `config.toml`, and record it. Changing it creates a new run identity. |
| O6 | License check outcome (§16). | Confirm that the data use agreement allows sending de-identified images to a third-party model API for non-commercial research. |
| O7 | Add a **reporting-radiologist arm** on the same 200 studies? | Score the model against labels from the original clinical report's **impression** (`impression_fixed.json`, one report per study). Optionally also score those report labels against the 3-radiologist consensus as a rough human-reader row. That row includes labeler noise, so it isn't a true reader study. Report text also helps when reviewing misses. |

---

## 3. Target output (the end result)

> **All numbers in this section are invented to show the layout. They are not results and not a prediction.**

Every run writes `runs/<run_id>/report.md` that looks like this:

```
# Golden test report: run 2026-11-24_v1_opus-5-5
Model claude-opus-5-5 (returned id: …) · Prompt v1 (sha256 3f9a…) · Golden set chexpert-valid-200 (lock 8c21…)
Status: VALID (G1 golden lock matches · G2 parse failures 1/200 = 0.5%, limit 2%)

Headline: mean AUROC across 5 primary findings 0.81 [95% CI 0.77–0.85]

| Finding               | Positive | AUROC [95% CI]    | Sens @50 [CI]    | Spec @50 [CI]    |
|-----------------------|----------|-------------------|------------------|------------------|
| Atelectasis           | 80/200   | 0.74 [0.67–0.81]  | 0.61 [0.50–0.71] | 0.79 [0.71–0.85] |
| Cardiomegaly          | 68/200   | 0.86 [0.81–0.91]  | …                | …                |
| Consolidation         | 33/200   | 0.79 [0.70–0.87]  | …                | …                |
| Edema                 | 45/200   | 0.83 [0.77–0.89]  | …                | …                |
| Pleural Effusion      | 67/200   | 0.88 [0.83–0.92]  | …                | …                |
| No Finding (secondary)| 25/200   | 0.80 [0.71–0.88]  | …                | …                |

Repeatability (first 50 cases × 3 repeats, from run 2026-11-24_v1_opus-5-5_rep3): mean |Δ probability| 6 points; same yes/no call 91%.
Tokens: 1.3M in / 0.5M out · estimated cost ≈ $15 (estimate from config prices)
Caveats: contamination possible · n=200 · non-commercial research use only · not for clinical use
```

Alongside it, `misses.csv` lists the top 10 false negatives and top 10 false positives for each finding, with an empty column for the radiologist:

| case_id | finding | reference | model_prob | images | source_study | reviewer_verdict |
|---|---|---|---|---|---|---|
| case_0137 | Consolidation | 1 | 8 | case_0137_1.png;case_0137_2.png | patient…/study… | *(reference right / model right / unclear)* |

When two runs are compared, `compare.py` writes `compare_vs_<runA>.md` into run B's folder and exits non-zero if the test fails:

| Finding | ΔAUROC (B − A) [95% CI] | Verdict |
|---|---|---|
| Edema | +0.04 [−0.01, +0.09] | no detectable change |
| Cardiomegaly | −0.06 [−0.10, −0.02] | **WORSE → test fails (exit 1)** |

**Reading guide.** AUROC is ranking ability independent of the cutoff (0.5 = chance). With n=200, differences of a few hundredths are often noise, so verdicts use confidence intervals, not point estimates. The misses table is where the clinical insight comes from.

---

## 4. Golden set

| Item | Definition |
|---|---|
| Images | The CheXpert **validation** split (`valid/…` paths) from Parthi's CheXpert Plus access on Redivis. **DICOM** preferred, rendered by our fixed recipe (§11.2). |
| Size | 200 studies / 234 images. |
| Reference standard | Majority of 3 board-certified radiologists who read the **images** (CheXpert paper). The label file is `valid.csv` from the original CheXpert v1.0, or `CheXpert/val_labels.csv` from Stanford AIMI **CheXlocalize**. Public docs don't show it inside CheXpert Plus, so get it from one of those two datasets if your access lacks it. |
| **Not a reference** | All CheXpert Plus label files (CheXpert labeler, CheXbert, RadGraph-XL) are machine-extracted from report text. **Never use `report_fixed.json`**: rows appear misaligned (GitHub issue #16, open as of 2026-11-24). Report-derived labels may only be used in the optional reporting-radiologist arm (O7). |
| Optional holdout | The CheXpert **test** split: 500 studies / 668 images, majority of 5 radiologists. Images and `test_labels.csv` are public via CheXlocalize. They are **not** in CheXpert Plus, have no reports, and their format (likely JPG) needs checking (O4). Never use it for prompt iteration. |
| Primary findings | Atelectasis, Cardiomegaly, Consolidation, Edema, Pleural Effusion (the published CheXpert evaluation set). |
| Secondary finding | No Finding. |
| Unit of analysis | The **study**: all views of one study in one call, frontal first. |
| Freezing | `prepare_golden` writes images, a manifest, sealed labels and `golden_lock.json`, which holds SHA-256 hashes of every image, the manifest, the labels and the prep parameters. The golden folder is never edited. A changed set is a new golden set with a new name. |
| Label guard | Any label that is −1 (uncertain) or blank **aborts** preparation. That pattern means report-derived labels, not the radiologist reference. |

---

## 5. Blinding rules

- **B1.** The model sees pixels and the fixed request text only: no reports, demographics, file names, dataset name, study IDs or labels.
- **B2.** Images are re-encoded to plain 8-bit PNG (all metadata dropped), renamed to opaque IDs (`case_0001_1.png`), and case order is shuffled with a fixed seed.
- **B3.** Labels and the source map live only in `golden/_sealed/`, and only `score.py` and `compare.py` read them. `run_eval.py` reads only `golden/manifest.csv`, `golden/golden_lock.json` and `golden/images/`. A test fails if `run_eval.py` or `mock_model.py` contains the string `_sealed` or `labels`.
- **B4.** One API call per study. There is no conversation history and no shared context across cases.
- **B5.** The request never names CheXpert, Stanford or any dataset, to avoid priming the model to recall the benchmark.
- **B6.** Prompt changes are made only against the validation split. A holdout is run once per frozen prompt.
- **B7.** `run_eval --show-request` prints the exact request for one case, with base64 truncated, so a human can audit what the model sees. Do this before the first paid run.

---

## 6. Model call

### 6.1 Request format (fixed)
- Model: `claude-opus-5-5`. `max_tokens` and any extra parameters (reasoning/effort, O5) come from `config.toml` and are recorded verbatim in each run.
- Message: a single `user` turn. For each image *i*, in order, a text block `Image i (frontal):` or `Image i (lateral):` followed by the image block (base64 PNG). Then **one** text block containing the prompt file's text exactly.
- Images go **before** the prompt text.
- Image size: resized during preparation so the long edge is at most 2,576 px and ⌈w/28⌉·⌈h/28⌉ is at most 4,784 visual tokens. This is the documented limit for Opus 4.7 and later; confirm it for 5.5 (§15).
- Retries: the SDK retries API errors (`max_retries = 5`). Unparseable output is retried once with an identical request. If it still fails, it is recorded as a parse failure.

### 6.2 Prompt v1 (`prompts/v1.txt`, verbatim, no placeholders)
```
These images are one chest X-ray study. Each image is labeled with its view.

For each finding below, give the probability (0-100) that it is present, based only on the images.

- Atelectasis
- Cardiomegaly
- Consolidation
- Edema
- Pleural Effusion
- No Finding (no abnormality; support devices alone still count as No Finding)

Reply with only this JSON, using whole numbers from 0 to 100:
{"Atelectasis": _, "Cardiomegaly": _, "Consolidation": _, "Edema": _, "Pleural Effusion": _, "No Finding": _}
```

**Only if O2 = yes**, add `prompts/v1e.txt`. It is identical except for the last two lines:
```
Reply with only this JSON. "p" is a whole number from 0 to 100; "seen" is at most 15 words:
{"Atelectasis": {"p": _, "seen": "_"}, "Cardiomegaly": {"p": _, "seen": "_"}, "Consolidation": {"p": _, "seen": "_"}, "Edema": {"p": _, "seen": "_"}, "Pleural Effusion": {"p": _, "seen": "_"}, "No Finding": {"p": _, "seen": "_"}}
```

**Prompt versioning rule:** never edit a prompt file once it has been used in a run. Changes go in a new file (`v2.txt`). The prompt's SHA-256 is part of the run identity.

### 6.3 Output contract and parsing
1. Join all `text` content blocks; ignore thinking blocks.
2. Find the first `{` from which `json.JSONDecoder().raw_decode` yields a dict.
3. Normalize keys: lower-case, `_` replaced by a space, trimmed. All 6 findings must be present.
4. Values must be numbers (not bool) in [0, 100]. For v1e, use the `p` field and store `seen` alongside it.
5. Anything else is a parse failure. Never fall back to an imputed value.

---

## 7. Data flow and files

```
data/ (raw from Redivis, never sent anywhere)
  └─ prepare_golden ─► golden/
                        images/case_0001_1.png …
                        manifest.csv            case_id, images, views, sha256  (";"-joined, no other columns allowed)
                        golden_lock.json        name, harness_version, n_cases, n_images, prep params,
                                                manifest_sha256, labels_sha256, images_sha256, lock_id
                        _sealed/labels.csv      case_id + 6 findings (0/1)
                        _sealed/source_map.csv  case_id, original study id, original image paths
                        _sealed/summary.json    prevalence per finding
  └─ run_eval ─► runs/<run_id>/
                   run_config.json   identity hash, model settings, prompt sha, golden lock_id, limit, repeats,
                                     harness/SDK/Python versions, start time
                   responses.jsonl   one line per attempt outcome (schema below)
                   predictions.csv   case_id, repeat, parse_ok, 6 probabilities
                   batches.json      batch mode only: batch ids, custom ids, collected flag
  └─ score   ─► scores.json, report.md, misses.csv
  └─ compare ─► compare_vs_<runA>.md (in run B)
```

`lock_id` is the SHA-256 of the lock contents **excluding** the creation time, so identical content always gives the same lock_id.

`responses.jsonl` has one line per (case, repeat) call outcome, including its parse retries. Resumed retries append new lines. Fields: `case_id, repeat, mode (sync|batch|mock), attempts, parse_ok, probs{}, seen{} (v1e only), raw_text, prior_raw[] (texts of failed attempts), model (as returned), stop_reason, usage{input_tokens, output_tokens}, latency_s, error, ts_utc`.

**Run identity** is the SHA-256 of: model name, `max_tokens`, extra params, prompt SHA-256, golden lock_id, `parse_retries`, `limit`, `repeats` and mock settings. Concurrency and sync/batch mode are **not** part of it. Resuming into a run folder with a different identity is refused.

---

## 8. Metrics (exact definitions)

- **Primary analysis set:** repeat 0, cases with parsed output. Parse failures are excluded and counted.
- **AUROC:** Mann–Whitney U using average ranks for ties, implemented in numpy (no sklearn).
- **95% CI:** percentile bootstrap, B = 1,000, seed 42, resampling cases with replacement. A resample is skipped for a finding if it lacks either class. The mean-AUROC CI uses the same resample indices across findings.
- **Sensitivity and specificity at threshold 50:** probability ≥ 50 counts as positive. Wilson 95% CI.
- **Consistency** (when repeats > 1): over cases where all repeats parsed, report the mean |p_r − p_0| per finding and the % agreement of the yes/no call with repeat 0.
- **Cost:** token totals × config prices. Batch-mode records get the batch discount. Always labelled an estimate.
- **Compare:** paired bootstrap on cases parsed in both runs, same B and seed. ΔAUROC = B − A per finding and for the mean.

---

## 9. Validity gates

| Gate | Rule | Effect |
|---|---|---|
| G1 | The run's golden lock_id equals the current `golden_lock.json` lock_id. | Otherwise `score` refuses (exit 2). |
| G2 | Parse failures ≤ 2% of repeat-0 calls, after the retry. | Otherwise the report is marked INVALID (exit 2). |
| G3 | In compare, a finding is **WORSE** if the whole 95% CI of ΔAUROC is below 0, **BETTER** if it is entirely above 0, and otherwise "no detectable change". | If any primary finding is WORSE: exit 1 (test fails). |
| G4 | Both runs in a compare share the same golden lock_id. | Otherwise compare refuses (exit 2). |

---

## 10. Repeatability rules

- The golden set, prompt files and scorer are versioned and never edited in place.
- Every run folder is self-contained and enough to rebuild the report.
- Model outputs are not bit-for-bit reproducible. Repeatability here means the same inputs and settings, plus **measured** run-to-run variation from the consistency check (first 50 cases × 3 repeats).
- Record the model ID the API returns. If it changes between runs, the reports must show it.

---

## 11. Harness to build

**Stack:** Python ≥ 3.11 (`tomllib`). Required: `anthropic`, `numpy`, `pillow`. Optional: `pydicom` (DICOM input), `redivis` (Step 0), `pandas` (Step 0 only). The harness uses no other third-party packages.

```
chexpert-golden-eval/
  SPEC.md  README.md  requirements.txt  config.toml  .env.example  .gitignore (data/ golden/ runs/ .env)
  prompts/v1.txt
  harness/
    common.py          findings lists, csv/json io, sha256, config + .env loading (no python-dotenv)
    imaging.py         load → 8-bit grayscale → resize to budget → PNG
    prepare_golden.py  builds golden/ (§4, §7)
    run_eval.py        blinded runner: sync, batch, mock; resumable
    mock_model.py      test double: fake Messages + Batches API
    score.py           metrics, gates, report.md, misses.csv
    compare.py         paired comparison, regression gate
    fetch_redivis.py   Step 0 helper (Redivis API calls unverified; see §13)
  tests/test_pipeline.py   self-test, plain python, no pytest needed
```

### 11.1 `config.toml` (proposed defaults)
```toml
[model]
name = "claude-opus-5-5"
max_tokens = 16000

[model.extra]
# Extra Messages API params passed through verbatim (reasoning/effort: decision O5).
# Empty = model defaults. Whatever is set here is recorded in run_config.json.

[run]
prompt = "prompts/v1.txt"
concurrency = 4
parse_retries = 1
api_max_retries = 5
batch_max_mb = 100          # conservative chunk size per batch submission

[score]
threshold = 50
bootstrap = 1000
seed = 42
max_parse_failure_rate = 0.02
misses_per_finding = 10

[cost]                      # USD per million tokens. ESTIMATES: check current pricing before relying on them
input_per_mtok = 4.0
output_per_mtok = 20.0
batch_discount = 0.5

[baseline]                  # O3: fill only from the CheXpert paper, with table/figure reference; leave empty otherwise
```

### 11.2 Module contracts

**`imaging.py`**
- Load: PNG/JPG through Pillow. 16-bit modes (`I;16*`, `I`, `F`) are min–max scaled to 8-bit. DICOM is detected by suffix or the `DICM` magic at byte 128, then: modality LUT → VOI LUT → invert if `MONOCHROME1` → min–max to 8-bit.
- `fit_size(w, h, max_edge, max_tokens, patch=28)`: never upscale. Scale until the long edge ≤ `max_edge` and ⌈w/28⌉·⌈h/28⌉ ≤ `max_tokens`.
- Resize with LANCZOS and save as PNG with no metadata. Refuse any image whose base64 size is over 9.5 MB.

**`prepare_golden.py`**
- CLI: `--labels CSV --image-root DIR --out golden --name chexpert-valid-200 --path-col Path --view-col "Frontal/Lateral" --study-regex "(patient\d+/study\d+)" --seed 42 --max-long-edge 2576 --max-visual-tokens 4784 [--force]`
- Input contract: a CSV in CheXpert `valid.csv` / CheXlocalize `val_labels.csv` format (one row per image, study-level labels repeated on each row) and an image root holding the CheXpert Plus files.
- Image lookup: match each label row to an image by its **path stem** `<split>/patientN/studyM/viewK_<frontal|lateral>`, ignoring any leading folder (for example `CheXpert-v1.0/`) and the file extension. Extension preference is configurable (`--ext-order .dcm,.png,.jpg`, default in that order). Each label row must match **exactly one** image; zero or several matches abort.
- Join check: the counts of distinct studies and images must equal the label file's counts (expect 200 / 234 for validation). Otherwise abort.
- Abort on: −1 or blank labels (guard, §4); a study whose rows disagree on labels; any missing image; an existing non-empty output folder unless `--force`.
- View: from `--view-col`, otherwise inferred from "frontal"/"lateral" in the filename, otherwise "unknown". Frontal comes first, then filename order.
- Shuffle study order with the seed, then assign `case_0001…`. Write everything in §7, and print counts and prevalence to the console.

**`run_eval.py`**
- CLI: `--golden golden --config config.toml [--run-dir DIR] [--limit N] [--repeats R] [--mode sync|batch] [--mock --mock-seed S --mock-noise SD --mock-fail-rate F] [--show-request]`
- Startup: load `.env` and config; verify the manifest columns are exactly `case_id, images, views, sha256`; verify the manifest SHA and every image SHA against the lock; compute the identity; create or resume the run folder.
- `--limit N` takes the first N cases of the (already shuffled) manifest.
- Resume: skip any (case, repeat) that already has a `parse_ok` record. Failed ones are retried.
- Sync: thread pool (`concurrency`); append to `responses.jsonl` under a lock.
- Batch: if there are uncollected batches in `batches.json`, poll and collect them; otherwise submit the remaining work in chunks of at most `batch_max_mb`, with `custom_id = <case_id>-r<repeat>`. Poll until `processing_status == "ended"`, then collect results by custom_id. Batch has no automatic parse retry. Afterwards it prints "N failed → rerun with `--mode sync` on the same run dir".
- Always rebuild `predictions.csv` at the end. For each (case, repeat), the last `parse_ok` record wins.
- `--show-request`: print the request for the first case with base64 truncated, then exit.

**`mock_model.py`** (test double; never used for real results)
- `MockClient().messages.create(**params)` returns an object with `.content` (text blocks), `.usage`, `.model = "mock"`, `.stop_reason` and `.id`. `MockClient().messages.batches` provides `create`, `retrieve` (status already "ended") and `results`.
- It decodes the **first frontal image** and reads the synthetic stripe encoding (§12) to produce probabilities, plus seeded noise that varies by call. This proves that the right images reach the right case without the mock ever seeing labels.
- `--mock-fail-rate` returns garbled text on a seeded fraction of calls, to exercise retries and the gates.

**`score.py`**: `python -m harness.score runs/<id> [--consistency-run runs/<rep_id>]` → applies gates G1 and G2, then writes `scores.json`, `report.md` (§3 layout) and `misses.csv` (with `source_study` from the sealed map). The repeatability section comes from the run itself if it has repeats > 1; otherwise it comes from `--consistency-run`. That run must share the golden lock_id, prompt SHA and model settings, or the section is refused and marked "not comparable". The report names the run the numbers came from. Exit codes: 0 valid, 2 invalid.

**`compare.py`**: `python -m harness.compare runs/<A> runs/<B>` → applies G4 and G3, writes `compare_vs_<A>.md` into B and prints it. Exit codes: 0 pass, 1 WORSE, 2 refused.

**`fetch_redivis.py`** (Step 0 helper): subcommands `list` (tables, columns, row counts), `export-table TABLE --out CSV [--filter-col C --contains S]` and `download-files --index CSV --file-id-col C --out DIR`. **The Redivis client calls are unverified.** Build them against the current Redivis Python docs and test `list` first.

### 11.3 Build notes (2026-11-24): where the spec was interpreted

Built and self-tested in a cloud workspace with Python 3.13, numpy 2.5 and Pillow 12. Neither the `anthropic` SDK nor `pydicom` was installed there, and Redivis wasn't reachable.

- **Untested paths:** the real API calls (sync and batch) were exercised only through a stand-in module with the SDK's interface, not the real SDK. DICOM loading is untested because `pydicom` was absent. `fetch_redivis.py` is untested. All three should be checked on the first real smoke run (Step 3).
- **Join check:** besides exact per-row matching, `prepare_golden` takes optional `--expect-studies` / `--expect-images` and aborts on a mismatch. The README passes 200 / 234.
- **Study ID:** `<split>/patientN/studyM`, from the path stem plus `--study-regex`.
- **`--force`** deletes the existing golden folder and rebuilds it. A golden set is never edited in place.
- **Synthetic noise:** "noise SD ≈ 40" is applied to each stripe's level (plus small pixel noise of SD 5), so mock AUROC lands around 0.92–0.98 instead of 1.0.
- **misses.csv:** lists only real errors at the threshold (false negatives below 50, false positives at 50 or above), most confident first, up to 10 per finding and type.
- **Cost:** sums tokens over every call, including parse retries and failed attempts; batch-mode records get the batch discount.
- **Scoring settings:** taken from the run's own config snapshot, so scoring is reproducible; `--config` overrides them.
- **Parsing:** extra keys in the model's JSON are ignored; all 6 findings must be present.
- **Sync memory:** requests (with base64 images) are built inside worker threads, so only `concurrency` of them are in memory at once.
- **Baseline column (O3):** read from `[baseline]` in config.toml as `Finding = 0.xx` plus a `source` string. It is shown only if filled in.
- **Extra outputs:** `run_config.json` also stores the prompt text, the full config and the case list, so each run folder is self-contained.

---

## 12. Self-test (must pass before any paid run)

`python tests/test_pipeline.py` creates a temporary folder and checks:

1. **Synthetic dataset:** 60 studies in CheXpert `valid.csv` format. Each study has a frontal image and, about half the time, a lateral one (256×320 grayscale). Each frontal image has 5 horizontal stripes, one per primary finding. A stripe's intensity is about 170 when the finding is positive and about 70 when negative, with noise of SD ≈ 40. Lateral images are uniform. No Finding = 1 when none of the 5 primary findings is positive.
2. **prepare:** output exists; manifest has only the allowed columns; no `patient`/`study` strings in the manifest; image count and hashes are correct.
3. **Label guard:** a copy of the CSV containing one −1 makes prepare abort; a blank label also aborts.
4. **Blinding static check:** neither `run_eval.py` nor `mock_model.py` contains `_sealed` or `labels`.
5. **Mock run (sync, 2 repeats, fail rate 0.1):** every (case, repeat) has a record; retries happened; leftover failures are counted.
6. **Resume:** a second invocation makes zero new calls when nothing failed. Test with fail rate 0.
7. **Tamper:** changing one byte of one golden image makes `run_eval` abort.
8. **score:** primary-finding AUROC > 0.9 on the stripe-encoded findings (this proves case↔image routing); the report renders; G2 triggers when the fail rate is forced high.
9. **AUROC unit test:** matches a brute-force pairwise computation, including ties, to 1e-9.
10. **Resize unit test:** 2320×2828 input gives long edge ≤ 2576 and tokens ≤ 4784; small images stay unchanged.
11. **Batch path:** mock batches produce the same records schema as sync.
12. **compare:** a run against itself passes (exit 0); a run against a deliberately degraded mock run (noise raised) exits 1.
13. **Path-stem matching:** label paths like `CheXpert-v1.0/valid/patient00001/study1/view1_frontal.jpg` match `valid/patient00001/study1/view1_frontal.dcm` (and `.png`) using the extension order. A missing match aborts, two images with the same stem and extension abort, and a study/image count mismatch aborts.

**Acceptance for "harness done":** all 13 checks pass; then (after Step 0) a 5-study real smoke run is audited with `--show-request` and produces a report in the §3 layout.

**Status 2026-11-24:** all 13 checks pass (31 assertions, about 6 seconds). The mock outputs are in `tests/output/`: synthetic data and mock model, so they are **not results**. The real smoke run is still to do.

---

## 13. Runbook

| Step | Action | Command or prompt |
|---|---|---|
| 0 | **Data.** In Parthi's Redivis CheXpert Plus access ([dataset page](https://stanford.redivis.com/datasets/5yyj-1a9f6ap0x)), answer five checks. Known names from a third-party repo: `df_chexpert_plus_240401`, `DICOM_train`, a "CheXpert Labels" file index. (a) Which DICOM/PNG index holds `valid/` (expect 234 images / 200 studies). (b) Whether any file holds the **radiologist** valid labels; expect not, in which case get `val_labels.csv` from CheXlocalize or `valid.csv` from the original CheXpert. (c) What the PNG and "compressed" PNG sets are (bit depth, size, processing). (d) Version and changelog, and whether `report_fixed.json` has been corrected. (e) The data use agreement wording on third-party API processing (O6). Then put the validation DICOMs under `data/images/` (keeping their `valid/patient…/study…/view…` paths) and the radiologist labels at `data/valid_labels.csv`. SQL checks: DATASET_ANALYSIS.md §9. | Starter prompt B; `python -m harness.fetch_redivis list` |
| 1 | Build the golden set | `python -m harness.prepare_golden --labels data/valid_labels.csv --image-root data/images --out golden` |
| 2 | Audit blinding | `python -m harness.run_eval --show-request` |
| 3 | Smoke run, 5 studies | `python -m harness.run_eval --limit 5` then `python -m harness.score runs/<id>` |
| 4 | Write down the pass line (O1) **before** the full run | edit §2 |
| 5 | Full dev run | `python -m harness.run_eval --mode batch` (then `--mode sync --run-dir runs/<id>` to retry failures) |
| 6 | Consistency (separate run) | `python -m harness.run_eval --limit 50 --repeats 3` |
| 7 | Score, then radiologist review of `misses.csv` | `python -m harness.score runs/<id> --consistency-run runs/<rep_id>` |
| 8 | Iterate (only if needed): new prompt file, new run, compare | `python -m harness.compare runs/<A> runs/<B>` |
| 9 | Freeze, then holdout once (if O4) | prepare a second golden set from the test split; run once |

---

## 14. Cost and time (estimate)

- **Per study:** about 1–2 images × ≤ 4,784 tokens plus ~300 prompt tokens, so roughly 6k input tokens. Output is ~100 tokens without reasoning and up to ~3k with reasoning. At $4 / $20 per million tokens, that is **≈ $0.03–0.09 per study**.
- **Full dev run (200 studies):** ≈ $5–18 standard, about half that via batch. The consistency check adds about 50%.
- **Time:** the harness plus self-test should take a few hours with Claude Code. A full run takes minutes in sync mode, or up to about a day in batch mode.
- **Caveat:** the prices come from third-party pages (§15), and reasoning length drives most of the cost. Check against the smoke run's actual token usage.

---

## 15. Claims, evidence, status

| Claim | Evidence | Status (as of 2026-11-24) |
|---|---|---|
| Valid split = 200 studies; reference = consensus of 3 board-certified radiologists who annotated the radiographs | CheXpert paper, arXiv:1901.07031 (2019) | Verified from source |
| Test split = 500 studies / 668 images; 8 radiologists annotated, majority of 5 is ground truth | Same paper; arXiv:2107.10230 | Verified |
| CheXlocalize releases CheXpert validation images (234) and test images (668) with `val_labels.csv` and `test_labels.csv` | github.com/rajpurkarlab/cheXlocalize README (accessed 2026-11-24) | Verified that the files exist. How the CSVs were built isn't stated there; test image format unverified |
| CheXpert Plus includes the validation split (with reports) but not the test split | RadEval arXiv:2509.18030; arXiv:2609.19093 | Verified by third-party use. Exact Redivis counts unverified |
| All CheXpert Plus 14-finding labels are machine-extracted from reports. Findings-based CheXbert scores F1 0.44 against an image-based test set | CheXpert Plus paper | Verified |
| Reports are original clinical reports; human review covered PHI only; no clinical verification described | CheXpert Plus paper | Verified (absence of clinical verification inferred from the paper's description) |
| `report_fixed.json` rows appear shifted against `path_to_image` | GitHub issue #16 (opened 2026-11-19, open, no maintainer reply) | Reported by a third party with detailed evidence; not confirmed by the maintainers |
| Some studies have near-duplicate reports differing only in PHI surrogates | GitHub issues #4 (maintainer confirmed) and #13 | Verified |
| Reports labeled by radiologists disagree significantly with images labeled by radiologists | VisualCheXbert, arXiv:2102.11467 | Verified |
| The 5-finding evaluation protocol (Atelectasis, Cardiomegaly, Consolidation, Edema, Pleural Effusion) | arXiv:1911.06475, describing the CheXpert protocol | Verified (secondary source restating the original) |
| CheXpert Plus may not be used commercially; research only; no distribution or reproduction | CheXpert Plus paper, arXiv:2405.19538 (2024) | Verified from paper. **Current agreement text not read** |
| AIMI datasets are free for non-commercial research; commercial use needs a paid AIMI license | aimi.stanford.edu/shared-datasets and /datasets-commercial-use (accessed 2026-11-19) | Verified |
| CheXpert Plus canonical URL on Redivis | aimi.stanford.edu/datasets/chexpert-plus (accessed 2026-11-19) | Verified |
| Parthi has approved access to CheXpert Plus and the Merlin Abdominal CT dataset on Redivis, and can create a Redivis API token | Stated by Parthi (Oct 2026) | Stated, not independently checked |
| Redivis names `df_chexpert_plus_240401`, `DICOM_train`, "CheXpert Labels" index | Third-party repo SChapmanL/prototipo_propuesta_fl (README as of 2026-11-18) | Third-party; the validation-split index name and PNG sets are **unverified**: Step 0 |
| Claude API: up to 600 images per request for models without a 200k context window (100 for 200k models); stricter per-image limit (2000 px) when a request has more than 20 images; 32 MB request size limit | platform.claude.com vision docs (page about 162 days old when accessed 2026-11-19) | Verified from docs; **page may be stale** |
| Opus 4.7 and later: ≤ 2,576 px long edge, ≤ 4,784 visual tokens, token cost ⌈w/28⌉×⌈h/28⌉ | platform.claude.com computer-use and coordinates docs (computer-use page about 120 days old when accessed) | Verified for "4.7 and later". **That Opus 5.5 is in this tier is inferred, not stated** |
| Opus 5.5 pricing $4 / $20 per MTok; batch $2 / $10 | Third-party pages (cloudzero.com; developersdigest.tech, citing platform.claude.com on 2026-10-09) | **Unverified on Anthropic's pricing page** |
| Claude Code is built into Claude Desktop (Code tab); needs a paid plan | code.claude.com desktop quickstart (page about 128 days old when accessed); support.claude.com FAQ | Verified from docs |
| Subscription and API usage are billed separately | thepricer.org (third-party) | Reasonable but third-party |
| Message Batches API size limits | none | **Unverified**: harness chunks at 100 MB to be safe |
| Merlin: 25,494 scans / 18,317 patients; test split 5,137 scans; 30-finding classification labels released for 5,082 of 5,125 released test scans | aimi.stanford.edu/data; NV-Reason-CT paper, arXiv:2609.27511 | AIMI figure verified; split and label counts come from a **secondary paper**; verify in Redivis |

---

## 16. Limitations and caveats (include in any write-up)

- **Contamination:** CheXpert has been public since 2019, so training-data exposure can't be ruled out. Treat results as a best case and don't generalize to unseen institutions. A later replication on a private de-identified set would address this.
- **Sample size:** n = 200, and low-prevalence findings (for example Consolidation) have wide intervals. Don't headline small differences.
- **Label semantics:** CheXpert definitions (for example what counts as Edema or No Finding) may not match the model's reading of the terms. Look for systematic disagreement in the misses review.
- **Resolution:** images are downscaled to the model's visual budget, so subtle findings may suffer. That is part of what's being measured, and it is recorded.
- **License:** non-commercial research use only, with no redistribution of the data. If results will inform a company's commercial vendor or product decisions, get an AIMI commercial license or legal sign-off first. Confirm that sending de-identified images to a model API is allowed (O6).
- **Not for clinical use.** This is a research benchmark.

---

## 17. Phase 2 sketch: CT (Merlin), not designed yet

Use the same harness pattern with a new golden set. The differences to design:
- **Reference labels are report-derived** (the released 30-finding labels), so this is a weaker reference standard than radiologists reading the images. Say so in the report.
- **3D → 2D conversion is a design choice that affects the result:** for example, axial slices at a fixed spacing with a soft-tissue window, sent as many images per call (the API allows up to 600 per request for 1M-context models, with stricter per-image size above 20 images). Freeze the rendering recipe in the golden lock.
- Start with 3–5 findings that are visible on axial slices and present in the released label file. Check the actual label list before choosing.

---

## 18. Sources (accessed 2026-11-19 unless noted)

- CheXpert paper: https://arxiv.org/abs/1901.07031
- CheXpert evaluation protocol restated: https://arxiv.org/pdf/1911.06475
- CheXpert Plus paper: https://arxiv.org/abs/2405.19538
- AIMI CheXpert Plus page: https://aimi.stanford.edu/datasets/chexpert-plus
- AIMI shared datasets (non-commercial terms): https://aimi.stanford.edu/shared-datasets
- AIMI commercial licensing: https://aimi.stanford.edu/datasets-commercial-use
- Merlin paper: https://arxiv.org/abs/2406.06512 · NV-Reason-CT (Merlin split/label counts): https://arxiv.org/pdf/2609.27511
- Claude vision docs: https://platform.claude.com/docs/en/build-with-claude/vision
- Claude image token budget (Opus 4.7+): https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool and https://platform.claude.com/docs/en/build-with-claude/vision-coordinates
- Claude Code desktop quickstart: https://code.claude.com/docs/en/desktop-quickstart
- Opus 5.5 pricing (third-party): https://www.cloudzero.com/blog/claude-opus-5-pricing/ · https://www.developersdigest.tech/models/claude-opus-5-5
- Added in 1.1 (accessed 2026-11-24): CheXpert Plus GitHub https://github.com/Stanford-AIMI/chexpert-plus and issues #4, #9, #13, #16 · CheXlocalize https://github.com/rajpurkarlab/cheXlocalize · CheXpert test set details https://arxiv.org/pdf/2107.10230 · VisualCheXbert https://arxiv.org/abs/2102.11467 · RadEval https://arxiv.org/abs/2509.18030 · Third-party Redivis downloader https://github.com/SChapmanL/prototipo_propuesta_fl
- Full dataset analysis: DATASET_ANALYSIS.md
