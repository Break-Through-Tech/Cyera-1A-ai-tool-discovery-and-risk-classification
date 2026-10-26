"""Bounded fetch of one observed Tool's public homepage.

Expected acquisition limits become a recorded ``Capture.outcome``, never an exception:
they leave the AI Determination to abstain rather than failing the Analysis Run.
"""

from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import Protocol
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from app.clock import utc_now
from app.enrichment.destinations import Blocked, Destination, Resolver, check_destination
from app.enrichment.extract import extract_page

MAX_REDIRECTS = 3
MAX_ROBOTS_REDIRECTS = 5
MAX_FETCHES_PER_RUN = 50
FETCH_WORKERS = 4
_REDIRECT_STATUSES = (301, 302, 303, 307, 308)
USER_AGENT_TOKEN = "CyeraToolGovernancePrototype"
USER_AGENT = f"{USER_AGENT_TOKEN}/0.1 (public product-page metadata for governance research)"


@dataclass(frozen=True)
class HttpResponse:
    status: int
    content_type: str
    location: str | None
    body: bytes


class FetchError(Exception):
    """The request did not complete: timeout, connection or TLS failure."""


class ResponseTooLarge(Exception):
    pass


class HttpClient(Protocol):
    def get(self, destination: Destination) -> HttpResponse:
        """One request with no automatic redirects, connecting only to the checked addresses."""


@dataclass(frozen=True)
class Capture:
    requested_url: str
    captured_at: str
    outcome: str
    detail: str | None = None
    final_url: str | None = None
    title: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    headings: tuple[str, ...] = ()
    main_text: str = ""


def fetch_homepages(
    domains: Iterable[str],
    http: HttpClient,
    resolve: Resolver,
    max_fetches: int = MAX_FETCHES_PER_RUN,
    workers: int = FETCH_WORKERS,
) -> dict[str, Capture]:
    """One capture per distinct domain; domains past the budget (in sorted order) are not fetched."""
    ordered = sorted(set(domains))
    allowed, skipped = ordered[:max_fetches], ordered[max_fetches:]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        fetched = pool.map(lambda domain: fetch_homepage(domain, http, resolve), allowed)
        captures = dict(zip(allowed, fetched))
    for domain in skipped:
        captures[domain] = Capture(f"https://{domain}/", utc_now(), "fetch_budget_exhausted")
    return captures


def fetch_homepage(domain: str, http: HttpClient, resolve: Resolver) -> Capture:
    requested_url = f"https://{domain}/"
    try:
        return _follow(requested_url, http, resolve)
    except ResponseTooLarge:
        return Capture(requested_url, utc_now(), "too_large")
    except FetchError as error:
        return Capture(requested_url, utc_now(), "fetch_failed", str(error) or None)


def _follow(requested_url: str, http: HttpClient, resolve: Resolver) -> Capture:
    url = requested_url
    robots_by_host: dict[str, RobotFileParser | str] = {}
    for _hop in range(MAX_REDIRECTS + 1):
        destination = check_destination(url, resolve)
        if isinstance(destination, Blocked):
            return Capture(requested_url, utc_now(), "blocked_destination", destination.reason)

        if destination.host not in robots_by_host:
            robots_by_host[destination.host] = _read_robots(destination, http, resolve)
        rules = robots_by_host[destination.host]
        if isinstance(rules, str):
            return Capture(requested_url, utc_now(), "robots_unavailable", rules)
        if not rules.can_fetch(USER_AGENT_TOKEN, destination.url):
            return Capture(requested_url, utc_now(), "robots_disallowed")

        response = http.get(destination)
        if response.status in _REDIRECT_STATUSES and response.location:
            url = urljoin(destination.url, response.location)
            continue
        if response.status != 200:
            return Capture(
                requested_url, utc_now(), "not_usable_response", f"http_{response.status}"
            )
        if "html" not in response.content_type.lower():
            return Capture(requested_url, utc_now(), "not_usable_response", "not_html")
        return Capture(
            requested_url,
            utc_now(),
            "extracted",
            final_url=destination.url,
            **extract_page(response.body, destination.url),
        )
    return Capture(requested_url, utc_now(), "redirect_limit")


def _read_robots(
    destination: Destination, http: HttpClient, resolve: Resolver
) -> RobotFileParser | str:
    """The host's robots rules; a missing file allows everything, any other failure is a reason.

    Redirects are followed (RFC 9309 asks for at least five), each through the destination
    check; the rules found still govern the original host.
    """
    scheme = urlsplit(destination.url).scheme
    robots_destination = replace(destination, url=f"{scheme}://{destination.host}/robots.txt")
    for _hop in range(MAX_ROBOTS_REDIRECTS + 1):
        response = http.get(robots_destination)
        if response.status not in _REDIRECT_STATUSES or not response.location:
            break
        target = check_destination(
            urljoin(robots_destination.url, response.location), resolve
        )
        if isinstance(target, Blocked):
            return target.reason
        robots_destination = target
    else:
        return "redirect_limit"
    rules = RobotFileParser()
    if response.status in (404, 410):
        rules.parse([])
        return rules
    if response.status != 200:
        return f"http_{response.status}"
    rules.parse(response.body.decode("utf-8", errors="replace").splitlines())
    return rules
