#!/usr/bin/env python3
"""Asset-chart benchmarks for the /fi/ pages: data/benchmarks.json, plus the peer math build_directory.py uses.

    python3 scripts/build_benchmarks.py            # fetch BLS CPI-U if not cached, then write data/benchmarks.json
    python3 scripts/build_benchmarks.py --offline  # rebuild from the caches only

Public sources only, nothing estimated:
  FDIC BankFind financials  ASSET for every filer each quarter (same cached files as scripts/fetch_callreports.py)
  NCUA 5300 call reports    FS220 ACCT_010 total assets for every filer each quarter (same cached zips)
  BLS CPI-U                 series CUUR0000SA0 (U.S. city average, all items, not seasonally adjusted), monthly,
                            https://api.bls.gov/publicAPI/v2/timeseries/data/ ; a quarter's value is the average of
                            the months BLS published for it (Oct 2025 was never published, so Q4 2025 uses Nov+Dec).
benchmarks.json holds, per charter type ("bank" = FDIC-insured banks, "cu" = federally insured credit unions):
  total[t]   industry total assets ($ thousands) of every filer in quarter t, and n[t] filers
  med[s]     for each chart start quarter s used by a page: med[s][t] = median over institutions that filed in both
             s and t (assets > 0 in s) of assets_t / assets_s  (the all-industry median, indexed to 1 at s)
Peer-tier medians depend on today's asset tier and leave the page's own institution out, so build_directory.py computes
them at build time with Peers below (from data/callreports.json). Output is sorted and has no timestamps.
Exit codes: 0 ok, 1 a source could not be fetched or parsed.
"""
import argparse, bisect, csv, io, json, os, sys, urllib.request, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.environ.get("FISIGNAL_CALLREPORTS", "/workspace/fi-signal/callreports")
CPI_CACHE = os.environ.get("FISIGNAL_CPI", "/workspace/fi-signal/cpi")
OUT = os.path.join(ROOT, "data", "benchmarks.json")
UA = "FISignalWeeklyBot/1.0 (+https://fisignalweekly.com; fisignal@mail.grokbot.com)"
CPI_SERIES = "CUUR0000SA0"
MIN_PEERS = 5  # fewer comparable peers than this: no peer line on the page (said plainly)


def median(xs):
    n = len(xs)
    if not n:
        return None
    m = n // 2
    return xs[m] if n % 2 else (xs[m - 1] + xs[m]) / 2


def r6(v):
    return None if v is None else round(v, 6)


# ---------------------------------------------------------------- sources
def fdic_assets(qs):
    out = []
    for q in qs:
        y, k = int(q[:4]), int(q[5])
        d = f"{y}{['0331', '0630', '0930', '1231'][k - 1]}"
        data = json.load(open(f"{CACHE}/fdic/fin-{d}.json"))
        if data["meta"]["total"] > len(data["data"]):
            raise ValueError(f"FDIC {d}: paged result")
        out.append({int(x["data"]["CERT"]): x["data"]["ASSET"] for x in data["data"] if x["data"].get("ASSET") is not None})
    return out


def ncua_assets(qs):
    out = []
    for q in qs:
        y, k = int(q[:4]), int(q[5])
        z = zipfile.ZipFile(f"{CACHE}/ncua/call-report-data-{y}-{k * 3:02d}.zip")
        name = next(i for i in z.namelist() if i.lower() == "fs220.txt")
        m = {}
        with z.open(name) as f:
            for r in csv.DictReader(io.TextIOWrapper(f, encoding="latin-1")):
                r = {(a or "").upper(): b for a, b in r.items()}
                if (r.get("ACCT_010") or "").strip():
                    m[int(r["CU_NUMBER"])] = int(round(float(r["ACCT_010"]) / 1000))
        out.append(m)
    return out


