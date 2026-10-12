# Authorized calibration recovery

The user authorized fixing search configuration and continuing the same twenty-group calibration. The prior workflow is stopped; its artifacts and checkpoints remain historical evidence, not completed labels. This contract supplements, and for recovery-specific instructions supersedes, `STAGE_CONTRACT.md`. The frozen labeling rubric and source inputs are unchanged.

## Fixed search route

`/home/newton/.pi/web-search.json` now contains only `{"provider":"anysearch"}`. There was no existing configuration file to overwrite. AnySearch is the documented anonymous search provider. Explicit-provider and omitted-provider smoke lookups returned actual product source URLs after the configuration change. No API keys or browser credentials were added or accessed.

Use this configured route for discovery. Omit `provider` or explicitly set `provider: "anysearch"` on web_search/source_check. Do not select OpenAI, Brave, Exa, or other providers. Do not access browser profiles, change account settings, or patch installed extensions. All labeler/verifier/adjudicator models remain exactly `openai-codex/gpt-6-luna:high`.

The OpenAI search adapter's obsolete hard-coded model selection and Exa quota were infrastructure blockers; they are not evidence about product functionality. Search summaries remain discovery aids, not final citations.

## Resume without repeating completed work

Research stages (labeler and blind verifier) must first read their own cwd's `resume_packet.json`. It contains prior consumed and remaining allowances, exact prior tool references, preserved fetched-page paths, and any completed group checkpoints. These counts were reconciled by the parent against actual per-query/per-URL tool arguments, including failed discovery attempts. A multi-product search call consumed one round for each affected group; multiple queries for one group in the same call consumed one round for that group.

- Reuse completed group checkpoint judgments without rerunning that group's research. The one completed blind-stage judgment is provisional until the other stages verify it; do not treat it as a final accepted annotation.
- For unfinished groups, read retained source pages before making new searches or fetching the same page again. Retained page files contain actual acquired content, source URL/title, errors, source-session reference, content hash, and real capture time from the original tool event. They are evidence snapshots, not new web requests.
- The original extension's search cache is process-local; old response IDs are not retrievable from a new child with get_search_content. Use the provided retained-page files instead. If a snapshot contains only an access error or insufficient text, preserve that limitation and use remaining research allowance, rather than invent content.
- Inspect your own `prior_research_tool_events.json` only as needed for prior discovery context and exact error records. These are your stage's own prior results, not sibling judgments.
- Do not reset allowances. Final/checkpoint research counts are cumulative across the stopped attempt and recovery. A group with zero remaining search rounds may still use its remaining page reads and existing discovered URLs; if evidence remains insufficient, send it through the bounded adjudication/forced-decision policy.
- Query each unfinished product specifically. Do not restart a whole batch's broad research or substitute a search failure for a negative label.

Blind verifier isolation still applies: never read labeler results, checkpoints, recovery packets, retained pages, or other judgments before recording your independent judgment. Your permitted recovery inputs are only your own previous work and the shared frozen source/rubric inputs. Evidence verifiers and adjudicators may inspect both completed independent proposals and the specific cited retained pages.

## Failures and output

Checkpoint completed groups within your exclusive stage directory. Write only authorized checkpoints and your bound result artifact. Return complete group coverage only when the stage actually completes.

If the configured search route itself fails transiently, report the failure with checkpoint state for the one permitted same-protocol retry. Unsupported/missing configuration stops immediately. Never fill a successful result schema with placeholder labels to hide incomplete infrastructure work. A blocker/failure checkpoint is separate from successful annotation JSON; the parent must not accept it as annotations.

The calibration still stops after twenty groups and reports its results before the remainder. No training, source/cleaner modifications, automatic grouping exceptions, commits, pushes, merges, or additional dataset groups are authorized.
