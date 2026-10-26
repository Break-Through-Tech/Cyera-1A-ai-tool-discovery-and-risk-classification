"""Category methods. Each returns a rows x labels score matrix in ``labels`` order."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

from category_descriptions import CATEGORY_DESCRIPTIONS

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ai_cascade"))
import jev_judge  # noqa: E402

CACHE = HERE / "cache"
SEED = 20261014
EMBEDDERS = ("sentence-transformers/all-MiniLM-L6-v2", "BAAI/bge-small-en-v1.5")
JEV_MODEL = "jev-1.14.0"
JEV_INSTRUCTIONS = ("Using only this text, which category best describes what this AI tool does for its users? "
                    "Do not use outside knowledge of the company.")
JEV_COST_PER_REQUEST = 0.00004


def tfidf_lr(train_text: list[str], train_labels: list[str], labels: list[str], *, c: float,
             class_weight: str | None):
    model = make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), min_df=2),
        LogisticRegression(C=c, class_weight=class_weight, max_iter=2000, random_state=SEED),
    )
    model.fit(train_text, train_labels)
    if list(model.classes_) != labels:
        raise ValueError("Classifier label order differs")
    return model.predict_proba


_encoders: dict = {}


def embed(name: str, texts: list[str]) -> np.ndarray:
    """Unit-normalized embeddings, cached on disk by model and exact text list."""
    key = hashlib.sha256(json.dumps([name, texts], ensure_ascii=False).encode()).hexdigest()[:20]
    path = CACHE / f"embed_{key}.npy"
    if path.exists():
        return np.load(path)
    if name not in _encoders:
        from sentence_transformers import SentenceTransformer
        _encoders[name] = SentenceTransformer(name, device="cpu")
    vectors = _encoders[name].encode(texts, normalize_embeddings=True, batch_size=64)
    CACHE.mkdir(exist_ok=True)
    np.save(path, vectors)
    return vectors


def zero_shot(name: str, labels: list[str]):
    categories = embed(name, [f"{label}: {CATEGORY_DESCRIPTIONS[label]}" for label in labels])
    return lambda texts: embed(name, texts) @ categories.T


def knn(name: str, train_text: list[str], train_labels: list[str], labels: list[str], *, k: int):
    """Similarity-weighted vote share of the k nearest train Tools."""
    train = embed(name, train_text)
    onehot = np.eye(len(labels))[[labels.index(label) for label in train_labels]]

    def scores(texts: list[str]) -> np.ndarray:
        similarity = embed(name, texts) @ train.T
        nearest = np.argpartition(-similarity, k, axis=1)[:, :k]
        weights = np.clip(np.take_along_axis(similarity, nearest, axis=1), 0, None)
        votes = np.einsum("rk,rkl->rl", weights, onehot[nearest])
        return votes / np.maximum(votes.sum(axis=1, keepdims=True), 1e-9)

    return scores


def embed_lr(name: str, train_text: list[str], train_labels: list[str], labels: list[str], *, c: float,
             class_weight: str | None):
    model = LogisticRegression(C=c, class_weight=class_weight, max_iter=2000, random_state=SEED)
    model.fit(embed(name, train_text), train_labels)
    if list(model.classes_) != labels:
        raise ValueError("Classifier label order differs")
    return lambda texts: model.predict_proba(embed(name, texts))


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_")


def jev_body(state: dict, labels: list[str]) -> dict:
    criteria = {_slug(label): f"{label}. {CATEGORY_DESCRIPTIONS[label]}" for label in labels}
    return {"model": JEV_MODEL, "state": state,
            "questions": {"category": {"type": "choice", "criteria": criteria, "instructions": JEV_INSTRUCTIONS}}}


def description_state(text: str) -> dict:
    return {"description": text}


def page_state(page: dict) -> dict:
    """The same homepage state the AI Determination judge sends."""
    return {"title": page["title"], "meta_description": page["meta_description"], "headings": page["headings"],
            "page_text": page["body"][:jev_judge.FULL_TEXT_CHARS]}


def jev(states: list[dict], labels: list[str]) -> tuple[np.ndarray, float, float]:
    """Choice probabilities, total cost of uncached requests, and their wall-clock seconds."""
    path = CACHE / "jev_cache.json"
    cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    bodies = [jev_body(state, labels) for state in states]
    todo = {jev_judge.request_id(body): body for body in bodies if jev_judge.request_id(body) not in cache}
    started = time.perf_counter()
    with ThreadPoolExecutor(jev_judge.WORKERS) as pool:
        for rid, result in zip(todo, pool.map(jev_judge._call, todo.values())):
            if result["model"] != JEV_MODEL:
                raise ValueError(f"Jev answered with {result['model']}")
            cache[rid] = {"model": result["model"], "answers": result["answers"], "usage": result["usage"]}
    seconds = time.perf_counter() - started
    if todo:
        CACHE.mkdir(exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False) + "\n", encoding="utf-8")
    slugs = [_slug(label) for label in labels]
    scores = np.array([[cache[jev_judge.request_id(body)]["answers"]["category"]["probabilities"][slug]
                        for slug in slugs] for body in bodies])
    return scores, len(todo) * JEV_COST_PER_REQUEST, seconds
