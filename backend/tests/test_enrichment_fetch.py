import pytest

from app.enrichment.fetch import (
    FetchError,
    HttpResponse,
    ResponseTooLarge,
    fetch_homepage,
    fetch_homepages,
)

PUBLIC = "93.184.215.14"
PAGE = b"""<html><head><title>Tool - Writes summaries</title>
<meta name="description" content="AI that summarizes meeting notes.">
<meta property="og:title" content="Tool"></head>
<body><h1>Summaries in seconds</h1><h2>For teams</h2><p>Body text.</p></body></html>"""


def html(body: bytes = PAGE, status: int = 200) -> HttpResponse:
    return HttpResponse(status=status, content_type="text/html; charset=utf-8", location=None, body=body)


def redirect(location: str) -> HttpResponse:
    return HttpResponse(status=301, content_type="text/html", location=location, body=b"")


def not_found() -> HttpResponse:
    return HttpResponse(status=404, content_type="text/plain", location=None, body=b"")


class FakeHttp:
    def __init__(self, responses: dict):
        self.responses = responses
        self.requested: list[tuple[str, tuple[str, ...]]] = []

    def get(self, destination):
        self.requested.append((destination.url, destination.addresses))
        response = self.responses[destination.url]
        if isinstance(response, Exception):
            raise response
        return response


def public_dns(addresses_by_host: dict[str, str] | None = None):
    def resolve(host, _port):
        return [(addresses_by_host or {}).get(host, PUBLIC)]

    return resolve


def fetch(responses: dict, resolve=None):
    http = FakeHttp(responses)
    capture = fetch_homepage("tool.com", http, resolve or public_dns())
    return capture, http


def test_homepage_is_fetched_through_a_checked_redirect_and_extracted():
    capture, http = fetch(
        {
            "https://tool.com/robots.txt": not_found(),
            "https://tool.com/": redirect("https://www.tool.com/"),
            "https://www.tool.com/robots.txt": not_found(),
            "https://www.tool.com/": html(),
        }
    )

    assert capture.outcome == "extracted"
    assert capture.requested_url == "https://tool.com/"
    assert capture.final_url == "https://www.tool.com/"
    assert capture.title == "Tool - Writes summaries"
    assert capture.metadata == {
        "description": "AI that summarizes meeting notes.",
        "og:title": "Tool",
    }
    assert capture.headings == ("Summaries in seconds", "For teams")
    assert capture.captured_at.endswith("Z")
    assert all(addresses == (PUBLIC,) for _url, addresses in http.requested)
    assert [url for url, _ in http.requested] == [
        "https://tool.com/robots.txt",
        "https://tool.com/",
        "https://www.tool.com/robots.txt",
        "https://www.tool.com/",
    ]


def robots(text: str) -> HttpResponse:
    return HttpResponse(status=200, content_type="text/plain", location=None, body=text.encode())


def test_robots_disallow_prevents_fetching_the_homepage():
    capture, http = fetch(
        {"https://tool.com/robots.txt": robots("User-agent: *\nDisallow: /\n")}
    )

    assert capture.outcome == "robots_disallowed"
    assert [url for url, _ in http.requested] == ["https://tool.com/robots.txt"]


def test_robots_rules_for_other_agents_do_not_block_us():
    capture, _ = fetch(
        {
            "https://tool.com/robots.txt": robots("User-agent: Googlebot\nDisallow: /\n"),
            "https://tool.com/": html(),
        }
    )

    assert capture.outcome == "extracted"


def test_unreadable_robots_file_skips_the_site_conservatively():
    capture, http = fetch(
        {"https://tool.com/robots.txt": HttpResponse(500, "text/html", None, b"")}
    )

    assert capture.outcome == "robots_unavailable"
    assert capture.detail == "http_500"
    assert [url for url, _ in http.requested] == ["https://tool.com/robots.txt"]


