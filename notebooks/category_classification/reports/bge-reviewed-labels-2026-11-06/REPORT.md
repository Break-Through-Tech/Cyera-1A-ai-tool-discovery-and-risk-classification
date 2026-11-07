# BGE and KNN with reviewed training labels

The two label corrections fixed two catalog description predictions and changed
no homepage predictions. Fine-tuning on the corrected training dataset added
three net correct descriptions and lost one correct homepage prediction relative
to the label-only run. Keep the deployed configuration for homepage
classification.

| Candidate | Homepage accuracy | Homepage macro-F1 | Homepage coverage / answered accuracy | Description accuracy | Description macro-F1 | Description coverage / answered accuracy |
|---|---:|---:|---:|---:|---:|---:|
| A. Original BGE, original labels | 55/106 (51.89%) | 0.3792 | 53.77% / 68.42% | 1,540/2,739 (56.22%) | 0.4559 | 60.75% / 69.17% |
| B. Original BGE, corrected labels | 55/106 (51.89%) | 0.3792 | 53.77% / 68.42% | 1,542/2,739 (56.30%) | 0.4565 | 60.83% / 69.21% |
| C. Fine-tuned BGE, corrected labels | 54/106 (50.94%) | 0.3625 | 51.89% / 69.09% | 1,545/2,739 (56.41%) | 0.4539 | 60.57% / 69.44% |
| Deployed BGE, original preprocessing | 57/106 (53.77%) | 0.4574 | 50.94% / 70.37% | 1,540/2,739 (56.22%) | 0.4559 | 60.75% / 69.17% |

Accuracy scores assign a category to every validation tool. The two answered-case
metrics apply the existing cutoff of 0.468914118995349. All four candidates use
15 neighbors and the same validation rows. A, B, and C use 128-token inputs.
B and C use the same two [training overrides](approved-training-labels.json)
with 8,214 reference tools. The recomputed A matched the previous experiment's
aggregate baseline.

## What changed the predictions

- **A to B, labels alone.** The comparison verified identical neighbor IDs,
  order, and similarities and exactly the expected category changes. At least
  one corrected tool appeared among the 15 neighbors for 26 descriptions and
  zero homepages. The general-purpose image generator's updated vote moved two
  descriptions from Creative And Entertainment to the expected Media And
  Content Creation. Its similarities in those two votes were 0.921 and 0.766.
  Prospectli's updated vote did not flip a category. Description accuracy rose
  by 0.073 percentage points, with two fixes and zero regressions.
- **B to C, encoder training.** Twelve descriptions improved and nine regressed
  (+0.110 percentage points). The homepage model fixed zero cases and regressed
  one (−0.943 points). Tallyrus moved from the expected Ai And Machine Learning
  to Operations And Management. Another homepage, aivoicegen.net, changed from
  one wrong category to another. Neither changed homepage had a corrected
  neighbor before or after training. Neither relabeled tool appeared in the
  256 sampled triplets. The measured C gain on descriptions therefore reflects
  this encoder run with corrected reference labels, without direct training on
  either corrected example.

The 64-update description-only run took 81.2 seconds and peaked at approximately
615 MiB sampled training memory. Frozen-weight and checkpoint-reload checks
passed. Full evaluation, including rebuilt reference vectors and the deployed
comparison, took 643.4 seconds. The exported experimental index was verified
against the saved model through the backend's local inference adapter.

## Decision and next review

Homepage accuracy was the selection metric. B tied A, and C lost one correct
homepage and dropped homepage macro-F1 by 0.0167 versus B, beyond the 0.01
guardrail. The experiment ended at the first seed and retained C as a local
artifact. Independent homepage testing is reserved for a candidate that improves
validation. The frozen test rows were used for split integrity checks only.

Prioritize training labels that recur in incorrect homepage votes. In Tallyrus's
paired result, original BGE retrieved Documente by Envistudios, labeled Ai And
Machine Learning, while fine-tuned BGE's winning neighbors included FilePower
AI, labeled Operations And Management. Both training descriptions describe
document extraction and processing. Review that category boundary against the
primary function rule before deciding whether either label needs correction.
Also review notesGPT, a voice-note transcription and organization tool labeled
Communication And Support, which contributed to three persistent wrong homepage
votes. These are review candidates.

## Reproduce

The previous homepage training artifacts, local review queue, and original
per-example baseline were absent. The experiment used the frozen training CSV
to recover the reviewed rows and the pinned original BGE to regenerate the
baseline. The restored CPU environment is under `.cache-training/reviewed-venv`.

```powershell
$python = ".\.cache-training\reviewed-venv\Scripts\python.exe"
$env:HF_HOME = "$PWD\.cache-training\huggingface"
$env:SENTENCE_TRANSFORMERS_HOME = "$env:HF_HOME\hub"
$env:HF_HUB_OFFLINE = "1"
$labels = "notebooks/category_classification/reports/bge-reviewed-labels-2026-11-06/approved-training-labels.json"
$run = "artifacts/category_finetuning/reviewed-labels-seed1-cpu"
& $python notebooks/category_classification/finetune_bge.py --reviewed-labels $labels --max-steps 64 --max-triplets 256 --sampler random --homepage-fraction 0 --max-length 128 --seed 20261014 --checkpoint --output $run
& $python notebooks/category_classification/evaluate_finetuned.py --run $run
& $python notebooks/category_classification/compare_reviewed_labels.py --evaluation "$run/validation-full/evaluation.json" --output "$run/label-comparison"
& $python notebooks/category_classification/export_finetuned_index.py --run $run
```

Use a new run directory for a rerun. See `label-comparison/comparison.json`
in the run directory for full paired changes, `validation-full` for per-example
votes, and `index` for the verified experimental reference index.
