"""One-off fixed-public-site experiment, not an arbitrary-URL ingestion service."""
import argparse
import json
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
import trafilatura
from bs4 import BeautifulSoup

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--client', choices=['requests', 'curl-cffi'], default='requests')
args = parser.parse_args()
OUT = Path(__file__).parent / 'captures' / args.client
OUT.mkdir(parents=True, exist_ok=True)
SITES = [
    'https://huggingface.co/',
    'https://www.grammarly.com/',
    'https://slack.com/',
    'https://www.libreoffice.org/',
    'https://claude.ai/',
    'https://app.asana.com/',
]
if args.client == 'curl-cffi':
    SITES = ['https://claude.ai/', 'https://app.asana.com/']
AGENT = 'ToolMetadataExperiment'
LIMIT = 2_000_000


def bounded_body(response):
    body = bytearray()
    for chunk in response.iter_content(chunk_size=65536):
        body.extend(chunk)
        if len(body) > LIMIT:
            raise ValueError('decoded response exceeds size limit')
    return bytes(body)


def fields(html):
    soup = BeautifulSoup(html, 'html.parser')
    metadata = {}
    for tag in soup.find_all('meta'):
        key = (tag.get('name') or tag.get('property') or '').lower()
        if key in {'description', 'og:description', 'og:title'}:
            metadata[key] = tag.get('content', '').strip()
    return {
        'title': soup.title.get_text(' ', strip=True) if soup.title else None,
        'metadata': metadata,
        'headings': [h.get_text(' ', strip=True) for h in soup.find_all(['h1', 'h2'])][:20],
    }


assert fields('<title> Test </title><meta name="description" content="Writes text"><h1>Writer</h1>') == {
    'title': 'Test', 'metadata': {'description': 'Writes text'}, 'headings': ['Writer']}
assert fields('<html></html>')['metadata'] == {}
assert fields('<meta charset="utf-8"><title>Office — Suite</title>'.encode('utf-8'))['title'] == 'Office — Suite'

fetch_errors = (requests.RequestException,)
if args.client == 'curl-cffi':
    from curl_cffi import requests as curl_requests
    session = curl_requests.Session(impersonate='chrome')
    fetch_errors += (curl_requests.RequestsError,)
else:
    session = requests.Session()
# Identify this experiment consistently; curl_cffi changes transport fingerprint,
# not the robots identity. No CAPTCHA solving or disallowed-page fetching.
session.headers['User-Agent'] = AGENT + '/0.1 (public HTML extraction experiment)'
results = []
for url in SITES:
    host = urlsplit(url).hostname
    result = {'url': url, 'client': args.client, 'captured_at': datetime.now(timezone.utc).isoformat()}
    start = time.monotonic()
    try:
        robots_url = f'https://{host}/robots.txt'
        with closing(session.get(robots_url, timeout=(5, 15), stream=True)) as response:
            result['robots_status'] = response.status_code
            robots = bounded_body(response)
            (OUT / f'{host}.robots.txt').write_bytes(robots)
            if response.status_code == 200:
                parser = RobotFileParser()
                parser.parse(robots.decode('utf-8', errors='replace').splitlines())
                if not parser.can_fetch(AGENT, url):
                    result['outcome'] = 'robots_disallowed'
                    result['elapsed_seconds'] = round(time.monotonic() - start, 2)
                    results.append(result)
                    print(json.dumps(result), flush=True)
                    continue
            elif response.status_code not in (404, 410):
                raise ValueError('robots unavailable; conservatively skipped')
        with closing(session.get(url, timeout=(5, 20), stream=True)) as response:
            result.update(status=response.status_code, final_url=response.url,
                          content_type=response.headers.get('Content-Type', ''))
            raw = bounded_body(response)
            (OUT / f'{host}.html').write_bytes(raw)
            result['bytes'] = len(raw)
            if response.status_code != 200 or 'html' not in result['content_type'].lower():
                result['outcome'] = 'not_usable_response'
            else:
                html = str(BeautifulSoup(raw, 'html.parser'))
                result.update(fields(html))
                text = trafilatura.extract(html, url=response.url, include_comments=False) or ''
                (OUT / f'{host}.text.txt').write_text(text)
                result.update(outcome='extracted', main_text_characters=len(text), main_text_preview=text[:1800])
    except fetch_errors as error:
        result.update(outcome='fetch_failed', error=str(error))
    except ValueError as error:
        result.update(outcome='skipped', error=str(error))
    result['elapsed_seconds'] = round(time.monotonic() - start, 2)
    results.append(result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
session.close()
(OUT / 'results.json').write_text(json.dumps(results, indent=2, ensure_ascii=False))
