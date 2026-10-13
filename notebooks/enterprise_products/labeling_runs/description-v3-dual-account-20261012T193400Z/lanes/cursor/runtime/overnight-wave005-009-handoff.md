# Cursor wave005–009 handoff

**Status:** checkpoint ready for parent; this is a wave boundary, not dataset completion or user pause.

## Completed

- Finalized `batch-005` through `batch-009` using the frozen plan, `label_v3.py` helper, immutable selections, helper checkpoint registration, exact quote/schema/coverage validation, required same-verifier routing, and `finalize_run` exports.
- Added this wave: **100 unique descriptions and 102 source rows**. Lane cumulative progress is **180/620 descriptions, 182/639 rows**, with **440 descriptions / 457 rows remaining**. These lane numbers do not claim global coverage. Batches001–004 were left unchanged.
- Reconciliation counts for005–009: **30** (3, 9, 11, 3, 4); cumulative lane reconciliation count recorded in `PROGRESS.json`: 41. Final weak/forced binary flags across this wave: **20** (0, 5, 10, 3, 2); weak cases remain flagged/excluded. Independent AI subtype evidence was retained separately.
- Three structural-only repairs were made in new accepted artifacts, with original outputs/checkpoints preserved: batch005 Luna exact quote; batch006 Luna annotation ID; batch008 Haiku exact quote. Raw artifact hashes and repair provenance are saved; batch005’s initially incorrect self-reported recovery hashes were replaced with directly computed actual hashes. No semantic fields were changed during recovery.

## Batch artifacts

Each batch has a helper-pinned `manifest.json`, immutable selection/packet, `PARENT_ACCEPTANCE.json`, and six finalized exports (`description_labels.json`, `record_labels.json`, `review_ledger.json`, `review_queue.json`, `non_ai_candidates.csv`, `calibration_report.json`). All five current manifests were re-verified against pinned inputs, helper, checkpoints, and export hashes.

- `batches/batch-005/` — 20 descriptions / 22 rows; 3 reconciliations; one quote-only structural recovery.
- `batches/batch-006/` — 20 / 20; 9 reconciliations; one annotation-ID-only structural recovery.
- `batches/batch-007/` — 20 / 20; 11 reconciliations.
- `batches/batch-008/` — 20 / 20; 3 reconciliations; one quote-only structural recovery.
- `batches/batch-009/` — 20 / 20; 4 reconciliations.

Independent raw result/checkpoint hashes, and repair receipts where applicable, are preserved in each batch’s `runtime/independent-result-hashes.json` and private `agents/*/structural-recovery/` directories. Same-original-Luna reconciliation proposals, exact source text, concerns, checkpoints, and aggregate are preserved under `agents/blind/reconciliation/`. Human review queues and ledgers are retained for later review.

## Validation and operational observations

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s notebooks/enterprise_products -p 'test_*.py'`: **36 tests passed**.
- Prior-run baseline preservation: **1,387 files checked, zero hash changes**.
- Native Cursor CLI sessions used explicit `--model` and workspace paths, fresh per batch, in assigned panes only. Observed terminal banners: **Claude Haiku 5.5 300K High** and **GPT-5.6 Luna 272K High**; Luna contexts reported requested `gpt-5.6-luna-high`. Haiku contexts acknowledged requested `claude-haiku-5-5-thinking-high` but stated they cannot verify the thinking setting internally. These are transport observations, not token usage. No cost/billed-token metadata was available; those remain null. No native constrained decode is claimed.
- Both batch009 sessions were exited with Ctrl+D; `wF:p19` and `wF:p1A` were inspected and are shells. No workers remain active. No Git operations were performed; parent retains commits and global progress.

## Next safe action

Parent should verify immutable exports and recompute global exact-description-hash/source-reference coverage, then continue with frozen Cursor `batch-010` using fresh native Haiku/Luna contexts in the same assigned panes. Global progress and Git checkpoint commits remain parent-owned.
