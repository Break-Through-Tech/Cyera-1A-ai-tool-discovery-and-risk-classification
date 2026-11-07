"""Export a new training-only index paired with the exact local model contents."""
import argparse
import csv
import json
from pathlib import Path

from finetuning.data import ROOT, CUTOFF, MODEL, load_data, sha256, write_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True, help='Saved model run')
    p.add_argument('--output', type=Path, help='New index directory; default RUN/index')
    p.add_argument('--batch-size', type=int, default=4, help='Encoding batch size; reduce to 1 for memory')
    p.add_argument('--verify-only', action='store_true', help='Verify an existing export and local inference without rebuilding')
    args = p.parse_args()
    if args.batch_size < 1:
        p.error('batch-size must be positive')
    import numpy as np
    import torch
    torch.set_num_threads(2)
    from finetuning.model import cached_encode, load_model, run_metadata
    manifest = run_metadata(args.run)
    splits, hashes = load_data()
    if hashes != manifest['dataset_hashes']:
        raise ValueError('Dataset changed since training')
    excluded = set(json.loads((ROOT / 'backend/config/known_tool_registry_exclusions.json').read_text())['excluded_tool_ids'])
    excluded.update(r['tool_id'] for split in ('validation', 'test') for r in splits[split])
    train = splits['train']
    if excluded & {r['tool_id'] for r in train}:
        raise ValueError('Held-out tool in training index')
    output = args.output or args.run / 'index'
    overrides = manifest['labels'].get('overrides', {})
    train = [dict(r, category=overrides.get(r['tool_id'], r['category'])) for r in train]
    if args.verify_only:
        verify_export(output, args.run / 'model', train)
        print(f'Verified {output}')
        return
    if output.exists():
        raise SystemExit(f'{output} already exists; use --verify-only or select a new output')
    with (ROOT / 'data/aitoolbuzz-com-16k-ai-tools-database/ai_tools_cleaned.csv').open(encoding='utf-8', newline='') as stream:
        names = {r['tool_id']: r['Name'] for r in csv.DictReader(stream)}
    model = load_model(args.run / 'model', manifest['settings']['max_length'])
    vectors = cached_encode(model, [r['description_text'] for r in train], args.batch_size)
    output.mkdir(parents=True, exist_ok=False)
    np.save(output / 'embeddings.npy', vectors)
    with (output / 'tools.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(['tool_id', 'name', 'category'])
        writer.writerows((r['tool_id'], names[r['tool_id']], overrides.get(r['tool_id'], r['category'])) for r in train)
    write_json(output / 'manifest.json', {
        'index_id': str(output), 'rows': len(train), 'dataset_hashes': hashes,
        'labels': manifest['labels'], 'excluded_held_out_tool_ids': sorted(excluded),
        'tools_sha256': sha256(output / 'tools.csv'), 'embeddings_sha256': sha256(output / 'embeddings.npy'),
        'classification': {'k': 15, 'cutoff': CUTOFF},
        'model': {'backend': 'sentence_transformers_local', 'repo': MODEL,
                  'revision': manifest['model_fingerprint'], 'fingerprint': manifest['model_fingerprint'],
                  'pooling': 'cls', 'normalized': True, 'dim': 384,
                  'max_length': manifest['settings']['max_length']}})
    del model
    verify_export(output, args.run / 'model', train)
    print(output)


def verify_export(output, model_directory, train):
    """Check the persisted tool order and actual backend inference adapter."""
    import sys
    import numpy as np
    sys.path.insert(0, str(ROOT / 'backend'))
    from app.category.embedder import LocalSentenceTransformerEmbedder
    from app.category.neighbors import load_neighbor_index
    index = load_neighbor_index(output)
    if [(tool.tool_id, tool.category) for tool in index.tools] != [(row['tool_id'], row['category']) for row in train]:
        raise ValueError('Persisted index tools/categories differ from frozen training order')
    embed = LocalSentenceTransformerEmbedder(model_directory, index.model, batch_size=1)
    actual = embed([row['description_text'] for row in train[:2]])
    np.testing.assert_allclose(actual, index.embeddings[:2], atol=1e-5, rtol=1e-5)


if __name__ == '__main__':
    main()
