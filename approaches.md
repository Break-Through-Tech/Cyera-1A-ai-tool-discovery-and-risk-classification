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
