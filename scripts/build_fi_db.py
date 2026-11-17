#!/usr/bin/env python3
"""Build the FI Signal Weekly institution database: every active US bank (FDIC) and credit union (NCUA).

    python3 scripts/build_fi_db.py            # fetch sources, write data/institutions.csv + data/institutions.json
    python3 scripts/build_fi_db.py --offline  # rebuild from cached source files only (no network)

Sources (public, free):
  * Banks: FDIC BankFind Suite API, institutions endpoint, ACTIVE:1
    (https://api.fdic.gov/banks/institutions; banks.data.fdic.gov/api redirects there).
    ASSET is in $ thousands; REPDTE is the call report date it comes from.
  * Credit unions: NCUA 5300 Call Report quarterly data zip
    (https://ncua.gov/files/publications/analysis/call-report-data-YYYY-MM.zip):
    FOICU.txt (name, type, city, state), FS220.txt ACCT_010 (total assets, $),
    FS220D.txt Acct_891 (website as reported by the credit union).
    Websites missing from the call report are filled from the NCUA Credit Union Locator
    (https://mapping.ncua.gov/api/CreditUnionDetails/GetCreditUnionDetails/<charter>), cached on disk.
    Nothing is ever guessed: no source value -> blank.

Idempotent: output is sorted and contains no run timestamps, so re-running on unchanged sources
produces byte-identical files (git shows no diff).

Exit codes:
  0  success (files written, or already up to date)
  1  a source could not be fetched/parsed (nothing written)
  2  sanity check failed (counts out of the expected range; nothing written)
"""
import argparse, csv, datetime as dt, io, json, os, re, sys, time, urllib.parse, urllib.request, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CACHE = os.environ.get("FISIGNAL_FIDB_CACHE", "/workspace/fisignal-state/fidb-cache")
UA = "FI Signal Weekly fisignal@mail.grokbot.com"
FDIC_URL = "https://api.fdic.gov/banks/institutions"
NCUA_ZIP = "https://ncua.gov/files/publications/analysis/call-report-data-{y}-{m:02d}.zip"
LOCATOR = "https://mapping.ncua.gov/api/CreditUnionDetails/GetCreditUnionDetails/{}"
COLUMNS = ["id", "name", "charter_type", "charter_class", "city", "state", "website",
           "total_assets", "assets_as_of", "assets_report_date", "holding_company", "also_known_as"]
# Plausible ranges for a sanity check (FDIC listed 4,208 active institutions and NCUA 4,299
# call-report filers in Nov 2026). Wide on purpose: they catch a broken pull, not normal attrition.
RANGES = {"bank": (3000, 6000), "cu": (3000, 6000)}
NCUA_TYPES = {"1": "FCU", "2": "FISCU", "3": "NFICU"}  # federal / federally insured state / non-federally insured state


class SourceError(Exception):
    pass


def log(*a):
    print(*a, file=sys.stderr)


