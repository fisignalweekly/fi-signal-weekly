#!/usr/bin/env python3
"""Build the sanitized, published-only data bundle the MCP Worker serves.

    python3 mcp/scripts/build_bundle.py                    # read repo files from the working tree
    python3 mcp/scripts/build_bundle.py --ref origin/main  # read them from a git ref (what is live)

Writes mcp/src/generated/bundle.json (git-ignored; rebuilt before every deploy).

Published-only is enforced here, by allowlist:
  * Only the files listed in INPUTS are read: published files in the public site repo, nothing else.
  * Every output record is built field by field from an explicit allowlist. Unknown or new input
    fields never pass through.
  * Signal rows that are not on the public board are dropped: fi_only rows, FI-only types
    (branch openings), unknown types, and any row carrying a non-public marker (draft, hidden, ...).
"""
import argparse, csv, datetime, io, json, os, re, subprocess, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "mcp", "src", "generated", "bundle.json")
SITE = "https://fisignalweekly.com"
INPUTS = ["data/triggers.json", "data/institutions.json", "data/providers.csv", "data/contract_windows.csv",
          "data/callreports.json", "data/benchmarks.json", "scripts/trigger_types.py"]

# Board types in priority order: M&A first, then executive moves, then the rest.
TYPE_ORDER = ["merger", "cu_merger", "cu_acquires_bank", "executive", "cu_executive",
              "core", "cu_charter", "digital_banking_change"]
TYPE_GROUP = {"merger": "m_and_a", "cu_merger": "m_and_a", "cu_acquires_bank": "m_and_a",
              "executive": "executive", "cu_executive": "executive"}
# Any of these keys set to a truthy value keeps a row out (defensive: none exist today).
NON_PUBLIC_MARKERS = ("fi_only", "draft", "hidden", "internal", "private", "unpublished", "unverified",
                      "embargo", "embargoed", "staging", "pending_review")
PROVIDER_FIELDS = ["digital", "digital_business", "core", "billpay"]
PROVIDER_STATUS = {"current", "announced"}
TREND_QUARTERS = 9  # latest quarter plus the eight before it (two years)


def reader(ref):
    def read(path):
        if path not in INPUTS:
            raise ValueError(f"{path} is not an allowlisted input")
        if ref:
            return subprocess.run(["git", "-C", ROOT, "show", f"{ref}:{path}"], check=True,
                                  capture_output=True).stdout.decode("utf-8")
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            return f.read()
    return read


def load_types(src):
    """TYPES and FI_ONLY_TYPES from scripts/trigger_types.py, executed in isolation."""
    ns = {"__name__": "trigger_types"}
    exec(compile(src, "trigger_types.py", "exec"), ns)
    return ns["TYPES"], set(ns["FI_ONLY_TYPES"])


