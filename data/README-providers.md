# Core, online banking, mobile app and bill pay providers (`data/providers.csv`)

Every institution page under `/fi/` shows five fields: **Online banking (retail)**, **Online banking (business)**, **Mobile app**, **Core provider** and **Bill pay provider**. Each one has its own "Updated" date, the evidence source type and a link to the source. When we have no evidence, the page says **Not yet identified**. Nothing is guessed. Core is never inferred from the digital vendor (Banno does not mean a Jack Henry core) or from a website scan.

## Columns

| Column | Meaning |
|---|---|
| `fi_id` | `fdic-<CERT>` / `ncua-<charter>`, as in `institutions.csv` |
| `field` | `digital` (online banking, retail), `digital_business` (online banking, business), `mobile` (mobile app), `core` or `billpay`. Core and bill pay never come from a scan |
| `value` | Vendor and platform as the source names it, e.g. `Corelation KeyStone`, `Jack Henry (Banno)` |
| `status` | `current` (in use now) or `announced` (a verified, announced change or selection that hasn't gone live yet) |
| `source_type` | `App listing` (mobile only), `Login page scan`, `Vendor press release`, `FI announcement`, `Press release`, `Regulator filing` |
| `source_url` | Public page the value comes from (for a scan, the homepage that was scanned; for `App listing`, the Google Play listing) |
| `last_updated` | Announcement date, or the date of the last scan that confirmed the value |
| `note` | Short public detail shown under the value (for a scan, the hostname evidence) |

## What the page shows

For each field: a verified `announced` row wins, shown as "Vendor (announced <date>)" with the old current value under it as "Before the change", unless a later `current` row already shows the new vendor (the change has happened). Otherwise the newest `current` row is shown. A row whose `source_url` matches a board signal for the same institution also links "See the signal".

## Where rows come from

- **Business digital, `Login page scan`:** only when the homepage links more than one vendor and the business one sits only on business/treasury hostnames (`treasury.*`, `tm.*`, `cm.*`, `*business*`). Otherwise there's no business row.
- **Bill pay:** verified announcements only. Bill pay links seen on websites are leads for the Scout/Verifier.
- **Digital, `Login page scan`:** written only by `python3 scripts/import_watcher_providers.py`. It reads the website watcher's results (login hosts and DNS CNAME chains, hostname fingerprints only) and takes the latest scan per institution where the homepage loaded. When two vendors tie, both are listed. Re-run it after each weekly watcher run, then rebuild. All other rows are kept.
- **Mobile app, `App listing` (approved Nov 18, 2026):** written only by `python3 scripts/import_mobile_apps.py` from the mobile app pass (`/workspace/fi-signal/mobile-scan/`, outside this repo). That pass reads the FI's own public homepage and at most one linked mobile-banking page, robots.txt obeyed, and records the Google Play app IDs linked there. App stores are not crawled by the pass; the prefix owners in `data/app_id_prefixes.csv` were checked by hand against a few public Play listings (robots.txt allows them). A row is written only when the app ID sits in a platform vendor's own namespace, e.g. `com.jackhenry.<bank>` gives "Jack Henry" (shown as "Jack Henry (Banno)" when the FI's site also carries Banno code). Mapped namespaces (`VENDOR_PREFIX` in the script): `com.jackhenry` Jack Henry, `com.q2e` Q2, `com.fiserv` Fiserv, `com.homecu` HomeCU, `com.bankjoyapp` Bankjoy, `com.digitalinsight` Candescent (ex-NCR Digital Insight), `com.malauzai` Malauzai (Finastra), `com.mahalo` Mahalo, `com.softek` Softek, `com.shareone` Share One, `com.iparse` iParse, `com.alkamitech` Alkami, plus Narmi, Lumin Digital, Tyfone and Apiture. Other namespaces are mapped only through `data/app_id_prefixes.csv` (approved Nov 18, 2026): one row per prefix with the vendor, the public source(s) that confirm who owns the namespace (Google Play "About the developer" entry naming the vendor, the vendor's own site, or an acquisition announcement) and the check date. Mapped there: `com.csiweb` CSI, `com.ifs` Candescent (ex-NCR Digital Insight), `com.mfoundry` and `com.fis` FIS, `com.asiweb` ASI, `com.ProfitStars.TeleWeb` DCI, `com.cspiinc` CSPI, `com.cmcflex` FLEX (CMC), `net.shazambanking` SHAZAM, `com.mnolb` AMI (Member.Net), `com.cuinterface` CU Interface, `com.blossom` Blossom. A prefix with no confirmed owner stays unmapped (e.g. `com.cuconnections`, `com.cssinc`, `com.fdc`, `com.metova`, `com.obs`, `com.jwaala`, `com.harlandfs`). Vendor card-control apps inside a mapped namespace (e.g. `com.fis.mobile.android`) are ignored. FI-branded IDs (`com.<bank>.mobile`) name no vendor and give no row, and card-control or mortgage side apps are ignored. The page shows it as "<vendor>, from app listing". **An app ID is evidence for the mobile app only:** it never fills online banking (retail or business) or core. Banno code on a website is supporting detail in the note only and never fills any field on its own. Online banking still comes only from verified announcements or a login hostname/DNS scan. `validate.py` enforces this (`App listing` rows must be `mobile`, and `mobile` rows must be `App listing` with a Play listing URL).
- **Core and digital from announcements:** added by hand only from rows that passed the Verifier (board rows in `triggers.json`, or Verifier "Pass"/"Verified" rows), citing the original public publisher. Never from CRM or other non-public data.

Then run `python3 scripts/validate.py` (it checks this file) and `python3 scripts/build_directory.py`.
