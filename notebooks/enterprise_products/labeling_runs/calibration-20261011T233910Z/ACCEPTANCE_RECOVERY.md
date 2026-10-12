# Acceptance-contract recovery

The verification-only workflow `0bfd8833-f375-4f43-abc8-58713673c61f` stopped after the harness rejected evidence-batch-02 with `Acceptance rejected: commands-run evidence missing from child report`. Its actual ten-record structured output passed the parent's stage checker. Preserve and consume `handoffs/evidence-02.recovered.json`; DO NOT rerun this completed evidence stage. The run stopped evidence-batch-01, which saved its Kalibrate checkpoint; reuse it without repeating that completed judgment.

This is harness contract configuration, not product evidence or a wrong-label verdict. Do not weaken required provenance, research limits or stage checks. The next continuation uses a required separate native `acceptanceReport`, plus real lightweight validation commands and the same host handoff check. No installed harness code or global settings are edited.

## Each unfinished/new stage

Read your own checkpoints first. Batch01 evidence continues unfinished judgments only. Checkpoint every newly completed group at the explicit absolute checkpoint path. Preserve real initial-stage research counters in their own ledgers; do not confuse their sums with new research performed in this stage.

The researcher role has no shell/command-runner tool. The parent has performed the actual `python3 -B <absolute run>/check_stage.py --self-test` (nine cases passed), current-checkpoint validation and `git status --short` (no staged files). Read `handoffs/parent_validation_commands.json` for timestamps, scope and outputs. Cite these real parent-performed commands in the separate acceptance report, explicitly identifying the parent as executor; never pretend this child ran them. No tool/model/execution fallback is needed. Inspect newly written checkpoints against the schema by reading their files; do not claim the parent's earlier check validated newly created checkpoints. The configured host gate validates your subsequently persisted complete aggregate. A supported label still requires authentic inspected product evidence.

Submit your complete stage object as the native `structured_output` tool's `value`, AND submit its separate `acceptanceReport` argument. Do not add acceptance fields to the stage object. The report must truthfully include:

- `criteriaSatisfied`: criterion `criterion-1`, status `satisfied` only if exact assigned coverage, proper binary/subtype fields and evidence limitations are present; describe evidence briefly.
- `changedFiles`: only your checkpoint artifacts (or empty if none newly written); `testsAddedOrUpdated`: empty, because no project tests were changed.
- `commandsRun`: actual parent-performed commands from the validation evidence, their result (`passed`, `failed` or `not-run`) and truthful summaries explicitly naming the parent executor and this child's lack of command tools.
- `validationOutput`: actual self-check/record-validation results, not a fictional run; distinguish previously checked checkpoints from newly written ones.
- `residualRisks`: real evidential limitations/forced judgments; an empty array is valid when none apply.
- `noStagedFiles`: true based on the recorded parent git-status verification; keep its timing/scope clear and never stage or unstage files. The child has no authority to modify the index.

If a validation command fails, preserve outputs and report the blocker. Do not claim it passed. Do not manually write the aggregate. The runtime persists the structured value and acceptance report independently.

Remain within the approved twenty groups. The parent accepts and exports only after checking saved results, authentic sources, required stage coverage and actual research/resource counts.
