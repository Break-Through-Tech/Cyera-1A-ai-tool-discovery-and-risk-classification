import re

_RESERVED_SUFFIXES = (
    "example",
    "test",
    "invalid",
    "localhost",
    "local",
    "internal",
    "example.com",
    "example.net",
    "example.org",
)
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def normalize_domain(raw: str) -> str:
    domain = raw.strip().lower().rstrip(".")
    return domain.removeprefix("www.")


def is_public_hostname(domain: str) -> bool:
    """A syntactically valid DNS name outside reserved and local-only namespaces.

    IP addresses are not hostnames: the final label must be alphabetic (or IDNA).
    """
    labels = domain.split(".")
    if len(domain) > 253 or len(labels) < 2:
        return False
    if not all(_LABEL.fullmatch(label) for label in labels):
        return False
    top = labels[-1]
    if not (top.isalpha() or top.startswith("xn--")):
        return False
    return not any(
        domain == suffix or domain.endswith(f".{suffix}") for suffix in _RESERVED_SUFFIXES
    )
