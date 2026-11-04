"""Frozen data verification and bounded, group-isolated triplet sampling."""
import csv
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / 'data/category_classification/v1'
MODEL = 'BAAI/bge-small-en-v1.5'
REVISION = '5c38ec7c405ec4b44b94cc5a9bb96e735b38267a'
SEED = 20261014
CUTOFF = 0.468914118995349


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temp.replace(path)


def restore_training_log(path, through_step):
    """Discard only uncommitted records and a crash-truncated final JSONL record."""
    if not path.exists():
        return
    with path.open(encoding='utf-8') as stream:
        lines = stream.readlines()
    records = []
    for index, line in enumerate(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            committed = records[-1]['step'] if records else 0
            if index == len(lines) - 1 and not line.endswith('\n') and committed >= through_step:
                break
            raise ValueError('Committed training log is corrupt; refusing to discard evidence')
        records.append(record)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(''.join(json.dumps(r) + '\n' for r in records if r['step'] <= through_step), encoding='utf-8')
    temp.replace(path)


def load_data(directory=DATA):
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    splits, hashes = {}, {'manifest': sha256(directory / 'manifest.json')}
    for name in ('train', 'validation', 'test'):
        path = directory / f'{name}.csv'
        hashes[name] = sha256(path)
        if hashes[name] != manifest['partitions'][name]['sha256']:
            raise ValueError(f'Frozen {name} hash changed')
        with path.open(encoding='utf-8', newline='') as stream:
            splits[name] = list(csv.DictReader(stream))
        if len(splits[name]) != manifest['partitions'][name]['rows']:
            raise ValueError(f'Frozen {name} row count changed')
    for left, right in (('train', 'validation'), ('train', 'test'), ('validation', 'test')):
        for key in ('tool_id', 'group_id'):
            if {r[key] for r in splits[left]} & {r[key] for r in splits[right]}:
                raise ValueError(f'{key} crosses {left}/{right}')
    return splits, hashes


def normalized(text):
    return re.sub(r'\W+', ' ', text.casefold()).strip()


def reviewed_labels(rows, path):
    """Explicit versioned JSON: version, provenance, labels {training tool ID: category}."""
    source = json.loads(path.read_text(encoding='utf-8'))
    if not source.get('version') or not source.get('provenance'):
        raise ValueError('Reviewed labels need version and provenance')
    ids = {r['tool_id'] for r in rows}
    labels = {r['category'] for r in rows}
    if set(source['labels']) - ids or set(source['labels'].values()) - labels:
        raise ValueError('Reviewed labels must use training IDs and existing categories')
    return [dict(r, category=source['labels'].get(r['tool_id'], r['category'])) for r in rows], {
        'kind': 'reviewed', 'version': source['version'], 'provenance': source['provenance'],
        'sha256': sha256(path), 'overrides': source['labels']}


def sample_triplets(rows, limit=256, seed=SEED, **kwargs):
    """Public sampler; implementation lives alongside its resumable epoch schedule."""
    from .sampling import sample_unique_triplets
    return sample_unique_triplets(rows, limit, seed, **kwargs)
