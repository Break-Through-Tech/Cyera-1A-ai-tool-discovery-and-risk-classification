# Binary AI/non-AI dataset preparation

Offline preparation is frozen through v4 at source cutoff `28a32b79f8f4c7ab000e2e66ba7fd21202d3dd44`. The user reviewed preparation and notebook Steps 1–3 and approved held-out testing. **Step 4 freezes the selected C=10, balanced model at a 0.5 AI score cutoff before evaluating test.** Preparation itself performed no model fitting. Notebook preprocessing and models fit train only; settings were selected on validation. No test-based tuning, calibration, model export, or application work is implemented.

## First baseline notebook — Step 4 held-out test

Open [first_binary_baseline.ipynb](first_binary_baseline.ipynb) for dataset integrity
checks, class/source summaries, dummy/keyword validation baselines, and **train-only
TF-IDF + logistic regression**. Step 3 compares `C={0.1,1,10}` with ordinary versus
balanced class weighting, selecting by pooled validation macro-F1 at the default
0.5 cutoff. Exact ties retain the first setting (lower C, then ordinary weighting).
The pipeline learns word unigrams/bigrams with `min_df=2`; source metadata is not a
feature. Step 4 verifies the approved model/cutoff before loading test descriptions;
it evaluates only that learned model and the unchanged dummy/keyword baselines.

From the repository root (Python 3):

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r notebooks/binary_dataset/requirements.txt
python -m jupyter lab notebooks/binary_dataset/first_binary_baseline.ipynb
```

Select the Python 3 kernel and run all cells from top to bottom. The notebook
locates the repository from its working directory, reads the frozen v4 artifacts
without modifying them, and fails if their recorded checksums/counts no longer
match. Step 2 reports per-class precision/recall/F1, macro-F1, confusion matrices,
error counts and previews, pure enterprise and enterprise-member cohorts, and
AIToolBuzz-member AI recall. Member cohorts include merged examples and overlap;
metrics count model examples once per cohort, not original source-record members.
The rule has no negation handling and returns labels rather than confidence scores.
Step 3 adds per-class PR-AUC/AP, all six setting comparisons, selected-model cohort
results, learned terms, and validation mistakes. Learned probability outputs are
uncalibrated scores, not verified confidence. Convergence warnings fail training.
Step 4 reports held-out pooled/per-class metrics, PR-AUC/AP, source-specific behavior,
all six enterprise AI decisions, and diagnostic error previews. Test macro-F1 is
**0.9593** with **5 false positives and 5 missed AI examples**; enterprise AI recall
is only **3/6**, versus **6/6** for the keyword rule. Review the source-specific
limitations alongside pooled results. The existing requirements cover this stage;
no model bundle is exported.

**The test split is now used for the frozen experiment.** Do not tune from its results
or use it to choose future models/rules/thresholds while claiming independent final
performance. Running all cells reproduces the same settled experiment; the test stage
refuses a selected configuration other than the approved C=10/balanced/0.5 policy.

## Frozen phase artifacts

- [v1 enterprise-label audit freeze](../../data/binary_ai_dataset/v1/) — 560 finalized descriptions / 577 rows; supported pool 416 non-AI + 40 AI descriptions. Weak/forced binary judgments are excluded; subtype weakness alone is permitted.
- [v2 unified candidate merge](../../data/binary_ai_dataset/v2/) — 16,688 candidates: 16,232 AIToolBuzz AI rows and 456 supported enterprise descriptions; 530 blank catalog descriptions excluded.
- [v3 duplicate, identity, and conflict review](../../data/binary_ai_dataset/v3/) — 16,669 eligible examples in 16,444 leakage groups; 19 normalized duplicate removals, 44 near-text pairs, 170 name-review candidates, zero quarantines.
- [v4 frozen splits](../../data/binary_ai_dataset/v4/) — leakage-group-safe partitions and text-only exports. `manifest.json` records measured counts/support, hashes, seed/policy and test-slice limitations; `assignments.json` maps each example to a group and partition; CSV metadata is in separate JSON files.

## v5 — complete enterprise labels

v1–v5 use the earlier operational definition (every AIToolBuzz entry is AI; any enterprise product AI mention is AI). [ADR 0001](../../docs/adr/0001-ai-tool-requires-own-ai-functionality.md) supersedes it for future datasets; these frozen versions are not relabeled.

[v5](../../data/binary_ai_dataset/v5/) is built by `build_v5.py` from source cutoff `7f72140a7205525b01758f6b1e462c11893c9387`, after all 1,391 enterprise descriptions were labeled or quarantined. It uses every accepted v3 export, where a `-parent-integration` copy supersedes its original. The four semantically held batches are replaced by the record-level release in `runtime/record-level-release-20261021/`, and the seven quarantined descriptions are excluded. Weak/forced labels stay excluded, which leaves 1,081 supported enterprise descriptions (1,007 non-AI, 74 AI).

Every v4 member keeps its v4 partition. Only the 624 wholly new leakage groups are placed, using the same greedy group-safe scoring with seed `20261022`. A group that would join v4 groups from different partitions fails the build. Metadata and `assignments.json` flag `new_in_v5` examples. The v4 test members were already scored once, so only the 94 `new_in_v5` test examples are previously unscored.

```sh
python3 notebooks/binary_dataset/build_v5.py build
.venv/bin/python notebooks/binary_dataset/evaluate_v5.py
```

`evaluate_v5.py` refits the frozen v4 model (C=10, balanced, 0.5 cutoff) from v4 train and fails unless it reproduces the v4 test macro-F1. It scores that model on v5 test, re-selects C/weighting on v5 validation with the same six-setting grid, scores the selected model once on test, and writes `v5_evaluation.json` with results by slice.

## Reproduce and test

Run from repository root with Python 3 (standard library only). Reproduce into a fresh temporary directory through the existing `build(out)` API, then compare the complete manifest and every recorded output hash with the frozen v4 artifacts; this leaves `data/binary_ai_dataset/v4/` untouched:

```sh
python3 - <<'PY'
import hashlib
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, "notebooks/binary_dataset")
from split_unified_dataset import build

