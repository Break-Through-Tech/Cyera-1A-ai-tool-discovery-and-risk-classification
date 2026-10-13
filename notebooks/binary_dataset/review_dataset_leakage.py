"""Review duplicates, related tools, and label conflicts before dataset splitting."""
import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

from freeze_enterprise_labels import CUTOFF, ROOT

INPUT = ROOT / "data/binary_ai_dataset/v2"
OUT = ROOT / "data/binary_ai_dataset/v3"
NORMALIZATION_POLICY = "matching-v1: Unicode casefold; trim and collapse whitespace; punctuation retained"
GROUPING_POLICY = "leakage-groups-v1: exact/normalized text, near-text candidates, enterprise product groups, and every same-normalized-name candidate set connect groups; same-name identity/conflict links require a shared non-generic vendor; domains are ambiguous evidence only"
NEAR_POLICY = "near-text-v1: token Jaccard >= 0.82; >= 8 distinct tokens, >= 60 chars, and >= 6 shared tokens; rare-token inverted index capped at 100 postings per token"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def stable_id(prefix, values):
    payload = "\0".join(sorted(values)).encode("utf-8")
    return f"{prefix}:{sha(payload)}"


def normalized(text):
    return " ".join(text.casefold().split())


def tokens(text):
    return set(re.findall(r"[\w]+", text.casefold(), flags=re.UNICODE))


def _name(value):
    return " ".join(re.findall(r"[a-z0-9]+", (value or "").casefold()))


def _domain(value):
    if not isinstance(value, str) or not value.strip():
        return ""
    value = value.strip()
    parsed = urlparse(value if "://" in value else "//" + value)
    host = (parsed.hostname or "").casefold().strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


class UnionFind:
    def __init__(self, values):
        self.parent = {x: x for x in values}

    def find(self, value):
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left, right):
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[max(a, b)] = min(a, b)


def near_text_pairs(examples):
    """Deterministic sparse candidate generation; no all-pairs scan."""
    wordsets = {x["example_id"]: tokens(x["description_text"]) for x in examples}
    eligible = {x["example_id"]: wordsets[x["example_id"]] for x in examples
                if len(wordsets[x["example_id"]]) >= 8 and len(x["description_text"]) >= 60}
    postings = defaultdict(list)
    for key in sorted(eligible):
        for word in eligible[key]:
            postings[word].append(key)
    candidates = set()
    for key in sorted(eligible):
        words = eligible[key]
        selected = sorted((w for w in words if len(postings[w]) <= 100), key=lambda w: (len(postings[w]), w))[:8]
        for word in selected:
            candidates.update((key, other) for other in postings[word] if other > key)
    pairs = []
    for left, right in sorted(candidates):
        a, b = eligible[left], eligible[right]
        shared = len(a & b)
        score = shared / len(a | b)
        if shared >= 6 and score >= 0.82:
            pairs.append((left, right, round(score, 6)))
    return pairs


