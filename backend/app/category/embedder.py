"""Text embeddings with the model the neighbor index was exported with."""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

Embed = Callable[[Sequence[str]], np.ndarray]
"""Unit-normalized embeddings, one row per text."""


class LocalSentenceTransformerEmbedder:
    """Explicit experimental adapter. Training packages are imported only when selected."""

    def __init__(self, directory: Path, metadata: Mapping[str, Any], batch_size: int = 4):
        # Share fingerprint and preprocessing checks with the offline experiment.
        import sys
        from app.config import REPO_DIR
        sys.path.insert(0, str(REPO_DIR / 'notebooks/category_classification'))
        from finetuning.model import fingerprint, load_model
        if metadata.get('backend') != 'sentence_transformers_local':
            raise ValueError('Local model requires a matching experimental index')
        if (metadata.get('pooling'), metadata.get('normalized'), metadata.get('dim')) != ('cls', True, 384):
            raise ValueError('Unsupported experimental model metadata')
        length = metadata['max_length']
        if fingerprint(directory, length) != metadata['fingerprint']:
            raise ValueError('Local model fingerprint differs from neighbor index')
        import torch
        torch.set_num_threads(2)
        self._embedding = load_model(directory, length)
        self._batch_size = batch_size

    def __call__(self, texts: Sequence[str]) -> np.ndarray:
        from finetuning.model import encode
        return encode(self._embedding, texts, self._batch_size)


class FastembedEmbedder:
    """Runs the index's pinned ONNX model; the files download into ``cache_dir`` on first use."""

    def __init__(self, model: Mapping[str, Any], cache_dir: Path):
        self._model = model
        self._cache_dir = cache_dir
        self._embedding = None

    def __call__(self, texts: Sequence[str]) -> np.ndarray:
        if self._embedding is None:
            self._embedding = self._load()
        return np.array(list(self._embedding.embed(list(texts))), dtype=np.float32)

    def _load(self):
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType
        from huggingface_hub import snapshot_download

        model = self._model
        if model["pooling"] != "cls" or not model["normalized"]:
            raise ValueError("Only CLS-pooled, normalized models are supported")
        path = snapshot_download(
            model["repo"],
            revision=model["revision"],
            allow_patterns=model["files"],
            cache_dir=self._cache_dir,
        )
        name = f"{model['repo']}@{model['revision']}"
        if name.lower() not in {m["model"].lower() for m in TextEmbedding.list_supported_models()}:
            TextEmbedding.add_custom_model(
                model=name,
                pooling=PoolingType.CLS,
                normalization=True,
                sources=ModelSource(hf=model["repo"]),
                dim=model["dim"],
                model_file=next(f for f in model["files"] if f.endswith(".onnx")),
            )
        return TextEmbedding(name, specific_model_path=path)
