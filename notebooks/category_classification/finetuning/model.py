"""Explicit PyTorch model loading, content fingerprints and inference."""
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path

from .data import MODEL, REVISION, sha256


def fingerprint(directory, max_length):
    directory = Path(directory)
    files = [(p.relative_to(directory).as_posix(), sha256(p))
             for p in sorted(directory.rglob('*')) if p.is_file()]
    if not files:
        raise ValueError('Model directory is empty')
    config = {'files': files, 'max_length': max_length, 'pooling': 'cls',
              'normalized': True, 'dim': 384, 'text': 'unmodified'}
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def load_model(path=None, max_length=128):
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(str(path) if path else MODEL, device='cpu', backend='torch',
                                **({} if path else {'revision': REVISION}))
    model.float()
    model.max_seq_length = max_length
    pools = [m for m in model.modules() if type(m).__name__ == 'Pooling']
    if len(pools) != 1 or not pools[0].pooling_mode_cls_token or any(
        getattr(pools[0], 'pooling_mode_' + mode, False)
        for mode in ('mean_tokens', 'max_tokens', 'mean_sqrt_len_tokens', 'weightedmean_tokens', 'lasttoken')
    ) or model.get_sentence_embedding_dimension() != 384:
        raise ValueError('Expected CLS-only pooling with 384 output dimensions')
    return model


def final_block(model):
    """Deliberately restrict training to the verified BERT architecture used by BGE."""
    encoder = model[0].auto_model
    if encoder.config.model_type != 'bert' or not hasattr(encoder.encoder, 'layer'):
        raise ValueError('Expected BERT encoder.layer; cannot safely identify final block')
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    block = encoder.encoder.layer[-1]
    for parameter in block.parameters():
        parameter.requires_grad_(True)
    model.eval()
    block.train()
    return block


def parameter_digest(model, trainable):
    digest = hashlib.sha256()
    for name, parameter in model.named_parameters():
        if parameter.requires_grad == trainable:
            digest.update(name.encode())
            digest.update(parameter.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def cosine_triplet_loss(anchor, positive, negative, margin=0.1):
    import torch.nn.functional as F
    anchor, positive, negative = [F.normalize(x, p=2, dim=-1) for x in (anchor, positive, negative)]
    return ((anchor * negative).sum(-1) - (anchor * positive).sum(-1) + margin).clamp_min(0)


def encode(model, texts, batch_size=4):
    import numpy as np
    import torch
    model.eval()
    with torch.inference_mode():
        vectors = model.encode(list(texts), batch_size=batch_size, normalize_embeddings=True,
                               convert_to_numpy=True, show_progress_bar=False)
    vectors = np.asarray(vectors, dtype=np.float32)
    validate_vectors(vectors)
    return vectors


def validate_vectors(vectors):
    import numpy as np
    if vectors.ndim != 2 or vectors.shape[1] != 384 or not np.isfinite(vectors).all():
        raise ValueError('Expected finite rows of 384 dimensions')
    if not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5):
        raise ValueError('Embeddings must be unit normalized (atol=1e-5)')


def run_metadata(run):
    manifest = json.loads((run / 'training_manifest.json').read_text(encoding='utf-8'))
    if manifest['status'] not in ('completed', 'interrupted', 'memory_reserve_stop') or not manifest.get('model_fingerprint'):
        raise ValueError('Run has no successfully saved candidate model')
    length = manifest['settings']['max_length']
    if fingerprint(run / 'model', length) != manifest['model_fingerprint']:
        raise ValueError('Saved model contents/preprocessing differ from training manifest')
    return manifest


@contextmanager
def preserve_training_state(model):
    """Inference must not leave an in-progress encoder in eval mode or consume its RNG."""
    import torch
    modes = [(module, module.training) for module in model.modules()]
    rng = torch.get_rng_state()
    try:
        yield
    finally:
        for module, training in modes:
            module.training = training
        torch.set_rng_state(rng)


def encoder_fingerprint(model, *, legacy_tokenizer_state=False):
    """Hash actual checkpoint tensors, tokenizer and preprocessing, independent of path."""
    digest = hashlib.sha256()
    for name, tensor in model.state_dict().items():
        digest.update(name.encode())
        digest.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    tokenizer = model.tokenizer.backend_tokenizer.to_str()
    if not legacy_tokenizer_state:
        tokenizer_config = json.loads(tokenizer)
        # These are mutable last-call settings. max_seq_length and dynamic padding
        # are explicitly applied by Sentence Transformers, including after resume.
        tokenizer_config.pop('padding', None)
        tokenizer_config.pop('truncation', None)
        tokenizer = json.dumps(tokenizer_config, sort_keys=True)
    digest.update(tokenizer.encode())
    digest.update(json.dumps({'max_length': model.max_seq_length, 'pooling': 'cls',
                              'normalized': True, 'dim': 384, 'precision': 'float32',
                              'text_preparation': 'unmodified-v1'}, sort_keys=True).encode())
    return digest.hexdigest()


def cached_encode(model, texts, batch_size=4, cache=None, checkpoint=None):
    """Inference-only cache, verified by content and exact ordered input texts."""
    import numpy as np
    from .data import ROOT, write_json
    cache = Path(cache) if cache else ROOT / '.cache-training/experiment-embeddings'
    checkpoint = checkpoint or encoder_fingerprint(model)
    key = hashlib.sha256(json.dumps([checkpoint, list(texts)], ensure_ascii=False).encode()).hexdigest()
    path = cache / f'{key}.npy'
    metadata = path.with_suffix('.json')
    if not path.exists() and hasattr(model, 'tokenizer'):
        legacy = encoder_fingerprint(model, legacy_tokenizer_state=True)
        legacy_key = hashlib.sha256(json.dumps([legacy, list(texts)], ensure_ascii=False).encode()).hexdigest()
        legacy_path = cache / f'{legacy_key}.npy'
        legacy_metadata = legacy_path.with_suffix('.json')
        if legacy != checkpoint and legacy_path.exists() and legacy_metadata.exists() and checkpoint == encoder_fingerprint(model):
            info = json.loads(legacy_metadata.read_text(encoding='utf-8'))
            if info['checkpoint'] != legacy or info['sha256'] != sha256(legacy_path):
                raise ValueError('Legacy embedding cache content changed')
            vectors = np.load(legacy_path, allow_pickle=False)
            validate_vectors(vectors)
            if len(vectors) != len(texts):
                raise ValueError('Legacy cache row count changed')
            np.save(path, vectors)
            write_json(metadata, {'checkpoint': checkpoint, 'sha256': sha256(path),
                                  'rows': len(texts), 'migrated_from': legacy})
    if path.exists() and metadata.exists():
        info = json.loads(metadata.read_text(encoding='utf-8'))
        if info['sha256'] != sha256(path) or info['checkpoint'] != checkpoint:
            raise ValueError('Embedding cache content/fingerprint changed')
        vectors = np.load(path, allow_pickle=False)
        validate_vectors(vectors)
        if len(vectors) != len(texts):
            raise ValueError('Embedding cache row count changed')
        return vectors
    with preserve_training_state(model):
        vectors = encode(model, texts, batch_size)
    cache.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    with temp.open('wb') as stream:
        np.save(stream, vectors)
    temp.replace(path)
    write_json(metadata, {'checkpoint': checkpoint, 'sha256': sha256(path), 'rows': len(texts)})
    return vectors
