# Frontend implementation roadmap

Updated November 24, 2026. Scope and contracts: [Frontend PRD](PRD.md).

Build on the `frontend` branch against the existing FastAPI backend. Start locally, use the owner's forthcoming pen.dev/HTML design, and review each completed milestone together before starting the next. This frontend roadmap supplements the repository's root `ROADMAP.md`.

## Current position

- [x] Review previous frontend planning chats and existing wireframe/IA work.
- [x] Bring local and remote `frontend` up to backend baseline `d271c83`.
- [x] Verify backend suite: 499 tests and 7 subtests passed; live test skipped.
- [x] Draft frontend PRD, integration map, and this roadmap.
- [ ] Review PRD and incorporate design handoff.
- [ ] Implement frontend. No application code has been created yet.

## Working agreement

Each milestone follows: understand the user task → trace the relevant API/data flow → implement the complete slice → verify its failure states → demo and review together. Save a short record of decisions and screenshots for portfolio evidence. Do not begin every screen at once.

At review, explain what changed, where data originates, what the tests establish, what remains incomplete, and the proposed next milestone. Check boxes only for verified results. No fixed calendar dates are assumed.

## Milestone 0 — Design handoff and scope alignment

- [ ] Read the supplied pen.dev design and HTML; identify reusable assets, typography, colors, navigation, and intended viewport behavior.
- [ ] Map every screen and displayed metric to PRD requirements and actual backend fields.
- [ ] Identify visuals that imply unavailable capabilities; agree how to omit, label, or defer them.
- [ ] Confirm branding, themes, and whether HTML should guide or seed the React implementation.
- [ ] Agree the proposed stack and local single-analyst scope.

Deliverable: reviewed design-to-data map and revised PRD. Dependency: design handoff. Exit: the first upload/batch milestone has a concrete visual reference and no unresolved critical interaction decisions.

## Milestone 1 — Application foundation and backend connection

- [ ] Scaffold Next.js, React, TypeScript, styling, package lock, and quality commands in `frontend/`.
- [ ] Create design tokens and only the primitives needed by initial screens.
- [ ] Build responsive navigation and page layout from the supplied design.
- [ ] Configure server-only `BACKEND_URL` and an allowlisted same-origin API bridge.
- [ ] Generate OpenAPI types; implement shared fetch/error handling and query serialization.
- [ ] Add query provider, safe backend-unavailable state, and local setup instructions.

Backend connection: `GET /health`, `/openapi.json`; FastAPI remains the source of application data. Exit: local frontend reaches the actual backend, secrets remain server-side, and navigation/error handling works. Review the shell and explain browser → bridge → FastAPI before proceeding.

## Milestone 2 — Complete upload and Batch workflow

- [ ] Build paginated dataset directory and accessible CSV upload.
- [ ] Add schema help, selected-file state, indeterminate upload/analysis state, and duplicate-submission prevention.
- [ ] Render line/field validation errors and duplicate-upload outcomes.
- [ ] Build Batch detail showing filename, event count, period, latest attempt, and latest successful Run.
- [ ] Handle successful HTTP upload with failed analysis distinctly from failed ingestion.
- [ ] Recover from connection loss without automatically repeating a write.

Backend connection: `GET/POST /batches`, `GET /batches/{batch_id}`. ML connection: creation triggers identity → website evidence → AI → category → contextual risk before responding. Exit: demonstrate valid, invalid, duplicate, and analysis-failed uploads plus reopening a Batch. This is the first complete product slice.

## Milestone 3 — Run history and shared findings scope

- [ ] Build Run history and explicit reanalysis action.
- [ ] Display running/succeeded/failed outcomes, failure phase, versions, and timestamps.
- [ ] Handle already-running conflicts and uncertain request outcomes.
- [ ] Add Batch/Run selection and UTC date scope in URL state.
- [ ] Preserve historical Run links and distinguish latest attempt from latest success.
- [ ] Implement shared coverage, warning, no-data, and no-successful-results components.

Backend connection: `GET /batches/{id}/runs`, `POST /batches/{id}/runs`, `GET /runs/{id}`, scoped read envelopes. Exit: inspect two Runs without confusing their results, and retain an earlier successful result after a later failure.

## Milestone 4 — Overview connected to real findings

- [ ] Render backend headline metrics and count definitions.
- [ ] Add AI/risk distributions, department/category breakdowns, and unresolved-stage indicators.
- [ ] Add time trends while preserving uncovered/null buckets.
- [ ] Link relevant summaries to filtered application/context listings as those destinations land.
- [ ] Verify totals use full backend aggregations, not loaded table rows.

