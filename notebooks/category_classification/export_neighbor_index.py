"""Export the Semantic Neighbor index for Category Classification (ADR 0003) and re-check it on validation."""

from __future__ import annotations

import csv
import hashlib
import json
from importlib.metadata import version
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType
from huggingface_hub import snapshot_download

from check_fastembed import CUTOFF, K, vote
from evaluate import labels_of, load_splits, load_transfer, page_text
from prepare_dataset import SOURCE


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/category_neighbor_index/v1"
EXCLUSIONS = ROOT / "backend/config/known_tool_registry_exclusions.json"
MODEL_REPO = "BAAI/bge-small-en-v1.5"
MODEL_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
MODEL_FILES = ["onnx/model.onnx", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "config.json"]
FASTEMBED_NAME = "bge-small-en-v1.5-onnx-cls"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_model() -> TextEmbedding:
    path = Path(snapshot_download(MODEL_REPO, revision=MODEL_REVISION, allow_patterns=MODEL_FILES))
    TextEmbedding.add_custom_model(model=FASTEMBED_NAME, pooling=PoolingType.CLS, normalization=True,
                                   sources=ModelSource(hf=MODEL_REPO), dim=384, model_file="onnx/model.onnx")
    return TextEmbedding(FASTEMBED_NAME, specific_model_path=str(path))


def main() -> None:
    splits = load_splits()
    train = splits["train"]
    labels = labels_of(train)
    held_out = set(json.loads(EXCLUSIONS.read_text(encoding="utf-8"))["excluded_tool_ids"])
    if held_out & {row["tool_id"] for row in train}:
        raise ValueError("A catalog-held-out Tool is in the train split")
    with SOURCE.open(encoding="utf-8", newline="") as stream:
        names = {row["tool_id"]: row["Name"] for row in csv.DictReader(stream)}

    model = load_model()
    encode = lambda texts: np.array(list(model.embed(texts, batch_size=64)), dtype=np.float32)
    embeddings = encode([row["description_text"] for row in train])

    OUT.mkdir(parents=True, exist_ok=True)
    np.save(OUT / "embeddings.npy", embeddings)
    with (OUT / "tools.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["tool_id", "name", "category"])
        writer.writerows([row["tool_id"], names[row["tool_id"]], row["category"]] for row in train)

    onehot = np.eye(len(labels))[[labels.index(row["category"]) for row in train]]
    pages = load_transfer("validation")
    checks = {}
    for name, texts, expected in (
        ("validation_descriptions", [row["description_text"] for row in splits["validation"]],
         [row["category"] for row in splits["validation"]]),
        ("validation_pages[full]", [page_text(page, "full") for page in pages], [page["category"] for page in pages]),
    ):
        scores = vote(encode(texts), embeddings, onehot)
        predicted = np.array(labels)[scores.argmax(1)]
        kept = scores.max(1) >= CUTOFF
        checks[name] = {"rows": len(texts), "accuracy": float(np.mean(predicted == expected)),
                        "answered": float(kept.mean()),
                        "accuracy_when_answering": float(np.mean(predicted[kept] == np.array(expected)[kept]))}

    manifest = {
        "index_id": "aitoolbuzz-category-neighbors-v1",
        "decision": "docs/adr/0003-category-classification-uses-semantic-neighbor-vote.md",
        "dataset_id": "aitoolbuzz-category-v1",
        "train_partition_sha256": json.loads((ROOT / "data/category_classification/v1/manifest.json")
                                             .read_text(encoding="utf-8"))["partitions"]["train"]["sha256"],
        "rows": len(train),
        "embedded_text": "description_text",
        "model": {"repo": MODEL_REPO, "revision": MODEL_REVISION, "files": MODEL_FILES,
                  "pooling": "cls", "normalized": True, "dim": 384},
        "runtime": {"fastembed": version("fastembed"), "onnxruntime": version("onnxruntime")},
        "embeddings_sha256": sha256(OUT / "embeddings.npy"),
        "tools_sha256": sha256(OUT / "tools.csv"),
        "held_out_tool_ids_absent": sorted(held_out),
        "validation_check": {"k": K, "cutoff": CUTOFF, **checks},
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(checks, indent=1))


if __name__ == "__main__":
    main()
