"""Bounded CPU-only triplet backpropagation experiment. See FINETUNING.md."""
import argparse
import importlib.metadata
import json
import os
import platform
import random
import signal
import time
from pathlib import Path

from finetuning.data import MODEL, REVISION, SEED, load_data, reviewed_labels, sample_triplets, sha256, write_json, restore_training_log
from finetuning.sampling import TripletSchedule, triplet_coverage, example_id


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True, help='New isolated run directory')
    p.add_argument('--pilot', action='store_true', help='Only eight optimizer updates; never starts a larger run')
    p.add_argument('--resume', action='store_true', help='Resume this run from its optimizer-boundary checkpoint')
    p.add_argument('--checkpoint', action='store_true', help='Retain checkpoint after successful completion')
    p.add_argument('--max-steps', type=int, default=64, help='Maximum optimizer updates (not microbatches)')
    p.add_argument('--max-triplets', type=int, default=256, help='Bounded number of training-only triplets')
    p.add_argument('--max-length', type=int, default=128, help='Truncation length in tokens; low-memory option: 64')
    p.add_argument('--microbatch-size', type=int, default=1, help='Triplets per differentiable forward')
    p.add_argument('--accumulation', type=int, default=4, help='Microbatches per update; low-memory option: 1')
    p.add_argument('--learning-rate', type=float, default=1e-5, help='AdamW learning rate')
    p.add_argument('--weight-decay', type=float, default=.01, help='AdamW weight decay')
    p.add_argument('--margin', type=float, default=.1, help='Cosine triplet margin')
    p.add_argument('--clip-norm', type=float, default=1., help='Maximum trainable gradient norm')
    p.add_argument('--threads', type=int, default=2, help='CPU threads, capped at two; data-loader workers are zero')
    p.add_argument('--reserve-gib', type=float, default=2., help='Stop at boundary if available RAM falls below this reserve')
    p.add_argument('--seed', type=int, default=SEED, help='Sampling and PyTorch seed')
    p.add_argument('--reviewed-labels', type=Path, help='Versioned training label JSON with provenance')
    p.add_argument('--sampler', choices=('random', 'mixed'), default='random', help='Unique random triplets or similarity-aware positives and mixed semi-hard negatives')
    p.add_argument('--semi-hard-fraction', type=float, default=.5, help='Requested semi-hard negative fraction for mixed sampling')
    p.add_argument('--mining-chunk-size', type=int, default=512, help='Training-only similarity search chunk size')
    p.add_argument('--homepage-fraction', type=float, default=0., help='Separate transfer experiment: fraction of training-only homepage anchors')
    p.add_argument('--measure-truncation', action='store_true', help='Record full training input token lengths before truncation')
    p.add_argument('--eval-steps', nargs='*', type=int, default=[], help='Predefined update boundaries for full KNN validation and saved candidate models, e.g. 64 128 256')
    return p


