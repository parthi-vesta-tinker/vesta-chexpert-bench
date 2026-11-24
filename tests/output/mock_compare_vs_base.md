# Compare: degraded (B) vs base (A)
Golden set lock 5a22ee7c… · 60 cases parsed in both · paired bootstrap 1000 (seed 42)

| Finding | AUROC A | AUROC B | ΔAUROC (B − A) [95% CI] | Verdict |
|---|---|---|---|---|
| Atelectasis | 0.95 | 0.80 | -0.16 [-0.30, -0.03] | **WORSE → test fails** |
| Cardiomegaly | 0.92 | 0.66 | -0.26 [-0.38, -0.14] | **WORSE → test fails** |
| Consolidation | 0.98 | 0.76 | -0.22 [-0.35, -0.10] | **WORSE → test fails** |
| Edema | 0.93 | 0.71 | -0.23 [-0.37, -0.10] | **WORSE → test fails** |
| Pleural Effusion | 0.97 | 0.72 | -0.25 [-0.40, -0.13] | **WORSE → test fails** |
| No Finding (secondary) | 0.96 | 0.46 | -0.50 [-0.71, -0.27] | WORSE |
| Mean of primary | 0.95 | 0.73 | -0.22 [-0.28, -0.17] | WORSE |

Result: FAIL (Atelectasis, Cardiomegaly, Consolidation, Edema, Pleural Effusion worse)
