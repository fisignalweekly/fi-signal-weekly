# FI Signal Weekly

Weekly buying-window triggers at US banks and credit unions: pending mergers, core renewals, and new executives, each linked to its public source.

## Updating the board

Rows live in `data/triggers.json`. For each publish (weekdays):

1. Add the new verified rows and set the top-level `updated` to the publish date (`YYYY-MM-DD`). The site shows it as "Board updated".
2. Run `python3 scripts/stamp_added.py` to set `added` (the date a row went live) on new rows. Rows added in the last 7 days get a "New" tag.
3. Run `python3 scripts/validate.py`.

Each row's `date` is the event/announcement date; `added` is when it went on the board. See `scripts/refresh_notes.md` for sourcing rules.
