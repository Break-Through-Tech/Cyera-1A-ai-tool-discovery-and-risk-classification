# Domain Docs

This repository uses a single-context domain documentation layout.

## Before exploring

Read these when they exist:

- `CONTEXT.md` at the repository root;
- relevant ADRs under `docs/adr/`.

If they do not exist, proceed silently. Create them lazily through the domain-modeling workflow only when genuine terminology or architectural decisions need recording.

## Intended layout

```
/
├── CONTEXT.md
├── docs/
│   └── adr/
├── frontend/
├── backend/
├── notebooks/
├── data/
└── artifacts/
```

## Vocabulary

Use terms defined in `CONTEXT.md` consistently in issue titles, specifications, tests, and code. If a needed concept is absent, determine whether it is unnecessary terminology or a genuine domain-modeling gap.

## ADR conflicts

If proposed work conflicts with an existing ADR, identify the conflict explicitly rather than silently overriding the decision.
