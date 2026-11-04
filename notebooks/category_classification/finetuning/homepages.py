"""Optional training-only homepage anchors and measured truncation."""
import json
from collections import Counter

from .data import ROOT, sha256


def training_homepages(train, path=None):
    path = path or ROOT / 'data/category_classification/transfer_v1/pages.jsonl'
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
    return result, {'source_sha256': sha256(path), 'eligible': len(result), 'excluded': dict(excluded),
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
