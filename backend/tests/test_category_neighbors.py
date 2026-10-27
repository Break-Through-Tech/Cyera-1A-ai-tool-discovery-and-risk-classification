import csv
import json
from pathlib import Path

import numpy as np
import pytest

from app.category.neighbors import load_neighbor_index
from app.config import Settings

TOOLS = [
    ("t_a", "Alpha", "Marketing And Sales", [1.0, 0.0]),
    ("t_b", "Beta", "Data And Analytics", [0.8, 0.6]),
    ("t_c", "Gamma", "Data And Analytics", [0.6, 0.8]),
    ("t_d", "Delta", "Marketing And Sales", [0.0, 1.0]),
]


def write_index(directory, tools=TOOLS, dim=2):
    directory.mkdir(parents=True, exist_ok=True)
    np.save(directory / "embeddings.npy", np.array([vector for *_, vector in tools], dtype=np.float32))
    with (directory / "tools.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["tool_id", "name", "category"])
        writer.writerows(row[:3] for row in tools)
    manifest = {"model": {"repo": "BAAI/bge-small-en-v1.5", "revision": "5c38ec7", "dim": dim}}
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def test_the_nearest_tools_vote_for_their_categories_weighted_by_similarity(tmp_path):
    index = load_neighbor_index(write_index(tmp_path / "index"))

    vote = index.vote(np.array([1.0, 0.0]), k=3)

    # Alpha is closest, but Beta (0.8) and Gamma (0.6) outweigh it for Data And Analytics.
    assert vote.category == "Data And Analytics"
    assert vote.share == pytest.approx(1.4 / 2.4)
    assert [(n.name, n.category) for n in vote.neighbors] == [
        ("Alpha", "Marketing And Sales"),
        ("Beta", "Data And Analytics"),
        ("Gamma", "Data And Analytics"),
    ]
    assert [n.similarity for n in vote.neighbors] == pytest.approx([1.0, 0.8, 0.6])


def test_the_committed_index_loads_without_the_catalog_held_out_tools():
    settings = Settings(data_dir=Path("unused"))
    index = load_neighbor_index(settings.neighbor_index_path)
    held_out = set(json.loads(settings.registry_exclusions_path.read_text())["excluded_tool_ids"])

    assert len(index.tools) == 8214
    assert held_out
    assert not held_out & {tool.tool_id for tool in index.tools}


def test_the_index_version_names_its_folder_size_and_model(tmp_path):
    index = load_neighbor_index(write_index(tmp_path / "index"))

    assert index.version == f"{(tmp_path / 'index').as_posix()};tools=4;model=BAAI/bge-small-en-v1.5@5c38ec7"


def test_an_index_whose_files_do_not_line_up_is_rejected(tmp_path):
    missing_row = write_index(tmp_path / "rows")
    (missing_row / "tools.csv").write_text(
        "tool_id,name,category\nt_a,Alpha,Marketing And Sales\n", encoding="utf-8"
    )
    wrong_dim = write_index(tmp_path / "dim", dim=384)

    with pytest.raises(ValueError, match="row"):
        load_neighbor_index(missing_row)
    with pytest.raises(ValueError, match="dimension"):
        load_neighbor_index(wrong_dim)
