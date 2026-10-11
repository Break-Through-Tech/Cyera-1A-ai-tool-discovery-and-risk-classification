# Enterprise products: first-pass EDA

**Analyzed input:** `data/technology-product-categorization/products.csv` · 1494 logical records · SHA-256 `afe7cdbcbf82d9b11f579eb6dce000815a04a301410636e2942036f072fc7aa1`. The source file is preserved byte-for-byte.

## Dataset and taxonomy

This is an imported product/vendor catalog, not enterprise activity and not a reviewed AI/non-AI dataset. Source taxonomy remains unchanged; it is not mapped to the project's 14 AIToolBuzz targets. The local file contains 13 categories and 59 observed subcategories; this is not a claim of full-taxonomy coverage. Parent-child consistency: **consistent** (0 subcategories assigned to multiple source categories).

| Source category | Records | Share |
|---|---:|---:|
| IT Infrastructure Software Services | 279 | 18.7% |
| Enterprise Platforms | 238 | 15.9% |
| Design, Development & Delivery | 174 | 11.6% |
| Customer Operational Platforms | 149 | 10.0% |
| Performance, Monitoring & Logging | 142 | 9.5% |
| BI & Data Analytics | 115 | 7.7% |
| Marketing Management | 89 | 6.0% |
| Telecom Network Management | 88 | 5.9% |
| Management & Governance | 68 | 4.6% |
| Digital Workplace | 64 | 4.3% |
| Geographic Information Systems (GIS) | 51 | 3.4% |
| AI & ML | 30 | 2.0% |
| Emerging Technologies | 7 | 0.5% |

Description length (trimmed characters): min 13, median 260.0, nearest-rank p90 546, max 1674. 42 are under 40 characters, 6 are name-only, and 2 match the narrow placeholder/boilerplate definition. These are review thresholds, not eligibility cuts.

## Hygiene and repeat cues

Hygiene issue counts (overlapping review cues; not all distinct rows): `encoding_or_control_anomaly:product_description` 53; `missing_or_placeholder:product_description` 2; `outer_whitespace:product_description` 16; `repeated_whitespace:product_description` 406; `repeated_whitespace:product_name` 5; `replacement_character:product_description` 52; `suspected_mojibake:product_description` 1.
Notable findings: 52 descriptions contain U+FFFD replacement characters; 2 equal `NEED PRODUCT DESCRIPTION`; 0 product-description HTML tag matches. Replacement and placeholder examples: record 882 Address Cleaning Solution (replacement character); record 883 L Series Communications Tax (replacement character); record 885 Q Series Communications Tax (replacement character); record 717 Linux Workstation (placeholder: NEED PRODUCT DESCRIPTION); record 723 Resilient Storage (placeholder: NEED PRODUCT DESCRIPTION).

Exact full-row duplicates: 0 extra rows (all five parsed fields must match exactly; no trimming/case-folding). Name/vendor repeat units: 25 case-sensitive trimmed groups; 26 normalized groups; 32 excess records; 39 pairwise comparisons. There are 35 normalized-description repeat groups. These counts are different units; repeated identity is unconfirmed.

Normalized name/vendor groups with category disagreement: 22; with subcategory disagreement: 25; with either: 25. Differences are preserved review observations, not errors or relabeling.

- Repeat-key example: 1177 Snowflake Platform: AI & ML / Development; 1178 Snowflake Platform: Customer Operational Platforms / Ordering & Billing; 1179 Snowflake Platform: BI & Data Analytics / Analytics Database.
- Repeat-key example: 69 Open Studio for Data Integration: BI & Data Analytics / Data Movement Management; 70 Open Studio for Data Integration: Management & Governance / Risk & Compliance.
- Repeat-key example: 75 Virtual App and Desktop: Digital Workplace / End-User Compute; 76 Virtual App and Desktop: IT Infrastructure Software Services / Virtualization.
- Repeat-key example: 316 tagVUE MX: Customer Operational Platforms / Retail & Ecommerce; 317 tagVUE MX: Management & Governance / Asset Management.
- Repeat-key example: 325 MEC Solutions Platform: Emerging Technologies / Internet of Things (IOT); 326 MEC Solutions Platform: Design, Development & Delivery / Software Design & Development.

Vendor concentration (normalized vendor keys): ibm 90 (6.0%); amazon web services 62 (4.2%); oracle 56 (3.8%); micro focus us inc 50 (3.4%); microsoft corp 37 (2.5%). Top four share: 17.3%.

## Focused review examples

