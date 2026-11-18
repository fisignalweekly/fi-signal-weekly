#!/usr/bin/env python3
import json,sys,re,os
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from trigger_types import TYPES  # the one list of board types
d=json.load(open("data/triggers.json"));ok=True
# every board type needs its label, filter option and colors on the site
_app,_idx,_css=(open(p).read() for p in ("js/app.js","index.html","css/style.css"))
for t,label in TYPES.items():
    if not re.search(r"\b"+t+r':"'+re.escape(label)+'"',_app): print("type missing from js/app.js TYPE_LABEL:",t);ok=False
    if 'value="'+t+'"' not in _idx: print("type missing from #f-type in index.html:",t);ok=False
    if ".badge."+t not in _css or ".card."+t not in _css: print("type missing colors in css/style.css:",t);ok=False
for r in d["rows"]:
    for k in ("id","type","institution","state","date","summary","source_url"):
        if not r.get(k): print("missing",k,r.get("id"));ok=False
    if r["type"] not in TYPES: print("bad type",r["id"],r["type"]);ok=False
    if not re.match(r"\d{4}-\d{2}-\d{2}$",r["date"]): print("bad date",r["id"]);ok=False
    if not r["source_url"].startswith("http"): print("bad url",r["id"]);ok=False
    # "added" = date the row went live on the board (drives the "New" tag, shown only that ET calendar day); set it with scripts/stamp_added.py
    # "backfill": true = historical site-only row; never gets a "New" tag; added should be the row's own date
    if "backfill" in r and r["backfill"] is not True and r["backfill"] is not False:
        print("bad backfill",r["id"]);ok=False
    if "added" not in r:
        if r.get("backfill") is True: print("warning: backfill row missing added (set added to the row's own date)",r["id"])
        else: print("warning: missing added (run scripts/stamp_added.py)",r["id"])
    elif not re.match(r"\d{4}-\d{2}-\d{2}$",str(r["added"])): print("bad added",r["id"]);ok=False
if not re.match(r"\d{4}-\d{2}-\d{2}$",str(d.get("updated",""))): print("bad top-level updated");ok=False
# institution database + links written by scripts/build_fi_db.py and scripts/link_institutions.py
import os
inst={}
if os.path.exists("data/institutions.json"):
    db=json.load(open("data/institutions.json"));cols=db["columns"]
    for x in db["rows"]:
        x=dict(zip(cols,x))
        if x["charter_type"] not in ("bank","cu") or not re.match(r"(fdic|ncua)-\d+$",x["id"]): print("bad institution",x["id"]);ok=False
        if x["total_assets"]!="" and not re.match(r"\d{4}Q[1-4]$",x["assets_as_of"]): print("bad assets_as_of",x["id"]);ok=False
        inst[x["id"]]=x
    if len(inst)!=len(db["rows"]): print("duplicate institution ids");ok=False
linked=0
for r in d["rows"]:
    if "fi_id" not in r:
        if "charter_type" in r: print("charter_type without fi_id",r["id"]);ok=False
        continue
    linked+=1
    if inst and r["fi_id"] not in inst: print("fi_id not in institutions.json",r["id"],r["fi_id"]);ok=False
    if r.get("charter_type") not in ("bank","cu"): print("bad charter_type",r["id"]);ok=False
    if r.get("fi_assets_usd") is not None and not isinstance(r["fi_assets_usd"],int): print("bad fi_assets_usd",r["id"]);ok=False
    if r.get("fi_assets_usd") is not None and not re.match(r"\d{4}Q[1-4]$",str(r.get("fi_assets_as_of"))): print("bad fi_assets_as_of",r["id"]);ok=False
# provider evidence for /fi/ pages (data/providers.csv; see data/README-providers.md)
import csv
PROV_COLS=["fi_id","field","value","status","source_type","source_url","last_updated","note"]
PROV_SOURCES={"Login page scan","Vendor press release","FI announcement","Press release","Regulator filing"}
if os.path.exists("data/providers.csv"):
    with open("data/providers.csv",newline="",encoding="utf-8") as f:
        rd=csv.DictReader(f); prov=list(rd)
    if rd.fieldnames!=PROV_COLS: print("providers.csv columns must be",",".join(PROV_COLS));ok=False
    seen=set();pc={"core":set(),"digital":set()}
    for i,r in enumerate(prov,2):
        tag=f"providers.csv line {i}"
        if inst and r["fi_id"] not in inst: print(tag,"fi_id not in institutions.json",r["fi_id"]);ok=False
        if r["field"] not in ("core","digital"): print(tag,"bad field",r["field"]);ok=False
        if not r["value"].strip() or r["value"].strip().lower() in ("not yet identified","unknown","n/a"): print(tag,"empty value (leave the row out instead)");ok=False
        if r["status"] not in ("current","announced"): print(tag,"bad status",r["status"]);ok=False
        if r["source_type"] not in PROV_SOURCES: print(tag,"bad source_type",r["source_type"]);ok=False
        if not r["source_url"].startswith("http"): print(tag,"bad source_url");ok=False
        if not re.match(r"\d{4}-\d{2}-\d{2}$",r["last_updated"]): print(tag,"bad last_updated");ok=False
        if r["field"]=="core" and r["source_type"]=="Login page scan": print(tag,"core can't come from a login page scan (leads only)");ok=False
        if r["status"]=="announced" and r["source_type"]=="Login page scan": print(tag,"a login page scan can't announce a change");ok=False
        k=(r["fi_id"],r["field"],r["value"],r["status"],r["source_url"])
        if k in seen: print(tag,"duplicate row");ok=False
        seen.add(k)
        if r["field"] in pc: pc[r["field"]].add(r["fi_id"])
    print(f"providers.csv: {len(prov)} rows, core for {len(pc['core'])} institutions, digital for {len(pc['digital'])}")
print(f"{linked} rows linked to institutions.json ({len(inst)} institutions)")
print(len(d["rows"]),"rows","OK" if ok else "ERRORS");sys.exit(0 if ok else 1)
