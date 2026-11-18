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
    seen=set();pc={"core":set(),"digital":set(),"digital_business":set(),"billpay":set()}
    for i,r in enumerate(prov,2):
        tag=f"providers.csv line {i}"
        if inst and r["fi_id"] not in inst: print(tag,"fi_id not in institutions.json",r["fi_id"]);ok=False
        if r["field"] not in ("core","digital","digital_business","billpay"): print(tag,"bad field",r["field"]);ok=False
        if not r["value"].strip() or r["value"].strip().lower() in ("not yet identified","unknown","n/a"): print(tag,"empty value (leave the row out instead)");ok=False
        if r["status"] not in ("current","announced"): print(tag,"bad status",r["status"]);ok=False
        if r["source_type"] not in PROV_SOURCES: print(tag,"bad source_type",r["source_type"]);ok=False
        if not r["source_url"].startswith("http"): print(tag,"bad source_url");ok=False
        if not re.match(r"\d{4}-\d{2}-\d{2}$",r["last_updated"]): print(tag,"bad last_updated");ok=False
        if r["field"] in ("core","billpay") and r["source_type"]=="Login page scan": print(tag,r["field"],"can't come from a login page scan (leads only)");ok=False
        if r["status"]=="announced" and r["source_type"]=="Login page scan": print(tag,"a login page scan can't announce a change");ok=False
        k=(r["fi_id"],r["field"],r["value"],r["status"],r["source_url"])
        if k in seen: print(tag,"duplicate row");ok=False
        seen.add(k)
        if r["field"] in pc: pc[r["field"]].add(r["fi_id"])
    print(f"providers.csv: {len(prov)} rows; institutions with digital (retail) {len(pc['digital'])}, digital (business) {len(pc['digital_business'])}, core {len(pc['core'])}, bill pay {len(pc['billpay'])}")
# call report history (scripts/fetch_callreports.py), social links, pinned pages
if os.path.exists("data/callreports.json"):
    cr=json.load(open("data/callreports.json"));qs=cr["quarters"];n=len(qs)
    if not all(re.match(r"\d{4}Q[1-4]$",q) for q in qs) or qs!=sorted(qs) or cr["as_of"]!=qs[-1]: print("callreports.json: bad quarters/as_of");ok=False
    if inst and set(cr["fi"])!=set(inst): print("callreports.json: institutions differ from institutions.json",len(set(cr["fi"])^set(inst)));ok=False
    for i,v in cr["fi"].items():
        for k in ("a","d","l")+(("m",) if "m" in v else ()):
            if len(v.get(k) or [])!=n or any(x is not None and (not isinstance(x,int) or x<0) for x in v[k]): print("callreports.json: bad series",i,k);ok=False;break
        if "off" in v and not (isinstance(v["off"],int) and v["off"]>=0): print("callreports.json: bad offices",i);ok=False
        if "rssd" in v and not re.match(r"\d*$",v["rssd"]): print("callreports.json: bad rssd",i);ok=False
        for h in v.get("hist",[]):
            if not re.match(r"\d{4}-\d{2}-\d{2}$",h.get("date","")) or not isinstance(h.get("code"),int): print("callreports.json: bad history event",i);ok=False;break
    print(f"callreports.json: {len(cr['fi'])} institutions, {n} quarters {qs[0]}..{qs[-1]}, latest assets for {sum(1 for v in cr['fi'].values() if v['a'][-1] is not None)}")
if os.path.exists("data/social.csv"):
    with open("data/social.csv",newline="",encoding="utf-8") as f:
        rd=csv.DictReader(f);soc=list(rd)
    if rd.fieldnames!=["fi_id","network","url","found_on","checked"]: print("social.csv: bad columns");ok=False
    ids=set()
    for r in soc:
        if inst and r["fi_id"] not in inst: print("social.csv: unknown fi_id",r["fi_id"]);ok=False
        if r["network"]!="linkedin" or not re.match(r"https://www\.linkedin\.com/company/[A-Za-z0-9_\-%.]+$",r["url"]): print("social.csv: bad linkedin url",r["fi_id"]);ok=False
        if not r["found_on"].startswith("http") or "linkedin.com" in r["found_on"]: print("social.csv: found_on must be the FI's own site",r["fi_id"]);ok=False
        if not re.match(r"\d{4}-\d{2}-\d{2}$",r["checked"]): print("social.csv: bad checked",r["fi_id"]);ok=False
        if (r["fi_id"],r["network"]) in ids: print("social.csv: duplicate",r["fi_id"]);ok=False
        ids.add((r["fi_id"],r["network"]))
    print(f"social.csv: {len(soc)} LinkedIn links")
if os.path.exists("data/fi-pinned.txt"):
    for ln in open("data/fi-pinned.txt"):
        ln=ln.strip()
        if ln and not ln.startswith("#") and not os.path.exists(ln): print("fi-pinned.txt: missing page",ln);ok=False
print(f"{linked} rows linked to institutions.json ({len(inst)} institutions)")
print(len(d["rows"]),"rows","OK" if ok else "ERRORS");sys.exit(0 if ok else 1)
