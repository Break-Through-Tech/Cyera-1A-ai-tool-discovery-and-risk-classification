# CPU BGE experiment

This is an explicit experimental alternative to ADR 0003's ONNX runtime. It does
not promote a model, alter the frozen results, or replace the backend defaults.
Catalog categories are source labels, not reviewed truth. A positive training
loss or parameter update does not establish better classification accuracy.

## Environment

Target: CPython 3.12, Windows x64 (AMD64), CPU float32. ARM64 and other Zenbook
variants are not validated. The implementation machine reports Windows x64 and
an AMD64 Family 26 Model 104 processor. See observed pilot measurements below;
other machines remain unbenchmarked. Inspect the generated manifest for actual
RAM, processor, peak observed process RSS, parameter counts, and timings.

Run these commands from the repository root. If `py` is unavailable, install
CPython 3.12 x64 and substitute its full executable path in the first command.
Training packages stay out of the backend's default dependencies.

```powershell
py -3.12 -m venv .venv-training
.\.venv-training\Scripts\python.exe -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
.\.venv-training\Scripts\python.exe -m pip install -r notebooks/category_classification/requirements-training.txt
.\.venv-training\Scripts\python.exe -m pip check
.\.venv-training\Scripts\python.exe -c "import torch, platform; print(platform.machine(), torch.__version__, torch.version.cuda)"
$env:HF_HOME = "$PWD\.cache-training\huggingface"
$env:SENTENCE_TRANSFORMERS_HOME = "$PWD\.cache-training\sentence-transformers"
```

