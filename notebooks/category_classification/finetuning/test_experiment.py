"""Tiny offline fixtures; no model downloads. Run with the training environment."""
import sys
from pathlib import Path

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from finetuning.data import sample_triplets, normalized
from finetuning.model import cosine_triplet_loss, final_block, fingerprint, parameter_digest, validate_vectors
from finetuning.evaluation import make_index


def fixture_rows():
    return [dict(tool_id=f'{c}{i}', group_id=f'{c}{i}', category=c,
                 description_text=f'Distinct tool {c} {i}') for c in ('a', 'b', 'c') for i in range(3)]


def test_sampling_is_reproducible_and_isolated():
    rows = fixture_rows()
    rows.extend([dict(rows[0], tool_id='conflict', category='b')])
    triplets = sample_triplets(rows, 18)
    assert triplets == sample_triplets(rows, 18)
    assert len(triplets) == 18
    lookup = {r['tool_id']: r for r in rows}
    for t in triplets:
        a, p, n = [t[k] for k in ('anchor', 'positive', 'negative')]
        assert a['category'] == p['category'] != n['category']
        assert len({r['group_id'] for r in (a, p, n)}) == 3
        assert not {'a0', 'conflict'} & {r['tool_id'] for r in (a, p, n)}
        assert len({normalized(lookup[r['tool_id']]['description_text']) for r in (a, p, n)}) == 3
    assert {t['anchor']['category'] for t in triplets} == {'a', 'b', 'c'}


def test_no_eligible_triplet():
    with pytest.raises(ValueError):
        sample_triplets(fixture_rows()[:1])


def test_validation_jsonl_preserves_unicode_line_separators(tmp_path):
    import json
    from finetuning.evaluation import validation_sets
    page = {'tool_ids': ['heldout'], 'catalog_split': 'validation', 'category': 'a',
            'title': 'Title', 'meta_description': '', 'headings': '', 'body': 'hello\u2028world'}
    path = tmp_path / 'pages.jsonl'
    path.write_text(json.dumps(page, ensure_ascii=False) + '\n', encoding='utf-8')
    splits = {'validation': [{'tool_id': 'heldout', 'category': 'a', 'description_text': 'description'}]}
    sets, _ = validation_sets(splits, pages_path=path)
    assert len(sets['homepages']) == 1
    assert sets['homepages'][0]['description_text'] == 'Title hello\u2028world'
    page['tool_ids'] = ['training-tool']
    path.write_text(json.dumps(page) + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='not a validation tool'):
        validation_sets(splits, pages_path=path)


def test_active_loss_updates_only_unfrozen_block():
    # Real local BERT and SentenceTransformer modules, random tiny weights, no network.
    from transformers import BertConfig, BertModel, BertTokenizerFast
    from sentence_transformers import SentenceTransformer, models
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp)
        (path / 'vocab.txt').write_text('[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nalpha\nbeta\ngamma\n', encoding='utf-8')
        BertTokenizerFast(vocab_file=str(path / 'vocab.txt')).save_pretrained(path)
        BertModel(BertConfig(vocab_size=8, hidden_size=12, intermediate_size=16,
                             num_attention_heads=2, num_hidden_layers=2)).save_pretrained(path)
        model = SentenceTransformer(modules=[models.Transformer(str(path), max_seq_length=8),
                                             models.Pooling(12, pooling_mode='cls')], device='cpu')
        final_block(model)
        frozen = parameter_digest(model, False)
        before = parameter_digest(model, True)
        parameters = [p for p in model.parameters() if p.requires_grad]
        opt = torch.optim.AdamW(parameters, lr=.01, weight_decay=0)
        embeddings = [model(model.tokenize([s]))['sentence_embedding'] for s in ('alpha', 'beta', 'gamma')]
        loss = cosine_triplet_loss(*embeddings, margin=2.).mean()
        assert loss.isfinite() and loss.item() > 0
        loss.backward()
        assert any(p.grad is not None and p.grad.abs().sum() > 0 for p in parameters)
        assert all(p.grad is None or torch.isfinite(p.grad).all() for p in parameters)
        opt.step()
        assert parameter_digest(model, True) != before
        assert parameter_digest(model, False) == frozen
        model.eval()
        expected = model.encode(['alpha'], normalize_embeddings=True)
        model.save_pretrained(str(path / 'saved'))
        loaded = SentenceTransformer(str(path / 'saved'), device='cpu')
        np.testing.assert_allclose(expected, loaded.encode(['alpha'], normalize_embeddings=True), atol=1e-6, rtol=1e-5)
        from finetuning.model import encoder_fingerprint
        checkpoint = encoder_fingerprint(model)
        model.tokenizer.backend_tokenizer.no_padding()
        model.tokenizer.backend_tokenizer.no_truncation()
        assert encoder_fingerprint(model) == checkpoint
        model.max_seq_length += 1
        assert encoder_fingerprint(model) != checkpoint


