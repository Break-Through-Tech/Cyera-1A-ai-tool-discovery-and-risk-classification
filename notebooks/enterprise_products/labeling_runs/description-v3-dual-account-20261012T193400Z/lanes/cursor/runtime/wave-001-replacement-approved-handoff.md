# Cursor replacement-approved wave 001 handoff — stopped on model startup error

## Outcome
Stopped during batch-001 startup after a required-model rejection by the native Cursor CLI. No annotation prompt was submitted and no annotation or result was produced. Batches 002–005 were not launched. This is an execution/configuration blocker, not a weak label or incomplete data judgment.

## Scope and reuse
- Reused the already-frozen `lanes/cursor/batches/batch-001`; did **not** call `freeze_run`, `select_descriptions`, or `assign_stage` again and did not overwrite existing inputs, selection, or stage assignments.
- Pre-launch helper/manifest verification passed: immutable inputs, packets and assignments; exact 20 selected descriptions and 20 source references; assigned models match the frozen plan.
- The existing batch worker observation is preserved. Detailed new attempt receipt: `runtime/wave-001-replacement-blocker.json`.

## Native execution observations
- Parent explicitly cleared the temporary hold after same-native-protocol inline-mode correction.
- Labeler: native `herdr_agent start` on `wF:p19`, with `--model claude-haiku-5-5-thinking-high` and the explicit batch-001 labeler workspace. The CLI showed `Claude Haiku 5.5 300K High`. No annotation prompt was submitted. After the verifier failure, the labeler was exited with native `ctrl+d`; the pane was inspected at a real shell prompt.
- Blind verifier: attempted native start on `wF:p1A` with `--model gpt-5.6-luna-high` and the explicit batch-001 blind workspace. Native startup timed out; inspection of the terminal showed the exact CLI rejection: `Cannot use this model: gpt-5.6-luna-high. Available models:`. No verifier agent registered. No retry, model substitution, permission/account change, or execution fallback was attempted.
- Final lifecycle inspection showed no registered annotation workers; both assigned panes were at shell prompts. The previous CLI text in the terminal was history, not an active session.

## Integrity, tests, counts
- Batch-001 private checkpoint/result counts: labeler 0, blind 0; helper-accepted stage checkpoints: 0; no result envelopes exist.
- Cursor lane: **0 newly completed descriptions / 0 rows**, **0 finalized batches**, **620 descriptions / 639 rows remaining**, `active_workers: 0`. Five-batch wave incomplete; only batch-001 was attempted.
- Enterprise suite: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s notebooks/enterprise_products -p 'test_*.py'` — **36 tests passed**.
- Baseline integrity: **1,387/1,387** entries in `lanes/cursor/PRIOR_RUN_BASELINES.json` matched; no mismatches.
- `cost_usd` and `billed_tokens` are null; no billing evidence was available.

## Blocker and next safe action
`PROGRESS.json` records `stopped_on_required_model_startup_error`. Parent directed: no model substitution or retry is authorized; this triggers the existing **both-lanes major-error stop**. Parent will safely stop/checkpoint Codex and obtain any new model/provider decision from the user. The prepared batch-001 remains unchanged. No further annotation launches occurred after the blocker; do not resume absent new explicit approval resolving model availability.

Skipped: no reconciliation, comparison, acceptance, export, or later-batch preparation was possible before both independent results existed. No semantic labels were authored here.
