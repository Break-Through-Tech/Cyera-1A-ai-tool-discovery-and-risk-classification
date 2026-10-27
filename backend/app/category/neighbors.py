"""The Semantic Neighbor index for Category Classification (ADR 0003)."""

import csv
import hashlib
import io
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


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
    version: str = "unversioned"
    model: Mapping[str, Any] = field(default_factory=dict)

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
    """Load the exported index; its version hashes the vectors, the Tools and the embedding model revision."""
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    vectors = (directory / "embeddings.npy").read_bytes()
    listing = (directory / "tools.csv").read_bytes()
    embeddings = np.load(io.BytesIO(vectors))
    tools = tuple(
        CatalogTool(r["tool_id"], r["name"], r["category"])
        for r in csv.DictReader(io.StringIO(listing.decode("utf-8")))
    )
    if embeddings.ndim != 2 or len(embeddings) != len(tools):
        raise ValueError(f"Neighbor index has {len(embeddings)} embedding rows for {len(tools)} Tools")
    if embeddings.shape[1] != manifest["model"]["dim"]:
        raise ValueError(
            f"Neighbor index embedding dimension {embeddings.shape[1]} is not {manifest['model']['dim']}"
        )
    model = f"{manifest['model']['repo']}@{manifest['model']['revision']}".encode()
    digest = hashlib.sha256(vectors + b"\0" + listing + b"\0" + model).hexdigest()
    return NeighborIndex(embeddings, tools, f"sha256:{digest}", manifest["model"])
