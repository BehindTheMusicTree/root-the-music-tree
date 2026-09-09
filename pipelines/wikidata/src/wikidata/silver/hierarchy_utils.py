import polars as pl

OUTPUT_COLUMNS = ["item_id", "item_label", "item_url", "parent_id", "parent_label", "parent_url", "relation_type"]


def collapse_to_lowest_qid(edges: pl.DataFrame) -> pl.DataFrame:
    # Wikidata's P279/P361 graph isn't a strict tree: ~43% of genre items have more than one
    # surviving genre parent, and only 1 item in the whole extension has a "preferred rank" P279
    # statement to disambiguate with (checked live). No reliable signal exists, so — provisionally,
    # pending a real product/curation decision — keep only the lowest-QID parent per item. This is
    # a tâtonnement placeholder, not a considered rule; see DESIGN.md#25-6_canonical_hierarchy.
    return (
        edges.with_columns(parent_numeric_id=pl.col("parent_id").str.slice(1).cast(pl.Int64, strict=False))
        .sort(["item_id", "parent_numeric_id"])
        .unique(subset="item_id", keep="first")
        .select(OUTPUT_COLUMNS)
    )


def promote_orphans_to_roots(items: pl.DataFrame, collapsed: pl.DataFrame) -> pl.DataFrame:
    orphans = (
        items.select("item_id", "item_label", "item_url")
        .unique(subset="item_id")
        .join(collapsed.select("item_id"), on="item_id", how="anti")
        .with_columns(
            parent_id=pl.lit(None, dtype=pl.Utf8),
            parent_label=pl.lit(None, dtype=pl.Utf8),
            parent_url=pl.lit(None, dtype=pl.Utf8),
            relation_type=pl.lit(None, dtype=pl.Utf8),
        )
        .select(OUTPUT_COLUMNS)
    )
    return pl.concat([collapsed, orphans])
