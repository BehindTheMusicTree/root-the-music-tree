# Schema

Data dictionary and lineage notes for `wikidata`. See [DESIGN.md](DESIGN.md) for the rationale and
rules behind each step, and [README.md#pipeline](README.md#pipeline) for the top-to-bottom
pipeline overview.

## Table of Contents

- [Schema](#schema)
  - [Table of Contents](#table-of-contents)
  - [1. Wikidata properties used](#1-wikidata-properties-used)
    - [1.1 P31 ("instance of")](#11-p31-instance-of)
    - [1.2 P279 ("subclass of")](#12-p279-subclass-of)
    - [1.3 P361 ("part of")](#13-p361-part-of)
    - [1.4 P2341 ("indigenous to")](#14-p2341-indigenous-to)
    - [1.5 P495 ("country of origin")](#15-p495-country-of-origin)
  - [2. Bronze](#2-bronze)
    - [2.1 wikidata_genre_tree.parquet](#21-wikidata_genre_treeparquet)
    - [2.2 wikidata_genre_indigenous_to.parquet](#22-wikidata_genre_indigenous_toparquet)
    - [2.3 wikidata_genre_country_of_origin.parquet](#23-wikidata_genre_country_of_originparquet)
  - [3. Silver](#3-silver)
    - [3.1 Overview](#31-overview)
    - [3.2 1_item_links](#32-1_item_links)
    - [3.3 2_regional_overview_classification](#33-2_regional_overview_classification)
    - [3.4 3_regional_classification](#34-3_regional_classification)
    - [3.5 4_genre_parents](#35-4_genre_parents)
    - [3.6 5_hierarchy](#36-5_hierarchy)
    - [3.7 6_canonical_roots](#37-6_canonical_roots)

## 1. Wikidata properties used

Wikidata models knowledge as items (`Q...` IDs) connected by properties (`P...` IDs). Five
properties drive this pipeline's whole shape.

The three taxonomy properties (`P31`, `P279`, `P361`) are not interchangeable and don't chain into
each other the way you might expect — see [DESIGN.md#1-bronze](DESIGN.md#1-bronze). `P2341` and
`P495` are separate, orthogonal kinds of edges (item-to-people and item-to-country, not
item-to-item taxonomy) and aren't part of that chaining discussion.

### 1.1 P31 ("instance of")

Links an item to the class it directly belongs to. `wd:Q11399` ("rock music") `wdt:P31`
`wd:Q188451` ("music genre") means "rock music is a music genre." This is Wikidata's
class-membership edge — it's how Bronze finds the full set of genre items in the first place (see
`GENRE_TREE_QUERY`'s `?item wdt:P31 wd:Q188451` clause).

### 1.2 P279 ("subclass of")

Links a class to its more general parent class(es), building a taxonomy. `wd:Q11399` ("rock
music") `wdt:P279` `wd:Q373342` ("popular music") means "rock music is a kind of popular music."
This is the main edge that builds the genre _hierarchy_ — a genre can have more than one `P279`
parent, since Wikidata classes aren't a strict tree.

### 1.3 P361 ("part of")

A meronymic (part-whole, not is-a) edge, used inconsistently across genre items in place of or
alongside `P279` for what is still, in practice, subgenre-of-genre information. It's sparser than
`P279` (~250 edges vs. ~9,000) and noisier (most `P361` targets aren't themselves a `P31` music
genre — e.g. "punk subculture"), but a meaningful minority of edges are hierarchy information
`P279` doesn't have at all — e.g. several juke/footwork/ghetto house subgenres are only linked to
their parent via `P361`. Bronze ingests the full `P361` edge set raw and unfiltered, just as it
already does for `P279`, tagged by `relation_type` (see below) so consumers can tell the two edge
types apart rather than silently merging two different semantics into one column.

### 1.4 P2341 ("indigenous to")

Links an item to the people/ethnic group it originates from (e.g. `wd:Q10376827` "Han Chinese
music" `wdt:P2341` `wd:Q49103` "Han Chinese"). This is an ethnographic attribute of the item
itself, not a genre-to-genre taxonomy edge like `P279`/`P361` — its cardinality is independent of
an item's parent count, so it's ingested into its own Bronze table
(`wikidata_genre_indigenous_to.parquet`, see below) rather than into `wikidata_genre_tree.parquet`.
See [DESIGN.md#22-3_regional_classification](DESIGN.md#22-3_regional_classification) for why it's
needed.

### 1.5 P495 ("country of origin")

Links an item to the country it originated in (e.g. `wd:Q1198131` "morna" `wdt:P495` `wd:Q1011`
"Cape Verde"). Same shape as `P2341` above: a per-item attribute, not a genre-to-genre taxonomy
edge, independent of an item's `P279`/`P361` parent count, so it's ingested into its own Bronze
table (`wikidata_genre_country_of_origin.parquet`, see below) rather than into
`wikidata_genre_tree.parquet`. See
[DESIGN.md#22-3_regional_classification](DESIGN.md#22-3_regional_classification) for why it's not
used as a classification signal.

## 2. Bronze

Three Parquet files, one per query in `wikidata_client.py`. See
[DESIGN.md#1-bronze](DESIGN.md#1-bronze) for why `P31` (not a `P279*` walk) is the root query, why
parents aren't restricted to genre items, and why `P2341`/`P495` are ingested into their own tables
instead of `wikidata_genre_tree.parquet`.

### 2.1 wikidata_genre_tree.parquet

One row per (item, parent, relation_type) edge: every Wikidata item classified `P31` ("instance
of") `Q188451` ("music genre") — the class extension, ~6,300 items as of this writing — plus each
genre's direct `P279` ("subclass of") and `P361` ("part of") parent(s). See
`wikidata_client.GENRE_TREE_QUERY` for the exact SPARQL.

An item with neither a `P279` nor a `P361` parent (a root, ~486 of them as of this writing — down
from ~510 pre-`P361`, since 22 formerly-root items turned out to have only a `P361` parent) gets a
single row with `parent_id`/`parent_label`/`relation_type` all null.

| Column        | Type | Meaning                                                                          |
| ------------- | ---- | ---------------------------------------------------------------------------------- |
| item_id       | str  | Wikidata QID of the genre (e.g. `Q11399`)                                        |
| item_label    | str  | Label for `item_id` (English, falling back to a language-agnostic `mul` label if no English label exists) (e.g. "rock music")                                  |
| parent_id     | str? | QID of a direct `P279`/`P361` parent within the genre tree, or null              |
| parent_label  | str? | Same fallback as `item_label`, for `parent_id`, or null                                           |
| relation_type | str? | `"P279"` or `"P361"` — which property produced this edge, or null for a root row |

A multi-parent item (Wikidata classes aren't a strict tree — a genre can have more than one
`P279`/`P361` parent) produces one row per parent, so `item_id` is not unique on its own.

### 2.2 wikidata_genre_indigenous_to.parquet

One row per (item, indigenous-to-group) pair: every `P31` music genre item that also has at least
one `P2341` ("indigenous to") value. Unlike `wikidata_genre_tree.parquet`, items with no `P2341`
value are absent entirely — there is no "root row" placeholder, since absence of an ethnographic
tag isn't a hierarchy position the way a missing parent is. See
`wikidata_client.INDIGENOUS_TO_QUERY`.

| Column               | Type | Meaning                                                             |
| -------------------- | ---- | ---------------------------------------------------------------------- |
| item_id               | str  | Wikidata QID of the genre (e.g. `Q10376827`)                        |
| indigenous_to_id      | str  | Wikidata QID of the people/ethnic group (e.g. `Q49103`)              |
| indigenous_to_label   | str  | Same English/`mul`-fallback label as `item_label`, for `indigenous_to_id` (e.g. "Han Chinese")            |

A genre with several `P2341` values produces one row per value, so `item_id` is not unique on its
own (as of this writing: 207 rows).

### 2.3 wikidata_genre_country_of_origin.parquet

One row per (item, country) pair: every `P31` music genre item that also has at least one `P495`
("country of origin") value. Same absence rule as `wikidata_genre_indigenous_to.parquet` — items
with no `P495` value are absent entirely, no "root row" placeholder. See
`wikidata_client.COUNTRY_OF_ORIGIN_QUERY`.

| Column                  | Type | Meaning                                                        |
| ------------------------ | ---- | ----------------------------------------------------------------- |
| item_id                  | str  | Wikidata QID of the genre (e.g. `Q1198131`)                    |
| country_of_origin_id     | str  | Wikidata QID of the country (e.g. `Q1011`)                     |
| country_of_origin_label  | str  | Same English/`mul`-fallback label as `item_label`, for `country_of_origin_id` (e.g. "Cape Verde")   |

A genre with several `P495` values produces one row per value, so `item_id` is not unique on its
own (as of this writing: 2,496 rows).

## 3. Silver

All five steps below are produced by `wikidata.silver`. `1_item_links`,
`2_regional_overview_classification`, `3_regional_classification`, and `4_genre_parents` preserve
the Bronze edge-list grain 1:1 (`item_id` still not unique) — none of them drop rows; downstream
consumers filter on the added columns themselves. `5_hierarchy` is different: it's the first step
that actually drops rows, and the first where `item_id` is unique — see below.

### 3.1 Overview

| Step                                                                        | Reads                                        | Writes                                                                       | Adds                                | Key result (as of this writing)                                                                                                                                                 |
| --------------------------------------------------------------------------- | -------------------------------------------- | ---------------------------------------------------------------------------- | ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`1_item_links`](#32-1_item_links)                                          | Bronze `wikidata_genre_tree.parquet`         | `1_item_links.parquet`                                                       | `item_url`, `parent_url`, `has_item_label`, `has_parent_label` | `item_url` populated for all 9,729 rows; `parent_url` null only for the 486 root rows                                                                                            |
| [`2_regional_overview_classification`](#33-2_regional_overview_classification) | `1_item_links.parquet`                       | `2_regional_overview_classification.parquet`                                 | `is_regional_overview`, `classification_reason` | 401 of 9,729 rows (299 of 6,344 items) tagged `is_regional_overview = true` / `regional_overview` (e.g. "music of Kenya") — not dropped                                          |
| [`3_regional_classification`](#34-3_regional_classification)                | `2_regional_overview_classification.parquet`, Bronze `wikidata_genre_indigenous_to.parquet`, `manual_regional_overrides.csv` | `3_regional_classification.parquet`                                          | `is_regional`, `regional_reason`    | 3,879 of 6,404 items flagged `is_regional` — 359 seed, 179 indigenous_to, 180 manual_override, 1,614 direct, 1,547 inherited (see [DESIGN.md#22-3_regional_classification](DESIGN.md#22-3_regional_classification))                                      |
| [`4_genre_parents`](#35-4_genre_parents)                                    | `3_regional_classification.parquet`          | `4_genre_parents.parquet`                                                    | `parent_is_genre`                   | 2,989 of 9,729 rows have a non-genre parent; 486 rows are roots (`parent_is_genre = null`)                                                                                      |
| [`5_hierarchy`](#36-5_hierarchy)                                            | `4_genre_parents.parquet`                    | `5_hierarchy.parquet` (canonical), `5_regional_hierarchy.parquet` (regional) | prunes to one row per `item_id`     | canonical: 806 final rows from 1,017 items; regional: 5,327 final rows from 5,327 items (seed items are real nodes, not promoted synthetic roots); 211 items vanish from both |
| [`6_canonical_roots`](#37-6_canonical_roots)                                | `5_hierarchy.parquet`                        | `6_canonical_roots.parquet`                                                  | filters to `parent_id = null`       | 297 root items, for manual exploration of the "too many roots" open question (see [DESIGN.md#24-5_hierarchy](DESIGN.md#24-5_hierarchy)) |

Each step's own section below has the full column definitions and profiling detail behind these
numbers; see [DESIGN.md](DESIGN.md) for why each step exists and its rules.

### 3.2 1_item_links

`1_item_links.parquet`: `wikidata_genre_tree.parquet` (Bronze) unchanged, plus two columns giving
the human-browsable Wikidata page for `item_id` and, where present, `parent_id`, and two columns
flagging whether `item_label`/`parent_label` are a real label or the QID-fallback string.

| Column           | Type | Meaning                                                                            |
| ---------------- | ---- | ----------------------------------------------------------------------------------- |
| item_url         | str  | `https://www.wikidata.org/wiki/` + `item_id` — the item's browsable Wikidata page   |
| parent_url       | str? | `https://www.wikidata.org/wiki/` + `parent_id`, or null when `parent_id` is null    |
| has_item_label   | bool | `False` when `item_label == item_id` (Wikidata's label service found no English/`mul` label and fell back to printing the QID) |
| has_parent_label | bool? | Same check for `parent_label`/`parent_id`, or null when `parent_id` is null       |

**Data profile (as of this writing):**

| Metric                                     |  Rows | Distinct `item_id`s |
| ------------------------------------------- | ----: | -------------------: |
| Total                                       | 9,729 |                6,344 |
| `parent_url` populated                      | 9,243 |                    — |
| `parent_url` null (root, `parent_id` null)  |   486 |                    — |

Regenerate with `uv run --package wikidata python -m wikidata.silver.profile` (reads
`SILVER_OUTPUT_DIR/1_item_links.parquet`, read-only, no new data fetched) — these numbers will
drift as Wikidata's live genre tree changes.

### 3.3 2_regional_overview_classification

`2_regional_overview_classification.parquet`: `1_item_links.parquet` unchanged, plus two
columns classifying whether each row's `item_id` is a regional-overview article (e.g. "music of Kenya")
rather than an actual musical style. See
[DESIGN.md#21-2_regional_overview_classification](DESIGN.md#21-2_regional_overview_classification)
for why this classification exists, its rule, and the manual-CSV backstop mechanics.

| Column                | Type | Meaning                                                                                    |
| --------------------- | ---- | -------------------------------------------------------------------------------------------- |
| is_regional_overview  | bool | `True` if `item_label` was classified as a regional overview article, not a musical style     |
| classification_reason | str? | Why `is_regional_overview` is `True`, or null when `is_regional_overview` is `False`         |

**Data profile (as of this writing):**

| Metric                                        |  Rows | Distinct `item_id`s |
| ---------------------------------------------- | ----: | ------------------: |
| Total                                          | 9,729 |               6,344 |
| `is_regional_overview = false`                 | 9,328 |               6,045 |
| `is_regional_overview = true` (`regional_overview`) |   401 |                 299 |

Regenerate with `uv run --package wikidata python -m wikidata.silver.profile` (reads
`SILVER_OUTPUT_DIR/2_regional_overview_classification.parquet`, read-only, no new data fetched) — these numbers
will drift as Wikidata's live genre tree changes.

### 3.4 3_regional_classification

`3_regional_classification.parquet`: `2_regional_overview_classification.parquet` unchanged, plus two columns
flagging whether each row's `item_id` is a **regional genre** — nationally or ethnically specific
(e.g. "morna", "fado", and the "music of X" seed items themselves), as opposed to a genre with no
particular regional grounding (e.g. "rock music"). See
[DESIGN.md#22-3_regional_classification](DESIGN.md#22-3_regional_classification) for why this step
reads the extra Bronze/CSV inputs, its seeding/cascade rule, and open caveats.

| Column          | Type | Meaning                                                                               |
| --------------- | ---- | ------------------------------------------------------------------------------------- |
| is_regional     | bool | Whether `item_id` is a regional genre — set for every item, including non-genre items |
| regional_reason | str? | `"seed"`, `"indigenous_to"`, `"manual_override"`, `"direct"`, `"inherited"`, or null |

**Data profile (as of this writing):**

| Metric                                   | Distinct items |
| ----------------------------------------- | -------------: |
| Total items                               |          6,404 |
| `is_regional = true`                      |          3,879 |
| `is_regional = false`                     |          2,525 |
| `regional_reason = "seed"`                |            359 |
| `regional_reason = "indigenous_to"`       |            179 |
| `regional_reason = "manual_override"`     |            180 |
| `regional_reason = "direct"`              |          1,614 |
| `regional_reason = "inherited"`           |          1,547 |

Regenerate with `uv run --package wikidata python -m wikidata.silver.profile` (reads
`SILVER_OUTPUT_DIR/3_regional_classification.parquet`, read-only, no new data fetched) — these
numbers will drift as Wikidata's live genre tree changes.

### 3.5 4_genre_parents

`4_genre_parents.parquet`: `3_regional_classification.parquet` unchanged, plus one column flagging
whether each row's `parent_id` is itself an actual musical style. See
[DESIGN.md#23-4_genre_parents](DESIGN.md#23-4_genre_parents) for the manual-CSV backstop this step
applies before that flag is computed, and the classification rule.

| Column          | Type  | Meaning                                                                                                                    |
| --------------- | ----- | -------------------------------------------------------------------------------------------------------------------------- |
| parent_is_genre | bool? | Whether `parent_id` is `is_regional_overview = False` in `2_regional_overview_classification`; null for root rows (`parent_id` is null) |

**Data profile (as of this writing):**

| Metric                                     |  Rows |
| ------------------------------------------ | ----: |
| Total                                      | 9,729 |
| `parent_is_genre = true`                   | 6,254 |
| `parent_is_genre = false`                  | 2,989 |
| `parent_is_genre = null` (root, no parent) |   486 |

Regenerate with `uv run --package wikidata python -m wikidata.silver.profile` (reads
`SILVER_OUTPUT_DIR/4_genre_parents.parquet`, read-only, no new data fetched) — these numbers will
drift as Wikidata's live genre tree changes.

### 3.6 5_hierarchy

`5_hierarchy.parquet` (canonical) and `5_regional_hierarchy.parquet` (regional): the first Silver
step that actually prunes rather than flags. Reads `4_genre_parents.parquet` and reduces it to one
row per genre item, split into two clean, directly-consumable genre hierarchy edge lists — a
canonical one, excluding every `is_regional = true` item, and a regional one, containing only
`is_regional = true` items (which now includes the `regional_overview` seed items themselves). See
[DESIGN.md#24-5_hierarchy](DESIGN.md#24-5_hierarchy) for the manual-CSV inputs this step also
reads, the two-stage pruning/collapse rule, and the open "too many roots" exploration.

| Column        | Type | Meaning                                                                          |
| ------------- | ---- | ---------------------------------------------------------------------------------- |
| item_id       | str  | Wikidata QID of the genre (e.g. `Q11399`) — **unique in this table**             |
| item_label    | str  | Same English/`mul`-fallback label as in `1_item_links` (see above), for `item_id`                                                      |
| item_url      | str  | `https://www.wikidata.org/wiki/` + `item_id`                                     |
| parent_id     | str? | QID of the single chosen parent, or null for a root                              |
| parent_label  | str? | Same fallback as `item_label`, for `parent_id`, or null                                           |
| parent_url    | str? | `https://www.wikidata.org/wiki/` + `parent_id`, or null for a root row           |
| relation_type | str? | `"P279"` or `"P361"` — which property produced this edge, or null for a root row |

**Data profile (as of this writing):**

| Metric                                    | Canonical (`5_hierarchy`) | Regional (`5_regional_hierarchy`) |
| ----------------------------------------- | ------------------------: | --------------------------------: |
| Genre items in scope (distinct `item_id`) |                     1,016 |                             5,328 |
| Final rows (= distinct `item_id`s)        |                       805 |                             5,328 |
| Root rows (`parent_id = null`)            |                       297 |                                417 |

Genre items with zero surviving rows in _either_ output (the canonical-style silent vanish): **211**
— all non-regional, i.e. every one is an "opera"-shaped item, not a regional one. See
[DESIGN.md#24-5_hierarchy](DESIGN.md#24-5_hierarchy) for why the two outputs diverge here.

Regenerate with `uv run --package wikidata python -m wikidata.silver.profile` (reads
`SILVER_OUTPUT_DIR/4_genre_parents.parquet`, `SILVER_OUTPUT_DIR/5_hierarchy.parquet`, and
`SILVER_OUTPUT_DIR/5_regional_hierarchy.parquet`, read-only, no new data fetched) — these numbers
will drift as Wikidata's live genre tree changes.

### 3.7 6_canonical_roots

`6_canonical_roots.parquet`: `5_hierarchy.parquet` filtered to rows where `parent_id` is null
(root items) and reduced to the three item-identifying columns, sorted by `item_label`. Exists
purely to make manual exploration of the "too many roots" open question
([DESIGN.md#24-5_hierarchy](DESIGN.md#24-5_hierarchy)) easier — a ready-to-open list of exactly the
items in question, instead of re-deriving the filter each time (as
`notebooks/explore_genre_tree.ipynb` currently does inline). Not consumed by any later step and not
itself part of the pruning chain — it's a read view of `5_hierarchy`, not new information.

| Column     | Type | Meaning                                       |
| ---------- | ---- | ---------------------------------------------- |
| item_id    | str  | Wikidata QID of the root genre (e.g. `Q11399`) |
| item_label | str  | English label for `item_id`                    |
| item_url   | str  | `https://www.wikidata.org/wiki/` + `item_id`   |

**Data profile (as of this writing):** 297 rows — see
[DESIGN.md#24-5_hierarchy](DESIGN.md#24-5_hierarchy)'s "Under exploration" callout for context on
why this count is expected to shrink as the multi-parent collapse heuristic and regional
classification rules mature.
