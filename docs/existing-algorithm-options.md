# Existing algorithm and rubric options

This document summarizes the algorithmic options already explored in this repo, the project’s current direction, and the recommended next step for the risk-assessment rubric.

## 1) Current project direction

The repo already states the governing frame for risk work:

- NIST AI RMF as the primary governance structure
- NIST Generative AI Profile to inform risk dimensions
- OWASP LLM Top 10 for security-focused checks
- No claim of formal compliance or certification

This is the strongest fit for the challenge because it gives a defensible governance lens without pretending to be a formal enterprise control framework.

## 2) Existing algorithm options already explored

### A. Binary AI detection

These are the main options already documented in the repo and the project plan.

| Option | How it works | Strengths | Weaknesses | Current status |
|---|---|---|---|---|
| Keyword rule / regex gate | Detect AI-related language in product text, homepage, or description | Fast, transparent, inexpensive, strong on obvious AI signals | Misses less explicit tools; can be brittle | Used as a deterministic gate in the selected approach |
| TF-IDF + logistic regression | Classifies on word frequency patterns from labeled AI/non-AI examples | Strong baseline, simple and explainable | Can be confounded by source/style differences | Documented as a prior benchmark, not selected for runtime deployment |
| Embeddings + classifier | Uses semantic embeddings and a downstream classifier | Better at semantic understanding than bag-of-words | More complexity; still not a true enterprise guarantee | Experimental, not selected |
| Jev judge cascade | Uses a typed judge on website text with evidence extraction and review flags | Good runtime performance, supports evidence and abstentions | External judge dependency, ambiguous cases need review | Selected for binary AI detection in the repo’s ADRs |
| Hybrid rule + model + review gate | Deterministic gate + judge decision + evidence review | Good balance of explainability and accuracy | More moving pieces to maintain | Selected architecture |

The repo’s own design summary says the final working solution for AI determination is a deterministic gate plus a TypeSafe Jev judge over homepage text, not a trained classifier alone.

### B. 14-category classification

The repo compared several approaches for assigning an AI tool to one of the catalog categories.

| Option | How it works | Strengths | Weaknesses | Current status |
|---|---|---|---|---|
| Most-frequent-category dummy | Always predicts the most common category | Baseline sanity check | Very weak | Baseline only |
| TF-IDF + logistic regression | Classifies based on text features | Fast, interpretable, strong baseline | Limited semantic depth | Documented and benchmarked |
| Zero-shot similarity | Compares against written category descriptions | No training labels required | Weak on taxonomy-specific nuance | Not selected |
| Semantic neighbor vote | Uses nearest-neighbor tool descriptions with weighted votes | Good explainability, strong on unseen tools, uses evidence from similar tools | Depends on catalog quality and similarity quality | Selected in ADR 0003 |
| Embeddings + logistic regression | Uses dense semantic embeddings with a linear classifier | Captures semantic similarity better than TF-IDF | Less interpretable; needs validation tuning | Tested, not chosen over neighbor vote |
| Jev 14-way choice judgment | Uses an LLM judge to choose a category | Flexible, easy to prompt | Usually weaker and less reliable for this specific taxonomy; confidence is poor | Rejected for final category assignment |
| Hybrid classification cascade | Combine deterministic and retrieval-based methods with abstention | Best operational balance | More engineering work | Strong candidate for future refinement |

The selected category method is the semantic neighbor vote using BGE-small embeddings and a weighted vote of the most similar catalog tools, with abstention thresholds when confidence is too low.

### C. Risk assessment

This is the phase that is not yet implemented in a full framework-backed form.

| Option | How it works | Strengths | Weaknesses | Recommendation |
|---|---|---|---|---|
| Deterministic rubric from framework factors | Map synthetic evidence to rule-based risk tiers and reasons | Explainable, auditable, deterministic, fits the repo’s architecture | Harder to generalize beyond the synthetic demo | Best next step |
| Weighted numeric scorecard | Summarize factors into a numeric score and then map to tiers | Easy to operationalize | Can feel opaque and less explainable | Useful only if the team wants a scoring layer on top of a rubric |
| LLM-assisted evidence extraction | Use an LLM to read vendor metadata and classify claims | Flexible for messy text | Not authoritative without deterministic rules; risk of overreach | Allowed only as a support layer, not final decision-maker |
| Jev-assisted evidence labeling | Use Jev to judge ambiguous vendor text, e.g. training claim = yes/no/conditional/unknown | Good for ambiguous textual evidence | Still requires deterministic risk rules; not a ground truth source | Acceptable as an experimental supporting evidence step |
| Learned risk classifier | Train a model on labeled risk examples | Can scale if quality labels exist | Requires real labels, which the repo explicitly says are not yet available | Deferred |

The repo’s own plan explicitly says the risk engine should be deterministic and framework-informed, not a learned classifier.

## 3) Recommended framework choice for the next phase

The project should move ahead with a framework-backed rubric using:

1. NIST AI RMF
2. NIST Generative AI Profile
3. OWASP LLM Top 10 as the security-risk lens

Why this choice fits:

- It already matches the repo’s confirmed direction.
- It gives governance categories that map naturally to AI tools in synthetic enterprise contexts.
- It keeps the risk assessment explainable and auditable.
- It avoids formal compliance claims while still being grounded in recognized frameworks.

Optional extension:

- Add ISO/IEC 42001 mapping as a management-level crosswalk, but keep it secondary.
- Do not lead with ISO as the primary rubric unless the team wants a more governance-suite framing.

## 4) Proposed next deliverable: framework-driven risk rubric

The next step should be a rubric that ingests synthetic-context evidence and classifies each usage context as:

- High
- Medium
- Lower
- Unresolved

The inputs should come from the synthetic data already defined in the repo:

- Tool approval status
- Training-on-customer-data posture
- Admin control availability
- Department, usage purpose, and data sensitivity
- Volume and event history
- Vendor evidence and source limitations
- Material unknowns rather than silent defaults

The rubric should not produce a numeric score as the primary output. It should produce:

- a tier
- a reason list
- factor codes
- references to evidence
- explicit unknowns

That matches the repo’s requirement for explainability and deterministic governance assessment.

## 5) Suggested implementation boundary

Recommended rule:

- Deterministic framework-based rubric decides the risk tier.
- LLM or Jev may assist with evidence extraction or ambiguous text interpretation.
- The final assessment must still be rule-based and explainable.

This preserves the repo’s stated contract:

- AI determination and category classification can use learned or judge-based methods.
- Risk assessment should remain deterministic and grounded in framework-informed project policy.

## 6) Decision for the team

This should be discussed with the team and with Shubham, but the recommended framework posture is:

- Primary: NIST AI RMF + NIST Generative AI Profile
- Security lens: OWASP LLM Top 10
- Secondary crosswalk: ISO 42001 if needed for management reporting

The final output should be a rubric and evidence-mapping document, not an opaque risk model.

## 7) Suggested next action

Pause after this document and let the team review it before starting the rubric implementation. The next work package should be a framework-driven rubric specification and synthetic-data ingestion design, not a learned risk classifier.
