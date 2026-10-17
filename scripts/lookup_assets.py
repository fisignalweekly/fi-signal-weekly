#!/usr/bin/env python3
"""Look up state + total assets for a US bank (FDIC BankFind API) or credit union (NCUA call-report data).

  python3 scripts/lookup_assets.py "Byline Bank"                # FDIC + NCUA matches
  python3 scripts/lookup_assets.py "TDECU" --cu --state TX
  python3 scripts/lookup_assets.py --candidates                 # annotate exec_candidates.json with asset_matches

Matches are SUGGESTIONS (fuzzy). Confirm the legal entity before copying into triggers.json, and
record CERT/charter + report date in assets_note. Assets are returned in $ millions.
NCUA data: quarterly call-report zip, cached in /workspace/fisignal-state/ncua (FOICU.txt names/state, FS220.txt ACCT_010 = total assets).
"""
import argparse, csv, datetime as dt, difflib, io, json, os, re, sys, time, urllib.parse, urllib.request, zipfile

STATE_DIR = os.environ.get("FISIGNAL_STATE", "/workspace/fisignal-state")
NCUA_DIR = os.path.join(STATE_DIR, "ncua")
UA = "FI Signal Weekly fisignal@mail.grokbot.com"
STOP = {"inc", "corp", "corporation", "co", "company", "the", "of", "and", "financial", "bancorp", "bancshares", "holding", "holdings", "group", "bank", "national", "association", "na", "n.a.", "federal", "credit", "union", "fcu", "cu", "trust", "savings", "&"}

