#!/usr/bin/env python3
"""Refresh the digital banking "Login page scan" rows in data/providers.csv from the website watcher.

    python3 scripts/import_watcher_providers.py [--db /workspace/fi-signal/site-watcher/data/watcher.db]

The watcher (outside this repo) records each FI's online-banking login host(s) and their DNS CNAME chain
and maps them to a vendor with hostname fingerprints only (see its README). This script takes, for every FI,
the latest completed run whose homepage loaded (HTTP 200) and, if that scan matched a vendor, writes one row:

    field=digital, status=current, source_type=Login page scan, source_url=<homepage scanned>,
    last_updated=<date of that scan>, note=<the hostname evidence>

If the latest good scan found no vendor, the FI gets no scan row (the page shows "Not yet identified").
When two vendors tie (for example a retail and a business login on different platforms) both are listed;
nothing is picked between them. Every other row in providers.csv (announcements, hand-checked rows) is kept as is.
Output is sorted, so re-running on the same data gives an identical file.
"""
import argparse, collections, csv, json, os, sqlite3, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(ROOT, "data", "providers.csv")
COLS = ["fi_id", "field", "value", "status", "source_type", "source_url", "last_updated", "note"]
SCAN = "Login page scan"
DEFAULT_DB = "/workspace/fi-signal/site-watcher/data/watcher.db"


def evidence_text(ev):
    if ev["via"] == "login_host":
        return f'login link goes to {ev["match"]}'
    if ev["via"] == "login_cname":
        return f'login host {ev["host"]} points (DNS) to {ev["match"]}'
    if ev["via"] == "login_redirect":
        return f'login host {ev["host"]} redirects to {ev["match"]}'
    return f'login page at {ev["host"]} names the vendor'


def scan_rows(db):
    c = sqlite3.connect(db)
    runs = [r[0] for r in c.execute("SELECT run_id FROM runs WHERE finished IS NOT NULL ORDER BY started")]
    latest = {}
    for run in runs:  # later runs overwrite earlier ones
        for fi, fetched, status, data in c.execute(
                "SELECT fi_id, fetched_at, http_status, data FROM snapshots WHERE run_id=?", (run,)):
            if status == 200:
                latest[fi] = (fetched, json.loads(data))
    out = []
    for fi, (fetched, d) in latest.items():
        ev = d.get("provider_evidence") or []
        if not ev:
            continue
        tally = collections.Counter()
        for x in ev:
            tally[x["vendor"]] += 1 + x.get("weight", 0)
        top = max(tally.values())
        tied = sorted(v for v, n in tally.items() if n == top)
        # a bare "Jack Henry" host (e.g. treasury) tied with a named Jack Henry product adds nothing
        if "Jack Henry" in tied and any(v.startswith("Jack Henry (") for v in tied):
            tied.remove("Jack Henry")
        others = sorted(v for v in tally if v not in tied and not (v == "Jack Henry" and any(t.startswith("Jack Henry") for t in tied)))
        proof = []
        for v in tied:
            x = next(x for x in ev if x["vendor"] == v)
            proof.append(evidence_text(x))
        note = "; ".join(proof)
        if len(tied) > 1:
            note = "More than one login platform is linked from the homepage. " + note
        if others:
            note += "; also linked: " + ", ".join(others)
        out.append({"fi_id": fi, "field": "digital", "value": " + ".join(tied), "status": "current",
                    "source_type": SCAN, "source_url": d.get("final_url") or d.get("url_fetched") or "",
                    "last_updated": (fetched or "")[:10], "note": note})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    a = ap.parse_args()
    if not os.path.exists(a.db):
        sys.exit(f"watcher db not found: {a.db}")
    keep = []
    if os.path.exists(CSV):
        with open(CSV, newline="", encoding="utf-8") as f:
            keep = [r for r in csv.DictReader(f) if r["source_type"] != SCAN]
    rows = keep + scan_rows(a.db)
    rows.sort(key=lambda r: (r["fi_id"].split("-")[0], int(r["fi_id"].split("-")[1]), r["field"], r["status"], r["last_updated"], r["value"]))
    with open(CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, COLS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    n = collections.Counter((r["field"], r["source_type"]) for r in rows)
    print(f"providers.csv: {len(rows)} rows; " + ", ".join(f"{k[0]}/{k[1]}: {v}" for k, v in sorted(n.items())))


if __name__ == "__main__":
    main()
