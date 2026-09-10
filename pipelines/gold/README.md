# gold

Part of the [the-music-tree-pipelines](../../README.md) monorepo.

The consumer-facing export layer: reads `wikidata`'s and `musicbrainz`'s Silver output and produces the
two artifacts `grow-the-music-tree-api` imports at seed time — a canonical genre tree and a small set of
songs reconciled against it. This is the repo's first cross-pipeline join.

## Table of Contents

- [gold](#gold)
  - [Table of Contents](#table-of-contents)
  - [Overview](#overview)
  - [Pipeline](#pipeline)
  - [Schema](#schema)
  - [Setup](#setup)
  - [Running](#running)
  - [Testing](#testing)
  - [Contributing](#contributing)
  - [License](#license)

## Overview

- **Inputs:** `wikidata`'s `7_canonical_hierarchy.parquet` and `musicbrainz`'s `3_song_example.parquet` (both Silver outputs, produced independently by those pipelines — see their own READMEs).
- **Outputs:** `1_canonical_genre_tree.json` (the full canonical genre tree, nested `{"tree": [...]}` shape) and `2_songs.json` (a flat list of songs, each tagged with a canonical `genre_name`), both validated against a JSON Schema before being written, and both regenerated automatically every run — there are no manual/on-demand export scripts here.

## Pipeline

1. `export_genre_tree` — builds the canonical genre tree from `7_canonical_hierarchy.parquet` and writes `1_canonical_genre_tree.json`. Independent of step 2/3 below.
2. `genre_match` — reconciles musicbrainz's raw `genre_name` tags against wikidata's canonical `item_label`s via a match cascade (exact → `" music"`-suffix-stripped → manual alias CSV → accepted-non-genre CSV → unmatched), writing `1_genre_match.parquet` and a triage sidecar `1_genre_match_unresolved.csv`. Unmatched names are a soft warning, not a pipeline failure — see [DESIGN.md](DESIGN.md).
3. `export_songs` — filters `1_genre_match.parquet` down to rows with a resolved genre and writes `2_songs.json`.

See [SCHEMA.md](SCHEMA.md) for full column/shape detail and [DESIGN.md](DESIGN.md) for the match-cascade rationale.

## Schema

See [SCHEMA.md](SCHEMA.md).

## Setup

See [CONTRIBUTING.md](../../CONTRIBUTING.md#setup) for local environment setup. `cp .env.example .env` and point `MUSICBRAINZ_SILVER_DIR`/`WIKIDATA_SILVER_DIR` at those pipelines' Silver output.

## Running

```bash
uv run --package gold python -m gold
```

Reads `MUSICBRAINZ_SILVER_DIR`, `WIKIDATA_SILVER_DIR`, writes to `GOLD_OUTPUT_DIR` (all required, no in-code defaults — see `.env.example`).

## Testing

`pytest -m "not integration"` from the repo root.

## Contributing

See [CONTRIBUTING.md](../../CONTRIBUTING.md).

## License

[Apache 2.0](../../LICENSE)