frozen_dir = Path("data/binary_ai_dataset/v4")
frozen = json.loads((frozen_dir / "manifest.json").read_text())
with tempfile.TemporaryDirectory(prefix="binary-ai-v4-replay-") as temp:
    replay_dir = Path(temp) / "v4"
    replay_manifest = build(replay_dir)
    assert replay_manifest == frozen
    assert (replay_dir / "manifest.json").read_bytes() == (frozen_dir / "manifest.json").read_bytes()
    for name, expected in frozen["output_sha256"].items():
        assert hashlib.sha256((replay_dir / name).read_bytes()).hexdigest() == expected, name
PY
python3 -m unittest discover -s notebooks/binary_dataset -p 'test_*.py'
python3 -m unittest discover -s notebooks/enterprise_products -p 'test_*.py'
```

The builder verifies frozen v3 checksums and cutoff; refuses to overwrite/alias an existing output path; and assigns whole leakage groups deterministically with seed `20261014` and policy `whole-leakage-group-greedy-stratified-v1`. It balances toward 70/15/15 across total examples, labels, and member source/class support; measured deviations are reported, not forced at the expense of grouping. `description_text` is the only feature allowlist. CSVs contain example ID, description text, and target label; identity/source/taxonomy/provenance metadata is stored separately.

The enterprise-only test slice is reported as a construction/quality check only; after freeze, test data must not select models or thresholds. Source/style confounding remains: AIToolBuzz contributes AI-only rows while enterprise contributes both classes. This dated snapshot is not current product truth or proof of feature use. No registry/retrieval implementation exists, so there is no universal or runtime previously-unseen Tool generalization claim. Reuse is limited to the private permission scope recorded in `notebooks/enterprise_products/LABELING_WORKFLOW.md`; no public license claim or correspondence is asserted. Do not hand-edit generated artifacts. **Do not train until independent review and user review have passed.**
