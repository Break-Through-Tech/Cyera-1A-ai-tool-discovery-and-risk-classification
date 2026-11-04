"""Export training-only label disagreements for human review; never change labels."""
import argparse
import csv
import json
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from finetuning.data import DATA, load_data, normalized, write_json, sha256


def review_pairs(rows, vectors, limit=200, chunk_size=16, additional_pairs=None):
    import numpy as np
    if len(rows) != len(vectors) or chunk_size < 1 or limit < 1:
        raise ValueError('Invalid review rows, vectors or bounds')
    pairs, confusions = {}, Counter()
    for start in range(0, len(rows), chunk_size):
        similarity = vectors[start:start + chunk_size] @ vectors.T
        nearest = np.argsort(-similarity, axis=1, kind='stable')[:, :min(16, len(rows))]
        for offset, neighbors in enumerate(nearest):
            left = start + offset
            for right in neighbors:
                right = int(right)
                if left == right or rows[left]['category'] == rows[right]['category']:
                    continue
                key = tuple(sorted((left, right)))
                category_pair = tuple(sorted((rows[left]['category'], rows[right]['category'])))
                confusions[category_pair] += 1
                pairs[key] = (float(similarity[offset, right]), category_pair)
    for left, right in additional_pairs or []:
        if not (0 <= left < len(rows) and 0 <= right < len(rows)):
            raise ValueError('Additional review pairs must reference training rows')
        if left == right or rows[left]['category'] == rows[right]['category']:
            continue
        key = tuple(sorted((left, right)))
        if key not in pairs:
            categories = tuple(sorted((rows[left]['category'], rows[right]['category'])))
            confusions[categories] += 1
            pairs[key] = (float(vectors[left] @ vectors[right]), categories)
    candidates = []
    texts = [normalized(r['description_text']) for r in rows]
    for (left, right), (similarity, categories) in pairs.items():
        a, b = rows[left], rows[right]
        matcher = SequenceMatcher(None, texts[left], texts[right])
        text_similarity = matcher.ratio() if matcher.quick_ratio() >= .85 else 0
        candidates.append({'left': a, 'right': b, 'similarity': similarity, 'normalized_text_similarity': text_similarity,
                           'confusion_frequency': confusions[categories], 'same_group': a['group_id'] == b['group_id'],
                           'review': {'decision': None, 'approved_category': None, 'reviewer': None,
                                      'version': None, 'provenance': None}})
    return sorted(candidates, key=lambda x: (-(x['normalized_text_similarity'] >= .92),
                  -x['confusion_frequency'], -x['similarity'], x['left']['tool_id'], x['right']['tool_id']))[:limit]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True, help='New review directory')
    p.add_argument('--limit', type=int, default=200, help='Maximum review pairs')
    p.add_argument('--chunk-size', type=int, default=16, help='Query chunk size; never allocate all pairwise similarities')
    p.add_argument('--max-length', type=int, default=128, help='Original BGE truncation limit')
    args = p.parse_args()
    if args.limit < 1 or args.chunk_size < 1 or args.max_length < 1:
        p.error('limit, chunk-size and max-length must be positive')
    import torch
    from threadpoolctl import threadpool_limits
    from finetuning.model import cached_encode, encoder_fingerprint, load_model
    torch.set_num_threads(2)
    threadpool_limits(limits=2)
    splits, hashes = load_data()
    rows = splits['train']
    args.output.mkdir(parents=True, exist_ok=False)
    model = load_model(max_length=args.max_length)
    checkpoint = encoder_fingerprint(model)
    vectors = cached_encode(model, [r['description_text'] for r in rows], checkpoint=checkpoint)
    near_path = DATA / 'near_description_review.csv'
    frozen = json.loads((DATA / 'manifest.json').read_text(encoding='utf-8'))
    if sha256(near_path) != frozen['near_review_sha256']:
        raise ValueError('Frozen near-description review changed')
    indices = {r['tool_id']: i for i, r in enumerate(rows)}
    with near_path.open(encoding='utf-8', newline='') as stream:
        known_pairs = [(indices[r['left_tool_id']], indices[r['right_tool_id']]) for r in csv.DictReader(stream)
                       if r['left_tool_id'] in indices and r['right_tool_id'] in indices]
    pairs = review_pairs(rows, vectors, args.limit, args.chunk_size, known_pairs)
    with (args.output / 'review_queue.jsonl').open('w', encoding='utf-8') as stream:
        for pair in pairs:
            stream.write(json.dumps(pair, ensure_ascii=False) + '\n')
    write_json(args.output / 'manifest.json', {'training_only': True, 'dataset_hashes': hashes,
               'checkpoint_fingerprint': checkpoint, 'max_length': args.max_length, 'pairs': len(pairs),
               'frozen_near_review_sha256': sha256(near_path), 'training_near_review_pairs_considered': len(known_pairs),
               'policy': 'Human queue only. No automatic corrections. Approved versioned training overrides required.'})
    print(f'Wrote {len(pairs)} training-only review pairs to {args.output}')


if __name__ == '__main__':
    main()
