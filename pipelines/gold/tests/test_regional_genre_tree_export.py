import json
from pathlib import Path

import polars as pl
import pytest

from gold.regional_genre_tree_export import export_regional_genre_tree

TREE_ROWS = [
    {"item_id": "Q10", "item_label": "music of Brazil", "parent_id": None},
    {"item_id": "Q11", "item_label": "samba", "parent_id": "Q10"},
    {"item_id": "Q12", "item_label": "music of Cape Verde", "parent_id": None},
]


def _hierarchy() -> pl.DataFrame:
    return pl.DataFrame(TREE_ROWS)


def test_export_regional_genre_tree_writes_tree_shape(tmp_path: Path) -> None:
    wikidata_silver_dir = tmp_path / "wikidata_silver"
    wikidata_silver_dir.mkdir()
    _hierarchy().write_parquet(wikidata_silver_dir / "8_regional_hierarchy.parquet")
    output_dir = tmp_path / "gold"

    result = export_regional_genre_tree(wikidata_silver_dir, output_dir)

    assert result == output_dir / "1_regional_genre_tree.json"
    tree = json.loads(result.read_text())
    assert {node["name"] for node in tree["tree"]} == {"music of Brazil", "music of Cape Verde"}


def test_export_regional_genre_tree_creates_output_dir(tmp_path: Path) -> None:
    wikidata_silver_dir = tmp_path / "wikidata_silver"
    wikidata_silver_dir.mkdir()
    _hierarchy().write_parquet(wikidata_silver_dir / "8_regional_hierarchy.parquet")
    output_dir = tmp_path / "does" / "not" / "exist"

    export_regional_genre_tree(wikidata_silver_dir, output_dir)

    assert output_dir.is_dir()


def test_export_regional_genre_tree_raises_on_schema_violation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import gold.regional_genre_tree_export as module

    monkeypatch.setattr(module, "build_genre_tree", lambda hierarchy: {"tree": [{"name": "samba"}]})
    wikidata_silver_dir = tmp_path / "wikidata_silver"
    wikidata_silver_dir.mkdir()
    _hierarchy().write_parquet(wikidata_silver_dir / "8_regional_hierarchy.parquet")

    with pytest.raises(ValueError, match="schema validation"):
        module.export_regional_genre_tree(wikidata_silver_dir, tmp_path / "gold")
