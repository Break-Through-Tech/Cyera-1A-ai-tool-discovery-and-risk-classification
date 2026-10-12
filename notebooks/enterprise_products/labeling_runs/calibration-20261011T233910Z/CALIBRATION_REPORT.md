# Enterprise AI-labeling calibration — 20 groups

**Completed calibration; paused before the remaining 1,386 groups.** This is a partial, model-reviewed annotation set, not gold-standard ground truth, a training partition, or a complete dataset export.

## Results

| Measure | Result |
| --- | ---: |
| Product groups / retained source rows | 20 / 21 |
| AI / non-AI groups | 11 / 9 |
| AI-enabled / AI-native | 10 / 1 |
| Adjudicated groups, each with one final evidence check | 17 |
| Initial binary / subtype disagreements | 2 / 1 |
| Model-forced binary / subtype decisions | 14 / 1 |
| Additional parent trusted-use holds | 2 |
| Trusted binary eligible / review queue | 4 / 16 |
| Structural/grouping blockers | 0 |

All groups have a binary label. Forced and parent-held annotations remain visibly excluded from trusted training/evaluation; this exclusion is metadata, not an additional label class. Subtype support is separate from binary support. Only one AI-positive group currently qualifies for trusted subtype analysis.

The four parent-accepted binary annotations are DataRobot Enterprise AI (`ai`, `ai_native`), Spring.NET, PingPlotter Pro and Dameware Remote Everywhere (all `non_ai`). These are evidence-backed operational annotations, not proof about every release or employee usage.

TRIRIGA and Alfabet retain the Luna `ai` / `ai_enabled` judgments but have additional parent evidence/applicability holds. Their imported descriptions are not official product-site claims, and current AI documentation does not establish inclusion in their represented historical product/version. See [parent acceptance](PARENT_ACCEPTANCE.md).

## Files

- [Group labels](exports/product_ai_labels.csv): one annotation per group, separate binary/subtype evidence flags and trusted-use eligibility.
- [Record labels](exports/product_ai_record_labels.csv): deterministic propagation to all 21 selected source rows.
- [Review queue](exports/product_ai_review_queue.csv): 16 groups with reasons.
- [Review ledger](exports/product_ai_review.jsonl): every stage's unchanged judgment, source excerpts/captures, native stage/run identities, prompt and input hashes.
- [Machine-readable report](exports/product_ai_labeling_report.json): distributions, provenance, resource telemetry and protocol limitations.

Run `python3 -B export_calibration.py` from this directory to regenerate the partial exports after checking pinned inputs and stage coverage. The source CSV, cleaner outputs, canonical plans and frozen rubric are unchanged. Export regeneration was tested twice with byte-identical results; stage-checker and trusted-use self-tests passed.

## Resource and protocol findings

All 15 launched children (including stopped/failed attempts) used `openai-codex/gpt-6-luna`, high thinking. Telemetry reports **6,889,798 tokens**, comprising 1,187,120 input, 197,654 output and 5,505,024 cached-read tokens. Reported model cost is $0.27258924, **not an invoice or a reliable billing estimate**; parent orchestration and search-provider charges are excluded. Search/output/acceptance recovery overhead is included. No reliable full-run cost forecast has been established.

The successful verification-only continuation took about 17.35 minutes. This is not end-to-end labeling throughput: earlier research, user pauses and configuration recovery are separate. Initial stages acquired 55 pages and recorded 103 group-attributed discovery rounds; these are not the same as individual tool-call counts. The entire set of child sessions contains 25 search-tool calls and 10 page-fetch calls, many batched. Later verification/finalcheck reused retained material; adjudication added one four-query discovery call and no new page fetches.

Retained deviations are explicit: the user accepted the two existing four-round blind-stage exceptions; an adjudicator also batched four different product queries in one call, contrary to the group-scoped query rule. This did not exceed a per-group numeric cap, but future assignments must use group-scoped calls. Stage-reported counters sometimes include earlier work; native tool traces, not those sums, establish new-stage usage. Infrastructure failures were not treated as non-AI evidence, and completed judgments were recovered rather than rerun.

## Recommendation and approval boundary

**Review the 16 flagged cases and address the concrete prompt/evidence failures before scaling.** The main limitation is missing historical version, feature inclusion and product/SKU mapping—not a missing binary-label class. Do not silently relabel contemporary product capabilities as historical evidence or promote dataset descriptions to official-site claims.

No remaining groups, model training, partitions, commits, pushes or merges have been performed. Processing the remaining 1,386 groups requires explicit user approval after this report. Existing historical-applicability, included-product and evidence rules remain unchanged.
