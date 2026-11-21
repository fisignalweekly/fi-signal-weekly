# Pipeline tools

Command-line tools for the row pipeline that feeds the board. They read working files that are
not in this repo (staging files, review verdict files, the ledger itself) and `data/triggers.json`
on `origin/main` of a site checkout. Nothing here edits row content or publishes data.

| file | what it does |
|---|---|
| `ledger.py` | One line per row id with its pipeline status, timestamps and lane. |
| `verified_unpublished.py` | Rows that passed review and are not live yet. |
| `source_health.py` | Per-source health for each collection sweep. |
| `test_ledger.py` | Tests: `python3 tools/test_ledger.py` |

## Configuration

No paths are built in. Pass `--config FILE`, or set `FISIGNAL_LEDGER_CONFIG` to a JSON file:

```json
{
  "data_dir": "/path/to/working-files",
  "site_dir": "/path/to/site-checkout",
  "extra_verdict_globs": ["/other/place/review*.tsv"],
  "meta_globs": ["queue-*.tsv"],
  "fresh_window_days": 14,
  "source_health_path": "/path/to/source-health.tsv"
}
```

Only `data_dir` is required. `FISIGNAL_DATA_DIR` and `FISIGNAL_SITE_DIR` override the file.

## Ledger

`ledger.tsv` columns: `row_id status verdict_file pr date source note found_at published_at lane`.
Row content (institution, type, dates, summary, URL) stays in the staging files; the ledger holds the
id, status, timestamps and lane.

Statuses, in order: `found` → `staged` → `verified` | `needs_review` | `rejected` → `live` → `corrected`.
`flagged` is the old name for `needs_review`: it is accepted as input and read as `needs_review`
from older ledger files. Conflict kind names (for example `live_but_flagged`) are unchanged.

| command | what it does |
|---|---|
| `ledger.py build` (or bare `ledger.py`) | Full rebuild. Derived state (triggers.json, verdict files, staging) is merged with the event log. |
| `ledger.py add <row_id> found\|staged [--date YYYY-MM-DD] [--lane fresh\|backlog\|backfill] [--backfill] [--found-at ISO] [--note TEXT]` | Record a found or staged item. Append-only and deduped by row id: a second `add` for the same id changes nothing and exits 0. The event date comes from the staging row, or `--date` when there is no staging row yet. |
| `ledger.py set <row_id> <status> [--note TEXT] [--at ISO] [--force]` | Change a row's status. Settable: `staged`, `verified`, `needs_review` (alias `flagged`), `rejected`, `corrected`. |
| `ledger.py published <row_id>... [--at ISO] [--pr URL]` | Record `published_at` for rows that went live. |
| `ledger.py stale [--now ISO] [--json]` | Fresh items still `found` or `staged` after more than 1 business day. Exit 1 if any. |
| `ledger.py status` | Counts by status, open conflicts, pending takedowns. |
| `ledger.py verified-unpublished [--json] [--quiet]` | Same as `verified_unpublished.py`. |
| `ledger.py snapshot <file>` | Copy a working file into `snapshots/` (last 10 kept), then rebuild. |
| `ledger.py snapshot --prune` | List snapshots older than the latest successful publish (dry run). `--yes` deletes them. The newest snapshot from each source is always kept. |

Allowed `set` changes (anything else exits 2 unless `--force`):
`found → staged | rejected`, `staged → verified | needs_review | rejected`,
`needs_review → staged | verified | rejected`, `verified → needs_review | rejected`,
`rejected → staged`, `live → corrected`, `corrected → corrected`.
`live` is never set by hand: it comes only from `triggers.json`, and live rows are never demoted.

A row is treated as live when its id is already in `triggers.json`. If the ids differ, the
ledger may still match on institution + type + date, then source URL, then a name-token
fuzzy match — this is how a staging id is tied to the t-id it was published as. A planned
branch (the row id contains `-branch-planned-`, or the type names a planned branch) is
never attached to a different live trigger that way. A plain `branch_opening` type is not
enough to decide: an opening and a separate plan can share an institution, date and source.


How explicit writes survive rebuilds: `add`, `set` and `published` append to `ledger-events.tsv`
(append-only, in `data_dir`). Every build derives state from the source files, then replays the
events:
- `add` creates the row if no source knows it yet, and sets `found_at` and `lane`. On a row that only
  has a staging line, its status (`found` or `staged`) wins.
- `set` wins over staging. Against a verdict file, a verdict file dated after the event's Eastern day
  wins; a same-day disagreement is applied and logged as an `event_verdict_disagree` conflict.
- `published` sets `published_at`. Without one, live rows use the publish-log date or `added`.

Lane rule (computed at `add` time, Eastern dates): `backfill` if the backfill flag is set (the row is in
`staging-backfill.tsv`, `--backfill` was passed, or the live row has `backfill: true`); `fresh` if the
event date is within the last 14 days; otherwise `backlog`. Rows recorded before `add` existed get the
same rule, measured from the first time the ledger saw them.

Stale rule: lane `fresh`, status `found` or `staged`, and more than 24 hours of Monday–Friday time
(Eastern calendar days) since `found_at`. Found Friday 9 AM is stale from Monday 9 AM. Holidays are
not skipped.

## Source health

Run once after every sweep and every retry:

```
source_health.py --results results.tsv        # per-source counts written by the sweep
source_health.py --sweep-dir DIR              # or read DIR/<name>.status files (HTTP code per fetch)
```

`results.tsv` has a header row: `source status parsed matched queued rejected` plus optional
`http detail`. Status is `ok`, `partial` or `fail` (an HTTP code or `CURL_FAIL` also works).

Each run appends one row per source and one `ALL` row to the health file:
`sweep_at sweep_id source status parsed matched queued rejected http detail fail_streak flag`.

Flags (exit 1 when any fires; 0 when healthy; 2 for bad input):
- `fail_2_in_row`: a source was `fail` or `partial` in 2 runs in a row (a retry counts as a run).
- `weekday_zero_yield`: a Monday–Friday sweep matched and queued 0 items across all sources.
- `yield_not_recorded`: a weekday sweep gave no counts at all, so a zero yield can't be ruled out.
