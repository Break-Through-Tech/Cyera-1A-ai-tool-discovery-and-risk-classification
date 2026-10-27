"""Check whether fastembed reproduces the frozen sentence-transformers neighbor vote (ADR 0003)."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType

from evaluate import labels_of, load_splits, load_transfer, page_text


HERE = Path(__file__).resolve().parent
ST_MODEL = "BAAI/bge-small-en-v1.5"
K = 15
CUTOFF = 0.468914118995349
OFFICIAL_ONNX = "bge-small-en-v1.5-official-onnx"


def st_cached(texts: list[str]) -> np.ndarray:
    """The sentence-transformers embeddings the experiment cached (same key as ``methods.embed``)."""
    key = hashlib.sha256(json.dumps([ST_MODEL, texts], ensure_ascii=False).encode()).hexdigest()[:20]
    return np.load(HERE / "cache" / f"embed_{key}.npy")


def vote(query: np.ndarray, train: np.ndarray, onehot: np.ndarray) -> np.ndarray:
    similarity = query @ train.T
    nearest = np.argpartition(-similarity, K, axis=1)[:, :K]
    weights = np.clip(np.take_along_axis(similarity, nearest, axis=1), 0, None)
    votes = np.einsum("rk,rkl->rl", weights, onehot[nearest])
    return votes / np.maximum(votes.sum(axis=1, keepdims=True), 1e-9)


def main() -> None:
    TextEmbedding.add_custom_model(
        model=OFFICIAL_ONNX, pooling=PoolingType.CLS, normalization=True,
        sources=ModelSource(hf=ST_MODEL), dim=384, model_file="onnx/model.onnx",
    )
    splits = load_splits()
    labels = labels_of(splits["train"])
    train_text = [row["description_text"] for row in splits["train"]]
    onehot = np.eye(len(labels))[[labels.index(row["category"]) for row in splits["train"]]]
    pages = load_transfer("validation")
    sets = {
        "validation_descriptions": ([row["description_text"] for row in splits["validation"]],
                                    [row["category"] for row in splits["validation"]]),
        "validation_pages[full]": ([page_text(page, "full") for page in pages], [page["category"] for page in pages]),
    }
    reference = {name: vote(st_cached(texts), st_cached(train_text), onehot) for name, (texts, _) in sets.items()}

    for variant in (ST_MODEL, OFFICIAL_ONNX):
        model = TextEmbedding(variant)
        encode = lambda texts: np.array(list(model.embed(texts, batch_size=64)))
        started = time.perf_counter()
        train = encode(train_text)
        print(f"\n== {variant}: train index {time.perf_counter() - started:.0f}s; "
              f"cosine to sentence-transformers {np.mean(np.sum(train * st_cached(train_text), axis=1)):.5f}")
        started = time.perf_counter()
        encode([sets["validation_pages[full]"][0][0]])
        print(f"one homepage: {1000 * (time.perf_counter() - started):.0f} ms")
        for name, (texts, expected) in sets.items():
            scores, ref = vote(encode(texts), train, onehot), reference[name]
            predicted = np.array(labels)[scores.argmax(1)]
            ref_predicted = np.array(labels)[ref.argmax(1)]
            kept, ref_kept = scores.max(1) >= CUTOFF, ref.max(1) >= CUTOFF
            print(f"{name:<24} acc {np.mean(predicted == expected):.3f} (ref {np.mean(ref_predicted == expected):.3f})  "
                  f"same Category {np.mean(predicted == ref_predicted):.3f}  "
                  f"same abstention {np.mean(kept == ref_kept):.3f}  "
                  f"answered {kept.mean():.3f}/acc {np.mean(predicted[kept] == np.array(expected)[kept]):.3f} "
                  f"(ref {ref_kept.mean():.3f}/{np.mean(ref_predicted[ref_kept] == np.array(expected)[ref_kept]):.3f})")


if __name__ == "__main__":
    main()
