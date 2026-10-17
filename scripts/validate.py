#!/usr/bin/env python3
import json,sys,re
d=json.load(open("data/triggers.json"));ok=True
for r in d["rows"]:
    for k in ("id","type","institution","state","date","summary","source_url"):
        if not r.get(k): print("missing",k,r.get("id"));ok=False
    if r["type"] not in("merger","core","executive"): print("bad type",r["id"]);ok=False
    if not re.match(r"\d{4}-\d{2}-\d{2}$",r["date"]): print("bad date",r["id"]);ok=False
    if not r["source_url"].startswith("http"): print("bad url",r["id"]);ok=False
print(len(d["rows"]),"rows","OK" if ok else "ERRORS");sys.exit(0 if ok else 1)