def get(url, timeout=120, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last = e
        except Exception as e:
            last = e
        time.sleep(2 * (i + 1))
    raise SourceError(f"{url}: {last}")


def quarter(d):
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def clean_url(u):
    u = (u or "").strip()
    if not u or u.lower() in ("n/a", "na", "none", "null", "0"):
        return ""
    return u.rstrip("/")


# ---------------------------------------------------------------- FDIC
def fdic_rows(offline):
    path = os.path.join(CACHE, "fdic_institutions.json")
    if not offline:
        fields = "CERT,NAME,CITY,STALP,WEBADDR,ASSET,REPDTE,BKCLASS,NAMEHCR,ACTIVE"
        rows, offset, total = [], 0, None
        while total is None or offset < total:
            q = urllib.parse.urlencode({"filters": "ACTIVE:1", "fields": fields, "sort_by": "CERT",
                                        "sort_order": "ASC", "limit": 5000, "offset": offset})
            try:
                d = json.loads(get(f"{FDIC_URL}?{q}"))
            except (SourceError, urllib.error.HTTPError, ValueError) as e:
                raise SourceError(f"FDIC API: {e}")
            total = d["meta"]["total"]
            batch = [x["data"] for x in d.get("data", [])]
            if not batch:
                break
            rows += batch
            offset += len(batch)
        if len(rows) != total:
            raise SourceError(f"FDIC API returned {len(rows)} of {total} rows")
        os.makedirs(CACHE, exist_ok=True)
        json.dump(rows, open(path + ".tmp", "w"))
        os.replace(path + ".tmp", path)
    if not os.path.exists(path):
        raise SourceError("no cached FDIC data (run without --offline)")
    out = []
    for r in json.load(open(path)):
        rep = dt.datetime.strptime(r["REPDTE"], "%m/%d/%Y").date() if r.get("REPDTE") else None
        asset = r.get("ASSET")
        out.append({
            "id": f"fdic-{int(r['CERT'])}", "name": (r.get("NAME") or "").strip(), "charter_type": "bank",
            "charter_class": r.get("BKCLASS") or "", "city": (r.get("CITY") or "").strip(),
            "state": (r.get("STALP") or "").strip(), "website": clean_url(r.get("WEBADDR")),
            "total_assets": int(round(asset * 1000)) if asset is not None else "",
            "assets_as_of": quarter(rep) if rep and asset is not None else "",
            "assets_report_date": rep.isoformat() if rep and asset is not None else "",
            "holding_company": (r.get("NAMEHCR") or "").strip(), "also_known_as": "",
        })
    return out


# ---------------------------------------------------------------- NCUA
def ncua_zip(offline):
    """Return (zip bytes, date of the quarter end) for the newest published NCUA call report zip."""
    os.makedirs(CACHE, exist_ok=True)
    t = dt.date.today()
    y, m = t.year, (t.month - 1) // 3 * 3 + 3  # current quarter end month; newest first
    tried = []
    for _ in range(6):
        if m <= 0:
            y, m = y - 1, m + 12
        path = os.path.join(CACHE, f"call-report-data-{y}-{m:02d}.zip")
        if os.path.exists(path):
            return open(path, "rb").read(), (y, m)
        if not offline:
            u = NCUA_ZIP.format(y=y, m=m)
            try:
                b = get(u, timeout=300)
                zipfile.ZipFile(io.BytesIO(b)).testzip()
                open(path + ".tmp", "wb").write(b)
                os.replace(path + ".tmp", path)
                return b, (y, m)
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise SourceError(f"{u}: HTTP {e.code}")
            except zipfile.BadZipFile:
                pass  # not published yet (some hosts serve an HTML page)
            tried.append(u)
        m -= 3
    raise SourceError("NCUA call report zip not found: " + ", ".join(tried))


def read_csv(z, name):
    for n in z.namelist():
        if n.lower() == name.lower():
            return list(csv.DictReader(io.StringIO(z.read(n).decode("latin-1"))))
    raise SourceError(f"{name} missing from NCUA zip")


def locator_websites(charters, offline):
    """Websites from the NCUA Credit Union Locator for charters the call report left blank. Cached forever
    per charter+quarter (a blank answer is cached too, so re-runs don't re-hit the API)."""
    path = os.path.join(CACHE, "ncua_locator_websites.json")
    cache = json.load(open(path)) if os.path.exists(path) else {}
    todo = [c for c in charters if c not in cache]
    if todo and not offline:
        log(f"NCUA locator: looking up {len(todo)} websites (cached after this run)")
        for i, c in enumerate(todo):
            try:
                d = json.loads(get(LOCATOR.format(c), timeout=30))
                cache[c] = clean_url(d.get("creditUnionWebsite"))
            except Exception as e:
                log(f"  locator {c}: {e} (left blank, retried next run)")
                continue
            if i % 50 == 49:
                json.dump(cache, open(path, "w"), sort_keys=True)
            time.sleep(0.25)  # be polite: ~4 requests/second at most
        json.dump(cache, open(path, "w"), sort_keys=True)
    return {c: cache.get(c, "") for c in charters}


def ncua_rows(offline):
    b, (y, m) = ncua_zip(offline)
    z = zipfile.ZipFile(io.BytesIO(b))
    rep = dt.date(y, m, 30 if m in (6, 9) else 31)
    foicu = read_csv(z, "FOICU.txt")
    assets = {}
    for r in read_csv(z, "FS220.txt"):
        try:
            assets[r["CU_NUMBER"].strip()] = int(round(float(r["ACCT_010"])))
        except (KeyError, ValueError):
            pass
    web = {}
    for r in read_csv(z, "FS220D.txt"):
        v = r.get("Acct_891") or r.get("ACCT_891")
        if clean_url(v):
            web[r["CU_NUMBER"].strip()] = clean_url(v)
    trade = {}
    for r in read_csv(z, "TradeNames.txt"):
        t = (r.get("TradeName") or "").strip()
        if t:
            trade.setdefault(r["CU_NUMBER"].strip(), set()).add(t)
    missing = sorted({r["CU_NUMBER"].strip() for r in foicu} - set(web), key=int)
    web.update({c: u for c, u in locator_websites(missing, offline).items() if u})
    cycle = {r.get("CYCLE_DATE", "").split(" ")[0] for r in foicu}
    out = []
    for r in foicu:
        c = r["CU_NUMBER"].strip()
        a = assets.get(c)
        out.append({
            "id": f"ncua-{int(c)}", "name": titlecase(r["CU_NAME"]), "charter_type": "cu",
            "charter_class": NCUA_TYPES.get(r.get("CU_TYPE", "").strip(), r.get("CU_TYPE", "").strip()),
            "city": titlecase(r["CITY"]), "state": r["STATE"].strip(), "website": web.get(c, ""),
            "total_assets": a if a is not None else "",
            "assets_as_of": quarter(rep) if a is not None else "",
            "assets_report_date": rep.isoformat() if a is not None else "",
            "holding_company": "", "also_known_as": "|".join(sorted(trade.get(c, ()))),
        })
    return out, rep, cycle, len(missing)


SMALL = {"of", "and", "the", "for", "in", "at", "on", "de", "del", "la"}
ACRONYMS = {"US", "USA", "U.S.", "IBM", "NASA", "EPB", "IBEW", "UAW", "TVA", "AFL", "CIO", "GE", "AT&T", "SAFE", "BECU",
            "USAA", "FAA", "CIA", "FBI", "IRS", "NIH", "NJ", "NY", "UNO", "MIT", "ABD", "AEA", "AMOCO", "TEG", "UFCW"}
NO_CAPS = {"ST", "MT", "FT", "DR", "SR", "JR"}
def titlecase(s):
    """NCUA names/cities are ALL CAPS; title-case them, keeping credit-union style acronyms (FCU, TDECU),
    vowel-less abbreviations (NW, PSG) and a short list of known acronyms in capitals."""
    words = []
    for i, w in enumerate((s or "").strip().split()):
        bare = re.sub(r"[^A-Z&.]", "", w)
        if w in ACRONYMS or re.fullmatch(r"[A-Z]{2,}CU", w) or w in ("CU", "FCU") or (
                bare == w and w.rstrip(".") not in NO_CAPS and 1 < len(w) <= 5 and not re.search(r"[AEIOUY]", w)):
            words.append(w)
        elif w.lower() in SMALL and i:
            words.append(w.lower())
        else:
            t = re.sub(r"[A-Za-z]+('[A-Za-z]+)?", lambda m: m.group(0).capitalize(), w.lower())
            words.append(re.sub(r"^(Mc)([a-z])", lambda m: m.group(1) + m.group(2).upper(), t))
    return " ".join(words)


# ---------------------------------------------------------------- output
def write_if_changed(path, text):
    old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
    if old == text:
        return False
    open(path + ".tmp", "w", encoding="utf-8", newline="").write(text)
    os.replace(path + ".tmp", path)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="use cached source files only")
    a = ap.parse_args()
    try:
        banks = fdic_rows(a.offline)
        cus, cu_rep, cycle, cu_missing_web = ncua_rows(a.offline)
    except SourceError as e:
        log(f"ERROR: {e}")
        return 1
    rows = sorted(banks + cus, key=lambda r: (r["charter_type"], int(r["id"].split("-")[1])))
    ids = [r["id"] for r in rows]
    problems = []
    if len(set(ids)) != len(ids):
        problems.append("duplicate ids")
    for kind, (lo, hi) in RANGES.items():
        n = sum(r["charter_type"] == kind for r in rows)
        if not lo <= n <= hi:
            problems.append(f"{kind} count {n} outside {lo}-{hi}")
    if any(not r["name"] or not r["state"] for r in rows):
        problems.append("rows missing name/state")
    if problems:
        log("SANITY CHECK FAILED: " + "; ".join(problems))
        return 2

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    quarters = {}
    for r in rows:
        if r["assets_as_of"]:
            quarters.setdefault(r["charter_type"], {}).setdefault(r["assets_as_of"], 0)
            quarters[r["charter_type"]][r["assets_as_of"]] += 1
    summary = {}
    for kind in ("bank", "cu"):
        rs = [r for r in rows if r["charter_type"] == kind]
        summary[kind] = {"rows": len(rs), "with_website": sum(bool(r["website"]) for r in rs),
                         "with_assets": sum(r["total_assets"] != "" for r in rs),
                         "assets_as_of": dict(sorted(quarters.get(kind, {}).items()))}
    meta = {
        "sources": {
            "bank": "FDIC BankFind Suite API, institutions, ACTIVE:1 (https://api.fdic.gov/banks/institutions)",
            "cu": f"NCUA 5300 Call Report quarterly data, cycle {cu_rep.isoformat()} "
                  f"({NCUA_ZIP.format(y=cu_rep.year, m=cu_rep.month)}); websites from FS220D Acct_891, "
                  "else the NCUA Credit Union Locator",
        },
        "columns": COLUMNS, "counts": summary,
    }
    js = json.dumps({**meta, "rows": [[r[c] for c in COLUMNS] for r in rows]}, ensure_ascii=False,
                    separators=(",", ":"))
    js = js.replace("],[", "],\n[") + "\n"  # one record per line: readable diffs
    changed = [p for p, t in ((os.path.join(DATA, "institutions.csv"), buf.getvalue()),
                              (os.path.join(DATA, "institutions.json"), js)) if write_if_changed(p, t)]

    print("FI database build")
    for kind, label in (("bank", "Banks (FDIC)"), ("cu", "Credit unions (NCUA)")):
        s = summary[kind]
        print(f"  {label:22} {s['rows']:>5} rows | websites {s['with_website']} | assets {s['with_assets']} | as of {s['assets_as_of']}")
    print(f"  {'Total':22} {len(rows):>5} rows")
    print(f"  NCUA call-report cycle {sorted(cycle)}; {cu_missing_web} CUs had no call-report website "
          f"({summary['cu']['rows'] - summary['cu']['with_website']} still blank after the locator)")
    print("  wrote: " + (", ".join(os.path.relpath(p, ROOT) for p in changed) if changed else "nothing (already up to date)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