def analyze(examples):
    if not isinstance(examples, list):
        raise ValueError("v2 examples must be a list")
    examples_by_id = {}
    for item in examples:
        if not isinstance(item, dict) or not isinstance(item.get("example_id"), str) or item["example_id"] in examples_by_id:
            raise ValueError("malformed or duplicate example ID")
        text = item.get("description_text")
        if not isinstance(text, str) or not text or sha(text.encode("utf-8")) != item.get("description_sha256"):
            raise ValueError(f"invalid example description/hash: {item.get('example_id')}")
        if item.get("label") not in {"ai", "non_ai"} or item.get("source") not in {"enterprise", "aitoolbuzz"}:
            raise ValueError(f"invalid example label/source: {item['example_id']}")
        examples_by_id[item["example_id"]] = item
    ids = sorted(examples_by_id)
    uf = UnionFind(ids)
    edges = []
    by_norm = defaultdict(list)
    for item in examples:
        by_norm[normalized(item["description_text"])].append(item["example_id"])
    duplicate_groups = []
    for norm, members in sorted(by_norm.items()):
        members = sorted(members)
        if len(members) > 1:
            duplicate_groups.append({"normalized_text_sha256": sha(norm.encode()), "example_ids": members,
                                     "exact_text_variants": len({examples_by_id[x]["description_text"] for x in members}),
                                     "merge_policy": "one candidate per casefold/trim/collapsed-whitespace text; exact source text and all members retained"})
            for other in members[1:]:
                uf.union(members[0], other)
                edges.append((members[0], other, "normalized_text_duplicate", {"normalized_text_sha256": sha(norm.encode())}))

    near_pairs = near_text_pairs(examples)
    near_reviews = []
    for left, right, score in near_pairs:
        uf.union(left, right)
        edges.append((left, right, "near_text_candidate", {"token_jaccard": score}))
        near_reviews.append({"left_example_id": left, "right_example_id": right, "token_jaccard": score,
                             "identity_status": "unconfirmed", "grouping_policy": "same leakage group; preserve distinct examples unless normalized text duplicate"})

    # Enterprise repeated product groups are high-confidence leakage links.
    products = defaultdict(list)
    for item in examples:
        if item["source"] == "enterprise":
            for row in item.get("metadata", {}).get("source_records", []):
                group = row.get("product_group_id")
                if group:
                    products[group].append(item["example_id"])
    for group, members in sorted(products.items()):
        members = sorted(set(members))
        for other in members[1:]:
            uf.union(members[0], other)
            edges.append((members[0], other, "enterprise_product_group", {"product_group_id": group}))

    # Same-name candidates share a leakage group; only a shared vendor supports identity edges.
    signals = defaultdict(lambda: {"names": set(), "vendors": set(), "domains": set()})
    for item in examples:
        meta = item.get("metadata", {})
        rows = meta.get("source_records", []) if item["source"] == "enterprise" else [meta]
        for row in rows:
            name = _name(row.get("product_name") or row.get("name"))
            vendor = _name(row.get("vendor_name"))
            domain = _domain(row.get("website") or row.get("link"))
            if name:
                signals[name]["names"].add(item["example_id"])
                if vendor:
                    signals[name]["vendors"].add((item["example_id"], vendor))
                if domain:
                    signals[name]["domains"].add((item["example_id"], domain))
    identity_reviews = []
    for name, signal in sorted(signals.items()):
        members = sorted(signal["names"])
        if len(members) < 2:
            continue
        vendor_map = defaultdict(set)
        domain_map = defaultdict(set)
        for eid, value in signal["vendors"]:
            vendor_map[value].add(eid)
        for eid, value in signal["domains"]:
            domain_map[value].add(eid)
        # Always connect the entire name candidate set for leakage control. This
        # candidate edge does not assert identity and cannot trigger quarantine.
        for other in members[1:]:
            uf.union(members[0], other)
            edges.append((members[0], other, "ambiguous_same_name_candidate", {"normalized_name": name}))
        shared_vendors = {vendor: sorted(owners) for vendor, owners in vendor_map.items()
                          if len(owners) > 1 and vendor not in {"", "unknown", "other"}}
        # Add strong edges only within each genuinely shared-vendor subset. Do not
        # combine evidence from different vendors/domains into a synthetic match.
        for vendor, owners in sorted(shared_vendors.items()):
            for left, right in zip(owners, owners[1:]):
                edges.append((left, right, "corroborated_same_name", {"normalized_name": name,
                              "shared_vendor": vendor}))
        identity_reviews.append({"normalized_name": name, "example_ids": members,
                                 "corroborating_evidence": {"shared_vendors": sorted(shared_vendors),
                                                             "shared_domains_ambiguous_only": sorted(k for k, v in domain_map.items() if len(v) > 1)},
                                 "identity_status": "candidate_same_tool" if shared_vendors else "ambiguous",
                                 "grouping_policy": "all same-name candidates connect leakage groups; only pairs sharing the same vendor support a same-tool/conflict edge; domains are ambiguous evidence only"})

    groups = defaultdict(list)
    for eid in ids:
        groups[uf.find(eid)].append(eid)
    group_ids = {root: stable_id("leakage-group", members) for root, members in groups.items()}
    conflicts = []
    for root, members in sorted(groups.items()):
        labels = {examples_by_id[e]["label"] for e in members}
        reasons = []
        if len(labels) > 1:
            member_edges = [(a, b, why, evidence) for a, b, why, evidence in edges if a in members and b in members]
            for a, b, why, evidence in member_edges:
                if examples_by_id[a]["label"] != examples_by_id[b]["label"] and why in {"normalized_text_duplicate", "enterprise_product_group", "corroborated_same_name"}:
                    reasons.append({"left_example_id": a, "right_example_id": b, "reason": "opposite_labels_high_confidence_" + why,
                                    "evidence": evidence})
        if reasons:
            conflicts.append({"leakage_group_id": group_ids[root], "example_ids": sorted(members),
                              "labels": sorted(labels), "evidence": reasons,
                              "disposition": "quarantine_entire_group; do not unify labels or alter judgments"})

    merged = []
    for dup in duplicate_groups:
        members = dup["example_ids"]
        if len(members) < 2:
            continue
        labels = {examples_by_id[e]["label"] for e in members}
        canonical = examples_by_id[members[0]]
        merged.append({"example_id": stable_id("merged-example", members), "source": "merged",
                       "source_record_ids": sorted({rid for e in members for rid in examples_by_id[e].get("source_record_ids", [])}),
                       "description_text": canonical["description_text"], "description_sha256": canonical["description_sha256"],
                       "matching_normalized_text": normalized(canonical["description_text"]),
                       "label": next(iter(labels)) if len(labels) == 1 else None,
                       "metadata": {"member_example_ids": members, "members": [{"example_id": e, "source": examples_by_id[e]["source"],
                           "label": examples_by_id[e]["label"], "source_record_ids": sorted(examples_by_id[e].get("source_record_ids", [])),
                           "metadata": examples_by_id[e].get("metadata", {})} for e in members]}})
    duplicate_members = {e for row in duplicate_groups for e in row["example_ids"]}
    merged.extend({**examples_by_id[e], "metadata": {**examples_by_id[e].get("metadata", {}), "member_example_ids": [e]}}
                  for e in ids if e not in duplicate_members)
    conflict_groups = {c["leakage_group_id"] for c in conflicts}
    eligible, quarantined = [], []
    for item in merged:
        # Group lookup uses source IDs for duplicate merges, retaining all relationships.
        member_ids = item["metadata"]["member_example_ids"]
        roots = {uf.find(e) for e in member_ids}
        group_id = group_ids[next(iter(roots))]
        item["leakage_group_id"] = group_id
        if group_id in conflict_groups:
            quarantined.append({**item, "quarantine_reason": "high_confidence_opposite_label_conflict_in_leakage_group"})
        else:
            eligible.append(item)
    quarantined_source_classes = Counter()
    for item in quarantined:
        for member_id in item["metadata"]["member_example_ids"]:
            member = examples_by_id[member_id]
            quarantined_source_classes[f"{member['source']}:{member['label']}"] += 1
    summary = {"source_cutoff": CUTOFF, "input_examples": len(examples), "normalized_duplicate_groups": len(duplicate_groups),
               "duplicate_examples_removed": len(examples) - len(merged), "merged_examples": len(merged),
               "eligible_examples": len(eligible), "quarantined_examples": len(quarantined),
               "quarantined_by_class": dict(sorted(Counter(x["label"] or "conflict" for x in quarantined).items())),
               "quarantined_source_class_memberships": dict(sorted(quarantined_source_classes.items())),
               "duplicate_merges_by_source": dict(sorted(Counter(examples_by_id[e]["source"] for d in duplicate_groups
                                                                    for e in d["example_ids"][1:]).items())),
               "leakage_groups": len(groups), "identity_review_candidates": len(identity_reviews),
               "near_text_candidate_pairs": len(near_reviews), "high_confidence_conflict_groups": len(conflicts),
               "feature_allowlist": ["description_text"], "normalization_policy_version": NORMALIZATION_POLICY,
               "grouping_policy_version": GROUPING_POLICY, "near_duplicate_policy_version": NEAR_POLICY,
               "partition_assignment": "not assigned in this phase"}
    return {"examples": eligible, "quarantined": quarantined, "duplicate_audit": duplicate_groups,
            "identity_review": identity_reviews + near_reviews, "conflicts": conflicts, "summary": summary}


