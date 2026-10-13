# Binary AI/non-AI dataset preparation

This directory contains the offline preparation pipeline. Milestone 1 freezes the finalized enterprise `enterprise-description-only-v3` labels at source cutoff `28a32b79f8f4c7ab000e2e66ba7fd21202d3dd44`. It does not merge ToolBuzz, split data, fit features/models, choose thresholds, or evaluate previously unseen tools.

## Reproduce enterprise label freeze

Run from the repository root with Python 3 and Git (standard library only):

```sh
python3 notebooks/binary_dataset/freeze_enterprise_labels.py build
python3 -m unittest discover -s notebooks/binary_dataset -p 'test_*.py'
python3 -m unittest discover -s notebooks/enterprise_products -p 'test_*.py'
```

The script reads only Git-tracked files at the pinned cutoff using `git show`/`git ls-tree`; it does not read later working-tree labeling artifacts. It validates completed acceptance markers and finalized exports, exact source text and SHA-256, exact supporting quotations, binary/subtype fields, source-record joins, and record/description coverage. It stops on conflicting binary annotations, malformed exports, lost/duplicate mappings, source mismatch, or an existing non-empty output directory. Delete/rename an output directory only after explicit review; do not hand-edit generated data.

Generated paths (created only by the script):

- `data/binary_ai_dataset/v1/enterprise_descriptions.json` — one exact-text description row per finalized annotation, including weak/forced labels, subtype metadata, binary eligibility/exclusion reason, evidence and provenance.
- `data/binary_ai_dataset/v1/enterprise_records.csv` — every source row joined to its finalized description annotation and provenance; features/targets are not preselected here.
- `data/binary_ai_dataset/v1/manifest.json` — cutoff, input/export/artifact hashes, selection/normalization/deduplication policy versions and measured counts.

## Frozen counts

At the pinned cutoff: 1,438 cleaned source rows, 1,391 distinct exact descriptions and 1,406 product groups. Accepted finalized evidence covers **560 distinct descriptions, 577 rows and 571 source product groups**; **831 descriptions and 861 rows remain unlabeled**. Finalized description labels: 518 non-AI and 42 AI (24 `ai_native`, 18 `ai_enabled`; 13 subtype judgments are weak), including 104 weak/forced binary descriptions. Supported binary labels: **416 non-AI and 40 AI**. Weak/forced labels are retained for audit but ineligible (106 source rows, due to repeated exact descriptions). No identical description was exported by more than one accepted artifact (0 duplicate exports counted). These counts are generated and rechecked, not used as hard-coded generation targets.

Subtype values, rationales, quotes, provenance, product/source metadata and labels are metadata only. A weak AI subtype does not disqualify a supported binary label. Training features must use description text only. This phase makes no partition assignment and does not establish independent evaluation coverage.

## Scope and limitations

The source describes a dated enterprise-product snapshot and is not current-product truth or proof of actual feature use. AI/non-AI labels are description-based rubric judgments. Source/style leakage remains possible even when later splitting groups identical text and related tools. Historical v3 execution was not uniformly the earlier two-Luna setup: the accepted Cursor Haiku/Luna and Codex Luna lanes were explicitly authorized in pinned run-specific preparation/continuation receipts. The generated manifest records stage model IDs and checksums for those approvals and their acceptance evidence; the older two-Luna workflow prose is not treated as the execution record. This is not permission to use a model fallback in new work. There is no implemented registry/retrieval corpus here, so this does **not** claim previously-unseen-tool runtime evaluation. The private reuse permission recorded in `notebooks/enterprise_products/LABELING_WORKFLOW.md` is the approved scope; the legacy unresolved-license note in `data/technology-product-categorization/SOURCE.md` and `notebooks/enterprise_products/README.md` is stale and is not replaced with a public license claim or correspondence. The source permission/correspondence was not altered or published. The harness task IDs 4–7 are local todo IDs, not GitHub issues; this step did not mutate issue #4.

No model training, vectorizer/embedding fitting, classifier threshold selection, cross-source deduplication, or application implementation occurs in this milestone. Review generated files and all limitations before authorizing the next dataset-preparation milestone. Do not train until all four preparation milestones have passed separate review and the user has reviewed the resulting dataset.
