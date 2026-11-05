# Project Statement: AI Tool Discovery & Risk Classification

## Summary

This project builds a lightweight **AI usage discovery and governance console**: a prototype that turns raw enterprise application activity into explainable AI-governance intelligence. Given synthetic activity data, it discovers which applications are AI tools (including ones on no known list), classifies what they do, assesses governance risk with reasons, and surfaces the results for a security or governance analyst to investigate.

The pipeline: **enterprise activity data → tool discovery → AI identification → classification → risk assessment → governance insights.**

## Background

- **Why it matters.** Employee AI adoption has outpaced enterprise governance. Most employees now use AI tools their employer never approved ("shadow AI"), most of that data flows to tools IT cannot see, and breaches tied to shadow AI are both more common and more costly — IBM's 2025 report linked it to ~1 in 5 breaches and ~$670K in added cost.
- **The gap this fills.** There is no turnkey product that reliably finds and governs all shadow AI, so organizations are left with partial visibility and no explainable way to triage. This project prototypes that missing discovery-and-triage layer.

## Key concepts

- **What is shadow AI?** AI tools used by employees without IT, security, or governance approval — standalone chatbots, AI features inside already-approved apps, and AI agents/integrations.
- **Why is visibility hard?** AI use often leaves no installed software and rides in ordinary encrypted traffic; it hides inside approved SaaS, runs through personal accounts, and uses new domains faster than any block-list can track.
- **What risks arise from unmanaged AI use?** Data leakage and loss of control over confidential data, compliance/legal exposure, data used for model training, a larger attack surface, and (increasingly) agents that can take actions.
- **What do security/governance teams need to decide?** For each tool: is it AI; what does it do; who and which departments use it, and how much; is it approved; what controls it offers (SSO, retention, training opt-out, admin controls); the data likely submitted; and a clear reason for its risk rating.
- **How does enterprise activity contribute to governance?** Activity data reveals real usage — which tools, by whom, how often, growing or newly appeared — turning governance from a static policy exercise into evidence-based, continuously updated triage.

## Problem

Enterprises cannot see or reason about the AI tools employees use. Known-tool lists go stale immediately and miss new applications; usage data sits disconnected from any judgment about risk; and when a tool is flagged, analysts get a verdict with no reasons they can act on. The result is either blanket bans that push usage further into the shadows, or no control at all.

## Solution

A prototype system with five components that run as one pipeline:

1. **Activity ingestion** — synthetic enterprise usage data (who used what app/domain, when, from which department).
2. **AI tool discovery** — decide whether each observed application is AI, reasoning about previously unseen tools from name, domain, and description rather than a fixed lookup.
3. **Categorization** — classify each AI tool's business purpose (coding, content, meetings, analytics, etc.).
4. **Governance risk assessment** — combine tool metadata (approval, SSO, retention, training-on-data, admin controls) with usage context (departments, number of users, growth, newly discovered) into an **explainable** risk rating with reasons.
5. **Investigation experience** — a lightweight dashboard (and optional natural-language querying) to explore tools, departments, and the highest-risk and newest applications.

## Benefits

The system gives analysts a platform to:

- **Discover** all AI tools in use, including unapproved and never-before-seen ones.
- **Understand** what each tool does and who is using it.
- **Triage** risk with transparent, reason-backed assessments instead of opaque scores.
- **Act** on priorities — newly discovered, fast-growing, or high-risk tools used by sensitive departments.

It converts scattered activity logs into a single, explainable view of enterprise AI adoption — the first step toward governing it.

## Future growth

- Connect to real activity sources (CASB, proxy/DNS, SSO, SaaS-management logs) instead of synthetic data.
- Enrich tool metadata automatically (live vendor data; embeddings/semantic search for unseen tools).
- Add continuous monitoring, trend detection, and alerting on new or spiking usage.
- Mature the risk model and map it to frameworks (e.g., NIST AI RMF, ISO 42001).
- Expand the conversational analyst interface (RAG / tool-calling) for ad-hoc governance questions.
