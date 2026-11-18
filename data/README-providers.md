# Core and digital banking providers (`data/providers.csv`)

Every institution page under `/fi/` shows two fields, **Core provider** and **Digital banking provider**. Each one has its own "Updated" date, the evidence source type and a link to the source. When we have no evidence, the page says **Not yet identified**. Nothing is guessed. Core is never inferred from the digital vendor (Banno does not mean a Jack Henry core) or from a website scan.

## Columns

| Column | Meaning |
|---|---|
| `fi_id` | `fdic-<CERT>` / `ncua-<charter>`, as in `institutions.csv` |
| `field` | `core` or `digital` |
| `value` | Vendor and platform as the source names it, e.g. `Corelation KeyStone`, `Jack Henry (Banno)` |
| `status` | `current` (in use now) or `announced` (a verified, announced change or selection that hasn't gone live yet) |
| `source_type` | `Login page scan`, `Vendor press release`, `FI announcement`, `Press release`, `Regulator filing` |
| `source_url` | Public page the value comes from (for a scan, the homepage that was scanned) |
| `last_updated` | Announcement date, or the date of the last scan that confirmed the value |
| `note` | Short public detail shown under the value (for a scan, the hostname evidence) |

## What the page shows

For each field: a verified `announced` row wins, shown as "Vendor (announced <date>)" with the old current value under it as "Before the change", unless a later `current` row already shows the new vendor (the change has happened). Otherwise the newest `current` row is shown. A row whose `source_url` matches a board signal for the same institution also links "See the signal".

## Where rows come from

- **Digital, `Login page scan`:** written only by `python3 scripts/import_watcher_providers.py`. It reads the website watcher's results (login hosts and DNS CNAME chains, hostname fingerprints only) and takes the latest scan per institution where the homepage loaded. When two vendors tie, both are listed. Re-run it after each weekly watcher run, then rebuild. All other rows are kept.
- **Core and digital from announcements:** added by hand only from rows that passed the Verifier (board rows in `triggers.json`, or Verifier "Pass"/"Verified" rows), citing the original public publisher. Never from CRM or other non-public data.

Then run `python3 scripts/validate.py` (it checks this file) and `python3 scripts/build_directory.py`.
