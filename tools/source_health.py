#!/usr/bin/env python3
"""Per-source health for each collection sweep. Run once after every sweep (and every retry).

Appends one row per source to the health file, plus one ALL row for the sweep, then
checks two failure rules and exits 1 if either fires:
  fail_2_in_row       a source failed (status fail or partial) in 2 runs in a row
  weekday_zero_yield  a Mon-Fri sweep (Eastern) matched and queued 0 items across all sources
  yield_not_recorded  a Mon-Fri sweep has no counts at all (pass --results), so zero yield can't be ruled out

Inputs (at least one):
  --results FILE   TSV with a header: source, status, parsed, matched, queued, rejected[, http, detail]
                   status: ok | partial | fail (an HTTP code or CURL_FAIL also works)
  --sweep-dir DIR  a sweep folder with <name>.status files (first word = HTTP code or CURL_FAIL);
                   pages like name-0, name-40 (when name-0 exists) roll up into one source "name". Counts stay blank.
When both are given, --results wins for the sources it lists.

Health file columns (tab-separated, append-only):
  sweep_at sweep_id source status parsed matched queued rejected http detail fail_streak flag

Output path: --out, else config key source_health_path, else <data_dir>/coverage/source-health.tsv
(same config as ledger.py: --config, FISIGNAL_LEDGER_CONFIG or FISIGNAL_DATA_DIR).
Exit codes: 0 healthy, 1 a flag fired, 2 bad input.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

COLUMNS = ["sweep_at", "sweep_id", "source", "status", "parsed", "matched", "queued", "rejected",
           "http", "detail", "fail_streak", "flag"]
COUNTS = ("parsed", "matched", "queued", "rejected")
FAILING = ("fail", "partial")
TZ_NAME = "America/New_York"


def tz():
    from zoneinfo import ZoneInfo
    return ZoneInfo(TZ_NAME)


def parse_at(value: str) -> datetime:
    d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (d if d.tzinfo else d.replace(tzinfo=tz())).astimezone(tz())


def norm_status(raw: str) -> tuple[str, str]:
    """-> (ok|partial|fail, http code or '')."""
    v = (raw or "").strip().split()[0].lower() if (raw or "").strip() else ""
    if v in ("ok", "pass", "passed", "healthy"):
        return "ok", ""
    if v in ("partial", "degraded"):
        return "partial", ""
    if re.fullmatch(r"\d{3}", v):
        return ("ok" if v[0] in "23" else "fail"), v
    return "fail", v if v and v not in ("fail", "failed", "error") else ""


def read_tsv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        return [{(k or "").strip(): (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(f, delimiter="\t")]


def from_sweep_dir(d: Path) -> dict[str, dict]:
    pages: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    files = sorted(d.glob("*.status"))
    names = {p.name[:-len(".status")] for p in files}
    for p in files:
        name = p.name[:-len(".status")]
        base = re.sub(r"-\d+$", "", name)
        src = base if base != name and f"{base}-0" in names else name  # name-0, name-40 ... are pages
        st, code = norm_status(p.read_text(errors="replace"))
        pages[src].append((name, st, code))
    out = {}
    for src, ps in pages.items():
        bad = [p for p in ps if p[1] != "ok"]
        status = "ok" if not bad else ("fail" if len(bad) == len(ps) else "partial")
        codes = sorted({p[2] for p in ps if p[2]})
        out[src] = {"source": src, "status": status, "http": ",".join(codes),
                    "detail": " ".join(f"{n}:{c or 'fail'}" for n, _, c in bad)}
    return out


def from_results(path: Path) -> dict[str, dict]:
    out = {}
    for r in read_tsv(path):
        src = r.get("source", "")
        if not src:
            continue
        st, code = norm_status(r.get("status", ""))
        row = {"source": src, "status": st, "http": r.get("http") or code, "detail": r.get("detail", "")}
        for c in COUNTS:
            v = r.get(c, "")
            if v and not re.fullmatch(r"\d+", v):
                raise SystemExit(f"source_health: {path}: {src}: {c} must be a whole number, got {v!r}")
            row[c] = v
        out[src] = row
    return out


def evaluate(history: list[dict], sweep: list[dict], sweep_at: datetime) -> tuple[list[dict], dict, list[str]]:
    """Fill fail_streak/flag for this sweep's rows, build the ALL row, return (rows, all_row, flags)."""
    prev = defaultdict(list)  # source -> statuses of earlier runs, oldest first
    for r in sorted((h for h in history if h.get("source") != "ALL"), key=lambda h: h.get("sweep_at", "")):
        prev[r["source"]].append(r.get("status", ""))
    flags = []
    for r in sweep:
        streak = 0
        if r["status"] in FAILING:
            streak = 1
            for st in reversed(prev[r["source"]]):
                if st not in FAILING:
                    break
                streak += 1
        r["fail_streak"] = str(streak)
        r["flag"] = "fail_2_in_row" if streak >= 2 else ""
        if r["flag"]:
            flags.append(f"fail_2_in_row {r['source']} ({streak} runs; {r.get('detail') or r['status']})")
    known = [r for r in sweep if any(r.get(c, "") != "" for c in ("matched", "queued"))]
    totals = {c: sum(int(r[c]) for r in sweep if r.get(c, "")) for c in COUNTS}
    weekday = sweep_at.weekday() < 5
    all_flag = ""
    if weekday and not known:
        all_flag = "yield_not_recorded"
        flags.append("yield_not_recorded (weekday sweep with no matched/queued counts)")
    elif weekday and totals["matched"] + totals["queued"] == 0:
        all_flag = "weekday_zero_yield"
        flags.append("weekday_zero_yield (0 matched and 0 queued across all sources)")
    failing = [r for r in sweep if r["status"] in FAILING]
    all_row = {"source": "ALL", "status": "fail" if failing and len(failing) == len(sweep) else (
        "partial" if failing else "ok"),
        **({c: str(totals[c]) for c in COUNTS} if known else {c: "" for c in COUNTS}),
        "http": "", "detail": f"{len(sweep)} sources, {len(failing)} failing", "fail_streak": "",
        "flag": ";".join(x for x in [all_flag] + (["fail_2_in_row"] if any(r["flag"] for r in sweep) else []) if x)}
    return sweep, all_row, flags


