import logging
from pathlib import Path

import polars as pl

from wikidata.silver.hierarchy_utils import OUTPUT_COLUMNS, promote_orphans_to_roots

logger = logging.getLogger(__name__)


def prune_canonical_hierarchy(canonical_parents_path: Path, output_dir: Path) -> Path:
    logger.info("pruning canonical hierarchy from %s", canonical_parents_path)
    df = pl.read_parquet(canonical_parents_path)

    parent_is_regional = df.select(
        pl.col("item_id").alias("parent_id"), pl.col("is_regional").alias("parent_is_regional")
    ).unique()

    # Canonical: genres that are not regional
    canonical_items = df.filter(~pl.col("is_regional")).join(parent_is_regional, on="parent_id", how="left")

    # Keep only edges to a canonical parent, or items with no parent at all. An item whose sole
    # parent edge points to a non-genre item (e.g. "electronic music" -> "music") loses its only
    # row here and drops out of `kept` entirely; promote_orphans_to_roots below adds it back as a
    # root by diffing against the unfiltered canonical_items. main_parent_selection.py already
    # collapsed each item to a single parent edge upstream, so no further multi-parent collapse is
    # needed here.
    parent_is_valid_genre_or_absent = pl.col("parent_id").is_null() | pl.col("parent_is_canonical")
    kept = canonical_items.filter(parent_is_valid_genre_or_absent).select(OUTPUT_COLUMNS)
    canonical = promote_orphans_to_roots(canonical_items, kept)

    output_dir.mkdir(parents=True, exist_ok=True)
    canonical_path = output_dir / "7_canonical_hierarchy.parquet"
    canonical.write_parquet(canonical_path)
    logger.info(
        "wrote %d rows to %s (%d items)",
        canonical.height,
        canonical_path,
        canonical_items.select("item_id").n_unique(),
    )

    return canonical_path
