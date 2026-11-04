"""Unique, group-isolated triplets and resumable deterministic epoch shuffling."""
import random
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from .data import SEED, normalized

ROLES = ('anchor', 'positive', 'negative')


def example_id(row):
    return row.get('example_id', row['tool_id'])


def triplet_key(triplet):
    return tuple(example_id(triplet[role]) for role in ROLES)


def triplet_coverage(triplets):
    result = {'unique_triplets': len({triplet_key(t) for t in triplets})}
    tools = set()
    for role in ROLES:
        members = [t[role] for t in triplets]
        result['unique_' + role + 's'] = len({example_id(r) for r in members})
        result[role + '_categories'] = dict(sorted(Counter(r['category'] for r in members).items()))
        tools.update(tool for r in members for tool in r.get('tool_ids', [r['tool_id']]))
    result['unique_tools'] = len(tools)
    result['homepage_anchors'] = sum(t['anchor'].get('text_source') == 'homepage' for t in triplets)
    return result


class TripletSchedule:
    def __init__(self, size, seed=SEED):
        if size < 1:
            raise ValueError('Triplet schedule must be nonempty')
        self.rng = random.Random(seed)
        self.order = list(range(size))
        self.rng.shuffle(self.order)
        self.cursor = self.epoch = 0

    def take(self, capacity):
        if capacity < 1:
            raise ValueError('Capacity must be positive')
        if self.cursor == len(self.order):
            self.cursor = 0
            self.epoch += 1
            self.rng.shuffle(self.order)
        end = min(len(self.order), self.cursor + capacity)
        selected = self.order[self.cursor:end]
        self.cursor = end
        return selected

    def state_dict(self):
        return {'order': list(self.order), 'cursor': self.cursor, 'epoch': self.epoch, 'rng': self.rng.getstate()}

    def load_state_dict(self, state):
        if sorted(state['order']) != list(range(len(self.order))) or not 0 <= state['cursor'] <= len(self.order):
            raise ValueError('Invalid saved shuffle state')
        self.order, self.cursor, self.epoch = list(state['order']), state['cursor'], state['epoch']
        self.rng.setstate(state['rng'])


def bounded_similarity(vector, vectors, chunk_size=512):
    import numpy as np
    if chunk_size < 1:
        raise ValueError('Chunk size must be positive')
    return np.concatenate([vectors[start:start + chunk_size] @ vector for start in range(0, len(vectors), chunk_size)])