def write_rows(out: Path, rows: list[dict]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.is_file():
        with out.open(encoding="utf-8", errors="replace") as f:
            header = f.readline().rstrip("\n").split("\t")
        if header != COLUMNS:  # an older file with another layout: keep it, start fresh
            keep = out.with_name(out.stem + ".pre-" + datetime.now(tz()).strftime("%Y-%m-%d-%H%M%S") + out.suffix)
            os.replace(out, keep)
            print(f"source_health: moved old-format {out.name} to {keep.name}", file=sys.stderr)
    new = not out.is_file()
    with out.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        if new:
            w.writerow(COLUMNS)
        for r in rows:
            w.writerow([str(r.get(c, "") or "").replace("\t", " ").replace("\n", " ") for c in COLUMNS])


def load_cfg(path: str | None) -> dict:
    path = path or os.environ.get("FISIGNAL_LEDGER_CONFIG")
    cfg = json.loads(Path(path).read_text()) if path else {}
    if os.environ.get("FISIGNAL_DATA_DIR"):
        cfg["data_dir"] = os.environ["FISIGNAL_DATA_DIR"]
    return cfg


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Per-source sweep health (run once per sweep)")
    ap.add_argument("--config")
    ap.add_argument("--results", help="per-source results TSV")
    ap.add_argument("--sweep-dir", help="sweep folder with <name>.status files")
    ap.add_argument("--sweep-id", help="label for this run (default: <date>T<HHMM> Eastern)")
    ap.add_argument("--at", help="sweep time, ISO (default: now)")
    ap.add_argument("--out", help="health TSV path")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)
    if not args.results and not args.sweep_dir:
        print("source_health: pass --results FILE and/or --sweep-dir DIR", file=sys.stderr)
        return 2
    cfg = load_cfg(args.config)
    out = Path(args.out or cfg.get("source_health_path") or
               (Path(cfg["data_dir"]) / "coverage" / "source-health.tsv" if cfg.get("data_dir") else ""))
    if not str(out):
        print("source_health: no output path (use --out or a config with data_dir)", file=sys.stderr)
        return 2
    try:
        at = parse_at(args.at) if args.at else datetime.now(tz())
    except ValueError:
        print(f"source_health: bad --at {args.at!r}", file=sys.stderr)
        return 2
    by_src: dict[str, dict] = {}
    if args.sweep_dir:
        d = Path(args.sweep_dir)
        if not d.is_dir():
            print(f"source_health: no such sweep dir {d}", file=sys.stderr)
            return 2
        by_src.update(from_sweep_dir(d))
    if args.results:
        p = Path(args.results)
        if not p.is_file():
            print(f"source_health: no such results file {p}", file=sys.stderr)
            return 2
        for src, row in from_results(p).items():
            by_src[src] = {**by_src.get(src, {}), **row}
    if not by_src:
        print("source_health: no sources found in the inputs", file=sys.stderr)
        return 2
    sweep_at = at.isoformat(timespec="seconds")
    sweep_id = args.sweep_id or at.strftime("%Y-%m-%dT%H%M")
    sweep = [{**{c: "" for c in COUNTS}, **r, "sweep_at": sweep_at, "sweep_id": sweep_id} for _, r in sorted(by_src.items())]
    history = read_tsv(out) if out.is_file() and read_tsv(out) and "sweep_id" in read_tsv(out)[0] else []
    rows, all_row, flags = evaluate(history, sweep, at)
    all_row.update({"sweep_at": sweep_at, "sweep_id": sweep_id})
    write_rows(out, rows + [all_row])
    if args.as_json:
        json.dump({"sweep_id": sweep_id, "sweep_at": sweep_at, "healthy": not flags, "flags": flags,
                   "sources": len(rows), "failing": [r["source"] for r in rows if r["status"] in FAILING]},
                  sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        failing = [f"{r['source']}:{r['status']}" for r in rows if r["status"] in FAILING]
        print(f"source_health {sweep_id}: {len(rows)} sources, {len(failing)} failing"
              + (f" ({' '.join(failing)})" if failing else ""))
        for f in flags:
            print(f"FLAG {f}")
        print("healthy" if not flags else f"flags={len(flags)}")
    return 1 if flags else 0


if __name__ == "__main__":
    sys.exit(main())
