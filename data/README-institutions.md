# US bank and credit union database

`data/institutions.csv` and `data/institutions.json` list every active FDIC-insured bank and savings institution and every credit union that files the NCUA 5300 call report. Each row has its charter type, city and state, website and latest reported total assets. Everything comes from free public regulator data. Nothing is estimated or guessed.

Built by `python3 scripts/build_fi_db.py`. Board rows link to these records with `python3 scripts/link_institutions.py`.

## Sources

| Charter | Source | What we take |
|---|---|---|
| Banks (`bank`) | FDIC BankFind Suite API, `institutions` endpoint, `ACTIVE:1` — https://api.fdic.gov/banks/institutions (the older `banks.data.fdic.gov/api` redirects here) | `CERT`, `NAME`, `CITY`, `STALP`, `WEBADDR`, `ASSET` (in $ thousands, converted to $), `REPDTE`, `BKCLASS`, `NAMEHCR` |
| Credit unions (`cu`) | NCUA 5300 Call Report quarterly data zip — `https://ncua.gov/files/publications/analysis/call-report-data-YYYY-MM.zip` | `FOICU.txt`: `CU_NUMBER`, `CU_NAME`, `CU_TYPE`, `CITY`, `STATE`; `FS220.txt`: `ACCT_010` total assets ($); `FS220D.txt`: `Acct_891` website; `TradeNames.txt` |
| CU websites missing from the call report | NCUA Credit Union Locator, `https://mapping.ncua.gov/api/CreditUnionDetails/GetCreditUnionDetails/<charter>` (`creditUnionWebsite`) | website only; about 4 requests a second at most, cached in `$FISIGNAL_FIDB_CACHE` (default `/workspace/fisignal-state/fidb-cache`) |

## Fields

| Column | Meaning |
|---|---|
| `id` | `fdic-<CERT>` or `ncua-<charter number>`. Stable, used as `fi_id` on board rows |
| `name` | FDIC legal name, or NCUA's registered name. NCUA drops the "Credit Union" / "Federal Credit Union" suffix (e.g. `Pentagon` = PenFed). Names are title-cased from NCUA's all caps |
| `charter_type` | `bank` (FDIC) or `cu` (NCUA) |
| `charter_class` | FDIC `BKCLASS` (N, NM, SM, SB, SA, SI, OI) or NCUA type: `FCU` federal, `FISCU` federally insured state-chartered, `NFICU` privately insured state-chartered that still files the 5300 |
| `city`, `state` | Main office city and 2-letter state. FDIC `CITY`/`STALP`, NCUA `CITY`/`STATE` |
| `website` | As reported (FDIC `WEBADDR`; NCUA `Acct_891`, else the locator). Kept as written, which is sometimes without `https://`. Blank if no source lists one |
| `total_assets` | Total assets in US dollars (integer) |
| `assets_as_of` | Quarter of the call report the assets come from, e.g. `2026Q2` |
| `assets_report_date` | Call report date, e.g. `2026-06-30` |
| `holding_company` | FDIC `NAMEHCR` (banks only), as FDIC writes it (abbreviated, all caps) |
| `also_known_as` | NCUA trade names, `|`-separated (CUs only) |

`institutions.json` is compact: `{"sources", "columns", "counts", "rows": [[...], ...]}`, one record per line, columns in the order above.

## As of (build of Nov 17, 2026)

- Banks: 4,208 active FDIC institutions. 4,201 have 2026Q2 (6/30/2026) assets and 2 have 2026Q1. 5 report no assets (new charters and uninsured trust/branch entities), and 4,137 have websites. FDIC's Q2 2026 Quarterly Banking Profile counted 4,238 insured institutions at 6/30. The API lists institutions active now, after Q3/Q4 mergers. Summed assets are $26.45T, against $26.46T in the QBP.
- Credit unions: 4,299 call-report filers for the 2026-06 cycle: 2,649 FCU, 1,565 FISCU and 85 NFICU. NCUA's Q2 2026 data summary reports 4,214 federally insured CUs (2,649 + 1,565), which matches. All have 2026Q2 assets, and federally insured CU assets sum to $2.50T, which also matches NCUA. 3,883 have websites. 418 had none in the call report, and the locator filled 2.

## Refresh (quarterly, after each call report round)

```
python3 scripts/build_fi_db.py          # fetch FDIC + newest NCUA zip, rewrite data/institutions.*
python3 scripts/link_institutions.py    # refresh fi_* fields on board rows
python3 scripts/validate.py
git add data/institutions.* data/triggers.json && git commit -m "Data: institution database refresh <quarter>"
```

- FDIC posts each quarter's call report data about 8 weeks after quarter end. NCUA publishes its zip about 8–10 weeks after quarter end (the 2026-06 zip was dated Aug 24). A refresh in mid-March, June, September and December picks up both.
- The script tries the newest quarter's NCUA zip first and falls back one quarter at a time. Downloaded zips and locator answers are cached, so re-runs are cheap.
- It's idempotent. Output is sorted by id and has no run timestamps, so an unchanged source gives byte-identical files.
- Exit codes: `0` ok (written or already up to date), `1` a source could not be fetched or parsed (nothing written), `2` sanity check failed (bank or CU count outside 3,000–6,000, duplicate ids, missing name/state; nothing written). `--offline` rebuilds from the cache only.
- It prints a summary of counts, website/asset coverage and as-of quarters.

## Known gaps

- 416 credit unions and 71 banks have no website in any source. They stay blank.
- FDIC assets are per bank charter, not holding company. Multi-bank holding companies show their banks separately.
- NCUA names are short names (no "Credit Union" suffix). Use `also_known_as` for brands (e.g. VyStar, PenFed).
- Corporate credit unions (5310 filers) and non-FDIC-insured, non-NCUA institutions (some trust companies, industrial banks under other insurers) are not included.
- Quarter mismatch: a bank's FDIC figure can be a quarter newer than NCUA's in the weeks after FDIC posts.

## Board links (`scripts/link_institutions.py`)

Adds `fi_id`, `fi_name`, `charter_type`, `fi_assets_usd`, `fi_assets_as_of`, `fi_assets_date`, `fi_match` to each row of `data/triggers.json`. It never changes other fields and never adds or removes rows, so it's safe to run after the daily publish.

- The main institution is the first FI named in the row (text before ` / `). That's the acquirer or continuing FI for "Acquirer / Target" rows, and the merging CU when only one is named. Later names are used only when the first has no record, such as an investor group, a fintech or a non-US bank.
- Match order: `data/institution_overrides.csv` (hard cases, each with a reason). Then a CERT/charter number recorded in `assets_note`. Then a normalized name, NCUA trade name or FDIC holding-company name in the row's state. Outside the row's state, a name is used only if it's unique nationwide.
- If a row has no match, it gets no `fi_*` fields. The site then uses the row's own `assets_millions` figure (shown with "~") and the name-based bank/CU guess.
