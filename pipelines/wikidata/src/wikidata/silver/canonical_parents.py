import logging
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)


def flag_canonical_parents(main_parent_selection_path: Path, output_dir: Path) -> Path:
    logger.info("flagging canonical-only parents in %s", main_parent_selection_path)
    df = pl.read_parquet(main_parent_selection_path)

    genre_ids = df.filter(~pl.col("is_regional_overview")).select("item_id").unique().to_series().to_list()
    df = df.with_columns(
        parent_is_canonical=pl.when(pl.col("parent_id").is_null())
        .then(None)
        .otherwise(pl.col("parent_id").is_in(genre_ids))
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "6_canonical_parents.parquet"
    df.write_parquet(output_path)
    logger.info(
        "wrote %d rows to %s (%d non-canonical parent edges flagged)",
        df.height,
        output_path,
        df.filter(~pl.col("parent_is_canonical")).height,
    )

    return output_path
