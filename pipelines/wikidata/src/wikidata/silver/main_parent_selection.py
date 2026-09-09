import logging
from pathlib import Path

import polars as pl

from wikidata.silver.regional_classification import MANUAL_MAIN_PARENT_RELATION_TYPE

logger = logging.getLogger(__name__)

SECONDARY_PARENT_COLUMNS = [
    "item_id",
    "item_label",
    "item_url",
    "parent_id",
    "parent_label",
    "parent_url",
    "relation_type",
]


def select_main_parents(regional_classification_path: Path, output_dir: Path) -> tuple[Path, Path]:
    logger.info("selecting main parents from %s", regional_classification_path)
    df = pl.read_parquet(regional_classification_path)

    # Wikidata's P279/P361 graph isn't a strict tree: many genre items have more than one surviving
    # genre parent. manual_main_parent.csv (already applied as a synthetic edge in
    # regional_classification.py, tagged MANUAL_MAIN_PARENT_RELATION_TYPE) is a data expert's
    # explicit pick and always wins; everything else falls back to the lowest-QID parent, a
    # provisional placeholder pending a real product/curation decision — see
    # DESIGN.md#25-6_main_parent_selection.
    manual_main = df.filter(pl.col("relation_type") == MANUAL_MAIN_PARENT_RELATION_TYPE)
    manual_item_ids = set(manual_main.select("item_id").unique().to_series())

    auto_candidates = df.filter(~pl.col("item_id").is_in(list(manual_item_ids)))
    auto_main = (
        auto_candidates.with_columns(parent_numeric_id=pl.col("parent_id").str.slice(1).cast(pl.Int64, strict=False))
        .sort(["item_id", "parent_numeric_id"])
        .unique(subset="item_id", keep="first")
        .drop("parent_numeric_id")
    )

    main = pl.concat([manual_main, auto_main])
    # `join` treats null != null, so a plain anti-join on (item_id, parent_id) would incorrectly
    # flag every root item's own (item_id, null) row as a leftover secondary edge. Root items have
    # only one candidate edge (their null-parent row) which is always their main parent, so they
    # never produce secondary edges — exclude them up front instead.
    secondary = (
        df.filter(pl.col("parent_id").is_not_null())
        .join(main.select("item_id", "parent_id"), on=["item_id", "parent_id"], how="anti")
        .select(SECONDARY_PARENT_COLUMNS)
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    main_path = output_dir / "5_main_parent_selection.parquet"
    secondary_path = output_dir / "5_secondary_parents.parquet"
    main.write_parquet(main_path)
    secondary.write_parquet(secondary_path)
    logger.info(
        "wrote %d rows to %s (%d items), %d secondary parent edges to %s",
        main.height,
        main_path,
        main.select("item_id").n_unique(),
        secondary.height,
        secondary_path,
    )

    return main_path, secondary_path
