"""Full KNN validation, persistent predictions and paired comparisons."""
import hashlib
import json
import time

from .data import ROOT, MODEL, REVISION, load_data, write_json, sha256
from .evaluation import make_index, score_examples, paired_changes, validation_sets
from .model import cached_encode, encoder_fingerprint, load_model, preserve_training_state, run_metadata, validate_vectors

PRIMARY_TARGET = 'validation_homepage_forced_accuracy'


def save_predictions(path, predictions):
    with path.open('w', encoding='utf-8') as stream:
        for row in predictions:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')


def evaluate_model(model, train, sets, output, batch_size=4, index=None):
    """Safe during training: restore every module's mode and the CPU RNG."""
    started = time.perf_counter()
    checkpoint = encoder_fingerprint(model)
    metrics, predictions = {}, {}
    with preserve_training_state(model):
        if index is None:
            vectors = cached_encode(model, [r['description_text'] for r in train], batch_size, checkpoint=checkpoint)
            index = make_index(vectors, train)
        for view, rows in sets.items():
            vectors = cached_encode(model, [r['description_text'] for r in rows], batch_size, checkpoint=checkpoint)
            metrics[view], predictions[view] = score_examples(index, vectors, rows)
            save_predictions(output / f'{view}.jsonl', predictions[view])
    return metrics, predictions, time.perf_counter() - started


def evaluate_run(run, output, batch_size=4, quick=0):
    import numpy as np
    import psutil
    import torch
    from threadpoolctl import threadpool_limits
    from app.category.embedder import FastembedEmbedder
    from app.category.neighbors import load_neighbor_index
    torch.set_num_threads(2)
    threadpool_limits(limits=2)
    manifest = run_metadata(run)
    splits, hashes = load_data()
    if hashes != manifest['dataset_hashes']:
        raise ValueError('Training dataset changed')
    sets, homepage_hash = validation_sets(splits, quick)
    overrides = manifest['labels'].get('overrides', {})
    train = [dict(r, category=overrides.get(r['tool_id'], r['category'])) for r in splits['train']]
    output.mkdir(parents=True, exist_ok=False)
    report = {'primary_target': PRIMARY_TARGET, 'development_only': bool(quick), 'run': str(run),
              'training_manifest': manifest, 'dataset_hashes': hashes, 'homepage_sha256': homepage_hash,
              'model_fingerprint': manifest['model_fingerprint'], 'original_model': {'repo': MODEL, 'revision': REVISION},
              'labels': manifest['labels'], 'preprocessing': {'max_length': manifest['settings']['max_length'], 'text_preparation': 'unmodified-v1'},
              'validation_examples': {v: [r.get('tool_id') or r['host'] for r in rows] for v, rows in sets.items()},
              'candidates': {}, 'evaluation_seconds': {}, 'paired_changes': {}, 'cutoff_selection': 'unchanged; k=15; no tuning',
              'uncertainty': '106 validation homepages are noisy; small changes are inconclusive. Fresh held-out tools needed.'}
    all_predictions = {}
    started = time.perf_counter()
    for name, path in (('original_same_length', None), ('finetuned', run / 'model')):
        print(f'Evaluating {name}: {len(train)} training tools; {len(sets["descriptions"])} descriptions / {len(sets["homepages"])} homepages', flush=True)
        directory = output / name
        directory.mkdir()
        model = load_model(path, manifest['settings']['max_length'])
        index = None
        exported = run / 'index'
        if name == 'finetuned' and (exported / 'manifest.json').exists():
            index_manifest = json.loads((exported / 'manifest.json').read_text(encoding='utf-8'))
            index = load_neighbor_index(exported)
            if (index.model.get('fingerprint') != manifest['model_fingerprint'] or index_manifest['dataset_hashes'] != hashes or
                [(t.tool_id, t.category) for t in index.tools] != [(r['tool_id'], r['category']) for r in train]):
                raise ValueError('Exported index differs from candidate/catalog')
        scores, predictions, seconds = evaluate_model(model, train, sets, directory, batch_size, index)
        report['candidates'][name], all_predictions[name], report['evaluation_seconds'][name] = scores, predictions, seconds
        write_json(directory / 'metrics.json', scores)
        del model, index
    print('Evaluating deployed baseline', flush=True)
    index_directory = ROOT / 'artifacts/category_neighbor_index/v1'
    index = load_neighbor_index(index_directory)
    deployed = FastembedEmbedder(index.model, ROOT / '.cache-training/onnx')
    directory = output / 'deployed_original_preprocessing'
    directory.mkdir()
    scores, predictions = {}, {}
    deployed_started = time.perf_counter()
    for view, rows in sets.items():
        texts = [r['description_text'] for r in rows]
        key = hashlib.sha256(json.dumps([index.model, sha256(index_directory / 'embeddings.npy'), texts], sort_keys=True).encode()).hexdigest()
        cache = ROOT / '.cache-training/deployed-validation' / f'{key}.npy'
        cache_metadata = cache.with_suffix('.json')
        if cache.exists():
            if cache_metadata.exists() and json.loads(cache_metadata.read_text(encoding='utf-8'))['sha256'] != sha256(cache):
                raise ValueError('Deployed validation cache content changed')
            vectors = np.load(cache, allow_pickle=False)
        else:
            vectors = np.concatenate([deployed(texts[i:i + batch_size]) for i in range(0, len(texts), batch_size)])
            cache.parent.mkdir(parents=True, exist_ok=True)
            np.save(cache, vectors)
        validate_vectors(vectors)
        if len(vectors) != len(rows):
            raise ValueError('Deployed validation cache row count changed')
        if not cache_metadata.exists():
            write_json(cache_metadata, {'sha256': sha256(cache), 'rows': len(rows), 'configuration_key': key})
        scores[view], predictions[view] = score_examples(index, vectors, rows)
        save_predictions(directory / f'{view}.jsonl', predictions[view])
    report['candidates']['deployed_original_preprocessing'] = scores
    report['evaluation_seconds']['deployed_original_preprocessing'] = time.perf_counter() - deployed_started
    report['deployed_model'] = dict(index.model)
    all_predictions['deployed_original_preprocessing'] = predictions
    write_json(directory / 'metrics.json', scores)
    for candidate in ('finetuned', 'deployed_original_preprocessing'):
        report['paired_changes'][candidate] = {view: paired_changes(all_predictions['original_same_length'][view], all_predictions[candidate][view]) for view in sets}
    report['accuracy_delta_from_same_length_original'] = {
        view: report['candidates']['finetuned'][view]['accuracy'] - report['candidates']['original_same_length'][view]['accuracy'] for view in sets}
    report['total_evaluation_seconds'] = time.perf_counter() - started
    memory = psutil.Process().memory_info()
    report['peak_observed_evaluation_rss_bytes'] = getattr(memory, 'peak_wset', memory.rss)
    write_json(output / 'evaluation.json', report)
    print(json.dumps({'output': str(output), 'seconds': report['total_evaluation_seconds'],
                      'accuracy_delta': report['accuracy_delta_from_same_length_original'],
                      'paired_counts': {v: {k: x for k, x in values.items() if not k.endswith('_ids')}
                                        for v, values in report['paired_changes']['finetuned'].items()}}, indent=2), flush=True)
    return report
