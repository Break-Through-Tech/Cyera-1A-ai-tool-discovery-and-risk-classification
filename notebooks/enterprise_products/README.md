# Enterprise products EDA and cleaning

Run from the repository root:

```sh
python3 notebooks/enterprise_products/eda.py
python3 -m unittest discover -s notebooks/enterprise_products -p 'test_*.py'
```

The script reads the byte-preserved `data/technology-product-categorization/products.csv` and regenerates `report.json`, `REPORT.md`, and `review_candidates.csv` in this directory. It uses only Python's standard library. No input file is modified.

`review_candidates.csv` contains only records with review cues, but retains all original product, vendor, source category/subcategory, and description values. `source_record_number` is the one-based logical CSV data-record number (excluding the header), so it remains correct when quoted descriptions contain newlines. Related repeat/group records are listed by the same logical numbering. Reasons are cues for human review, never automatic exclusion, identity resolution, label assignment, or deletion. Generic-service, fee-name, placeholder, description-length, and AI/ML keyword reasons use narrow script-defined heuristics; AI/ML mentions do not establish AI status, and differences from broader literal scans are expected. Source label differences are not treated as errors.

The exact full-row duplicate check requires all five parsed field values to match exactly; it does not trim or case-fold. Name/vendor repeat groups use separately reported trimmed case-sensitive and normalized keys; repeated keys are not confirmed identities. The EDA describes the supplied source taxonomy only. It does not create project labels, map to the 14 AIToolBuzz targets, or establish AI/non-AI status. The optional raw AIToolBuzz description-style comparison was not run. Per `data/technology-product-categorization/SOURCE.md`, reuse permission is unresolved; resolve it before training or redistribution.

## Reproduce the approved cleaned view

```sh
python3 notebooks/enterprise_products/clean.py
python3 -m unittest discover -s notebooks/enterprise_products -p 'test_*.py'
```

The cleaner reads the pinned original snapshot and writes separate, generated artifacts:

- `data/technology-product-categorization/products_cleaned.csv`
- `data/technology-product-categorization/cleaning_report.json`

Rules:

- Trim outer whitespace and convert CRLF/CR line endings to LF. Keep internal spacing, punctuation and legitimate Unicode; do not guess or repair lost characters.
- Exclude `NEED PRODUCT DESCRIPTION`, descriptions containing the actual replacement character `�`, and empty descriptions if encountered.
- Exclude only the two reviewed name/vendor pairs: Signature Services / QLIKTECH INC and Hyperion BI Analysis Fee / KURT STECKEL. Other names containing “support”, “suite”, “service” or “fee” are not automatically excluded.
- Assign a deterministic `product_group_id` from normalized product name plus vendor, following the approved multi-category membership assumption. Keep all eligible source rows and their category/subcategory pairs; do not choose the first label or merge differing descriptions. Identical descriptions for differently named products do not establish shared identity.

The cleaned CSV adds only `source_record_number` and `product_group_id` to the five source fields; it adds no encoding flag or AI labels. Record numbers refer to logical CSV data records, not physical lines. The report records source/output/code checksums, rule version, excluded record references and reasons, normalization counts, category supports and repeated-group memberships. Reason counts can overlap; `excluded_records` counts distinct source records.

The default input checksum must match the source card. Schema/row-width errors and missing identity/taxonomy fields fail before outputs are written. Input/output/report aliases, including symlinks and existing hard links, are rejected. Re-running intentionally regenerates the two output artifacts; do not hand-edit them.

This remains a source-taxonomy dataset, not an AI/non-AI training set or a mapping to the 14 AIToolBuzz categories. Grouping is source-scoped, not verified cross-source identity. Shared descriptions across different product groups still need leakage review before partitions are frozen. Further fee/support candidates need explicit review; broad keyword-based deletion is not an approved rule.
