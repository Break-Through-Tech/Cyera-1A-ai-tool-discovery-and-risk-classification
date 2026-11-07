"""Bounded, resumable training-only homepage collection; no approval or training."""
import argparse
import csv
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
DATA = ROOT / 'data/category_classification'
SOURCE = ROOT / 'data/aitoolbuzz-com-16k-ai-tools-database/ai_tools_cleaned.csv'
EXCLUSIONS = ROOT / 'backend/config/known_tool_registry_exclusions.json'
PRIOR = ROOT / 'artifacts/category_finetuning/reviewed-labels-seed1-cpu/validation-full/original_same_length/homepages.jsonl'


def host(url):
    return (urlsplit(url).hostname or '').lower().rstrip('.').removeprefix('www.')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def records(path):
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def jsonl(path, values):
    path.write_text(''.join(json.dumps(v, ensure_ascii=False) + '\n' for v in values), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DATA / 'homepage_training_v2/pilot-30')
    parser.add_argument('--limit', type=int, default=30)
    parser.add_argument('--seed', type=int, default=20261106)
    parser.add_argument('--select-only', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.limit <= 30:
        parser.error('Pilot budget must be between 1 and 30')
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    split_paths = [DATA / 'v1' / f'{s}.csv' for s in ('train', 'validation', 'test')]
    train, validation, test = map(rows, split_paths)
    by_id = {r['tool_id']: r for r in train}
    held_ids = {r['tool_id'] for r in validation + test} | set(json.loads(EXCLUSIONS.read_text())['excluded_tool_ids'])
    held_groups = {r['group_id'] for r in validation + test}
    catalog = rows(SOURCE)
    hosts = defaultdict(list)
    for r in catalog:
        hosts[host(r['Website'])].append(r)
    forbidden = {h for h, rs in hosts.items() if any(r['tool_id'] in held_ids or r['tool_id'] not in by_id for r in rs)}
    existing = records(DATA / 'transfer_v1/pages.jsonl')
    used_hosts = {p['host'] for p in existing}
    raw_sources = [ROOT / 'notebooks/ai_cascade/pool/captures.jsonl', ROOT / 'notebooks/website_feasibility/captures/results.jsonl']
    for path in raw_sources:
        for capture in records(path):
            if capture.get('outcome') == 'extracted':
                used_hosts.add(host(capture.get('url') or capture.get('requested_url') or ''))
                used_hosts.add(host(capture.get('final_url') or ''))
    used_groups = {by_id[i]['group_id'] for p in existing for i in p['tool_ids'] if i in by_id}
    support = Counter(p['category'] for p in existing if p['catalog_split'] == 'train' and all(i in by_id for i in p['tool_ids']) and any(p[k].strip() for k in ('title', 'meta_description', 'headings', 'body')))
    confusion = Counter(r['expected'] for r in records(PRIOR) if not r['correct'])
    excluded = Counter()
    candidates = []
    for r in catalog:
        tid, h = r['tool_id'], host(r['Website'])
        if tid not in by_id:
            continue
        group = by_id[tid]['group_id']
        reason = ('held_out_host' if h in forbidden else 'already_captured_host' if h in used_hosts else 'already_captured_group' if group in used_groups else 'held_out_group' if group in held_groups else 'missing_host' if not h else None)
        if reason:
            excluded[reason] += 1
            continue
        candidates.append(dict(tool_id=tid, group_id=group, name=r['Name'], catalog_url=r['Website'], requested_url=f'https://{h}/', host=h, catalog_category=by_id[tid]['category'], identity_review_required=len(hosts[h]) > 1, shared_host_products=[v['Name'] for v in hosts[h]]))
    rng = random.Random(args.seed)
    candidates.sort(key=lambda r: r['tool_id'])
    rng.shuffle(candidates)
    selected, added = [], Counter()
    while candidates and len(selected) < args.limit:
        candidates.sort(key=lambda r: (support[r['catalog_category']] + added[r['catalog_category']], -confusion[r['catalog_category']]))
        r = candidates.pop(0)
        selected.append(r)
        added[r['catalog_category']] += 1
        candidates = [v for v in candidates if v['host'] != r['host'] and v['group_id'] != r['group_id']]
    if len(selected) != args.limit:
        raise ValueError('Insufficient eligible URLs')
    sources = split_paths + [SOURCE, EXCLUSIONS, DATA / 'transfer_v1/pages.jsonl'] + [p for p in raw_sources if p.exists()] + ([PRIOR] if PRIOR.exists() else [])
    source_hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    selection_path = out / 'selection.jsonl'
    if selection_path.exists() and records(selection_path) != selected and (out / 'captures.jsonl').exists():
        raise ValueError('Existing selection differs; use a new output directory')
    jsonl(selection_path, selected)
    if args.select_only:
        print(json.dumps({'selected': len(selected), 'output': str(out)}))
        return
    from app.enrichment.destinations import system_resolver
    from app.enrichment.fetch import fetch_homepage
    from app.enrichment.http import CurlHttpClient
    extractor_hashes = {str(p.relative_to(ROOT)): digest(p) for p in sorted((ROOT / 'backend/app/enrichment').glob('*.py'))}
    captures_path = out / 'captures.jsonl'
    captures = records(captures_path)
    selected_ids = {r['tool_id'] for r in selected}
    if any(c['tool_id'] not in selected_ids or c['extractor_version'] != extractor_hashes for c in captures):
        raise ValueError('Resume capture selection/extractor mismatch')
    completed = {c['tool_id'] for c in captures}
    http = CurlHttpClient()
    for r in selected:
        if r['tool_id'] in completed:
            continue
        capture = asdict(fetch_homepage(r['host'], http, system_resolver))
        metadata = capture.get('metadata') or {}
        record = {**r, **capture, 'meta_description': metadata.get('description') or metadata.get('og:description') or '', 'body': capture['main_text'], 'extractor_version': extractor_hashes}
        with captures_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
        captures.append(record)
        print(f"{len(captures)}/{len(selected)} {r['host']}: {capture['outcome']}", flush=True)
    held_pages = [p for p in existing if p['catalog_split'] != 'train']
    def text(p):
        headings = p.get('headings') or ''
        if isinstance(headings, (list, tuple)):
            headings = ' | '.join(headings)
        return ' '.join((p.get('title') or '', p.get('meta_description') or '', headings, p.get('body') or '')).strip()
    def normalized(p):
        return ' '.join(text(p).casefold().split())
    held_text = {normalized(p) for p in held_pages}
    seen_text, seen_final = set(), set()
    queue = []
    for c in captures:
        final_host = host(c.get('final_url') or '')
        reason = ('fetch_failed' if c['outcome'] != 'extracted' else 'empty_extraction' if not text(c) else 'held_out_final_host' if final_host in forbidden or final_host in {p['host'] for p in held_pages} else 'held_out_text_overlap' if normalized(c) in held_text else 'existing_final_host' if final_host in used_hosts else 'duplicate_capture' if normalized(c) in seen_text or final_host in seen_final else None)
        if not reason:
            seen_text.add(normalized(c))
            seen_final.add(final_host)
        queue.append({'tool_id': c['tool_id'], 'identity_status': 'pending', 'review_status': 'pending_review' if not reason else reason, 'proposed_category': c['catalog_category'], 'supporting_excerpt': None, 'rationale': None, 'reviewer': None, 'rule_version': 'primary-function-general-image-media-v1', 'evidence_within_128_tokens': None})
    jsonl(out / 'reviews.jsonl', queue)
    ready = sum(q['review_status'] == 'pending_review' for q in queue)
    summary = {'selected': len(selected), 'attempted': len(captures), 'captured': sum(c['outcome'] == 'extracted' for c in captures), 'ready_for_review': ready, 'approved': 0, 'outcomes': dict(Counter(c['outcome'] for c in captures)), 'review_queue_outcomes': dict(Counter(q['review_status'] for q in queue)), 'selection_exclusions': dict(excluded), 'existing_training_pages_by_category': dict(support), 'selected_by_category': dict(added), 'selection_seed': args.seed, 'selection_policy': 'lowest existing+selected page count, descending validation errors, seeded shuffle; unique host/group', 'workers': 1, 'source_hashes': source_hashes, 'extractor_version': extractor_hashes, 'output_hashes': {p.name: digest(p) for p in (selection_path, captures_path, out / 'reviews.jsonl')}, 'scope': 'Collection pilot only; pending review is not approval. No training/export.'}
    write(out / 'manifest.json', summary)
    (out / 'REPORT.md').write_text(f"# Homepage collection pilot\n\nSelected: {len(selected)}. Attempted: {len(captures)}. Captured: {summary['captured']}. Ready for review: {ready}. Approved: 0.\n\nCapture outcomes: {json.dumps(summary['outcomes'])}.\n\nReady for review means nonempty extraction without detected held-out or duplicate overlap; product identity, category, usability and 128-token evidence still require review. Exact text is retained in captures.jsonl. No training or approved export was run.\n", encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('attempted', 'captured', 'ready_for_review', 'outcomes')}, indent=2))


if __name__ == '__main__':
    main()
