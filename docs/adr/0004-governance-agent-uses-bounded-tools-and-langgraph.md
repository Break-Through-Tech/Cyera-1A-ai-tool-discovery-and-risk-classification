---
status: accepted
date: 2026-10-29
updated: 2026-11-06
---

# Governance agent uses bounded tools, controlled Python, and LangGraph

## Context

The Governance Analyst needs to understand which AI-tool usage deserves attention, why it matters, and what evidence to investigate next. The first deliverable is a briefing for a completed Batch analysis. Analyst-directed conversations can later reuse the same tools to investigate dates, departments, Categories, and particular findings.

Semantic retrieval alone cannot answer questions about counts, organizational spread, or changes over time. Those questions require deterministic queries over Activity Events and stored Analysis Run results. An LLM adds value by selecting investigations, connecting supported facts, explaining uncertainty, and suggesting next steps.

The [project plan](../../PROJECT_PLAN.md#rag-governance-assistant-contract--confirmed-implementation-details-deferred) already requires deterministic queries, grounded explanations, and read-only assessments. This ADR specifies agent orchestration, controlled custom Python analysis, and initial delivery scope; narrow project-plan extensions are explicit below. It does not change AI Determination, Category Classification, or contextual-risk rules.

## Decision

Use one tool-calling LLM inside a small LangGraph workflow in the existing FastAPI backend, combining predefined query tools with controlled custom Python analysis. Backend code owns authorized data selection, joins, counts, filters, standard summaries, permissions, and citation resolution. When those tools cannot directly answer an analytical question, the agent may generate Python over an immutable, scoped dataset in an isolated worker separate from FastAPI. This avoids a separate predefined tool for every analytical question while accepting additional isolation, provenance, and method-evaluation responsibilities.

The agent produces interpretations and advisory investigation priorities. It cannot create or override stored identities, classifications, Policy Status, or risk tiers. An advisory priority is distinct from a contextual-risk tier and must be labeled accordingly.

LangGraph coordinates deterministic briefing steps and a flexible investigation loop. Use explicit state and conditional transitions rather than separate planner, researcher, and reviewer agents.

## Initial workflow

The briefing starts on request for a selected Batch with a successful Analysis Run. Automatic invocation after analysis can be added later without changing the investigation tools.

1. Resolve and pin the Batch and successful Analysis Run. Establish the available event-time range and disclose the selected scope.
2. Run standard summaries covering usage, departmental distribution, flagged Usage Contexts, and missing assessment facts.
3. Give the agent compact results and evidence references. Let it request targeted follow-up operations when they can clarify a finding.
4. Stop when the evidence is sufficient or the configured execution budget is reached.
5. Validate the response structure and citation references, then return the briefing with its scope and limitations.

An execution-budget stop must disclose any material unfinished investigation. Database, retrieval, model-service, and worker/service failures produce a failed turn with retry. Recoverable generated-code errors may instead return structured diagnostics to the agent for correction within explicit attempt and resource budgets. An unrecovered error or exhausted repair budget produces an explicit failed turn with retry, preserving earlier messages and citations. Do not present incomplete calculations as completed findings or fall back to model memory or partial execution results. Valid no-match results and successful analyses with evidence limitations remain distinct from failures.

The investigation loop is:

1. Resolve the question and pin its data scope.
2. Use existing query tools when they answer the question directly.
3. Prepare an immutable dataset when custom analysis is needed.
4. Specify the analytical question, method, assumptions, and required inputs before execution.
5. Generate and execute Python within the execution contract below.
6. Inspect results and artifacts; optionally revise the analysis within explicit tool-call, repair-attempt, and resource budgets.
7. Return findings with evidence references, qualifications, and advisory next steps after response validation.

LangGraph coordinates the same agent and execution steps; this extension requires no extra agents.

Analyst conversations later enter the same loop after resolving the question's scope. They can skip the standard briefing summaries when a narrower query answers the request.

## Tool contracts

All tool names below are proposed interfaces, not existing backend functions; final signatures remain deferred. Keep their implementations independent of LangGraph so they can be tested and called directly.

| Tool | Responsibility |
|---|---|
| `describe_dataset` | Return available dates, departments, Categories, analysis coverage, and material missing fields. |
| `summarize_usage` | Filter Activity Events and stored results, then return counts or grouped summaries. |
| `compare_usage` | Compare explicitly scoped periods using the same filters and count definitions. |
| `get_risk_assessments` | Return stored contextual-risk tiers, reason codes, investigation flags, and unknown facts. |
| `get_evidence` | Return bounded supporting records and the lineage behind a particular result. |
| `retrieve_context` | Retrieve relevant retained project-policy, governance, or Tool evidence once the controlled corpus is available. |
| `prepare_analysis_dataset` | Accept validated filters and a supported dataset shape. Backend code performs authorized queries and joins, pins contributing Batches and Runs, and creates an immutable dataset. Return its ID, schema, row count, coverage, qualifications, and bounded preview. |
| `run_python_analysis` | Accept approved dataset references and agent-generated Python. Execute in the isolated worker; return bounded results, artifact references, warnings, or structured errors. Cannot modify application records or stored assessments. |
| `inspect_analysis_artifact` | Return bounded previews or details of result tables, charts, and execution artifacts under the same request scope and access restrictions. |

FastAPI validates typed tool arguments before SQLAlchemy constructs queries. Arbitrary SQL and unrestricted host execution remain excluded; generated Python is available only through the controlled execution contract below. Tools support compatible filters for event time, department, Category, AI status, and stored assessment fields. Unsupported combinations produce an explicit limitation or clarification.

Tool contracts must preserve these properties:

- Time intervals use an inclusive start and exclusive end, with an explicit timezone. Resolve calendar dates to the stored UTC event timestamps.
- Return applied scope, metric definitions, contributing Run references, and stable evidence references alongside results.
- Distinguish event counts, distinct employees, Tools, and Usage Contexts. Keep unresolved AI status, Category, and risk outcomes visible where relevant.
- Bound record and group counts. Disclose truncation and provide pagination or drill-down rather than treating a limited response as the full population.
- Distinguish no matching records, unavailable data, unsupported requests, and execution failures.
- Return summaries first. Fetch detailed evidence only when needed, without dropping material unknowns or conflicts.

The backend enforces the allowed data scope. Model-generated arguments cannot expand access or change the selected historical result.

## Dataset lifecycle and execution boundary

- Preparation resolves the authorized request scope into a complete, immutable input snapshot with an immutable identity and manifest. Record supported shape, schema, row grain, join/count definitions, contributing Batches and Runs, filters, event-time range/timezone, coverage, missing fields, and overlap/conflict qualifications. Existing Run-selection and cross-Batch identity/counting rules apply before export and throughout analysis.
- Keep the complete dataset outside the model's conversation context; pass references, metadata, and bounded previews. A preview is not the population. Never silently substitute a truncated sample for the requested population. If preparation exceeds supported limits, return an explicit limitation and require an explicit scope change before preparing a smaller population.
- Approve dataset references against request scope before every execution and artifact inspection. A filter or Run change creates a new dataset identity; neither follow-ups nor newer Runs mutate existing inputs. Dataset or artifact IDs do not grant broader access.
- Run generated code with read-only mounted inputs and a temporary output directory. The worker has no database credentials, network access, application-state mounts, or unrestricted host access. Enforce CPU, memory, runtime, and output limits outside generated code. Import filtering or Python-level restrictions alone are not a security boundary.
- Use a fixed, versioned set of analytical libraries. Capture the execution environment and enforce result/artifact size limits, disclosing bounded previews and omitted output. Artifact inspection cannot execute output content or expand worker permissions.
- On completion, failure, or termination, clean up the worker and temporary files after retaining permitted outputs and diagnostics with their provenance. Retained datasets, manifests, executions, and artifacts must remain resolvable for cited findings independently of chat lifetime; retention duration and storage mechanics remain deferred. An unavailable artifact returns an explicit status, never a reconstructed result under its old identity.

## Analysis provenance and correctness

Retain the exact generated code for every attempt, dataset manifest and immutable input identity, contributing Batches and Runs, filters and event-time scope, analytical question/method/assumptions, execution and environment/library versions, outputs, warnings, and execution status. Preserve repair-attempt lineage. Link each reported result and artifact to its producing execution and inputs; artifact previews retain those references and qualifications.

Evaluate four separate properties: successful execution, correct computation, appropriate analytical method, and supported interpretation. Successful Python execution does not establish the other three; schema and reference checks do not automatically verify code-generated results. Preserve unknowns, source conflicts, identity boundaries, and overlap warnings through transformations and reporting. Missing denominators, sparse baselines, or missing data must qualify or prevent affected conclusions.

Generated output is derived evidence, not a new authoritative source for AI status, Category, Policy Status, or contextual-risk tiers. Numerically correct results cannot justify an unsupported interpretation, such as inferring sensitive-data submission from department membership or application usage.

## State and conversation behavior

Keep explicit state for the request, selected Batches and Runs, active filters, compact tool results, evidence references, candidate findings, dataset/execution/artifact references, repair attempts, and remaining execution budget. Record tool calls and outcomes for debugging and evaluation.

Follow-ups such as "show Engineering instead" update the relevant filter while retaining the established scope. Clarify terms when different interpretations materially change the population or meaning. Conversation history resolves references but is never evidence.

General conversational questions retain the project plan's database-wide contract. Select the latest successful Run for each Batch at the start of a new general question. Failed Runs do not replace successful results. Follow-ups about an earlier finding retain its producing Runs and disclose newer results rather than silently substituting them.

Cross-Batch aggregation uses confirmed known-Tool identities. Unknown observed Tools remain Batch-scoped. Count supplied events without automatic deduplication, disclose exact-overlap or conflicting-ID warnings, and retain Batch-qualified event references. Disclose material model or rule version differences across contributing Runs.

LangGraph persistence is available for future execution recovery, but this ADR does not require saved conversations. The initial chat lifetime remains the current open session. Reloading starts a new conversation, as specified in the project plan.

## Findings and evidence

Produce structured findings before rendering the briefing. Each finding includes:

- A concise statement of what deserves attention.
- Observed facts and metrics with claim-linked evidence references.
- An interpretation that explains why the facts matter together.
- Material unknowns and limits on the conclusion.
- A clearly labeled advisory next step when supported.

The response also identifies its event-time scope, filters, count definitions, and contributing Analysis Runs. Aggregate evidence exposes the query definition and a way to inspect included records. A short conversational answer need not use the full briefing format.

For example, adoption across Finance and Engineering can justify an approval review. It does not establish that employees submitted sensitive data. Missing vendor terms remain unknown, and an unresolved determination remains unresolved.

Use recorded result lineage to explain a determination or assessment. Semantic retrieval supplies relevant retained context, but cannot replace the evidence that produced the stored decision. Recommendations distinguish project demonstration rules, general governance guidance, and recorded organization-specific policy.

Validate output schemas and reference existence in code. Those checks do not prove that an interpretation follows from its evidence. Evaluate claim support separately.

## Boundaries and execution controls

Use configurable tool-call, repair-attempt, CPU, memory, runtime, and output-size limits across the turn and its executions. Repairs and analytical revisions consume the same finite turn budget; they cannot reset it. Retrieved passages, uploaded text, and conversation content cannot expand tool permissions. The assistant has no live-web browsing, approval, enforcement, or assessment-writing tools.

The initial briefing operates on stored pipeline outputs and their retained evidence. Document retrieval follows when a controlled local corpus and its evaluation cases exist. No vector database, embedding model, LLM provider, or autonomous remediation workflow is selected here.

## Considered options

- **LangGraph with one agent, chosen.** Explicit transitions support standard briefing coverage and adaptive follow-up queries in the same workflow. State carries filters and result provenance between steps. The cost is an additional dependency and responsibility for graph state and transitions.
- **OpenAI Agents SDK.** Function tools, sessions, and tracing fit a conversational tool loop. LangGraph is preferred for explicit control over the deterministic briefing steps and the investigation loop. This is a project-fit decision, not a claim that the SDK cannot implement the workflow.
- **Direct model SDK loop.** Provides full control with fewer framework concepts, but requires application code for execution transitions, state, and recovery behavior.
- **Vector retrieval followed by a summary.** Useful for document questions, but cannot establish complete event counts or temporal comparisons.
- **Predefined query tools only.** Simpler to validate and operate, but requires a new tool or backend change for each unsupported analytical method. Retain these tools for direct queries and standard summaries.
- **Controlled Python over prepared datasets, chosen alongside predefined tools.** Supports custom methods and artifacts without database or host access. Requires immutable inputs, worker isolation, resource controls, execution provenance, and separate evaluation of methods and claims.
- **Generated arbitrary SQL or unrestricted code execution, rejected.** Would expose database or host capabilities beyond the validated query and isolated dataset contracts. Controlled Python does not authorize either.

## Agent patterns to explore after initial delivery

Revisit these options after the Batch briefing and analyst-directed filters/follow-ups are implemented and evaluated. This exploration does not block those stages or replace the current decision: one agent in LangGraph, with deterministic briefing steps followed by a bounded ReAct-style tool-selection/result loop and response validation. LangGraph is the orchestration framework; ReAct describes an agent interaction pattern, not a competing framework.

| Option | Question to evaluate |
|---|---|
| Fixed workflow | Can predefined investigation steps meet the required coverage with fewer calls and simpler validation? Use as a baseline. |
| Bounded ReAct-style loop | Does choosing each next tool from observed results improve investigation coverage and evidence support within the turn budget? Use the initial implementation as the baseline. |
| Plan then execute | Do explicit investigation plans and bounded replanning improve longer investigations enough to justify additional calls and state? This need not introduce additional agents. |
| Code-agent approach, including Hugging Face `smolagents` | Does expressing analytical actions as code improve supported custom analyses compared with invoking controlled Python through a typed tool? Any experiment must preserve backend-owned data selection, immutable datasets, worker isolation, and provenance. |

Compare the same representative questions and known-answer cases using coverage, computational correctness, method appropriateness, claim/citation support, tool/model calls, latency, cost, and failure recovery. Framework changes require a separate decision supported by those results. Code-agent experiments must wait until the complete custom-analysis execution boundary is implemented; no pattern or framework supplies that boundary automatically.

## Delivery and acceptance

Deliver one complete path first: a Batch briefing over stored analysis results, with drill-down to evidence. Then add analyst-directed filters and follow-ups using the same tools. Deliver dataset preparation, isolated Python execution, artifact inspection, provenance, and bounded repair as one complete custom-analysis path before enabling generated code. Add controlled document retrieval after the structured investigation path works.

Acceptance scenarios must establish the following behavior:

- Counts, grouped summaries, and period comparisons match independently specified fixture expectations and database queries.
- The standard briefing covers unapproved and flagged contexts, unresolved outcomes, and material missing evidence.
- A department-and-date question applies the intended filters. A follow-up changes only the requested scope, with clarification for material ambiguity.
- General questions and historical follow-ups obey Run selection, cross-Batch identity, overlap disclosure, and provenance rules.
- Every material factual claim has valid supporting references. Interpretations do not assert sensitive-data submission, policy violations, or changed tiers without evidence.
- No-match results, sparse or conflicting evidence, truncation, execution-budget stops, and service failures remain distinguishable.
- Known-answer custom analyses match independently specified expected computations, including dataset grain, joins, requested population, and filter/Run scope; previews and output limits never masquerade as complete populations.
- Missing denominators, sparse baselines, missing fields, overlapping Batches, and conflicting sources retain qualifications or cause appropriate abstention. Numerically correct outputs with unsupported methods or interpretations fail their scenarios.
- Attempts to read outside mounted inputs, access credentials or the network, modify inputs/application state, or expand artifact access are denied by enforced isolation and scope controls, including when directed by untrusted text.
- CPU, memory, runtime, and output limits terminate or bound execution as specified. Recoverable code errors can be corrected only within explicit budgets; exhausted repairs and worker/service failures return failed turns without incomplete findings.
- Result and artifact references resolve to the exact producing execution, code attempt, immutable inputs, environment versions, and retained warnings/status. Historical follow-ups remain traceable after newer Runs and chat reloads.

Inspect tool traces alongside answers. Report execution success, computational correctness, method appropriateness, interpretation/claim support, citation correctness, and document-retrieval relevance separately. Exact evaluation datasets, model/provider, worker/isolation technology, library versions, budgets, retention policy, and API signatures remain deferred implementation decisions within these boundaries.

## Relationship to the project plan

The conversation initially proposed a selected-Batch starting point and discussed persistent investigations. The project plan instead makes database-wide chat the core conversational scope and requires only open-session history. This ADR adopts the selected-Batch briefing as the first deliverable while preserving those conversational contracts. Saved chats and automatic post-analysis briefings remain deferred.

This ADR narrowly extends the plan's “Aggregate counts and trends” and “Structured questions” clauses: deterministic backend queries remain authoritative for data selection, counts, filters, and standard summaries; additional analytical computations may use generated Python over prepared datasets, with execution-linked derived evidence. It also extends the statement that no new assistant analysis workflow is introduced to permit this controlled investigation path, without changing the Batch upload/re-analysis lifecycle. The plan's execution-failure clause is refined only for recoverable generated-code errors; database, retrieval, model-service, and worker/service failures still fail the turn. Read-only assessments/application records remain mandatory; retaining analysis inputs, execution records, and artifacts is technical provenance, not permission to write assessments. These are explicit amendments for this capability, not changes to unrelated product contracts; PROJECT_PLAN.md is otherwise unchanged.

## References

- [Project plan: assistant contracts](../../PROJECT_PLAN.md#rag-governance-assistant-contract--confirmed-implementation-details-deferred).
- [ADR 0002: AI Determination](0002-binary-ai-detection-uses-gated-jev-judge.md).
- [ADR 0003: Category Classification](0003-category-classification-uses-semantic-neighbor-vote.md).
- [Microsoft Security Analyst Agent](https://learn.microsoft.com/en-us/defender-xdr/security-analyst-agent). Inspiration for this project’s investigation pattern: the documentation describes KQL retrieval, Python analysis, custom investigations, and supporting artifacts. It does not establish Microsoft’s internal framework, agent count, exact tool interfaces, or whether every analysis uses generated code; those are not implementation facts inferred here.
- [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview).
- [LangGraph workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents).
- [Hugging Face smolagents](https://huggingface.co/docs/smolagents/index). Candidate for deferred code-agent exploration.
- [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/).