- Placeholder, record 717: **Linux Workstation** — IBM; IT Infrastructure Software Services / Operating Systems. “NEED PRODUCT DESCRIPTION”
- Placeholder, record 723: **Resilient Storage** — IBM; IT Infrastructure Software Services / Storage Management. “NEED PRODUCT DESCRIPTION”
- Replacement character, record 882: **Address Cleaning Solution** — VERTEX INC; Enterprise Platforms / Finance. “Vertex's Address Cleansing Service gives companies a solution for tracking sales tax changes and applying them across transaction and customer data.� The service allows companies to send customer addresses to Vertex in a”
- Replacement character, record 883: **L Series Communications Tax** — VERTEX INC; Enterprise Platforms / Finance. “Sales Tax�L Series�contains current rates updated monthly for every taxing jurisdiction in the United States, its trusts and possessions, and Canada.”
- Generic service/add-on, record 3: **Signature Services** — QLIKTECH INC; BI & Data Analytics / Self-Serve Visualization & Ent. Reporting. “The Signature Services is a package of key services including but not limi]ted to; consulting, customer success, education services, and support that are designed to support Customer in building a successful foundation f”
- Generic service/add-on, record 36: **Business Objects BI Suite, analytics edition** — SAP; BI & Data Analytics / Self-Serve Visualization & Ent. Reporting. “SAP BusinessObjects BI (SAP BO, also historically BOBJ) is a reporting and analytics business intelligence (BI) platform aimed at business users. It consists of a number of reporting applications that allow users to disc”
- Fee product granularity, record 9: **Hyperion BI Analysis Fee** — KURT STECKEL; BI & Data Analytics / Self-Serve Visualization & Ent. Reporting. “Hyperion BI Development Analysis fee in support of Wireless B2B and Public Sector reporting and tables.”
- AI/ML cue within source AI & ML category, record 43: **KORE BOTS Platform** — KORE AI INC; AI & ML / Development. “Kore.ai bots platform provides a secure, scalable, and superior end-to-end solution to design, built, test and deploy AI-powered chatbots. Kore.ai Bots Platform - Kore Bots Platform B2E Licenses Use AI as a customer-serv”
- AI/ML cue within source AI & ML category, record 46: **Comprehend** — AMAZON WEB SERVICES; AI & ML / Development. “Amazon Comprehend is a natural-language processing (NLP) service that uses machine learning to uncover valuable insights and connections in text.”
- AI/ML cue outside source AI & ML category, record 2: **MicroStrategy BI Platform** — MICROSTRATEGY SERVICES CORP; BI & Data Analytics / Self-Serve Visualization & Ent. Reporting. “The MicroStrategy platform supports interactive dashboards, scorecards, highly formatted reports, ad hoc query, thresholds and alerts, and automated report distribution. From data discovery, to pixel-perfect reporting, a”
- AI/ML cue outside source AI & ML category, record 16: **Spark** — APACHE SOFTWARE FOUNDATION; BI & Data Analytics / Data Movement Management. “Spark has been called a 'general purpose distributed data processing engine' and 'a lightning fast unified analytics engine for big data and machine learning'². It lets you process big data sets faster by splitting the w”

AI/ML phrase cue count: 76 records total: 11 within source category AI & ML and 65 outside it. Search covers product name and description only, using these case-insensitive word-boundary phrases: `\b(?:AI|A\.I\.|artificial intelligence|machine learning|ML|generative AI|large language models?|LLMs?)\b`. Broader literal scans can produce different counts; cues and source categories are not labels. Neither absence nor source category establishes AI status.

## Safe next steps and limitations

- Proposed safe normalization: trim outer whitespace and standardize line endings in a separate derived text field, preserving untouched raw values and source references. These recommendations are not applied by this EDA.
- Manual review: do not automatically repair placeholder or replacement-character text, resolve product identity, or change labels; retain the evidence for adjudication.
- Manually adjudicate repeat groups/label disagreements; similar identity clues do not authorize merge or deletion. Multi-category labels may be intentional.
- Inspect short descriptions, generic service/add-on names, and fee-like granularity examples; these flags do not determine eligibility.
- Reuse permission is unresolved per `SOURCE.md`; resolve it before training or redistribution.
- Optional raw AIToolBuzz writing-style comparison was not run. This EDA does not test or prove source/style confounding.

`review_candidates.csv` contains 682 review-only rows with original values, explicit reasons, and logical CSV-record references (not physical line numbers). No labels, automatic exclusions, or identity merges are produced.
