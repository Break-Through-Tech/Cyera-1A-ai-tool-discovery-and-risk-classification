from contextlib import closing

from curl_cffi import CurlOpt
from curl_cffi import requests as curl_requests

from app.enrichment.destinations import Destination
from app.enrichment.fetch import USER_AGENT, FetchError, HttpResponse, ResponseTooLarge

MAX_BODY_BYTES = 2_000_000
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 15


class CurlHttpClient:
    """curl_cffi with a Chrome TLS fingerprint and an honest User-Agent.

    Each request gets a fresh session (no cookies carried between sites), connects only to
    the destination's checked addresses, never follows redirects itself, and reads at most
    ``MAX_BODY_BYTES``.
    """

    def get(self, destination: Destination) -> HttpResponse:
        pinned = ",".join(
            f"[{address}]" if ":" in address else address for address in destination.addresses
        )
        session = curl_requests.Session(
            impersonate="chrome",
            curl_options={CurlOpt.RESOLVE: [f"{destination.host}:{destination.port}:{pinned}"]},
        )
        try:
            with closing(session), closing(
                session.get(
                    destination.url,
                    headers={"User-Agent": USER_AGENT},
                    allow_redirects=False,
                    timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
                    stream=True,
                )
            ) as response:
                body = bytearray()
                for chunk in response.iter_content(chunk_size=65536):
                    body.extend(chunk)
                    if len(body) > MAX_BODY_BYTES:
                        raise ResponseTooLarge()
                return HttpResponse(
                    status=response.status_code,
                    content_type=response.headers.get("Content-Type", ""),
                    location=response.headers.get("Location"),
                    body=bytes(body),
                )
        except curl_requests.RequestsError as error:
            raise FetchError(type(error).__name__) from error
