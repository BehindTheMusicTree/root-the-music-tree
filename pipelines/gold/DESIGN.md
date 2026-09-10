# Design

Rationale for `gold`'s match cascade. See [SCHEMA.md](SCHEMA.md) for column/shape detail.

## Why reconciliation lives here, not in either source pipeline

Matching musicbrainz's raw tag names against wikidata's canonical genre labels needs both pipelines'
Silver output at once — the first genuine cross-pipeline join in this repo. Neither `wikidata` nor
`musicbrainz` should depend on the other's output (they stay independently runnable, independently
testable), so the join lives in a new layer downstream of both.

## Match cascade

Empirical check (musicbrainz `tag.name`, as used by `2_recording_genre`, against wikidata canonical
`item_label`s): 77.0% match case-insensitive exact, 83.4% after stripping a trailing `" music"` suffix.
The remaining ~17% splits between real naming-convention mismatches (fixable via alias, e.g. musicbrainz
"drum and bass" vs. wikidata's actual label) and permanent non-genre folksonomy noise (`asmr`,
`birdsong`, personal-taste tags, etc.) that should never match.

`genre_match` tags each row with a `match_method`, trying each of the following in order and stopping
at the first that succeeds:

1. `exact` — case-insensitive equality against a canonical `item_label`.
2. `music_suffix` — same, after stripping a trailing `" music"` from the musicbrainz name (covers the
   bulk of the naming-convention gap between the two sources).
3. `manual_alias` — looked up in `manual_genre_alias.csv`, a data expert's curated real-genre alias.
4. `accepted_non_genre` — looked up in `manual_accepted_non_genre_tags.csv`, a data expert's curated
   permanent-noise list. Kept in the output (not dropped) with a `null` `wikidata_genre_name`, for
   audit visibility — a reviewer can see it was triaged, not silently missed.
5. `unmatched` — anything left. **Not a hard failure.**

## Why `unmatched` is a soft warning, not a raise

`wikidata`'s `canonical_roots.py` raises on an untriaged new root, blocking that pipeline's run until a
data expert reviews it — appropriate there because a new root is rare and reviewable in isolation.
Genre-name reconciliation is different: musicbrainz's tag vocabulary is large, uncurated folksonomy, and
new unmatched names will appear routinely as the sample data or the tag vocabulary shifts. Blocking the
daily Gold run on every new unmatched name would make the pipeline fragile for no benefit — a missing
tag alias doesn't corrupt the tree or the songs export, it just means fewer songs get a resolved genre
this run.

Instead, `genre_match` logs a warning and writes every unmatched `(genre_name, title, artist,
youtube_video_id)` combination to `1_genre_match_unresolved.csv` every run (even when empty) — a durable,
human-scannable triage surface. A data expert reviews it and promotes each name into
`manual_genre_alias.csv` (real genre, different name) or `manual_accepted_non_genre_tags.csv` (permanent
noise), same closing-the-loop shape as `wikidata`'s manual-CSV backstops, just non-blocking.

## Manual CSV validation

Both manual CSVs are validated the same way `wikidata`'s manual CSVs are (see
`non_genre_pruning.py::_load_dropped_ids`): a `ValueError` naming the CSV and offending value(s) for a
blank/null required column, a duplicate key (case-insensitive), or an unknown reference. Additionally,
each CSV is checked against the auto-match cascade and against each other, since an alias/non-genre entry
that would already resolve automatically (or that conflicts with the other CSV) indicates stale or
contradictory triage data:

- `manual_genre_alias.csv`: `wikidata_genre_name` must exist in the canonical hierarchy;
  `musicbrainz_genre_name` must not already match via `exact`/`music_suffix` (dead-weight alias).
- `manual_accepted_non_genre_tags.csv`: `musicbrainz_genre_name` must not already match via
  `exact`/`music_suffix`, nor appear in `manual_genre_alias.csv` (can't be both a real alias and
  permanent noise).
