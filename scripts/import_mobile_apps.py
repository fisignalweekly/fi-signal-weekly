#!/usr/bin/env python3
"""Refresh the "Mobile app" rows (field=mobile, source_type=App listing) in data/providers.csv.

    python3 scripts/import_mobile_apps.py [--scan /workspace/fi-signal/mobile-scan/results.jsonl]

Input: the mobile app pass (outside this repo), which reads each FI's own public homepage and at most one linked
mobile-banking page (robots.txt obeyed) and records the Google Play app IDs linked there. No app store is crawled.

A row is written only when the app ID itself sits in a platform vendor's namespace, e.g. com.jackhenry.<bank>:
either a namespace that spells the vendor's own name (VENDOR_PREFIX below) or a namespace whose owner a public source
confirms (data/app_id_prefixes.csv, one row per prefix with its source URLs and check date). FI-branded IDs (com.<bank>.mobile) name no vendor and give no row. Card-control, mortgage and
similar side apps are ignored. Banno code seen on the FI's site is mentioned in the note as supporting detail only.
An app ID is evidence for the MOBILE APP ONLY: it never writes digital / digital_business (online banking) or core.
Every other row in providers.csv is kept as is. Output is sorted, so re-running on the same data gives the same file.
"""
import argparse, collections, csv, json, os, re, sys, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(ROOT, "data", "providers.csv")
COLS = ["fi_id", "field", "value", "status", "source_type", "source_url", "last_updated", "note"]
SRC = "App listing"
DEFAULT_SCAN = "/workspace/fi-signal/mobile-scan/results.jsonl"
# Only namespaces that spell out the platform vendor's own name.
# The label matches the vendor names used for login page scans. Other namespaces are mapped only through
# data/app_id_prefixes.csv, after a public source confirms who owns them. Anything else stays unmapped.
VENDOR_PREFIX = [
    (r"com\.jackhenry\.", "Jack Henry"),
    (r"com\.homecu\.", "HomeCU"),
    (r"com\.bankjoy(app)?\.", "Bankjoy"),
    (r"com\.digitalinsight\.", "Candescent (ex-NCR Digital Insight)"),
    (r"com\.malauzai\.", "Malauzai (Finastra)"),
    (r"com\.mahalo\.", "Mahalo"),
    (r"com\.softek\.", "Softek"),
    (r"com\.shareone\.", "Share One"),
    (r"com\.iparse\.", "iParse"),
    (r"com\.alkami(tech)?\.", "Alkami"),
    (r"com\.narmi\.", "Narmi"),
    (r"com\.lumindigital\.", "Lumin Digital"),
    (r"com\.tyfone\.", "Tyfone"),
    (r"com\.apiture\.", "Apiture"),
    (r"com\.q2e\.", "Q2"),
    (r"com\.fiserv\.", "Fiserv"),
]
PREFIX_CSV = os.path.join(ROOT, "data", "app_id_prefixes.csv")
# Apps inside a mapped namespace that are not the FI's mobile banking app (card controls etc.).
SIDE_APP_IDS = {"com.fis.mobile.android"}   # FIS SecurLOCK Equip, a card-control app
SIDE_APP = re.compile(r"card|valet|ondot|mortgage|zelle|wallet|reward|loan|insur|invest|wealth|bizcard|mrdc", re.I)
PLAY = "https://play.google.com/store/apps/details?id="


def load_prefixes(path=PREFIX_CSV):
    """[(prefix, vendor, namespace wording)] from data/app_id_prefixes.csv; each row carries its public source URL."""
    out = []
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if not r["source_url"].startswith("https://"):
                    sys.exit(f"app_id_prefixes.csv: {r['prefix']} has no source URL")
                out.append((r["prefix"], r["vendor"], r["namespace"]))
    return out


PREFIXES = load_prefixes()


def vendor_of(app_id):
    """(vendor, namespace wording for the note) or None."""
    if app_id in SIDE_APP_IDS:
        return None
    for pat, v in VENDOR_PREFIX:
        if re.match(pat, app_id, re.I):
            return v, f"{v.split(' (')[0]}'s app namespace"
    for pre, v, ns in PREFIXES:
        if app_id.lower().startswith(pre.lower()):
            return v, ns
    return None


def mobile_rows(path):
    out = []
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        pages = r.get("pages") or []
        banno = any(p.get("banno") for p in pages)
        found = collections.OrderedDict()   # vendor -> (app_id, page host, namespace wording)
        for p in pages:
            for a in p.get("play", []):
                m = vendor_of(a)
                if m and not SIDE_APP.search(a.split(".", 2)[-1]) and m[0] not in found:
                    found[m[0]] = (a, urllib.parse.urlparse(p["url"]).netloc, m[1])
        if not found:
            continue
        vals, notes = [], []
        for v, (a, url, ns) in found.items():
            if v == "Jack Henry" and banno:
                v = "Jack Henry (Banno)"
            vals.append(v)
            notes.append(f"Android app ID {a} (in {ns}), linked from {url}")
        note = "; ".join(notes)
        if banno:
            note += ". The website also carries Banno code"
        note += "."
        first = next(iter(found.values()))
        out.append({"fi_id": r["fi_id"], "field": "mobile", "value": " + ".join(vals), "status": "current", "source_type": SRC,
                    "source_url": PLAY + first[0], "last_updated": r["at"][:10], "note": note})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", default=DEFAULT_SCAN)
    a = ap.parse_args()
    if not os.path.exists(a.scan):
        sys.exit(f"mobile scan not found: {a.scan}")
    with open(CSV, newline="", encoding="utf-8") as f:
        keep = [r for r in csv.DictReader(f) if r["source_type"] != SRC]
    rows = keep + mobile_rows(a.scan)
    rows.sort(key=lambda r: (r["fi_id"].split("-")[0], int(r["fi_id"].split("-")[1]), r["field"], r["status"], r["last_updated"], r["value"]))
    with open(CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, COLS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    n = collections.Counter(r["value"] for r in rows if r["source_type"] == SRC)
    print(f"providers.csv: {len(rows)} rows; mobile/{SRC}: {sum(n.values())} (" + ", ".join(f"{k}: {v}" for k, v in sorted(n.items())) + ")")


if __name__ == "__main__":
    main()
