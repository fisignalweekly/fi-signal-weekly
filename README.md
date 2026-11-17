# FI Signal Weekly

Weekly buying-window triggers at US banks and credit unions: pending mergers, core renewals, and new executives, each linked to its public source.

## Updating the board

Rows live in `data/triggers.json`. For each publish (weekdays):

1. Add the new verified rows and set the top-level `updated` to the publish date (`YYYY-MM-DD`). The site shows it as "Board updated".
2. Run `python3 scripts/stamp_added.py` to set `added` (the date a row went live) on new rows. Rows added in the last 7 days get a "New" tag.
3. Run `python3 scripts/validate.py`.

Each row's `date` is the event/announcement date; `added` is when it went on the board. See `scripts/refresh_notes.md` for sourcing rules.

## Brand

Colors, logo use, voice and X post rules: [`docs/brand-guide.md`](docs/brand-guide.md).

The board's "Bank or CU" filter is derived from the institution name in `js/app.js` (`charter()`): "Credit Union", or an all-caps word ending in "CU" (CU, FCU, TDECU...), means credit union; everything else is a bank. Cross-charter deals where a credit union is named count as credit union.

## Saved territory views

Every board filter is kept in the URL query string, so a filtered board is a plain, shareable link. No accounts and no tracking:

```
https://fisignalweekly.com/?state=MI,OH&charter=cu&assets=1b-10b&type=merger&from=2026-10-01&to=2026-11-30&q=core
```

| Param | Values |
|---|---|
| `type` | `merger`, `core`, `executive` |
| `state` | one or more 2-letter codes, comma-separated |
| `charter` | `bank`, `cu` |
| `assets` | `lt500m`, `500m-1b`, `1b-10b`, `10b-50b`, `50b+`, `na` |
| `from`, `to` | `YYYY-MM-DD` (event date) |
| `q` | search text |

Unknown values are ignored. "Copy link to this view" in the Filters panel copies the current view. A row anchor still wins: `/?state=MI#t217` lands on t217 and clears the filters if they would hide it. Row "Link" buttons never carry filters. The quick-view chips are plain links in `index.html`.
