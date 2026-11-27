"""Versioned passage references for an authorized documentation snapshot."""

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from .chunking import Chunk
from .profiles import DOCS_ONLY, CorpusSnapshot


def document_id(source_path: str) -> str:
    """Identify a document by its stable, repository-relative source path."""
    return "doc-" + sha256(source_path.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PassageEvidence:
    corpus_version: str
    document_id: str
    document_version: str
    chunk_id: str
    section_passage_id: str
    source_role: Literal["project_policy"]
    excerpt: str
    source_path: str
    heading: str

    @property
    def reference(self) -> str:
        return ":".join(("passage", self.corpus_version, self.document_id,
                         self.document_version, self.chunk_id))


@dataclass(frozen=True)
class EvidenceResolution:
    status: Literal["resolved", "malformed_reference", "not_found", "version_mismatch", "unavailable"]
    evidence: PassageEvidence | None = None


_REFERENCE = re.compile(r"passage:([0-9a-f]{64}):(doc-[0-9a-f]{64}):([0-9a-f]{64}):([0-9a-f]{20})")


class EvidenceIndex:
    """Resolve exact excerpts from one immutable, authorized docs_only snapshot."""

    def __init__(self, snapshot: CorpusSnapshot, chunks: list[Chunk]):
        if snapshot.profile != DOCS_ONLY:
            raise ValueError("Evidence resolution requires docs_only.")
        self._corpus_version = snapshot.corpus_version
        self._documents = {document_id(path): version for path, version in snapshot.source_fingerprints}
        self._chunks: dict[str, PassageEvidence] = {}
        paths = dict(snapshot.source_fingerprints)
        allowed = set(snapshot.passages)
        for chunk in chunks:
            passage = chunk.passage
            if (passage not in allowed or passage.catalog is not None
                    or passage.source_role != "project_policy"):
                raise ValueError("Chunk is outside the approved documentation snapshot.")
            excerpt = chunk.text.strip()
            entry = PassageEvidence(snapshot.corpus_version, document_id(passage.source_path),
                                    paths[passage.source_path], chunk.chunk_id, passage.passage_id,
                                    "project_policy", excerpt, passage.source_path, passage.heading)
            if not excerpt or not _REFERENCE.fullmatch(entry.reference) or chunk.chunk_id in self._chunks:
                raise ValueError("Invalid or duplicate passage evidence identity.")
            self._chunks[chunk.chunk_id] = entry

    def for_chunk(self, chunk_id: str) -> PassageEvidence:
        return self._chunks[chunk_id]

    def resolve(self, reference: str) -> EvidenceResolution:
        match = _REFERENCE.fullmatch(reference) if isinstance(reference, str) else None
        if match is None:
            return EvidenceResolution("malformed_reference")
        corpus_version, document, document_version, chunk = match.groups()
        if corpus_version != self._corpus_version:
            return EvidenceResolution("version_mismatch")
        current_version = self._documents.get(document)
        if current_version is None:
            return EvidenceResolution("not_found")
        if current_version != document_version:
            return EvidenceResolution("version_mismatch")
        evidence = self._chunks.get(chunk)
        if evidence is None or evidence.document_id != document:
            return EvidenceResolution("not_found")
        return EvidenceResolution("resolved", evidence)
