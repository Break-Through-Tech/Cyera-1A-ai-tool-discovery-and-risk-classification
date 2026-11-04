"""Produce compact, auditable validation comparisons; never promote a checkpoint."""
import argparse
import csv
import json
from pathlib import Path

from finetuning.sampling import triplet_coverage


def observed_coverage(run, manifest):
    with (run / 'triplets.jsonl').open(encoding='utf-8') as stream:
        triplets = [json.loads(line) for line in stream]
    with (run / 'training_log.jsonl').open(encoding='utf-8') as stream:
        logs = [json.loads(line) for line in stream]
    if logs and 'triplet_indices' in logs[0]:
        seen = {i for record in logs for i in record['triplet_indices']}
    else:
        # The preserved v1 pilot consumed triplets in recorded, unshuffled order.
        seen = {i % len(triplets) for i in range(manifest['triplet_presentations'])}
    coverage = triplet_coverage([triplets[i] for i in sorted(seen)])
    coverage['available_unique_triplets'] = triplet_coverage(triplets)['unique_triplets']
    return coverage


def build_report(evaluations, output):
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    checkpoints, candidates = [], []
    evidence_hashes = None
    def consider(run, label, step, scores, reference, model, settings, label_version):
        acceptable = all(scores[v]['macro_f1'] >= reference[v]['macro_f1'] - .01 and
                         scores[v]['coverage'] >= reference[v]['coverage'] - .05
                         for v in ('descriptions', 'homepages'))
        candidates.append({'run': run, 'candidate': label, 'updates': step, 'model': str(model),
                           'settings': settings, 'labels_version': label_version,
                           'homepage_accuracy': scores['homepages']['accuracy'],
                           'description_accuracy': scores['descriptions']['accuracy'],
                           'homepage_accuracy_delta': scores['homepages']['accuracy'] - reference['homepages']['accuracy'],
                           'description_macro_f1': scores['descriptions']['macro_f1'],
                           'passes_supporting_guards': acceptable,
                           'eligible_gain': acceptable and scores['homepages']['accuracy'] > reference['homepages']['accuracy']})
    for path in evaluations:
        report = json.loads(path.read_text(encoding='utf-8'))
        if report['development_only']:
            raise ValueError('Run comparisons require full validation, not quick subsets')
        hashes = (report['dataset_hashes'], report['homepage_sha256'])
        if evidence_hashes is not None and hashes != evidence_hashes:
            raise ValueError('Comparison datasets/homepages changed')
        evidence_hashes = hashes
        manifest = report['training_manifest']
        settings = manifest['settings']
        consider(Path(report['run']).name, 'finetuned', manifest['optimizer_updates'], report['candidates']['finetuned'],
                 report['candidates']['original_same_length'], Path(report['run']) / 'model', settings,
                 manifest['labels'].get('sha256', 'original'))
        for step in manifest.get('evaluated_steps', []):
            if step == manifest['optimizer_updates']:
                continue
            directory = Path(report['run']) / 'validation-checkpoints' / f'step-{step}'
            scores = json.loads((directory / 'metrics.json').read_text(encoding='utf-8'))
            checkpoints.append((Path(report['run']).name, step, scores))
            consider(Path(report['run']).name, f'checkpoint-{step}', step, scores,
                     report['candidates']['original_same_length'], directory / 'model', settings,
                     manifest['labels'].get('sha256', 'original'))
        coverage = observed_coverage(Path(report['run']), manifest)
        for name in ('original_same_length', 'finetuned', 'deployed_original_preprocessing'):
            scores = report['candidates'][name]
            row = {'run': Path(report['run']).name, 'candidate': name, 'sampling': settings.get('sampler', 'legacy_random'),
                   'seed': settings['seed'], 'updates': manifest['optimizer_updates'] if name == 'finetuned' else 0,
                   'length': 'deployed-original' if name == 'deployed_original_preprocessing' else settings['max_length'],
                   'learning_rate': settings['learning_rate'],
                   'unique_triplets': coverage.get('unique_triplets') if name == 'finetuned' else 0,
                   'unique_tools': coverage.get('unique_tools') if name == 'finetuned' else None,
                   'available_unique_triplets': coverage['available_unique_triplets'] if name == 'finetuned' else 0,
                   'presentations': manifest.get('triplet_presentations') if name == 'finetuned' else 0,
                   'training_seconds': manifest['training_seconds'] if name == 'finetuned' else 0,
                   'evaluation_seconds': report['total_evaluation_seconds'] + manifest.get('checkpoint_evaluation_seconds', 0.)
                   if name == 'finetuned' else report['evaluation_seconds'][name],
                   'final_candidate_evaluation_seconds': report['evaluation_seconds'][name],
                   'checkpoint_evaluation_seconds': manifest.get('checkpoint_evaluation_seconds', 0.) if name == 'finetuned' else 0.,
                   'mean_triplet_loss': manifest.get('mean_triplet_loss') if name == 'finetuned' else None,
                   'active_triplet_fraction': manifest.get('positive_loss_fraction') if name == 'finetuned' else None,
                   'actual_semi_hard_fraction': manifest.get('sampling', {}).get('actual_semi_hard_fraction'),
                   'fallback_rate': manifest.get('sampling', {}).get('fallback_rate_among_requested'),
                   'completion_status': manifest['status'] if name == 'finetuned' else 'pretrained',
                   'peak_training_mib': manifest['peak_observed_rss_bytes'] / 2**20 if name == 'finetuned' else None,
                   'peak_comparison_process_mib': report['peak_observed_evaluation_rss_bytes'] / 2**20,
                   'sampling_seconds': manifest.get('sampling_seconds', 0.) if name == 'finetuned' else 0.,
                   'reviewed_labels': manifest['labels']['kind'] if name != 'deployed_original_preprocessing' else 'original catalog labels',
                   'labels_version': manifest['labels'].get('sha256', 'original') if name != 'deployed_original_preprocessing' else 'deployed-original',
                   'evaluation_source': str(path)}
            for view in ('descriptions', 'homepages'):
                for metric in ('accuracy', 'macro_f1', 'coverage', 'accuracy_when_answering', 'neighbor_category_agreement'):
                    row[f'{view}_{metric}'] = scores[view][metric]
                paired = report.get('paired_changes', {}).get(name, {}).get(view, {})
                row[f'{view}_wrong_to_correct'] = paired.get('wrong_to_correct')
                row[f'{view}_correct_to_wrong'] = paired.get('correct_to_wrong')
                row[f'{view}_accuracy_delta'] = scores[view]['accuracy'] - report['candidates']['original_same_length'][view]['accuracy']
            rows.append(row)
    with (output / 'comparison.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    text = ['# Bounded BGE experiment comparison', '',
            'Primary target, declared before comparisons: forced category accuracy on validation homepages. '
            'All runs use k=15 and the unchanged cutoff. The 106 homepages provide a noisy estimate; '
            'small differences are inconclusive. No test tools were scored. No checkpoint is promoted.', '',
            '| Run / candidate | Sampler (tokens, LR, seed) | Updates | Unique triplets / tools | Train s | Eval s incl. checkpoints | Peak train MiB |',
            '|---|---|---:|---:|---:|---:|---:|']
    shown = []
    baseline_keys = set()
    for r in rows:
        key = (r['candidate'], r['length'], r['labels_version'])
        if r['candidate'] != 'finetuned' and key in baseline_keys:
            continue
        baseline_keys.add(key)
        shown.append(r)
    for r in shown:
        settings_text = f"{r['sampling']} ({r['length']}, {r['learning_rate']:g}, {r['seed']})" if r['candidate'] == 'finetuned' else 'pretrained'
        coverage_text = f"{r['unique_triplets']} / {r['unique_tools']}" if r['candidate'] == 'finetuned' else 'n/a'
        text.append(f"| {r['run']} / {r['candidate']} | {settings_text} | {r['updates']} | {coverage_text} | {r['training_seconds']:.1f} | {r['evaluation_seconds']:.1f} | {r['peak_training_mib'] or 0:.1f} |")
    text += ['', '| Run / candidate | Description accuracy / F1 | Homepage accuracy / F1 | Description coverage / answered accuracy | Homepage coverage / answered accuracy | Homepage fixed / regressed |',
             '|---|---:|---:|---:|---:|---:|']
    def pair(r, view, first, second):
        a, b = r[f'{view}_{first}'], r[f'{view}_{second}']
        return f'{a:.4f} / {b:.4f}' if b is not None else f'{a:.4f} / n/a'
    for r in shown:
        text.append(f"| {r['run']} / {r['candidate']} | {pair(r, 'descriptions', 'accuracy', 'macro_f1')} | {pair(r, 'homepages', 'accuracy', 'macro_f1')} | {pair(r, 'descriptions', 'coverage', 'accuracy_when_answering')} | {pair(r, 'homepages', 'coverage', 'accuracy_when_answering')} | {r['homepages_wrong_to_correct']} / {r['homepages_correct_to_wrong']} |")
    text += ['', 'Settings, paired changes, exact evaluation provenance, per-category recall, confusion matrices and neighbor evidence are retained in the source evaluations and comparison.csv. '
             'Training and evaluation times are measured separately; cached baseline evaluations may be faster on later runs. '
             'Original BGE with the same reference labels remains a candidate. Reviewed-label comparisons require explicit approved versioned annotations; no labels were automatically changed. '
             'A promising configuration requires a second-seed comparison before considering deployment.', '']
    if checkpoints:
        text += ['| Retained earlier checkpoint | Description accuracy / F1 | Homepage accuracy / F1 | Homepage coverage |',
                 '|---|---:|---:|---:|']
        for run, step, scores in checkpoints:
            d, h = scores['descriptions'], scores['homepages']
            text.append(f"| {run} / update {step} | {d['accuracy']:.4f} / {d['macro_f1']:.4f} | {h['accuracy']:.4f} / {h['macro_f1']:.4f} | {h['coverage']:.4f} |")
        text.append('')
    eligible = [c for c in candidates if c['eligible_gain']]
    selected = max(eligible, key=lambda c: (c['homepage_accuracy'], c['description_macro_f1'], -c['updates'])) if eligible else None
    training_keys = ('sampler', 'max_triplets', 'max_length', 'microbatch_size', 'accumulation',
                     'learning_rate', 'weight_decay', 'margin', 'clip_norm', 'homepage_fraction',
                     'semi_hard_fraction', 'mining_chunk_size', 'threads', 'training_version')
    def group_key(candidate):
        return (candidate['updates'], candidate['labels_version'],
                *(candidate['settings'].get(k) for k in training_keys))
    groups = {}
    for candidate in candidates:
        groups.setdefault(group_key(candidate), {})[candidate['settings']['seed']] = candidate
    replications = []
    for group in groups.values():
        if len(group) < 2:
            continue
        results = list(group.values())
        values = [r['homepage_accuracy'] for r in results]
        replications.append({'updates': results[0]['updates'],
                             'training_settings': {k: results[0]['settings'].get(k) for k in training_keys},
                             'seed_results': results, 'homepage_accuracy_mean': sum(values) / len(values),
                             'homepage_accuracy_min': min(values), 'homepage_accuracy_max': max(values),
                             'all_seeds_improve_primary_and_pass_guards': all(r['eligible_gain'] for r in results)})
    needs_seed = selected if selected and len(groups[group_key(selected)]) < 2 else None
    selection = {'primary_target': 'validation_homepage_forced_accuracy',
                 'supporting_guards': {'maximum_macro_f1_drop_each_view': .01, 'maximum_coverage_drop_each_view': .05},
                 'candidates': candidates, 'best_validation_candidate': selected,
                 'selected_for_second_seed': needs_seed, 'seed_replications': replications,
                 'deployment_recommendation': 'None; validation selection alone does not justify deployment.'}
    (output / 'selection.json').write_text(json.dumps(selection, indent=2) + '\n', encoding='utf-8')
    text += ['Selection uses homepage accuracy with predeclared guards: macro-F1 may fall by at most 0.01 and '
             'coverage by at most five percentage points on each view, relative to matching original BGE. '
             'The deployed baseline is retained separately because its original preprocessing differs.', '',
             f"Candidate still needing a second-seed check: {needs_seed['run'] + ' / ' + needs_seed['candidate'] if needs_seed else 'none'}. "
             'This is experimental selection, not automatic promotion.', '']
    for replication in replications:
        results = ', '.join(f"seed {r['settings']['seed']}: {r['homepage_accuracy']:.4f}" for r in replication['seed_results'])
        text += [f"Second-seed comparison at {replication['updates']} updates: {results}. "
                 f"Mean {replication['homepage_accuracy_mean']:.4f}; range {replication['homepage_accuracy_min']:.4f}–{replication['homepage_accuracy_max']:.4f}. "
                 f"Both seeds improve the primary target and pass supporting guards: {replication['all_seeds_improve_primary_and_pass_guards']}. "
                 'Two seeds on the same small validation set do not provide an independent performance claim.', '']
    (output / 'REPORT.md').write_text('\n'.join(text), encoding='utf-8')
    return rows


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evaluations', nargs='+', required=True, type=Path, help='Full evaluation.json files')
    p.add_argument('--output', required=True, type=Path, help='New report directory')
    args = p.parse_args()
    build_report(args.evaluations, args.output)
