"""Optional training-only homepage anchors and measured truncation."""
import json
import csv
import hashlib
from pathlib import Path
from urllib.parse import urlsplit
from collections import Counter

from .data import ROOT, sha256, load_data, normalized


def host(url):
    return (urlsplit(url).hostname or '').lower().rstrip('.').removeprefix('www.')


def require_same_source(previous, current):
    if previous != current:
        raise ValueError('Training homepage source or review provenance changed')


def records(path):
    with path.open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def validate_supplement(train, path):
    """Fail closed on isolation, evidence, review and effective-label disagreement."""
    splits, _ = load_data()
    by_id = {r['tool_id']: r for r in train}
    held = splits['validation'] + splits['test']
    excluded = set(json.loads((ROOT / 'backend/config/known_tool_registry_exclusions.json').read_text())['excluded_tool_ids'])
    forbidden_ids = {r['tool_id'] for r in held} | excluded
    forbidden_groups = {r['group_id'] for r in held}
    with (ROOT / 'data/aitoolbuzz-com-16k-ai-tools-database/ai_tools_cleaned.csv').open(encoding='utf-8-sig', newline='') as stream:
        forbidden_hosts = {host(r['Website']) for r in csv.DictReader(stream) if r['tool_id'] in forbidden_ids}
    reviews_path = path.with_name('reviews.jsonl')
    manifest_path = path.with_name('manifest.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    for name in ('pages.jsonl', 'reviews.jsonl'):
        if manifest['output_hashes'][name] != sha256(path.with_name(name)):
            raise ValueError('Supplement output hash changed')
    captures_path = ROOT / manifest['capture_source']
    if sha256(captures_path) != manifest['capture_sha256']:
        raise ValueError('Immutable capture source changed')
    captures = records(captures_path)
    review_rows = records(reviews_path)
    reviews = {r['tool_id']: r for r in review_rows}
    if len(reviews) != len(review_rows):
        raise ValueError('Duplicate review identities')
    existing = records(ROOT / 'data/category_classification/transfer_v1/pages.jsonl')
    held_pages = [p for p in existing if p['catalog_split'] != 'train']
    forbidden_hosts.update(p['host'] for p in held_pages)
    held_text = {normalized(' '.join(p[k] for k in ('title', 'meta_description', 'headings', 'body') if p[k])) for p in held_pages}
    seen = {k: set() for k in ('host', 'url', 'group', 'text')}
    for page in records(path):
        ids = page['tool_ids']
        if page['catalog_split'] != 'train' or not ids or set(ids) - by_id.keys() or set(ids) & forbidden_ids:
            raise ValueError('Supplement references held-out/unknown IDs')
        groups = {by_id[i]['group_id'] for i in ids}
        if groups & forbidden_groups:
            raise ValueError('Supplement references held-out groups')
        if {by_id[i]['category'] for i in ids} != {page['category']}:
            raise ValueError('Supplement category disagrees with effective labels')
        if {r['category'] for r in train if r['group_id'] in groups} != {page['category']}:
            raise ValueError('Conflicting effective labels within homepage group')
        text = ' '.join(page[k] for k in ('title', 'meta_description', 'headings', 'body') if page[k])
        hosts = {host(page['requested_url']), host(page['final_url']), page['host']}
        if '' in hosts or hosts & forbidden_hosts or normalized(text) in held_text:
            raise ValueError('Supplement overlaps held-out hosts/text')
        for key, values in [('host', hosts), ('url', {page['final_url'].rstrip('/')}), ('group', groups), ('text', {normalized(text)})]:
            if seen[key] & values:
                raise ValueError('Duplicate supplement ' + key)
            seen[key].update(values)
        for tid in ids:
            review = reviews[tid]
            if (review['status'] != 'approved' or not review['supporting_excerpt'] or
                not all(review.get(k) for k in ('reviewer', 'reviewed_at', 'labeling_rule_version')) or
                not review['excerpt_visible_at_128'] or review['proposed_category'] != page['category'] or
                review['training_text'] != text or review['group_id'] != by_id[tid]['group_id']):
                raise ValueError('Missing approval/evidence or inconsistent review')
            capture = captures[review['capture_index']]
            digest = hashlib.sha256(json.dumps(capture, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if digest != review['capture_sha256'] or capture['tool_id'] != tid:
                raise ValueError('Capture reference mismatch')
            if any(page[k] != capture[k] for k in ('requested_url', 'final_url')):
                raise ValueError('Page URLs differ from immutable capture')
            expected = dict(title=capture['title'], meta_description=capture['meta_description'], headings=' | '.join(capture['headings']), body=capture['body'])
            if any(page[k] != v for k, v in expected.items()) or review['supporting_excerpt'] not in text:
                raise ValueError('Page/evidence differs from immutable capture')
    return {'reviews_sha256': sha256(reviews_path), 'manifest_sha256': sha256(manifest_path), 'capture_sha256': sha256(captures_path)}


def training_homepages(train, path=None):
    custom = path is not None
    path = path or ROOT / 'data/category_classification/transfer_v1/pages.jsonl'
    path = Path(path)
    provenance = validate_supplement(train, path) if custom else {}
    by_id = {r['tool_id']: r for r in train}
    result, excluded = [], Counter()
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            page = json.loads(line)
            if page['catalog_split'] != 'train':
                continue
            ids = page['tool_ids']
            if not ids or not set(ids) <= set(by_id):
                raise ValueError('Training homepage references a held-out/unknown tool')
            categories = {by_id[i]['category'] for i in ids}
            if len(categories) != 1:
                excluded['ambiguous_catalog_labels'] += 1
                continue
            text = ' '.join(page[k] for k in ('title', 'meta_description', 'headings', 'body') if page[k])
            if not text.strip():
                excluded['empty_text'] += 1
                continue
            groups = sorted({by_id[i]['group_id'] for i in ids})
            result.append({'tool_id': ids[0], 'tool_ids': list(ids), 'category': next(iter(categories)),
                           'group_id': groups[0], 'excluded_groups': groups, 'text_source': 'homepage',
                           'example_id': 'homepage:' + page['host'], 'description_text': text})
    return result, {**provenance, 'source_sha256': sha256(path), 'eligible': len(result), 'excluded': dict(excluded),
                    'text_preparation': 'title-meta-headings-body-space-join-v1', 'partition': 'train'}


def truncation_statistics(tokenizer, rows, batch_size=4):
    import numpy as np
    lengths = []
    for start in range(0, len(rows), batch_size):
        tokens = tokenizer([r['description_text'] for r in rows[start:start + batch_size]], truncation=False, padding=False)
        lengths.extend(len(ids) for ids in tokens['input_ids'])
    return {'examples': len(rows), 'median_tokens': float(np.median(lengths)) if lengths else 0.,
            'p95_tokens': float(np.percentile(lengths, 95)) if lengths else 0.,
            'fraction_over_128': sum(n > 128 for n in lengths) / max(1, len(lengths)),
            'fraction_over_256': sum(n > 256 for n in lengths) / max(1, len(lengths)),
            'tokens': lengths,
            'interpretation': 'Token truncation is measured; functional information beyond the cutoff is not automatically verified.'}
