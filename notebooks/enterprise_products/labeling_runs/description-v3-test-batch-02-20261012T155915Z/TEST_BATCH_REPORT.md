# Test batch 2 — waiting for human review

Open [the read-only review page](review.html). Start with **Show cases → Weak evidence (6)**, then review independent judgments and reconciliation explanations. No further batch, merge, partitions, training or historical-run changes are authorized.

## Results

- 20 new exact descriptions → 31 source rows; no overlap with the first v3 calibration.
- Final binary: **8 AI / 12 non-AI**. Independent binary agreement: 20/20, which is not an accuracy estimate.
- Supported negatives: **9 distinct descriptions / 18 row references**. Duplicate references are not separate independent examples.
- **3 weak/forced binary negatives**: records 414–416 (Programming Language), 581 (Modelling for 5G), 1414 (Email support). Excluded from trusted binary and negative pools.
- **3 weak/forced AI subtypes**: records 49 (Datacap), 206 (Driveway Location Services), 235 (IEX Workforce Management). Supported binary AI remains intact; subtype uncertainty is separate and excluded from trusted subtype labels.
- Final subtypes: 3 AI-enabled, 5 AI-native (including the 3 weak/forced subtypes).
- One bounded continuation of the original blind verifier reconciled 7 descriptions: the 6 weak cases plus the shared EA-tools description (records 1028–1034). No third semantic model or web research.
- Identical text was joined across five shared-description groups; 11 extra source rows inherited the exact-text annotation. No propagation by product name/group to unequal text.
- Across both v3 batches: **40 descriptions / 51 rows covered; 1,351 descriptions / 1,387 rows remain unapproved**. The generated calibration report's remainder is per-run, not cumulative.

## Checks that caught real problems

1. Native schema rejected one missing required `ai_type_rationale: null`; the labeler corrected it once without changing any decision.
2. Three independent EA evidence quotes omitted source line breaks. Parent restored only the exact original whitespace in separate accepted handoffs. Raw native results/checkpoints remain unchanged; labels, rationales and flags were not rewritten. See `STRUCTURAL_CORRECTIONS.json` and the page's quote-repair disclosure.
3. Parent challenged three subtype-consensus assumptions (49, 206, 235). Reconciliation retained supported binary AI but explicitly marked the forced subtype weak. Agreement alone did not establish subtype support.

Bound-result materialization worked for both independent agents and reconciliation. No transport recovery or extra labeling run was needed.

## Review-page validation

- 4 renderer tests and all 36 enterprise tests pass.
- Native Chrome desktop (1440×1000) and responsive width simulation (390×844) visually reviewed; no horizontal overflow, correctly stacked comparisons.
- DOM text exactly matches all 20 original descriptions, 31 source references and 40 final evidence quotes.
- Filters verified: all 20/31 rows, uncertain 6/8, reconciled 7/15, supported negative 9/18.
- Comparison, reconciliation, seven-row provenance and whitespace-audit disclosures opened and verified. No console messages, page errors or external resources.
- Parent made source record/product headings visible and preserved audit quote line breaks in the renderer, then regenerated the HTML. No label/export change.
- QA required a dedicated local Chrome launch with `--no-sandbox` because this host blocks sandbox startup; no remote pages were visited. Other browsers, real mobile hardware and formal screen-reader auditing were not checked.

Evidence: `UI_VALIDATION.json`, `runtime/screenshots/`, `PARENT_ACCEPTANCE.json`, native session captures and stage receipts.

## Reported Luna usage

Second-batch labeling: 132,044 reported tokens, **$0.03124040**. Review-page worker: 43,100 tokens, **$0.01044728**. Total: 175,144 tokens, **$0.04168768**.

These are native metadata estimates, not an invoice; they exclude parent Sol usage and do not double-count outer workflows. See `USAGE_REPORT.json` for per-child receipts.

## Review boundary

Names/vendors help locate source rows but are not labeling evidence. These are historical description-based labels, not claims about current product capabilities. Accepting the batch cannot upgrade weak evidence. Tell the parent which source records look wrong before authorizing any further work.