The last check should show AMD64, PyTorch 2.6.0 with a CPU build, and CUDA `None`.
The pinned Sentence Transformers 3.4.1 / Transformers 4.48.3 combination uses the
PyTorch backend, not compilation or mixed precision. No reporting service is used.
The CPU wheel installation command follows [PyTorch's versioned instructions](https://pytorch.org/get-started/previous-versions/).
Model loading uses the documented [SentenceTransformer revision and backend arguments](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html).

The pinned packages installed successfully on CPython 3.12.10 Windows x64 during
implementation. Offline training tests and the real BGE pilot both ran on CPU.

## Pilot and training

```powershell
.\.venv-training\Scripts\python.exe notebooks/category_classification/finetune_bge.py --help
.\.venv-training\Scripts\python.exe notebooks/category_classification/finetune_bge.py --pilot --output artifacts/category_finetuning/zenbook-pilot
```

Inspect `training_manifest.json` and `training_log.jsonl` before choosing to run:

```powershell
.\.venv-training\Scripts\python.exe notebooks/category_classification/finetune_bge.py --max-steps 64 --max-triplets 256 --checkpoint --output artifacts/category_finetuning/zenbook-run-01
```

Defaults: CPU float32, 128 tokens, final BERT encoder block only, one triplet per
microbatch, four microbatches per update, AdamW at 1e-5 with 0.01 decay, cosine
triplet margin 0.1, gradient norm clip 1, two CPU threads, zero loader workers,
seed 20261014. Pilot stops at eight updates; ordinary training at 64. Triplets are
shuffled deterministically each epoch, with the permutation, cursor and independent
shuffle RNG saved in each boundary checkpoint. Partial accumulation at epoch boundaries
uses the actual triplet count. Fully inactive groups call the optimizer with no
gradients, preventing weight decay from creating an apparent learning result.
There is no automatic search or larger run after a pilot.

For lower memory, add `--max-length 64 --accumulation 1`. Reducing accumulation
changes effective batch size; it usually does not lower the peak activation
memory of a single microbatch. A 64-update budget is a resource bound, not an
accuracy promise. The pilot estimate is approximate training time, including
boundary checkpoints, and excludes downloads, final model save/reload validation,
KNN validation, and index building. RSS is sampled, so brief peaks may be missed.

The default available-memory reserve is 2 GiB (`--reserve-gib`). Memory is checked
before model load and at each microbatch/update. A low-memory event finishes the
current update, saves, and stops. This is a best-effort guard, not a hard limit;
model loading or a microbatch can still exceed available RAM.

Ctrl+C requests a stop at the next optimizer boundary, with random states,
optimizer, model and progress in `checkpoint/state.pt`. Every boundary is saved
atomically; a crash resumes from the last successful boundary. Resume an
incomplete run with the exact original settings plus `--resume`:

```powershell
.\.venv-training\Scripts\python.exe notebooks/category_classification/finetune_bge.py --max-steps 64 --max-triplets 256 --checkpoint --resume --output artifacts/category_finetuning/zenbook-run-01
```

Only load checkpoints created by your local experiment. Completed runs are never
overwritten. Checkpoints are removed after success unless `--checkpoint` was used.

## Data and artifacts

Existing v1 split hashes and disjoint IDs/groups are verified without reshuffling.
Sampling uses training descriptions only, approximately balances eligible anchor
categories, excludes conflicting/identical normalized text, and requires three
distinct existing groups. It never enumerates all triples. Validation/test text,
predictions, employee activity, category-name augmentation and Gemini output do
not enter training. `triplets.jsonl` records tool IDs, groups and categories.

Optional `--reviewed-labels annotations.json` accepts:

```json
{"version": "review-1", "provenance": "reviewer and source reference", "labels": {"training-tool-id": "Existing Category"}}
```

Overrides must reference training IDs and existing categories. Hashes and label
provenance are recorded. Evaluation and export reuse those overrides for the
experimental catalog; the deployed baseline retains its original labels.

Each new `artifacts/category_finetuning/<run>/` contains `model/`,
`training_manifest.json`, `triplets.jsonl`, `training_log.jsonl`, and optionally
`checkpoint/`. The manifest records settings, model revision, packages, dataset
hashes, parameter counts, status, timings, nonzero gradients and whether trainable
parameters changed while frozen parameters stayed unchanged. No active loss means
the run did not demonstrate learning. A content fingerprint covers every saved
model/tokenizer file plus sequence length, pooling and normalization; the existing
model-name embedding cache is never used.

## Validation and index export

The training environment also needs the backend's ONNX packages to evaluate the
deployed candidate (these do not change its production installation):

```powershell
.\.venv-training\Scripts\python.exe -m pip install fastembed==0.9.1 onnxruntime==1.31.1
.\.venv-training\Scripts\python.exe notebooks/category_classification/evaluate_finetuned.py --run artifacts/category_finetuning/zenbook-run-01 --quick 16
.\.venv-training\Scripts\python.exe notebooks/category_classification/evaluate_finetuned.py --run artifacts/category_finetuning/zenbook-run-01
.\.venv-training\Scripts\python.exe notebooks/category_classification/export_finetuned_index.py --run artifacts/category_finetuning/zenbook-run-01
# Recheck an existing export, including the backend's local inference adapter:
.\.venv-training\Scripts\python.exe notebooks/category_classification/export_finetuned_index.py --run artifacts/category_finetuning/zenbook-run-01 --verify-only
```

Encoding batches default to four; use `--batch-size 1` to reduce memory. Both
PyTorch candidates use the run's token limit (normally 128). The third uses the
existing deployed index and ONNX preprocessing. Full validation scores all 2,739
validation descriptions and 106 validation homepages. Quick mode records a fixed
sorted subset in `validation-quick/evaluation.json`; it is only a development check, never a
replacement for full validation. Index building always embeds all training tools.
Scoring calls the actual backend `NeighborIndex.vote`, including stable neighbor
ordering, clipped similarity weights, alphabetical label ties and k=15.

New evaluations write a fresh comparison directory (or an explicit `--output`),
preserving existing reports. Each candidate has `descriptions.jsonl` and
`homepages.jsonl` with example IDs, forced predictions, winning shares, answered
flags, neighbor IDs, neighbor labels and similarities. Reports include accuracy,
macro-F1, per-category results and confusion matrices, neighbor category agreement, coverage and accuracy
among answers at the existing cutoff 0.468914118995349, plus trained-versus-original
accuracy deltas. Negative or zero deltas are retained. Neither model is discarded.
No replacement cutoff is selected here. Any future cutoff selection must use
validation only and disclose coverage and the small homepage sample size. The old
test split is read only for hash/isolation checks and excluded IDs, never scored.
Fresh held-out tools are necessary for an independent final performance claim.

The new `index/` has `embeddings.npy`, `tools.csv`, and `manifest.json`, in frozen
training order. It records excluded validation/test/catalog-held-out IDs, dataset
hashes, vector and table hashes, model fingerprint, dimension, CLS pooling,
normalization, sequence length, k and cutoff. Nonfinite or nonunit vectors fail
export. Different checkpoints must never share an index.

## Explicit local backend inference

Install the training requirements into the environment running the backend only
if selecting this experimental path. Keep the ordinary backend environment for
FastEmbed usage. Then select the pair together before starting the backend:

```powershell
$env:CATEGORY_EXPERIMENT_MODEL = "$PWD\artifacts\category_finetuning\zenbook-run-01\model"
$env:CATEGORY_NEIGHBOR_INDEX = "$PWD\artifacts\category_finetuning\zenbook-run-01\index"
```

The saved model loads once on CPU through the `Embed` callable, in inference mode,
with the index's token limit and normalized float32 output. Mismatched model
contents, vector dimensions, table/vector hashes or k/cutoff fail validation.
Assigned/unresolved results and neighbor evidence follow the existing classifier.
Remove both environment variables to return to defaults. Local PyTorch checkpoints
cannot be passed to the pinned remote FastEmbed loader. ONNX export is future work.

## Verification

```powershell
.\.venv-training\Scripts\python.exe -m pytest notebooks/category_classification/finetuning/test_experiment.py -q
# In the existing backend dev environment, from backend/:
python -m pytest tests/test_category_classification.py -q
```

Offline tests construct tiny local random BERT weights/tokenizer and do not
download BGE. They verify group-isolated reproducible sampling, conflicting text
exclusion, finite active-loss backpropagation, frozen parameters, partial gradient
accumulation, model reload (atol 1e-6, rtol 1e-5), fingerprints and backend votes.
The explicit real-model pilot additionally checks architecture, actual model
updates, frozen weights and saved-model reload. Review its observed result before
recommending a longer experiment.

## Observed implementation pilot (2026-11-04)

`artifacts/category_finetuning/implementation-pilot/` is an ignored local artifact.
It used the documented defaults and original catalog labels, with `--pilot --checkpoint`.
On Windows 11 AMD64 (12 logical CPUs, restricted to two training threads), installed
RAM was 31.15 GiB and available RAM before loading was 13.10 GiB.

| Measurement | Observed |
|---|---:|
| Total / trainable parameters | 33,360,000 / 1,774,464 |
| Optimizer updates / microbatches | 8 / 32 |
| Training time / time per update | 6.54 s / 0.818 s |
| Peak sampled process RSS | 618.1 MiB |
| Mean triplet loss | 0.08926 |
| Triplets with positive loss | 81.25% |
| Nonzero gradient / trainable weights changed | Yes / Yes |
| Frozen weights unchanged / reload check | Yes / Passed |
| Approximate training time for 64 updates | 52.4 s |

The timing estimate excludes download, final save/reload, validation and index
building, and does not establish accuracy improvement. No longer training run was
automatically started. Eleven offline experiment tests (including exact interrupted
versus uninterrupted weights/RNG) and all six existing category tests passed.

The pilot also exported and verified all 8,214 training vectors, their tool order,
and the backend local embedder. A fixed quick check of 16 validation descriptions
and 16 validation homepages completed for all three candidates. Original 128-token
BGE, the trained checkpoint and the deployed baseline each scored 56.25% on those
descriptions and 37.50% on those homepages: the pilot showed no accuracy improvement
on this small development subset. Detailed metrics and the exact subset are in
`evaluation_quick.json`. Full validation and a longer training run had not yet run
when this initial pilot was recorded; the follow-up workflow below retains this artifact.
At the unchanged cutoff, description coverage was 62.50% for original/deployed BGE
and 56.25% for the trained model; homepage coverage was 25% for all three. This
small check provides no basis to promote the trained checkpoint.

## Bounded follow-up comparisons

The completed 2026-11-04 comparisons are in
[the measured report](reports/bge-finetuning-2026-11-04/REPORT.md) and
[its interpretation](reports/bge-finetuning-2026-11-04/ANALYSIS.md).
Full validation, random budgets A/B, matched mixed sampling, and a second seed
were run. The one-homepage gain at 64 updates did not repeat; neither 256-update
configuration improved homepage accuracy. Backend defaults remain selected.

Primary target, chosen before comparisons: **forced category accuracy on validation
homepages**. Description accuracy, macro-F1, per-category recall, neighbor agreement
and coverage are supporting measures. With only 106 homepages, one changed example
moves accuracy by about 0.94 percentage points; small changes are inconclusive.
Keep k=15, margin 0.1, final block only, 128 tokens, microbatch 1, accumulation 4,
two CPU threads, and learning rate 1e-5 throughout the initial comparisons.
Predeclared supporting guards permit at most a 0.01 macro-F1 drop and a five
percentage point coverage drop on each view against matching original BGE. The
comparison report selects a candidate for a second-seed check only if homepage
accuracy improves and these guards pass. This is not a deployment recommendation.

Full validation of the existing pilot runs first, outside the preserved run:

```powershell
.\.venv-training\Scripts\python.exe notebooks/category_classification/evaluate_finetuned.py --run artifacts/category_finetuning/implementation-pilot --output artifacts/category_finetuning/comparisons/pilot-full
.\.venv-training\Scripts\python.exe notebooks/category_classification/finetune_bge.py --max-steps 64 --max-triplets 256 --checkpoint --output artifacts/category_finetuning/budget-a-random
.\.venv-training\Scripts\python.exe notebooks/category_classification/finetune_bge.py --max-steps 256 --max-triplets 1024 --checkpoint --eval-steps 128 256 --output artifacts/category_finetuning/budget-b-random
.\.venv-training\Scripts\python.exe notebooks/category_classification/finetune_bge.py --max-steps 256 --max-triplets 1024 --sampler mixed --checkpoint --eval-steps 128 256 --output artifacts/category_finetuning/budget-b-mixed
```

The sampler deduplicates exact triplets and records unique anchor/positive/negative
examples, tool and category coverage, actual presentations, requested and actual
negative mixtures, and fallback rates. Mixed sampling chooses among up to eight
reasonably similar same-category positives from other groups, excludes normalized
duplicate/near-identical positives, then requests semi-hard negatives 50% of the
time. Semi-hard means positive similarity exceeds negative similarity by less
than the margin. Selection is random among eligible negatives, rather than always
choosing the hardest. No eligible semi-hard candidate means a recorded random
fallback. Original BGE inference embeddings are cached by actual checkpoint tensor
contents, tokenizer, token length, text preparation and exact ordered texts. Mutable
tokenizer padding/truncation state is excluded because the encoder explicitly sets
these per call; cache contents are hash-verified. Candidate searches use bounded
chunks, never an all-tools pairwise similarity matrix.

`--eval-steps 128 256` saves reloadable models, full KNN metrics and example-level
predictions under `validation-checkpoints/step-N/`. All module modes and CPU RNG
are restored afterward, including on failure. Frozen blocks remain in evaluation
mode and the final block remains in training mode. Validation duration is excluded
from `training_seconds` and recorded as `checkpoint_evaluation_seconds`. Choose
checkpoints using KNN results; minimum training loss is not a selection rule.
For resume, repeat every original setting and add `--resume`. Version-2 runs save
the shuffled permutation, position, epoch and shuffle RNG, optimizer and random
states. Legacy completed runs remain evaluation candidates and are not resumed
with the new sampler/shuffle policy.

```powershell
.\.venv-training\Scripts\python.exe notebooks/category_classification/evaluate_finetuned.py --run artifacts/category_finetuning/budget-a-random
.\.venv-training\Scripts\python.exe notebooks/category_classification/evaluate_finetuned.py --run artifacts/category_finetuning/budget-b-random
.\.venv-training\Scripts\python.exe notebooks/category_classification/evaluate_finetuned.py --run artifacts/category_finetuning/budget-b-mixed
.\.venv-training\Scripts\python.exe notebooks/category_classification/compare_finetuning_runs.py --evaluations artifacts/category_finetuning/comparisons/pilot-full/evaluation.json artifacts/category_finetuning/budget-a-random/validation-full/evaluation.json artifacts/category_finetuning/budget-b-random/validation-full/evaluation.json artifacts/category_finetuning/budget-b-mixed/validation-full/evaluation.json --output artifacts/category_finetuning/comparison-report
```

Each full comparison includes original BGE at matching preprocessing and reference
labels, the trained model, and the deployed baseline. Paired wrong-to-correct and
correct-to-wrong changes retain exact example IDs. The test split is used only to
verify frozen hashes and isolation, never for predictions or checkpoint selection.
The report CSV separates training and evaluation time and contains all supporting
metrics. Cached original/deployed baseline evaluations can take less time later.

## Label review and separate homepage-transfer experiments

```powershell
.\.venv-training\Scripts\python.exe notebooks/category_classification/review_training_neighbors.py --output artifacts/category_finetuning/label-review
```

The bounded training-only review queue includes both descriptions, original labels,
similarity, neighboring conflicting categories, repeated-confusion frequency,
near-identical-text indicators and empty human-decision/provenance fields. It
does not replace labels. Apply only approved corrections via `--reviewed-labels`
and retain version/source provenance. The matching original-BGE comparison uses
the same corrected reference labels; validation truth stays unchanged. Without
approved review annotations, label-correction improvement remains unmeasured.
The observed queue is `artifacts/category_finetuning/label-review-v2/`; it also
includes existing frozen near-description flags after filtering both IDs to train.

After description-only comparisons, `--homepage-fraction 0.25` enables a separate
transfer experiment. Every training homepage's referenced tool IDs are checked
against the frozen training split. Ambiguous reviewed categories are excluded.
All anchor identities/groups are excluded from its positive and negative tools.
Homepage anchors use title, meta-description, headings and body in the same order
as validation/runtime preparation. `--measure-truncation` records training input
token lengths and proportions beyond 128 and 256 in `truncation.json`; it does not
assert where the important functional information occurs.

```powershell
# Separate resource pilots before considering a 128-vs-256-token accuracy comparison:
.\.venv-training\Scripts\python.exe notebooks/category_classification/finetune_bge.py --pilot --homepage-fraction 0.25 --measure-truncation --max-length 128 --output artifacts/category_finetuning/homepage-pilot-128
.\.venv-training\Scripts\python.exe notebooks/category_classification/finetune_bge.py --pilot --homepage-fraction 0.25 --measure-truncation --max-length 256 --output artifacts/category_finetuning/homepage-pilot-256
```

Keep sampler, seed, budget and learning rate constant when comparing lengths and
evaluate each against original BGE with its own matching token limit. A promising
description-only configuration should first be repeated with `--seed 20261015`.
Only after choosing sampling should a separate 1e-5-versus-3e-5 comparison be run.
If active loss collapses, inspect triplet difficulty before increasing the margin.
If validation worsens despite falling loss, prefer an earlier candidate or lower
learning rate. Unfreezing more blocks is deferred and requires a new resource
pilot; neither the trainable architecture nor abstention cutoff is changed here.
No run or report automatically promotes a model into the backend.

## Reviewed 30-attempt homepage experiment (2026-11-07)

The immutable `homepage_training_v2/pilot-30` captures were reviewed by Codex
(AI, not a human reviewer). The isolated
`data/category_classification/homepage_training_v2/reviewed-2026-11-07-v1/`
supplement retains all 30 decisions, exact training texts, pinned-tokenizer
128-token evidence checks, capture hashes, and five effective training-label
overrides (the prior two corrections plus three homepage-supported corrections).
Sixteen pages passed review. No further URLs were collected.

`--training-homepages PATH/pages.jsonl` explicitly selects a reviewed supplement
for `--homepage-fraction`. Its adjacent reviews and manifest are required. The
loader verifies capture evidence, approvals, effective categories, group labels,
held-out IDs/groups/hosts/text, and duplicate hosts/groups/URLs/text. Supplement
and review hashes participate in resume validation. Omitting the option retains
the original homepage source; validation continues to use its separate frozen
source. Each homepage anchor's groups remain excluded from reference examples.

The bounded matched comparison is implemented in `run_homepage_comparison.py`:
an eight-update resource pilot, then description-only A and supplement-only B
at 64 updates / 256 unique triplets maximum, with identical reviewed labels and
128-token preprocessing. Full validation includes matching original BGE. Both
conditions repeat with seed 20261015 only if the predeclared accuracy and
supporting guards pass. See the resulting
[experiment report](reports/bge-homepages-2026-11-07/REPORT.md).

```powershell
# New experiment only; existing artifacts are preserved:
.\.venv-training\Scripts\python.exe notebooks/category_classification/run_homepage_comparison.py
# Recover an interrupted execution without rerunning completed conditions:
.\.venv-training\Scripts\python.exe notebooks/category_classification/run_homepage_comparison.py --continue-existing
.\.venv-training\Scripts\python.exe -m pytest notebooks/category_classification/finetuning/test_homepage_supplement.py notebooks/category_classification/finetuning/test_experiment.py -q
```