def cpi_quarters(qs, offline):
    os.makedirs(CPI_CACHE, exist_ok=True)
    y0, y1 = int(qs[0][:4]), int(qs[-1][:4])
    months = {}
    for a in range(y0, y1 + 1, 10):
        b = min(a + 9, y1)
        p = f"{CPI_CACHE}/bls-{CPI_SERIES}-{a}-{b}.json"
        if not os.path.exists(p):
            if offline:
                raise OSError(f"not cached: {p}")
            body = json.dumps({"seriesid": [CPI_SERIES], "startyear": str(a), "endyear": str(b)}).encode()
            req = urllib.request.Request("https://api.bls.gov/publicAPI/v2/timeseries/data/", data=body,
                                         headers={"User-Agent": UA, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                open(p, "wb").write(r.read())
        d = json.load(open(p))
        if d.get("status") != "REQUEST_SUCCEEDED":
            raise ValueError(f"BLS {a}-{b}: {d.get('status')} {d.get('message')}")
        for x in d["Results"]["series"][0]["data"]:
            if x["period"].startswith("M") and x["period"] != "M13":
                try:
                    months[(int(x["year"]), int(x["period"][1:]))] = float(x["value"])
                except ValueError:
                    pass  # "-" = not published
    out, used = [], {}
    for q in qs:
        y, k = int(q[:4]), int(q[5])
        vs = [months[(y, mm)] for mm in range(3 * k - 2, 3 * k + 1) if (y, mm) in months]
        out.append(round(sum(vs) / len(vs), 4) if vs else None)
        used[q] = len(vs)
    return out, {q: n for q, n in used.items() if n != 3}


# ---------------------------------------------------------------- math
def industry(per_q, starts):
    n = len(per_q)
    total = [sum(m.values()) for m in per_q]
    cnt = [len(m) for m in per_q]
    med = {}
    for s in sorted(starts):
        base = {i: v for i, v in per_q[s].items() if v and v > 0}
        row = []
        for t in range(n):
            if t < s:
                row.append(None)
                continue
            rs = sorted(per_q[t][i] / v for i, v in base.items() if i in per_q[t])
            row.append(r6(median(rs)))
        med[s] = row
    return total, cnt, med


class Peers:
    """Peer-tier medians from data/callreports.json, leaving the page's own institution out.

    groups: {key: [fi_id, ...]} (build_directory.py passes (asset tier, charter type) groups of today's institutions).
    series(fi_id, key, s) -> (median ratio list indexed to 1 at quarter s, peers counted at the last quarter) or (None, n).
    """

    def __init__(self, cr, groups):
        self.cr, self.groups, self._sorted = cr, groups, {}

    def _table(self, key, s):
        if (key, s) not in self._sorted:
            cols = None
            for i in self.groups.get(key, []):
                a = self.cr.get(i, {}).get("a") or []
                if len(a) <= s or not a[s] or a[s] <= 0:
                    continue
                if cols is None:
                    cols = [[] for _ in a]
                for t in range(s, len(a)):
                    if a[t] is not None:
                        cols[t].append((a[t] / a[s], i))
            for c in cols or []:
                c.sort()
            self._sorted[(key, s)] = cols or []
        return self._sorted[(key, s)]

    def series(self, fi_id, key, s):
        cols = self._table(key, s)
        if not cols:
            return None, 0
        a = self.cr.get(fi_id, {}).get("a") or []
        out = []
        for t, c in enumerate(cols):
            if t < s:
                out.append(None)
                continue
            mine = (a[t] / a[s], fi_id) if (len(a) > t and a[t] is not None and a[s]) else None
            vals = [r for r, _ in c]
            if mine is not None:
                j = bisect.bisect_left(c, mine)
                if j < len(c) and c[j] == mine:
                    vals = vals[:j] + vals[j + 1:]
            out.append(r6(median(vals)) if len(vals) >= MIN_PEERS else None)
        last = len(cols[-1]) - (1 if a and a[-1] is not None and a[s] else 0)
        return out, last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    crj = json.load(open(os.path.join(ROOT, "data", "callreports.json")))
    qs = crj["quarters"]
    starts = {"bank": set(), "cu": set()}
    for i, x in crj["fi"].items():
        s = next((j for j, v in enumerate(x["a"]) if v is not None), None)
        if s is not None:
            starts["bank" if i.startswith("fdic-") else "cu"].add(s)
    try:
        cpi, partial = cpi_quarters(qs, a.offline)
        out = {"quarters": qs, "as_of": crj["as_of"], "units": "USD thousands",
               "sources": {"bank": "FDIC BankFind Suite API financials (ASSET), every filer each quarter",
                           "cu": "NCUA 5300 Call Report FS220 (ACCT_010 total assets), every filer each quarter",
                           "cpi": f"BLS CPI-U {CPI_SERIES} (U.S. city average, all items, NSA), quarterly average of published months"},
               "cpi": cpi, "cpi_partial_quarters": partial}
        for ct, per_q in (("bank", fdic_assets(qs)), ("cu", ncua_assets(qs))):
            total, cnt, med = industry(per_q, starts[ct])
            out[ct] = {"total": total, "n": cnt, "med": {qs[s]: v for s, v in med.items()}}
    except (OSError, KeyError, ValueError, StopIteration, zipfile.BadZipFile) as ex:
        print("error:", ex, file=sys.stderr)
        return 1
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), sort_keys=True)
        f.write("\n")
    b, c = out["bank"], out["cu"]
    print(f"benchmarks.json: {len(qs)} quarters {qs[0]}..{qs[-1]}; banks {b['n'][0]}->{b['n'][-1]} filers, "
          f"total x{b['total'][-1] / b['total'][0]:.3f}, median x{b['med'][qs[0]][-1]:.3f}; CUs {c['n'][0]}->{c['n'][-1]}, "
          f"total x{c['total'][-1] / c['total'][0]:.3f}, median x{c['med'][qs[0]][-1]:.3f}; "
          f"{len(b['med']) + len(c['med'])} start quarters; CPI partial quarters {partial}; {os.path.getsize(OUT) / 1e3:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
