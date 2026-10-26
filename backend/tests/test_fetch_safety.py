import pytest

from app.enrichment.destinations import Blocked, Destination, check_destination

PUBLIC_V4 = "93.184.215.14"
PUBLIC_V6 = "2606:2800:21f:cb07:6820:80da:af6b:8b2c"


def resolver(*addresses: str):
    def resolve(_host: str, _port: int) -> list[str]:
        return list(addresses)

    return resolve


def test_public_https_destination_is_allowed_and_pinned_to_its_checked_addresses():
    result = check_destination("https://WWW.Example-Tool.com/", resolver(PUBLIC_V4, PUBLIC_V6))

    assert result == Destination(
        url="https://www.example-tool.com/",
        host="www.example-tool.com",
        port=443,
        addresses=(PUBLIC_V4, PUBLIC_V6),
    )


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("ftp://tool.com/", "unsupported_scheme"),
        ("file:///etc/passwd", "unsupported_scheme"),
        ("https://tool.com:8443/", "unsupported_port"),
        ("https://user:secret@tool.com/", "credentials_in_url"),
        ("https://93.184.215.14/", "non_public_hostname"),
        ("https://[::1]/", "non_public_hostname"),
        ("https://localhost/", "non_public_hostname"),
        ("https://workbench.example/", "non_public_hostname"),
        ("https:///no-host", "non_public_hostname"),
    ],
)
def test_destinations_rejected_before_any_dns_lookup(url, reason):
    def must_not_resolve(_host, _port):
        raise AssertionError("resolved a destination that should be rejected first")

    assert check_destination(url, must_not_resolve) == Blocked(reason)


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.5",
        "172.16.3.4",
        "192.168.1.10",
        "127.0.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "::1",
        "fd12:3456::1",
        "fe80::1",
        "::ffff:10.0.0.5",
    ],
)
def test_hostname_resolving_to_any_non_public_address_is_blocked(address):
    result = check_destination("https://tool.com/", resolver(PUBLIC_V4, address))

    assert result == Blocked("non_public_address")


def test_hostname_that_does_not_resolve_is_blocked():
    def fails(_host, _port):
        raise OSError("Name or service not known")

    assert check_destination("https://tool.com/", fails) == Blocked("dns_failure")
    assert check_destination("https://tool.com/", resolver()) == Blocked("dns_failure")
