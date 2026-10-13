# Enterprise description-only v3 calibration

**Status: calibration accepted after parent validation; paused for explicit approval before the remainder.**

Rubric: `enterprise-description-only-v3`. This run labels historical snapshot descriptions, not current products or observed AI-feature usage. The cue-selected 20-description challenge set is not a representative evaluation sample; agreement is not measured accuracy.

## Coverage and results

- Frozen source: 1,494 source records, 56 cleaner exclusions, **1,438 retained rows / 1,406 product groups / 1,391 exact descriptions**.
- Calibration: **20 exact descriptions / 20 source rows / 19 product groups**. Both descriptions in the one differing-description group were included and independently annotated. No labels were propagated across unequal text.
- Final binary labels: **6 AI, 14 non-AI**.
- **8 binary decisions remain weak/forced** and are excluded from trusted training/evaluation and the negative pool.
- AI subtypes: 4 native, 2 enabled; **1 subtype remains weak/forced** (record 61), independently excluded from trusted subtype analysis.
- **7 supported non-AI candidates**, with successful required verification. Their exact original cleaned text is preserved.
- Independent binary agreement: **19/20**; the only binary disagreement was record 53. No additional standalone subtype disagreement.
- **9 reconciliations:** 8 required by disagreement/uncertainty plus 1 parent semantic concern (record 1153's unsupported deterministic-implementation claim). The latter was resolved without changing its binary label.
- `review_queue.json` retains all 9 routed cases for audit; **8 remain weak**, not 9 unresolved cases.
- Remaining: **1,371 descriptions / 1,418 source rows**, unannotated by v3. No full-source coverage claim.

## Decisions

Source product names below are human-review provenance only; agents did not receive separate names/vendor/taxonomy columns.

| Source record | Source product name | Binary | Subtype | Binary support | Subtype support |
|---|---|---|---|---|---|
| 2 | MicroStrategy BI Platform | ai | ai_enabled | supported | supported |
| 10 | Domo Business Cloud | non_ai | — | supported | — |
| 35 | Enterprise Stack | non_ai | — | supported | — |
| 43 | KORE BOTS Platform | ai | ai_native | supported | supported |
| 45 | Crystal Ball | non_ai | — | weak | — |
| 46 | Comprehend | ai | ai_native | supported | supported |
| 51 | IQ Bot | ai | ai_native | supported | supported |
| 52 | Enterprise AI | ai | ai_native | supported | supported |
| 53 | ASAPP | non_ai | — | weak | — |
| 59 | SAS Suite | non_ai | — | weak | — |
| 61 | ICP4D | ai | ai_enabled | weak | weak |
| 114 | Localworks | non_ai | — | supported | — |
| 231 | MOVEit | non_ai | — | supported | — |
| 252 | Quality Management | non_ai | — | weak | — |
| 555 | Intersight | non_ai | — | weak | — |
| 607 | MongoDB | non_ai | — | supported | — |
| 876 | Pegasystems Training | non_ai | — | weak | — |
| 1012 | MoveIt | non_ai | — | supported | — |
| 1153 | Decisions on Demand | non_ai | — | supported | — |
| 1330 | HCL Technologies Managed Services - Imaging | non_ai | — | weak | — |

### Remaining weak cases

- **Record 45, Crystal Ball:** The text describes spreadsheet-based predictive modeling, forecasting, simulation, optimization, and risk insight, but does not specify the methods. Prediction-related functions can be conventional or AI-based, so the non-AI interpretation is weak and forced.
- **Record 53, ASAPP:** The text labels the company an artificial intelligence company, but describes the offering as an asynchronous messaging and social/chat customer-interaction platform without connecting AI to those functions. The relationship is unclear, so the best-supported non-AI decision is forced and weak.
- **Record 59, SAS Suite:** The text identifies statistical software for data management, advanced and multivariate analysis, BI, investigation, and predictive analytics. Predictive analytics is not specified as AI or as a particular conventional method, leaving an ambiguity.
- **Record 61, ICP4D:** The description links the data and analytics platform's collection, organization, and analysis functions with accelerating the value of 'data science and AI.' This is a product-context AI mention, but it is unclear whether it describes included AI functionality or a related use area, so binary applicability is weak/forced.
- **Record 252, Quality Management:** The quality-management description covers interaction review, audio waveforms, analytics categories, emotions, keywords, and a separately worded automated-quality-management add-on. It does not say how analytics or automation work or establish AI, leaving potentially AI-dependent functionality unresolved.
- **Record 555, Intersight:** The text meaningfully describes deployment, monitoring, management, and lifecycle control of infrastructure. It also says the platform is augmented by 'intelligent systems' without explaining those systems; therefore the conventional non-AI judgment remains weak and forced.
- **Record 876, Pegasystems Training:** Only the title 'Pega Training' is supplied. It does not meaningfully describe offering functionality or establish AI, so the best-supported non-AI decision is forced.
- **Record 1330, HCL Technologies Managed Services - Imaging:** The entire description is 'Laptop imaging.' This suggests a conventional device-imaging task but gives too little information about the offering to support a confident label.

Weak labels remain best-supported forced binary choices, not trusted negatives. Acceptance/agreement alone has not upgraded weak text to supported evidence.

## Execution and acceptance

- One labeler and one fresh blind verifier, both **`openai-codex/gpt-6-luna:high`**, followed by exactly one continuation of that original verifier for the 9 routed descriptions.
- At most 2 active Luna workers; no third semantic reviewer/adjudicator, child delegation, external evidence or web calls.
- Parent validated both persisted independent outputs against all 40 private checkpoints, exact spans, source hashes, IDs, coverage and applicable subtype/null/boolean flags. The final 9 records passed the same gates and explicitly addressed conflicts.
- Native session captures prove the independent passes read only their own frozen prompt and common description packet. The follow-up read only its frozen reconciliation prompt and routed packet. Actual provider/model and allowed write paths were checked.
- Original blind session bytes remained an unchanged prefix of the continued verifier session. Independent proposals/checkpoints are preserved, not overwritten.
- Parent examined all independent rationales and final reconciliations against original text; no replacement semantic labels were invented.
- **36 enterprise unittest tests passed**, including immutable packet preparation, registered checkpoint/resume integrity, exact-text-only joining, weak exclusions, complete parent routing, and stage-specific prompt binding.
- All pinned live inputs and **all 233 historical files remain unchanged**.

### Recorded delivery failure and recovery

The original independent workflow failed its file-only materialization check: the write-capable agents called native `structured_output`, which retained complete JSON, but did not create the separately bound result files under the initial aggregate-writing prohibition. Both native structured values matched the 20 respective checkpoints.

The parent copied those complete native bytes to the bound paths with **no extra model call, semantic modification or model/execution substitution**. Original partial child statuses and the failed workflow receipt remain retained. The reconciliation task explicitly authorized writing a complete nonempty bound aggregate **in addition to** native structured output; that native workflow completed successfully.

Thus parent artifact acceptance succeeded; the original workflow is not falsely reported as native-successful. Corrected aggregate-materialization instructions are necessary before scaling. Do not rerun completed calibration work.

## Measured Luna usage

Reported by retained native per-child status records; wrappers are not double-counted:

| Scope | Reported tokens | Reported pricing-metadata cost (USD) |
|---|---:|---:|
| Setup implementation and focused reviews | 246557 | 0.085254 |
| Labeler, blind verifier and one reconciliation | 118374 | 0.026169 |
| All Luna subagents for this task | 364931 | 0.111423 |

These are **native pricing estimates, not a verified invoice**. Root parent Sol usage and subscription/invoice billing are excluded. No full-run time/cost estimate is established from this deliberately difficult calibration sample. Details and per-run elapsed times are in `USAGE_REPORT.json`.

## Retained artifacts and next boundary

- `description_labels.json`, `record_labels.json`: finalized calibration annotations.
- `non_ai_candidates.csv`: 7 supported verified negative descriptions with source references and exact text; not an authorized training dataset.
- `parent_join_map.json`: complete original source metadata, parent-only.
- `review_ledger.json`, `review_queue.json`: unchanged proposals, final calls and uncertainty history.
- `PARENT_COMPARISON.json`, `PARENT_ACCEPTANCE.json`, launch/recovery receipts, and `runtime/`: actual validation, native captures and provenance.
- `inputs/`: frozen raw/cleaned/report/rubric/role prompts plus exact packets and schemas.

Source/product/taxonomy columns, rationales, evidence spans, labels and subtypes are audit metadata—not classifier features. Weak/forced decisions cannot enter trusted training/evaluation. Related product groups and identical text need leakage-safe treatment before any later partitioning or cross-source merge.

**Recommendation:** approve the remaining description-only labeling only if this conservative uncertainty handling is acceptable; keep all weak/forced cases excluded and use corrected bound-output materialization. Continue with fresh bounded batches, preserving these 20 completed annotations. Stop before AIToolBuzz merging, partitioning or training.

No historical archival/deletion, cleaner edits, web research, commits, pushes, merges, training or partitions were performed. The user reports private source-owner reuse permission; no correspondence was accessed and no public license or broader redistribution rights are asserted.
