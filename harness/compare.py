"""Compare two runs on the same golden set with a paired bootstrap regression gate (SPEC §8, §9 G3/G4).

Example:
    python -m harness.compare runs/<A> runs/<B>
Exit codes: 0 pass, 1 a primary finding got WORSE, 2 refused.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

from .common import FINDINGS, PRIMARY, die, read_json
from .score import auroc, check_lock, load_predictions, load_truth, percentile_ci


def verdict(lo: float, hi: float) -> str:
    if math.isnan(lo) or math.isnan(hi):
        return "not estimable"
    if hi < 0:
        return "WORSE"
    if lo > 0:
        return "BETTER"
    return "no detectable change"


def compare(run_a: Path, run_b: Path, golden_override: str | None, n_boot: int | None, seed: int | None):
    rc_a, rc_b = read_json(run_a / "run_config.json"), read_json(run_b / "run_config.json")
    if rc_a["golden_lock_id"] != rc_b["golden_lock_id"]:
        die("G4 failed: the two runs used different golden sets (lock_id differs).", code=2)
    golden_dir = Path(golden_override or rc_b["golden_dir"])
    check_lock(golden_dir, rc_b)
    sc = rc_b["config"]["score"]
    n_boot = int(n_boot if n_boot is not None else sc["bootstrap"])
    seed = int(seed if seed is not None else sc["seed"])

    truth = load_truth(golden_dir)
    pa, pb = load_predictions(run_a), load_predictions(run_b)
    common = [c for c in rc_b["case_ids"] if (c, 0) in pa and (c, 0) in pb and c in truth]
    if not common:
        die("the two runs share no parsed cases", code=2)

    Y = np.array([[truth[c][f] for f in FINDINGS] for c in common], dtype=int)
    SA = np.array([[pa[(c, 0)][f] for f in FINDINGS] for c in common], dtype=float)
    SB = np.array([[pb[(c, 0)][f] for f in FINDINGS] for c in common], dtype=float)
    prim_idx = [FINDINGS.index(f) for f in PRIMARY]

    def mean_prim(vals):
        sel = [vals[j] for j in prim_idx]
        return float("nan") if any(math.isnan(v) for v in sel) else float(np.mean(sel))

    point_a = [auroc(Y[:, j], SA[:, j]) for j in range(len(FINDINGS))]
    point_b = [auroc(Y[:, j], SB[:, j]) for j in range(len(FINDINGS))]

    rng = np.random.default_rng(seed)
    n = len(common)
    deltas = {f: [] for f in FINDINGS}
    mean_deltas = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        va = [auroc(Y[idx, j], SA[idx, j]) for j in range(len(FINDINGS))]
        vb = [auroc(Y[idx, j], SB[idx, j]) for j in range(len(FINDINGS))]
        for j, f in enumerate(FINDINGS):
            deltas[f].append(vb[j] - va[j])
        mean_deltas.append(mean_prim(vb) - mean_prim(va))

    rows = []
    for j, f in enumerate(FINDINGS):
        lo, hi = percentile_ci(deltas[f])
        rows.append({"finding": f, "primary": f in PRIMARY, "auroc_a": point_a[j], "auroc_b": point_b[j],
                     "delta": point_b[j] - point_a[j], "ci": (lo, hi), "verdict": verdict(lo, hi)})
    lo, hi = percentile_ci(mean_deltas)
    mean_row = {"finding": "Mean of primary", "primary": False, "auroc_a": mean_prim(point_a),
                "auroc_b": mean_prim(point_b), "delta": mean_prim(point_b) - mean_prim(point_a),
                "ci": (lo, hi), "verdict": verdict(lo, hi)}

    worse = [r["finding"] for r in rows if r["primary"] and r["verdict"] == "WORSE"]
    f2 = lambda v: "n/a" if math.isnan(v) else f"{v:+.2f}"  # noqa: E731
    f2u = lambda v: "n/a" if math.isnan(v) else f"{v:.2f}"  # noqa: E731
    lines = [
        f"# Compare: {run_b.name} (B) vs {run_a.name} (A)",
        f"Golden set lock {rc_b['golden_lock_id'][:8]}… · {n} cases parsed in both · paired bootstrap "
        f"{n_boot} (seed {seed})",
    ]
    if rc_a["identity_obj"]["model"] != rc_b["identity_obj"]["model"]:
        lines.append(f"Models differ: A = {rc_a['identity_obj']['model']}, B = {rc_b['identity_obj']['model']}")
    if rc_a["prompt_sha256"] != rc_b["prompt_sha256"]:
        lines.append(f"Prompts differ: A = {rc_a['prompt_path']}, B = {rc_b['prompt_path']}")
    lines += ["", "| Finding | AUROC A | AUROC B | ΔAUROC (B − A) [95% CI] | Verdict |", "|---|---|---|---|---|"]
    for r in rows + [mean_row]:
        name = r["finding"] if r["primary"] or r is mean_row else f"{r['finding']} (secondary)"
        v = f"**{r['verdict']} → test fails**" if (r["primary"] and r["verdict"] == "WORSE") else r["verdict"]
        lines.append(f"| {name} | {f2u(r['auroc_a'])} | {f2u(r['auroc_b'])} | {f2(r['delta'])} "
                     f"[{f2(r['ci'][0])}, {f2(r['ci'][1])}] | {v} |")
    lines.append("")
    lines.append("Result: FAIL (" + ", ".join(worse) + " worse)" if worse else
                 "Result: PASS (no primary finding is worse)")
    text = "\n".join(lines) + "\n"
    (run_b / f"compare_vs_{run_a.name}.md").write_text(text, encoding="utf-8")
    return text, bool(worse)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Compare two runs (SPEC §9 G3/G4).")
    ap.add_argument("run_a")
    ap.add_argument("run_b")
    ap.add_argument("--golden", default=None)
    ap.add_argument("--bootstrap", type=int, default=None)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args(argv)
    text, failed = compare(Path(args.run_a), Path(args.run_b), args.golden, args.bootstrap, args.seed)
    print(text)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
