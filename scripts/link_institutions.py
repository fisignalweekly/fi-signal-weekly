#!/usr/bin/env python3
"""Link each board row in data/triggers.json to its institution record in data/institutions.json.

    python3 scripts/link_institutions.py           # update data/triggers.json in place (re-runnable)
    python3 scripts/link_institutions.py --report  # also print every row's match and the unmatched list
    python3 scripts/link_institutions.py --check   # exit 3 if triggers.json would change (no write)

Main institution of a row = the FIRST FI named in `institution` (text before " / "). In merger rows that is
the acquirer / continuing FI when the row is written "Acquirer / Target", and the merging CU when only one is
named. Inside that segment, a parenthetical "(…)" names the bank behind a holding company (or vice versa), and
both are tried.

Match order (first hit wins):
  1. data/institution_overrides.csv (trigger_id -> fi_id, or fi_id "none" to force no match)
  2. an FDIC CERT / NCUA charter number recorded in the row's assets_note, if that record's name fits the
     main institution
  3. normalized exact name (or NCUA trade name, or FDIC holding-company name) in the row's state;
     the same name outside the row's state only if it is unique nationwide

Fields written on each row (and removed again if a row stops matching):
  fi_id, fi_name, charter_type (bank|cu), fi_assets_usd, fi_assets_as_of, fi_assets_date, fi_match
Rows with no match keep their existing assets_millions; the site then falls back to that figure and to the
name-based bank/CU guess. Nothing else in a row is touched, and rows are never added or removed.
Exit codes: 0 ok, 1 missing/invalid input, 3 (--check only) triggers.json is out of date.
"""
import argparse, csv, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRIG = os.path.join(ROOT, "data", "triggers.json")
INST = os.path.join(ROOT, "data", "institutions.json")
OVR = os.path.join(ROOT, "data", "institution_overrides.csv")
FIELDS = ["fi_id", "fi_name", "charter_type", "fi_assets_usd", "fi_assets_as_of", "fi_assets_date", "fi_match"]

CORP = r"\b(inc|incorporated|corp|corporation|co|company|companies|the|n\s?a|national association|ssb|fsb|mhc|ltd|llc|plc)\b"


# FDIC abbreviates holding-company names (e.g. "FIRST FINANCIAL BCORP", "PNC FINL SERVICES GROUP INC")
ABBR = {"bcorp": "bancorp", "bancorporation": "bancorp", "finl": "financial", "natl": "national", "svgs": "savings",
        "svg": "savings", "bkg": "banking", "bk": "bank", "coml": "commercial", "cmnty": "community", "hldgs": "holdings",
        "grp": "group", "corp": "corp", "mhc": "mhc"}


def norm(s):
    s = (s or "").lower().replace("&", " and ").replace("'s", "s").replace("’s", "s")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = " ".join(ABBR.get(w, w) for w in s.split())
    s = re.sub(CORP, " ", s)
    return " ".join(s.split())


def cu_norm(s):
    """NCUA's FOICU names drop 'Credit Union' / 'Federal Credit Union'; strip them from both sides."""
    s = norm(s)
    s = re.sub(r"\b(federal credit union|credit union|fcu|cu)\b", " ", s)
    return " ".join(s.split())


def segment_names(seg):
    names = [seg]
    m = re.match(r"^(.*?)\s*\((.*)\)\s*$", seg)
    if m:
        names = [m.group(1).strip()] + [p.strip() for p in re.split(r"\s*/\s*|;\s*", m.group(2)) if p.strip()]
    return [n for n in names if n]


def segments(institution):
    """FIs named in the row, in order. " / " separates FIs, except inside parentheses."""
    out, depth, cur = [], 0, ""
    i = 0
    while i < len(institution):
        ch = institution[i]
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0 and institution.startswith(" / ", i):
            out.append(cur.strip()); cur = ""; i += 3; continue
        cur += ch; i += 1
    out.append(cur.strip())
    return [segment_names(x) for x in out if x]


def load():
    try:
        d = json.load(open(INST))
        cols = d["columns"]
        inst = {r[0]: dict(zip(cols, r)) for r in d["rows"]}
        trig = json.load(open(TRIG))
    except (OSError, ValueError, KeyError) as e:
        sys.exit(f"ERROR: {e}") or 1
    ovr = {}
    if os.path.exists(OVR):
        for r in csv.DictReader(open(OVR, newline="")):
            if r.get("trigger_id", "").strip() and not r["trigger_id"].startswith("#"):
                ovr[r["trigger_id"].strip()] = r["fi_id"].strip()
    return inst, trig, ovr


def build_index(inst):
    idx = {}
    def add(key, rec):
        if key and key[1]:
            idx.setdefault(key, set()).add(rec["id"])
            idx.setdefault((key[0], key[1].replace(" ", "")), set()).add(rec["id"])  # "NorthCountry" = "North Country"
    for rec in inst.values():
        if rec["charter_type"] == "cu":
            add(("cu", cu_norm(rec["name"])), rec)
            for a in (rec.get("also_known_as") or "").split("|"):
                add(("cu", cu_norm(a)), rec)
        else:
            add(("bank", norm(rec["name"])), rec)
            if rec.get("holding_company"):
                add(("hc", norm(rec["holding_company"])), rec)
    return idx


