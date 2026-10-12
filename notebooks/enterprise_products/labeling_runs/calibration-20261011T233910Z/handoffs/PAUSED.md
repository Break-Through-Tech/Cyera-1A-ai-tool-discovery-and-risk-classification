# Calibration paused after handoff recovery

The recovery workflow `7a870d41-7399-4261-9367-d6c061fe72a4` is stopped. No pending supervisor requests remain at the last inspection; the final labeler was instructed to stop research and preserve its complete result before stopping the enclosing run.

Forty initial stage judgments (twenty labeler plus twenty independent blind judgments) were recovered from complete `structured_output.value` tool calls in the saved native child sessions. New deterministic handoffs are `labeler-01.json`, `blind-01.json`, `labeler-02.json`, and `blind-02.json`. No completed research was rerun. These are candidates, not accepted final labels.

Output packaging defects: labeler batch 01 wrote an empty aggregate despite complete checkpoints; the blind stages returned full structured data without writing required file-only aggregates; labeler batch 02 used a wrong output directory and wrote malformed aggregate JSON. Original artifacts are preserved. The eleven exclusively agent-created misrouted files were byte-verified against native write calls and moved under `misrouted-labeler-02/`; hashes and original paths are in `misrouted_files.json`.

`resource_audit.json` reconciles actual cumulative searches and page reads against both original and recovery sessions. Blind batch 01 used four search rounds, not the approved three, for Kalibrate and ICP4I; its recorded counts were clamped to three to fit the metric schema. Dameware's blind count was reported as two but actually three, within the cap. Actual audited counts supersede self-reports. No page-read cap violations were found. Do not falsify counters to pass a schema or claim the resource gate passed.

Next execution requires explicit disposition of the two search-cap exceptions. Recommendation: retain the already acquired evidence with truthful counters and visible deviations, perform no further labeler/blind research, then continue only the approved evidence verification and conditional adjudication stages. Do not increase future research budgets automatically.

Before that continuation, correct the handoff contract: record observed metrics without schema ceilings that encourage clamping; serialize complete structured results rather than rely on manually copied JSON; mechanically check bound artifact content and selected-group coverage before downstream consumption. These are operational repairs, not changes to the labeling rubric.

All pinned original inputs remain unchanged. Zero accepted final labels; the remaining dataset is not authorized.
