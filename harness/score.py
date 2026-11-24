"""Score a run against the sealed reference standard (SPEC §3, §8, §9, §11.2).

Example:
    python -m harness.score runs/<run_id> [--consistency-run runs/<rep_id>]
Exit codes: 0 valid, 2 invalid or refused.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

from .common import (
    FINDINGS,
    PRIMARY,
    die,
    load_config,
    public_golden_paths,
    read_csv,
    read_json,
    read_jsonl,
    sealed_golden_paths,
    utc_now,
    write_csv,
    write_json,
)

Z95 = 1.959963984540054


# ---------------------------------------------------------------- statistics

def auroc(y, s) -> float:
    """Mann–Whitney U with average ranks for ties."""
    y = np.asarray(y, dtype=int)
    s = np.asarray(s, dtype=float)
    n_pos = int(y.sum())
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    _, inverse, counts = np.unique(s, return_inverse=True, return_counts=True)
    cum = np.cumsum(counts)
    start = cum - counts
    avg_rank = (start + 1 + cum) / 2.0
    ranks = avg_rank[inverse]
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float, float]:
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return p, max(0.0, center - half), min(1.0, center + half)


def percentile_ci(values) -> tuple[float, float]:
    vals = np.asarray([v for v in values if not math.isnan(v)], dtype=float)
    if len(vals) == 0:
        return float("nan"), float("nan")
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return float(lo), float(hi)


def bootstrap_auroc(Y: np.ndarray, S: np.ndarray, n_boot: int, seed: int) -> tuple[dict, list]:
    """Per-finding AUROC CIs and mean-of-primary CI from the same case resamples."""
    rng = np.random.default_rng(seed)
    n = Y.shape[0]
    per = {f: [] for f in FINDINGS}
    means = []
    prim_idx = [FINDINGS.index(f) for f in PRIMARY]
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        vals = [auroc(Y[idx, j], S[idx, j]) for j in range(len(FINDINGS))]
        for j, f in enumerate(FINDINGS):
            per[f].append(vals[j])
        prim = [vals[j] for j in prim_idx]
        means.append(float("nan") if any(math.isnan(v) for v in prim) else float(np.mean(prim)))
    return {f: percentile_ci(per[f]) for f in FINDINGS}, percentile_ci(means)


# ---------------------------------------------------------------- loading

def load_truth(golden_dir: Path) -> dict:
    sealed = sealed_golden_paths(golden_dir)
    _, rows = read_csv(sealed["truth"])
    return {r["case_id"]: {f: int(r[f]) for f in FINDINGS} for r in rows}


def load_predictions(run_dir: Path) -> dict:
    """(case_id, repeat) -> {finding: prob} for parsed rows only."""
    _, rows = read_csv(run_dir / "predictions.csv")
    out = {}
    for r in rows:
        if r["parse_ok"] == "1":
            out[(r["case_id"], int(r["repeat"]))] = {f: float(r[f]) for f in FINDINGS}
    return out


def check_lock(golden_dir: Path, rc: dict) -> dict:
    lock = read_json(public_golden_paths(golden_dir)["lock"])
    if lock["lock_id"] != rc["golden_lock_id"]:
        die(f"G1 failed: the run used golden lock {rc['golden_lock_id'][:16]}…, but {golden_dir} has "
            f"{lock['lock_id'][:16]}…. Score against the golden set the run used.", code=2)
    return lock


def consistency(preds: dict, case_ids: list[str], repeats: int, threshold: float) -> dict | None:
    if repeats < 2:
        return None
    complete = [c for c in case_ids if all((c, r) in preds for r in range(repeats))]
    if not complete:
        return {"n_cases": 0}
    out = {"n_cases": len(complete), "repeats": repeats, "per_finding": {}}
    all_abs, all_agree = [], []
    for f in FINDINGS:
        diffs, agree = [], []
        for c in complete:
            p0 = preds[(c, 0)][f]
            for r in range(1, repeats):
                pr = preds[(c, r)][f]
                diffs.append(abs(pr - p0))
                agree.append((pr >= threshold) == (p0 >= threshold))
        out["per_finding"][f] = {"mean_abs_diff": float(np.mean(diffs)), "agreement": float(np.mean(agree))}
        if f in PRIMARY:
            all_abs.extend(diffs)
            all_agree.extend(agree)
    out["mean_abs_diff"] = float(np.mean(all_abs))
    out["agreement"] = float(np.mean(all_agree))
    return out


def comparable(rc_a: dict, rc_b: dict) -> bool:
    keys = ("model", "max_tokens", "extra", "prompt_sha256", "golden_lock_id", "mock")
    return all(rc_a["identity_obj"].get(k) == rc_b["identity_obj"].get(k) for k in keys)


# ---------------------------------------------------------------- report

def fmt(v, nd=2) -> str:
    return "n/a" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.{nd}f}"


def fmt_ci(point, lo, hi, nd=2) -> str:
    return f"{fmt(point, nd)} [{fmt(lo, nd)}–{fmt(hi, nd)}]"


def write_report(run_dir: Path, s: dict) -> str:
    rc = s["run"]
    thr = s["threshold"]
    thr_txt = str(int(thr)) if float(thr).is_integer() else str(thr)
    status = "VALID" if s["valid"] else "INVALID"
    g2 = s["gates"]["G2"]
    lines = [
        f"# Golden test report: run {run_dir.name}",
        f"Model {rc['model']} (returned id: {', '.join(s['returned_models']) or 'n/a'}) · Prompt "
        f"{rc['prompt_path']} (sha256 {rc['prompt_sha256'][:8]}…) · Golden set {rc['golden_name']} "
        f"(lock {rc['golden_lock_id'][:8]}…)",
        f"Status: {status} (G1 golden lock matches · G2 parse failures {g2['failures']}/{g2['calls']} = "
        f"{g2['rate'] * 100:.1f}%, limit {g2['limit'] * 100:.0f}%)",
        f"Scored {s['n_scored']} cases · threshold {thr_txt} · bootstrap {s['bootstrap']} (seed {s['seed']})",
        f"Generated {s['generated_utc']}",
        "",
        f"Headline: mean AUROC across {len(PRIMARY)} primary findings "
        f"{fmt_ci(s['mean_auroc'], *s['mean_auroc_ci'])}",
        "",
    ]
    has_base = any(s["per_finding"][f].get("baseline_auroc") is not None for f in FINDINGS)
    header = "| Finding | Positive | AUROC [95% CI] | Sens @{t} [CI] | Spec @{t} [CI] |".format(t=thr_txt)
    sep = "|---|---|---|---|---|"
    if has_base:
        header += " Baseline AUROC |"
        sep += "---|"
    lines += [header, sep]
    for f in FINDINGS:
        m = s["per_finding"][f]
        name = f if f in PRIMARY else f"{f} (secondary)"
        row = (f"| {name} | {m['positive']}/{m['n']} | {fmt_ci(m['auroc'], *m['auroc_ci'])} | "
               f"{fmt_ci(*m['sensitivity'])} | {fmt_ci(*m['specificity'])} |")
        if has_base:
            row += f" {fmt(m.get('baseline_auroc'))} |"
        lines.append(row)
    if has_base:
        lines.append("")
        lines.append(f"Baseline source: {s.get('baseline_source') or 'not given'}")
    lines.append("")
    c = s.get("consistency")
    if c and c.get("n_cases"):
        src = c.get("source_run", run_dir.name)
        lines.append(f"Repeatability (first {c['n_cases']} cases × {c['repeats']} repeats, from run {src}): "
                     f"mean |Δ probability| {c['mean_abs_diff']:.1f} points; same yes/no call "
                     f"{c['agreement'] * 100:.0f}%.")
    elif c and c.get("not_comparable"):
        lines.append(f"Repeatability: not comparable ({c['not_comparable']}).")
    else:
        lines.append("Repeatability: not measured (run with --repeats 3, or pass --consistency-run).")
    u = s["usage"]
    lines.append(f"Tokens: {u['input_tokens'] / 1e6:.2f}M in / {u['output_tokens'] / 1e6:.2f}M out · "
                 f"estimated cost ≈ ${u['estimated_cost_usd']:.2f} (estimate from config prices)")
    lines.append("Caveats: contamination possible · n=" + str(s["n_scored"]) +
                 " · non-commercial research use only · not for clinical use")
    lines.append("")
    lines.append("Misses for radiologist review: misses.csv")
    text = "\n".join(lines) + "\n"
    (run_dir / "report.md").write_text(text, encoding="utf-8")
    return text


# ---------------------------------------------------------------- main

def score_run(run_dir: Path, golden_override: str | None, config_override: str | None,
              consistency_run: str | None) -> tuple[dict, str]:
    rc_path = run_dir / "run_config.json"
    if not rc_path.exists():
        die(f"{run_dir} has no run_config.json")
    rc = read_json(rc_path)
    cfg = load_config(config_override) if config_override else rc["config"]
    sc = cfg["score"]
    threshold, n_boot, seed = float(sc["threshold"]), int(sc["bootstrap"]), int(sc["seed"])

    golden_dir = Path(golden_override or rc["golden_dir"])
    check_lock(golden_dir, rc)
    truth = load_truth(golden_dir)
    preds = load_predictions(run_dir)
    case_ids = rc["case_ids"]
    repeats = int(rc["repeats"])

    calls = len(case_ids)
    parsed = [c for c in case_ids if (c, 0) in preds]
    failures = calls - len(parsed)
    rate = failures / calls if calls else 1.0
    g2_ok = rate <= float(sc["max_parse_failure_rate"])

    Y = np.array([[truth[c][f] for f in FINDINGS] for c in parsed], dtype=int)
    S = np.array([[preds[(c, 0)][f] for f in FINDINGS] for c in parsed], dtype=float)
    cis, mean_ci = bootstrap_auroc(Y, S, n_boot, seed) if len(parsed) else ({f: (math.nan, math.nan) for f in FINDINGS}, (math.nan, math.nan))

    baseline = cfg.get("baseline") or {}
    per = {}
    for j, f in enumerate(FINDINGS):
        y, s = Y[:, j] if len(parsed) else np.array([]), S[:, j] if len(parsed) else np.array([])
        pos = int(y.sum())
        neg = len(y) - pos
        called = s >= threshold
        tp = int((called & (y == 1)).sum())
        tn = int((~called & (y == 0)).sum())
        b = baseline.get(f)
        per[f] = {
            "n": len(y), "positive": pos,
            "auroc": auroc(y, s) if len(y) else math.nan, "auroc_ci": list(cis[f]),
            "sensitivity": list(wilson(tp, pos)), "specificity": list(wilson(tn, neg)),
            "baseline_auroc": float(b) if isinstance(b, (int, float)) and not isinstance(b, bool) else None,
        }
    prim = [per[f]["auroc"] for f in PRIMARY]
    mean_auroc = float(np.mean(prim)) if not any(math.isnan(v) for v in prim) else math.nan

    # consistency
    cons = consistency(preds, case_ids, repeats, threshold)
    if cons is None and consistency_run:
        crun = Path(consistency_run)
        crc = read_json(crun / "run_config.json")
        if not comparable(rc, crc):
            cons = {"not_comparable": f"{crun.name} differs in model settings, prompt or golden set"}
        else:
            cons = consistency(load_predictions(crun), crc["case_ids"], int(crc["repeats"]), threshold)
            if cons is None:
                cons = {"not_comparable": f"{crun.name} has only one repeat"}
            else:
                cons["source_run"] = crun.name

    # usage and cost (every record costs money, including retries and failures)
    records = read_jsonl(run_dir / "responses.jsonl")
    cost_cfg = cfg["cost"]
    tin = sum(r["usage"]["input_tokens"] for r in records)
    tout = sum(r["usage"]["output_tokens"] for r in records)
    cost = 0.0
    for r in records:
        c = (r["usage"]["input_tokens"] * float(cost_cfg["input_per_mtok"]) +
             r["usage"]["output_tokens"] * float(cost_cfg["output_per_mtok"])) / 1e6
        if r.get("mode") == "batch":
            c *= float(cost_cfg["batch_discount"])
        cost += c
    returned_models = sorted({r["model"] for r in records if r.get("model")})

    scores = {
        "generated_utc": utc_now(),
        "valid": g2_ok,
        "gates": {"G1": True, "G2": {"ok": g2_ok, "calls": calls, "failures": failures, "rate": rate,
                                     "limit": float(sc["max_parse_failure_rate"])}},
        "run": {"model": rc["identity_obj"]["model"], "prompt_path": rc["prompt_path"],
                "prompt_sha256": rc["prompt_sha256"], "golden_name": rc.get("golden_name"),
                "golden_lock_id": rc["golden_lock_id"]},
        "returned_models": returned_models,
        "n_scored": len(parsed), "threshold": threshold, "bootstrap": n_boot, "seed": seed,
        "mean_auroc": mean_auroc, "mean_auroc_ci": list(mean_ci),
        "per_finding": per,
        "baseline_source": baseline.get("source"),
        "consistency": cons,
        "usage": {"input_tokens": tin, "output_tokens": tout, "estimated_cost_usd": cost},
    }
    write_json(run_dir / "scores.json", scores)
    report = write_report(run_dir, scores)

    # misses.csv for reviewer
    _, manifest = read_csv(public_golden_paths(golden_dir)["manifest"])
    images_by_case = {r["case_id"]: r["images"] for r in manifest}
    _, source_rows = read_csv(sealed_golden_paths(golden_dir)["source_map"])
    study_by_case = {r["case_id"]: r["study_id"] for r in source_rows}
    k = int(sc["misses_per_finding"])
    miss_rows = []
    for f in FINDINGS:
        # Actual errors at the threshold, most confident first.
        fn = sorted((c for c in parsed if truth[c][f] == 1 and preds[(c, 0)][f] < threshold),
                    key=lambda c: preds[(c, 0)][f])[:k]
        fp = sorted((c for c in parsed if truth[c][f] == 0 and preds[(c, 0)][f] >= threshold),
                    key=lambda c: -preds[(c, 0)][f])[:k]
        for kind, group in (("false_negative", fn), ("false_positive", fp)):
            for c in group:
                miss_rows.append({"case_id": c, "finding": f, "error_type": kind, "reference": truth[c][f],
                                  "model_prob": preds[(c, 0)][f], "images": images_by_case.get(c, ""),
                                  "source_study": study_by_case.get(c, ""), "reviewer_verdict": ""})
    write_csv(run_dir / "misses.csv", miss_rows,
              ["case_id", "finding", "error_type", "reference", "model_prob", "images", "source_study",
               "reviewer_verdict"])
    return scores, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Score a run (SPEC §8, §9).")
    ap.add_argument("run_dir")
    ap.add_argument("--golden", default=None, help="golden folder (default: the one recorded in the run)")
    ap.add_argument("--config", default=None, help="override score settings (default: the run's config)")
    ap.add_argument("--consistency-run", default=None)
    args = ap.parse_args(argv)
    scores, report = score_run(Path(args.run_dir), args.golden, args.config, args.consistency_run)
    print(report)
    if not scores["valid"]:
        print("INVALID: G2 failed (too many unparseable answers).", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
