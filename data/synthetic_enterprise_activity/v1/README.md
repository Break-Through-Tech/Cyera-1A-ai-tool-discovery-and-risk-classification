# Synthetic enterprise activity v1

`activity.csv` is a fictional Dataset A upload: 265 Activity Events from 44
active synthetic employees, across nine departments and 12 evaluation
scenarios in 10 observed applications. The generator creates 72 fictional
employee profiles; not every employee has an event in this sample. Its
frequencies measure scenario coverage, not real enterprise prevalence.

`generate_activity.py` uses only the Python standard library and fixed seed
`20261014`. It samples department and role distributions, department-specific
application adoption rates, and per-employee/tool event counts from a
gamma-Poisson negative-binomial distribution (capped at 20). It weights
weekdays more heavily than weekends and business hours more heavily than
evenings. Each evaluation scenario is guaranteed at least two active
employees; this deliberate coverage floor is not a prevalence estimate.
Department/role weights, adoption rates, event-count parameters, and time
weights are illustrative simulation assumptions, not fitted to real workforce
telemetry.
Regenerate the activity and matching evaluation-only event mapping with:

```powershell
python -B data\synthetic_enterprise_activity\v1\generate_activity.py --write
python -B data\synthetic_enterprise_activity\v1\generate_activity.py --check
```

Each activity row has a unique `event_id` and UTC `Z` timestamp. `job_role`
is optional, entirely synthetic employee context. Purpose and sensitivity
are supplied synthetic context; neither is inferred from department or
activity. An `app_open` or `browser_visit` does not establish that any prompt,
document, or sensitive content was submitted.

`scenario_tool_metadata.csv` is separate runtime scenario metadata, not model
training data and not a known-Tool registry. It supplies optional functionality
text and fictional policy/vendor assumptions. `approved_status`,
`training_on_customer_data`, and `admin_controls_available` are synthetic
demonstration facts, **not claims about the real named vendors**. `unknown`
stays unknown. Workbench intentionally has no metadata row or live website:
`.example` is reserved, so a failed enrichment attempt should leave the
candidate unresolved. Magic Inspector intentionally has no supplied
functionality text, allowing a real bounded website-enrichment test; if that
fetch fails, the system should abstain and record why rather than force a
classification.

Only the two CSVs above are inference inputs. Do not upload or index
`evaluation_only/expected_scenarios.csv` or its partition contract. The
hidden CSV maps scenario IDs to `event_id` values and expected Tool identity,
AI status, Category, and contextual risk behavior. It contains no employee
data. Different ChatGPT departments are separate Usage Contexts; both have
the same synthetic risk facts and therefore the same Lower tier. Non-AI and
AI-unresolved cases do not receive a contextual-risk tier. Open Canvas AI is
a fictional reviewed AI scenario whose category and risk remain unresolved.

The two catalog-held-out Tools are in the frozen **test** partitions of both
the binary and category datasets. The independently reviewed Comprehend and
Playbooks descriptions are in the binary **test** partition and have no
matching product in the cleaned AIToolBuzz catalog snapshot. Their 14-category
answers are fixture-review mappings, not imported source labels. Slack and
Mattermost are reviewed ordinary-software controls in the existing enterprise
description records; those labels apply to the reviewed descriptions and do
not assert that every feature of those products is non-AI. The partition
contract records IDs, source manifest hashes, and required exclusions.
The application must exclude the held-out Tools from lookup and retrieval
evidence at the evaluation cutoff before reporting them as previously unseen;
these files alone do not enforce that contract.

The fixture uses the project's synthetic demonstration risk rule:
unapproved + training permitted gives High; approved + no training + admin
controls gives Lower; other classifiable cases with usable facts give Medium;
all risk facts unknown gives unresolved. An independent investigation flag
tracks High, unapproved, training permission, missing admin controls, or
insufficient evidence for any tier. These rules assess Usage Contexts, not
global Tool risk. They are not a security certification or organizational
policy claim.

Functionality descriptions for Amazon Comprehend and Playbooks are short
paraphrases of their [official product pages](https://aws.amazon.com/comprehend/)
and [InsideSales Playbooks page](https://www.insidesales.com/playbooks/),
consulted on 2026-10-14. All other descriptions are labeled as source-snapshot
or synthetic scenario text in the metadata CSV. Website evidence can change;
the current fixture does not itself test catalog-to-website transfer quality.
