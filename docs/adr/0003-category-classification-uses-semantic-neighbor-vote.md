---
status: proposed
---

# Category Classification of unseen AI Tools uses a Semantic Neighbor vote

An AI Tool without a known-catalog Category gets the Category chosen by a vote of its 15 most similar catalog Tools. Its homepage text, or its supplied description when no homepage was extracted, is embedded with `BAAI/bge-small-en-v1.5` (revision `5c38ec7`) and compared by cosine similarity with the 8,214 train-split descriptions of `aitoolbuzz-category-v1`. Each neighbor votes for its catalog Category with its similarity as the weight. The winning share of the vote is the score, and a score below 0.469 makes the Category unresolved. The neighbors and their similarities are stored with every decision as its explanation. This narrows the earlier rule that Semantic Neighbors are supporting evidence only: they become the authority for Category, and only for Category. They remain evidence, not authority, for identity and AI status. The versioned artifact is the embedding model and revision, the neighbor index, `k` and the cutoff.

## Considered Options

Every option was tuned on validation descriptions and the 106 validation-split homepages, then frozen and scored once on test (`notebooks/category_classification/FREEZE.json`, `test_results.json`). The table shows accuracy when every Tool gets a Category.

| Method | Test descriptions (2,738) | Test homepages (89) |
|---|---:|---:|
| **Semantic Neighbor vote (chosen)** | **0.566** | **0.528** |
| TF-IDF + logistic regression | 0.526 | 0.472 |
| Embeddings + logistic regression | 0.543 | 0.427 |
| Jev 14-way `choice` question | 0.485 | 0.494 |

- **TF-IDF + logistic regression** (the planned trained artifact). Rejected: it was 4 points behind on test descriptions and 5–6 points behind on homepages, and it gives no similar-Tool explanation.
- **Embeddings + logistic regression.** Rejected: it lost more accuracy on homepages than the vote did. To reach 70% accuracy on validation homepages it had to answer only 24% of Tools.
- **Jev 14-way `choice` question.** Rejected: it trailed by 8 points on descriptions. Its confidence separated right from wrong answers poorly, so no cutoff reached 70% accuracy on validation homepages. Unlike in ADR 0002, an external judge brings no gain here: AIToolBuzz Categories follow catalog labeling habits that only methods learning from catalog labels pick up.
- **Zero-shot similarity to written category descriptions.** Rejected: 0.10–0.27 accuracy, no better than always choosing the most common Category.

## Consequences

- Expect about 63–71% accuracy on the 55–61% of unseen AI Tools that receive a Category; the rest are unresolved. The cutoff was chosen on only 106 homepages and fell short of its 70% target on the test homepages (0.633 on 49 answers).
- The catalog labels are noisy, so a vote of the closest labeled Tools also inherits their mislabels. Showing the neighbors makes those mistakes visible.
- The neighbor index is the train split only. The two catalog-held-out Tools in `backend/config/known_tool_registry_exclusions.json` sit in test and must never enter the index. Growing the index with validation or test Tools is a new configuration that needs new held-out pages to measure.
- Inference needs the embedding model on the backend. It runs locally on CPU with no external call, unlike AI Determination.
- This is the second use of the v1 test split; the first scored the fixed TF-IDF baseline. A future change to `k`, the cutoff or the embedding model needs freshly labeled pages for an independent claim.
