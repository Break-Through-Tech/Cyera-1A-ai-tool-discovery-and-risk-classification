> All roles are provisional hypotheses until leakage-resistant evaluation promotes an approach.

| Approach | How it works | Strengths | Weaknesses | Candidate role |
|---|---|---|---|---|
| Cosine similarity to category descriptions | Embeds each tool and category definition, then selects the closest category | No labeled training data required; handles unseen tools | Sensitive to category wording; similarity is not a calibrated probability | Zero-shot baseline |
| K-nearest neighbors | Retrieves labeled tools with similar embeddings and uses their labels to classify the new tool | Easy to explain; provides similar-tool evidence | Noisy neighbors can mislead predictions; performance depends on `k` | Retrieval and explainability |
| TF-IDF + logistic regression | Learns categories from important words and phrases in labeled descriptions | Fast, inexpensive, interpretable, and a strong baseline | Weaker at recognizing synonyms and semantic similarity | Initial supervised baseline |
| Embeddings + logistic regression | Converts descriptions into embeddings and trains a linear classifier on them | Captures semantic meaning; efficient; produces class probabilities | Requires clean labels; may miss exact keyword patterns | Candidate supervised model |
| Embeddings + XGBoost | Trains decision trees using embeddings and optional structured metadata | Combines text, pricing, tags, department, and usage features | More complex; may not outperform linear models on dense embeddings | Structured-feature fusion experiment |
| Fine-tuned transformer | Fine-tunes a pretrained language model directly on tool descriptions and labels | Can learn subtle category distinctions and achieve strong performance | Requires substantial clean labeled data, compute, and tuning | Advanced experiment |
| Zero-shot or few-shot LLM | Prompts an LLM with the tool description, taxonomy, and optional examples | Flexible; handles ambiguity; produces explanations | Expensive, slower, less consistent, and difficult to calibrate | Low-confidence fallback or label generation |
| Hybrid classification cascade | Combines exact matching, supervised classification, vector retrieval, confidence thresholds, and review | Balances accuracy, explainability, cost, and unseen-tool handling | More components to integrate, evaluate, and maintain | Candidate integration architecture |

## Binary AI detection — first validation experiment

**Status: frozen held-out test evaluated; awaiting results review; not promoted.** Reproduce in
[the baseline notebook](notebooks/binary_dataset/first_binary_baseline.ipynb).
Dataset: frozen `binary-ai-v4`; description text only. Fit preprocessing and models
on train only; select settings on validation. The approved test experiment keeps
C=10, balanced weights, and the default 0.5 AI cutoff unchanged.

TF-IDF word unigrams/bigrams, `min_df=2`, standard remaining vectorizer defaults;
L2 logistic regression (`liblinear`, `max_iter=1000`, seed `20261014`).
Compare `C={0.1,1,10}` with ordinary/balanced weights; select highest pooled
validation macro-F1 at the default 0.5 AI score cutoff. Exact ties retain lower C,
then ordinary weights. Selected: **C=10, balanced**. No calibration or threshold tuning.

| Validation model | Accuracy | Macro-F1 | False positives | Missed AI |
|---|---:|---:|---:|---:|
| Always-AI dummy | 0.9748 | 0.4936 | 63 | 0 |
| Fixed keyword rule | 0.5090 | 0.3782 | 0 | 1,228 |
| Selected TF-IDF + logistic regression | 0.9916 | 0.9152 | 10 | 11 |

Enterprise validation: selected model detects **4/6 AI** and rejects **53/63 non-AI**;
macro-F1 **0.6492**, versus keyword **1.0000**. Catalog-member AI recall: **2,423/2,432
(99.63%)**. Source-record supports are not model-example counts; the notebook reports
cohorts explicitly. Scores are uncalibrated, and source/style confounding remains.
The selected model wins pooled macro-F1 but does not beat the keyword rule on the
small enterprise slice; no enterprise-generalization or promotion claim follows.

## Binary AI detection — frozen held-out test

The user approved the settled **C=10 / balanced / 0.5** experiment. Reuse its train-only
fitted pipeline, unchanged keyword rule and dummy; no refit on train+validation,
alternative learned-model testing, threshold tuning, or post-test configuration change.

| Test model | Accuracy | Macro-F1 | False positives | Missed AI |
|---|---:|---:|---:|---:|
| Always-AI dummy | 0.9748 | 0.4936 | 63 | 0 |
| Fixed keyword rule | 0.5154 | 0.3817 | 0 | 1,212 |
| Frozen TF-IDF + logistic regression | 0.9960 | 0.9593 | 5 | 5 |

Selected model: non-AI precision/recall/F1 **0.9206**; AI precision/recall/F1 **0.9979**.
Non-AI PR-AUC (trapezoidal) **0.8858**, AP **0.8876**; AI PR-AUC/AP **0.9999**.

Enterprise test: **3/6 AI detected**, **58/63 non-AI rejected**, macro-F1 **0.6820**.
The keyword rule gets all 69 enterprise examples right. Learned misses: Playbooks,
Micro Focus Operations Management, and Intelligent Customer Engagement Platform,
despite explicit AI/ML signals. Catalog-member AI recall: **2,430/2,432 (99.92%)**.

Strong pooled benchmark performance does not establish enterprise-AI transfer.
Six enterprise AI examples make recall noisy; concrete explicit-signal misses and
source/style confounding remain material limitations. Scores are uncalibrated.
No model bundle is exported and no model is promoted. The test split has now been
evaluated; its outcomes must not select future settings/rules/thresholds while
claiming independent final performance. Exact replay reproduces this settled result,
not new independent evidence.

## 14-category classification — description-only baseline

**Status: frozen held-out test evaluated; not promoted.** The separate
`aitoolbuzz-category-v1` dataset uses the cleaned AIToolBuzz catalog only.
The input is `Short Description`; the target is the original 14-value
`Category`. The preparation script keeps normalized-name, website-host, exact
description, and strongly similar-description groups within one partition.
It excludes the 10 rows in five identical-description pairs with conflicting
Category labels pending review, while retaining 24 same-label duplicate-text
rows in shared split groups. The dataset has 8,214 train, 2,739 validation,
and 2,738 test examples. See
[method and review files](notebooks/category_classification/README.md).

Fixed first-pass model: train-only fitted word unigram/bigram TF-IDF
(`min_df=2`) plus logistic regression (`max_iter=1000`, seed `20261014`).
No feature selection, hyperparameter search, threshold tuning, or refit took
place after validation. The most-frequent-category dummy is the comparison.

| Split | Model | Accuracy | Macro F1 | Weighted F1 |
| --- | --- | ---: | ---: | ---: |
| Validation | Most frequent | 0.2574 | 0.0292 | 0.1054 |
| Validation | TF-IDF + logistic regression | 0.5152 | 0.3469 | 0.4744 |
| Test | Most frequent | 0.2575 | 0.0293 | 0.1055 |
| Test | TF-IDF + logistic regression | 0.5139 | 0.3321 | 0.4698 |

The model beats the trivial baseline, but test recall is only 0.022 for
`Personal And Lifestyle` and 0.030 for `Security And Privacy`.
[The full report](data/category_classification/v1/baseline_evaluation.json)
has per-class metrics and confusion matrices. Catalog description results do
not establish performance on runtime website-enriched text or unseen
out-of-catalog Tools; no model bundle is exported. The test set has been
evaluated and cannot guide settings while retaining an independent final-test
claim.
