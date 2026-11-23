from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from app.evidence import EvidenceReference, EvidenceSources, ResolvedEvidence, resolve_evidence
from app.pipeline.identity import load_tool_metadata

router = APIRouter(tags=["evidence"])


class ResolveRequest(BaseModel):
    """One typed reference; aggregate references are rejected toward their listing operation."""

    model_config = ConfigDict(extra="forbid")
    reference: EvidenceReference


@router.post("/evidence/resolve")
def resolve(request: Request, body: ResolveRequest) -> ResolvedEvidence:
    """Read-only despite POST: open the stored source behind one Evidence reference."""
    with request.app.state.engine.connect() as connection:
        return resolve_evidence(connection, body.reference, _sources(request))


def _sources(request: Request) -> EvidenceSources:
    """Loaded once per app; the Tool metadata snapshot is versioned against each Run."""
    state = request.app.state
    if getattr(state, "evidence_sources", None) is None:
        path = state.settings.tool_metadata_path
        state.evidence_sources = EvidenceSources(
            tool_metadata=load_tool_metadata(path) if path.is_file() else None
        )
    return state.evidence_sources
