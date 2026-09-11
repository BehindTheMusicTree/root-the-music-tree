import json
from pathlib import Path

import polars as pl
import pytest

from gold.canonical_genre_tree_export import export_canonical_genre_tree

TREE_ROWS = [
    {"item_id": "Q1", "item_label": "rock", "parent_id": None},
    {"item_id": "Q2", "item_label": "punk rock", "parent_id": "Q1"},
    {"item_id": "Q3", "item_label": "hardcore punk", "parent_id": "Q2"},
    {"item_id": "Q4", "item_label": "pop rock", "parent_id": "Q1"},
    {"item_id": "Q5", "item_label": "jazz", "parent_id": None},
]


def _hierarchy() -> pl.DataFrame:
    return pl.DataFrame(TREE_ROWS)


def test_export_canonical_genre_tree_writes_tree_shape(tmp_path: Path) -> None:
    wikidata_silver_dir = tmp_path / "wikidata_silver"
    wikidata_silver_dir.mkdir()
    _hierarchy().write_parquet(wikidata_silver_dir / "7_canonical_hierarchy.parquet")
    output_dir = tmp_path / "gold"

    result = export_canonical_genre_tree(wikidata_silver_dir, output_dir)

    assert result == output_dir / "1_canonical_genre_tree.json"
    tree = json.loads(result.read_text())
    assert {node["name"] for node in tree["tree"]} == {"rock", "jazz"}


def test_export_canonical_genre_tree_creates_output_dir(tmp_path: Path) -> None:
    wikidata_silver_dir = tmp_path / "wikidata_silver"
    wikidata_silver_dir.mkdir()
    _hierarchy().write_parquet(wikidata_silver_dir / "7_canonical_hierarchy.parquet")
    output_dir = tmp_path / "does" / "not" / "exist"

    export_canonical_genre_tree(wikidata_silver_dir, output_dir)

    assert output_dir.is_dir()


def test_export_canonical_genre_tree_raises_on_schema_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import gold.canonical_genre_tree_export as module

    monkeypatch.setattr(module, "build_genre_tree", lambda hierarchy: {"tree": [{"name": "rock"}]})
    wikidata_silver_dir = tmp_path / "wikidata_silver"
    wikidata_silver_dir.mkdir()
    _hierarchy().write_parquet(wikidata_silver_dir / "7_canonical_hierarchy.parquet")

    with pytest.raises(ValueError, match="schema validation"):
        module.export_canonical_genre_tree(wikidata_silver_dir, tmp_path / "gold")
