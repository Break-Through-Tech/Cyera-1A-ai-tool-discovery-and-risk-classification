"""One predeclared bounded homepage comparison; no model promotion or search."""
import json
import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from finetuning.data import ROOT, MODEL, REVISION, CUTOFF, write_json, sha256
from finetuning.homepages import records
from finetuning.evaluation import paired_changes

SUPPLEMENT = ROOT / 'data/category_classification/homepage_training_v2/reviewed-2026-11-07-v1'
OUT = ROOT / 'artifacts/category_finetuning/homepage-reviewed-2026-11-07-v1'
REPORT = ROOT / 'notebooks/category_classification/reports/bge-homepages-2026-11-07'
CONTINUE = False


def command(name, script, args):
    log = OUT / (name + '.log')
    print('Starting ' + name, flush=True)
    with log.open('a' if CONTINUE else 'w', encoding='utf-8') as stream:
        subprocess.run([sys.executable, str(ROOT / 'notebooks/category_classification' / script), *map(str, args)],
                       cwd=ROOT, check=True, stdout=stream, stderr=subprocess.STDOUT)
    print('Completed ' + name, flush=True)


def train(name, seed, mixed=False, pilot=False):
    args = ['--output', OUT / name, '--reviewed-labels', SUPPLEMENT / 'reviewed-labels.json',
            '--seed', seed, '--max-steps', 64, '--max-triplets', 256, '--checkpoint',
            '--homepage-fraction', .25 if mixed else 0]
    if mixed:
        args += ['--training-homepages', SUPPLEMENT / 'pages.jsonl']
    if pilot:
        args += ['--pilot']
    prior = OUT / name / 'training_manifest.json'
    completed = prior.exists() and json.loads(prior.read_text())['status'] == 'completed'
    if not (CONTINUE and completed):
        if CONTINUE and prior.exists():
            args += ['--resume']
        command(name, 'finetune_bge.py', args)
    manifest = json.loads((OUT / name / 'training_manifest.json').read_text())
    assert manifest['status'] == 'completed'
    assert manifest['nonzero_gradient'] and manifest['trainable_parameters_changed'] and manifest['frozen_parameters_unchanged']
    assert manifest['reload_tolerance'] and manifest['optimizer_updates'] == (8 if pilot else 64)
    if mixed:
        assert manifest['homepage_source']['source_sha256'] == sha256(SUPPLEMENT / 'pages.jsonl')
        triplets = records(OUT / name / 'triplets.jsonl')
        presented = [triplets[i] for log in records(OUT / name / 'training_log.jsonl') for i in log['triplet_indices']]
        assert any(t['anchor'].get('text_source') == 'homepage' for t in presented)
    return manifest


def evaluate(name):
    if not (CONTINUE and (OUT / name / 'validation-full/evaluation.json').exists()):
        command(name + '-validation', 'evaluate_finetuned.py', ['--run', OUT / name])
    return json.loads((OUT / name / 'validation-full/evaluation.json').read_text())


def passes(a, b):
    original = b['candidates']['original_same_length']
    mixed = b['candidates']['finetuned']
    return (mixed['homepages']['accuracy'] > a['candidates']['finetuned']['homepages']['accuracy'] and
            mixed['homepages']['accuracy'] > original['homepages']['accuracy'] and
            all(mixed[v]['macro_f1'] >= original[v]['macro_f1'] - .01 and
                mixed[v]['coverage'] >= original[v]['coverage'] - .05 for v in ('homepages','descriptions')))


