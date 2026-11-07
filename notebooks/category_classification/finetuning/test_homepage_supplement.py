"""Offline tests for explicit reviewed homepage sources and resume provenance."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from finetuning import homepages
from finetuning.data import sha256


@pytest.fixture
def supplement(tmp_path, monkeypatch):
    monkeypatch.setattr(homepages, 'ROOT', tmp_path)
    train = [dict(tool_id='train', group_id='g1', category='a')]
    held = [dict(tool_id='held', group_id='g2', category='a')]
    monkeypatch.setattr(homepages, 'load_data', lambda: ({'train':train, 'validation':held, 'test':[]}, {}))
    for folder in ['backend/config', 'data/aitoolbuzz-com-16k-ai-tools-database', 'data/category_classification/transfer_v1', 'supplement']:
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    (tmp_path / 'backend/config/known_tool_registry_exclusions.json').write_text('{"excluded_tool_ids":[]}')
    (tmp_path / 'data/aitoolbuzz-com-16k-ai-tools-database/ai_tools_cleaned.csv').write_text('tool_id,Website\nheld,https://held.example/\n')
    (tmp_path / 'data/category_classification/transfer_v1/pages.jsonl').write_text('')
    capture = dict(tool_id='train', title='Specific AI function', meta_description='', headings=[], body='',
                   requested_url='https://train.example/', final_url='https://train.example/')
    (tmp_path / 'captures.jsonl').write_text(json.dumps(capture) + '\n')
    review = dict(tool_id='train', group_id='g1', status='approved', supporting_excerpt='AI function',
                  reviewer='Codex (AI)', reviewed_at='2026-11-07T00:00:00Z', labeling_rule_version='test-v1',
                  excerpt_visible_at_128=True, proposed_category='a', training_text='Specific AI function', capture_index=0,
                  capture_sha256=hashlib.sha256(json.dumps(capture, sort_keys=True, ensure_ascii=False).encode()).hexdigest())
    page = dict(tool_ids=['train'], host='train.example', requested_url='https://train.example/', final_url='https://train.example/',
                catalog_split='train', category='a', title=capture['title'], meta_description='', headings='', body='')
    path = tmp_path / 'supplement/pages.jsonl'
    def save(pages=None, reviews=None):
        path.write_text(''.join(json.dumps(p) + '\n' for p in (pages or [page])))
        path.with_name('reviews.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in (reviews or [review])))
        path.with_name('manifest.json').write_text(json.dumps(dict(capture_source='captures.jsonl', capture_sha256=sha256(tmp_path / 'captures.jsonl'),
            output_hashes={n:sha256(path.with_name(n)) for n in ['pages.jsonl', 'reviews.jsonl']})))
    save()
    return train, page, review, path, save


def test_custom_source(supplement):
    train, _, _, path, _ = supplement
    rows, provenance = homepages.training_homepages(train, path)
    assert len(rows) == 1 and rows[0]['description_text'] == 'Specific AI function'
    assert provenance['reviews_sha256'] == sha256(path.with_name('reviews.jsonl'))


@pytest.mark.parametrize('change', ['id', 'group', 'host', 'approval', 'category', 'duplicate', 'evidence'])
def test_rejections(supplement, change):
    train, page, review, path, save = supplement
    if change == 'id': page['tool_ids'] = ['held']
    if change == 'group': train[0]['group_id'] = 'g2'
    if change == 'host': page['final_url'] = 'https://www.held.example/'
    if change == 'approval': review['status'] = 'pending_review'
    if change == 'category': page['category'] = 'b'
    if change == 'evidence': page['body'] = 'unreviewed text'
    save([page, page] if change == 'duplicate' else [page])
    with pytest.raises(ValueError):
        homepages.training_homepages(train, path)


def test_changed_source_rejects_resume(supplement):
    train, _, review, path, save = supplement
    _, previous = homepages.training_homepages(train, path)
    review['reviewer'] = 'updated reviewer'
    save()
    _, current = homepages.training_homepages(train, path)
    with pytest.raises(ValueError, match='changed'):
        homepages.require_same_source(previous, current)


def test_default_source_remains_compatible(supplement):
    train, page, _, _, _ = supplement
    default = homepages.ROOT / 'data/category_classification/transfer_v1/pages.jsonl'
    default.write_text(json.dumps(page) + '\n')
    rows, provenance = homepages.training_homepages(train)
    assert rows[0]['text_source'] == 'homepage'
    assert 'reviews_sha256' not in provenance


def test_unresolved_group_labels_rejected(supplement):
    train, _, _, path, _ = supplement
    train.append(dict(tool_id='related', group_id='g1', category='b'))
    with pytest.raises(ValueError, match='group'):
        homepages.training_homepages(train, path)


def test_capture_mutation_rejected(supplement):
    train, _, _, path, _ = supplement
    (homepages.ROOT / 'captures.jsonl').write_text('{}\n')
    with pytest.raises(ValueError, match='capture source changed'):
        homepages.training_homepages(train, path)


def test_heldout_normalized_text_rejected(supplement):
    train, page, _, path, _ = supplement
    held_page = dict(page, host='held.example', tool_ids=['held'], catalog_split='validation', title='SPECIFIC AI FUNCTION!')
    (homepages.ROOT / 'data/category_classification/transfer_v1/pages.jsonl').write_text(json.dumps(held_page) + '\n')
    with pytest.raises(ValueError, match='held-out hosts/text'):
        homepages.training_homepages(train, path)


def test_explicit_cli_option():
    from finetune_bge import parser
    args = parser().parse_args(['--output', 'run', '--training-homepages', 'reviewed/pages.jsonl'])
    assert args.training_homepages == Path('reviewed/pages.jsonl')
