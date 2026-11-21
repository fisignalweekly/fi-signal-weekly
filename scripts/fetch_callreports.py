#!/usr/bin/env python3
"""Call report history for every institution page: data/callreports.json.

    python3 scripts/fetch_callreports.py            # fetch anything missing into the cache, then write data/callreports.json
    python3 scripts/fetch_callreports.py --offline  # rebuild from the cache only

Public sources only (no keys):
  FDIC BankFind  https://api.fdic.gov/banks/financials  ASSET, DEP, LNLSNET by REPDTE ($ thousands), one call per quarter
                 https://api.fdic.gov/banks/institutions OFFICES, FED_RSSD, ESTYMD for active banks
                 https://api.fdic.gov/banks/history     institution-level events (ORG_ROLE_CDE:FI) since 2016
  NCUA 5300      https://ncua.gov/files/publications/analysis/call-report-data-YYYY-MM.zip (2016-03 onward)
                 FS220: ACCT_010 total assets, ACCT_018 shares and deposits, ACCT_025B loans and leases, ACCT_083 members
                 FOICU: RSSD, YEAR_OPENED; "Credit Union Branch Information": offices by SiteTypeName (latest quarter)
Raw downloads are cached in $FISIGNAL_CALLREPORTS (default /workspace/fi-signal/callreports). Output is sorted and has
no run timestamps, so the same cache gives an identical file. Money is in $ thousands (NCUA dollars are rounded to
thousands). A quarter an institution didn't file is null. Nothing is estimated.
Exit codes: 0 ok, 1 a source could not be fetched or parsed.
"""
import argparse, csv, io, json, os, sys, time, urllib.parse, urllib.request, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.environ.get("FISIGNAL_CALLREPORTS", "/workspace/fi-signal/callreports")
OUT = os.path.join(ROOT, "data", "callreports.json")
UA = "FISignalWeeklyBot/1.0 (+https://fisignalweekly.com; hello@fisignalweekly.com)"
FIRST = (2016, 1)
HIST_CODES = {110, 211, 221, 222, 223, 224, 420, 430, 440, 510, 712, 810, 811}


