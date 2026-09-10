import json
import logging
from pathlib import Path

import polars as pl
from jsonschema import ValidationError, validate

from gold.genre_tree_builder import build_genre_tree

GENRE_TREE_SCHEMA_PATH = Path(__file__).parent / "schemas" / "genre_tree.schema.json"

logger = logging.getLogger(__name__)


def export_canonical_genre_tree(wikidata_silver_dir: Path, output_dir: Path) -> Path:
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
