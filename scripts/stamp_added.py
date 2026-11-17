#!/usr/bin/env python3
"""Set "added" (YYYY-MM-DD, the date a row went live on the board) on rows that lack it.

Run after adding rows and bumping the top-level "updated" date:
    python3 scripts/stamp_added.py            # uses the top-level "updated" date
    python3 scripts/stamp_added.py 2026-11-17 # or an explicit publish date
Rows that already have "added" are never changed. The board shows a "New" tag
only on the Eastern-time calendar day a row was published ("added"); it drops
off at midnight ET. "Today" is computed in the browser in America/New_York.
"""
import json, re, sys

PATH = "data/triggers.json"
d = json.load(open(PATH))
day = sys.argv[1] if len(sys.argv) > 1 else d["updated"]
if not re.match(r"\d{4}-\d{2}-\d{2}$", day):
    sys.exit("bad date: " + day)
n = 0
for r in d["rows"]:
    if not r.get("added"):
        # keep "added" next to "date" for readability
        items = list(r.items()); r.clear()
        for k, v in items:
            r[k] = v
            if k == "date": r["added"] = day
        if "added" not in r: r["added"] = day
        n += 1
with open(PATH, "w") as f:
    f.write(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
print(n, "rows stamped added =", day)