Backend connection: `GET /overview`. Exit: values agree with the API for the selected scope; filters, empty states, coverage warnings, keyboard use, and narrow layout behave correctly. No mock values in the connected product.

## Milestone 5 — Application inventory and ML explanation

- [ ] Build server-paginated application table, supported search, and shared/AI/identity filters.
- [ ] Keep known Tools, observed Tools, and unresolved candidates visible and distinguishable.
- [ ] Build Run-pinned details and preserve list filters on return.
- [ ] Display candidate-level AI outcome, review flags, evidence sentences, and source.
- [ ] Display category method, unresolved/inapplicable reasons, and Semantic Neighbors.
- [ ] Link available contexts and label any highest contextual tier correctly.

Backend connection: `GET /applications`, `GET /runs/{run_id}/applications/{subject_kind}/{subject_id}`. Exit: explain identity, AI determination, and category for one application using actual returned evidence; demonstrate an unresolved candidate too.

## Milestone 6 — Risk investigation and activity drill-down

- [ ] Build context table with tier, flags, department, purpose, sensitivity, and supported filters.
- [ ] Build context detail with original assessed scope, rule version, facts, reasons, and unknowns.
- [ ] Connect application ↔ context ↔ event navigation.
- [ ] Build paginated events view using the backend-provided Run/context query.
- [ ] Distinguish filtered activity from the original context and eligible-unresolved from inapplicable risk.

Backend connection: `GET /contexts`, `GET /runs/{run_id}/contexts/{context_id}`, `GET /events`. Use these instead of the deprecated assessments endpoint. Exit: analyst can answer “What use is flagged, why, and which events belong to it?” without a global Tool risk claim.

## Milestone 7 — Evidence inspection and complete core demo

- [ ] Build reusable typed evidence resolution and display.
- [ ] Show source role/version, applicability, excerpts, model outputs, and truncation.
- [ ] Handle unavailable, missing, invalid, and unsupported evidence references.
- [ ] Connect citations and source actions from application and risk views.
- [ ] Verify the full upload → results → investigation → evidence journey in a browser.
- [ ] Review accessibility, responsive behavior, stale-request handling, and meaningful error states across the core UI.
- [ ] Document local setup, required services, known limitations, and a reproducible synthetic demo.

Backend connection: `POST /evidence/resolve` plus prior listing/detail APIs. Exit: a teammate completes the core investigation task and opens supporting evidence. Record usability feedback and fixes. This milestone is the core frontend release even if the assistant is still blocked.

## Milestone 8 — Governance assistant when backend contracts are ready

- [ ] Coordinate public HTTP contracts, selected-Batch briefing, session/history needs, scope selection, errors, and citation envelopes with the backend owner.
- [ ] Confirm actual capability availability, including absent document retrieval; do not infer readiness from internal adapters.
- [ ] Build briefing and conversation UI with clear pinned scope.
- [ ] Render claims, interpretations, citations, limitations, and advisory next steps distinctly.
- [ ] Preserve previous messages on failure; support retry and limited/clarification responses.
- [ ] Integrate evidence actions and verify scope remains attached to historical answers.

Backend connection: future public endpoints over existing LangGraph/Gemini and query adapters; exact paths remain TBD. Blocked until those contracts exist. Streaming, generated Python artifacts, and saved chat UI are separate decisions, not assumed initial features. Exit: real backend responses and citations work end to end; advisory text cannot alter stored risk decisions.

## Milestone 9 — Deployment planning and optional extensions

Deferred until local core review:

- [ ] Choose frontend/backend hosting and persistent storage.
- [ ] Decide access control and whether shared multi-user state is supported.
- [ ] Validate long-running upload/reanalysis behavior against hosting timeouts; coordinate async jobs if needed.
- [ ] Protect service credentials and document environment configuration.
- [ ] Agree any export, saved investigation, approval editing, theme, or additional analytics requirements and their backend dependencies.
- [ ] Run hosted acceptance checks before calling deployment complete.

Exit: separately approved hosting scope and verified deployment. No deployment is required to finish the local core frontend.

## Verification and review checklist for every implemented milestone

- [ ] Acceptance behavior demonstrated against the actual contract.
- [ ] Relevant type checks, lint, focused interaction tests, and browser checks pass.
- [ ] Loading, empty, failure, and recovery states tested where applicable.
- [ ] Keyboard access and narrow viewport checked.
- [ ] Offline fixtures and live service checks clearly distinguished.
- [ ] PRD/roadmap updated for real decisions and remaining dependencies.
- [ ] Milestone reviewed together before the next begins.
