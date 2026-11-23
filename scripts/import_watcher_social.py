#!/usr/bin/env python3
"""Refresh data/social.csv (LinkedIn company pages) from the website watcher's homepage scans.

    python3 scripts/import_watcher_social.py [--db /workspace/fi-signal/site-watcher/data/watcher.db]

Only URLs the FI's own homepage links to are used (the watcher's `social_links`, captured since Nov 18, 2026).
linkedin.com itself is never fetched. A URL is kept only when the homepage links exactly one linkedin.com/company
page, or, if it links several, exactly one whose slug matches the institution's name or a trade name.
Hand-checked rows already in social.csv are kept unless a newer scan finds a different single URL.
"""
import argparse, csv, json, os, re, sqlite3, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(ROOT, "data", "social.csv")
COLS = ["fi_id", "network", "url", "found_on", "checked"]
DEFAULT_DB = "/workspace/fi-signal/site-watcher/data/watcher.db"
LI = re.compile(r"^https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/([A-Za-z0-9_\-%.]+)$", re.I)
DROP = r"\b(the|of|and|inc|n\.?a\.?|national association|fsb|ssb|federal|credit union|cu|fcu|bank|banking|company|co|trust|savings|association)\b"


def norm(s):
    s = re.sub(DROP, " ", s.lower().replace("&", " and "))
    return re.sub(r"[^a-z0-9]", "", s)


def slug_matches(slug, names):
    sl = norm(re.sub(r"[-_.]", " ", slug))
    for n in names:
        nn = norm(n)
        if len(nn) >= 4 and (nn in sl or (len(sl) >= 4 and sl in nn)):
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    a = ap.parse_args()
    db = json.load(open(os.path.join(ROOT, "data", "institutions.json")))
    cols = db["columns"]
    names = {}
    for r in db["rows"]:
        x = dict(zip(cols, r))
        names[x["id"]] = [x["name"]] + (x["also_known_as"].split("|") if x["also_known_as"] else [])
    c = sqlite3.connect(a.db)
    runs = [r[0] for r in c.execute("SELECT run_id FROM runs WHERE finished IS NOT NULL ORDER BY started")]
    latest = {}
    for run in runs:
        for fi, fetched, status, data in c.execute("SELECT fi_id, fetched_at, http_status, data FROM snapshots WHERE run_id=?", (run,)):
            d = json.loads(data)
            if status == 200 and "social_links" in d:
                latest[fi] = (fetched, d)
    rows = {}
    if os.path.exists(CSV):
        with open(CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows[(r["fi_id"], r["network"])] = r
    stats = {"scanned": len(latest), "one": 0, "slug": 0, "ambiguous": 0}
    for fi, (fetched, d) in latest.items():
        if fi not in names:
            continue
        found = {}
        for u in d.get("social_links") or []:
            m = LI.match(u)
            if m:
                found[m.group(1).lower()] = f"https://www.linkedin.com/company/{m.group(1)}"
        if not found:
            continue
        if len(found) == 1:
            url = next(iter(found.values())); stats["one"] += 1
        else:
            hits = [u for s, u in found.items() if slug_matches(s, names[fi])]
            if len(hits) != 1:
                stats["ambiguous"] += 1
                continue
            url = hits[0]; stats["slug"] += 1
        rows[(fi, "linkedin")] = {"fi_id": fi, "network": "linkedin", "url": url,
                                  "found_on": d.get("final_url") or d.get("url_fetched"), "checked": fetched[:10]}
    out = sorted(rows.values(), key=lambda r: (r["fi_id"].split("-")[0], int(r["fi_id"].split("-")[1]), r["network"]))
    with open(CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, COLS, lineterminator="\n"); w.writeheader(); w.writerows(out)
    print(f"social.csv: {len(out)} LinkedIn links (homepages scanned with social capture {stats['scanned']}; "
          f"single company URL {stats['one']}, picked by name {stats['slug']}, held as ambiguous {stats['ambiguous']})")


if __name__ == "__main__":
    sys.exit(main())
