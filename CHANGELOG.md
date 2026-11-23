# Changelog

Production releases of the FI Signal Weekly site. Entries are dated in Eastern Time and listed newest first. Version numbers follow semantic versioning: the patch number increases for a fix, the minor number for a feature, and the major number for a breaking change.

## v1.4.5 (2026-11-23, ET)

Directory importers: adds LinkedIn company-page extraction and login link-text detection for business banking platforms from website scans.

## v1.4.4 (2026-11-23, ET)

Binds each ledger source row to at most one live trigger, so a planned branch matches its own published trigger instead of staying unpublished next to a related opening.

Adds a mark-published command for provider and contract-window rows that went out without a triggers.json entry. It is a dry run unless --yes is passed.

## v1.4.3 (2026-11-21, ET)

Adds a dry-run prune for ledger snapshot backups: it drops copies older than the latest publish and always keeps the newest copy from each source

## v1.4.2 (2026-11-21, ET)

Stops the pipeline ledger from treating a planned branch as the same live event as a different row that only shares an institution, date and source

## v1.4.1 (2026-11-19, ET)

The subscribe page address now takes visitors to the signup form on the homepage instead of a not-found page

## v1.4.0 (2026-11-19, ET)

Adds pipeline tools in tools/: a row ledger with found, staged, verified, needs_review, rejected, live and corrected statuses, plus found, published and lane fields

New ledger commands add, set, published and stale (fresh items waiting more than 1 business day), and a per-source sweep health check

## v1.3.1 (2026-11-19, ET)

Landscape phones: a Filters button appears after scrolling deep into the board and jumps back to the filters

Footer links are now larger, easier-to-tap targets

## v1.3.0 (2026-11-19, ET)

Homepage: new Latest added section listing rows added in the last 7 days, newest first, with each row's event date

Board: New tag now lasts 7 days (Eastern time) and has a lighter look; new Added: Last 7 days filter

## v1.2.0 (2026-11-19, ET)

Adds a new Strategic priorities section on showcase institution pages, built only from verified rows.

## v1.1.0 (2026-11-19, ET)

Adds cookieless Cloudflare Web Analytics to every page, with a short privacy note on the About page. No cookies and no cross-site tracking.

## v1.0.0 (2026-11-19, ET)

First formally versioned production release of a site that has been live and stable. This baseline covers the current live site, including the mobile-first redesign, the signup fallback, the directory, and the board. Fixes bump the patch number and features bump the minor number. Data publishes are not versioned.

The read-only data server is versioned separately as mcp-v1.0.0 on the mcp-server-src branch.