def report(evaluations):
    REPORT.mkdir(parents=True, exist_ok=False)
    review = json.loads((SUPPLEMENT / 'manifest.json').read_text())
    lines = ['# Reviewed homepage BGE experiment', '',
             'Primary target: forced accuracy on 106 validation homepages. Fixed k=15 and cutoff ' + str(CUTOFF) + '.',
             'CPU float32, final block only, 128 tokens, 64 updates, at most 256 unique triplets, microbatch 1 / accumulation 4, learning rate 1e-5, margin 0.1, random sampler.', '',
             f"30 attempts, 25 extracted, 16 approved distinct tools/groups. Outcomes: {review['review_counts']}.",
             'Approved tools/groups per category: ' + json.dumps(review['approved_by_category']), '',
             'Review decisions and exact token visibility evidence: data/category_classification/homepage_training_v2/reviewed-2026-11-07-v1/REPORT.md and reviews.jsonl.',
             'Bexi → Media And Content Creation (text editing); FloorDesign → Industry Specific (space planning); Atricent → Personal And Lifestyle (personal stylist). Prior two corrections retained for all conditions.', '',
             '| Seed / candidate | View | Correct / total | Accuracy | Macro-F1 | Coverage | Answered accuracy |',
             '|---|---|---:|---:|---:|---:|---:|']
    summary = {'review':review, 'runs':{}, 'paired':{}, 'seed1_passed':passes(*evaluations[20261014])}
    pilot = json.loads((OUT / 'resource-pilot/training_manifest.json').read_text())
    summary['resource_pilot'] = {k:pilot[k] for k in ('optimizer_updates','mean_triplet_loss','positive_loss_fraction','trainable_parameters_changed','frozen_parameters_unchanged','reload_tolerance','peak_observed_rss_bytes','training_seconds','homepage_source')}
    lines += ['', 'Resource pilot: ' + json.dumps(summary['resource_pilot'])]
    for seed, (a,b) in evaluations.items():
        for name, evaluation, candidate in [('original',b,'original_same_length'),('A-descriptions',a,'finetuned'),('B-homepages',b,'finetuned')]:
            for view in ('homepages','descriptions'):
                s = evaluation['candidates'][candidate][view]
                correct = round(s['accuracy'] * s['rows'])
                answered = s['accuracy_when_answering']
                lines += [f"| {seed} / {name} | {view} | {correct}/{s['rows']} | {s['accuracy']:.4%} | {s['macro_f1']:.4f} | {s['coverage']:.2%} | {answered:.2%} |"]
        for name, e in [('A',a),('B',b)]:
            m = e['training_manifest']
            run = Path(e['run'])
            triplets = records(run / 'triplets.jsonl')
            presented = [triplets[i] for log in records(run / 'training_log.jsonl') for i in log['triplet_indices']]
            pages = [t['anchor'] for t in presented if t['anchor'].get('text_source') == 'homepage']
            actual = dict(homepage_presentations=len(pages), total_presentations=len(presented),
                          unique_homepage_anchors=len({p['example_id'] for p in pages}),
                          categories=sorted({p['category'] for p in pages}),
                          active_loss_fraction=m['positive_loss_fraction'], training_seconds=m['training_seconds'],
                          evaluation_seconds=e['total_evaluation_seconds'], rss_bytes=m['peak_observed_rss_bytes'], sampler=m['sampling'])
            summary['runs'][f'{seed}-{name}'] = actual
            lines += ['', f"{seed} {name}: {json.dumps(actual)}"]
        for view in ('homepages','descriptions'):
            pa = records(Path(a['run']) / 'validation-full/finetuned' / (view + '.jsonl'))
            pb = records(Path(b['run']) / 'validation-full/finetuned' / (view + '.jsonl'))
            paired = paired_changes(pa,pb)
            paired['changed_wrong_categories'] = [dict(example_id=x['example_id'], expected=x['expected'], A=x['predicted'], B=y['predicted'])
                for x,y in zip(pa,pb) if not x['correct'] and not y['correct'] and x['predicted'] != y['predicted']]
            paired['details'] = [dict(example_id=x['example_id'], expected=x['expected'], A=x['predicted'], B=y['predicted']) for x,y in zip(pa,pb) if x['predicted'] != y['predicted']]
            summary['paired'][f'{seed}-{view}'] = paired
            lines += ['', f'{seed} B versus A, {view}: ' + json.dumps(paired)]
    repeated = len(evaluations) == 2 and all(passes(a,b) for a,b in evaluations.values())
    conclusion = 'Preliminary improvement repeated across both matched seeds; independent fresh held-out pages are still needed.' if repeated else 'No demonstrated improvement.'
    lines += ['', conclusion, 'One homepage changes accuracy by 0.94 percentage points. Small gains are preliminary.',
              'Second seed was run only if the first comparison improved the primary metric and passed both supporting guards.' if len(evaluations)==2 else 'Stopping rule: first seed did not justify a second-seed comparison; no additional experiments launched.',
              'Full per-category recall, confusion matrices and original-versus-trained paired errors are retained in each validation-full/evaluation.json and prediction files.',
              'Frozen test data was used only for hash/isolation checks. No collection expansion, model deployment or backend-default changes.']
    summary['conclusion'] = conclusion
    write_json(REPORT / 'summary.json', summary)
    (REPORT / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(conclusion, flush=True)


def main():
    global CONTINUE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--continue-existing', action='store_true', help='Resume interrupted runs and retain completed conditions')
    parser.add_argument('--report-only', action='store_true', help='Render the completed comparison without running models')
    args = parser.parse_args()
    if args.report_only:
        finish_report()
        return
    CONTINUE = args.continue_existing
    os.environ['HF_HOME'] = str(ROOT / '.cache-training/huggingface')
    os.environ['SENTENCE_TRANSFORMERS_HOME'] = str(ROOT / '.cache-training/sentence-transformers')
    declaration = dict(model=MODEL, revision=REVISION,
        max_length=128, trainable='final encoder block', device='cpu', precision='float32', max_steps=64, max_triplets=256,
        microbatch=1, accumulation=4, learning_rate=1e-5, margin=.1, sampler='random', seed=20261014, k=15, cutoff=CUTOFF,
        supplement_sha256=sha256(SUPPLEMENT / 'pages.jsonl'), labels_sha256=sha256(SUPPLEMENT / 'reviewed-labels.json'),
        conditions={'A':0,'B':.25}, repeat_seed=20261015,
        stopping_rule='Repeat both only if B beats A and matching original homepage accuracy and passes macro-F1 -0.01 / coverage -0.05 guards on both views.')
    if CONTINUE:
        previous = json.loads((OUT / 'predeclared.json').read_text())
        if {k:v for k,v in previous.items() if k != 'created_at'} != declaration:
            raise ValueError('Predeclared settings or input hashes changed')
    else:
        OUT.mkdir(parents=True, exist_ok=False)
        write_json(OUT / 'predeclared.json', dict(created_at=datetime.now(timezone.utc).isoformat(), **declaration))
    train('resource-pilot',20261014,mixed=True,pilot=True)
    evaluations = {}
    for seed in (20261014,20261015):
        train('A-' + str(seed),seed)
        train('B-' + str(seed),seed,mixed=True)
        a,b = evaluate('A-' + str(seed)), evaluate('B-' + str(seed))
        evaluations[seed] = (a,b)
        if not passes(a,b):
            break
    report(evaluations)
    finish_report()


def finish_report():
    """Keep the narrative concise; retain full metrics and changed examples as JSON."""
    from finetuning.data import load_data, reviewed_labels
    from finetuning.homepages import training_homepages
    splits, _ = load_data()
    effective, _ = reviewed_labels(splits['train'], SUPPLEMENT / 'reviewed-labels.json')
    training_homepages(effective, SUPPLEMENT / 'pages.jsonl')
    summary = json.loads((REPORT / 'summary.json').read_text())
    review = summary['review']
    metrics = {}
    lines = ['# Reviewed homepage BGE experiment', '', summary['conclusion'], '',
             'Codex reviewed all 30 immutable attempts (AI review, not human approval): 25 extracted and 16 approved distinct tools/groups. '
             'The other decisions were 5 acquisition failures, 4 insufficient-evidence/suitability decisions, 3 unverified/different products, and 2 ambiguous categories.', '',
             '[All 30 decisions and reasons](../../../../data/category_classification/homepage_training_v2/reviewed-2026-11-07-v1/REPORT.md). '
             'Shutdown content, redirects without product continuity, a company portfolio, a non-English page, and uncertain function boundaries were excluded. '
             'Bexi was relabeled to Media And Content Creation, FloorDesign to Industry Specific, and Atricent to Personal And Lifestyle; the two prior corrections were retained for every condition.', '',
             '| Approved category | Distinct pages/tools/groups |', '|---|---:|']
    lines += [f'| {category} | {n} |' for category,n in sorted(review['approved_by_category'].items())]
    lines += ['', 'The predeclared comparison used pinned BGE revision ' + REVISION + ', 128 tokens, CPU float32, final encoder block only, '
              '64 optimizer updates and 256 unique triplets maximum per condition; microbatch 1, accumulation 4, learning rate 1e-5, margin 0.1, random sampling, k=15, and cutoff ' + str(CUTOFF) + '. '
              'A used descriptions only; B used only the new supplement for homepage anchors (requested fraction 0.25). All references used the same merged labels.', '',
              '| Seed / candidate | View | Correct / total | Accuracy | Macro-F1 | Answered / total | Coverage | Accuracy when answered |',
              '|---|---|---:|---:|---:|---:|---:|---:|']
    for seed in (20261014,20261015):
        if f'{seed}-A' not in summary['runs']:
            continue
        a = json.loads((OUT / f'A-{seed}/validation-full/evaluation.json').read_text())
        b = json.loads((OUT / f'B-{seed}/validation-full/evaluation.json').read_text())
        for name,evaluation,candidate in [('Original BGE',b,'original_same_length'),('A descriptions',a,'finetuned'),('B homepages',b,'finetuned')]:
            for view in ('homepages','descriptions'):
                s = evaluation['candidates'][candidate][view]
                metrics[f'{seed}-{name}-{view}'] = s
                lines += [f"| {seed} / {name} | {view} | {round(s['accuracy']*s['rows'])}/{s['rows']} | {s['accuracy']:.2%} | {s['macro_f1']:.4f} | {s['answered']}/{s['rows']} | {s['coverage']:.2%} | {s['accuracy_when_answering']:.2%} |"]
        metrics[f'{seed}-original-to-trained-paired'] = {'A':a['paired_changes']['finetuned'], 'B':b['paired_changes']['finetuned']}
    lines += ['', '| Run | Actual homepage presentations | Unique homepage anchors | Active-loss fraction | Training seconds | Evaluation seconds | Peak training RSS MiB |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for name,r in summary['runs'].items():
        lines += [f"| {name} | {r['homepage_presentations']}/{r['total_presentations']} | {r['unique_homepage_anchors']} | {r['active_loss_fraction']:.2%} | {r['training_seconds']:.2f} | {r['evaluation_seconds']:.2f} | {r['rss_bytes']/2**20:.1f} |"]
    pilot = json.loads((OUT / 'resource-pilot/training_manifest.json').read_text())
    summary['resource_pilot'] = {k:pilot[k] for k in ('optimizer_updates','mean_triplet_loss','positive_loss_fraction','trainable_parameters_changed','frozen_parameters_unchanged','reload_tolerance','peak_observed_rss_bytes','training_seconds','homepage_source')}
    lines += ['', f"The eight-update pilot passed finite-loss, parameter-update, frozen-weight, saved-model reload and source-provenance checks in {pilot['training_seconds']:.2f} seconds, with {pilot['peak_observed_rss_bytes']/2**20:.1f} MiB peak sampled RSS. "
              'The homepage condition was interrupted after update 36 and resumed at its saved optimizer boundary; completed conditions were retained.', '',
              'The requested homepage fraction is conditional on category eligibility. Actual presentations and category coverage, together with sampler fallback counts, are retained in [summary.json](summary.json). '
              'Random sampling used no semi-hard fallback.', '']
    for key,p in summary['paired'].items():
        lines += [f"B versus A, {key}: {p['wrong_to_correct']} fixed, {p['correct_to_wrong']} regressed, and {len(p['changed_wrong_categories'])} changed between wrong categories."]
        if key.endswith('homepages'):
            lines += ['', '| Validation example | Expected | A | B |', '|---|---|---|---|']
            lines += [f"| {r['example_id']} | {r['expected']} | {r['A']} | {r['B']} |" for r in p['details']]
            lines += ['']
    lines += ['', 'The supporting guards permit at most a 0.01 macro-F1 drop and a five-percentage-point coverage drop on either view versus matching original BGE. '
              + ('The first seed passed; both conditions repeated with seed 20261015.' if '20261015-A' in summary['runs'] else 'The first seed did not meet the repeat criterion, so no second seed or further experiment was launched.'), '',
              'Full per-category recall and confusion matrices are in [metrics.json](metrics.json); exact paired IDs, expected/predicted labels and training coverage are in [summary.json](summary.json). '
              'Encoder-specific training-only indexes were rebuilt during validation. Original BGE used the same effective labels. Test data was limited to hash/isolation checks.', '',
              'One validation homepage changes accuracy by about 0.94 percentage points; small gains remain preliminary. Fresh independently labeled held-out pages are required for an independent claim. '
              'No deployment, backend-default change, new collection or further search was performed.']
    write_json(REPORT / 'metrics.json', metrics)
    write_json(REPORT / 'summary.json', summary)
    (REPORT / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