def build():
    if OUT.exists() or OUT.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing output: {OUT}")
    manifest_path = INPUT / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get("source_cutoff") != CUTOFF:
        raise ValueError("v2 source cutoff mismatch")
    for name, expected in manifest.get("artifact_sha256", {}).items():
        if sha((INPUT / name).read_bytes()) != expected:
            raise ValueError(f"v2 artifact checksum mismatch: {name}")
    examples = json.loads((INPUT / "examples.json").read_bytes())
    result = analyze(examples)
    payloads = {"examples.json": result["examples"], "quarantined.json": result["quarantined"],
                "duplicate_audit.json": result["duplicate_audit"], "identity_review.json": result["identity_review"],
                "conflicts.json": result["conflicts"]}
    encoded = {name: (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode() for name, value in payloads.items()}
    summary = {**result["summary"], "input_sha256": {"v2_examples.json": sha((INPUT / "examples.json").read_bytes()),
                 "v2_manifest.json": sha(manifest_path.read_bytes())},
               "artifact_sha256": {name: sha(data) for name, data in encoded.items()}}
    encoded["manifest.json"] = (json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.mkdir()
    try:
        for name, data in encoded.items():
            with (OUT / name).open("xb") as handle:
                handle.write(data)
    except Exception:
        for child in OUT.iterdir():
            child.unlink()
        OUT.rmdir()
        raise
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build",))
    parser.parse_args()
    print(json.dumps(build(), indent=2))


if __name__ == "__main__":
    main()
