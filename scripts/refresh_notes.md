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
**Run the harvester first** (collection only, no judgment, ~1.5 min for 14 days):
```
python3 scripts/harvest_exec.py                 # default last 14 days -> /workspace/fisignal-state/exec_candidates.json
python3 scripts/lookup_assets.py --candidates   # optional: adds FDIC/NCUA state+assets suggestions per candidate
python3 scripts/read_candidates.py --n 40       # fetches each source_url, prints dated key sentences to verify
```
- Sources: SEC 8-K Item 5.02 from bank-SIC filers (EDGAR daily index; highest precision), PR Newswire banking category, Google News RSS (wires + CU Today / CUInsight / American Banker / Banking Dive / local papers; links decoded to the publisher URL), Finextra / ABA Banking Journal / Bank Director / CUInsight / American Banker / Banking Dive RSS.
- Dedupes against `data/triggers.json` (by URL / SEC accession) and `/workspace/fisignal-state/seen.json` (anything already surfaced). `--days 60 --no-seen --no-mark-seen` re-runs a backfill.
- Candidates are NOT rows. For each one: open `source_url`, confirm a **named US bank/credit union**, a C-level / president / EVP-level (tech, ops, lending, digital, risk, finance, retail/commercial) change, and the **real announcement date** (Google News often resurfaces old articles: check the date on the page). Skip market/branch presidents, boards-only items, non-US institutions, vendors/fintechs, leagues/associations.
- Many publishers (Business Wire, bizjournals, CU Times, GlobeNewswire, Banking Dive) block curl: open those with a normal browser/WebFetch. If you can't open the page, don't add the row.
- State/assets: `scripts/lookup_assets.py "Bank Name" --state XX` (FDIC for banks, NCUA call-report data for CUs). Use the **bank/CU entity** assets and say so in `assets_note`; use `null` if unsure.
- Focus: CEO, president, CFO, COO, CIO/CTO, chief digital / technology / lending / credit / risk / operations officers, head of retail or commercial banking.

## 5. Update the data
1. Edit `data/triggers.json`: add rows (next `id`), bump top-level `updated`.
2. Fields: `type` (merger|core|executive), `institution`, `state` (2-letter), `assets_millions` (number or null), `date`, `summary` (one line), `source_url`, optional `assets_note`, `assets_source`.
3. `python3 scripts/validate.py` (checks schema), then `python3 -m http.server 8000` and eyeball filters.
4. Publish the site, then send the Friday digest from the newest rows (not automated yet).

## Automation ideas (later)
- Script the NCUA table scrape + diff against last week's dockets to flag new mergers.
- Script FDIC lookups for assets.
- Use an LLM pass over press-wire RSS for candidate rows, always human-verified before adding.
