import logging
from pathlib import Path

import polars as pl

from wikidata.silver.hierarchy_utils import collapse_to_lowest_qid, promote_orphans_to_roots

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
    # row here and drops out of `collapsed` entirely; promote_orphans_to_roots below adds it back
    # as a root by diffing against the unfiltered canonical_items.
    parent_is_valid_genre_or_absent = pl.col("parent_id").is_null() | pl.col("parent_is_canonical")
    collapsed = collapse_to_lowest_qid(canonical_items.filter(parent_is_valid_genre_or_absent))
    canonical = promote_orphans_to_roots(canonical_items, collapsed)

    output_dir.mkdir(parents=True, exist_ok=True)
    canonical_path = output_dir / "6_canonical_hierarchy.parquet"
    canonical.write_parquet(canonical_path)
    logger.info(
        "wrote %d rows to %s (%d items)",
        canonical.height,
        canonical_path,
        canonical_items.select("item_id").n_unique(),
    )

    return canonical_path
