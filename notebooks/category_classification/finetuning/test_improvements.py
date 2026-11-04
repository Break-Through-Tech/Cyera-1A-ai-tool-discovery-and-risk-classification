"""Bounded offline checks for evaluation, sampling, mining and training state."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from finetuning.evaluation import paired_changes, make_index, score_examples
from finetuning.model import preserve_training_state


def test_evaluation_saves_neighbor_evidence_and_paired_counts():
    rows = [dict(tool_id='a', category='x'), dict(tool_id='b', category='y')]
    index = make_index(np.eye(2, dtype=np.float32), rows)
    result, predictions = score_examples(index, np.eye(2, dtype=np.float32), rows)
    assert result['accuracy'] == 1
    assert result['confusion_matrix']['counts'] == [[1, 0], [0, 1]]
    assert predictions[0]['neighbors'][0]['tool_id'] == 'a'
    changed = [dict(predictions[0], correct=False), dict(predictions[1], correct=True)]
    changes = paired_changes(changed, predictions)
    assert changes['wrong_to_correct'] == 1 and changes['correct_to_wrong'] == 0
    with pytest.raises(ValueError, match='same examples'):
        paired_changes(predictions, list(reversed(predictions)))


def test_modes_and_rng_restored_even_when_validation_fails():
    model = torch.nn.Sequential(torch.nn.Linear(2, 2), torch.nn.Dropout())
    model.eval()
    model[-1].train()
    modes = [m.training for m in model.modules()]
    rng = torch.get_rng_state().clone()
    with pytest.raises(RuntimeError):
        with preserve_training_state(model):
            model.eval()
            torch.rand(10)
            raise RuntimeError('evaluation interrupted')
    assert [m.training for m in model.modules()] == modes
    assert torch.equal(rng, torch.get_rng_state())


def test_content_checked_embedding_cache(tmp_path, monkeypatch):
    import finetuning.model as helpers
    calls = []
    def fake_encode(model, texts, batch_size):
        calls.append(list(texts))
        vectors = np.zeros((len(texts), 384), dtype=np.float32)
        vectors[:, 0] = 1
        return vectors
    monkeypatch.setattr(helpers, 'encode', fake_encode)
    model = torch.nn.Linear(2, 2)
    for checkpoint in ('first', 'first', 'second'):
        helpers.cached_encode(model, ['text'], cache=tmp_path, checkpoint=checkpoint)
    assert len(calls) == 2
    metadata = next(tmp_path.glob('*.json'))
    data = json.loads(metadata.read_text())
    data['sha256'] = 'changed'
    metadata.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='cache content'):
        helpers.cached_encode(model, ['text'], cache=tmp_path, checkpoint=data['checkpoint'])


def test_unique_sampling_and_saved_epoch_shuffle():
    from finetuning.sampling import sample_unique_triplets, TripletSchedule, triplet_key
    from finetuning.test_experiment import fixture_rows
    triplets, stats = sample_unique_triplets(fixture_rows(), 40, return_stats=True)
    assert len({triplet_key(t) for t in triplets}) == len(triplets) == 40
    assert stats['unique_tools'] == 9 and stats['unique_triplets'] == 40
    schedule = TripletSchedule(40, 17)
    first = schedule.take(40)
    state = schedule.state_dict()
    expected = schedule.take(40)
    assert sorted(expected) == list(range(40)) and expected != first
    resumed = TripletSchedule(40, 17)
    resumed.load_state_dict(state)
    assert resumed.take(40) == expected


def test_mining_semihard_rules_and_training_isolation():
    from finetuning.sampling import sample_unique_triplets, bounded_similarity, triplet_key
    from finetuning.test_experiment import fixture_rows
    rows = fixture_rows()
    descriptions = ['Draft technical articles for readers', 'Create visual assets from sketches',
                    'Edit narration and polish audio tracks', 'Forecast quarterly project expenses',
                    'Summarize documents into checklists', 'Translate customer support requests',
                    'Monitor networks for unusual access', 'Organize appointment reminders', 'Analyze survey statistics']
    rows = [dict(r, description_text=text) for r, text in zip(rows, descriptions)]
    rng = np.random.default_rng(11)
    vectors = rng.normal(size=(9, 8)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    triplets, stats = sample_unique_triplets(rows, 40, vectors=vectors, margin=.4,
                                            semi_hard_fraction=.5, chunk_size=2, return_stats=True)
    assert len({triplet_key(t) for t in triplets}) == len(triplets)
    assert triplets == sample_unique_triplets(rows, 40, vectors=vectors, margin=.4, chunk_size=2)
    ids = {r['tool_id'] for r in rows}
    for t in triplets:
        members = [t[role] for role in ('anchor', 'positive', 'negative')]
        assert {r['tool_id'] for r in members} <= ids
        assert len({r['group_id'] for r in members}) == 3
        if t['sampling']['negative'] == 'semi_hard':
            assert 0 < t['sampling']['positive_similarity'] - t['sampling']['negative_similarity'] < .4
    assert stats['negative_counts']['semi_hard'] > 0
    np.testing.assert_allclose(bounded_similarity(vectors[0], vectors, 2), vectors @ vectors[0], atol=1e-7)
    foreign = dict(rows[0], tool_id='validation-tool', example_id='homepage:foreign')
    with pytest.raises(ValueError, match='training tools'):
        sample_unique_triplets(rows, 2, extra_anchors=[foreign], homepage_fraction=1)


def test_training_homepage_identity_and_partition_checks(tmp_path):
    from finetuning.homepages import training_homepages
    from finetuning.sampling import sample_unique_triplets
    from finetuning.test_experiment import fixture_rows
    rows = fixture_rows()
    page = {'catalog_split': 'train', 'tool_ids': ['a0'], 'host': 'example.com',
            'title': 'Homepage', 'meta_description': '', 'headings': '', 'body': 'specific function'}
    path = tmp_path / 'pages.jsonl'
    path.write_text(json.dumps(page) + '\n')
    anchors, _ = training_homepages(rows, path)
    triplets = sample_unique_triplets(rows, 3, extra_anchors=anchors, homepage_fraction=1)
    for t in triplets:
        if t['anchor'].get('text_source') == 'homepage':
            assert t['positive']['tool_id'] != 'a0' and t['negative']['tool_id'] != 'a0'
            assert t['positive']['group_id'] != 'a0' and t['negative']['group_id'] != 'a0'
    page['tool_ids'] = ['test-tool']
    path.write_text(json.dumps(page) + '\n')
    with pytest.raises(ValueError, match='held-out'):
        training_homepages(rows, path)


def test_review_queue_is_deterministic_training_evidence_only():
    from review_training_neighbors import review_pairs
    from finetuning.test_experiment import fixture_rows
    rows = fixture_rows()
    vectors = np.eye(len(rows), dtype=np.float32)
    queue = review_pairs(rows, vectors, limit=4, chunk_size=2)
    assert queue == review_pairs(rows, vectors, limit=4, chunk_size=3)
    assert len(queue) == 4
    assert queue[0]['normalized_text_similarity'] >= .92
    ids = {r['tool_id'] for r in rows}
    for pair in queue:
        assert pair['left']['tool_id'] in ids and pair['right']['tool_id'] in ids
        assert pair['left']['category'] != pair['right']['category']
        assert all(value is None for value in pair['review'].values())
    with pytest.raises(ValueError, match='training rows'):
        review_pairs(rows, vectors, additional_pairs=[(0, len(rows))])


def test_truncation_measurement_does_not_change_random_sampling():
    from finetuning.homepages import truncation_statistics
    from finetuning.sampling import sample_unique_triplets
    from finetuning.test_experiment import fixture_rows
    rows = fixture_rows()
    page = dict(rows[0], example_id='homepage:example', text_source='homepage')
    assert sample_unique_triplets(rows, 10) == sample_unique_triplets(rows, 10, extra_anchors=[page], homepage_fraction=0)
    def tokenizer(texts, **kwargs):
        assert kwargs == {'truncation': False, 'padding': False}
        return {'input_ids': [list(range(len(t.split()))) for t in texts]}
    stats = truncation_statistics(tokenizer, [{'description_text': 'word ' * n} for n in (10, 200, 300)])
    assert stats['fraction_over_128'] == 2/3
    assert stats['fraction_over_256'] == 1/3


def test_committed_log_corruption_is_not_silently_discarded(tmp_path):
    from finetuning.data import restore_training_log
    path = tmp_path / 'training_log.jsonl'
    path.write_text('{"step":1}\nnot valid JSON\n', encoding='utf-8')
    with pytest.raises(ValueError, match='Committed training log'):
        restore_training_log(path, 1)
