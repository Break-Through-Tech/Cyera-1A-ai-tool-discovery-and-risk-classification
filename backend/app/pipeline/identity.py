"""Identity Resolution: group Activity Events into Tool Candidates and resolve each one.

Outcomes are a known Tool, a Batch-stable observed Tool, or an unresolved Tool Candidate.
They say nothing about AI status.
"""

import csv
import hashlib
import io
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from app.config import REPO_DIR
from app.hostnames import is_public_hostname, normalize_domain


@dataclass(frozen=True)
class CatalogListing:
    tool_id: str
    name: str
    website: str
    category: str = ""


@dataclass(frozen=True)
class KnownToolRegistry:
    """Known Tools reachable by exact domain: only listings whose website is a site root.

    A listing for a deeper page (a feature or blog URL) does not identify every product
    on its host, so it never maps a bare domain.
    """

    root_listings_by_domain: Mapping[str, tuple[CatalogListing, ...]]
    version: str = "unversioned"

    @classmethod
    def from_listings(
        cls,
        listings: Iterable[CatalogListing],
        excluded_tool_ids: set[str],
        version: str = "unversioned",
    ) -> "KnownToolRegistry":
        by_domain: dict[str, list[CatalogListing]] = {}
        for listing in listings:
            if listing.tool_id in excluded_tool_ids:
                continue
            url = urlsplit(listing.website.strip())
            if url.path not in ("", "/") or not url.hostname:
                continue
            by_domain.setdefault(normalize_domain(url.hostname), []).append(listing)
        return cls(
            {domain: tuple(found) for domain, found in by_domain.items()}, version
        )

    @property
    def catalog_categories(self) -> Mapping[str, str]:
        """Catalog Category by tool ID for every listing a Known Tool can resolve to."""
        return {
            listing.tool_id: listing.category
            for listings in self.root_listings_by_domain.values()
            for listing in listings
        }


@dataclass(frozen=True)
class ToolMetadataSnapshot:
    """Supplied Tool metadata (Dataset B); a row identifies a Tool by exact domain and name."""

    rows: Sequence[Mapping[str, str]]
    version: str = "unversioned"

    def match(self, domain: str, name: str) -> str | None:
        row = self.find(domain, name)
        return row["metadata_id"] if row else None

    def find(self, domain: str, name: str) -> Mapping[str, str] | None:
        for row in self.rows:
            if (
                normalize_domain(row["domain"]) == domain
                and normalize_name(row["application_name"]) == name
            ):
                return row
        return None


def load_registry(catalog_path: Path, exclusions_path: Path) -> KnownToolRegistry:
    """Build the registry from the cleaned catalog minus held-out Tools.

    Its version hashes both files, so changing either one produces a new registry version.
    """
    catalog = catalog_path.read_bytes()
    exclusions = exclusions_path.read_bytes()
    excluded = set(json.loads(exclusions)["excluded_tool_ids"])
    listings = [
        CatalogListing(row["tool_id"], row["Name"], row["Website"], row["Category"])
        for row in csv.DictReader(io.StringIO(catalog.decode("utf-8")))
    ]
    digest = hashlib.sha256(catalog + b"\0" + exclusions).hexdigest()
    return KnownToolRegistry.from_listings(listings, excluded, f"sha256:{digest}")


def load_tool_metadata(path: Path) -> ToolMetadataSnapshot:
    content = path.read_bytes()
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8"))))
    return ToolMetadataSnapshot(
        rows, f"{_display_path(path)}@sha256:{hashlib.sha256(content).hexdigest()}"
    )


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    if resolved.is_relative_to(REPO_DIR):
        return resolved.relative_to(REPO_DIR).as_posix()
    return resolved.as_posix()


@dataclass(frozen=True)
class CandidateIdentity:
    domain: str
    application_names: tuple[str, ...]
    event_ids: tuple[str, ...]
    outcome: str
    tool_id: str | None = None
    basis: str | None = None
    reason: str | None = None
    catalog_tool_ids: tuple[str, ...] = field(default=())
    metadata_id: str | None = None


def resolve_identities(
    batch_id: str,
    events: Iterable[Mapping[str, str]],
    registry: KnownToolRegistry,
    metadata: ToolMetadataSnapshot,
) -> list[CandidateIdentity]:
    groups: dict[tuple[str, str], list[Mapping[str, str]]] = {}
    for event in events:
        key = (normalize_domain(event["domain"]), normalize_name(event["application_name"]))
        groups.setdefault(key, []).append(event)

    return [
        _resolve(batch_id, domain, name, grouped, registry, metadata)
        for (domain, name), grouped in sorted(groups.items())
    ]


def _resolve(
    batch_id: str,
    domain: str,
    name: str,
    events: list[Mapping[str, str]],
    registry: KnownToolRegistry,
    metadata: ToolMetadataSnapshot,
) -> CandidateIdentity:
    clues = {
        "domain": domain,
        "application_names": tuple(dict.fromkeys(e["application_name"] for e in events)),
        "event_ids": tuple(e["event_id"] for e in events),
    }
    matches = registry.root_listings_by_domain.get(domain, ())
    if len(matches) == 1:
        return CandidateIdentity(
            **clues,
            outcome="known_tool",
            tool_id=f"aitoolbuzz:{matches[0].tool_id}",
            basis="exact_root_domain",
            catalog_tool_ids=(matches[0].tool_id,),
        )
    if matches:
        return CandidateIdentity(
            **clues,
            outcome="unresolved_candidate",
            reason="ambiguous_known_match",
            catalog_tool_ids=tuple(m.tool_id for m in matches),
        )
    metadata_id = metadata.match(domain, name)
    if metadata_id is not None:
        return CandidateIdentity(
            **clues,
            outcome="observed_tool",
            tool_id=_observed_tool_id(batch_id, domain, name),
            basis="tool_metadata_match",
            metadata_id=metadata_id,
        )
    if is_public_hostname(domain):
        return CandidateIdentity(
            **clues,
            outcome="observed_tool",
            tool_id=_observed_tool_id(batch_id, domain, name),
            basis="public_hostname",
        )
    return CandidateIdentity(
        **clues, outcome="unresolved_candidate", reason="insufficient_identity_evidence"
    )


def _observed_tool_id(batch_id: str, domain: str, name: str) -> str:
    digest = hashlib.sha256(f"{batch_id}\n{domain}\n{name}".encode()).hexdigest()
    return f"observed:{digest[:24]}"


def normalize_name(raw: str) -> str:
    return " ".join(raw.split()).casefold()
