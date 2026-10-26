"""Decide whether an uploaded, untrusted destination may be fetched.

Every URL, including each redirect target, passes through ``check_destination``. An
allowed destination carries the addresses that were checked; the HTTP client connects
only to those, so a second DNS answer cannot redirect the request to a private host.
"""

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from app.hostnames import is_public_hostname

Resolver = Callable[[str, int], list[str]]

_DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass(frozen=True)
class Destination:
    url: str
    host: str
    port: int
    addresses: tuple[str, ...]


@dataclass(frozen=True)
class Blocked:
    reason: str


def system_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in infos))


def check_destination(url: str, resolve: Resolver) -> Destination | Blocked:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS:
        return Blocked("unsupported_scheme")
    if parts.username is not None or parts.password is not None:
        return Blocked("credentials_in_url")
    try:
        port = parts.port
    except ValueError:
        return Blocked("unsupported_port")
    if port not in (None, _DEFAULT_PORTS[scheme]):
        return Blocked("unsupported_port")
    host = (parts.hostname or "").rstrip(".")
    if not is_public_hostname(host):
        return Blocked("non_public_hostname")

    port = _DEFAULT_PORTS[scheme]
    try:
        addresses = tuple(dict.fromkeys(resolve(host, port)))
    except OSError:
        return Blocked("dns_failure")
    if not addresses:
        return Blocked("dns_failure")
    if not all(_is_public_address(address) for address in addresses):
        return Blocked("non_public_address")

    return Destination(
        url=urlunsplit((scheme, host, parts.path or "/", parts.query, "")),
        host=host,
        port=port,
        addresses=addresses,
    )


def _is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast
