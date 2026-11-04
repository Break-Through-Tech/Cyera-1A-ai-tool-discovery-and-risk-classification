"""The Semantic Neighbor index for Category Classification (ADR 0003)."""

import csv
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.config import display_path


@dataclass(frozen=True)
class CatalogTool:
    tool_id: str
    name: str
    category: str


@dataclass(frozen=True)
class Neighbor:
    tool_id: str
    name: str
    category: str
    similarity: float


@dataclass(frozen=True)
class NeighborVote:
    category: str
    share: float
    neighbors: tuple[Neighbor, ...]


@dataclass(frozen=True)
class NeighborIndex:
    """Unit-normalized catalog embeddings, one row per catalog Tool."""

    embeddings: np.ndarray
    tools: tuple[CatalogTool, ...]
    version: str
    model: Mapping[str, Any]

    def vote(self, vector: np.ndarray, k: int) -> NeighborVote:
        """The k most similar Tools, each voting for its Category with its (non-negative) similarity."""
        similarity = self.embeddings @ vector
        nearest = np.argsort(-similarity, kind="stable")[:k]
        neighbors = tuple(
            Neighbor(self.tools[i].tool_id, self.tools[i].name, self.tools[i].category, float(similarity[i]))
            for i in nearest
        )
        votes: dict[str, float] = {}
        for neighbor in neighbors:
            votes[neighbor.category] = votes.get(neighbor.category, 0.0) + max(neighbor.similarity, 0.0)
        total = sum(votes.values())
        category = max(sorted(votes), key=lambda c: votes[c])
        return NeighborVote(category, votes[category] / total if total else 0.0, neighbors)


def load_neighbor_index(directory: Path) -> NeighborIndex:
    """Load an exported index. A changed index is exported to a new folder, so the version names the folder."""
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    model = manifest['model']
    if model.get('backend') == 'sentence_transformers_local':
        import hashlib
        for name, key in (('tools.csv', 'tools_sha256'), ('embeddings.npy', 'embeddings_sha256')):
            digest = hashlib.sha256((directory / name).read_bytes()).hexdigest()
            if digest != manifest[key]:
                raise ValueError(f'Experimental index {name} content changed')
        if manifest.get('classification') != {'k': 15, 'cutoff': 0.468914118995349}:
            raise ValueError('Experimental index k/cutoff differs from classifier configuration')
    embeddings = np.load(directory / "embeddings.npy")
    with (directory / "tools.csv").open(encoding="utf-8", newline="") as stream:
        tools = tuple(CatalogTool(r["tool_id"], r["name"], r["category"]) for r in csv.DictReader(stream))
    if embeddings.ndim != 2 or len(embeddings) != len(tools):
        raise ValueError(f"Neighbor index has {len(embeddings)} embedding rows for {len(tools)} Tools")
    if embeddings.shape[1] != model["dim"]:
        raise ValueError(f"Neighbor index embedding dimension {embeddings.shape[1]} is not {model['dim']}")
    if model.get('backend') == 'sentence_transformers_local':
        if not np.isfinite(embeddings).all() or not np.allclose(np.linalg.norm(embeddings, axis=1), 1, atol=1e-5):
            raise ValueError('Experimental index vectors must be finite and unit normalized')
    version = f"{display_path(directory)};tools={len(tools)};model={model['repo']}@{model['revision'][:7]}"
    return NeighborIndex(embeddings, tools, version, model)
