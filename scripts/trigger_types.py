#!/usr/bin/env python3
"""Board trigger types: the one place that lists them and maps staging rows onto them.

    python3 scripts/trigger_types.py                         # list board types and labels
    python3 scripts/trigger_types.py cuex-foo-2026-11-01 executive   # print the board type for a staging row

TYPES is what data/triggers.json "type" may hold (scripts/validate.py checks it). The site's labels live in
js/app.js (TYPE_LABEL), index.html (#f-type options) and css/style.css (.card.<type>, .badge.<type>);
validate.py checks that every type here appears in each of them.

Staging files (staging.tsv, cu_verified_ready.tsv) carry a trigger_type per row. The credit-union batch rows
use these strings (checked Nov 17, 2026):
    cuab-*  cu_acquires_bank            -> cu_acquires_bank   (CU buys bank)
    cuex-*  executive                   -> cu_executive       (CU exec move)
    cumg-*  merger, acquisition         -> cu_merger          (CU merger)
    cucr-*  core                        -> core               (these two rows are core conversions, not charter changes)
    db-*    (any staging trigger_type)  -> digital_banking_change  (Phase 1 digital-banking; staging starts Nov 18, 2026)
    branch_opening                     -> branch_opening (FI pages only; the published row gets "fi_only": true)
A row already typed with a board type (e.g. cu_charter) keeps it. A db-* id always maps to digital_banking_change.
"""
import sys

TYPES = {
    "merger": "Pending merger",
    "core": "Core renewal / conversion",
    "executive": "New executive",
    "cu_acquires_bank": "CU buys bank",
    "cu_executive": "CU exec move",
    "cu_merger": "CU merger",
    "cu_charter": "CU charter change",
    "digital_banking_change": "Digital banking change",
    "branch_opening": "Branch opening",
}

# Types that show ONLY on /fi/ institution pages, never on the main board, its filters, feeds, X posts or the digest
# (approved Nov 18, 2026). Their rows must carry "fi_only": true. js/boardrows.js mirrors this.
FI_ONLY_TYPES = {"branch_opening"}


def is_board_row(r):
    """True if a triggers.json row belongs on the main board (and X / newsletter selections)."""
    return r.get("fi_only") is not True and r.get("type") not in FI_ONLY_TYPES

# (staging id prefix, staging trigger_type) -> board type
STAGING_MAP = {
    ("cuab", "cu_acquires_bank"): "cu_acquires_bank",
    ("cuex", "executive"): "cu_executive",
    ("cumg", "merger"): "cu_merger",
    ("cumg", "acquisition"): "cu_merger",
    ("cucr", "core"): "core",
}


# Prefixes that always map to one board type (db-* = Phase 1 digital-banking rows).
PREFIX_MAP = {
    "db": "digital_banking_change",
}


def board_type(row_id, trigger_type):
    """Board type for a staging row, or raise ValueError if it has no mapping."""
    prefix = (row_id or "").split("-", 1)[0].lower()
    t = (trigger_type or "").strip().lower()
    if (prefix, t) in STAGING_MAP:
        return STAGING_MAP[(prefix, t)]
    if prefix in PREFIX_MAP:
        return PREFIX_MAP[prefix]
    if t in TYPES:
        return t
    raise ValueError(f"no board type for {row_id!r} / {trigger_type!r}")


if __name__ == "__main__":
    if len(sys.argv) == 3:
        try:
            print(board_type(sys.argv[1], sys.argv[2]))
        except ValueError as ex:
            sys.exit(str(ex))
    else:
        for k, v in TYPES.items():
            print(f"{k}\t{v}")