def main():
    args = parser().parse_args()
    for key in ('max_steps', 'max_triplets', 'max_length', 'microbatch_size', 'accumulation', 'threads'):
        if getattr(args, key) < 1:
            raise SystemExit(f'{key} must be positive')
    if (args.reserve_gib < 0 or args.learning_rate <= 0 or args.clip_norm <= 0 or args.margin < 0 or
        not 0 <= args.semi_hard_fraction <= 1 or not 0 <= args.homepage_fraction <= 1 or
        args.mining_chunk_size < 1 or any(s < 1 for s in args.eval_steps)):
        raise SystemExit('Invalid optimizer or memory settings')
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    import numpy as np
    import psutil
    import torch
    from finetuning.model import (cosine_triplet_loss, encode, final_block, fingerprint,
                                 load_model, parameter_digest, cached_encode, encoder_fingerprint, preserve_training_state)
    from threadpoolctl import threadpool_limits
    torch.set_num_threads(min(2, args.threads))
    threadpool_limits(limits=min(2, args.threads))
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.use_deterministic_algorithms(True)
    splits, hashes = load_data()
    rows = splits['train']
    provenance = {'kind': 'original catalog labels; not verified truth'}
    if args.reviewed_labels:
        rows, provenance = reviewed_labels(rows, args.reviewed_labels)
    settings = {k: v for k, v in vars(args).items() if k not in
                ('output', 'resume', 'checkpoint', 'reviewed_labels')}
    settings.update(device='cpu', precision='float32', workers=0, threads=min(2, args.threads))
    settings.update(training_version=2, shuffle_policy='independent-saved-epoch-rng-v1')
    run = args.output
    checkpoint = run / 'checkpoint/state.pt'
    if args.resume:
        manifest = json.loads((run / 'training_manifest.json').read_text(encoding='utf-8'))
        if manifest['status'] == 'completed':
            raise SystemExit('Completed runs cannot be overwritten')
        if manifest['settings'] != settings or manifest['dataset_hashes'] != hashes or manifest['labels'] != provenance:
            raise SystemExit('Resume requires identical settings, labels and dataset hashes')
        if sha256(run / 'triplets.jsonl') != manifest['triplets_sha256']:
            raise SystemExit('Triplet file changed')
        triplets = [json.loads(line) for line in (run / 'triplets.jsonl').read_text(encoding='utf-8').splitlines()]
    else:
        run.mkdir(parents=True, exist_ok=False)
        source_info, extra_anchors, vectors, anchor_vectors = {}, [], None, None
        sampling_started = time.perf_counter()
        if args.sampler == 'mixed' or args.homepage_fraction or args.measure_truncation:
            if psutil.virtual_memory().available < args.reserve_gib * 2**30:
                raise SystemExit('Available memory below reserve before mining')
            original = load_model(max_length=args.max_length)
            original_fingerprint = encoder_fingerprint(original)
            source_info['checkpoint_fingerprint'] = original_fingerprint
            if args.homepage_fraction or args.measure_truncation:
                from finetuning.homepages import training_homepages, truncation_statistics
                extra_anchors, source_info['homepages'] = training_homepages(rows)
                write_json(run / 'truncation.json', {
                    'training_descriptions': truncation_statistics(original.tokenizer, rows),
                    'training_homepages': truncation_statistics(original.tokenizer, extra_anchors)})
                if args.homepage_fraction and not extra_anchors:
                    raise SystemExit('No eligible training homepage anchors')
            if args.sampler == 'mixed':
                vectors = cached_encode(original, [r['description_text'] for r in rows], checkpoint=original_fingerprint)
                if args.homepage_fraction:
                    page_vectors = cached_encode(original, [r['description_text'] for r in extra_anchors], checkpoint=original_fingerprint)
                    anchor_vectors = {example_id(r): v for r, v in zip(extra_anchors, page_vectors)}
            del original
        triplets, sampling_stats = sample_triplets(rows, args.max_triplets, args.seed, vectors=vectors,
                    margin=args.margin, semi_hard_fraction=args.semi_hard_fraction,
                    extra_anchors=extra_anchors, anchor_vectors=anchor_vectors,
                    homepage_fraction=args.homepage_fraction, chunk_size=args.mining_chunk_size, return_stats=True)
        del vectors, anchor_vectors
        (run / 'triplets.jsonl').write_text(''.join(json.dumps(t) + '\n' for t in triplets), encoding='utf-8')
        manifest = {'model': MODEL, 'revision': REVISION, 'dataset_hashes': hashes,
                    'settings': settings, 'labels': provenance, 'status': 'initializing',
                    'sampling': sampling_stats, 'triplet_coverage': triplet_coverage(triplets),
                    'sampling_source': source_info, 'sampling_seconds': time.perf_counter() - sampling_started,
                    'triplets_sha256': sha256(run / 'triplets.jsonl'),
                    'packages': {p: importlib.metadata.version(p) for p in
                                 ('torch', 'sentence-transformers', 'transformers', 'numpy', 'scikit-learn', 'psutil')},
                    'hardware': {'os': platform.platform(), 'architecture': platform.machine(),
                                 'processor': platform.processor(), 'cpu_count': os.cpu_count(),
                                 'ram_gib': psutil.virtual_memory().total / 2**30,
                                 'available_ram_gib': psutil.virtual_memory().available / 2**30}}
        write_json(run / 'training_manifest.json', manifest)
    if psutil.virtual_memory().available < args.reserve_gib * 2**30:
        manifest['status'] = 'stopped_before_model_load'
        write_json(run / 'training_manifest.json', manifest)
        raise SystemExit('Available memory below reserve before loading model; choose a smaller configuration')
    # Mining/reference model construction must not perturb the training dropout RNG.
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    model = load_model(max_length=args.max_length)
    final_block(model)
    trainable = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(trainable, lr=args.learning_rate, weight_decay=args.weight_decay)
    assert trainable and all(p.requires_grad for group in optimizer.param_groups for p in group['params'])
    total = sum(p.numel() for p in model.parameters())
    count = sum(p.numel() for p in trainable)
    manifest.update(total_parameters=total, trainable_parameters=count, trainable_block='0.auto_model.encoder.layer[-1]')
    print(json.dumps({'hardware': manifest['hardware'], 'total_parameters': total, 'trainable_parameters': count}, indent=2))
    step = cursor = microbatches = 0
    elapsed = 0.
    evaluation_seconds = 0.
    session_evaluation_seconds = 0.
    evaluated_steps = []
    schedule = TripletSchedule(len(triplets), args.seed)
    nonzero = False
    loss_sum = active_count = triplet_count = 0
    initial_train = parameter_digest(model, True)
    frozen = parameter_digest(model, False)
    if args.resume:
        state = torch.load(checkpoint, map_location='cpu', weights_only=False)  # trusted local run only
        model.load_state_dict(state['model'])
        optimizer.load_state_dict(state['optimizer'])
        torch.set_rng_state(state['torch_rng'])
        random.setstate(state['random_rng'])
        np.random.set_state(state['numpy_rng'])
        step, cursor, microbatches, elapsed, nonzero = [state[k] for k in
            ('step', 'cursor', 'microbatches', 'elapsed', 'nonzero')]
        initial_train, frozen = state['initial_train'], state['frozen']
        schedule.load_state_dict(state['shuffle_state'])
        evaluation_seconds, evaluated_steps = state['evaluation_seconds'], state['evaluated_steps']
        loss_sum, active_count, triplet_count = [state[k] for k in ('loss_sum', 'active_count', 'triplet_count')]
        # A crash after appending a log but before committing a boundary can leave a trailing row.
        log_path = run / 'training_log.jsonl'
        restore_training_log(log_path, step)
    texts = {r['tool_id']: r['description_text'] for r in rows}
    if args.homepage_fraction:
        from finetuning.homepages import training_homepages
        pages, source = training_homepages(rows)
        if source != manifest['sampling_source']['homepages']:
            raise ValueError('Training homepages changed since sampling')
        texts.update({example_id(r): r['description_text'] for r in pages})
    limit = 8 if args.pilot else args.max_steps
    process = psutil.Process()
    peak = max(manifest.get('peak_observed_rss_bytes', 0), process.memory_info().rss)
    stopped = False
    low_memory = False
    def interrupt(signum, frame):
        nonlocal stopped
        stopped = True  # finish the current optimizer boundary before stopping
    previous_handler = signal.signal(signal.SIGINT, interrupt)
    started = time.perf_counter()
    def save_checkpoint():
        checkpoint.parent.mkdir(exist_ok=True)
        temp = checkpoint.with_suffix('.tmp')
        torch.save({'model': model.state_dict(), 'optimizer': optimizer.state_dict(),
                    'torch_rng': torch.get_rng_state(), 'random_rng': random.getstate(),
                    'numpy_rng': np.random.get_state(), 'step': step, 'cursor': cursor,
                    'microbatches': microbatches, 'elapsed': elapsed + time.perf_counter() - started - session_evaluation_seconds,
                    'nonzero': nonzero, 'initial_train': initial_train, 'frozen': frozen,
                    'loss_sum': loss_sum, 'active_count': active_count, 'triplet_count': triplet_count,
                    'shuffle_state': schedule.state_dict(), 'evaluation_seconds': evaluation_seconds,
                    'evaluated_steps': list(evaluated_steps)}, temp)
        temp.replace(checkpoint)
    def evaluate_boundary():
        nonlocal evaluation_seconds, session_evaluation_seconds
        if step not in args.eval_steps or step in evaluated_steps:
            return
        from finetuning.validation import evaluate_model
        from finetuning.evaluation import validation_sets
        destination = run / 'validation-checkpoints' / f'step-{step}'
        evaluation_started = time.perf_counter()
        with preserve_training_state(model):
            if (destination / 'metrics.json').exists():
                prior = json.loads((destination / 'metadata.json').read_text(encoding='utf-8'))
                if prior['checkpoint'] != encoder_fingerprint(model) or prior['dataset_hashes'] != hashes:
                    raise ValueError('Saved boundary evaluation differs from resumed checkpoint')
            else:
                destination.mkdir(parents=True, exist_ok=True)
                model.save_pretrained(str(destination / 'model'))
                sets, homepage_hash = validation_sets(splits)
                scores, _, seconds = evaluate_model(model, rows, sets, destination)
                write_json(destination / 'metadata.json', {'step': step, 'checkpoint': encoder_fingerprint(model),
                           'dataset_hashes': hashes, 'homepage_sha256': homepage_hash, 'evaluation_seconds': seconds,
                           'primary_target': 'validation_homepage_forced_accuracy', 'training_loss': loss_sum / max(1, triplet_count),
                           'active_fraction': active_count / max(1, triplet_count)})
                write_json(destination / 'metrics.json', scores)
        duration = time.perf_counter() - evaluation_started
        evaluation_seconds += duration
        session_evaluation_seconds += duration
        evaluated_steps.append(step)
        save_checkpoint()
    status = 'completed'
    try:
        if not args.resume:
            save_checkpoint()  # step zero also permits recovery before the first update commits
        evaluate_boundary()
        while step < limit:
            if stopped or low_memory or psutil.virtual_memory().available < args.reserve_gib * 2**30:
                status = 'interrupted' if stopped else 'memory_reserve_stop'
                break
            optimizer.zero_grad(set_to_none=True)
            # Do not cross the epoch boundary; weight a partial accumulation by its actual triplet count.
            selected = schedule.take(args.microbatch_size * args.accumulation)
            group = [triplets[i] for i in selected]
            losses, active = [], 0
            for start in range(0, len(group), args.microbatch_size):
                batch = group[start:start + args.microbatch_size]
                outputs = []
                for role in ('anchor', 'positive', 'negative'):
                    features = model.tokenize([texts[example_id(t[role])] for t in batch])
                    outputs.append(model(features)['sentence_embedding'])
                loss = cosine_triplet_loss(*outputs, args.margin)
                if not torch.isfinite(loss).all():
                    raise FloatingPointError('Nonfinite triplet loss')
                (loss.sum() / len(group)).backward()
                losses.extend(loss.detach().tolist())
                active += int((loss > 0).sum())
                microbatches += 1
                peak = max(peak, process.memory_info().rss)
                if psutil.virtual_memory().available < args.reserve_gib * 2**30:
                    low_memory = True
            for parameter in trainable:
                if parameter.grad is not None:
                    if not torch.isfinite(parameter.grad).all():
                        raise FloatingPointError('Nonfinite gradient')
                    nonzero |= bool(torch.count_nonzero(parameter.grad))
            torch.nn.utils.clip_grad_norm_(trainable, args.clip_norm, error_if_nonfinite=True)
            # AdamW decay alone must not masquerade as learning on inactive triplets.
            if not active:
                optimizer.zero_grad(set_to_none=True)
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            step += 1
            loss_sum += sum(losses)
            active_count += active
            triplet_count += len(losses)
            cursor = schedule.cursor
            record = {'step': step, 'microbatches': microbatches, 'loss': sum(losses) / len(losses),
                      'active_fraction': active / len(losses), 'rss_bytes': process.memory_info().rss,
                      'epoch': schedule.epoch, 'triplet_indices': selected}
            with (run / 'training_log.jsonl').open('a', encoding='utf-8') as log:
                log.write(json.dumps(record) + '\n')
            print(json.dumps(record), flush=True)
            save_checkpoint()
            evaluate_boundary()
        if low_memory:
            status = 'memory_reserve_stop'
        elif stopped:
            status = 'interrupted'
    except Exception:
        status = 'failed'
        raise
    finally:
        signal.signal(signal.SIGINT, previous_handler)
        seconds = elapsed + time.perf_counter() - started - session_evaluation_seconds
        unchanged = parameter_digest(model, False) == frozen
        changed = parameter_digest(model, True) != initial_train
        manifest.update(status=status, optimizer_updates=step, microbatches=microbatches,
                        training_seconds=seconds, seconds_per_update=seconds / max(1, step),
                        approximate_requested_training_seconds=seconds / max(1, step) * args.max_steps,
                        peak_observed_rss_bytes=peak, nonzero_gradient=nonzero,
                        trainable_parameters_changed=changed, frozen_parameters_unchanged=unchanged,
                        demonstrated_learning=bool(nonzero and changed))
        manifest.update(checkpoint_evaluation_seconds=evaluation_seconds, evaluated_steps=evaluated_steps,
                        completed_epochs=schedule.epoch + int(schedule.cursor == len(schedule.order)),
                        shuffle_epoch=schedule.epoch, triplet_coverage=triplet_coverage(triplets))
        manifest.update(mean_triplet_loss=loss_sum / max(1, triplet_count),
                        positive_loss_fraction=active_count / max(1, triplet_count),
                        triplet_presentations=triplet_count)
        if not unchanged:
            manifest['status'] = 'failed_frozen_parameters_changed'
        if status != 'failed':
            save_checkpoint()
            probe = encode(model, ['A reproducible embedding reload check.'], 1)
            model.save_pretrained(str(run / 'model'))
            reloaded = load_model(run / 'model', args.max_length)
            np.testing.assert_allclose(probe, encode(reloaded, ['A reproducible embedding reload check.'], 1), atol=1e-6, rtol=1e-5)
            manifest['reload_tolerance'] = {'atol': 1e-6, 'rtol': 1e-5}
            manifest['model_fingerprint'] = fingerprint(run / 'model', args.max_length)
        write_json(run / 'training_manifest.json', manifest)
        print(json.dumps(manifest, indent=2))
        if status == 'completed' and not args.checkpoint:
            checkpoint.unlink(missing_ok=True)
        if not unchanged:
            raise RuntimeError('Frozen parameters changed')


if __name__ == '__main__':
    main()
