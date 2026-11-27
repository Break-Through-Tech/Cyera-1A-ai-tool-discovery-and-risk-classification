"""Versioned corpus profiles and local catalog eligibility rules."""

import csv
from dataclasses import dataclass
from hashlib import sha256

from .catalog import TOOL_ID, digest_json, load_catalog
from .corpus import REPO_ROOT, Passage, load_documents


DOCS_ONLY = "docs_only"
CATALOG_DEV = "catalog_dev"
CATALOG_UNSEEN_EVAL = "catalog_unseen_eval"
PROFILE_NAMES = (DOCS_ONLY, CATALOG_DEV, CATALOG_UNSEEN_EVAL)
CATALOG_PATH = "data/aitoolbuzz-com-16k-ai-tools-database/ai_tools_cleaned.csv"
DOCS_POLICY_VERSION = "docs-allowlist-v1"
CATALOG_POLICY_VERSION = "catalog-development-v1"
# Set to a reviewed permission reference only after approval for this local use.
CATALOG_REUSE_REFERENCE: str | None = None
REVIEWED_IDENTITY_EXCLUSIONS: tuple[tuple[str, str], ...] = ()
# Cross-checked against the fixture partition contract and known-Tool registry exclusions.
FIXTURE_HOLDOUTS = {
    "227949d3a6ca2fc955ca573c724b1f93a59a41832a1778524d85b2a0d4b98cf9": "MeetOscar",
    "eae7b946239074e028ddaec2c04a8fcab433fabbab5d951046213b91de76b8d8": "Magic Inspector",
}
DEV_NOTICE = ("Local development only. Ineligible for unseen-Tool evaluation or Gemini. "
              "Same-Tool aliases and related domains remain incompletely reviewed.")
EVAL_DISABLED = ("catalog_unseen_eval is disabled. The binary v4 manifest checksum differs "
                 "from the fixture pin, and alias and identity review is incomplete.")


class ProfileError(ValueError):
    """The requested profile could not be activated."""


@dataclass(frozen=True)
class Exclusion:
    tool_id: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CorpusSnapshot:
    profile: str
    passages: tuple[Passage, ...]
    source_fingerprints: tuple[tuple[str, str], ...]
    eligibility_policy_version: str
    corpus_version: str
    exclusions: tuple[Exclusion, ...] = ()
    notices: tuple[str, ...] = ()

    @property
    def source_roles(self) -> tuple[str, ...]:
        return tuple(sorted({p.source_role for p in self.passages}))


def require_profile(profile: str) -> None:
    """Enforce the current profile and catalog permission gates."""
    if profile == CATALOG_UNSEEN_EVAL:
        raise ProfileError(EVAL_DISABLED)
    if profile not in PROFILE_NAMES:
        raise ProfileError("Unknown corpus profile.")
    if profile == CATALOG_DEV and not (CATALOG_REUSE_REFERENCE or "").strip():
        raise ProfileError(f"catalog_dev requires confirmed catalog reuse permission. {DEV_NOTICE}")

def load_snapshot(profile: str = DOCS_ONLY) -> CorpusSnapshot:
    """Activate a profile only after checking its access and reuse policy."""
    require_profile(profile)
    docs, fingerprints = load_documents()
    passages = tuple(docs)
    policy = DOCS_POLICY_VERSION
    exclusions = ()
    notices = ()
    controls = None
    if profile == CATALOG_DEV:
        path = REPO_ROOT / CATALOG_PATH
        if path.resolve() != path:
            raise ProfileError("Catalog source must be the configured repository file.")
        data = path.read_bytes()
        try:
            catalog = load_catalog(data, CATALOG_PATH)
        except csv.Error:
            raise ProfileError("Invalid cleaned catalog CSV.") from None
        eligible, exclusions = select_catalog(catalog)
        passages += eligible
        fingerprints += ((CATALOG_PATH, sha256(data).hexdigest()),)
        policy = CATALOG_POLICY_VERSION
        notices = (DEV_NOTICE,)
        controls = (FIXTURE_HOLDOUTS, sorted(REVIEWED_IDENTITY_EXCLUSIONS))

    version = digest_json([
        profile, policy, fingerprints, controls,
        [(p.passage_id, p.source_role, p.content_version) for p in passages],
    ])
    return CorpusSnapshot(profile, passages, fingerprints, policy, version, exclusions, notices)


def select_catalog(catalog: tuple[Passage, ...]) -> tuple[tuple[Passage, ...], tuple[Exclusion, ...]]:
    """Record all applicable exclusion reasons, leaving distinct listings intact."""
    reviewed = {}
    for tool_id, reason in REVIEWED_IDENTITY_EXCLUSIONS:
        if not TOOL_ID.fullmatch(tool_id) or not reason.strip() or tool_id in reviewed:
            raise ProfileError("Invalid reviewed identity exclusion configuration.")
        reviewed[tool_id] = reason
    eligible, exclusions = [], []
    for passage in catalog:
        record = passage.catalog
        if record is None or passage.source_role != "tool_evidence":
            raise ProfileError("Catalog eligibility requires catalog evidence.")
        reasons = []
        if record.tool_id in FIXTURE_HOLDOUTS:
            reasons.append(f"fixture_holdout: {FIXTURE_HOLDOUTS[record.tool_id]}")
        if record.description_label_conflict_flag == "review_label_conflict":
            reasons.append("description_category_conflict")
        if record.tool_id in reviewed:
            reasons.append(f"reviewed_identity_exclusion: {reviewed[record.tool_id]}")
        if reasons:
            exclusions.append(Exclusion(record.tool_id, tuple(reasons)))
        else:
            eligible.append(passage)
    return tuple(eligible), tuple(exclusions)