def get(url, path, offline):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    if offline:
        raise OSError(f"not cached: {path}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r, open(path + ".part", "wb") as f:
        f.write(r.read())
    os.replace(path + ".part", path)
    time.sleep(1)
    return path


def quarters(last):
    y, q = FIRST
    out = []
    while (y, q) <= last:
        out.append((y, q))
        y, q = (y, q + 1) if q < 4 else (y + 1, 1)
    return out


def qlabel(y, q):
    return f"{y}Q{q}"


def k(v):
    try:
        return int(round(float(v) / 1000))
    except (TypeError, ValueError):
        return None


def zip_member(z, name):
    for i in z.namelist():
        if i.lower() == name.lower():
            return i
    raise KeyError(name)


def rows_ci(z, name):
    with z.open(zip_member(z, name)) as f:
        for r in csv.DictReader(io.TextIOWrapper(f, encoding="latin-1")):
            yield {(a or "").upper(): b for a, b in r.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    db = json.load(open(os.path.join(ROOT, "data", "institutions.json")))
    cols = db["columns"]
    ids = {dict(zip(cols, r))["id"] for r in db["rows"]}
    as_of = max(dict(zip(cols, r))["assets_as_of"] for r in db["rows"] if dict(zip(cols, r))["assets_as_of"])
    last = (int(as_of[:4]), int(as_of[5]))
    qs = quarters(last)
    n = len(qs)
    fi = {i: {"a": [None] * n, "d": [None] * n, "l": [None] * n} for i in ids}
    try:
        # FDIC financials, one bulk call per quarter
        for j, (y, q) in enumerate(qs):
            d = f"{y}{['0331', '0630', '0930', '1231'][q - 1]}"
            url = ("https://api.fdic.gov/banks/financials?" + urllib.parse.urlencode(
                {"filters": f"REPDTE:{d}", "fields": "CERT,REPDTE,ASSET,DEP,LNLSNET", "limit": 10000, "format": "json"}))
            data = json.load(open(get(url, f"{CACHE}/fdic/fin-{d}.json", a.offline)))
            if data["meta"]["total"] > len(data["data"]):
                raise ValueError(f"FDIC {d}: paged result")
            for x in data["data"]:
                x = x["data"]
                i = f"fdic-{x['CERT']}"
                if i in fi:
                    fi[i]["a"][j], fi[i]["d"][j], fi[i]["l"][j] = x.get("ASSET"), x.get("DEP"), x.get("LNLSNET")
        url = ("https://api.fdic.gov/banks/institutions?" + urllib.parse.urlencode(
            {"filters": "ACTIVE:1", "fields": "CERT,OFFICES,FED_RSSD,ESTYMD", "limit": 10000, "format": "json"}))
        for x in json.load(open(get(url, f"{CACHE}/fdic/institutions-offices.json", a.offline)))["data"]:
            x = x["data"]
            i = f"fdic-{x['CERT']}"
            if i in fi:
                if x.get("OFFICES") is not None:
                    fi[i]["off"] = x["OFFICES"]
                fi[i]["rssd"] = str(x.get("FED_RSSD") or "")
                m, dd, yy = (x.get("ESTYMD") or "//").split("/")
                if yy:
                    fi[i]["est"] = f"{yy}-{m}-{dd}"
        # FDIC institution-level history since 2016
        hist_path = f"{CACHE}/fdic/history-fi-2016plus.json"
        if not os.path.exists(hist_path) and not a.offline:
            F = "CERT,CHANGECODE,CHANGECODE_DESC,EFFDATE,OUT_CERT,OUT_INSTNAME,ACQ_INSTNAME,INSTNAME,FRM_INSTNAME,FRM_CLASS,CLASS,TRANSNUM"
            allr, off = [], 0
            while True:
                url = "https://api.fdic.gov/banks/history?" + urllib.parse.urlencode(
                    {"filters": 'ORG_ROLE_CDE:FI AND EFFDATE:["2016-01-01" TO "2099-12-31"]', "fields": F, "limit": 10000,
                     "offset": off, "format": "json", "sort_by": "EFFDATE", "sort_order": "ASC"})
                d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=180))
                rows = [x["data"] for x in d["data"]]
                allr += rows
                off += len(rows)
                if not rows or off >= d["meta"]["total"]:
                    break
            json.dump(allr, open(hist_path, "w"))
        hist = {}
        for r in json.load(open(hist_path)):
            i = f"fdic-{r.get('CERT')}"
            if i not in fi or r.get("CHANGECODE") not in HIST_CODES:
                continue
            ev = {"date": r["EFFDATE"][:10], "code": r["CHANGECODE"], "desc": r["CHANGECODE_DESC"]}
            for f_, t_ in (("OUT_INSTNAME", "other"), ("FRM_INSTNAME", "from_name"), ("INSTNAME", "name"), ("FRM_CLASS", "from_class"), ("CLASS", "class")):
                if r.get(f_):
                    ev[t_] = r[f_]
            hist.setdefault(i, []).append(ev)
        # NCUA quarterly zips
        latest_zip = None
        for j, (y, q) in enumerate(qs):
            name = f"call-report-data-{y}-{q * 3:02d}.zip"
            p = get(f"https://ncua.gov/files/publications/analysis/{name}", f"{CACHE}/ncua/{name}", a.offline)
            z = zipfile.ZipFile(p)
            latest_zip = z
            for r in rows_ci(z, "FS220.txt"):
                i = f"ncua-{int(r['CU_NUMBER'])}"
                if i in fi:
                    f_ = fi[i]
                    f_["a"][j], f_["d"][j], f_["l"][j] = k(r.get("ACCT_010")), k(r.get("ACCT_018")), k(r.get("ACCT_025B"))
                    f_.setdefault("m", [None] * n)[j] = int(float(r["ACCT_083"])) if r.get("ACCT_083") not in (None, "") else None
        for r in rows_ci(latest_zip, "FOICU.txt"):
            i = f"ncua-{int(r['CU_NUMBER'])}"
            if i in fi:
                fi[i]["rssd"] = (r.get("RSSD") or "").strip()
                if (r.get("YEAR_OPENED") or "").strip():
                    fi[i]["est"] = r["YEAR_OPENED"].strip()[:10]
        for r in rows_ci(latest_zip, "Credit Union Branch Information.txt"):
            i = f"ncua-{int(r['CU_NUMBER'])}"
            if i in fi:
                b = fi[i].setdefault("sites", {"Branch Office": 0, "Corporate Office": 0})
                b[r["SITETYPENAME"]] = b.get(r["SITETYPENAME"], 0) + 1
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as ex:
        print("error:", ex, file=sys.stderr)
        return 1
    for i, v in hist.items():
        fi[i]["hist"] = sorted(v, key=lambda e: (e["date"], e["code"], e.get("other", "")), reverse=True)
    lines = ",\n".join(json.dumps(i) + ":" + json.dumps(fi[i], separators=(",", ":"), sort_keys=True) for i in sorted(fi))
    head = {"quarters": [qlabel(*x) for x in qs], "as_of": qlabel(*last), "units": "USD thousands",
            "sources": {"bank": "FDIC BankFind Suite API (financials, institutions, history)",
                        "cu": "NCUA 5300 Call Report quarterly data (FS220, FOICU, Credit Union Branch Information)"}}
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(json.dumps(head, separators=(",", ":"))[:-1] + ',"fi":{\n' + lines + "\n}}\n")
    have = sum(1 for v in fi.values() if v["a"][-1] is not None)
    print(f"callreports.json: {len(fi)} institutions, {n} quarters {qlabel(*qs[0])}..{as_of}, latest-quarter assets for {have}, "
          f"history events for {len(hist)} banks, {os.path.getsize(OUT) / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
