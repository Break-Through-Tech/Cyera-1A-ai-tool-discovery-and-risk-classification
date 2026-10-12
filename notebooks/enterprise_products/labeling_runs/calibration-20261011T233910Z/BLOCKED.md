# Calibration blocked — search infrastructure

The workflow `792352ce-da86-4559-8919-e80bfde8aade` is stopped. All four recorded children are stopped. The twenty-group calibration is incomplete; no completed labeler/blind/evidence-verifier pipeline exists and **zero groups have accepted final labels**.

## Cause

The requesting labeler reported HTTP 400 because the configured OpenAI web-search route selected `gpt-5.3-codex-spark`, unsupported for its ChatGPT account. Exa also returned HTTP 429 for its free MCP route. These are research infrastructure failures, not evidence that any product is non-AI.

The labeling model did not change: each saved child session records `openai-codex/gpt-6-luna`. No replacement search backend, alternate execution mode, or fallback labeling model was authorized or launched.

## Preserved work

- `labeler-batch-02/checkpoints/infrastructure-blocker.json`: exact failure, pending group IDs and discovery-only URLs; no completed judgments in that lane.
- `blind-batch-02/checkpoints/enterprise-7ac31d358d03a67becc7584222b72b9620ece17705166aa34c1e91878e7bfbf2.json`: one provisional blind-stage judgment, not an accepted final label. Its historical applicability and negative-evidence sufficiency still require the other stages; do not promote it into training or trusted analysis.
- `runtime/status.json` and `runtime/workflow-receipt.json`: terminal orchestration evidence.
- `blocked_report.json`: independent input-preservation checks, checkpoint inventory, child model records and saved-session usage counters.
- Native child session paths are retained in the report for recovery of discovery/fetch evidence and actual per-group research allowances. Checkpoint research counts are self-reported and must be reconciled against those tool logs before continuation.

All pinned original inputs still matched their checksums when the blocked report was generated. No source/cleaner artifacts, commits, pushes, merges, training or partition assignments were changed.

The stopped native workflow is not resumable. Recovery therefore requires a new same-protocol continuation using the frozen inputs and saved checkpoints, without rerunning completed group judgments or resetting consumed research allowances. Blind continuation must remain isolated from labeler/evidence judgments.

## Next action requiring approval

Diagnose and repair the web-search configuration, smoke-test one product lookup, and then continue only unfinished calibration work on the same GPT-6 Luna model. Do not change the global/user search configuration or select a new backend without explicit approval. First repair the deterministic unsupported-model route; do not merely repeat it or interpret rate-limited discovery as negative evidence.

No remaining-dataset work is authorized. The twenty-group report and user approval gate still apply after recovery. Reported token/cost counters are provider telemetry, not an invoice or a valid full-run cost estimate.
