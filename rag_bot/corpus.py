"""Load citable passages from a fixed set of project documents."""

import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
# None allows every section of that document. Other entries use exact headings.
SOURCES = (
    ("CONTEXT.md", "project_policy", None),
    (
        "PROJECT_PLAN.md",
        "project_policy",
        (
            "Assessment unit — Confirmed",
            "Initial contextual-risk contract — Confirmed",
            "Evidence and citation-ready provenance — Confirmed",
            "Assistant retrieval and response interaction contract — Confirmed",
        ),
    ),
    (
        "docs/adr/0001-ai-tool-requires-own-ai-functionality.md",
        "project_policy",
        ("An AI Tool must show its own AI functionality",),
    ),
)

HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)\s*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


@dataclass(frozen=True)
class CatalogMetadata:
    record_id: str
    tool_id: str
    website: str
    hostname: str
    category: str
    primary_task: str
    keywords: str | None
    industry: str | None
    text_quality_flag: str
    duplicate_description_flag: str
    description_label_conflict_flag: str


@dataclass(frozen=True)
class Passage:
    passage_id: str
    source_path: str
    heading: str
    source_role: str
    content_version: str
    text: str
    catalog: CatalogMetadata | None = None


def split_sections(markdown: str) -> list[tuple[str, str]]:
    """Return heading/body pairs, ignoring heading syntax inside code fences."""
    sections = []
    heading = ""
    body = []
    open_fence = ""
    for line in markdown.splitlines():
        fence = FENCE.match(line)
        if fence:
            marker, trailing = fence.groups()
            if not open_fence:
                open_fence = marker
            elif marker.startswith(open_fence) and not trailing.strip():
                open_fence = ""
            body.append(line)
            continue

        match = HEADING.match(line) if not open_fence else None
        if match:
            sections.append((heading, "\n".join(body).strip()))
            heading = re.sub(r"[ \t]+#+$", "", match.group(1))
            body = []
        else:
            body.append(line)
    sections.append((heading, "\n".join(body).strip()))
    return [(heading, body) for heading, body in sections if heading and body]


def load_passages() -> list[Passage]:
    """Read allowlisted files and attach stable identities and content hashes."""
    passages, _ = load_documents()
    return passages


def load_documents() -> tuple[list[Passage], tuple[tuple[str, str], ...]]:
    """Load the Markdown passages and fingerprint the exact source bytes."""
    passages = []
    fingerprints = []
    for source_path, source_role, allowed_headings in SOURCES:
        path = REPO_ROOT / source_path
        if path.resolve() != path:
            raise ValueError(f"Allowlisted source must be a regular repository path: {source_path}")
        data = path.read_bytes()
        fingerprints.append((source_path, sha256(data).hexdigest()))
        sections = split_sections(data.decode("utf-8"))
        occurrences: dict[str, int] = {}
        for heading, body in sections:
            occurrences[heading] = occurrences.get(heading, 0) + 1
            if allowed_headings is not None and heading not in allowed_headings:
                continue
            identity = f"{source_path}\n{heading}\n{occurrences[heading]}"
            passages.append(
                Passage(
                    passage_id=sha256(identity.encode("utf-8")).hexdigest()[:16],
                    source_path=source_path,
                    heading=heading,
                    source_role=source_role,
                    content_version=sha256(f"{heading}\n{body}".encode("utf-8")).hexdigest(),
                    text=body,
                )
            )
        if allowed_headings is not None:
            missing = set(allowed_headings) - occurrences.keys()
            if missing:
                raise ValueError(f"Missing allowlisted headings in {source_path}: {sorted(missing)}")
    return passages, tuple(fingerprints)
