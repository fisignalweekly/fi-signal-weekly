#!/usr/bin/env python3
"""Set "added" (YYYY-MM-DD, the date a row went live on the board) on rows that lack it.

Run after adding rows and bumping the top-level "updated" date:
    python3 scripts/stamp_added.py            # uses the top-level "updated" date
    python3 scripts/stamp_added.py 2026-11-17 # or an explicit publish date
Rows that already have "added" are never changed. Backfill rows ("backfill": true)
also never have "added" overwritten; if they lack it, it is set to the row's own
"date" (the event/announcement date), not the publish day. The board shows a
"New" tag for 7 Eastern-time calendar days starting the day a row was published
("added"), and lists those rows in "Latest added"; the tag drops off at midnight ET
after day 7 and is never shown on backfill rows. "Today" is
computed in the browser in America/New_York.
"""
import json, re, sys

PATH = "data/triggers.json"
d = json.load(open(PATH))
day = sys.argv[1] if len(sys.argv) > 1 else d["updated"]
if not re.match(r"\d{4}-\d{2}-\d{2}$", day):
    sys.exit("bad date: " + day)
n = 0
n_bf = 0
for r in d["rows"]:
    if r.get("added"):
        continue
    if r.get("backfill") is True and re.match(r"\d{4}-\d{2}-\d{2}$", str(r.get("date", ""))):
        stamp = r["date"]
        n_bf += 1
    else:
        stamp = day
    # keep "added" next to "date" for readability
    items = list(r.items()); r.clear()
    for k, v in items:
        r[k] = v
        if k == "date": r["added"] = stamp
    if "added" not in r: r["added"] = stamp
    n += 1
with open(PATH, "w") as f:
    f.write(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
if n_bf:
    print(n, "rows stamped;", n_bf, "backfill added = their own date; others added =", day)
else:
    print(n, "rows stamped added =", day)
