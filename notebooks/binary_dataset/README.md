# Binary AI/non-AI dataset preparation

Offline preparation is frozen through v4 at source cutoff `28a32b79f8f4c7ab000e2e66ba7fd21202d3dd44`. Final state: **PREPARED AWAITING USER REVIEW**. No model training, vectorizer/embedding fitting, threshold selection, or application work has occurred.

## Frozen phase artifacts

- [v1 enterprise-label audit freeze](../../data/binary_ai_dataset/v1/) — 560 finalized descriptions / 577 rows; supported pool 416 non-AI + 40 AI descriptions. Weak/forced binary judgments are excluded; subtype weakness alone is permitted.
- [v2 unified candidate merge](../../data/binary_ai_dataset/v2/) — 16,688 candidates: 16,232 AIToolBuzz AI rows and 456 supported enterprise descriptions; 530 blank catalog descriptions excluded.
- [v3 duplicate, identity, and conflict review](../../data/binary_ai_dataset/v3/) — 16,669 eligible examples in 16,444 leakage groups; 19 normalized duplicate removals, 44 near-text pairs, 170 name-review candidates, zero quarantines.
- [v4 frozen splits](../../data/binary_ai_dataset/v4/) — leakage-group-safe partitions and text-only exports. `manifest.json` records measured counts/support, hashes, seed/policy and test-slice limitations; `assignments.json` maps each example to a group and partition; CSV metadata is in separate JSON files.

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
