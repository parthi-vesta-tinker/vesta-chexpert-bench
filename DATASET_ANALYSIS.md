# CheXpert Plus on Stanford Redivis: Dataset Analysis for the Golden Test

| | |
|---|---|
| As of | 2026-11-24 |
| Dataset | CheXpert Plus, https://stanford.redivis.com/datasets/5yyj-1a9f6ap0x |
| Method | Public sources only: the CheXpert Plus paper, Stanford AIMI pages, the official GitHub repo and its issues, papers that used the dataset, and one third-party repo that downloads it from Redivis. The Redivis pages show only summary metadata without a sign-in. **Your logged-in view was not accessed**, so everything marked **[verify]** needs a check there (§9). |
| Companion to | SPEC.md (v1.2) |

---

## 1. Bottom line

1. **The reports are real but not "golden".** They are the original clinical reports written by Stanford radiologists during care (2002–2017), after de-identification. Human review covered PHI removal only; nobody verified or corrected the clinical content. Each report is a single radiologist's reading made with clinical context and prior studies. That makes it a good "what the reporting radiologist said" reference, not an image-level ground truth.
2. **The CheXpert Plus labels are not golden either.** All 14-finding labels in CheXpert Plus are **extracted from the reports automatically** (CheXpert labeler, CheXbert), and RadGraph-XL annotations are model output. Their accuracy against image-based labels is weak for findings-based labels (F1 0.44, per the authors).
3. **One label file is currently broken:** `report_fixed.json` appears row-shifted against `path_to_image` (GitHub issue #16, open, opened 2026-11-19, no maintainer response). **Do not use it.** Also, some studies have several near-duplicate reports that differ only in the substituted PHI, and their labels can differ (issues #4 and #13).
4. **The golden labels exist, but in a different dataset.** The CheXpert **validation** set (200 studies, majority of 3 board-certified radiologists who read the images) and **test** set (500 studies / 668 images, majority of 5) carry image-based expert labels. Those label files come with the original CheXpert release (validation) and with **Stanford AIMI's CheXlocalize** release (`val_labels.csv`, `test_labels.csv`). Public documentation does not show them inside CheXpert Plus **[verify]**.
5. **Recommended design:** golden test images come from the CheXpert Plus **validation** split (DICOM, rendered by our own fixed recipe). The golden reference is the **3-radiologist image labels**, joined by path. The same 200 studies' **reports** are an optional second reference ("does the model agree with the reporting radiologist?"). The train split's report-derived labels are only for a large-scale **silver** check, never the golden test.

---

## 2. Inventory

| Component | What it is | Counts (source) | Format | Status |
|---|---|---|---|---|
| Images | Chest X-rays from Stanford Health Care, 2002–2017 | 223,228 images in the paper text; 223,462 image–report pairs on the AIMI/Redivis pages and in paper Table 1. The discrepancy is unexplained. | **DICOM** (47 metadata elements per image; paper says pixel data identical to CheXpert 1.0) and **PNG** | Verified (paper, AIMI). DICOM vs PNG processing details: **[verify]** |
| "Compressed" PNG variant | What you saw on Redivis | Not documented publicly | — | **[verify]** what it is: downsampled? JPEG-compressed? 8-bit? |
| Reports | Original clinical reports, de-identified, parsed into up to 11 sections | 187,711 studies; Findings present in 47,328 reports, Impression in 187,575 | Columns in `df_chexpert_plus_240401` (for example `section_findings`, `section_impression`) | Verified (paper, GitHub) |
| Report-derived labels | CheXpert labeler and CheXbert output for 14 findings, run on different report sections | One row per image (`path_to_image` key) | JSON Lines, for example `impression_fixed.json`, `findings_fixed.json`, `report_fixed.json` in the "CheXpert Labels" file index | Verified to exist; **quality caveats in §5** |
| RadGraph-XL | Entity/relation annotations from a pretrained model, on the Findings and Impression sections | — | JSON | Model output, not human |
| Demographics | Age, sex, race, ethnicity, insurance type, BMI, deceased status, interpreter need | 8 fields (insurance as of Feb 2024) | Table | Verified (paper) |
| Prior-study linkage | `patient_report_date_order` | — | Column | Verified (paper) |
| Splits | Train and **validation** (CheXpert's 200-study valid set is included, with reports). **Test is not in CheXpert Plus.** | Validation: RadEval reports "74 studies with Findings and 234 with Impression". The 234 likely counts image rows (the validation set has 234 images in 200 studies). | Path prefix `train/…`, `valid/…` | Valid included: verified by third-party use. Exact Redivis counts: **[verify]** |

Redivis table and index names seen in a third-party repo that downloads from this dataset: `df_chexpert_plus_240401`, `DICOM_train`, and a "CheXpert Labels" file index that contains `report_fixed.json`. Other names (a valid DICOM index, PNG indexes, demographics) are **[verify]**.

---

## 3. Provenance and trust tiers

| Tier | Data | Who produced it | Use in this project |
|---|---|---|---|
| **Gold** (image-based expert reference) | CheXpert **validation** labels (200 studies) and **test** labels (500 studies) | Board-certified radiologists reading the **images**: majority of 3 (valid), majority of 5 of 8 annotators (test) | **Primary reference for the golden test** |
| **Real, unverified** | Clinical reports (Findings, Impression, etc.) | One reporting radiologist in clinical practice, with history and priors | Secondary reference on the same 200 studies; report-generation tasks |
| **Silver** (automatic, noisy) | CheXbert / CheXpert-labeler labels; RadGraph-XL | NLP models run on report text | Large-scale screening only; never a golden reference |
| **Broken (currently)** | `report_fixed.json` | Same labelers, but rows appear misaligned | **Do not use** until fixed |

**Why reports ≠ image truth:** VisualCheXbert (Stanford, 2021) showed that radiologists labeling **reports** "significantly disagree" with radiologists labeling the corresponding **images**. Reports also contain things the image can't show (history, comparison statements like "unchanged", clinical judgment), and they leave out things the reader didn't mention.

---

## 4. Are the reports golden and verified?

**No, and they were not meant to be.**

- **What they are:** original clinical reports written by Stanford radiologists. The authors note that section names were used inconsistently, and that reports were chosen for detailed impressions.
- **What was verified:** de-identification only. The process: transformer-based PHI detection, then surrogate replacement ("hide in plain sight"), annotator review, and a board-certified radiologist checking the real-to-synthetic mappings. Of 853,878 PHI spans, 23 were fully missed and 841 partly missed by the model. The authors say the report structure wasn't altered. **No clinical verification or correction is described.**
- **Known artifacts:** about 11,303 rows where images of the same study carry slightly different report text. The maintainer confirmed the differences are PHI surrogates only and "the radiology content stays unchanged" (issue #4). Deduplicate to **one report per study**.
- **Fit for this project:** the reports are a valid "reporting radiologist" comparator, but only with these caveats: single reader, clinical context available to that reader, Findings often missing (Findings in about 25% of reports vs Impression in nearly all), and no adjudication.

---

## 5. Are the labels golden and verified?

**No.** Every 14-finding label in CheXpert Plus is machine-extracted from report text:

| Label source | How made | Reported accuracy (authors) | Known defects |
|---|---|---|---|
| CheXpert labeler | Rule-based NLP on reports: positive / negative / uncertain / not mentioned | — | Uncertain (−1) and blank values need a policy |
| CheXbert (findings, impression, full report, concatenations) | Transformer labeler, input capped at 512 tokens | Findings-based vs a 154-sample **image-based** test set: F1 **0.44**. Impression-based vs a 339-sample **report-based** test set: F1 **0.93**. | The authors warn report-derived labels may be unreliable for image classifiers |
| `report_fixed.json` | CheXbert on full report | — | **Rows appear shifted** against `path_to_image`: the lag grows to about 3,400 rows, there are about 3,673 skipped images, and the last 3,673 rows are blank. Kappa against `impression_fixed.json` is about 0 (Cardiomegaly 0.002, Effusion 0.031). A downstream project saw validation AUROC 0.51–0.57 with it versus 0.85–0.88 with `impression_fixed.json`. Issue #16, **open, no maintainer reply** as of 2026-11-24. |
| Duplicate reports per study | — | — | Labels can differ across a study's near-duplicate reports. The maintainer said to use the labels "with a grain of salt" (issue #13). |
| `section_impression.json` vs CSV | — | — | 223,292 vs 223,462 rows; the 170-row gap is unexplained (issue #9, unanswered) |

**Where the golden labels live:**
- **Validation:** majority vote of 3 board-certified radiologists who read the images. The file is `valid.csv` in the original CheXpert v1.0 download, and `CheXpert/val_labels.csv` in **CheXlocalize** (234 images, 200 patients).
- **Test:** 500 studies / 668 images; 8 radiologists annotated it and the majority of 5 is ground truth. The file is `CheXpert/test_labels.csv` plus the images in **CheXlocalize**. These images are **not** in CheXpert Plus, have no reports, and their format (likely JPG) is **[verify]**.

---

## 6. Images: DICOM vs PNG

- **DICOM:** the most faithful source, with full bit depth and metadata (view position, photometric interpretation, windowing). Recommended for the golden set; our harness renders it with a fixed, recorded recipe (modality LUT → VOI LUT → MONOCHROME1 inversion → 8-bit → resize).
- **Provided PNGs:** fine if their processing is documented. The paper says PNGs exist for pipeline convenience but doesn't give bit depth or windowing **[verify]**. Don't use the "compressed" variant for the golden test unless its processing is documented. Downscaling or lossy compression changes what's being measured.
- **Rendering matters:** the paper's appendix code converts DICOM to CheXpert-1.0-style JPG **with histogram equalization**, so CheXpert 1.0 JPGs look different from a plain DICOM window. Whatever you choose, freeze it in the golden lock and keep it identical across runs.
- **Size:** about 12.6 MB per DICOM on average (a third-party download of 800 frontal DICOMs totalled about 10.07 GB). The 234 validation images come to roughly 3 GB **[verify]**.

---

## 7. What this means for the golden test

| Option | Images | Reference | Verdict |
|---|---|---|---|
| **A. Golden (recommended)** | CheXpert Plus `valid/` DICOMs (200 studies / 234 images) | 3-radiologist image labels (`val_labels.csv` / `valid.csv`), joined on patient/study/view path | Use as the primary test |
| **B. Reporting-radiologist arm (optional)** | Same 200 studies | Labels from the **impression** (`impression_fixed.json`, one report per study), plus the report text for misses review | Adds a "single radiologist in clinical practice" comparator. You can also score the report-derived labels against the consensus, which gives a rough human-reader row, labeler noise included. |
| **C. Holdout** | CheXlocalize test images (668 / 500 studies) | 5-radiologist image labels (`test_labels.csv`) | Run once per frozen prompt. Images aren't DICOM **[verify format]**, so render them with the same final steps. |
| **D. Silver at scale** | Train split (thousands of studies) | `impression_fixed.json` | Only for "does it hold up at scale?"; noisy, contamination-prone; never golden |
| **Never** | — | `report_fixed.json`; findings-based labels as an image reference | — |

**Join check (must pass before building the golden set):** 200 distinct `patientXXXXX/studyY` IDs and 234 images, with every image in the label file matched to exactly one DICOM. Any mismatch stops the build.

---

## 8. Open questions this analysis raises

1. Does your CheXpert Plus access include the radiologist validation labels? If not, you need access to **CheXpert** (original) or **CheXlocalize**, both Stanford AIMI datasets. **[verify]**
2. What exactly is the "compressed" PNG set? **[verify]**
3. Is there a DICOM index for `valid/`, alongside `DICOM_train`? **[verify]**
4. Which Redivis version are you on, and has a corrected `report_fixed.json` been posted? **[verify]**

---

## 9. Checks to run in your Redivis view

**In the browser (5 minutes):**
- [ ] Tables tab: write down every table and file index name, its row count and its size.
- [ ] Find any table or file containing **radiologist** validation labels (`valid.csv` / `val_labels.csv`). Expect none in CheXpert Plus.
- [ ] Find the DICOM and PNG indexes for `valid/`. Open one PNG's details for bit depth and resolution, and the "compressed" set's description.
- [ ] Version / changelog: note the version and dates. Check whether `report_fixed.json` was replaced after 2026-03-05.
- [ ] The data use agreement: does it allow sending de-identified images to a third-party model API (non-commercial research)?

**SQL to run in Redivis** (BigQuery-style SQL as far as I know; adjust names to what you see):
```sql
-- 1. Split sizes in the main table
SELECT SPLIT(path_to_image, '/')[OFFSET(0)] AS split,
       COUNT(*) AS images,
       COUNT(DISTINCT REGEXP_EXTRACT(path_to_image, r'^\w+/(patient\d+/study\d+)')) AS studies
FROM df_chexpert_plus_240401
GROUP BY split;
-- expect valid ≈ 234 images / 200 studies

-- 2. Studies whose images carry different impression text (PHI-surrogate duplicates)
SELECT COUNT(*) AS studies_with_variants
FROM (
  SELECT REGEXP_EXTRACT(path_to_image, r'^(\w+/patient\d+/study\d+)') AS study,
         COUNT(DISTINCT section_impression) AS n
  FROM df_chexpert_plus_240401
  GROUP BY study
  HAVING n > 1
);

-- 3. Validation rows with/without a findings section
SELECT COUNTIF(section_findings IS NOT NULL) AS with_findings, COUNT(*) AS total
FROM df_chexpert_plus_240401
WHERE STARTS_WITH(path_to_image, 'valid/');
```

---

## 10. Sources and staleness

| Source | Used for | Date / age |
|---|---|---|
| CheXpert Plus paper, arXiv:2405.19538 v2 (Chambon, Delbrouck et al.) | Composition, reports, de-identification, labelers, accuracy, limitations | 2024; v2 HTML |
| AIMI CheXpert Plus page; AIMI Azure listing (file explorer: DICOM, PNG, `df_chexpert_plus_240401.csv` 405.65 MB, `chexbert_labels.zip` 6.26 MB, `radgraph-XL-annotations.zip` 78.17 MB) | Scale, hosting, files | Azure page about 912 days old (the older host) |
| Redivis dataset and table pages | Description only (no tables without sign-in) | Table page snapshot about 264 days old |
| GitHub Stanford-AIMI/chexpert-plus README | Files, columns, example paths | About 907 days old |
| GitHub issues #4, #9, #13, #16 | Defects | #16 opened 2026-11-19, open; others undated on page |
| CheXpert paper, arXiv:1901.07031; datasheet arXiv:2105.03020 | Valid/test labeling by radiologists | 2019 / 2021 |
| arXiv:2107.10230 | Test set: 668 images, 8 annotators, majority of 5 | 2021 |
| CheXlocalize GitHub (rajpurkarlab/cheXlocalize) and AIMI page | `val_labels.csv`, `test_labels.csv`, images | Accessed 2026-11-24 |
| VisualCheXbert, arXiv:2102.11467 | Report labels vs image labels disagree | 2021 |
| RadEval, arXiv:2509.18030 | CheXpert Plus validation set: 74 studies with Findings, 234 with Impression; no official test split | 2025 |
| SChapmanL/prototipo_propuesta_fl (third-party) | Redivis table names; DICOM size estimate | README state as of 2026-11-18; code not read |
| MinaAhmdian/retrieval (third-party) | — | **Could not be read** (rate-limited) |
