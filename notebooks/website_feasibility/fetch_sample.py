"""Fetch public homepages for a seeded AIToolBuzz / CompanyEnrich sample; a research run, not a production fetcher."""
import csv
import hashlib
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import trafilatura
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

ROOT = Path(__file__).resolve().parents[2]
TOOLBUZZ = ROOT / "data/aitoolbuzz-com-16k-ai-tools-database/Complete AI Tools Dataset 2025 - 16763 Tools from AIToolBuzz.csv"
COMPANYENRICH = ROOT / "data/companyenrich-saas-companies/dataset.jsonl"
OUT = Path(__file__).resolve().parent / "captures"
SEED = 20261022
PER_SOURCE = 150
WORKERS = 12
AGENT = "ToolMetadataExperiment"
LIMIT = 2_000_000
MAIN_TEXT_CHARS = 6000

_local = threading.local()


def session():
    if not hasattr(_local, "session"):
        _local.session = curl_requests.Session(impersonate="chrome")
        _local.session.headers["User-Agent"] = AGENT + "/0.1 (public HTML extraction experiment)"
    return _local.session


def homepage(url):
    url = url.strip()
    parts = urlsplit(url if "://" in url else "https://" + url)
    return urlunsplit(("https", parts.hostname or "", "/", "", ""))


def host_key(url):
    host = (urlsplit(url).hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


def sample():
    with TOOLBUZZ.open(encoding="utf-8-sig", newline="") as f:
        toolbuzz = [{"source": "aitoolbuzz", "name": r["Name"], "url": homepage(r["Website"])}
                    for r in csv.DictReader(f) if r["Website"].strip() and r["Website Status"] == "Active"]
    enrich = [{"source": "companyenrich", "name": r["Name"], "url": homepage(r["URL"])}
              for r in map(json.loads, COMPANYENRICH.open(encoding="utf-8"))]
    toolbuzz_hosts = {host_key(r["url"]) for r in toolbuzz}
    enrich_hosts = {host_key(r["url"]) for r in enrich}
    chosen = []
    for pool, other in ((toolbuzz, enrich_hosts), (enrich, toolbuzz_hosts)):
        rng = random.Random(SEED)
        seen = set()
        candidates = [r for r in pool if host_key(r["url"]) and host_key(r["url"]) not in other]
        rng.shuffle(candidates)
        for row in candidates:
            if host_key(row["url"]) in seen:
                continue
            seen.add(host_key(row["url"]))
            chosen.append(row)
            if len(seen) == PER_SOURCE:
                break
    for row in chosen:
        row["sample_id"] = "site_" + hashlib.sha256(f"{SEED}:{row['url']}".encode()).hexdigest()[:12]
    return chosen


def bounded_body(response):
    body = bytearray()
    for chunk in response.iter_content(chunk_size=65536):
        body.extend(chunk)
        if len(body) > LIMIT:
            raise ValueError("decoded response exceeds size limit")
    return bytes(body)


def fields(html):
    soup = BeautifulSoup(html, "html.parser")
    metadata = {}
    for tag in soup.find_all("meta"):
        key = (tag.get("name") or tag.get("property") or "").lower()
        if key in {"description", "og:description", "og:title"}:
            metadata[key] = tag.get("content", "").strip()
    return {"title": soup.title.get_text(" ", strip=True) if soup.title else None, "metadata": metadata,
            "headings": [h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2"])][:20]}


def fetch(row):
    result = {**row, "captured_at": datetime.now(timezone.utc).isoformat()}
    start = time.monotonic()
    host = urlsplit(row["url"]).hostname
    try:
        with closing(session().get(f"https://{host}/robots.txt", timeout=(5, 15), stream=True)) as response:
            result["robots_status"] = response.status_code
            robots = bounded_body(response)
            if response.status_code == 200:
                parser = RobotFileParser()
                parser.parse(robots.decode("utf-8", errors="replace").splitlines())
                if not parser.can_fetch(AGENT, row["url"]):
                    return {**result, "outcome": "robots_disallowed"}
            elif response.status_code not in (404, 410):
                return {**result, "outcome": "skipped", "error": "robots unavailable; conservatively skipped"}
        with closing(session().get(row["url"], timeout=(5, 20), stream=True)) as response:
            result.update(status=response.status_code, final_url=response.url,
                          content_type=response.headers.get("Content-Type", ""))
            raw = bounded_body(response)
            if response.status_code != 200 or "html" not in result["content_type"].lower():
                return {**result, "outcome": "not_usable_response"}
            html = str(BeautifulSoup(raw, "html.parser"))
            text = trafilatura.extract(html, url=response.url, include_comments=False) or ""
            return {**result, **fields(html), "outcome": "extracted", "main_text_characters": len(text),
                    "main_text": text[:MAIN_TEXT_CHARS]}
    except curl_requests.RequestsError as error:
        return {**result, "outcome": "fetch_failed", "error": str(error)[:300]}
    except ValueError as error:
        return {**result, "outcome": "skipped", "error": str(error)}
    finally:
        result["elapsed_seconds"] = round(time.monotonic() - start, 2)


def main():
    rows = sample()
    OUT.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(fetch, rows))
    with (OUT / "results.jsonl").open("w", encoding="utf-8") as f:
        for result in results:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
    counts = {}
    for r in results:
        counts.setdefault(r["source"], {}).setdefault(r["outcome"], 0)
        counts[r["source"]][r["outcome"]] += 1
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
