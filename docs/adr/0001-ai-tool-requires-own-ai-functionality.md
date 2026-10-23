# An AI Tool must show its own AI functionality

The governance question is whether a product actually uses AI, so a Tool is AI only when evidence describes AI work performed by its own functionality, as its core offering or as an included feature. An AI Mention is not enough: vague marketing ("AI-powered platform"), AI as the product's subject ("secure your AI agents"), AI as content (blog or course headlines), or a denial. A Tool whose only evidence is a vague product AI claim is unresolved, not AI or non-AI. Catalog membership no longer decides AI status: AIToolBuzz entries are strong candidates and stay Category examples, but each one's AI status comes from its evidence.

## Considered Options

- **Any product AI mention counts** (the earlier enterprise v3 rubric). Rejected: a 2026-10-22 sample of 231 fetched homepages showed the keyword rule already reproduces this definition at 0.88 macro-F1, while 42% of CompanyEnrich SaaS pages make some product AI claim. That flags most modern software without saying anything actionable about governance.
- **Every AIToolBuzz entry is AI** (the earlier PROJECT_PLAN definition). Rejected: 9 of 99 sufficient AIToolBuzz homepages in the same sample showed no AI, and most catalog taglines cannot show a capability either way.
- **Vague claims count as non-AI.** Rejected: a missing capability description is not evidence of absence, and the plan already treats insufficient evidence as an Abstention.

## Consequences

- Existing enterprise v3 `non_ai` labels remain valid. The 78 enterprise `ai` labels need review against this definition before they are used as positives. Website labels from `notebooks/website_feasibility/labeling/` map directly: `ai_core` and `ai_feature` are AI, `ai_mention_only` and `insufficient` are unresolved, and `no_ai` is non-AI.
- `binary-ai-v5` and earlier datasets keep their original operational definition and stay frozen; they are not relabeled.
