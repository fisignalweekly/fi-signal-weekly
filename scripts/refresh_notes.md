# Weekly refresh — FI Signal Weekly

Goal: ~30–45 minutes every week (target: Thursday, so the Friday digest is fresh). Rule: **never add a row without a source URL you opened and read.** Dates are ISO `YYYY-MM-DD` = announcement/approval date; put vote/close/effective dates in the summary.

## 1. Pending mergers
- **NCUA**: https://ncua.gov/support-services/credit-union-merger-acquisition/comments-proposed-credit-union-mergers — table of merging CU, continuing CU, member vote date, docket. It has NO state or assets. For each new row, find the credit union's press release / league news (search "<CU name> merger") for state, assets, vote and close dates. Quick fetch:
  `curl -sL -A "Mozilla/5.0" <url> -o ncua.html` then parse the first `<table>`.
- **Bank M&A**: search press wires (PR Newswire, Business Wire, GlobeNewswire) and SEC 8-Ks for "definitive merger agreement" bank/bancorp. Use the target's HQ state in `state`; mention the acquirer in the summary.
- Retire/mark rows after the legal close date (delete, or move to `data/archive.json`).

## 2. Asset sizes (FDIC, banks only)
API docs: https://api.fdic.gov/banks/docs/. Assets are in **$ thousands**; divide by 1000 for `assets_millions`.
```
curl -sG 'https://api.fdic.gov/banks/institutions' \
  --data-urlencode 'search=NAME:"Bank Name" AND ACTIVE:1' \
  --data-urlencode 'fields=NAME,CITY,STALP,ASSET,REPDTE,CERT' --data-urlencode 'limit=5'
```
Record the CERT/report date in `assets_note`. For credit unions use the press release figure, or NCUA call report data (https://ncua.gov/analysis/credit-union-corporate-call-report-data) quarterly. Use `null` if unverified.

## 3. Core renewals / conversions
Check vendor newsrooms weekly: Corelation, Jack Henry, Fiserv, FIS, Synergent, Finastra, Temenos, Q2, nCino, Alkami, CU*Answers, Co-op Solutions, Candescent. Also search "selects" + "core" + "credit union"/"bank". Only include named US institutions (aggregate "six CUs signed" releases need each name verified separately).

## 4. New executives
SEC 8-K Item 5.02 (EDGAR full-text search: "Chief Executive Officer" bank, last 7 days), bank/CU newsroom pages, American Banker / CU Times / CU Today headlines. Focus on CEO, president, CIO/CTO, chief digital or lending officers.

## 5. Update the data
1. Edit `data/triggers.json`: add rows (next `id`), bump top-level `updated`.
2. Fields: `type` (merger|core|executive), `institution`, `state` (2-letter), `assets_millions` (number or null), `date`, `summary` (one line), `source_url`, optional `assets_note`, `assets_source`.
3. `python3 scripts/validate.py` (checks schema), then `python3 -m http.server 8000` and eyeball filters.
4. Publish the site, then send the Friday digest from the newest rows (not automated yet).

## Automation ideas (later)
- Script the NCUA table scrape + diff against last week's dockets to flag new mergers.
- Script FDIC lookups for assets.
- Use an LLM pass over press-wire RSS for candidate rows, always human-verified before adding.
