# Reviewed homepage BGE experiment

No demonstrated improvement.

Codex reviewed all 30 immutable attempts (AI review, not human approval): 25 extracted and 16 approved distinct tools/groups. The other decisions were 5 acquisition failures, 4 insufficient-evidence/suitability decisions, 3 unverified/different products, and 2 ambiguous categories.

[All 30 decisions and reasons](../../../../data/category_classification/homepage_training_v2/reviewed-2026-11-07-v1/REPORT.md). Shutdown content, redirects without product continuity, a company portfolio, a non-English page, and uncertain function boundaries were excluded. Bexi was relabeled to Media And Content Creation, FloorDesign to Industry Specific, and Atricent to Personal And Lifestyle; the two prior corrections were retained for every condition.

| Approved category | Distinct pages/tools/groups |
|---|---:|
| Data And Analytics | 1 |
| Education And Learning | 3 |
| Industry Specific | 3 |
| Media And Content Creation | 1 |
| Personal And Lifestyle | 4 |
| Security And Privacy | 4 |

The predeclared comparison used pinned BGE revision 5c38ec7c405ec4b44b94cc5a9bb96e735b38267a, 128 tokens, CPU float32, final encoder block only, 64 optimizer updates and 256 unique triplets maximum per condition; microbatch 1, accumulation 4, learning rate 1e-5, margin 0.1, random sampling, k=15, and cutoff 0.468914118995349. A used descriptions only; B used only the new supplement for homepage anchors (requested fraction 0.25). All references used the same merged labels.

| Seed / candidate | View | Correct / total | Accuracy | Macro-F1 | Answered / total | Coverage | Accuracy when answered |
|---|---|---:|---:|---:|---:|---:|---:|
| 20261014 / Original BGE | homepages | 55/106 | 51.89% | 0.3792 | 57/106 | 53.77% | 68.42% |
| 20261014 / Original BGE | descriptions | 1542/2739 | 56.30% | 0.4560 | 1666/2739 | 60.83% | 69.15% |
| 20261014 / A descriptions | homepages | 55/106 | 51.89% | 0.3780 | 56/106 | 52.83% | 69.64% |
| 20261014 / A descriptions | descriptions | 1547/2739 | 56.48% | 0.4567 | 1656/2739 | 60.46% | 69.26% |
| 20261014 / B homepages | homepages | 55/106 | 51.89% | 0.3781 | 56/106 | 52.83% | 67.86% |
| 20261014 / B homepages | descriptions | 1544/2739 | 56.37% | 0.4552 | 1665/2739 | 60.79% | 69.31% |

| Run | Actual homepage presentations | Unique homepage anchors | Active-loss fraction | Training seconds | Evaluation seconds | Peak training RSS MiB |
|---|---:|---:|---:|---:|---:|---:|
| 20261014-A | 0/256 | 0 | 81.64% | 70.41 | 238.95 | 620.6 |
| 20261014-B | 29/256 | 12 | 80.08% | 50.64 | 290.10 | 699.9 |

The eight-update pilot passed finite-loss, parameter-update, frozen-weight, saved-model reload and source-provenance checks in 6.60 seconds, with 637.8 MiB peak sampled RSS. The homepage condition was interrupted after update 36 and resumed at its saved optimizer boundary; completed conditions were retained.

The requested homepage fraction is conditional on category eligibility. Actual presentations and category coverage, together with sampler fallback counts, are retained in [summary.json](summary.json). Random sampling used no semi-hard fallback.

B versus A, 20261014-homepages: 1 fixed, 1 regressed, and 1 changed between wrong categories.

| Validation example | Expected | A | B |
|---|---|---|---|
| homepage:aivoicegen.net | Ai And Machine Learning | Business And Finance | Media And Content Creation |
| homepage:askaiquestions.net | Communication And Support | Ai And Machine Learning | Communication And Support |
| homepage:imagepromptguru.net | Media And Content Creation | Media And Content Creation | Creative And Entertainment |

B versus A, 20261014-descriptions: 11 fixed, 14 regressed, and 15 changed between wrong categories.

The supporting guards permit at most a 0.01 macro-F1 drop and a five-percentage-point coverage drop on either view versus matching original BGE. Both guards passed, but primary accuracy did not improve. The first seed did not meet the repeat criterion, so no second seed or further experiment was launched.

Full per-category recall and confusion matrices are in [metrics.json](metrics.json); exact paired IDs, expected/predicted labels and training coverage are in [summary.json](summary.json). Encoder-specific training-only indexes were rebuilt during validation. Original BGE used the same effective labels. Test data was limited to hash/isolation checks.

One validation homepage changes accuracy by about 0.94 percentage points; small gains remain preliminary. Fresh independently labeled held-out pages are required for an independent claim. No deployment, backend-default change, new collection or further search was performed.

Verification: 25 offline training/supplement tests and 10 existing backend category classification/neighbor tests passed. `git diff --check` passed. The incomplete local training environment was repaired; training dependencies remain isolated from backend defaults.
