# Frozen retrieval evaluation protocol v1

The benchmark is documentation retrieval only. Labels were drafted by
reading the actual indexed excerpts in source order, without using ranked
results as labels. A teammate can review the exact IDs and rationales in
`benchmark-v1.json`. Grade 2 directly supports the requested answer or
one required part. Grade 1 offers related background. Grade 0 is implicit.
These are analyst-drafted judgments pending independent human review.
Correct a label by creating a new benchmark version and recording the
change. Once held-out results have been inspected, use new held-out
questions for a new independent calibration cycle.

The 36/24 split is recorded on each question. All members of a labeled
paraphrase family stay together. All 13 earlier smoke questions are in
calibration. Each category is represented in both partitions. The corpus
and model are frozen via the snapshot version and pinned model revision.

## Metrics and selection

All ranking cutoffs are five. Passage metrics deduplicate retrieved chunks
by first occurrence, with no backfill beyond the method's actual returned
results. Chunk metrics deduplicate by chunk ID. Hit Rate is the share of
answerable questions with a Grade 2 hit. Precision is Grade 2 hits divided
by five even for a short or empty list. Recall divides Grade 2 hits by all
judged Grade 2 units. MRR@5 averages the reciprocal of the first Grade 2
rank, with misses scoring zero. nDCG@5 discounts gains of 3 for Grade 2,
1 for Grade 1, and 0 for unjudged results, dividing each gain by
`log2(rank + 1)` and normalizing by the best possible judged list.
Ranking metrics are macro-averaged over answerable questions only.

Out-of-domain correct abstention is the share returning an empty list.
False abstention is the share of answerable questions returning an empty
list. A nonempty irrelevant answerable result is a ranking miss and not
an abstention. In-domain unsupported questions report Grade 1 background
hits and empty results separately. They do not measure answer sufficiency
or actual Gemini behavior. Multi-evidence coverage is the fraction of
required groups with at least one matching result, macro-averaged over
multi-evidence questions. Each group's IDs are alternative qualifying
excerpts. Passage-level mapping can collapse separate needs into one
passage, so use chunk coverage for precise evidence coverage. Group
coverage and full coverage are both reported.

Distinct passages counts unique original passages in an actual result
list. Timing uses mean, median, and nearest-rank p95 over actual
sequential retrieval calls, excluding preload and metric computation.
Parameter sweeps reuse complete keyword and cosine rankings and do not
report latency.

The fixed calibration utility is 30% average passage/chunk direct Hit
Rate, 20% average passage/chunk nDCG, 15% chunk multi-evidence coverage,
and 35% out-of-domain empty rate. Prefer the incumbent on exact ties,
then the first enumerated alternative. Start from production defaults.
Sweep semantic cutoff, then independently sweep hybrid cutoff, k, depth,
cap, and final limit one factor at a time. Keep the winning setting at
each stage. Freeze the selected settings and benchmark/model identity in
`selection.json` before evaluating the held-out set. No changes to the
application defaults are part of this protocol. A winner of this staged
search is not necessarily a global optimum.
