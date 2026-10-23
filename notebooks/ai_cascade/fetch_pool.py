"""Fetch a fresh train/test pool of homepages, disjoint from the website_feasibility dev sample."""
import csv
import hashlib
import json
import random
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "notebooks/website_feasibility"))
from fetch_sample import COMPANYENRICH, TOOLBUZZ, WORKERS, fetch, homepage, host_key  # noqa: E402

DEV = ROOT / "notebooks/website_feasibility/captures/results.jsonl"
OUT = Path(__file__).resolve().parent / "pool/captures.jsonl"
SEED = 20261023
TOOLBUZZ_N = 450
TEST_FRACTION = 1 / 3


def split_for(url):
    digest = int(hashlib.sha256(f"{SEED}:split:{url}".encode()).hexdigest(), 16)
    return "test" if digest % 3 == 0 else "train"


def sample():
    dev_hosts = {host_key(json.loads(line)["url"]) for line in DEV.open(encoding="utf-8")}
    with TOOLBUZZ.open(encoding="utf-8-sig", newline="") as f:
        toolbuzz = [{"source": "aitoolbuzz", "name": r["Name"], "url": homepage(r["Website"])}
                    for r in csv.DictReader(f) if r["Website"].strip() and r["Website Status"] == "Active"]
    enrich = [{"source": "companyenrich", "name": r["Name"], "url": homepage(r["URL"])}
              for r in map(json.loads, COMPANYENRICH.open(encoding="utf-8"))]
    toolbuzz_hosts = {host_key(r["url"]) for r in toolbuzz}
    enrich_hosts = {host_key(r["url"]) for r in enrich}
    chosen = []
    for pool, other, limit in ((toolbuzz, enrich_hosts, TOOLBUZZ_N), (enrich, toolbuzz_hosts, None)):
        rng = random.Random(SEED)
        candidates = [r for r in pool if host_key(r["url"]) and host_key(r["url"]) not in other | dev_hosts]
        rng.shuffle(candidates)
        seen = set()
        for row in candidates:
            if host_key(row["url"]) in seen:
                continue
            seen.add(host_key(row["url"]))
            chosen.append(row)
            if limit and len(seen) == limit:
                break
    for row in chosen:
        row["sample_id"] = "site_" + hashlib.sha256(f"{SEED}:{row['url']}".encode()).hexdigest()[:12]
        row["split"] = split_for(row["url"])
    return chosen


def main():
    rows = sample()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(fetch, rows))
    with OUT.open("w", encoding="utf-8") as f:
        for result in results:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
    print(json.dumps({f"{s}/{p}": dict(Counter(r["outcome"] for r in results if r["source"] == s and r["split"] == p))
                      for s in ("aitoolbuzz", "companyenrich") for p in ("train", "test")}, indent=1))


if __name__ == "__main__":
    main()