def get(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read()

def norm(s):
    s = re.sub(r"[^a-z0-9& ]", " ", (s or "").lower())
    return " ".join(w for w in s.split())

def core(s):
    return " ".join(w for w in norm(s).split() if w not in STOP)

def score(a, b):
    ca, cb = core(a), core(b)
    if not ca or not cb: return 0
    r = difflib.SequenceMatcher(None, ca, cb).ratio()
    if min(len(ca), len(cb)) >= 5 and (re.search(r"\b%s\b" % re.escape(ca), cb) or re.search(r"\b%s\b" % re.escape(cb), ca)): r = max(r, 0.9)
    return r

# ---- FDIC
def fdic(name, state=None, limit=5):
    c = re.sub(r"\b(inc|corp|corporation|co|company|holdings?)\b\.?", "", name, flags=re.I).strip(" ,.")
    out = {}
    for q in (f'NAME:"{c}"', f'NAMEHCR:"{c}"', "NAME:(" + " AND ".join(w for w in re.findall(r"[A-Za-z0-9]+", c)[:4]) + ")"):
        if not c: break
        search = q + " AND ACTIVE:1" + (f" AND STALP:{state}" if state else "")
        u = "https://api.fdic.gov/banks/institutions?" + urllib.parse.urlencode({"search": search, "fields": "NAME,CITY,STALP,ASSET,REPDTE,CERT,NAMEHCR", "sort_by": "ASSET", "sort_order": "DESC", "limit": 15})
        try: d = json.loads(get(u))
        except Exception: continue
        for r in d.get("data", []):
            r = r["data"]
            if r.get("ASSET") is None: continue
            sc = max(score(name, r["NAME"]), score(name, r.get("NAMEHCR") or ""))
            out[r["CERT"]] = {"kind": "bank", "name": r["NAME"], "holding_co": r.get("NAMEHCR"), "state": r["STALP"], "city": r["CITY"],
                              "assets_millions": round(r["ASSET"] / 1000, 1), "report_date": r["REPDTE"], "id": f"CERT {r['CERT']}", "match": round(sc, 2),
                              "source": f"https://api.fdic.gov/banks/institutions?filters=CERT%3A{r['CERT']}&fields=NAME,STALP,ASSET,REPDTE"}
        if out: break
    return sorted(out.values(), key=lambda x: -x["match"])[:limit]

# ---- NCUA
_cu = None
def ncua_load():
    global _cu
    if _cu is not None: return _cu
    os.makedirs(NCUA_DIR, exist_ok=True)
    foicu, fs = os.path.join(NCUA_DIR, "FOICU.txt"), os.path.join(NCUA_DIR, "FS220.txt")
    stale = not os.path.exists(foicu) or time.time() - os.path.getmtime(foicu) > 80 * 86400
    if stale:
        t = dt.date.today(); y, m = t.year, (t.month - 1) // 3 * 3
        tried = []
        for _ in range(6):  # newest published quarter first
            if m <= 0: y, m = y - 1, 12
            u = f"https://ncua.gov/files/publications/analysis/call-report-data-{y}-{m:02d}.zip"
            try:
                z = zipfile.ZipFile(io.BytesIO(get(u, 120)))
                for n in ("FOICU.txt", "FS220.txt", "TradeNames.txt"): open(os.path.join(NCUA_DIR, n), "wb").write(z.read(n))
                open(os.path.join(NCUA_DIR, "quarter.txt"), "w").write(f"{y}-{m:02d}")
                break
            except Exception: tried.append(u); m -= 3
        else:
            if not os.path.exists(foicu): raise SystemExit("NCUA data unavailable: " + ", ".join(tried))
    q = open(os.path.join(NCUA_DIR, "quarter.txt")).read().strip() if os.path.exists(os.path.join(NCUA_DIR, "quarter.txt")) else "?"
    assets = {}
    with open(fs, newline="", encoding="latin-1") as f:
        for r in csv.DictReader(f):
            try: assets[r["CU_NUMBER"]] = float(r["ACCT_010"])
            except Exception: pass
    trade = {}
    try:
        with open(os.path.join(NCUA_DIR, "TradeNames.txt"), newline="", encoding="latin-1") as f:
            for r in csv.DictReader(f): trade.setdefault(r["CU_NUMBER"], []).append(r["TradeName"])
    except FileNotFoundError: pass
    _cu = []
    with open(foicu, newline="", encoding="latin-1") as f:
        for r in csv.DictReader(f):
            a = assets.get(r["CU_NUMBER"])
            _cu.append({"kind": "credit_union", "name": re.sub(r"'S\b", "'s", r["CU_NAME"].title()), "state": r["STATE"], "city": r["CITY"].title(), "assets_millions": round(a / 1e6, 1) if a is not None else None,
                        "aliases": trade.get(r["CU_NUMBER"], []), "report_date": q, "id": f"NCUA charter {r['CU_NUMBER']}", "source": "https://ncua.gov/analysis/credit-union-corporate-call-report-data"})
    return _cu

def ncua(name, state=None, limit=5):
    res = []
    for r in ncua_load():
        if state and r["state"] != state: continue
        s = max([score(name, r["name"])] + [score(name, t) for t in r["aliases"]])
        if s >= 0.6: res.append({**r, "match": round(s, 2)})
    return sorted(res, key=lambda x: (-x["match"], -(x["assets_millions"] or 0)))[:limit]

def lookup(name, state=None, kind=None):
    out = []
    looks_cu = bool(re.search(r"credit union|fcu|\bcu\b", name, re.I))
    if kind != "cu" and not (looks_cu and kind is None): out += fdic(name, state)
    if kind != "bank": out += ncua(name, state)
    return sorted(out, key=lambda x: -x["match"])[:6]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?"); ap.add_argument("--state"); ap.add_argument("--cu", action="store_true"); ap.add_argument("--bank", action="store_true")
    ap.add_argument("--candidates", nargs="?", const=os.path.join(STATE_DIR, "exec_candidates.json"))
    a = ap.parse_args()
    if a.candidates:
        d = json.load(open(a.candidates)); n = 0
        for c in d["candidates"]:
            if c.get("institution"):
                c["asset_matches"] = [m for m in lookup(c["institution"], c.get("state") or None) if m["match"] >= 0.7][:3]; n += bool(c["asset_matches"])
        json.dump(d, open(a.candidates, "w"), indent=1); print(f"annotated {n} of {len(d['candidates'])} candidates"); return
    if not a.name: ap.error("name or --candidates required")
    print(json.dumps(lookup(a.name, a.state, "cu" if a.cu else "bank" if a.bank else None), indent=1))

if __name__ == "__main__":
    main()
