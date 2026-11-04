# Bounded BGE experiment comparison

Primary target, declared before comparisons: forced category accuracy on validation homepages. All runs use k=15 and the unchanged cutoff. The 106 homepages provide a noisy estimate; small differences are inconclusive. No test tools were scored. No checkpoint is promoted.

| Run / candidate | Sampler (tokens, LR, seed) | Updates | Unique triplets / tools | Train s | Eval s incl. checkpoints | Peak train MiB |
|---|---|---:|---:|---:|---:|---:|
| implementation-pilot / original_same_length | pretrained | 0 | n/a | 0.0 | 280.8 | 0.0 |
| implementation-pilot / finetuned | legacy_random (128, 1e-05, 20261014) | 8 | 32 / 96 | 6.5 | 417.5 | 618.1 |
| implementation-pilot / deployed_original_preprocessing | pretrained | 0 | n/a | 0.0 | 49.8 | 0.0 |
| budget-a-random / finetuned | random (128, 1e-05, 20261014) | 64 | 256 / 719 | 70.6 | 292.6 | 618.9 |
| budget-b-random / finetuned | random (128, 1e-05, 20261014) | 256 | 1024 / 2415 | 282.7 | 584.2 | 618.6 |
| budget-b-mixed / finetuned | mixed (128, 1e-05, 20261014) | 256 | 1024 / 2371 | 247.1 | 270.8 | 770.9 |
| budget-a-random-seed2 / finetuned | random (128, 1e-05, 20261015) | 64 | 256 / 729 | 49.4 | 220.0 | 619.5 |

| Run / candidate | Description accuracy / F1 | Homepage accuracy / F1 | Description coverage / answered accuracy | Homepage coverage / answered accuracy | Homepage fixed / regressed |
|---|---:|---:|---:|---:|---:|
| implementation-pilot / original_same_length | 0.5622 / 0.4559 | 0.5189 / 0.3792 | 0.6075 / 0.6917 | 0.5377 / 0.6842 | None / None |
| implementation-pilot / finetuned | 0.5615 / 0.4552 | 0.5189 / 0.3792 | 0.6064 / 0.6918 | 0.5377 / 0.6842 | 0 / 0 |
| implementation-pilot / deployed_original_preprocessing | 0.5622 / 0.4559 | 0.5377 / 0.4574 | 0.6075 / 0.6917 | 0.5094 / 0.7037 | None / None |
| budget-a-random / finetuned | 0.5619 / 0.4541 | 0.5283 / 0.3815 | 0.6053 / 0.6936 | 0.5189 / 0.6909 | 1 / 0 |
| budget-b-random / finetuned | 0.5630 / 0.4582 | 0.5094 / 0.3621 | 0.6061 / 0.6934 | 0.5377 / 0.6842 | 2 / 3 |
| budget-b-mixed / finetuned | 0.5670 / 0.4578 | 0.5094 / 0.3261 | 0.6156 / 0.6987 | 0.5377 / 0.7018 | 2 / 3 |
| budget-a-random-seed2 / finetuned | 0.5666 / 0.4617 | 0.5189 / 0.3769 | 0.6035 / 0.6933 | 0.5283 / 0.6786 | 1 / 1 |

Settings, paired changes, exact evaluation provenance, per-category recall, confusion matrices and neighbor evidence are retained in the source evaluations and comparison.csv. Training and evaluation times are measured separately; cached baseline evaluations may be faster on later runs. Original BGE with the same reference labels remains a candidate. Reviewed-label comparisons require explicit approved versioned annotations; no labels were automatically changed. A promising configuration requires a second-seed comparison before considering deployment.

| Retained earlier checkpoint | Description accuracy / F1 | Homepage accuracy / F1 | Homepage coverage |
|---|---:|---:|---:|
| budget-b-random / update 128 | 0.5637 / 0.4555 | 0.5189 / 0.3692 | 0.5283 |

Selection uses homepage accuracy with predeclared guards: macro-F1 may fall by at most 0.01 and coverage by at most five percentage points on each view, relative to matching original BGE. The deployed baseline is retained separately because its original preprocessing differs.

Candidate still needing a second-seed check: none. This is experimental selection, not automatic promotion.

Second-seed comparison at 64 updates: seed 20261014: 0.5283, seed 20261015: 0.5189. Mean 0.5236; range 0.5189–0.5283. Both seeds improve the primary target and pass supporting guards: False. Two seeds on the same small validation set do not provide an independent performance claim.