def test_cosine_loss_and_partial_accumulation():
    torch.manual_seed(4)
    weight = torch.nn.Parameter(torch.randn(3, 3))
    inputs = torch.randn(3, 3, 3)
    def losses(w, subset):
        return cosine_triplet_loss(*(subset[:, i] @ w for i in range(3)), margin=2.)
    losses(weight, inputs).mean().backward()
    expected = weight.grad.clone()
    weight.grad = None
    for chunk in (inputs[:2], inputs[2:]):
        (losses(weight, chunk).sum() / len(inputs)).backward()
    torch.testing.assert_close(weight.grad, expected)


def test_fingerprint_includes_contents_and_length(tmp_path):
    path = tmp_path / 'weights'
    path.write_bytes(b'first')
    first = fingerprint(tmp_path, 128)
    assert fingerprint(tmp_path, 64) != first
    path.write_bytes(b'second')
    assert fingerprint(tmp_path, 128) != first


def test_votes_use_backend_ties_and_clipping():
    vectors = np.array([[1., 0.], [1., 0.], [-1., 0.]], dtype=np.float32)
    rows = [dict(tool_id=str(i), category=c) for i, c in enumerate(('b', 'a', 'c'))]
    index = make_index(vectors, rows)
    vote = index.vote(np.array([1., 0.]), 15)
    assert vote.category == 'a' and vote.share == .5
    assert [n.tool_id for n in vote.neighbors] == ['0', '1', '2']


def test_vector_validation():
    vectors = np.zeros((2, 384), dtype=np.float32)
    vectors[:, 0] = 1
    validate_vectors(vectors)
    vectors[0, 1] = np.nan
    with pytest.raises(ValueError):
        validate_vectors(vectors)


def test_exported_index_order_integrity_and_model_pair(tmp_path):
    import csv
    from finetuning.data import sha256, write_json, CUTOFF
    from app.category.neighbors import load_neighbor_index
    from app.category.embedder import LocalSentenceTransformerEmbedder
    vectors = np.zeros((2, 384), dtype=np.float32)
    vectors[0, 0], vectors[1, 1] = 1, 1
    np.save(tmp_path / 'embeddings.npy', vectors)
    with (tmp_path / 'tools.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerows([['tool_id', 'name', 'category'], ['first', 'One', 'a'], ['second', 'Two', 'b']])
    metadata = {'backend': 'sentence_transformers_local', 'repo': 'fixture', 'revision': 'fake',
                'fingerprint': 'incorrect', 'dim': 384, 'pooling': 'cls', 'normalized': True, 'max_length': 128}
    write_json(tmp_path / 'manifest.json', {'model': metadata, 'classification': {'k': 15, 'cutoff': CUTOFF},
               'tools_sha256': sha256(tmp_path / 'tools.csv'), 'embeddings_sha256': sha256(tmp_path / 'embeddings.npy')})
    index = load_neighbor_index(tmp_path)
    assert [r.tool_id for r in index.tools] == ['first', 'second']
    assert index.vote(vectors[0], 1).neighbors[0].tool_id == 'first'
    with pytest.raises(ValueError, match='fingerprint'):
        LocalSentenceTransformerEmbedder(tmp_path, metadata)
    (tmp_path / 'tools.csv').write_text('changed', encoding='utf-8')
    with pytest.raises(ValueError, match='content changed'):
        load_neighbor_index(tmp_path)


def test_frozen_partition_hashes_and_groups(tmp_path):
    import csv
    from finetuning.data import load_data, sha256, write_json
    manifest = {'partitions': {}}
    for i, name in enumerate(('train', 'validation', 'test')):
        path = tmp_path / f'{name}.csv'
        with path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(fixture_rows()[0]))
            writer.writeheader()
            writer.writerows([dict(r, tool_id=name + r['tool_id'], group_id=name + r['group_id'])
                             for r in fixture_rows()])
        manifest['partitions'][name] = {'rows': 9, 'sha256': sha256(path)}
    write_json(tmp_path / 'manifest.json', manifest)
    splits, hashes = load_data(tmp_path)
    assert len(splits['train']) == 9
    assert set(hashes) == {'manifest', 'train', 'validation', 'test'}
    # No scoring of held-out tools occurs here.
    sampled = sample_triplets(splits['train'], 8)
    training_ids = {r['tool_id'] for r in splits['train']}
    assert all(member['tool_id'] in training_ids for t in sampled for member in t.values())
    with (tmp_path / 'train.csv').open('a', encoding='utf-8') as stream:
        stream.write('changed')
    with pytest.raises(ValueError, match='hash changed'):
        load_data(tmp_path)


