import json
import logging
from pathlib import Path

import polars as pl
from jsonschema import ValidationError, validate

GENRE_TREE_SCHEMA_PATH = Path(__file__).parent / "schemas" / "genre_tree.schema.json"

logger = logging.getLogger(__name__)


def build_genre_tree(hierarchy: pl.DataFrame) -> dict:
    children_by_parent: dict[str, list[str]] = {}
    for row in hierarchy.iter_rows(named=True):
        children_by_parent.setdefault(row["parent_id"], []).append(row["item_id"])

    labels_by_id = dict(hierarchy.select("item_id", "item_label").unique(subset="item_id").iter_rows())

    # A `parent_id` can point at a label that never has its own row (only ever appears as a parent
    # value) — such a parent is a dead end, not a real ancestor, so the item pointing at it is a
    # root just as much as one with a null parent_id. Mirrors canonical_roots.py's root definition.
    known_item_ids = set(hierarchy.select("item_id").unique().to_series().to_list())

    def build_node(item_id: str, label: str) -> dict:
        return {
            "name": label,
            "children": [
                build_node(child_id, labels_by_id[child_id]) for child_id in children_by_parent.get(item_id, [])
            ],
        }

    roots = (
        hierarchy.filter(pl.col("parent_id").is_null() | ~pl.col("parent_id").is_in(known_item_ids))
        .select("item_id", "item_label")
        .unique(subset="item_id")
        .sort("item_label")
    )
    return {"tree": [build_node(row["item_id"], row["item_label"]) for row in roots.iter_rows(named=True)]}


def export_genre_tree(wikidata_silver_dir: Path, output_dir: Path) -> Path:
    hierarchy_path = wikidata_silver_dir / "7_canonical_hierarchy.parquet"
    logger.info("building canonical genre tree from %s", hierarchy_path)
    hierarchy = pl.read_parquet(hierarchy_path)
    tree = build_genre_tree(hierarchy)

    schema = json.loads(GENRE_TREE_SCHEMA_PATH.read_text())
    try:
        validate(tree, schema)
    except ValidationError as e:
        raise ValueError(f"canonical genre tree failed schema validation ({GENRE_TREE_SCHEMA_PATH}): {e.message}")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "1_canonical_genre_tree.json"
    output_path.write_text(json.dumps(tree, indent=2, ensure_ascii=False))
    logger.info("wrote %d root(s) to %s", len(tree["tree"]), output_path)
    return output_path
