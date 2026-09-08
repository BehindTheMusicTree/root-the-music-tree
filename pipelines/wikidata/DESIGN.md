# Design

Design rationale, classification rules, and manual-CSV curation mechanics for `wikidata`'s Silver
pipeline. See [SCHEMA.md](SCHEMA.md) for column definitions and data profiles.

## Table of Contents

- [Design](#design)
  - [Table of Contents](#table-of-contents)
  - [1. Bronze](#1-bronze)
    - [1.1 wikidata_genre_tree.parquet](#11-wikidata_genre_treeparquet)
      - [1.1.1 Why `P31`, not a `P279*` walk from `Q188451`](#111-why-p31-not-a-p279-walk-from-q188451)
      - [1.1.2 Parents are not restricted to also being a music genre instance](#112-parents-are-not-restricted-to-also-being-a-music-genre-instance)
      - [1.1.3 Bare QIDs, not full entity URIs](#113-bare-qids-not-full-entity-uris)
    - [1.2 wikidata_genre_indigenous_to.parquet and wikidata_genre_country_of_origin.parquet](#12-wikidata_genre_indigenous_toparquet-and-wikidata_genre_country_of_originparquet)
      - [1.2.1 Why separate tables, not extra columns on `wikidata_genre_tree.parquet`](#121-why-separate-tables-not-extra-columns-on-wikidata_genre_treeparquet)
  - [2. Silver](#2-silver)
    - [2.1 2_regional_overview_classification](#21-2_regional_overview_classification)
      - [2.1.1 Why classification is needed](#211-why-classification-is-needed)
      - [2.1.2 `classification_reason` values](#212-classification_reason-values)
      - [2.1.3 Auto-promotion of orphan `"music of "` parents](#213-auto-promotion-of-orphan-music-of--parents)
      - [2.1.4 Manual addition of overview items missing from Bronze entirely](#214-manual-addition-of-overview-items-missing-from-bronze-entirely)
      - [2.1.5 Manual reclassification of existing items as overview](#215-manual-reclassification-of-existing-items-as-overview)
      - [2.1.6 Scope of this first pass](#216-scope-of-this-first-pass)
    - [2.2 3_regional_classification](#22-3_regional_classification)
      - [2.2.1 Inputs](#221-inputs)
      - [2.2.2 Rule: four seed sources](#222-rule-four-seed-sources)
      - [2.2.3 Cascade](#223-cascade)
    - [2.3 4_genre_parents](#23-4_genre_parents)
      - [2.3.1 `manual_canonical_parents.csv` backstop](#231-manual_canonical_parentscsv-backstop)
      - [2.3.2 Rule: what counts as a genre parent](#232-rule-what-counts-as-a-genre-parent)
    - [2.4 5_hierarchy](#24-5_hierarchy)
      - [2.4.1 Manual CSV backstops](#241-manual-csv-backstops)
      - [2.4.2 Rule: two-stage pruning](#242-rule-two-stage-pruning)
      - [2.4.3 Known consequence — the two outputs diverge here](#243-known-consequence--the-two-outputs-diverge-here)

## 1. Bronze

Three queries, three Parquet files — see [SCHEMA.md#2-bronze](SCHEMA.md#2-bronze) for their column
definitions and data profiles.

### 1.1 wikidata_genre_tree.parquet

#### 1.1.1 Why `P31`, not a `P279*` walk from `Q188451`

The intuitive query — "every item transitively `P279` subclass-of music genre" — returns only 14
items (verified live), mostly _meta-categories_ rather than actual genres:

> `gharana`, `palo`, `game piece`, `opera genre`, `fusion music genre`, `jazz genre`, `electronic
> music genre`, `blues genre`, `folk music genre`, `world music genre`, `rock genre`, `music by
> instrument`, `Shengqiang`, plus `Q188451` itself.

Note the pattern: `"jazz genre"`, `"rock genre"` are _classes of genre_, not genres — not the
~6,300 actual genres like "rock music" or "bebop" that Bronze needs.

That's because Wikidata keeps the two relationships separate:

- **Class membership** is `P31` — e.g. `wd:Q11399` "rock music" `wdt:P31` `wd:Q188451` "music genre".
- **Subgenre hierarchy** is `P279`, but _between genre items_ — e.g. `wd:Q11399` "rock music"
  `wdt:P279` `wd:Q373342` "popular music".

That `P279` edge doesn't chain back up to `Q188451`. Confirmed live:

```sparql
ASK { wd:Q373342 wdt:P279* wd:Q188451 }   # → false
```

So a `P279*` walk from `Q188451` finds only the 14 meta-category items above, and silently misses
"rock music" and every other real genre — their `P279` parent chains lead to broader _concepts_
like "popular music", not back to the "music genre" class they're an _instance_ of.

#### 1.1.2 Parents are not restricted to also being a music genre instance

A genre's `P279`/`P361` edges routinely point at non-genre classes too — e.g. "opera" (`Q1344`) is
`P279` both "classical music" and "composed musical work" (`Q207628`, not itself `P31` music
genre).

Bronze ingests this raw and unfiltered, consistent with the "as-is" bronze principle used for
MusicBrainz's tables (see [`../musicbrainz/SCHEMA.md`](../musicbrainz/SCHEMA.md)). Flagging
genre-only parents and pruning to a single parent per item is Silver-layer work — see
[`2.3 4_genre_parents`](#23-4_genre_parents) (flagging) and [`2.4 5_hierarchy`](#24-5_hierarchy)
(pruning) below.

#### 1.1.3 Bare QIDs, not full entity URIs

Wikidata's SPARQL results return full entity URIs (`http://www.wikidata.org/entity/Q11399`), not
bare QIDs. `ingest.py` strips the `http://www.wikidata.org/entity/` prefix before writing Parquet,
since the QID is the natural join key and the full URI is otherwise dead weight. Labels are passed
through as-is. This applies to all three Bronze queries, not just this one.

### 1.2 wikidata_genre_indigenous_to.parquet and wikidata_genre_country_of_origin.parquet

#### 1.2.1 Why separate tables, not extra columns on `wikidata_genre_tree.parquet`

`P2341` ("indigenous to") and `P495` ("country of origin") are per-item ethnographic/provenance
attributes, not genre-to-genre taxonomy edges like `P279`/`P361`. Their cardinality is independent
of an item's parent count — an item can have any number of `P279`/`P361` parents and, separately,
any number of `P2341` or `P495` values.

Querying either alongside `P279`/`P361` in a single row (the way `GENRE_TREE_QUERY` handles
`P279`/`P361` together, since those share the same "parent edge" semantics) would cross-multiply
the extra `OPTIONAL` into spurious combinations — e.g. an item with 2 parents and 3 `P2341` values
would produce 6 rows instead of 2 + 3.

Each is therefore its own query, producing its own (item, value) table. See
`wikidata_client.INDIGENOUS_TO_QUERY` / `COUNTRY_OF_ORIGIN_QUERY`, and
[2.2 3_regional_classification](#22-3_regional_classification) below for how each is used
downstream.

## 2. Silver

### 2.1 2_regional_overview_classification

#### 2.1.1 Why classification is needed

Wikidata's `P31` "instance of" `Q188451` ("music genre") class extension — Bronze's source query —
is noisy. It includes items that are not themselves musical styles, e.g. "music of Kenya" (a
country's music scene overview, not a style). Left unflagged, these would pollute any genre
hierarchy or genre-matching built on top of this data.

#### 2.1.2 `classification_reason` values

| Value                              | Rule                                                                  | Rationale                                                                                                                                                                                   |
| ----------------------------------- | ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `regional_overview`                | `item_label` starts with `"music of "`                               | Wikidata's national/regional music overview articles (e.g. "music of France", "music of Kenya") — ~300 of ~6,300 items as of this writing, always this exact prefix, never a genre name. |
| `manual_overview_reclassification` | `item_id` listed in `manual_overview_reclassifications.csv`          | An existing genre item (already has its own Bronze row and a real `P279`/`P361` parent) that a data expert has decided plays the same non-genre regional-overview role despite not carrying the `"music of "` label prefix — see [2.1.5](#215-manual-reclassification-of-existing-items-as-overview). |

This tags, it does not exclude: `regional_overview` items stay in every downstream Parquet file
and are the seed set [`2.2 3_regional_classification`](#22-3_regional_classification) propagates
`is_regional` down from — any genre item with a parent edge into one of these becomes a regional
genre, and the seeds themselves become regional genre nodes in their own right (see
[`2.4 5_hierarchy`](#24-5_hierarchy)).

#### 2.1.3 Auto-promotion of orphan `"music of "` parents

Before the `classification_reason` rule above runs, this step also scans `parent_label` (not just
`item_label`) for the `"music of "` prefix.

Some regional-overview items (e.g. "music of Wales", `Q6942327`) are never themselves classified
`P31` instance-of music genre, so Bronze never fetches their own row — they only ever show up as a
`parent_label` on their subgenres (e.g. "Welsh folk music"). Left alone, such an item is invisible
to the `classification_reason` rule above and cannot legally be used as a
`manual_regional_overrides.csv` `overview_item_id` target (`3_regional_classification` requires
the target to already exist and be flagged `is_regional_overview`).

For every distinct `(parent_id, parent_label)` pair matching the prefix whose `parent_id` has no
`item_id` row of its own, this step synthesizes one root row (`parent_id`/`parent_label`/
`relation_type` null, same shape as any other unparented item) before the prefix classification
runs, so the promoted row gets `is_regional_overview = True` "for free."

This is purely mechanical — the id/label pair is already present in Bronze as a `parent_label`, so
no live Wikidata fetch is involved (Silver never fetches raw data — see `CLAUDE.md`) — unlike
deciding which broader region a promoted item nests under (e.g. Wales → United Kingdom), which
stays a manual `manual_regional_overrides.csv` entry.

#### 2.1.4 Manual addition of overview items missing from Bronze entirely

Some real "music of `<place>`" Wikidata items never appear in Bronze at all — not as their own
`item_id` row (they're not `P31` instance-of music genre, e.g. "music of Dominica" is `P31`
instance-of a different class) and not as any item's `parent_label` either (so orphan-promotion
above can't reach them). Such an item is invisible to this step and cannot legally be used as a
`manual_regional_overrides.csv` `overview_item_id` target.

`manual_regional_overview_additions.csv` (`src/wikidata/silver/manual_regional_overview_additions.csv`,
git-tracked, hand-curated — columns `item_id,item_label,reason`) is the backstop: a data expert who
has looked up the item's real Wikidata QID adds a row here, and this step synthesizes it as a root
row (same shape as an auto-promoted orphan) before the `classification_reason` rule runs, so it
gets `is_regional_overview = True` "for free" and becomes a legal `overview_item_id` target.

This is still not a live fetch — the id/label pair is authored by hand, same as
`manual_regional_overrides.csv` (Silver never fetches raw data — see `CLAUDE.md`) — and the
pipeline fails fast if a row's `item_label` doesn't start with `"music of "` or its `item_id` is
already present in the genre tree (in which case it doesn't need manual addition).

`item_id` is normally a real Wikidata QID, but a synthetic id (e.g. `LOCAL:indigenous-americas`)
is allowed as a last resort when no matching real Wikidata "music of `<place>`" item exists at all
— not every Gold-layer grouping concept has a Wikidata counterpart. Such rows still need
`item_label` to start with `"music of "`; their `item_url` is built the same way as any other row
and simply won't resolve to a real Wikidata page.

#### 2.1.5 Manual reclassification of existing items as overview

Unlike 2.1.4's case, some items are the opposite problem: they already have their own row in
Bronze/`1_item_links` (usually with a real `P279`/`P361` parent edge, making them look like an
ordinary genre) but a data expert has decided the item actually functions as a non-genre regional
overview node — it just doesn't carry the `"music of "` label prefix the automated rule keys off
of. "European folk music" (`Q98528192`) is the motivating example: a continent-wide folk-music
umbrella that is parent to dozens of national folk genres (Hungarian folk music, Nordic folk
music, ...), functionally identical to a "music of Europe" overview item, but named without the
prefix.

`manual_overview_reclassifications.csv`
(`src/wikidata/silver/manual_overview_reclassifications.csv`, git-tracked, hand-curated — columns
`item_id,item_label,reason`) is the backstop for this case: a data expert lists the item's QID and
current label, and this step flags it `is_regional_overview = True` /
`classification_reason = "manual_overview_reclassification"` directly, without touching its label.

This is the mirror image of `manual_regional_overview_additions.csv` in every validation rule:
`item_label` here does **not** need the `"music of "` prefix (that's the whole point — these are
exactly the items the prefix rule misses), but `item_id` **must** already be present in the genre
tree with a matching `item_label`, and must not already be flagged `is_regional_overview` by the
prefix rule (nothing to reclassify in that case). As usual, the pipeline fails fast on any row that
violates these constraints, on blank `item_id`/`item_label`, or on duplicate `item_id` rows.

Reclassifying an item this way excludes it from `5_hierarchy` as a canonical genre — it becomes a
scaffolding node in `5_regional_hierarchy` only, the same as any other `regional_overview` item.
It's also included in `3_regional_classification`'s seed set (see
[2.2.2](#222-rule-four-seed-sources)), so regional status still cascades correctly to its
children.

#### 2.1.6 Scope of this first pass

This is a first classification pass covering the single highest-confidence, most mechanical rule
found during analysis. Other non-genre categories are pruned separately, later, via manual CSV
backstops (see [2.4.1](#241-manual-csv-backstops)) rather than an automated rule here.

### 2.2 3_regional_classification

#### 2.2.1 Inputs

`3_regional_classification` also reads Bronze `wikidata_genre_indigenous_to.parquet` (see
[SCHEMA.md#2-bronze](SCHEMA.md#2-bronze)) to catch nationally/ethnically-specific genres that have
no `P279`/`P361` parent for the cascade below to propagate through in the first place, plus a
git-tracked, hand-curated CSV (`src/wikidata/silver/manual_regional_overrides.csv`, not Bronze —
it's authored by a data expert, not fetched from Wikidata) for the rare item the automated sources
still miss.

Bronze `wikidata_genre_country_of_origin.parquet` (`P495`, "country of origin") is deliberately
**not** read here — see [SCHEMA.md#2-bronze](SCHEMA.md#2-bronze) for why (it's set on broad
canonical umbrella genres too, e.g. jazz, heavy metal music, which would wrongly cascade regional
status onto their real subgenres).

#### 2.2.2 Rule: four seed sources

Four kinds of items seed the regional graph and are themselves flagged `is_regional = True`, not
merely a launching point for other items:

- `regional_overview` items (from `2_regional_overview_classification`, e.g. "music of Kenya",
  "music of Cape Verde"), including items reclassified into that same role via
  `manual_overview_reclassifications.csv` despite not carrying the `"music of "` prefix (e.g.
  "European folk music" — see [2.1.5](#215-manual-reclassification-of-existing-items-as-overview))
  — `regional_reason = "seed"`.
- Items with at least one `P2341` ("indigenous to") value in Bronze
  `wikidata_genre_indigenous_to.parquet` (e.g. "Han Chinese music") — `regional_reason =
  "indigenous_to"`. Unlike `regional_overview` seeds these are ordinary genre items, not non-genre
  overview articles, and are often roots with no `P279`/`P361` parent at all — the parent-based
  cascade has nothing to reach them through, so they need this direct, independent signal instead.
- Items listed by `item_id` in `manual_regional_overrides.csv` — `regional_reason =
  "manual_override"`. A fallback for genres the structural/property-based sources above don't
  catch — typically a root item with no `P279`/`P361` parent and no `P2341` value either (e.g.
  "mezwed", a Tunisian genre with neither signal). Each entry carries a `reason` column explaining
  why a data expert added it; see the file itself for the current list.

  Because these override items typically have no `P279`/`P361` parent at all, they'd otherwise
  surface as their own orphan roots in `5_regional_hierarchy` instead of nesting under their
  region — a required `overview_item_id` column gives the override item's `item_id` the `item_id`
  of a `regional_overview` item (e.g. "music of Japan" — normally a real QID, but see
  `manual_regional_overview_additions.csv` above for the synthetic-id fallback) as a synthetic
  parent edge (`relation_type = "manual_override_parent"`), replacing its null-parent row. Every
  row must set it; a row with it missing or blank fails the pipeline at this step rather than
  silently leaving the item an orphan root.

#### 2.2.3 Cascade

A genre item is regional if **any one** of its parent edges points at any kind of seed, or at an
item already flagged regional — propagated down as a multi-source cascade, repeated to a fixpoint.
`regional_reason` is `"direct"` when the item's own parent set includes a seed
(`regional_overview`, `indigenous_to`, or `manual_override`) directly, `"inherited"` when it only
reaches regional status via an already-flagged parent that isn't itself a seed.

> ⚠️ **ANY-parent, not ALL-parent — confirmed by a real multi-parent case.** A naive "every parent
> trail dead-ends in a seed" rule would miss real regional genres that also happen to have a clean
> secondary parent: "Australian rock" has one parent edge into "rock music" (a clean canonical
> genre, no regional signal) and another into "music of Australia" (a seed) — live data confirms
> it's still correctly flagged regional.
>
> Having _any_ parent edge into a regional item is sufficient, regardless of whether the item also
> has a clean parent elsewhere. This structural rule alone catches both "morna" (direct seed hit)
> and "fado" (inherited, two hops through "Portuguese folk music") without any manual help — the
> curated override list above exists only for items the structural rule and the `P2341` signal all
> miss entirely.

> ⚠️ **Exploration phase — this rule will evolve.** Cascading from _every_ `regional_overview`
> seed, including continent-level overview articles ("music of Asia", "music of Europe", "music of
> Africa", "music of the Americas") alongside country/ethnic-level ones ("music of Kenya", "music
> of Cape Verde"), currently flags **~61% of all items** as regional (see
> [SCHEMA.md#34-3_regional_classification](SCHEMA.md#34-3_regional_classification) for the
> profile) — well more than the ~367-item vanished-from-hierarchy baseline that originally
> motivated this step. That's largely because continent-level seeds have large direct fan-out
> (e.g. "A-pop" is a direct child of "music of Asia").
>
> `P495` ("country of origin") was considered as an additional seed source but deliberately
> excluded — see [1. Bronze](#1-bronze) above — because it's also set on broad canonical umbrella
> genres (jazz, heavy metal music, etc.), which would wrongly flag their real subgenres regional
> too.
>
> This is being kept as-is for now since the pipeline is still in an exploration phase, not
> shipped as a settled design decision — narrowing the seed set to exclude continent-level
> overview articles (so only country/ethnic-level pages seed the cascade) is a likely future
> refinement once there's a concrete product need to get the regional/canonical split tighter.

> ⚠️ **Known Bronze gap, not yet investigated:** "variété française," a named example of a regional
> genre, does not appear anywhere in the current Bronze extraction at all — not a `P279`/`P361`
> gap, it's simply absent from the `P31` "music genre" class extension entirely. This needs deeper
> investigation into why Wikidata's own query misses it (wrong assumed label, different
> instance-of class, etc.) rather than being treated as a non-issue.

### 2.3 4_genre_parents

#### 2.3.1 `manual_canonical_parents.csv` backstop

Before the `parent_is_genre` flag is computed, this step also reads a git-tracked, hand-curated
`manual_canonical_parents.csv` (columns: `item_id`, `item_label`, `reason`, `parent_item_id`) and
applies each row as a synthetic parent edge, replacing the item's null-parent root row.

It's a backstop for canonical (non-regional) genres with no `P279`/`P361` parent that a data
expert has identified as a subgenre of an existing canonical genre elsewhere in the tree —
typically a cross-national fusion genre with no single national/ethnic home, so
`manual_regional_overrides.csv` doesn't apply (e.g. "metal prehispánico" → "heavy metal music").
Unlike `manual_regional_overrides.csv` this doesn't affect `is_regional`/`regional_reason` — it
only supplies a missing canonical parent edge, tagged `relation_type =
"manual_canonical_parent"`.

The pipeline fails fast if `parent_item_id` is missing/blank, if `item_id` or `parent_item_id`
isn't a known item in the tree, or if `parent_item_id` points at an item flagged
`is_regional_overview` (that's what `manual_regional_overrides.csv` is for).

#### 2.3.2 Rule: what counts as a genre parent

A parent counts as an actual musical style only if it is flagged `is_regional_overview = False` by
`2_regional_overview_classification` — not merely present in Bronze's raw `P31` "music genre"
extension. This keeps the Silver steps agreeing with each other: an edge into a `regional_overview`
item like "music of Kenya" is `parent_is_genre = False`, the same as an edge into a concept that
was never `P31` "music genre" at all (e.g. "opera" → "composed musical work").

Non-genre parents span both a genre item tagged non-genre in step 1 (e.g. an edge into "music of
Tanzania") and a parent that was never in Bronze's `P31` "music genre" extension at all (e.g.
"national song" → "national anthem", "Renaissance music" → "Renaissance art") — both count as
`parent_is_genre = false` under the rule above.

### 2.4 5_hierarchy

`5_hierarchy.parquet` (canonical) and `5_regional_hierarchy.parquet` (regional) are the first
Silver step that actually prunes rather than flags: it reduces `4_genre_parents.parquet` to one
row per genre item, split into two clean, directly-consumable genre hierarchy edge lists — a
canonical one, excluding every `is_regional = true` item, and a regional one, containing only
`is_regional = true` items (which now includes the `regional_overview` seed items themselves).

#### 2.4.1 Manual CSV backstops

Three git-tracked, hand-curated CSVs (same columns: `item_id`, `item_label`, `reason`) each list
items that no automated signal distinguishes from a real genre, so a data expert reviewing the
root lists adds them by hand. Every `item_id` across all three is dropped entirely from **both**
outputs before either pruning stage below runs (unknown `item_id`s raise), and any child edge that
pointed at one is treated exactly like an edge into a non-genre/non-regional parent (severed, per
stage 1) rather than left dangling:

- `manual_theme_genres.csv` — genre items organized around a subject/theme/subculture (e.g. "LGBT
  music", "steampunk music", "bronycore") rather than a geography, ethnicity, or musical style.
- `manual_technique_genres.csv` — compositional or performance techniques (e.g. "crab canon",
  "fauxbourdon", "call and response") rather than a genre at all.
- `manual_out_of_scope_genres.csv` — items that aren't a music genre at all, i.e. Wikidata's `P31`
  "music genre" classification was simply wrong (e.g. a near-empty stub with no real description,
  a record label, an event, a person) — as opposed to a real but off-topic genre
  (`manual_theme_genres.csv`) or a technique (`manual_technique_genres.csv`).

#### 2.4.2 Rule: two-stage pruning

Applied in two stages, run separately for the two outputs:

1. **Prune to same-graph edges.** For `5_hierarchy`, keep a row only if
   `is_regional_overview = False` for the item itself and it is _not_ `is_regional`, and either
   `parent_id` is null (a root) or `parent_is_genre = True` and the parent is not itself regional.
   For `5_regional_hierarchy`, keep a row only if the item _is_ `is_regional` (seed items
   included), and either `parent_id` is null or the parent is itself `is_regional = True`. Either
   way, an edge into a non-regional, non-genre parent, or across the canonical/regional boundary,
   doesn't count as a legitimate hierarchy parent.
2. **Collapse multi-parent items to one row.** If an item still has more than one surviving parent
   within its own output, keep only the edge to the parent with the lowest numeric QID.

> ⚠️ **Provisional / tâtonnement:** the lowest-QID rule in stage 2 is an arbitrary placeholder, not
> a considered design decision. QIDs are assigned by Wikidata in creation order and carry no
> taxonomic meaning. It exists only because no better signal is currently available: live SPARQL
> queries against the real genre extension found that **2,727 of ~6,337 genre items (~43%)** have
> more than one `P279` parent even after Wikidata's own "best rank" resolution, and only **1 item
> in the entire genre extension** has any `P279` statement marked `preferred` rank — Wikidata's own
> disambiguation mechanism is essentially unused here.
>
> `musicbrainz/README.md` already documents that the eventual single-parent hierarchy format for
> TheMusicTreeAPI is "not yet decided" — this rule is a stand-in until that product/curation
> decision exists, and should be expected to change, likely once real curation input (e.g. via
> GrowTheMusicTree) is available.

#### 2.4.3 Known consequence — the two outputs diverge here

In `5_hierarchy` (canonical), an item whose every parent edge points to a non-genre or regional
parent (and which isn't itself a root) has all its rows dropped in stage 1 — it disappears
entirely, not even as an implicit root (e.g. "opera" → "composed musical work").

In `5_regional_hierarchy`, a `regional_overview` seed like "music of Cape Verde" is now a real node
with its own real parent chain (or a genuine root, if it has no `P279`/`P361` parent at all) rather
than being dropped — so an item like "morna," whose only parent is that seed, keeps its real parent
edge instead of being promoted to a synthetic root itself.

Check `profile_hierarchy`'s "zero surviving rows in either output" count (see
[SCHEMA.md#36-5_hierarchy](SCHEMA.md#36-5_hierarchy)) for how often the canonical vanishing still
happens.

> ⚠️ **Under exploration:** `5_hierarchy` (canonical) surfaces a high number of root items
> (`parent_id = null`) — **297 of 805 rows as of this writing** — not the small handful a genre
> tree with one or two top-level categories (e.g. "music") would suggest. Whether that many roots
> is a real property of the source data (genuinely disconnected genre subtrees) or an artifact of
> upstream pruning/collapse rules (e.g. stage 2's lowest-QID collapse severing an item from its
> more meaningful parent) is not yet determined — see
> `pipelines/wikidata/notebooks/explore_genre_tree.ipynb` for the current exploration of these
> roots' relevance.
>
> **Ruled out:** `?item wdt:P279 wd:Q188451` (items directly subclass-of "music genre" itself,
> rather than `P31`-instance-of it) was considered as an alternate, smaller root/seed list. Live
> Wikidata returns only 12 items, not a clean top-level genre list — one is unrelated ("game
> piece"), two are specific traditions rather than roots ("gharana", "palo"), and seven are
> meta-classes describing a _category of genre_ (e.g. "jazz genre", "rock genre") rather than the
> genre item itself (jazz music is the separate `P31` instance `Q1298934`, not this `P279`
> subclass). No prior art found for using this pattern to seed a Wikidata music genre tree. Doesn't
> resolve the root-count question above.
>
> **Target shape (design intent, not yet reached):** the canonical tree should collapse down to a
> handful of root genre families — rock, blues, jazz, funk/disco, electronic, hip-hop, reggae/dub,
> classical music, etc. — not the hundreds of roots it currently produces. Getting there is
> expected to be mostly a linking/cleaning problem (correcting mis-collapsed parent edges, e.g. the
> multi-parent lowest-QID heuristic above) rather than a new extraction or classification
> mechanism. `5_regional_hierarchy` follows different logic entirely and is **not** expected to
> converge to a small root count: one root per cultural/geographic region (e.g. "music of Cape
> Verde"), with that region's own genres nested underneath it.
