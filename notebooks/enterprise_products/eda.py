#!/usr/bin/env python3
"""Reproducible, review-only EDA for the imported enterprise products CSV."""

import csv
import hashlib
import html
import json
import math
import re
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "data/technology-product-categorization/products.csv"
OUT = Path(__file__).resolve().parent
FIELDS = ("product_name", "vendor_name", "taxonomy_category", "taxonomy_sub_category", "product_description")
PLACEHOLDERS = {"", "-", "n/a", "na", "none", "null", "unknown", "not available", "not applicable", "tbd", "need product description"}
AI_TERMS = re.compile(r"\b(?:AI|A\.I\.|artificial intelligence|machine learning|ML|generative AI|large language models?|LLMs?)\b", re.I)
GENERIC_TERMS = re.compile(r"\b(?:services?|support|subscription|maintenance|implementation|professional services|add[- ]?on|module|license|licensing|package|suite)\b", re.I)
FEE_NAME = re.compile(r"\bfees?\b", re.I)
BOILERPLATE = re.compile(r"^(?:product description|no description available|not available|n/?a|coming soon|need product description)[.! ]*$", re.I)
HTML_TAG = re.compile(r"</?\s*[a-z][^>]*>", re.I)


def norm(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def load_rows(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        header = next(reader, None)
        if header != list(FIELDS):
            raise ValueError(f"schema mismatch: expected {list(FIELDS)!r}, got {header!r}")
        rows = []
        for number, values in enumerate(reader, start=1):
            if len(values) != len(FIELDS):
                raise ValueError(f"logical source record {number}: expected 5 fields, got {len(values)}")
            rows.append({"source_record_number": number, **dict(zip(FIELDS, values))})
    return rows


def percentiles(values):
    ordered = sorted(values)
    if not ordered:
        return {key: None for key in ("min", "median", "p90", "max")}
    rank = max(0, math.ceil(0.90 * len(ordered)) - 1)
    return {"min": ordered[0], "median": statistics.median(ordered), "p90": ordered[rank], "max": ordered[-1]}


def add_reason(reasons, number, reason):
    reasons[number].add(reason)


def analyze(rows, source_path=None, source_sha256=None):
    reasons = defaultdict(set)
    related = defaultdict(set)
    counts = Counter()
    names = defaultdict(list)
    trimmed_names = defaultdict(list)
    descriptions = defaultdict(list)
    exact = defaultdict(list)
    category_pairs = Counter()
    vendors = Counter()
    normalized_vendors = Counter()
    lengths = []
    ai_examples = []
    generic_examples = []
    fee_examples = []
    short_examples = []
    name_only = []
    boilerplate_examples = []

    for row in rows:
        number = row["source_record_number"]
        values = [row[field] for field in FIELDS]
        names[(norm(row["product_name"]), norm(row["vendor_name"]))].append(number)
        trimmed_names[(row["product_name"].strip(), row["vendor_name"].strip())].append(number)
        description_key = norm(row["product_description"])
        if description_key:
            descriptions[description_key].append(number)
        exact[tuple(values)].append(number)
        category_pairs[(row["taxonomy_category"], row["taxonomy_sub_category"])] += 1
        vendors[row["vendor_name"]] += 1
        normalized_vendors[norm(row["vendor_name"])] += 1

        for field, value in zip(FIELDS, values):
            cleaned = value.strip()
            if not cleaned or norm(cleaned) in PLACEHOLDERS:
                add_reason(reasons, number, f"missing_or_placeholder:{field}")
                counts[f"missing_or_placeholder:{field}"] += 1
            if value != cleaned:
                add_reason(reasons, number, f"outer_whitespace:{field}")
                counts[f"outer_whitespace:{field}"] += 1
            if re.search(r"\s{2,}", value):
                add_reason(reasons, number, f"repeated_whitespace:{field}")
                counts[f"repeated_whitespace:{field}"] += 1
            if "�" in value:
                add_reason(reasons, number, f"replacement_character:{field}")
                counts[f"replacement_character:{field}"] += 1
            if "�" in value or any(unicodedata.category(ch) == "Cc" and ch not in "\t\n\r" for ch in value):
                add_reason(reasons, number, f"encoding_or_control_anomaly:{field}")
                counts[f"encoding_or_control_anomaly:{field}"] += 1
            if unicodedata.normalize("NFC", value) != value:
                add_reason(reasons, number, f"unicode_normalization_difference:{field}")
                counts[f"unicode_normalization_difference:{field}"] += 1
            if any(unicodedata.category(ch) == "Cf" for ch in value):
                add_reason(reasons, number, f"unicode_format_character:{field}")
                counts[f"unicode_format_character:{field}"] += 1
            if html.unescape(value) != value:
                add_reason(reasons, number, f"html_entity:{field}")
                counts[f"html_entity:{field}"] += 1
            if HTML_TAG.search(value):
                add_reason(reasons, number, f"html_tag:{field}")
                counts[f"html_tag:{field}"] += 1
            if re.search(r"(?:Ã.|Â.|â€™|â€œ|â€|ðŸ)", value):
                add_reason(reasons, number, f"suspected_mojibake:{field}")
                counts[f"suspected_mojibake:{field}"] += 1

        description = row["product_description"].strip()
        length = len(description)
        lengths.append(length)
        if length < 40:
            short_examples.append((number, length))
            add_reason(reasons, number, "short_description_under_40_chars_review")
        if description and norm(description) == norm(row["product_name"]):
            name_only.append(number)
            add_reason(reasons, number, "description_is_name_only_review")
        if BOILERPLATE.fullmatch(description):
            boilerplate_examples.append(number)
            add_reason(reasons, number, "boilerplate_description_review")
        if AI_TERMS.search(" ".join((row["product_name"], description))):
            ai_examples.append(number)
            add_reason(reasons, number, "ai_ml_keyword_mention_review_only")
        if GENERIC_TERMS.search(row["product_name"]):
            generic_examples.append(number)
            add_reason(reasons, number, "generic_service_addon_name_review")
        if FEE_NAME.search(row["product_name"]):
            fee_examples.append(number)
            add_reason(reasons, number, "fee_name_granularity_review")

    for group in exact.values():
        if len(group) > 1:
            for n in group:
                add_reason(reasons, n, "exact_full_row_duplicate_review_identity_unconfirmed")
                related[n].update(set(group) - {n})
    for group in names.values():
        if len(group) > 1:
            label_pairs = {(rows[n - 1]["taxonomy_category"], rows[n - 1]["taxonomy_sub_category"]) for n in group}
            reason = "normalized_name_vendor_repeat_identity_unconfirmed"
            if len(label_pairs) > 1:
                reason += ";normalized_name_vendor_label_conflict_manual_review"
            for n in group:
                add_reason(reasons, n, reason)
                related[n].update(set(group) - {n})
    for group in descriptions.values():
        if len(group) > 1:
            label_pairs = {(rows[n - 1]["taxonomy_category"], rows[n - 1]["taxonomy_sub_category"]) for n in group}
            for n in group:
                add_reason(reasons, n, "normalized_description_repeat_identity_unconfirmed")
                if len(label_pairs) > 1:
                    add_reason(reasons, n, "normalized_description_label_conflict_manual_review")
                related[n].update(set(group) - {n})

    category_counts = Counter(row["taxonomy_category"] for row in rows)
    subcategory_counts = Counter(row["taxonomy_sub_category"] for row in rows)
    # A subcategory associated with multiple source categories is an observed parent-child inconsistency cue.
    subcategory_parents = defaultdict(set)
    for category, subcategory in category_pairs:
        subcategory_parents[subcategory].add(category)
    inconsistencies = {sub: sorted(parents) for sub, parents in subcategory_parents.items() if len(parents) > 1}
    for row in rows:
        if row["taxonomy_sub_category"] in inconsistencies:
            add_reason(reasons, row["source_record_number"], "subcategory_has_multiple_source_category_parents_review")

    candidate_rows = []
    for row in rows:
        number = row["source_record_number"]
        if reasons[number]:
            candidate_rows.append({
                **row,
                "review_reasons": ";".join(sorted(reasons[number])),
                "related_source_record_numbers": ";".join(map(str, sorted(related[number]))),
            })

    vendor_ranked = vendors.most_common()
    normalized_vendor_ranked = normalized_vendors.most_common()
    def example_records(numbers):
        return [{"source_record_number": n, "product_name": rows[n - 1]["product_name"], "vendor_name": rows[n - 1]["vendor_name"], "taxonomy_category": rows[n - 1]["taxonomy_category"], "taxonomy_sub_category": rows[n - 1]["taxonomy_sub_category"], "description_excerpt": " ".join(rows[n - 1]["product_description"].split())[:220]} for n in numbers[:4]]

    def label_conflicts(groups):
        conflicts = []
        for key, group in groups.items():
            cats = {rows[n - 1]["taxonomy_category"] for n in group}
            subs = {rows[n - 1]["taxonomy_sub_category"] for n in group}
            if len(cats) > 1 or len(subs) > 1:
                conflicts.append({"key": str(key), "source_records": [{"source_record_number": n, "product_name": rows[n - 1]["product_name"], "vendor_name": rows[n - 1]["vendor_name"], "taxonomy_category": rows[n - 1]["taxonomy_category"], "taxonomy_sub_category": rows[n - 1]["taxonomy_sub_category"]} for n in group], "category_disagreement": len(cats) > 1, "subcategory_disagreement": len(subs) > 1})
        return conflicts

    name_conflicts = label_conflicts(names)
    description_conflicts = label_conflicts(descriptions)
    name_conflicts.sort(key=lambda group: (not any(s in group["key"].casefold() for s in ("talend open studio", "snowflake")), group["source_records"][0]["source_record_number"]))
    replacement_records = [row["source_record_number"] for row in rows if "�" in row["product_description"]]
    placeholder_records = [row["source_record_number"] for row in rows if norm(row["product_description"].strip()) == "need product description"]
    ai_inside = [n for n in ai_examples if rows[n - 1]["taxonomy_category"] == "AI & ML"]
    ai_outside = [n for n in ai_examples if rows[n - 1]["taxonomy_category"] != "AI & ML"]
    report = {
        "dataset": {"path": source_path, "sha256": source_sha256, "records": len(rows), "schema": list(FIELDS)},
        "integrity": {"strict_csv": True, "schema_and_width_validated": True, "logical_data_records": len(rows), "category_support_sum": sum(category_counts.values()), "subcategory_support_sum": sum(subcategory_counts.values())},
        "missingness_and_hygiene": {"issue_counts_by_field_and_type": dict(sorted(counts.items())), "rows_with_any_review_reason": sum(bool(value) for value in reasons.values()), "replacement_character_description_count": sum("�" in row["product_description"] for row in rows), "replacement_character_description_examples": example_records(replacement_records), "placeholder_description_count": len(placeholder_records), "placeholder_description_examples": example_records(placeholder_records), "html_tag_field_count": counts.get("html_tag:product_description", 0)},
        "description_character_length": {**percentiles(lengths), "percentile_method": "nearest-rank p90; stripped description characters", "short_under_40_count": len(short_examples), "short_examples": [{"source_record_number": n, "characters": size, "product_name": rows[n - 1]["product_name"], "description_excerpt": " ".join(rows[n - 1]["product_description"].split())[:160]} for n, size in short_examples[:8]], "name_only_count": len(name_only), "name_only_examples": name_only[:8], "boilerplate_count": len(boilerplate_examples), "boilerplate_examples": boilerplate_examples[:8]},
        "duplicates_and_identity_cues": {"exact_duplicate_definition": "all five parsed field values exactly equal; no trim, case folding, or normalization", "exact_duplicate_extra_rows": sum(len(g)-1 for g in exact.values() if len(g)>1), "trimmed_case_sensitive_name_vendor_repeat_groups": sum(1 for g in trimmed_names.values() if len(g)>1), "normalized_name_vendor_repeat_groups": sum(1 for g in names.values() if len(g)>1), "normalized_name_vendor_excess_records": sum(len(g)-1 for g in names.values() if len(g)>1), "normalized_name_vendor_pairwise_comparisons": sum(len(g)*(len(g)-1)//2 for g in names.values() if len(g)>1), "normalized_description_repeat_groups": sum(1 for g in descriptions.values() if len(g)>1), "identity_resolution": "Suspected repeats are review cues only; no identity confirmation, merge, or deletion is performed."},
        "taxonomy": {"category_count": len(category_counts), "observed_subcategory_count": len(subcategory_counts), "coverage_note": f"{len(subcategory_counts)} subcategories are observed in this local file; this is not a claim of full-taxonomy coverage.", "categories": dict(sorted(category_counts.items())), "subcategories": dict(sorted(subcategory_counts.items())), "parent_child_pairs": len(category_pairs), "subcategory_parent_consistency": "consistent" if not inconsistencies else "multiple category parents observed", "subcategories_with_multiple_category_parents": inconsistencies},
        "vendors": {"distinct_exact_vendor_strings": len(vendors), "distinct_normalized_vendor_names": len(normalized_vendors), "top_10": [{"vendor_name": name, "records": count, "share": round(count/len(rows), 4) if rows else 0} for name, count in vendor_ranked[:10]], "top_10_normalized": [{"normalized_vendor_name": name, "records": count, "share": round(count/len(rows), 4) if rows else 0} for name, count in normalized_vendor_ranked[:10]], "top_10_share": round(sum(c for _,c in vendor_ranked[:10])/len(rows), 4) if rows else 0},
        "label_disagreements": {"normalized_name_vendor_groups_with_category_disagreement": sum(item["category_disagreement"] for item in name_conflicts), "normalized_name_vendor_groups_with_subcategory_disagreement": sum(item["subcategory_disagreement"] for item in name_conflicts), "normalized_name_vendor_groups_with_any_label_disagreement": len(name_conflicts), "normalized_description_groups_with_category_disagreement": sum(item["category_disagreement"] for item in description_conflicts), "normalized_description_groups_with_subcategory_disagreement": sum(item["subcategory_disagreement"] for item in description_conflicts), "examples": name_conflicts[:5], "interpretation": "Different source labels are reported as disagreements for review, not errors; distinct records are retained."},
        "review_cues": {"generic_service_or_addon_name_count": len(generic_examples), "generic_name_examples": example_records(generic_examples), "fee_name_count": len(fee_examples), "fee_name_examples": example_records(fee_examples), "ai_ml_keyword_mention_count": len(ai_examples), "ai_ml_mention_examples": example_records(ai_examples), "ai_ml_keyword_mentions_by_source_taxonomy": {"AI & ML": {"count": len(ai_inside), "examples": example_records(ai_inside)}, "other_source_categories": {"count": len(ai_outside), "examples": example_records(ai_outside)}}, "ai_phrase_definition": AI_TERMS.pattern, "keyword_note": "Only the listed case-insensitive word-boundary phrases in product name and description are counted; taxonomy fields excluded. This differs from broader literal cue scans. Mentions are review cues, not labels; absence and source taxonomy do not establish non-AI status."},
        "limitations": ["This is an imported vendor/product catalog, not observed enterprise activity or a reviewed AI/non-AI dataset.", "Source taxonomy is preserved and is not mapped to the project's 14 AIToolBuzz targets.", "Heuristic flags are not eligibility or exclusion rules; no ai_label, ai_role, mapped category, or split field is produced.", "Potential source, writing-style, vendor, or taxonomy confounding is not tested or proven by this EDA.", "No optional AIToolBuzz description-style comparison was run."],
        "review_candidate_rows": len(candidate_rows),
    }
    return report, candidate_rows


def write_outputs(input_path=INPUT, output_dir=OUT):
    input_path = Path(input_path).resolve()
    output_dir = Path(output_dir).resolve()
    targets = [output_dir / name for name in ("report.json", "REPORT.md", "review_candidates.csv")]
    if input_path in (target.resolve() for target in targets):
        raise ValueError("refusing to overwrite the input CSV")
    if any(target.exists() and input_path.exists() and input_path.samefile(target) for target in targets):
        raise ValueError("refusing to overwrite the input CSV through a filesystem alias")
    if len({target.resolve() for target in targets}) != len(targets):
        raise ValueError("output paths collide")
    digest = hashlib.sha256(input_path.read_bytes()).hexdigest()
    if input_path == INPUT.resolve():
        expected = "afe7cdbcbf82d9b11f579eb6dce000815a04a301410636e2942036f072fc7aa1"
        if digest != expected:
            raise ValueError(f"input checksum mismatch: {digest}")
    rows = load_rows(input_path)
    source_label = str(INPUT.relative_to(ROOT)) if input_path == INPUT.resolve() else str(input_path)
    report, candidates = analyze(rows, source_label, digest)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "REPORT.md").write_text(render_markdown(report), encoding="utf-8")
    with (output_dir / "review_candidates.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["source_record_number", *FIELDS, "review_reasons", "related_source_record_numbers"])
        writer.writeheader()
        writer.writerows(candidates)
    return report


def render_markdown(report):
    ds = report["dataset"]
    tax = report["taxonomy"]
    lengths = report["description_character_length"]
    hygiene = report["missingness_and_hygiene"]
    duplicates = report["duplicates_and_identity_cues"]
    disagreements = report["label_disagreements"]
    vendors = report["vendors"]
    cues = report["review_cues"]
    issues = hygiene["issue_counts_by_field_and_type"]
    lines = [
        "# Enterprise products: first-pass EDA", "",
        f"**Analyzed input:** `{ds['path']}` · {ds['records']} logical records · SHA-256 `{ds['sha256']}`. The source file is preserved byte-for-byte.", "",
        "## Dataset and taxonomy", "",
        f"This is an imported product/vendor catalog, not enterprise activity and not a reviewed AI/non-AI dataset. Source taxonomy remains unchanged; it is not mapped to the project's 14 AIToolBuzz targets. The local file contains {tax['category_count']} categories and {tax['observed_subcategory_count']} observed subcategories; this is not a claim of full-taxonomy coverage. Parent-child consistency: **{tax['subcategory_parent_consistency']}** ({len(tax['subcategories_with_multiple_category_parents'])} subcategories assigned to multiple source categories).", "",
        "| Source category | Records | Share |", "|---|---:|---:|",
    ]
    for category, count in sorted(tax["categories"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {category} | {count} | {count / ds['records']:.1%} |")
    lines += ["", f"Description length (trimmed characters): min {lengths['min']}, median {lengths['median']}, nearest-rank p90 {lengths['p90']}, max {lengths['max']}. {lengths['short_under_40_count']} are under 40 characters, {lengths['name_only_count']} are name-only, and {lengths['boilerplate_count']} match the narrow placeholder/boilerplate definition. These are review thresholds, not eligibility cuts.", "", "## Hygiene and repeat cues", ""]
    lines.append("Hygiene issue counts (overlapping review cues; not all distinct rows): " + "; ".join(f"`{key}` {value}" for key, value in sorted(issues.items())) + ".")
    lines.append(f"Notable findings: {hygiene['replacement_character_description_count']} descriptions contain U+FFFD replacement characters; {hygiene['placeholder_description_count']} equal `NEED PRODUCT DESCRIPTION`; {hygiene['html_tag_field_count']} product-description HTML tag matches. Replacement and placeholder examples: " + "; ".join([*(f"record {x['source_record_number']} {x['product_name']} (replacement character)" for x in hygiene['replacement_character_description_examples'][:3]), *(f"record {x['source_record_number']} {x['product_name']} (placeholder: {x['description_excerpt']})" for x in hygiene['placeholder_description_examples'][:3])]) + ".")
    lines += ["", f"Exact full-row duplicates: {duplicates['exact_duplicate_extra_rows']} extra rows (all five parsed fields must match exactly; no trimming/case-folding). Name/vendor repeat units: {duplicates['trimmed_case_sensitive_name_vendor_repeat_groups']} case-sensitive trimmed groups; {duplicates['normalized_name_vendor_repeat_groups']} normalized groups; {duplicates['normalized_name_vendor_excess_records']} excess records; {duplicates['normalized_name_vendor_pairwise_comparisons']} pairwise comparisons. There are {duplicates['normalized_description_repeat_groups']} normalized-description repeat groups. These counts are different units; repeated identity is unconfirmed.", "", f"Normalized name/vendor groups with category disagreement: {disagreements['normalized_name_vendor_groups_with_category_disagreement']}; with subcategory disagreement: {disagreements['normalized_name_vendor_groups_with_subcategory_disagreement']}; with either: {disagreements['normalized_name_vendor_groups_with_any_label_disagreement']}. Differences are preserved review observations, not errors or relabeling.", ""]
    for group in disagreements["examples"][:5]:
        entries = "; ".join(f"{item['source_record_number']} {item['product_name']}: {item['taxonomy_category']} / {item['taxonomy_sub_category']}" for item in group["source_records"])
        lines.append(f"- Repeat-key example: {entries}.")
    top = vendors["top_10_normalized"][:5]
    lines += ["", "Vendor concentration (normalized vendor keys): " + "; ".join(f"{item['normalized_vendor_name']} {item['records']} ({item['share']:.1%})" for item in top) + f". Top four share: {sum(item['share'] for item in vendors['top_10_normalized'][:4]):.1%}.", "", "## Focused review examples", ""]
    for label, examples in (("Placeholder", hygiene["placeholder_description_examples"]), ("Replacement character", hygiene["replacement_character_description_examples"]), ("Generic service/add-on", cues["generic_name_examples"]), ("Fee product granularity", cues["fee_name_examples"]), ("AI/ML cue within source AI & ML category", cues["ai_ml_keyword_mentions_by_source_taxonomy"]["AI & ML"]["examples"]), ("AI/ML cue outside source AI & ML category", cues["ai_ml_keyword_mentions_by_source_taxonomy"]["other_source_categories"]["examples"])):
        for item in examples[:2]:
            lines.append(f"- {label}, record {item['source_record_number']}: **{item['product_name']}** — {item['vendor_name']}; {item['taxonomy_category']} / {item['taxonomy_sub_category']}. “{item['description_excerpt']}”")
    ai_split = cues["ai_ml_keyword_mentions_by_source_taxonomy"]
    lines += ["", f"AI/ML phrase cue count: {cues['ai_ml_keyword_mention_count']} records total: {ai_split['AI & ML']['count']} within source category AI & ML and {ai_split['other_source_categories']['count']} outside it. Search covers product name and description only, using these case-insensitive word-boundary phrases: `{cues['ai_phrase_definition']}`. Broader literal scans can produce different counts; cues and source categories are not labels. Neither absence nor source category establishes AI status.", "", "## Safe next steps and limitations", "", "- Proposed safe normalization: trim outer whitespace and standardize line endings in a separate derived text field, preserving untouched raw values and source references. These recommendations are not applied by this EDA.", "- Manual review: do not automatically repair placeholder or replacement-character text, resolve product identity, or change labels; retain the evidence for adjudication.", "- Manually adjudicate repeat groups/label disagreements; similar identity clues do not authorize merge or deletion. Multi-category labels may be intentional.", "- Inspect short descriptions, generic service/add-on names, and fee-like granularity examples; these flags do not determine eligibility.", "- Reuse permission is unresolved per `SOURCE.md`; resolve it before training or redistribution.", "- Optional raw AIToolBuzz writing-style comparison was not run. This EDA does not test or prove source/style confounding.", "", f"`review_candidates.csv` contains {report['review_candidate_rows']} review-only rows with original values, explicit reasons, and logical CSV-record references (not physical line numbers). No labels, automatic exclusions, or identity merges are produced.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    try:
        result = write_outputs()
    except (OSError, UnicodeError, csv.Error, ValueError) as error:
        print(f"EDA failed: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Wrote {result['review_candidate_rows']} review candidates from {result['dataset']['records']} records to {OUT}")
