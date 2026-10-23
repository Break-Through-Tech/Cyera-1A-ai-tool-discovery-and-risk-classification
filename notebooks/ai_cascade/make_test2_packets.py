"""Build blind labeling packets for the second held-out test: the pool's train-split pages, which the cascade was never tuned on."""
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "test2_labeling"
SEED = 12
PACKETS = 8
PAGE_TEXT_CHARS = 2500


def packet_item(capture):
    meta = capture.get("metadata", {})
    return {"sample_id": capture["sample_id"], "title": capture.get("title") or "",
            "meta_description": meta.get("description") or "", "og_description": meta.get("og:description") or "",
            "headings": capture.get("headings", []), "page_text": (capture.get("main_text") or "")[:PAGE_TEXT_CHARS]}


def main():
    captures = [c for c in map(json.loads, (HERE / "pool/captures.jsonl").open(encoding="utf-8"))
                if c["split"] == "train" and c["outcome"] == "extracted"]
    random.Random(SEED).shuffle(captures)
    OUT.mkdir(exist_ok=True)
    for i in range(PACKETS):
        items = [packet_item(c) for c in captures[i::PACKETS]]
        (OUT / f"packet_{i + 1}.json").write_text(json.dumps(items, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"packet_{i + 1}: {len(items)}")


if __name__ == "__main__":
    main()
