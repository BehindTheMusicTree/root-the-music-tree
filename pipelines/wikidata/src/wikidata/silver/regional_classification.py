import logging
from pathlib import Path

import polars as pl

from wikidata.silver.regional_overview_classification import MANUAL_OVERVIEW_RECLASSIFICATION_REASON

logger = logging.getLogger(__name__)

WIKIDATA_ITEM_URL_PREFIX = "https://www.wikidata.org/wiki/"

# Committed alongside the code (not a gitignored bronze/silver output) because it's hand-curated,
# not fetched from Wikidata: genres that slip through the automated seed/indigenous_to/
# country_of_origin classification below (e.g. roots with no P279/P361 parent and no P2341/P495
# value) get added here by a data expert reviewing 5_canonical_hierarchy's root list, with a `reason` for
# each entry. `overview_item_id` is the `item_id` of the `regional_overview` item (e.g. "music of
# Japan" — normally a real QID, but may be a synthetic `LOCAL:` id, see regional_overview_classification.py)
# the override item nests under in 5_regional_hierarchy — required, since these override items
# typically have no P279/P361 parent and would otherwise surface as their own orphan root in the
# regional tree instead of sitting under their region. See DESIGN.md#22-3_regional_classification.
MANUAL_OVERRIDES_PATH = Path(__file__).parent / "manual_regional_overrides.csv"

# Committed alongside the code (not a gitignored bronze/silver output) because it's hand-curated,
# not fetched from Wikidata: genre items organized around a subject/theme/subculture (e.g. "LGBT
# music", "steampunk music", "bronycore") rather than a geography, ethnicity, or musical style
# don't belong in either the canonical or regional genre tree. A data expert reviewing the root
# lists adds them here with a `reason`. Dropped before the regional cascade below runs (not just
# at the final hierarchy.py pruning step) so a dropped item can never sit on a cascade path and
# hand its (unrelated) is_regional status down to a real genre beneath it.
MANUAL_THEME_GENRES_PATH = Path(__file__).parent / "manual_theme_genres.csv"

# Same mechanism as MANUAL_THEME_GENRES_PATH, but for items that are a compositional/performance
# technique (e.g. "crab canon", "fauxbourdon", "call and response") rather than a genre at all — no
# automated signal distinguishes a technique from a genre either, so a data expert reviewing the
# root lists adds them here by hand. Dropped identically to theme items.
MANUAL_TECHNIQUE_GENRES_PATH = Path(__file__).parent / "manual_technique_genres.csv"

# Same mechanism as MANUAL_THEME_GENRES_PATH, but for items that are simply not a music genre at
# all — Wikidata's P31 "music genre" classification was wrong (e.g. a near-empty stub with no real
# description, a record label, an event, a person) rather than the item being a real genre that's
# off-topic (that's MANUAL_THEME_GENRES_PATH) or a technique (MANUAL_TECHNIQUE_GENRES_PATH). No
# automated signal distinguishes this either, so it's curated by hand the same way, and dropped
# identically.
MANUAL_OUT_OF_SCOPE_GENRES_PATH = Path(__file__).parent / "manual_out_of_scope_genres.csv"


def _load_dropped_ids(df: pl.DataFrame, manual_csv: pl.DataFrame, csv_name: str) -> set[str]:
    if "item_id" not in manual_csv.columns:
        raise ValueError(f"{csv_name} is missing the required 'item_id' column")
    manual_csv = manual_csv.with_columns(pl.col("item_id").cast(pl.Utf8).str.strip_chars())
    blank = manual_csv.filter(pl.col("item_id").is_null() | (pl.col("item_id") == ""))
    if not blank.is_empty():
        raise ValueError(f"{csv_name} has row(s) with a null/blank 'item_id'")

    dropped_item_ids = manual_csv.select("item_id").to_series().to_list()
    if len(dropped_item_ids) != len(set(dropped_item_ids)):
        raise ValueError(f"{csv_name} contains duplicate item_id rows")

    known_item_ids = set(df.select("item_id").unique().to_series())
    dropped_ids = set(manual_csv.select("item_id").unique().to_series())
    unknown_item_ids = sorted(item_id for item_id in dropped_ids if item_id not in known_item_ids)
    if unknown_item_ids:
        raise ValueError(f"{csv_name} rows reference item_id(s) not found in the genre tree: {unknown_item_ids}")
    return dropped_ids