def test_redirect_to_an_internal_address_is_blocked_before_any_request():
    capture, http = fetch(
        {
            "https://tool.com/robots.txt": not_found(),
            "https://tool.com/": redirect("https://metadata.tool.com/latest/"),
        },
        resolve=public_dns({"metadata.tool.com": "169.254.169.254"}),
    )

    assert capture.outcome == "blocked_destination"
    assert capture.detail == "non_public_address"
    assert all("metadata.tool.com" not in url for url, _ in http.requested)


def test_redirect_chain_longer_than_three_hops_stops():
    capture, _ = fetch(
        {
            "https://tool.com/robots.txt": not_found(),
            "https://tool.com/": redirect("/a"),
            "https://tool.com/a": redirect("/b"),
            "https://tool.com/b": redirect("/c"),
            "https://tool.com/c": redirect("/d"),
        }
    )

    assert capture.outcome == "redirect_limit"


def test_non_public_domain_is_never_requested():
    http = FakeHttp({})

    capture = fetch_homepage("workbench.example", http, public_dns())

    assert (capture.outcome, capture.detail) == ("blocked_destination", "non_public_hostname")
    assert http.requested == []


@pytest.mark.parametrize(
    ("page", "outcome", "detail"),
    [
        (html(status=403), "not_usable_response", "http_403"),
        (HttpResponse(200, "application/pdf", None, b"%PDF"), "not_usable_response", "not_html"),
        (ResponseTooLarge(), "too_large", None),
        (FetchError("Timeout"), "fetch_failed", "Timeout"),
    ],
    ids=["forbidden", "pdf", "too-large", "timeout"],
)
def test_unusable_homepages_are_recorded_outcomes_not_errors(page, outcome, detail):
    capture, _ = fetch({"https://tool.com/robots.txt": not_found(), "https://tool.com/": page})

    assert (capture.outcome, capture.detail) == (outcome, detail)
    assert capture.final_url is None
    assert capture.main_text == ""


def test_robots_request_that_times_out_is_a_fetch_failure():
    capture, _ = fetch({"https://tool.com/robots.txt": FetchError("timed out")})

    assert capture.outcome == "fetch_failed"


def test_redirected_robots_file_is_followed_through_checked_destinations():
    capture, _ = fetch(
        {
            "https://tool.com/robots.txt": redirect("https://www.tool.com/robots.txt"),
            "https://www.tool.com/robots.txt": robots("User-agent: *\nDisallow: /private\n"),
            "https://tool.com/": html(),
        }
    )

    assert capture.outcome == "extracted"


def test_robots_redirect_to_an_internal_address_makes_robots_unavailable():
    capture, http = fetch(
        {"https://tool.com/robots.txt": redirect("https://intranet.tool.com/robots.txt")},
        resolve=public_dns({"intranet.tool.com": "10.0.0.5"}),
    )

    assert (capture.outcome, capture.detail) == ("robots_unavailable", "non_public_address")
    assert [url for url, _ in http.requested] == ["https://tool.com/robots.txt"]


def test_homepages_beyond_the_per_run_budget_are_not_fetched():
    http = FakeHttp(
        {
            url: not_found()
            for domain in ("a.com", "b.com", "c.com")
            for url in (f"https://{domain}/robots.txt", f"https://{domain}/")
        }
    )

    captures = fetch_homepages(["c.com", "a.com", "b.com", "a.com"], http, public_dns(), max_fetches=2)

    assert {domain: c.outcome for domain, c in captures.items()} == {
        "a.com": "not_usable_response",
        "b.com": "not_usable_response",
        "c.com": "fetch_budget_exhausted",
    }
    assert not any("c.com" in url for url, _ in http.requested)


def test_redirect_to_a_host_whose_robots_disallow_us_stops_there():
    capture, http = fetch(
        {
            "https://tool.com/robots.txt": not_found(),
            "https://tool.com/": redirect("https://app.tool.com/login"),
            "https://app.tool.com/robots.txt": robots("User-agent: *\nDisallow: /login\n"),
        }
    )

    assert capture.outcome == "robots_disallowed"
    assert "https://app.tool.com/login" not in [url for url, _ in http.requested]
