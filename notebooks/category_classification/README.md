# AIToolBuzz category classification: first experiment

This experiment uses only the cleaned AIToolBuzz catalog. It is separate from
`binary_ai_dataset` and synthetic enterprise Activity Events. Its input is each
eligible Tool's `Short Description`; its target is the unchanged 14-value
AIToolBuzz `Category`. `Primary Task`, `Keywords`, `technologies`, names, URLs,
and identity group IDs are excluded from model features. The frozen CSV files
contain only the tool ID, group ID, description text, and target so that the
feature boundary is easy to inspect.

## Review and eligibility

The cleaned catalog has 13,701 rows. Its quality report flags 34 rows in 17
identical-description pairs. Five pairs (10 rows) have conflicting categories.
Those 10 rows are held out of all model partitions pending manual label review;
they are retained in `description_review.csv` with both source labels. The
remaining 24 flagged rows share a category within their pairs. They stay in
the dataset but cannot cross partitions. Identical text does not prove that
two listings are the same Tool.

`near_description_review.csv` lists 44 additional highly similar text pairs;
three pairs disagree in Category. They remain labeled as supplied and are
grouped together for the split. They are candidates for later label review.
The cleaner's 500 short-description flags remain in this first dataset; no
length threshold silently removes them. The split manifest records source
hashes, review counts, partition hashes, category support, and the input
feature allowlist.

## Frozen split

Rows are joined into conservative split groups when they share a normalized
description, normalized name, or exact website hostname. Descriptions at least
40 characters long are also grouped if they share a rare four-word phrase and
have normalized sequence similarity at least 0.92. Grouping is a leakage
precaution, not an identity assertion. A seeded five-fold stratified group
split assigns fold 0 to final test, fold 1 to validation, and the remaining
folds to train. Every category is present in every split. The result has
8,214 training rows, 2,739 validation rows, and 2,738 test rows. This is a
catalog Tool holdout; a separate experiment still needs to test transfer to
website-enriched descriptions available at runtime.

## Fixed baseline result

The model fits word unigram/bigram TF-IDF and logistic regression on training
descriptions only, with fixed first-pass settings and no post-validation
tuning. A most-frequent-category dummy is the comparison. The test set has
already been evaluated; changing features, groups, thresholds, or model
settings after seeing these results requires a newly frozen independent test
set for a fresh final-performance claim.

| Split | Model | Accuracy | Macro F1 | Weighted F1 |
| --- | --- | ---: | ---: | ---: |
| Validation | Most frequent | 0.2574 | 0.0292 | 0.1054 |
| Validation | TF-IDF + logistic regression | 0.5152 | 0.3469 | 0.4744 |
| Test | Most frequent | 0.2575 | 0.0293 | 0.1055 |
| Test | TF-IDF + logistic regression | 0.5139 | 0.3321 | 0.4698 |

The exact metrics, per-category precision/recall/F1 and support, and confusion
matrices are in `baseline_evaluation.json`. Test recall is particularly low
for `Personal And Lifestyle` and `Security And Privacy` (about 0.02 and 0.03).
These results do not support promoting the model into the application. The
report also records known limitations: remaining near-duplicate risk,
description-only evaluation, and uncalibrated scores.

## Reproduce

From the repository root, install `notebooks/category_classification/requirements.txt`,
then run:

```powershell
python -B notebooks/category_classification/prepare_dataset.py
python -B -m unittest discover -s notebooks/category_classification -p 'test_*.py'
python -B notebooks/category_classification/train_baseline.py
```

The preparation step deterministically regenerates the CSV partitions, review
files, and manifest. The training step checks partition hashes and group
separation before evaluation. It does not export a model artifact or promote
an inference model.