def slugify(s):  # mirrors scripts/build_directory.py
    s = s.lower().replace("&", " and ").replace("'", "").replace("\u2019", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "fi"


def page_paths(inst):
    """fi_id -> /fi/<st>/<slug>/ exactly as scripts/build_directory.py assigns them."""
    inst = sorted(inst, key=lambda x: (x["charter_type"], int(x["id"].split("-")[1])))
    groups = {}
    for x in inst:
        base = slugify(x["name"])
        if x["charter_type"] == "cu" and not re.search(r"(^|-)(cu|fcu|credit-union|federal-credit-union)$", base):
            base += "-cu"
        groups.setdefault((x["state"].lower(), base), []).append(x)
    used = {k for k, xs in groups.items() if len(xs) == 1}
    out = {}
    for (st, base), xs in sorted(groups.items()):
        cities = {}
        for x in xs:
            cities[slugify(x["city"])] = cities.get(slugify(x["city"]), 0) + 1
        for x in xs:
            if len(xs) == 1:
                s = base
            else:
                s = f"{base}-{slugify(x['city'])}"
                if cities[slugify(x["city"])] > 1 or (st, s) in used:
                    s = f"{s}-{x['id'].split('-')[1]}"
                used.add((st, s))
            out[x["id"]] = f"/fi/{st}/{s}/"
    return out


def is_public_signal(r, types, fi_only_types):
    if r.get("type") not in types or r.get("type") in fi_only_types:
        return False
    if any(r.get(k) not in (None, False, "", 0, "false") for k in NON_PUBLIC_MARKERS):
        return False
    for k in ("id", "type", "institution", "state", "date", "summary", "source_url"):
        if not r.get(k):
            return False
    return str(r["source_url"]).startswith("http")


def build(read):
    types, fi_only_types = load_types(read("scripts/trigger_types.py"))
    trig = json.loads(read("data/triggers.json"))
    db = json.loads(read("data/institutions.json"))
    cr = json.loads(read("data/callreports.json"))
    bm = json.loads(read("data/benchmarks.json"))

    cols = db["columns"]
    inst = [dict(zip(cols, r)) for r in db["rows"]]
    paths = page_paths(inst)

    # ---- types (priority order; FI-only types never listed)
    order = [t for t in TYPE_ORDER if t in types] + sorted(t for t in types if t not in TYPE_ORDER)
    type_list = [{"type": t, "label": types[t], "group": TYPE_GROUP.get(t, "other"), "priority": i + 1}
                 for i, t in enumerate(t for t in order if t not in fi_only_types)]

    # ---- signals
    signals = []
    for r in trig["rows"]:
        if not is_public_signal(r, types, fi_only_types):
            continue
        fid = r.get("fi_id") if r.get("fi_id") in paths else None
        if r.get("fi_assets_usd") is not None:
            assets, basis, as_of = r["fi_assets_usd"], "call_report", r.get("fi_assets_as_of")
        elif r.get("assets_millions") is not None:
            assets, basis, as_of = int(round(float(r["assets_millions"]) * 1e6)), "reported_approx", None
        else:
            assets, basis, as_of = None, None, None
        added = r.get("added") or r["date"]
        signals.append({
            "id": r["id"], "type": r["type"], "type_label": types[r["type"]],
            "type_group": TYPE_GROUP.get(r["type"], "other"),
            "institution": r["institution"], "state": r["state"],
            "event_date": r["date"], "added": added, "backfill": r.get("backfill") is True,
            "summary": r["summary"], "source_url": r["source_url"],
            "fi_id": fid, "fi_name": r.get("fi_name") if fid else None,
            "charter_type": r.get("charter_type") if fid else None,
            "assets_usd": assets, "assets_basis": basis, "assets_as_of": as_of,
            "fi_page_url": SITE + paths[fid] if fid else None,
            "board_url": f"{SITE}/#{r['id']}",
        })
    signals.sort(key=lambda s: (s["added"], s["id"]))

    # ---- institutions (compact rows)
    inst_cols = ["fi_id", "name", "charter_type", "charter_class", "city", "state", "website",
                 "total_assets_usd", "assets_as_of", "holding_company", "also_known_as", "path"]
    inst_rows = []
    for x in sorted(inst, key=lambda x: x["id"]):
        ta = x.get("total_assets")
        inst_rows.append([x["id"], x["name"], x["charter_type"], x.get("charter_class") or None, x.get("city") or None,
                          x["state"], x.get("website") or None, ta if isinstance(ta, (int, float)) else None,
                          x.get("assets_as_of") or None, x.get("holding_company") or None,
                          x.get("also_known_as") or None, paths[x["id"]]])

    # ---- financials (USD thousands in source -> USD)
    qs = cr["quarters"]
    tq = qs[-TREND_QUARTERS:]
    def last(v):
        return v[-1] * 1000 if v and v[-1] is not None else None
    fin = {}
    for fid, v in cr["fi"].items():
        if fid not in paths:
            continue
        a = v.get("a") or []
        rec = {"assets_usd": [None if n is None else n * 1000 for n in a[-TREND_QUARTERS:]],
               "deposits_usd": last(v.get("d")), "loans_usd": last(v.get("l")),
               "established": v.get("est") or None}
        if v.get("m"):
            rec["members"] = v["m"][-1]
        if v.get("off") is not None:
            rec["offices"] = v["off"]
        if v.get("sites"):
            rec["sites"] = {str(k): int(n) for k, n in v["sites"].items()}
        hist = []
        for e in v.get("hist") or []:
            hist.append({k: e[k] for k in ("date", "desc", "other", "name", "from_name") if e.get(k)})
        if hist:
            rec["history"] = hist
        fin[fid] = rec

    # ---- industry benchmarks: median and aggregate growth by charter type
    bench = {}
    for ct in ("bank", "cu"):
        b = bm[ct]
        def med(n):
            row = b["med"].get(qs[-1 - n])
            return None if not row or row[-1] is None else round(row[-1] - 1, 6)
        def tot(n):
            t = b["total"]
            return round(t[-1] / t[-1 - n] - 1, 6) if t[-1 - n] else None
        bench[ct] = {"filers": b["n"][-1], "median_growth_1y": med(4), "median_growth_5y": med(20),
                     "industry_growth_1y": tot(4), "industry_growth_5y": tot(20)}

    # ---- tech stack evidence
    prov = {}
    for r in csv.DictReader(io.StringIO(read("data/providers.csv"))):
        if r["fi_id"] not in paths or r["field"] not in PROVIDER_FIELDS or r["status"] not in PROVIDER_STATUS:
            continue
        if not r["value"].strip() or not r["source_type"].strip():
            continue
        prov.setdefault(r["fi_id"], {}).setdefault(r["field"], []).append({
            "value": r["value"], "status": r["status"], "source_type": r["source_type"],
            "source_url": r["source_url"] or None, "last_updated": r["last_updated"] or None,
            "note": r["note"].strip() or None})
    windows = {}
    for r in csv.DictReader(io.StringIO(read("data/contract_windows.csv"))):
        if r.get("public_display") == "true" and r.get("approved") and r["fi_id"] in paths and r["field"] in PROVIDER_FIELDS:
            windows.setdefault(r["fi_id"], {})[r["field"]] = {"text": r["text"], "source_url": r["source_url"] or None}

    return {
        "meta": {"site": SITE, "data_updated": trig.get("updated"), "assets_as_of": cr.get("as_of"),
                 "trend_quarters": tq, "built_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "sources": "FDIC BankFind and NCUA call reports; signals from public sources cited per row"},
        "types": type_list,
        "signals": signals,
        "institutions": {"cols": inst_cols, "rows": inst_rows},
        "financials": fin,
        "benchmarks": bench,
        "providers": prov,
        "renewal_windows": windows,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", help="git ref to read data from (e.g. origin/main); default: working tree")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    bundle = build(reader(a.ref))
    if a.ref:
        bundle["meta"]["source_commit"] = subprocess.run(["git", "-C", ROOT, "rev-parse", a.ref], check=True,
                                                         capture_output=True, text=True).stdout.strip()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(bundle, f, separators=(",", ":"), ensure_ascii=False)
    print(f"bundle: {len(bundle['signals'])} signals, {len(bundle['institutions']['rows'])} institutions, "
          f"{len(bundle['providers'])} with tech stack, {os.path.getsize(a.out)/1e6:.2f} MB -> {os.path.relpath(a.out, ROOT)}")


if __name__ == "__main__":
    main()