def _apply_overview_overrides(df: pl.DataFrame, manual_overrides: pl.DataFrame) -> pl.DataFrame:
    if "overview_item_id" not in manual_overrides.columns:
        raise ValueError("manual_regional_overrides.csv is missing the required 'overview_item_id' column")
    manual_overrides = manual_overrides.with_columns(pl.col("overview_item_id").cast(pl.Utf8))
    missing = manual_overrides.filter(
        pl.col("overview_item_id").is_null() | (pl.col("overview_item_id").str.strip_chars() == "")
    )
    if not missing.is_empty():
        missing_ids = missing.select("item_id").to_series().to_list()
        raise ValueError(f"manual_regional_overrides.csv rows missing required 'overview_item_id': {missing_ids}")
    overrides = manual_overrides.with_columns(overview_item_id=pl.col("overview_item_id").str.strip_chars())

    known_item_ids = set(df.select("item_id").unique().to_series())
    unknown_item_ids = [
        item_id for item_id in overrides.select("item_id").unique().to_series() if item_id not in known_item_ids
    ]
    if unknown_item_ids:
        raise ValueError(
            f"manual_regional_overrides.csv rows reference item_id(s) not found in the genre tree: {unknown_item_ids}"
        )
    unknown_overview_item_ids = [
        overview_item_id
        for overview_item_id in overrides.select("overview_item_id").unique().to_series()
        if overview_item_id not in known_item_ids
    ]
    if unknown_overview_item_ids:
        raise ValueError(
            "manual_regional_overrides.csv rows reference overview_item_id(s) not found in the genre tree: "
            f"{unknown_overview_item_ids}"
        )
    regional_overview_ids = set(df.filter(pl.col("is_regional_overview")).select("item_id").unique().to_series())
    non_regional_overview_ids = [
        overview_item_id
        for overview_item_id in overrides.select("overview_item_id").unique().to_series()
        if overview_item_id not in regional_overview_ids
    ]
    if non_regional_overview_ids:
        raise ValueError(
            "manual_regional_overrides.csv rows reference overview_item_id(s) not flagged is_regional_overview "
            f"in the genre tree: {non_regional_overview_ids}"
        )

    overview_labels = (
        df.select("item_id", "item_label")
        .unique(subset="item_id")
        .rename({"item_id": "overview_item_id", "item_label": "overview_item_label"})
    )
    item_columns = [c for c in df.columns if c not in ("parent_id", "parent_label", "parent_url", "relation_type")]
    synthetic_edges = (
        overrides.select("item_id", "overview_item_id")
        .join(overview_labels, on="overview_item_id", how="left")
        .join(df.select(item_columns).unique(subset="item_id"), on="item_id", how="left")
        .with_columns(
            parent_id=pl.col("overview_item_id"),
            parent_label=pl.col("overview_item_label"),
            parent_url=pl.lit(WIKIDATA_ITEM_URL_PREFIX) + pl.col("overview_item_id"),
            relation_type=pl.lit("manual_override_parent"),
        )
    )
    if "has_parent_label" in df.columns:
        synthetic_edges = synthetic_edges.with_columns(
            has_parent_label=pl.col("overview_item_label").is_not_null()
            & (pl.col("overview_item_label") != pl.col("overview_item_id"))
        )
    synthetic_edges = synthetic_edges.select(df.columns)

    overridden_ids = set(overrides.select("item_id").unique().to_series())
    df = df.filter(~(pl.col("item_id").is_in(list(overridden_ids)) & pl.col("parent_id").is_null()))
    return pl.concat([df, synthetic_edges])