def looks_cu(name):
    return bool(re.search(r"credit union|\b[A-Z]*CU\b", name))


def fits(rec, names):
    f = cu_norm if rec["charter_type"] == "cu" else norm
    keys = {f(rec["name"])} | {f(a) for a in (rec.get("also_known_as") or "").split("|") if a}
    if rec.get("holding_company"):
        keys.add(norm(rec["holding_company"]))
    for n in names:
        k = f(n)
        if k and any(k == x or (len(k) >= 4 and (re.search(rf"\b{re.escape(k)}\b", x) or re.search(rf"\b{re.escape(x)}\b", k)))
                     for x in keys if x):
            return True
    return False


def name_match(row, names, inst, idx):
    for n in names:
        kinds = ["cu", "bank", "hc"] if looks_cu(n) else ["bank", "hc", "cu"]
        for k in kinds:
            key = cu_norm(n) if k == "cu" else norm(n)
            if not key:
                continue
            ids = idx.get((k, key), set()) or idx.get((k, key.replace(" ", "")), set())
            if not ids:
                continue
            in_state = [i for i in ids if inst[i]["state"] == row["state"]]
            if k == "hc":  # holding company -> its largest bank in the row's state (the lead bank)
                if in_state:
                    return inst[max(in_state, key=lambda i: inst[i]["total_assets"] or 0)], "holding_company"
                hcs = {norm(inst[i]["holding_company"]) for i in ids}
                if len(hcs) == 1:  # one holding company nationwide -> its largest bank
                    return inst[max(ids, key=lambda i: inst[i]["total_assets"] or 0)], "holding_company_out_of_state"
            elif len(in_state) == 1:
                return inst[in_state[0]], "name_state"
            elif not in_state and len(ids) == 1:
                return inst[next(iter(ids))], "name_unique_out_of_state"
    return None, None


def match(row, inst, idx, ovr):
    rid = row["id"]
    if rid in ovr:
        fid = ovr[rid]
        if fid.lower() == "none":
            return None, "override:none"
        if fid not in inst:
            print(f"warning: override {rid} -> {fid} not in institutions.json (ignored)", file=sys.stderr)
        else:
            return inst[fid], "override"
    segs = segments(row["institution"])
    note = row.get("assets_note") or ""
    hints = [f"fdic-{n}" for n in re.findall(r"CERT\s*#?\s*(\d+)", note)]
    hints += [f"ncua-{n}" for n in re.findall(r"(?:charter|NCUA[^;,)]*?#)\s*(\d+)", note, flags=re.I)]
    hints = [h for h in hints if h in inst]
    # a single-FI row whose note cites exactly one record: that record is the FI (covers renames like TDECU)
    if len(segs) == 1 and len(set(hints)) == 1:
        return inst[hints[0]], "id_in_note"
    for h in hints:
        if fits(inst[h], segs[0]):
            return inst[h], "id_in_note"
    # first named FI with a record; later segments only when an earlier one has none (non-bank acquirers such as
    # investor groups or fintechs, or a merged-away FI)
    for si, names in enumerate(segs):
        rec, how = name_match(row, names, inst, idx)
        if rec:
            return rec, how + ("" if si == 0 else f"_segment{si + 1}")
    return None, "unmatched"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    inst, trig, ovr = load()
    idx = build_index(inst)
    before = json.dumps(trig, ensure_ascii=False, indent=2)
    stats, unmatched = {}, []
    for row in trig["rows"]:
        rec, how = match(row, inst, idx, ovr)
        for f in FIELDS:
            row.pop(f, None)
        stats[how] = stats.get(how, 0) + 1
        if rec:
            row.update({"fi_id": rec["id"], "fi_name": rec["name"], "charter_type": rec["charter_type"],
                        "fi_assets_usd": rec["total_assets"] if rec["total_assets"] != "" else None,
                        "fi_assets_as_of": rec["assets_as_of"] or None, "fi_assets_date": rec["assets_report_date"] or None,
                        "fi_match": how})
        else:
            unmatched.append(row)
        if a.report:
            print(f"{row['id']}\t{how}\t{row['institution']}\t-> {rec['id'] + ' ' + rec['name'] + ' (' + rec['state'] + ')' if rec else '-'}")
    after = json.dumps(trig, ensure_ascii=False, indent=2)
    if a.check:
        print("up to date" if before == after else "triggers.json needs relinking")
        return 0 if before == after else 3
    if before != after:
        # keep the file's existing formatting (indent=2, UTF-8, trailing newline, same as stamp_added.py)
        raw = open(TRIG, encoding="utf-8").read()
        nl = "\n" if raw.endswith("\n") else ""
        open(TRIG + ".tmp", "w", encoding="utf-8").write(after + nl)
        os.replace(TRIG + ".tmp", TRIG)
    print(f"linked {len(trig['rows']) - len(unmatched)} of {len(trig['rows'])} rows; " +
          ", ".join(f"{k} {v}" for k, v in sorted(stats.items())) + ("; wrote data/triggers.json" if before != after else "; no change"))
    if unmatched:
        print("unmatched (fallback: row's own assets_millions + name-based bank/CU guess):")
        for r in unmatched:
            print(f"  {r['id']}  {r['institution']} ({r['state']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