def test_boundary_resume_matches_uninterrupted_training(tmp_path, monkeypatch):
    """Exercise the CLI loop, optimizer state and RNG restoration with local weights."""
    import copy
    import json
    import signal
    from transformers import BertConfig, BertModel, BertTokenizerFast
    from sentence_transformers import SentenceTransformer, models
    import finetune_bge
    import finetuning.model as model_helpers
    path = tmp_path / 'tiny'
    path.mkdir()
    (path / 'vocab.txt').write_text('[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\ndistinct\ntool\na\nb\nc\n0\n1\n2\n', encoding='utf-8')
    BertTokenizerFast(vocab_file=str(path / 'vocab.txt')).save_pretrained(path)
    BertModel(BertConfig(vocab_size=13, hidden_size=384, intermediate_size=16,
                         num_attention_heads=2, num_hidden_layers=1)).save_pretrained(path)
    template = SentenceTransformer(modules=[models.Transformer(str(path), max_seq_length=8),
                                            models.Pooling(384, pooling_mode='cls')], device='cpu')
    # A validation callback deliberately changes modes and consumes RNG. The loop
    # must restore both before the next differentiable transformer forward.
    def require_training_mode(block, args):
        if torch.is_grad_enabled():
            assert block.training
    template[0].auto_model.encoder.layer[-1].register_forward_pre_hook(require_training_mode)
    import finetuning.validation as validation_helpers
    import finetuning.evaluation as evaluation_helpers
    monkeypatch.setattr(evaluation_helpers, 'validation_sets', lambda splits: ({}, 'fixture-homepages'))
    def fake_validation(model, train, sets, output):
        model.eval()
        torch.rand(11)
        return {'homepages': {'accuracy': .5}}, {}, 0.
    monkeypatch.setattr(validation_helpers, 'evaluate_model', fake_validation)
    original_loader = model_helpers.load_model
    monkeypatch.setattr(model_helpers, 'load_model', lambda path=None, max_length=8:
                        original_loader(path, max_length) if path else copy.deepcopy(template))
    monkeypatch.setattr(finetune_bge, 'load_data', lambda: ({'train': fixture_rows()}, {'fixture': 'unchanged'}))
    def run(directory, resume=False):
        monkeypatch.setattr(sys, 'argv', ['finetune_bge', '--output', str(directory), '--checkpoint',
                            '--max-steps', '5', '--max-triplets', '3', '--accumulation', '2',
                            '--max-length', '8', '--margin', '2', '--reserve-gib', '0', '--eval-steps', '2', '4'] + (['--resume'] if resume else []))
        finetune_bge.main()
    continuous = tmp_path / 'continuous'
    run(continuous)
    original_step = torch.optim.AdamW.step
    raised = False
    def interrupting_step(self, *args, **kwargs):
        nonlocal raised
        result = original_step(self, *args, **kwargs)
        if not raised:
            raised = True
            signal.raise_signal(signal.SIGINT)
        return result
    monkeypatch.setattr(torch.optim.AdamW, 'step', interrupting_step)
    resumed = tmp_path / 'resumed'
    run(resumed)
    assert json.loads((resumed / 'training_manifest.json').read_text())['status'] == 'interrupted'
    with (resumed / 'training_log.jsonl').open('a', encoding='utf-8') as stream:
        stream.write('{"step": 2, "loss": ')
    monkeypatch.setattr(torch.optim.AdamW, 'step', original_step)
    run(resumed, resume=True)
    expected = torch.load(continuous / 'checkpoint/state.pt', weights_only=False)
    actual = torch.load(resumed / 'checkpoint/state.pt', weights_only=False)
    assert actual['step'] == expected['step'] == 5
    assert actual['microbatches'] == expected['microbatches'] == 8
    assert actual['shuffle_state'] == expected['shuffle_state']
    for key, value in expected['model'].items():
        torch.testing.assert_close(actual['model'][key], value, atol=0, rtol=0)
    torch.testing.assert_close(actual['torch_rng'], expected['torch_rng'], atol=0, rtol=0)