def classify_regional_genres(
    regional_overview_classification_path: Path,
    indigenous_to_path: Path,
    manual_overrides_path: Path,
    manual_theme_genres_path: Path,
    manual_technique_genres_path: Path,
    manual_out_of_scope_genres_path: Path,
    output_dir: Path,
) -> Path:
    logger.info("classifying regional genres in %s", regional_overview_classification_path)
    df = pl.read_parquet(regional_overview_classification_path)

    manual_theme_genres = pl.read_csv(manual_theme_genres_path)
    manual_technique_genres = pl.read_csv(manual_technique_genres_path)
    manual_out_of_scope_genres = pl.read_csv(manual_out_of_scope_genres_path)
    theme_ids = _load_dropped_ids(df, manual_theme_genres, "manual_theme_genres.csv")
    technique_ids = _load_dropped_ids(df, manual_technique_genres, "manual_technique_genres.csv")
    out_of_scope_ids = _load_dropped_ids(df, manual_out_of_scope_genres, "manual_out_of_scope_genres.csv")
    dropped_ids = theme_ids | technique_ids | out_of_scope_ids
    # Dropped before the cascade below runs: a dropped item's own row disappears entirely, so no
    # parent edge can point *into* it by the time seed_ids/direct_ids/the frontier loop run, and any
    # edge that pointed *out of* it is gone along with the row. See hierarchy.py's _prune_canonical/
    # _prune_regional for how a severed edge like this still surfaces the child as a root instead of
    # vanishing it.
    df = df.filter(~pl.col("item_id").is_in(list(dropped_ids)))

    indigenous_ids = set(pl.read_parquet(indigenous_to_path).select("item_id").unique().to_series())
    manual_overrides = pl.read_csv(manual_overrides_path)
    manual_override_ids = set(manual_overrides.select("item_id").unique().to_series())
    df = _apply_overview_overrides(df, manual_overrides)

    # Seeds: the "music of <place>" items themselves (plus items reclassified into that same
    # non-genre-overview role via manual_overview_reclassifications.csv, e.g. "European folk music"
    # — see regional_overview_classification.py), plus every item Wikidata's P2341 ("indigenous to")
    # flags as belonging to a specific people (e.g. "Han Chinese music" -> "Han Chinese people", see
    # bronze wikidata_genre_indigenous_to.parquet), plus anything a data expert has hand-flagged in
    # manual_regional_overrides.csv for genres none of the automated sources catch. P495 ("country of
    # origin") is deliberately not used as a seed source: it's set on broad canonical umbrella genres
    # too (jazz -> United States, heavy metal music -> United Kingdom), which would wrongly cascade
    # regional status onto their real subgenres. All remaining sets are tagged non-genre or
    # nationally/ethnically-specific in their own right but are not excluded from the regional graph
    # — they're regional genre nodes themselves (see hierarchy.py), and together form the seed set
    # every other regional flag propagates from. A genre item is "direct" regional if any one of its
    # parent edges points at a seed — not all of them, since e.g. "Australian rock" has one parent
    # into "rock music" (clean) and another into "music of Australia" (a seed), and is still
    # considered regional. Regional status then cascades to children layer by layer: any genre item
    # with a parent edge into an already-regional item is "inherited" regional, repeated until no new
    # items are found.
    seed_ids = set(
        df.filter(pl.col("classification_reason").is_in(["regional_overview", MANUAL_OVERVIEW_RECLASSIFICATION_REASON]))
        .select("item_id")
        .unique()
        .to_series()
    )
    source_ids = seed_ids | indigenous_ids | manual_override_ids
    direct_ids = set(
        df.filter(
            ~pl.col("is_regional_overview")
            & pl.col("parent_id").is_in(list(source_ids))
            & ~pl.col("item_id").is_in(list(source_ids))
        )
        .select("item_id")
        .unique()
        .to_series()
    )

    regional_ids = set(direct_ids) | indigenous_ids | manual_override_ids
    frontier = set(regional_ids)
    while frontier:
        candidates = df.filter(
            ~pl.col("is_regional_overview")
            & pl.col("parent_id").is_in(list(frontier))
            & ~pl.col("item_id").is_in(list(regional_ids | source_ids))
        )
        frontier = set(candidates.select("item_id").unique().to_series())
        regional_ids |= frontier

    df = df.with_columns(
        is_regional=pl.when(pl.col("item_id").is_in(list(seed_ids)))
        .then(pl.lit(True))
        .when(pl.col("is_regional_overview"))
        .then(None)
        .when(pl.col("item_id").is_in(list(indigenous_ids)))
        .then(pl.lit(True))
        .when(pl.col("item_id").is_in(list(manual_override_ids)))
        .then(pl.lit(True))
        .when(pl.col("item_id").is_in(list(direct_ids)))
        .then(pl.lit(True))
        .otherwise(pl.col("item_id").is_in(list(regional_ids))),
        regional_reason=pl.when(pl.col("item_id").is_in(list(seed_ids)))
        .then(pl.lit("seed"))
        .when(pl.col("item_id").is_in(list(indigenous_ids)))
        .then(pl.lit("indigenous_to"))
        .when(pl.col("item_id").is_in(list(manual_override_ids)))
        .then(pl.lit("manual_override"))
        .when(pl.col("item_id").is_in(list(direct_ids)))
        .then(pl.lit("direct"))
        .when(pl.col("item_id").is_in(list(regional_ids)))
        .then(pl.lit("inherited"))
        .otherwise(None),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "3_regional_classification.parquet"
    df.write_parquet(output_path)
    regional_counts = df.filter(pl.col("is_regional")).unique("item_id").group_by("regional_reason").len().to_dicts()
    logger.info(
        "wrote %d rows to %s (regional items by reason: %s)",
        df.height,
        output_path,
        regional_counts,
    )

    return output_path
