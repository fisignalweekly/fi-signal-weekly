# FI Signal Weekly

Weekly buying-window triggers at US banks and credit unions: pending mergers, core renewals, and new executives, each linked to its public source.

## Updating the board

Rows live in `data/triggers.json`. For each publish (weekdays):

1. Add the new verified rows and set the top-level `updated` to the publish date (`YYYY-MM-DD`). The site shows it as "Board updated".
2. Run `python3 scripts/stamp_added.py` to set `added` (the date a row went live) on new rows. The board shows a "New" tag only on the Eastern-time calendar day a row was published (`added`); it drops off at midnight ET. "Today" is computed in the browser in `America/New_York` (`js/newtag.js`), not the visitor's local zone or UTC. Rows with `"backfill": true` (historical, website-only) never show the tag; `stamp_added.py` will not overwrite their `added`, and if it is missing sets it to the row's own `date`.
3. Run `python3 scripts/link_institutions.py` (if rows were added), then `python3 scripts/build_directory.py` to refresh the FI directory.
4. Run `python3 scripts/validate.py`.

Row `type` must be one of the board types in `scripts/trigger_types.py`: `merger`, `core`, `executive`, `digital_banking_change` (shown as "Digital banking change"; staging ids `db-*` map to it), and for credit unions `cu_acquires_bank` (shown as "CU buys bank", highlighted), `cu_merger`, `cu_executive`, `cu_charter`. For staging rows, `python3 scripts/trigger_types.py <staging id> <trigger_type>` prints the board type (e.g. `cuex-…` + `executive` gives `cu_executive`; `db-…` gives `digital_banking_change`). Adding a type means adding it there, in `js/app.js` `TYPE_LABEL`, the `#f-type` options in `index.html` and the colors in `css/style.css`. `validate.py` fails if one is missing.

Each row's `date` is the event/announcement date; `added` is when it went on the board. The board and pagination sort by `date` (newest first), so a backfill row lands in its historical spot, not on top. See `scripts/refresh_notes.md` for sourcing rules.

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
| `type` | any board type: `merger`, `core`, `executive`, `digital_banking_change`, `cu_acquires_bank`, `cu_merger`, `cu_executive`, `cu_charter` |
| `state` | one or more 2-letter codes, comma-separated |
| `charter` | `bank`, `cu` |
| `assets` | `lt500m`, `500m-1b`, `1b-10b`, `10b-50b`, `50b+`, `na` |
| `from`, `to` | `YYYY-MM-DD` (event date) |
| `q` | search text |

Unknown values are ignored. "Copy link to this view" in the Filters panel copies the current view. A row anchor still wins: `/?state=MI#t217` lands on t217 and clears the filters if they would hide it. Row "Link" buttons never carry filters. The quick-view chips are plain links in `index.html`.

## FI directory (`/fi/`)

`python3 scripts/build_directory.py` builds a static page for every institution in `data/institutions.json`, at `/fi/<state>/<slug>/`. CU slugs end in `-cu`, and duplicate names in a state get the city added (then the charter number). Each page has the name, charter, city and state, call-report assets and quarter, website, the FDIC or NCUA record link, and the institution's signal history from `data/triggers.json` (rows whose `fi_id` is that institution), each with a `/#tNNN` board link and its source.

It also writes state indexes (`/fi/<st>/`), asset-tier indexes (`/fi/assets/<tier>/`, same tiers as the board), the `/fi/` landing page with client-side search (`js/fi-search.js` over `fi/search.json`), `fi/linked.json` (the board uses it to link institution names), `sitemap.xml` and `robots.txt`.

- Pages for institutions with no signals carry `noindex,follow` and are left out of `sitemap.xml`. The sitemap lists the board, About, the directory indexes and institution pages with signals.
- Idempotent. No timestamps and sorted output, so a re-run on unchanged data changes nothing. Files under `fi/` the build no longer makes (an institution that merged away) are deleted. `--check` exits 3 if the output is stale.
- Asset links use `?v=<hash of css/style.css + js/fi-search.js>`, so a CSS change rewrites every page. Commit them together.
- Run it after `link_institutions.py` on every publish, and after each quarterly `build_fi_db.py` refresh: `python3 scripts/build_directory.py && git add fi sitemap.xml robots.txt`.
