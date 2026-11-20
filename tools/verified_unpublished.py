#!/usr/bin/env python3
"""List review-passed trigger rows that are not yet on the board.

Usage:
  python3 tools/verified_unpublished.py [--config FILE] [--json] [--quiet]
  python3 tools/verified_unpublished.py --legacy   # original verdict-file scan

Default: reads ledger.tsv through tools/ledger.py (status=verified, not live,
no open conflict), rebuilding it first if it is missing or older than its
sources. --legacy runs the original verdict-file scan below. Paths come from
the same configuration as ledger.py (--config, FISIGNAL_LEDGER_CONFIG or
FISIGNAL_DATA_DIR / FISIGNAL_SITE_DIR); see tools/README.md.

Prints a TSV of id, institution, type, date, verdict file to stdout
(or JSON with --json). --quiet suppresses stdout. Exit code 1 if any
verified-but-unpublished rows exist, 0 if none.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

# Set by configure_legacy() from the ledger configuration.
FI_SIGNAL = Path(".")
EXTRA_VERDICT_GLOBS: tuple[str, ...] = ()
STAGING_FILES = (FI_SIGNAL / "staging.tsv", FI_SIGNAL / "staging-backfill.tsv")
PUBLISH_LOG = FI_SIGNAL / "publish-log.tsv"
LOCAL_TRIGGERS = Path("data/triggers.json")


def configure_legacy(cfg: dict) -> None:
    global FI_SIGNAL, EXTRA_VERDICT_GLOBS, STAGING_FILES, PUBLISH_LOG, LOCAL_TRIGGERS
    FI_SIGNAL = Path(cfg["data_dir"])
    EXTRA_VERDICT_GLOBS = tuple(cfg.get("extra_verdict_globs") or ())
    STAGING_FILES = (FI_SIGNAL / "staging.tsv", FI_SIGNAL / "staging-backfill.tsv")
    PUBLISH_LOG = FI_SIGNAL / "publish-log.tsv"
    LOCAL_TRIGGERS = Path(cfg.get("site_dir") or ".") / "data" / "triggers.json"
LIVE_TRIGGERS_URL = "https://fisignalweekly.com/data/triggers.json"
LIVE_TIMEOUT_SEC = 8

STAGING_TYPE_MAP = {
    ("cuab", "cu_acquires_bank"): "cu_acquires_bank",
    ("cuex", "executive"): "cu_executive",
    ("cumg", "merger"): "cu_merger",
    ("cumg", "acquisition"): "cu_merger",
    ("cucr", "core"): "core",
}
PREFIX_TYPE_MAP = {"db": "digital_banking_change"}

QUOTE_COLUMNS = {"exact quote", "priority", "theme", "fi/parent"}
VERDICT_COLUMNS = ("verdict", "status", "result")
ID_COLUMNS = ("id", "row_id")
TYPE_COLUMNS = ("trigger_type", "type")
DATE_COLUMNS = ("date", "corrected_date")
NOTES_COLUMNS = ("notes", "note")
URL_COLUMNS = ("source_url", "verified_source_url")
FILENAME_DATE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
SNAPSHOT_NAME = re.compile(r"\.pre-|\.pre\.|\.bak$|\.backup\.", re.I)
DROP_STATUS = {"dropped", "live"}
HELD_STATUS = {"held", "hold"}

# Notes must clearly mark a drop. Bare "duplicate" is too common in
# "not a duplicate" / "no duplicate found" review writeups.
DROP_NOTES = re.compile(
    r"\b(?:superseded(?:\s+duplicate)?|dropped\s+from\s+publish|dropped\s+from\s+staging|"
    r"would\s+be\s+a\s+duplicate|duplicate\s+of)\b",
    re.I,
)
NEGATED_DROP = re.compile(
    r"\b(?:not|no|n't|never)\s+(?:a\s+)?(?:superseded|duplicate|dropped)\b",
    re.I,
)


def board_type(row_id: str, trigger_type: str) -> str:
    prefix = (row_id or "").split("-", 1)[0].lower()
    typ = (trigger_type or "").strip().lower()
    if (prefix, typ) in STAGING_TYPE_MAP:
        return STAGING_TYPE_MAP[(prefix, typ)]
    if prefix in PREFIX_TYPE_MAP:
        return PREFIX_TYPE_MAP[prefix]
    return typ or trigger_type or ""


def type_aliases(row_id: str, typ: str) -> set[str]:
    board = board_type(row_id, typ)
    aliases = {a for a in (typ, typ.lower(), board, board.lower()) if a}
    if board in {"cu_executive", "executive"} or typ.lower() in {"cu_executive", "executive"}:
        aliases.update({"executive", "cu_executive"})
    if board in {"cu_merger", "merger"} or typ.lower() in {"cu_merger", "merger"}:
        aliases.update({"merger", "cu_merger"})
    return aliases


def norm_inst(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").replace("\u2019", "'").replace("\u2018", "'")).strip().casefold()


def norm_url(url: str) -> str:
    return (url or "").strip().rstrip("/").casefold()


def first_field(row: dict, names: tuple[str, ...]) -> str:
    lower = {k.lower(): k for k in row}
    for name in names:
        key = lower.get(name.lower())
        if key and (row.get(key) or "").strip():
            return (row[key] or "").strip()
    return ""


def clean_id(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"^\(proposed new\)\s*", "", value, flags=re.I).strip()
    return value


def normalize_verdict(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().casefold()).replace("_", " ")


def is_passed(value: str) -> bool:
    v = normalize_verdict(value)
    if not v:
        return False
    if v.startswith(("reject", "flag", "needs review", "need review", "held", "hold")):
        return False
    if v == "pass" or v.startswith(("pass ", "passed")):
        return True
    if v.startswith("verified"):
        return True
    return False


def is_known_verdict(value: str) -> bool:
    v = normalize_verdict(value)
    if not v:
        return False
    if is_passed(value):
        return True
    return v.startswith(("reject", "flag", "needs review", "need review", "held", "hold"))


def date_from_filename(path: Path) -> date | None:
    matches = FILENAME_DATE.findall(path.name)
    if not matches:
        return None
    try:
        return date.fromisoformat(matches[-1])
    except ValueError:
        return None


def file_sort_key(path: Path) -> tuple:
    mtime = path.stat().st_mtime
    named = date_from_filename(path)
    if named is None:
        named = datetime.fromtimestamp(mtime).date()
    return (named, mtime, str(path))


def is_snapshot(path: Path) -> bool:
    name = path.name
    if SNAPSHOT_NAME.search(name):
        return True
    if name.startswith("staging.") or name.startswith("staging-"):
        return True
    return False


def header_of(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f, delimiter="\t")
        return [c.strip() for c in next(reader, [])]


def is_strategic_quotes(path: Path, header: list[str] | None = None) -> bool:
    cols = {c.strip().casefold() for c in (header if header is not None else header_of(path))}
    if cols & {c.casefold() for c in QUOTE_COLUMNS} and not (cols & {"verdict", "trigger_type"}):
        return True
    return False


def is_verdict_file(path: Path) -> bool:
    try:
        header = header_of(path)
    except OSError:
        return False
    if is_strategic_quotes(path, header):
        return False
    cols = {c.strip().casefold() for c in header}
    if not (cols & {c.casefold() for c in VERDICT_COLUMNS}):
        return False
    try:
        with path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
            for i, row in enumerate(csv.DictReader(f, delimiter="\t")):
                if i > 400:
                    break
                if is_known_verdict(first_field(row, VERDICT_COLUMNS)):
                    return True
    except OSError:
        return False
    return False


def discover_verdict_files() -> list[Path]:
    found: set[Path] = set()
    if FI_SIGNAL.is_dir():
        for path in FI_SIGNAL.rglob("*.tsv"):
            name = path.name.casefold()
            if name.startswith("verify") or "verif" in name:
                found.add(path.resolve())
    for pattern in EXTRA_VERDICT_GLOBS:
        for path in Path(pattern).parent.glob(Path(pattern).name):
            found.add(path.resolve())
    out = []
    for path in found:
        if not path.is_file() or is_snapshot(path):
            continue
        if is_verdict_file(path):
            out.append(path)
    out.sort(key=file_sort_key)
    return out


def read_tsv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        return [{k: (v or "").strip() if isinstance(v, str) else v for k, v in row.items()} for row in csv.DictReader(f, delimiter="\t")]


def load_staging() -> tuple[dict[str, dict], dict[tuple, dict]]:
    by_id: dict[str, dict] = {}
    by_key: dict[tuple, dict] = {}
    for path in STAGING_FILES:
        for row in read_tsv(path):
            row_id = clean_id(row.get("id") or "")
            inst = row.get("institution") or ""
            typ = row.get("trigger_type") or row.get("type") or ""
            day = row.get("date") or ""
            rec = {
                "id": row_id,
                "institution": inst,
                "type": typ,
                "date": day,
                "status": row.get("status") or "",
                "notes": row.get("notes") or row.get("note") or "",
                "source_url": row.get("source_url") or "",
                "staging_file": str(path),
            }
            if row_id:
                by_id[row_id] = rec
            if inst and typ and day:
                by_key[(norm_inst(inst), typ.lower(), day)] = rec
                by_key[(norm_inst(inst), board_type(row_id, typ), day)] = rec
    return by_id, by_key


def verdict_record(row: dict, path: Path, index: int) -> dict | None:
    row_id = clean_id(first_field(row, ID_COLUMNS))
    inst = first_field(row, ("institution",))
    typ = first_field(row, TYPE_COLUMNS)
    day = first_field(row, DATE_COLUMNS)
    if day and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        try:
            day = datetime.fromisoformat(day[:10]).date().isoformat()
        except ValueError:
            pass
    verdict = first_field(row, VERDICT_COLUMNS)
    if not verdict:
        return None
    if not row_id and not (inst and typ and day):
        return None
    return {
        "id": row_id,
        "institution": inst,
        "type": typ,
        "date": day,
        "verdict": verdict,
        "passed": is_passed(verdict),
        "notes": first_field(row, NOTES_COLUMNS),
        "source_url": first_field(row, URL_COLUMNS),
        "path": path,
        "index": index,
        "sort_key": (*file_sort_key(path), index),
    }


def latest_verdicts(files: list[Path]) -> list[dict]:
    groups: dict[str, dict] = {}
    for path in files:
        for index, row in enumerate(read_tsv(path)):
            rec = verdict_record(row, path, index)
            if rec is None:
                continue
            if rec["id"]:
                key = "id:" + rec["id"]
            else:
                key = "k:" + "|".join((norm_inst(rec["institution"]), rec["type"].lower(), rec["date"]))
            prev = groups.get(key)
            if prev is None or rec["sort_key"] >= prev["sort_key"]:
                groups[key] = rec
    return list(groups.values())


def notes_say_dropped(*notes: str) -> bool:
    text = " ".join(n for n in notes if n)
    if not text:
        return False
    stripped = NEGATED_DROP.sub(" ", text)
    return bool(DROP_NOTES.search(stripped))


def is_dropped(staging: dict | None, verdict: dict) -> bool:
    status = normalize_verdict((staging or {}).get("status") or "")
    if status in DROP_STATUS:
        return True
    if status in HELD_STATUS and not verdict["passed"]:
        return True
    # A later Pass/Verified lifts a stale staging Held (e.g. branch openings).
    if notes_say_dropped((staging or {}).get("notes") or "", verdict.get("notes") or ""):
        return True
    return False


def load_triggers_json(raw: str) -> list[dict]:
    data = json.loads(raw)
    if isinstance(data, dict):
        return data.get("rows") or data.get("triggers") or []
    if isinstance(data, list):
        return data
    return []


def load_published_rows() -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()

    def add(batch: list[dict], origin: str) -> None:
        for row in batch:
            key = row.get("id") or json.dumps(row, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            row = dict(row)
            row["_origin"] = origin
            rows.append(row)

    if LOCAL_TRIGGERS.is_file():
        add(load_triggers_json(LOCAL_TRIGGERS.read_text(encoding="utf-8")), "local")
    elif Path("data/triggers.json").is_file():
        add(load_triggers_json(Path("data/triggers.json").read_text(encoding="utf-8")), "local")
    try:
        req = urllib.request.Request(LIVE_TRIGGERS_URL, headers={"User-Agent": "fi-signal-verified-unpublished/1"})
        with urllib.request.urlopen(req, timeout=LIVE_TIMEOUT_SEC) as resp:
            add(load_triggers_json(resp.read().decode("utf-8", "replace")), "live")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        pass
    return rows


def published_indexes(pub_rows: list[dict], log_text: str) -> tuple[set[tuple], set[str], set[str]]:
    keys: set[tuple] = set()
    urls: set[str] = set()
    raw_ids: set[str] = set()
    for row in pub_rows:
        inst = norm_inst(row.get("institution") or "")
        typ = (row.get("type") or "").strip()
        day = (row.get("date") or "").strip()
        if inst and typ and day:
            keys.add((inst, typ, day))
        url = norm_url(row.get("source_url") or "")
        if url:
            urls.add(url)
        for field in ("id", "staging_id", "source_id", "origin_id", "row_id"):
            value = clean_id(str(row.get(field) or ""))
            if value:
                raw_ids.add(value)
        # fi_only branch openings are still published if present on the row.
        if typ == "branch_opening" and inst and day:
            keys.add((inst, typ, day))
    if log_text:
        for match in re.findall(r"\b(?:t\d+|[A-Za-z][A-Za-z0-9-]*-\d{4}-\d{2}-\d{2})\b", log_text):
            raw_ids.add(match)
        # Also catch collector-style ids such as w-dbc-261118-1 or bf-...
        for match in re.findall(r"\b[A-Za-z][\w-]*-\d[\w-]*\b", log_text):
            raw_ids.add(match)
    return keys, urls, raw_ids


def is_published(row: dict, pub_keys: set[tuple], pub_urls: set[str], pub_ids: set[str]) -> bool:
    row_id = row["id"]
    if row_id and row_id in pub_ids:
        return True
    urls = {norm_url(u) for u in row.get("urls") or [row.get("source_url") or ""] if norm_url(u)}
    if urls & pub_urls:
        return True
    insts = [i for i in row.get("institutions") or [row.get("institution") or ""] if i]
    dates = [d for d in row.get("dates") or [row.get("date") or ""] if d]
    types = set()
    for typ in [row.get("type") or ""] + list(row.get("types") or []):
        types.update(type_aliases(row_id, typ))
    for inst in insts:
        ni = norm_inst(inst)
        if not ni:
            continue
        for typ in types:
            for day in dates:
                if (ni, typ, day) in pub_keys:
                    return True
    return False


def attach_staging(verdict: dict, by_id: dict, by_key: dict) -> dict:
    staging = None
    if verdict["id"] and verdict["id"] in by_id:
        staging = by_id[verdict["id"]]
    elif verdict["institution"] and verdict["type"] and verdict["date"]:
        inst = norm_inst(verdict["institution"])
        for typ in type_aliases(verdict["id"], verdict["type"]):
            staging = by_key.get((inst, typ, verdict["date"]))
            if staging:
                break
    if staging:
        inst = staging["institution"] or verdict["institution"]
        typ = staging["type"] or verdict["type"]
        day = staging["date"] or verdict["date"]
        # Prefer a review-corrected date/name when the row later went live that way.
        out_inst = verdict["institution"] or inst
        out_type = board_type(staging["id"] or verdict["id"], typ)
        out_date = verdict["date"] or day
        return {
            "id": staging["id"] or verdict["id"],
            "institution": out_inst or inst,
            "type": out_type,
            "date": out_date or day,
            "source_url": verdict["source_url"] or staging["source_url"],
            "institutions": [i for i in (staging["institution"], verdict["institution"]) if i],
            "types": [t for t in (staging["type"], verdict["type"]) if t],
            "dates": [d for d in (staging["date"], verdict["date"]) if d],
            "urls": [u for u in (staging["source_url"], verdict["source_url"]) if u],
            "staging": staging,
            "verdict": verdict,
        }
    return {
        "id": verdict["id"],
        "institution": verdict["institution"],
        "type": board_type(verdict["id"], verdict["type"]),
        "date": verdict["date"],
        "source_url": verdict["source_url"],
        "institutions": [verdict["institution"]] if verdict["institution"] else [],
        "types": [verdict["type"]] if verdict["type"] else [],
        "dates": [verdict["date"]] if verdict["date"] else [],
        "urls": [verdict["source_url"]] if verdict["source_url"] else [],
        "staging": None,
        "verdict": verdict,
    }


def find_unpublished() -> tuple[list[dict], list[Path]]:
    files = discover_verdict_files()
    by_id, by_key = load_staging()
    pub_rows = load_published_rows()
    log_text = PUBLISH_LOG.read_text(encoding="utf-8", errors="replace") if PUBLISH_LOG.is_file() else ""
    pub_keys, pub_urls, pub_ids = published_indexes(pub_rows, log_text)

    out = []
    for verdict in latest_verdicts(files):
        if not verdict["passed"]:
            continue
        row = attach_staging(verdict, by_id, by_key)
        if not row["id"] or not row["institution"] or not row["type"] or not row["date"]:
            continue
        if is_dropped(row["staging"], verdict):
            continue
        if is_published(row, pub_keys, pub_urls, pub_ids):
            continue
        out.append({
            "id": row["id"],
            "institution": row["institution"],
            "type": row["type"],
            "date": row["date"],
            "verdict file": str(verdict["path"]),
            "verdict": verdict["verdict"],
        })
    out.sort(key=lambda r: (r["date"], r["id"], r["verdict file"]))
    return out, files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List review-passed trigger rows that are not yet on the board."
    )
    parser.add_argument("--config", help="ledger JSON config (default: $FISIGNAL_LEDGER_CONFIG)")
    parser.add_argument("--json", action="store_true", dest="as_json", help="print JSON instead of TSV")
    parser.add_argument("--quiet", action="store_true", help="print nothing; still set the exit code")
    parser.add_argument("--legacy", action="store_true", help="use the original verdict-file scan instead of ledger.tsv")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ledger  # tools/ledger.py

    cfg = ledger.setup(args.config)
    if not args.legacy:
        return ledger.emit_verified_unpublished(args.as_json, args.quiet)
    configure_legacy(cfg)

    rows, files = find_unpublished()
    if not args.quiet:
        if args.as_json:
            payload = [
                {
                    "id": r["id"],
                    "institution": r["institution"],
                    "type": r["type"],
                    "date": r["date"],
                    "verdict_file": r["verdict file"],
                }
                for r in rows
            ]
            json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
        else:
            writer = csv.DictWriter(
                sys.stdout,
                fieldnames=["id", "institution", "type", "date", "verdict file"],
                delimiter="\t",
                lineterminator="\n",
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(rows)
        print(
            f"{len(rows)} verified-unpublished row{'s' if len(rows) != 1 else ''} "
            f"from {len(files)} verdict files",
            file=sys.stderr,
        )
    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main())
