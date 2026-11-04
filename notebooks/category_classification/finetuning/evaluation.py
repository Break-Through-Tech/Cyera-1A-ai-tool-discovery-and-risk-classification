"""Use the actual backend vote, including stable ties and nonnegative similarities."""
import json
import sys

from .data import ROOT, CUTOFF, sha256

sys.path.insert(0, str(ROOT / 'backend'))
from app.category.neighbors import CatalogTool, NeighborIndex


def make_index(vectors, rows, model=None):
    return NeighborIndex(vectors, tuple(CatalogTool(r['tool_id'], r.get('name', r['tool_id']), r['category'])
                                       for r in rows), 'experimental', model or {})


def score_examples(index, vectors, rows):
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
    votes = [index.vote(vector, 15) for vector in vectors]
    truth = [r['category'] for r in rows]
    predicted = [v.category for v in votes]
    kept = [i for i, v in enumerate(votes) if v.share >= CUTOFF]
    labels = sorted({t.category for t in index.tools})
    examples = []
    for row, vote in zip(rows, votes):
        identifier = row.get('tool_id') or 'homepage:' + row['host']
        examples.append({'example_id': identifier, 'tool_ids': row.get('tool_ids', [identifier]),
                         'expected': row['category'], 'predicted': vote.category, 'share': vote.share,
                         'correct': vote.category == row['category'], 'answered': vote.share >= CUTOFF,
                         'neighbors': [dict(tool_id=n.tool_id, category=n.category, similarity=n.similarity)
                                       for n in vote.neighbors]})
    result = {'rows': len(rows), 'accuracy': accuracy_score(truth, predicted),
            'macro_f1': f1_score(truth, predicted, labels=labels, average='macro', zero_division=0),
            'per_category': classification_report(truth, predicted, labels=labels, output_dict=True, zero_division=0),
            'confusion_matrix': {'labels': labels, 'counts': confusion_matrix(truth, predicted, labels=labels).tolist()},
            'neighbor_category_agreement': sum(sum(n.category == v.category for n in v.neighbors) / len(v.neighbors)
                                                for v in votes) / len(votes),
            'cutoff': CUTOFF, 'answered': len(kept), 'coverage': len(kept) / len(rows),
            'accuracy_when_answering': accuracy_score([truth[i] for i in kept], [predicted[i] for i in kept]) if kept else None}
    return result, examples


def metrics(index, vectors, rows):
    return score_examples(index, vectors, rows)[0]


def paired_changes(original, candidate):
    if [r['example_id'] for r in original] != [r['example_id'] for r in candidate]:
        raise ValueError('Paired predictions must refer to the same examples in the same order')
    if [r['expected'] for r in original] != [r['expected'] for r in candidate]:
        raise ValueError('Validation ground truth changed')
    fixed = [a['example_id'] for a, b in zip(original, candidate) if not a['correct'] and b['correct']]
    broken = [a['example_id'] for a, b in zip(original, candidate) if a['correct'] and not b['correct']]
    return {'wrong_to_correct': len(fixed), 'correct_to_wrong': len(broken),
            'fixed_ids': fixed, 'regressed_ids': broken, 'net_correct_change': len(fixed) - len(broken)}


def validation_sets(splits, quick=0, pages_path=None):
    path = pages_path or ROOT / 'data/category_classification/transfer_v1/pages.jsonl'
    # JSON strings can contain literal Unicode line separators. splitlines() would
    # split those inside strings; JSONL records are separated by physical newlines.
    with path.open(encoding='utf-8') as stream:
        pages = [json.loads(line) for line in stream if line.strip()]
    pages = [p for p in pages if p['catalog_split'] == 'validation']
    validation_ids = {r['tool_id'] for r in splits['validation']}
    for page in pages:
        identifiers = page['tool_ids']
        if not identifiers or not set(identifiers) <= validation_ids:
            raise ValueError('Homepage is not a validation tool')
    descriptions = sorted(splits['validation'], key=lambda r: r['tool_id'])
    pages = sorted(pages, key=lambda p: json.dumps(p, sort_keys=True))
    if quick:
        descriptions, pages = descriptions[:quick], pages[:quick]
    homepage_rows = [dict(p, description_text=' '.join(p[k] for k in
                     ('title', 'meta_description', 'headings', 'body') if p[k])) for p in pages]
    return {'descriptions': descriptions, 'homepages': homepage_rows}, sha256(path)