def sample_unique_triplets(rows, limit=256, seed=SEED, *, vectors=None, margin=.1,
                           semi_hard_fraction=.5, extra_anchors=None, anchor_vectors=None,
                           homepage_fraction=0., chunk_size=512, return_stats=False):
    import numpy as np
    if limit < 1 or not 0 <= semi_hard_fraction <= 1 or not 0 <= homepage_fraction <= 1:
        raise ValueError('Invalid triplet limit or mixture fraction')
    if vectors is not None and (len(vectors) != len(rows) or not np.isfinite(vectors).all()):
        raise ValueError('Mining vectors must align with training rows')
    rng = random.Random(seed)
    keys = [normalized(r['description_text']) for r in rows]
    text_labels = defaultdict(set)
    for row, key in zip(rows, keys):
        text_labels[key].add(row['category'])
    clean = [i for i, r in enumerate(rows) if keys[i] and len(text_labels[keys[i]]) == 1]
    categories = defaultdict(list)
    for i in clean:
        categories[rows[i]['category']].append(i)
    anchors = defaultdict(list)
    for c, indices in categories.items():
        if len({rows[i]['group_id'] for i in indices}) > 1:
            anchors[c] = indices
    if len(categories) < 2 or not anchors:
        raise ValueError('No eligible training triplets')
    pages = defaultdict(list)
    training_ids = {r['tool_id'] for r in rows}
    training_groups = {r['group_id'] for r in rows}
    for row in extra_anchors or []:
        if (not set(row.get('tool_ids', [row['tool_id']])) <= training_ids or
            not set(row.get('excluded_groups', [row['group_id']])) <= training_groups):
            raise ValueError('Extra mining anchors must reference training tools/groups only')
        if row['category'] in anchors:
            pages[row['category']].append(row)
    names = sorted(anchors)
    result, seen, counts = [], set(), Counter()
    def member(row):
        return {k: row[k] for k in ('tool_id', 'category', 'group_id', 'example_id', 'text_source', 'tool_ids', 'excluded_groups') if k in row}
    for attempt in range(max(100, limit * 50)):
        category = names[attempt % len(names)]
        if homepage_fraction > 0 and pages[category] and rng.random() < homepage_fraction:
            anchor = rng.choice(pages[category])
            anchor_index = None
        else:
            anchor_index = rng.choice(anchors[category])
            anchor = rows[anchor_index]
        groups = set(anchor.get('excluded_groups', [anchor['group_id']]))
        anchor_text = normalized(anchor['description_text'])
        positives = [i for i in categories[category] if rows[i]['group_id'] not in groups and keys[i] != anchor_text]
        if not positives:
            continue
        similarity = None
        positive_fallback = False
        if vectors is not None:
            vector = vectors[anchor_index] if anchor_index is not None else anchor_vectors[example_id(anchor)]
            similarity = bounded_similarity(vector, vectors, chunk_size)
            reasonable = sorted((i for i in positives if .2 <= similarity[i] < .98), key=lambda i: (-float(similarity[i]), i))[:32]
            reasonable = [i for i in reasonable if SequenceMatcher(None, anchor_text, keys[i]).ratio() < .92][:8]
            if reasonable:
                positives = reasonable
            else:
                positives = [i for i in positives if SequenceMatcher(None, anchor_text, keys[i]).ratio() < .92]
                positive_fallback = True
        if not positives:
            continue
        positive_index = rng.choice(positives)
        positive = rows[positive_index]
        excluded_groups = groups | {positive['group_id']}
        negatives = [i for i in clean if rows[i]['category'] != category and rows[i]['group_id'] not in excluded_groups
                     and keys[i] not in (anchor_text, keys[positive_index])]
        if not negatives:
            continue
        kind = 'random'
        requested = similarity is not None and rng.random() < semi_hard_fraction
        if requested:
            semi_hard = [i for i in negatives if 0 < float(similarity[positive_index] - similarity[i]) < margin]
            if semi_hard:
                negatives = semi_hard
                kind = 'semi_hard'
            else:
                kind = 'fallback_random'
        negative_index = rng.choice(negatives)
        t = dict(zip(ROLES, (member(anchor), member(positive), member(rows[negative_index]))))
        key = triplet_key(t)
        if key in seen:
            continue
        seen.add(key)
        if similarity is not None:
            t['sampling'] = {'negative': kind, 'semi_hard_requested': requested,
                             'positive_similarity': float(similarity[positive_index]),
                             'negative_similarity': float(similarity[negative_index]), 'positive_fallback': positive_fallback}
        result.append(t)
        counts[kind] += 1
        counts['semi_hard_requested'] += requested
        counts['positive_fallback'] += positive_fallback
        if len(result) == limit:
            break
    if not result:
        raise ValueError('No triplets satisfy text and group isolation')
    stats = {**triplet_coverage(result), 'requested_triplets': limit, 'attempts': attempt + 1,
             'negative_counts': {kind: counts[kind] for kind in ('random', 'semi_hard', 'fallback_random')},
             'requested_semi_hard_fraction': semi_hard_fraction if vectors is not None else 0.,
             'actual_semi_hard_fraction': counts['semi_hard'] / len(result),
             'fallback_rate_among_requested': counts['fallback_random'] / max(1, counts['semi_hard_requested']),
             'positive_fallback_count': counts['positive_fallback']}
    return (result, stats) if return_stats else result
