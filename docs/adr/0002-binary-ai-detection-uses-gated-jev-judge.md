# Binary AI detection uses a keyword gate plus a Jev judge on website text

Binary AI detection for a Tool without a known-catalog answer runs on its fetched homepage text, not its catalog description. A deterministic gate (the v4 AI keyword regex plus an AI-capability phrase regex) sends pages with no AI signal straight to non-AI, or to unresolved when under 200 characters of text. Every gated page goes to TypeSafe Jev (`jev-1.14.0`) as one typed `choice` question over AI, non-AI and unresolved, using the full page text. The page is AI when `P(ai) ≥ 0.4`; otherwise it is whichever of non-AI or unresolved is more probable. A second Jev request scores each candidate sentence as evidence of the product's own AI performing a task. The top sentences are stored with every decision, and AI calls whose best sentence scores below 0.6 are marked `needs_review`. This implements [ADR 0001](0001-ai-tool-requires-own-ai-functionality.md) and departs from the trained-pipeline team choice for this one task: the versioned artifact is the gate, question set, model ID and cutoffs, not a fitted model.

## Considered Options

- **TF-IDF + logistic regression on catalog descriptions** (the `binary-ai-v4`/`v5` model). Rejected: AIToolBuzz rows were all AI and their text gives away their source (0.994 AUC predicting source among AI rows). On 94 new enterprise test examples, the frozen model scored 0.658 macro-F1, against 0.942 for the keyword rule.
- **Keyword rule alone.** Rejected: on 409 fresh, blindly labeled homepages it made 27 false alarms and 61 unsupported AI calls, and it cannot abstain.
- **Students distilled from judge labels** (MiniLM/BGE embeddings or TF-IDF, each with logistic regression). Rejected: the best scored 0.859. With only 26 non-AI and 32 unresolved teacher examples, they agreed with the judge on only 59–70% of keyword pages.
- **GPT-5.6 Luna judge through `codex exec`.** Matched Jev's accuracy (0.929 against 0.931 macro-F1 on the same 409 pages). Not chosen: batches took 15–40 s, it varied between runs, it depends on a CLI subprocess, and it can only read snippets.
- **An open-ended browsing agent for unresolved pages.** Rejected: at most about 5% of pages abstain while having a clear answer, and an agent adds cost, latency, prompt-injection exposure and inconsistent answers. A bounded, code-driven deeper-page fetch remains a possible later experiment.

## Consequences

- An external API sits on the inference path. Inference needs `TYPESAFE_API_KEY`, network access, and a cache keyed by request hash, so a re-analysis replays stored answers instead of re-asking. A model or question change is a new versioned configuration that must be re-validated with `notebooks/ai_cascade/evaluate_test.py` on freshly labeled pages. Both existing held-out samples have already been used.
- Jev returns probabilities, not explanations. Traceability comes from the stored evidence sentences and their probabilities. They show which text supports a call, not the model's reasoning.
- The gold labels behind these measurements come from two blind passes by the same model family, so agreement is an upper bound. Remaining errors are mostly rubric-boundary cases (vendor support chatbots, short "built-in AI Assistant" claims, parked pages reaching the gate), not missing evidence.
- 14-category classification keeps its own separate artifact and is not covered by this decision.
