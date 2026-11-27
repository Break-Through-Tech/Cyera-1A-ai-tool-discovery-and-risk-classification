"""Persist normalized document vectors without persisting source text."""

import io
import json
import os
import re
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np

from .catalog import digest_json


CACHE_DIR = Path(__file__).resolve().parent / ".index_cache"
FORMAT_VERSION = 1
NORMALIZATION = "float32-l2-unit-or-zero-v1"


def valid_vectors(vectors, shape: tuple[int, int]) -> bool:
    if (not isinstance(vectors, np.ndarray) or vectors.shape != shape
            or vectors.dtype != np.dtype("float32") or not np.isfinite(vectors).all()):
        return False
    norms = np.linalg.norm(vectors.astype(np.float64), axis=1)
    return bool(np.all((norms == 0) | np.isclose(norms, 1, atol=1e-6, rtol=1e-5)))


def atomic_write(path: Path, data: bytes) -> None:
    """Publish a complete file in a single rename within the same directory."""
    with NamedTemporaryFile(dir=path.parent, prefix=".writing-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


class VectorStore:
    """Each manifest points to an immutable, checksum-named vector file."""

    def __init__(self, metadata: dict, cache_dir: Path = CACHE_DIR):
        self.metadata = metadata
        self.identity = digest_json(metadata)
        self.directory = cache_dir / self.identity
        self.manifest_path = self.directory / "manifest.json"
        self.shape = (len(metadata["chunk_ids"]), metadata["embedding_dimension"])

    def load(self) -> np.ndarray | None:
        """Treat missing, corrupt, or incompatible files as cache misses."""
        try:
            manifest = json.loads(self.manifest_path.read_bytes())
            if not isinstance(manifest, dict):
                return None
            checksum = manifest.pop("vector_sha256", None)
            if manifest != self.metadata or not isinstance(checksum, str):
                return None
            if not re.fullmatch(r"[0-9a-f]{64}", checksum):
                return None
            data = (self.directory / f"{checksum}.npy").read_bytes()
            if sha256(data).hexdigest() != checksum or not data.startswith(b"\x93NUMPY"):
                return None
            vectors = np.load(io.BytesIO(data), allow_pickle=False)
            if valid_vectors(vectors, self.shape):
                return vectors
        except (OSError, ValueError, EOFError, OverflowError):
            pass
        return None

    def save(self, vectors: np.ndarray) -> None:
        if not valid_vectors(vectors, self.shape):
            raise ValueError("Invalid normalized document vectors.")
        with io.BytesIO() as buffer:
            np.save(buffer, vectors, allow_pickle=False)
            data = buffer.getvalue()
        checksum = sha256(data).hexdigest()
        manifest = self.metadata | {"vector_sha256": checksum}
        self.directory.mkdir(parents=True, exist_ok=True)
        atomic_write(self.directory / f"{checksum}.npy", data)
        atomic_write(self.manifest_path, (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode())
