"""Isolate the vote-label and encoder effects of a reviewed-label run."""

import argparse
import json
from pathlib import Path

from finetuning.data import load_data, write_json
from finetuning.evaluation import paired_changes, validation_sets
from finetuning.model import load_model
from finetuning.validation import evaluate_model


def read_votes(directory, view):
    with (directory / f'{view}.jsonl').open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream]


def compare_votes(before, after, overrides):
    result = paired_changes(before, after)
    result['examples_with_reviewed_neighbors'] = sum(
        any(n['tool_id'] in overrides for n in row['neighbors']) for row in before
    )
    result['changed_predictions'] = [
        {
            'example_id': old['example_id'], 'expected': old['expected'],
            'before': old['predicted'], 'after': new['predicted'],
            'reviewed_neighbors_before': [
                n for n in old['neighbors'] if n['tool_id'] in overrides
            ],
            'reviewed_neighbors_after': [
                n for n in new['neighbors'] if n['tool_id'] in overrides
            ],
        }
        for old, new in zip(before, after) if old['predicted'] != new['predicted']
    ]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluation', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()

    import torch
    from threadpoolctl import threadpool_limits

    torch.set_num_threads(2)
    threadpool_limits(limits=2)
    evaluation = json.loads(args.evaluation.read_text(encoding='utf-8'))
    overrides = evaluation['labels'].get('overrides', {})
    if evaluation['development_only'] or not overrides:
        raise ValueError('A full validation evaluation with reviewed labels is required')
    splits, hashes = load_data()
    sets, homepage_hash = validation_sets(splits)
    row_ids = {view: [r.get('tool_id') or r['host'] for r in rows]
               for view, rows in sets.items()}
    if (hashes != evaluation['dataset_hashes'] or homepage_hash != evaluation['homepage_sha256']
            or row_ids != evaluation['validation_examples']):
        raise ValueError('Frozen validation inputs differ from the reviewed evaluation')
    args.output.mkdir(parents=True, exist_ok=False)
    model = load_model(max_length=evaluation['preprocessing']['max_length'])
    original_scores, original_votes, seconds = evaluate_model(
        model, splits['train'], sets, args.output
    )
    candidates = evaluation['candidates']
    comparisons = {}
    for view in sets:
        corrected = read_votes(args.evaluation.parent / 'original_same_length', view)
        trained = read_votes(args.evaluation.parent / 'finetuned', view)
        for original, reviewed in zip(original_votes[view], corrected):
            expected_neighbors = [
                dict(n, category=overrides.get(n['tool_id'], n['category']))
                for n in original['neighbors']
            ]
            if expected_neighbors != reviewed['neighbors']:
                raise ValueError('Label-only comparison changed neighbor order or similarities')
        comparisons[view] = {
            'label_effect': compare_votes(original_votes[view], corrected, overrides),
            'encoder_effect': compare_votes(corrected, trained, overrides),
        }
    run = Path(evaluation['run'])
    with (run / 'triplets.jsonl').open(encoding='utf-8') as stream:
        triplets = [json.loads(line) for line in stream]
    with (run / 'training_log.jsonl').open(encoding='utf-8') as stream:
        used = {i for line in stream for i in json.loads(line)['triplet_indices']}
    exposure = {tool_id: {role: sum(triplets[i][role]['tool_id'] == tool_id for i in used)
                         for role in ('anchor', 'positive', 'negative')}
                for tool_id in overrides}
    write_json(args.output / 'comparison.json', {
        'source_evaluation': str(args.evaluation),
        'preprocessing': evaluation['preprocessing'],
        'dataset_hashes': hashes,
        'homepage_sha256': homepage_hash,
        'original_rescore_seconds': seconds,
        'candidates': {
            'A_original_labels': original_scores,
            'B_corrected_labels': candidates['original_same_length'],
            'C_corrected_finetuned': candidates['finetuned'],
            'deployed': candidates['deployed_original_preprocessing'],
        },
        'reviewed_tool_triplet_counts': exposure,
        'comparisons': comparisons,
    })
    print(args.output / 'comparison.json')


if __name__ == '__main__':
    main()
