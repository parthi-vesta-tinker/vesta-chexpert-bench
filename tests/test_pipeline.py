#!/usr/bin/env python3
"""Self-test for the golden-test harness (SPEC §12).

Synthetic data and the mock model only: no Anthropic API calls, no Redivis access, no real images.
Run from the project root:  python tests/test_pipeline.py [--keep]
Copies the mock report and comparison to tests/output/ for inspection.
"""
from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.common import FINDINGS, MANIFEST_COLUMNS, PRIMARY, read_csv, read_json, read_jsonl, sha256_file  # noqa: E402
from harness.imaging import fit_size, visual_tokens  # noqa: E402
from harness.score import auroc  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    line = f"[{'PASS' if ok else 'FAIL'}] {name}"
    if detail and not ok:
        line += f"\n        {detail.strip()[:1500]}"
    print(line)


def run(work: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    env.pop("ANTHROPIC_API_KEY", None)  # guarantee no real calls
    return subprocess.run([sys.executable, *args], cwd=work, capture_output=True, text=True, env=env)


# ---------------------------------------------------------------- synthetic data (check 1)

def make_synthetic(work: Path, n_studies: int = 60, seed: int = 7) -> tuple[Path, int]:
    rng = np.random.default_rng(seed)
    img_root = work / "data" / "images"
    rows = []
    n_images = 0
    for i in range(n_studies):
        pid, sid = f"patient{64541 + i:05d}", "study1"
        vals = {f: int(rng.random() < 0.35) for f in PRIMARY}
        vals["No Finding"] = int(not any(vals.values()))
        folder = img_root / "valid" / pid / sid
        folder.mkdir(parents=True, exist_ok=True)

        frontal = np.zeros((320, 256))
        for f, band in zip(PRIMARY, np.array_split(np.arange(320), len(PRIMARY))):
            level = (170.0 if vals[f] else 70.0) + rng.normal(0, 40)  # stripe-level noise, SD 40
            frontal[band] = level + rng.normal(0, 5, size=(len(band), 256))
        Image.fromarray(np.clip(frontal, 0, 255).astype(np.uint8)).save(folder / "view1_frontal.png")
        n_images += 1
        base = {"Sex": "Female", "Age": "60", **{f: f"{v}.0" for f, v in vals.items()}}
        rows.append({"Path": f"CheXpert-v1.0/valid/{pid}/{sid}/view1_frontal.jpg", "Frontal/Lateral": "Frontal",
                     "AP/PA": "AP", **base})
        if i == 1:  # same stem in a second format: .png must win under the default extension order
            Image.fromarray(np.full((320, 256), 10, np.uint8)).save(folder / "view1_frontal.jpg")
        if i % 2 == 0:
            Image.fromarray(np.full((320, 256), 120, np.uint8)).save(folder / "view2_lateral.png")
            n_images += 1
            rows.append({"Path": f"CheXpert-v1.0/valid/{pid}/{sid}/view2_lateral.jpg", "Frontal/Lateral": "Lateral",
                         "AP/PA": "", **base})

    csv_path = work / "data" / "valid_labels.csv"
    write_rows(csv_path, rows)
    return csv_path, n_images


def write_rows(path: Path, rows: list[dict]) -> None:
    fields = ["Path", "Sex", "Age", "Frontal/Lateral", "AP/PA", *FINDINGS]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def read_rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- checks

def main() -> int:
    keep = "--keep" in sys.argv
    work = Path(tempfile.mkdtemp(prefix="golden_selftest_"))
    shutil.copy(ROOT / "config.toml", work / "config.toml")
    shutil.copytree(ROOT / "prompts", work / "prompts")
    print(f"Working folder: {work}\n")

    # 1. synthetic dataset
    csv_path, n_images = make_synthetic(work)
    n_rows = len(read_rows(csv_path))
    check("1 synthetic dataset: 60 studies in valid.csv format", n_rows == n_images and n_images == 90,
          f"rows={n_rows} images={n_images}")

    # 2. prepare
    p = run(work, "-m", "harness.prepare_golden", "--labels", str(csv_path), "--image-root", "data/images",
            "--out", "golden", "--name", "synthetic-60", "--expect-studies", "60", "--expect-images", str(n_images))
    check("2 prepare: builds the golden set", p.returncode == 0, p.stderr + p.stdout)
    golden = work / "golden"
    hdr, mrows = read_csv(golden / "manifest.csv")
    mtext = (golden / "manifest.csv").read_text()
    names = [n for r in mrows for n in r["images"].split(";")]
    hashes = [h for r in mrows for h in r["sha256"].split(";")]
    hashes_ok = all(sha256_file(golden / "images" / n) == h for n, h in zip(names, hashes))
    check("2 prepare: manifest has only the allowed columns", hdr == MANIFEST_COLUMNS, str(hdr))
    check("2 prepare: no patient/study strings in the manifest", "patient" not in mtext and "study" not in mtext)
    check("2 prepare: image count and hashes correct",
          len(mrows) == 60 and len(names) == n_images and hashes_ok and
          len(list((golden / "images").iterdir())) == n_images)
    check("2 prepare: sealed reference files and lock exist",
          all((golden / x).exists() for x in ["_sealed/labels.csv", "_sealed/source_map.csv",
                                              "_sealed/summary.json", "golden_lock.json"]))

    # 3. label guard
    rows = read_rows(csv_path)
    bad = [dict(r) for r in rows]
    bad[0]["Atelectasis"] = "-1.0"
    write_rows(work / "data" / "bad_uncertain.csv", bad)
    p = run(work, "-m", "harness.prepare_golden", "--labels", "data/bad_uncertain.csv", "--image-root", "data/images",
            "--out", "golden_bad1")
    check("3 label guard: -1 aborts", p.returncode != 0 and "label guard" in p.stderr, p.stderr)
    bad = [dict(r) for r in rows]
    bad[3]["Edema"] = ""
    write_rows(work / "data" / "bad_blank.csv", bad)
    p = run(work, "-m", "harness.prepare_golden", "--labels", "data/bad_blank.csv", "--image-root", "data/images",
            "--out", "golden_bad2")
    check("3 label guard: blank aborts", p.returncode != 0 and "label guard" in p.stderr, p.stderr)

    # 4. blinding static check (+ show-request audit)
    offending = []
    for fname in ["run_eval.py", "mock_model.py"]:
        text = (ROOT / "harness" / fname).read_text(encoding="utf-8")
        for word in ["_sealed", "labels"]:
            if word in text:
                offending.append(f"{fname} contains {word!r}")
    check("4 blinding: runner and mock never mention the sealed folder or reference files", not offending,
          "; ".join(offending))
    p = run(work, "-m", "harness.run_eval", "--golden", "golden", "--show-request")
    check("4 blinding: --show-request shows images + prompt, no study IDs",
          p.returncode == 0 and "Image 1 (frontal):" in p.stdout and "base64 chars" in p.stdout
          and "patient" not in p.stdout and "CheXpert" not in p.stdout, p.stderr + p.stdout[:500])

    # 5. mock run with failures and retries
    p = run(work, "-m", "harness.run_eval", "--golden", "golden", "--mock", "--mock-fail-rate", "0.1",
            "--repeats", "2", "--run-dir", "runs/mock_fail")
    recs = read_jsonl(work / "runs/mock_fail/responses.jsonl")
    keys = {(r["case_id"], r["repeat"]) for r in recs}
    leftover = sum(1 for r in recs if not r["parse_ok"])
    _, pred_rows = read_csv(work / "runs/mock_fail/predictions.csv") if (work / "runs/mock_fail/predictions.csv").exists() else ([], [])
    check("5 mock run: every (case, repeat) has a record", p.returncode == 0 and len(keys) == 120 and len(pred_rows) == 120,
          p.stderr + f" keys={len(keys)}")
    check("5 mock run: parse retries happened", any(r["attempts"] > 1 for r in recs))
    print(f"        leftover parse failures after retry: {leftover}/120")

    # 6. resume makes zero new calls
    p1 = run(work, "-m", "harness.run_eval", "--golden", "golden", "--mock", "--run-dir", "runs/base")
    n1 = len(read_jsonl(work / "runs/base/responses.jsonl"))
    p2 = run(work, "-m", "harness.run_eval", "--golden", "golden", "--mock", "--run-dir", "runs/base")
    n2 = len(read_jsonl(work / "runs/base/responses.jsonl"))
    check("6 resume: second invocation makes zero new calls",
          p1.returncode == 0 and p2.returncode == 0 and n1 == 60 and n2 == n1 and "to do: 0" in p2.stdout,
          p1.stderr + p2.stderr + f" n1={n1} n2={n2}")
    p3 = run(work, "-m", "harness.run_eval", "--golden", "golden", "--mock", "--repeats", "2", "--run-dir", "runs/base")
    check("6 resume: a different identity is refused", p3.returncode != 0 and "different run identity" in p3.stderr,
          p3.stderr)

    # 7. tamper
    shutil.copytree(golden, work / "golden_tampered")
    victim = work / "golden_tampered" / "images" / names[0]
    data = bytearray(victim.read_bytes())
    data[len(data) // 2] ^= 0xFF
    victim.write_bytes(bytes(data))
    p = run(work, "-m", "harness.run_eval", "--golden", "golden_tampered", "--mock", "--run-dir", "runs/tamper")
    check("7 tamper: one changed byte aborts the runner", p.returncode != 0 and "hash mismatch" in p.stderr, p.stderr)

    # 8. score
    p = run(work, "-m", "harness.score", "runs/base")
    scores = read_json(work / "runs/base/scores.json") if (work / "runs/base/scores.json").exists() else {}
    aucs = {f: scores.get("per_finding", {}).get(f, {}).get("auroc", 0) for f in PRIMARY}
    check("8 score: valid run exits 0 and writes report + misses",
          p.returncode == 0 and (work / "runs/base/report.md").exists() and (work / "runs/base/misses.csv").exists(),
          p.stderr)
    check("8 score: primary AUROC > 0.9 on stripe-encoded findings (proves case↔image routing)",
          all(v > 0.9 for v in aucs.values()), str({k: round(v, 3) for k, v in aucs.items()}))
    report = (work / "runs/base/report.md").read_text() if (work / "runs/base/report.md").exists() else ""
    check("8 score: report renders in the §3 layout",
          "Headline: mean AUROC" in report and "Status: VALID" in report and "| Atelectasis |" in report)
    _, misses = read_csv(work / "runs/base/misses.csv")
    check("8 score: misses.csv lists only real errors at the threshold",
          len(misses) > 0 and all((float(m["model_prob"]) < 50) == (m["error_type"] == "false_negative") for m in misses))
    run(work, "-m", "harness.run_eval", "--golden", "golden", "--mock", "--mock-fail-rate", "0.9",
        "--run-dir", "runs/mostly_fail")
    p = run(work, "-m", "harness.score", "runs/mostly_fail")
    bad_report = (work / "runs/mostly_fail/report.md").read_text() if (work / "runs/mostly_fail/report.md").exists() else ""
    check("8 score: G2 triggers when parse failures exceed 2%", p.returncode == 2 and "Status: INVALID" in bad_report,
          p.stderr)
    run(work, "-m", "harness.run_eval", "--golden", "golden", "--mock", "--limit", "20", "--repeats", "3",
        "--run-dir", "runs/rep3")
    p = run(work, "-m", "harness.score", "runs/base", "--consistency-run", "runs/rep3")
    report = (work / "runs/base/report.md").read_text()
    check("8 score: repeatability from a consistency run is reported",
          p.returncode == 0 and "Repeatability (first 20 cases × 3 repeats, from run rep3)" in report, report[-600:])

    # 9. AUROC unit test vs brute force (with ties)
    rng = np.random.default_rng(3)
    worst = 0.0
    for _ in range(200):
        n = int(rng.integers(5, 60))
        y = rng.integers(0, 2, n)
        if y.min() == y.max():
            y[0] = 1 - y[0]
        s = rng.integers(0, 6, n).astype(float)
        pos, neg = s[y == 1], s[y == 0]
        brute = sum(1.0 if a > b else 0.5 if a == b else 0.0 for a in pos for b in neg) / (len(pos) * len(neg))
        worst = max(worst, abs(auroc(y, s) - brute))
    check("9 AUROC matches brute force including ties (1e-9)", worst < 1e-9, f"max error {worst}")

    # 10. resize
    w, h = fit_size(2320, 2828, 2576, 4784)
    check("10 resize: 2320×2828 fits long edge ≤ 2576 and ≤ 4784 tokens",
          max(w, h) <= 2576 and visual_tokens(w, h) <= 4784, f"{w}x{h} tokens={visual_tokens(w, h)}")
    check("10 resize: small images unchanged", fit_size(256, 320, 2576, 4784) == (256, 320))

    # 11. batch path
    p = run(work, "-m", "harness.run_eval", "--golden", "golden", "--mock", "--mode", "batch", "--run-dir", "runs/batch")
    brecs = read_jsonl(work / "runs/batch/responses.jsonl")
    srecs = read_jsonl(work / "runs/base/responses.jsonl")
    state = read_json(work / "runs/batch/batches.json") if (work / "runs/batch/batches.json").exists() else {"batches": []}
    check("11 batch: same record schema as sync, all cases collected",
          p.returncode == 0 and len(brecs) == 60 and set(brecs[0]) == set(srecs[0])
          and all(b["collected"] for b in state["batches"]) and len(state["batches"]) >= 1, p.stderr)

    # 12. compare
    p = run(work, "-m", "harness.compare", "runs/base", "runs/base")
    check("12 compare: a run against itself passes (exit 0)", p.returncode == 0, p.stderr + p.stdout)
    run(work, "-m", "harness.run_eval", "--golden", "golden", "--mock", "--mock-noise", "80", "--mock-seed", "1",
        "--run-dir", "runs/degraded")
    p = run(work, "-m", "harness.compare", "runs/base", "runs/degraded")
    check("12 compare: a degraded run fails the gate (exit 1)", p.returncode == 1 and "WORSE" in p.stdout,
          p.stderr + p.stdout)

    # 13. path-stem matching
    _, src_rows = read_csv(golden / "_sealed/source_map.csv")
    pick = [r for r in src_rows if r["study_id"].endswith("patient64542/study1")]
    check("13 stem match: .jpg reference path matched .png image; .png preferred over .jpg",
          len(pick) == 1 and pick[0]["source_paths"].endswith("view1_frontal.png"), str(pick))
    extra = rows + [dict(rows[0], Path="CheXpert-v1.0/valid/patient99999/study1/view1_frontal.jpg")]
    write_rows(work / "data" / "missing.csv", extra)
    p = run(work, "-m", "harness.prepare_golden", "--labels", "data/missing.csv", "--image-root", "data/images",
            "--out", "golden_bad3")
    check("13 stem match: a missing image aborts", p.returncode != 0 and "no image found" in p.stderr, p.stderr)
    dup_root = work / "data" / "images_dup"
    shutil.copytree(work / "data" / "images", dup_root / "a")
    shutil.copytree(work / "data" / "images" / "valid" / "patient64541", dup_root / "b" / "valid" / "patient64541")
    p = run(work, "-m", "harness.prepare_golden", "--labels", str(csv_path), "--image-root", "data/images_dup",
            "--out", "golden_bad4")
    check("13 stem match: two images with the same stem and extension abort",
          p.returncode != 0 and "share stem" in p.stderr, p.stderr)
    p = run(work, "-m", "harness.prepare_golden", "--labels", str(csv_path), "--image-root", "data/images",
            "--out", "golden_bad5", "--expect-studies", "59")
    check("13 stem match: a study/image count mismatch aborts", p.returncode != 0 and "join check" in p.stderr,
          p.stderr)

    # outputs for inspection
    out_dir = ROOT / "tests" / "output"
    out_dir.mkdir(exist_ok=True)
    for src, dst in [("runs/base/report.md", "mock_report.md"), ("runs/base/misses.csv", "mock_misses.csv"),
                     ("runs/degraded/compare_vs_base.md", "mock_compare_vs_base.md")]:
        if (work / src).exists():
            shutil.copy(work / src, out_dir / dst)

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} assertions passed across the 13 SPEC §12 checks.")
    print(f"Mock outputs copied to {out_dir}")
    if keep:
        print(f"Kept working folder: {work}")
    else:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
