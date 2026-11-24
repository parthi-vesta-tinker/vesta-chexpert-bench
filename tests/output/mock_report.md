# Golden test report: run base
Model claude-opus-5-5 (returned id: mock) · Prompt prompts/v1.txt (sha256 136d0444…) · Golden set synthetic-60 (lock 5a22ee7c…)
Status: VALID (G1 golden lock matches · G2 parse failures 0/60 = 0.0%, limit 2%)
Scored 60 cases · threshold 50 · bootstrap 1000 (seed 42)
Generated 2026-11-24T19:11:25Z

Headline: mean AUROC across 5 primary findings 0.95 [0.93–0.97]

| Finding | Positive | AUROC [95% CI] | Sens @50 [CI] | Spec @50 [CI] |
|---|---|---|---|---|
| Atelectasis | 15/60 | 0.95 [0.89–1.00] | 0.87 [0.62–0.96] | 0.91 [0.79–0.96] |
| Cardiomegaly | 25/60 | 0.92 [0.84–0.97] | 0.76 [0.57–0.89] | 0.86 [0.71–0.94] |
| Consolidation | 20/60 | 0.98 [0.95–1.00] | 0.90 [0.70–0.97] | 0.95 [0.83–0.99] |
| Edema | 24/60 | 0.93 [0.86–0.99] | 0.83 [0.64–0.93] | 0.94 [0.82–0.98] |
| Pleural Effusion | 17/60 | 0.97 [0.93–1.00] | 0.94 [0.73–0.99] | 0.91 [0.78–0.96] |
| No Finding (secondary) | 10/60 | 0.96 [0.90–1.00] | 0.90 [0.60–0.98] | 0.92 [0.81–0.97] |

Repeatability (first 20 cases × 3 repeats, from run rep3): mean |Δ probability| 4.8 points; same yes/no call 94%.
Tokens: 0.45M in / 0.00M out · estimated cost ≈ $1.87 (estimate from config prices)
Caveats: contamination possible · n=60 · non-commercial research use only · not for clinical use

Misses for radiologist review: misses.csv
