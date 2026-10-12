# Parent acceptance of the 20-group calibration

All required Luna stages completed. Their binary/subtype judgments and original evidence flags are retained unchanged. Mechanical validation of all ten saved stage handoffs passed, including the exact seventeen adjudicated groups and their one final check. This is a partial model-reviewed annotation export, not gold-standard labels or a full-dataset export.

## Additional trusted-use exclusions

The final model marks the following two groups supported, but the parent does **not** accept them for trusted training/evaluation or trusted subtype analysis under the existing frozen rubric:

- **TRIRIGA bridge content and subscription**, source row 1042: the final rationale treats an AI claim in the imported dataset as satisfying the official-product-website claim rule. The dataset is not the vendor website, nor is it a traced reputable product-review source. The retained IBM announcement specifically introduces *new* AI monitoring in TRIRIGA Application Suite v11.6. It does not establish inclusion in this bridge/subscription item or its represented historical release. Retain the model's positive/enabled annotation but put it in the review queue with a parent applicability/evidence hold.
- **Alfabet**, source row 1051: the imported source description claims AI, and official 11.13 documentation genuinely documents an AI help assistant. The source version/deployment are unknown, so the current assistant cannot establish historical inclusion. The separate 11.9 AI Portfolio Management page documents governance/inventory of other systems' AI; managing an AI portfolio does not itself establish use of AI. Retain the model's positive/enabled annotation but exclude it from trusted use pending product/version-specific corroboration.

These holds are separate acceptance metadata, not parent-generated replacement labels and not a third label class. Preserve the six model-supported versus fourteen forced binary counts, and separately report the four groups accepted for trusted binary use versus sixteen groups excluded (fourteen model-forced plus these two holds). Trusted eligibility here is not an authorization to train or evaluate.

## Protocol observations

- The already accepted initial-stage exceptions remain: blind Kalibrate and ICP4I each used four discovery rounds rather than three. Actual counters and the user's waiver remain preserved.
- Adjudicator batch01 made one search-tool call containing four queries for four different products. It did not breach the per-group numerical cap, but violated the instruction that queries within one call concern the same group. Keep the trace and disclose this batching deviation; do not redo research to hide it. Future assignments must make one group-scoped call at a time.
- Later-stage counters sometimes copy/sum prior stages rather than count newly performed searches/pages. Native tool events are the source of observed resource use; reported counters remain unchanged in the review ledger. No additional page fetches occurred during verification/adjudication/finalcheck in the completed continuation.
- Search/configuration and output/acceptance failures consumed additional resource usage. Report these separately rather than treating the run as a clean throughput benchmark.

## Next authorization boundary

Pause before the remaining 1,386 groups. Do not silently loosen the historical applicability or included-product rule to increase supported counts. The parent recommends reviewing this calibration's evidence limitations and fixing the concrete cross-group-search/acceptance-packet issues before any full-run approval.
