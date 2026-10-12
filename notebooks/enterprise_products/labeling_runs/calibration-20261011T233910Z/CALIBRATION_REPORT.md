# Enterprise AI-labeling calibration — 20 groups

**Completed calibration; paused before the remaining 1,386 groups.** This is a partial, model-reviewed annotation set, not gold-standard ground truth, a training partition, or a complete dataset export.

## Results

| Measure | Result |
| --- | ---: |
| Product groups / retained source rows | 20 / 21 |
| AI / non-AI groups (after user review) | 12 / 8 |
| AI-enabled / AI-native | 11 / 1 |
| Adjudicated groups, each with one final evidence check | 17 |
| Initial binary / subtype disagreements | 2 / 1 |
| Forced binary / subtype decisions (retained from evidence flags) | 14 / 2 |
| Parent holds accepted by user review | 2 |
| Trusted binary / subtype eligible | 6 / 3 |
| Evidence-flagged review queue | 14 |
| User-reviewed groups / user label overrides | 16 / 1 |
| Structural/grouping blockers | 0 |

The user reviewed all 16 previously flagged cases, accepted the original Luna judgments except for one explicit override, and accepted the earlier parent evidence holds on TRIRIGA and Alfabet. Their accepted `ai` / `ai_enabled` labels are included in the six trusted binary and three trusted subtype-eligible annotations. These manual dispositions do not alter the preserved Luna stages.

The user-directed override changes Evercoast Managed Services from the original Luna `non_ai` judgment to `ai` / `ai_enabled`. Because the retained AI evidence concerns separate Cloudbreak and Mavericks products, its binary and subtype evidence remain weak/forced; it is not trusted-eligible. The 14 remaining evidence-flagged groups remain excluded from trusted analysis. Human approval does not convert weak/forced evidence into source support.

The current workflow specification was later updated to `enterprise-ai-mention-v2`; this calibration and frozen stage artifacts remain under the earlier pinned rubric. The user override is recorded separately and does not silently rerun/relabel other stages. See [parent acceptance](PARENT_ACCEPTANCE.md), the [user review disposition](USER_REVIEW_DISPOSITION.md), and `user_review_decisions.json`.

## Files

- [Group labels](exports/product_ai_labels.csv): one annotation per group, separate binary/subtype evidence flags and trusted-use eligibility.
- [Record labels](exports/product_ai_record_labels.csv): deterministic propagation to all 21 selected source rows.
- [Review queue](exports/product_ai_review_queue.csv): 14 groups still carrying weak/forced evidence exclusions after manual review; all original 16 reviewed dispositions are in the ledger and [HTML case page](exports/flagged_cases.html).
- [Review ledger](exports/product_ai_review.jsonl): every stage's unchanged judgment, source excerpts/captures, native stage/run identities, prompt and input hashes.
- [Machine-readable report](exports/product_ai_labeling_report.json): distributions, provenance, resource telemetry and protocol limitations.

Run `python3 -B export_calibration.py` from this directory to regenerate the partial exports after checking pinned inputs and stage coverage. The source CSV and cleaner outputs are unchanged. The frozen calibration rubric hash remains pinned; the live workflow specification subsequently changed to v2 and its hash drift is reported rather than rewriting this historical run. Export regeneration was tested twice with byte-identical results; stage-checker and trusted-use self-tests passed.

## Resource and protocol findings

All 15 launched children (including stopped/failed attempts) used `openai-codex/gpt-6-luna`, high thinking. Telemetry reports **6,889,798 tokens**, comprising 1,187,120 input, 197,654 output and 5,505,024 cached-read tokens. Reported model cost is $0.27258924, **not an invoice or a reliable billing estimate**; parent orchestration and search-provider charges are excluded. Search/output/acceptance recovery overhead is included. No reliable full-run cost forecast has been established.

The successful verification-only continuation took about 17.35 minutes. This is not end-to-end labeling throughput: earlier research, user pauses and configuration recovery are separate. Initial stages acquired 55 pages and recorded 103 group-attributed discovery rounds; these are not the same as individual tool-call counts. The entire set of child sessions contains 25 search-tool calls and 10 page-fetch calls, many batched. Later verification/finalcheck reused retained material; adjudication added one four-query discovery call and no new page fetches.

Retained deviations are explicit: the user accepted the two existing four-round blind-stage exceptions; an adjudicator also batched four different product queries in one call, contrary to the group-scoped query rule. This did not exceed a per-group numeric cap, but future assignments must use group-scoped calls. Stage-reported counters sometimes include earlier work; native tool traces, not those sums, establish new-stage usage. Infrastructure failures were not treated as non-AI evidence, and completed judgments were recovered rather than rerun.

## Recommendation and approval boundary

The user has now reviewed the 16 cases and accepted the original calls except Evercoast, explicitly overridden to `ai` / `ai_enabled`. Fourteen evidence-flagged cases remain excluded from trusted analysis. The main evidence limitations are product/feature identity and incomplete historical/source coverage. The user-authored v2 workflow changes how future product-specific AI mentions/showcases are treated; it does not retroactively rewrite these frozen calibration judgments.

No remaining groups, model training, partitions, commits, pushes or merges have been performed. Processing the remaining 1,386 groups requires explicit user approval after this report. Existing historical-applicability, included-product and evidence rules remain unchanged.
