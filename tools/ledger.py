#!/usr/bin/env python3
"""Row ledger: one line per row id with its current pipeline status.

Reads (never edits) the working staging files, review verdict files and
data/triggers.json on origin/main of a site checkout (read with `git show`,
no checkout or fetch). Explicit writes (found items, status decisions,
publish times, corrections) go to an append-only event log that every
rebuild merges back in, so they survive rebuilds.

Statuses: found -> staged -> verified | needs_review | rejected -> live -> corrected
("flagged" is accepted as an input alias of needs_review and is read as
needs_review from older ledger files.)

Subcommands:
  build                    full idempotent rebuild of ledger.tsv (also the default with no subcommand)
  snapshot <file>          copy <file> into snapshots/ (keep last 10), then build
  verified-unpublished     rows with status=verified that are not live
  status                   row counts by status and conflict count
  add <row_id> found|staged  record a found or staged item (append-only, deduped by row id)
  set <row_id> <status>    record a decision: staged | verified | needs_review | rejected | corrected
  published <row_id>...    record published_at (and optional PR) for rows that went live
  stale                    fresh items still found/staged after more than 1 business day (exit 1 if any)

Configuration (no paths are hard-coded): --config FILE, or env
FISIGNAL_LEDGER_CONFIG, a JSON file with keys data_dir (required), site_dir,
extra_verdict_globs, meta_globs, fresh_window_days,
source_health_path. FISIGNAL_DATA_DIR / FISIGNAL_SITE_DIR work without a file.
See tools/README.md.

Status precedence: live (row is in triggers.json on origin/main) >
verdict files (verified / needs_review / rejected, newest file day wins) >
staging (staged). Disagreements are written to ledger-conflicts.tsv and the
row's source column says "conflict"; they are never silently resolved.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

# Paths are set by configure(); see load_config().
FI = Path(".")
SITE = Path(".")
TRIGGERS_REF = "origin/main:data/triggers.json"
EXTRA_VERDICT_GLOBS: tuple[str, ...] = ()
FRESH_WINDOW_DAYS = 14
TZ_NAME = "America/New_York"

LEDGER = FI / "ledger.tsv"
HISTORY = FI / "ledger-history.tsv"
CONFLICTS = FI / "ledger-conflicts.tsv"
META = FI / "ledger-meta.json"
LOCK = FI / ".ledger.lock"
SNAPSHOTS = FI / "snapshots"
KEEP_SNAPSHOTS = 10

STAGING_FILES = (FI / "staging.tsv", FI / "staging-backfill.tsv")
PUBLISH_LOG = FI / "publish-log.tsv"
# Metadata-only lookups (institution/type/date/url for ids that have a
# verdict but no staging row). They never set status. Set from config.
META_GLOBS: tuple[str, ...] = ()

COLUMNS = ["row_id", "status", "verdict_file", "pr", "date", "source", "note", "found_at", "published_at", "lane"]
BACKFILL_STAGING = Path("staging-backfill.tsv")
CONFLICT_KINDS = ("verdict_files_disagree", "live_but_rejected", "live_but_flagged", "ambiguous_live_match",
                  "staging_says_live_not_in_triggers", "duplicate_id_different_content", "duplicate_live_id")
# Review resolution files (see ledger-README.md "Resolutions"). Never verdict files.
RESOLUTION_GLOB = "verify-ledger-conflicts-*.tsv"
RESOLUTIONS_EXTRA = FI / "ledger-resolutions.tsv"
RES_WARNINGS = FI / "ledger-resolution-warnings.tsv"
STATUSES = ("found", "staged", "verified", "needs_review", "rejected", "live", "corrected")
STATUS_ALIASES = {"flagged": "needs_review", "needs-review": "needs_review", "needs review": "needs_review"}
DECISIONS = ("verified", "needs_review", "rejected")
SETTABLE = ("staged", *DECISIONS, "corrected")
LANES = ("fresh", "backlog", "backfill")
EVENTS = FI / "ledger-events.tsv"
EVENT_COLUMNS = ["event_at", "row_id", "action", "status", "lane", "found_at", "published_at", "pr",
                 "institution", "type", "date", "source_url", "note"]


def canon_status(value: str) -> str:
    """Canonical status name; 'flagged' (old name) reads as needs_review."""
    v = (value or "").strip().lower()
    return STATUS_ALIASES.get(v, v)

# ---- helpers shared with verified_unpublished.py legacy logic ------------

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
DROP_NOTES = re.compile(
    r"\b(?:superseded(?:\s+duplicate)?|dropped\s+from\s+publish|dropped\s+from\s+staging|"
    r"would\s+be\s+a\s+duplicate|duplicate\s+of)\b",
    re.I,
)
NEGATED_DROP = re.compile(r"\b(?:not|no|n't|never)\s+(?:a\s+)?(?:superseded|duplicate|dropped)\b", re.I)


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
    if {board, typ.lower()} & {"cu_executive", "executive"}:
        aliases.update({"executive", "cu_executive"})
    if {board, typ.lower()} & {"cu_merger", "merger"}:
        aliases.update({"merger", "cu_merger"})
    return aliases


def norm_inst(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").replace("\u2019", "'").replace("\u2018", "'")).strip().casefold()


def norm_url(url: str) -> str:
    return (url or "").strip().rstrip("/").casefold()


def first_field(row: dict, names: tuple[str, ...]) -> str:
    lower = {(k or "").lower(): k for k in row}
    for name in names:
        key = lower.get(name.lower())
        if key and (row.get(key) or "").strip():
            return (row[key] or "").strip()
    return ""


def clean_id(value: str) -> str:
    return re.sub(r"^\(proposed new\)\s*", "", (value or "").strip(), flags=re.I).strip()


def normalize_verdict(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().casefold()).replace("_", " ")


def is_passed(value: str) -> bool:
    v = normalize_verdict(value)
    if not v or v.startswith(("reject", "flag", "needs review", "need review", "held", "hold")):
        return False
    return v == "pass" or v.startswith(("pass ", "passed", "verified"))


def verdict_status(value: str) -> str | None:
    """Map a raw verdict string to verified / flagged / rejected (None = unknown)."""
    v = normalize_verdict(value)
    if not v:
        return None
    if is_passed(value):
        return "verified"
    if v.startswith("reject"):
        return "rejected"
    if v.startswith(("flag", "needs review", "need review", "held", "hold")):
        return "flagged"
    return None


NAME_STOP = {
    "bank", "banks", "credit", "union", "federal", "financial", "fcu", "the", "and", "of", "national",
    "association", "corp", "corporation", "inc", "bancorp", "bancshares", "banking", "savings", "trust",
    "company", "community", "services", "group", "acquired", "by", "merging", "merged", "into", "to", "be",
    "with", "state", "first", "holding", "holdings", "mhc", "division", "closed", "ncua", "assumed",
    "members", "shares", "n.a", "na", "co", "loan",
}


def name_tokens(name: str) -> set[str]:
    words = re.findall(r"[a-z0-9&']+", norm_inst(name))
    return {w for w in words if len(w) >= 3 and w not in NAME_STOP}


def coarse_type(typ: str) -> str:
    """Collector types like 'merger (completed)' -> 'merger'."""
    return re.split(r"\s*\(", (typ or "").strip().lower(), maxsplit=1)[0].strip()



PLANNED_BRANCH_ID = re.compile(r"-branch-planned-", re.I)


def is_planned_branch(row_id: str, types: list[str] | None = None) -> bool:
    """True when this is a planned-branch row, not an already-open branch.

    Signalled by '-branch-planned-' in the row id, or a type that names a
    planned branch. A plain 'branch_opening' type is not enough: opened and
    planned branches share that type, and must not be collapsed together.
    """
    if PLANNED_BRANCH_ID.search(row_id or ""):
        return True
    for typ in types or []:
        t = (typ or "").replace("_", " ").replace("-", " ").casefold()
        if "planned" in t and "branch" in t:
            return True
    return False


def date_from_filename(path: Path) -> date | None:
    m = FILENAME_DATE.findall(path.name)
    try:
        return date.fromisoformat(m[-1]) if m else None
    except ValueError:
        return None


def file_day(path: Path) -> date:
    return date_from_filename(path) or datetime.fromtimestamp(path.stat().st_mtime).date()


def file_sort_key(path: Path) -> tuple:
    return (file_day(path), path.stat().st_mtime, str(path))


def is_snapshot(path: Path) -> bool:
    name = path.name
    return bool(SNAPSHOT_NAME.search(name)) or name.startswith(("staging.", "staging-")) or SNAPSHOTS in path.parents


def read_tsv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        return [{(k or "").strip(): (v or "").strip() if isinstance(v, str) else (v or "") for k, v in row.items()}
                for row in csv.DictReader(f, delimiter="\t")]


def header_of(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        return [c.strip() for c in next(csv.reader(f, delimiter="\t"), [])]


def is_verdict_file(path: Path) -> bool:
    try:
        header = header_of(path)
    except OSError:
        return False
    cols = {c.casefold() for c in header}
    if cols & QUOTE_COLUMNS and not (cols & {"verdict", "trigger_type"}):
        return False  # strategic-priority quote files
    if not cols & set(VERDICT_COLUMNS):
        return False
    for i, row in enumerate(read_tsv(path)):
        if i > 400:
            break
        if verdict_status(first_field(row, VERDICT_COLUMNS)):
            return True
    return False


def is_resolution_file(path: Path) -> bool:
    return path.parent == FI and (path.match(RESOLUTION_GLOB) or path.name == RESOLUTIONS_EXTRA.name)


def resolution_files() -> list[Path]:
    """Newest first: by date in the file name, then mtime."""
    files = [p for p in FI.glob(RESOLUTION_GLOB) if p.is_file()]
    if RESOLUTIONS_EXTRA.is_file():
        files.append(RESOLUTIONS_EXTRA)
    return sorted(files, key=file_sort_key, reverse=True)


def discover_verdict_files() -> list[Path]:
    """Same discovery rule as verified_unpublished.py (legacy)."""
    found: set[Path] = set()
    for path in FI.rglob("*.tsv"):
        name = path.name.casefold()
        if name.startswith("verify") or "verif" in name:
            found.add(path.resolve())
    for pattern in EXTRA_VERDICT_GLOBS:
        base = Path(pattern).parent
        for path in base.glob(Path(pattern).name):
            found.add(path.resolve())
    out = [p for p in found if p.is_file() and not is_snapshot(p) and not is_resolution_file(p) and is_verdict_file(p)]
    out.sort(key=file_sort_key)
    return out


# ---- configuration -------------------------------------------------------

def configure(cfg: dict) -> None:
    """Point every path at cfg['data_dir'] (and the site checkout at cfg['site_dir'])."""
    global FI, SITE, TRIGGERS_REF, EXTRA_VERDICT_GLOBS, META_GLOBS, FRESH_WINDOW_DAYS, TZ_NAME
    global LEDGER, HISTORY, CONFLICTS, META, LOCK, SNAPSHOTS, STAGING_FILES, BACKFILL_STAGING, PUBLISH_LOG
    global RESOLUTIONS_EXTRA, RES_WARNINGS, EVENTS
    if not cfg.get("data_dir"):
        raise SystemExit("ledger: no data_dir configured (use --config, FISIGNAL_LEDGER_CONFIG or FISIGNAL_DATA_DIR)")
    FI = Path(cfg["data_dir"])
    SITE = Path(cfg.get("site_dir") or FI)
    TRIGGERS_REF = cfg.get("triggers_ref") or "origin/main:data/triggers.json"
    EXTRA_VERDICT_GLOBS = tuple(cfg.get("extra_verdict_globs") or ())
    META_GLOBS = tuple(cfg.get("meta_globs") or ())
    FRESH_WINDOW_DAYS = int(cfg.get("fresh_window_days") or 14)
    TZ_NAME = cfg.get("timezone") or "America/New_York"
    LEDGER = FI / "ledger.tsv"
    HISTORY = FI / "ledger-history.tsv"
    CONFLICTS = FI / "ledger-conflicts.tsv"
    META = FI / "ledger-meta.json"
    LOCK = FI / ".ledger.lock"
    SNAPSHOTS = FI / "snapshots"
    STAGING_FILES = (FI / "staging.tsv", FI / "staging-backfill.tsv")
    BACKFILL_STAGING = STAGING_FILES[1]
    PUBLISH_LOG = FI / "publish-log.tsv"
    RESOLUTIONS_EXTRA = FI / "ledger-resolutions.tsv"
    RES_WARNINGS = FI / "ledger-resolution-warnings.tsv"
    EVENTS = FI / "ledger-events.tsv"


def load_config(path: str | None = None) -> dict:
    path = path or os.environ.get("FISIGNAL_LEDGER_CONFIG")
    cfg: dict = {}
    if path:
        cfg = json.loads(Path(path).read_text())
    if os.environ.get("FISIGNAL_DATA_DIR"):
        cfg["data_dir"] = os.environ["FISIGNAL_DATA_DIR"]
    if os.environ.get("FISIGNAL_SITE_DIR"):
        cfg["site_dir"] = os.environ["FISIGNAL_SITE_DIR"]
    return cfg


def setup(config_path: str | None = None) -> dict:
    cfg = load_config(config_path)
    configure(cfg)
    return cfg


# ---- time (Eastern) -----------------------------------------------------

def tz():
    from zoneinfo import ZoneInfo
    return ZoneInfo(TZ_NAME)


def now_et() -> datetime:
    return datetime.now(tz())


def parse_when(value: str) -> datetime | None:
    """ISO timestamp (any offset) or YYYY-MM-DD (= 00:00 Eastern) -> aware datetime in Eastern time."""
    v = (value or "").strip()
    if not v:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            return datetime.fromisoformat(v).replace(tzinfo=tz())
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=tz())).astimezone(tz())


def business_seconds(start: datetime, end: datetime) -> float:
    """Seconds between start and end that fall on Mon-Fri (Eastern calendar days). Holidays are not skipped."""
    if end <= start:
        return 0.0
    from datetime import timedelta
    total = 0.0
    day = start.astimezone(tz()).date()
    last = end.astimezone(tz()).date()
    while day <= last:
        if day.weekday() < 5:
            lo = datetime(day.year, day.month, day.day, tzinfo=tz())
            nxt = day + timedelta(days=1)
            hi = datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz())
            a, b = max(lo, start), min(hi, end)
            if b > a:
                total += (b - a).total_seconds()
        day += timedelta(days=1)
    return total


def derive_lane(event_date: str, ref: datetime | None, backfill: bool) -> str:
    """backfill if the backfill flag is set; fresh if the event date is within FRESH_WINDOW_DAYS
    of the reference time (Eastern calendar days); otherwise backlog. No event date -> fresh."""
    if backfill:
        return "backfill"
    d = parse_when(event_date)
    if d is None or ref is None:
        return "fresh"
    age = (ref.astimezone(tz()).date() - d.date()).days
    return "fresh" if age <= FRESH_WINDOW_DAYS else "backlog"


# ---- event log (explicit writes; merged into every build) ---------------

RANK = {"found": 0, "staged": 1, "needs_review": 2, "verified": 2, "rejected": 2, "live": 3, "corrected": 4}
# set: allowed status changes. live is only ever derived from triggers.json.
TRANSITIONS = {
    "found": {"staged", "rejected"},
    "staged": {"verified", "needs_review", "rejected"},
    "needs_review": {"staged", "verified", "rejected"},
    "verified": {"needs_review", "rejected"},
    "rejected": {"staged"},
    "live": {"corrected"},
    "corrected": {"corrected"},
}


def read_events() -> list[dict]:
    return read_tsv(EVENTS)


def append_event(ev: dict) -> None:
    new_file = not EVENTS.is_file()
    with open(LOCK, "w") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        with EVENTS.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter="\t", lineterminator="\n")
            if new_file:
                w.writerow(EVENT_COLUMNS)
            w.writerow([str(ev.get(c, "") or "").replace("\t", " ").replace("\n", " ") for c in EVENT_COLUMNS])


def history_first_seen() -> dict[str, str]:
    out: dict[str, str] = {}
    for r in read_tsv(HISTORY):
        ts = r.get("timestamp", "")
        if ts and (r["row_id"] not in out or ts < out[r["row_id"]]):
            out[r["row_id"]] = ts
    return out


def find_target(records: dict, rid: str) -> str | None:
    if rid in records:
        return rid
    for k, rec in records.items():
        if rec.get("_live") == rid:
            return k
    return None


def apply_events(records: dict, now: str) -> tuple[list[list[str]], list[str]]:
    """Merge the event log into derived records. Returns (extra conflict lines, warnings)."""
    conflicts, warns = [], []
    first_seen = history_first_seen()
    adds: dict[str, dict] = {}
    for ev in read_events():
        rid, action = ev.get("row_id", ""), ev.get("action", "")
        if not rid:
            continue
        if action == "add":
            if rid in adds:
                continue  # dedupe: first add wins
            adds[rid] = ev
            st = canon_status(ev.get("status", ""))
            rec = records.get(rid)
            if rec is None:
                records[rid] = rec = {
                    "row_id": rid, "status": st, "verdict_file": "", "pr": "", "date": ev["event_at"][:10],
                    "source": f"event:add {ev['event_at']}", "note": ev.get("note", ""), "_conflict": False,
                    "_live": "", "_verdict": None, "_event_date": "", "_added": "", "_backfill": False, "_urls": [],
                    "_staging_only": True}
            elif rec.get("_staging_only"):
                rec["status"], rec["source"] = st, f"event:add {ev['event_at']}"
            rec["found_at"] = ev.get("found_at") or ev["event_at"]
            if ev.get("lane"):
                rec["lane"] = ev["lane"]
            continue
        key = find_target(records, rid)
        if key is None:
            warns.append(f"{rid}: {action} event for unknown row ignored")
            continue
        rec = records[key]
        at = ev.get("event_at", "")
        if action == "published":
            rec["published_at"] = ev.get("published_at") or at
            if ev.get("pr") and not rec.get("pr"):
                rec["pr"] = ev["pr"]
            continue
        if action != "set":
            continue
        st = canon_status(ev.get("status", ""))
        cur = rec["status"]
        if st == cur:
            if ev.get("note"):
                rec["note"] = ev["note"]
            continue
        if cur in ("live", "corrected") and st != "corrected":
            warns.append(f"{rid}: set {st} ignored (row is {cur}; live rows are never demoted)")
            continue
        if st == "corrected" and cur not in ("live", "corrected"):
            warns.append(f"{rid}: set corrected ignored (row is {cur}, not live)")
            continue
        v = rec.get("_verdict")
        ev_day = (parse_when(at) or now_et()).date()
        if st in DECISIONS and v is not None and not rec.get("_staging_only"):
            if v["day"] > ev_day:
                continue  # a newer verdict file supersedes this event
            if v["day"] == ev_day and v["status"].replace("flagged", "needs_review") != st:
                rec["_conflict"] = True
                conflicts.append([key, "event_verdict_disagree", f"ledger-events.tsv@{at} | {v['path'].name}",
                                  f"{st} | {v['verdict']}"])
        rec["status"] = st
        rec["source"] = "conflict" if rec.get("_conflict") else f"event:set {at}"
        if ev.get("note"):
            rec["note"] = ev["note"]
        if not rec.get("date") or st in DECISIONS:
            rec["date"] = at[:10]

    for rid, rec in records.items():
        fs = rec.get("found_at") or ""
        if not fs:
            cands = [c for c in (first_seen.get(rid, ""), rec.get("_added", "")) if c]
            fs = min(cands) if cands else now
            rec["found_at"] = fs
        if not rec.get("published_at") and rec["status"] in ("live", "corrected"):
            rec["published_at"] = rec.get("date") if "publish-log" in rec.get("source", "") else (
                rec.get("_added") or rec.get("date", ""))
        if not rec.get("lane"):
            rec["lane"] = derive_lane(rec.get("_event_date", ""), parse_when(fs), rec.get("_backfill", False))
    return conflicts, warns


# ---- source loading -----------------------------------------------------

def git(*args: str) -> str:
    res = subprocess.run(["git", "-C", str(SITE), *args], capture_output=True, text=True, timeout=30)
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.strip()[:300]}")
    return res.stdout


def triggers_sha() -> str:
    return git("rev-parse", "origin/main").strip()


def load_triggers() -> tuple[list[dict], str]:
    sha = triggers_sha()
    data = json.loads(git("show", f"{sha}:data/triggers.json"))
    rows = data.get("rows") or data.get("triggers") or [] if isinstance(data, dict) else data
    return rows, sha


def load_publish_log() -> dict[str, tuple[str, str]]:
    """t-id -> (date, pr_url). Expands ranges like t100-t120. Later lines win."""
    out: dict[str, tuple[str, str]] = {}
    for row in read_tsv(PUBLISH_LOG):
        ids = row.get("ids") or ""
        for part in re.split(r"[,\s]+", ids):
            m = re.fullmatch(r"t(\d+)-t?(\d+)", part)
            if m:
                width = len(part.split("-")[0]) - 1
                for n in range(int(m.group(1)), int(m.group(2)) + 1):
                    out[f"t{n:0{width}d}"] = (row.get("date", ""), row.get("pr_url", ""))
            elif re.fullmatch(r"t\d+", part):
                out[part] = (row.get("date", ""), row.get("pr_url", ""))
    return out


def source_files() -> list[Path]:
    files = ([p for p in STAGING_FILES if p.is_file()] + [p for p in (PUBLISH_LOG,) if p.is_file()]
             + discover_verdict_files() + resolution_files())
    if EVENTS.is_file():
        files.append(EVENTS)
    for g in META_GLOBS:
        files += sorted(p for p in FI.glob(g) if not is_snapshot(p))
    return files


def fingerprint(files: list[Path], sha: str) -> str:
    h = hashlib.sha256(sha.encode())
    h.update(f"schema={'|'.join(COLUMNS)}\n".encode())  # a column change forces one rebuild
    for p in sorted(files):
        st = p.stat()
        h.update(f"{p}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()


# ---- model --------------------------------------------------------------

class Row:
    def __init__(self, rid: str):
        self.id = rid
        self.insts: list[str] = []
        self.types: list[str] = []
        self.dates: list[str] = []
        self.urls: list[str] = []
        self.staging: dict | None = None
        self.staging_rows: list[dict] = []   # (file, row) for dup detection
        self.verdicts: list[dict] = []
        self.meta: dict | None = None

    def add_attrs(self, inst="", typ="", day="", url=""):
        for lst, v in ((self.insts, inst), (self.types, typ), (self.dates, day), (self.urls, url)):
            if v and v not in lst:
                lst.append(v)


def verdict_record(row: dict, path: Path, index: int) -> dict | None:
    rid = clean_id(first_field(row, ID_COLUMNS))
    raw = first_field(row, VERDICT_COLUMNS)
    st = verdict_status(raw)
    if not rid or not st:
        return None
    day = first_field(row, DATE_COLUMNS)
    if day and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        try:
            day = datetime.fromisoformat(day[:10]).date().isoformat()
        except ValueError:
            pass
    return {
        "id": rid, "verdict": raw, "status": st, "passed": st == "verified",
        "institution": first_field(row, ("institution",)), "type": first_field(row, TYPE_COLUMNS),
        "date": day, "notes": first_field(row, NOTES_COLUMNS), "source_url": first_field(row, URL_COLUMNS),
        "path": path, "day": file_day(path), "sort_key": (*file_sort_key(path), index),
    }


def notes_say_dropped(*notes: str) -> bool:
    text = " ".join(n for n in notes if n)
    return bool(text) and bool(DROP_NOTES.search(NEGATED_DROP.sub(" ", text)))


def load_model():
    rows: dict[str, Row] = {}

    def get(rid: str) -> Row:
        if rid not in rows:
            rows[rid] = Row(rid)
        return rows[rid]

    for path in STAGING_FILES:
        for r in read_tsv(path):
            rid = clean_id(r.get("id", ""))
            if not rid:
                continue
            rec = {"id": rid, "institution": r.get("institution", ""), "type": r.get("trigger_type") or r.get("type", ""),
                   "date": r.get("date", ""), "status": r.get("status", ""), "notes": r.get("notes") or r.get("note", ""),
                   "source_url": r.get("source_url", ""), "file": path, "summary": r.get("summary", "")}
            row = get(rid)
            row.staging_rows.append(rec)
            row.staging = rec  # later file wins for attrs (legacy did the same)
            row.add_attrs(rec["institution"], rec["type"], rec["date"], rec["source_url"])

    vfiles = discover_verdict_files()
    for path in vfiles:
        for i, r in enumerate(read_tsv(path)):
            rec = verdict_record(r, path, i)
            if rec is None:
                continue
            row = get(rec["id"])
            row.verdicts.append(rec)
            row.add_attrs(rec["institution"], rec["type"], rec["date"], rec["source_url"])

    # metadata-only (collector queue files) for ids we already track
    for g in META_GLOBS:
        for path in sorted(FI.glob(g)):
            if is_snapshot(path):
                continue
            for r in read_tsv(path):
                rid = clean_id(r.get("id", ""))
                if rid in rows and rows[rid].staging is None:
                    row = rows[rid]
                    row.meta = {"file": path, **r}
                    row.add_attrs(r.get("institution", ""), r.get("trigger_type") or r.get("type", ""),
                                  r.get("date", ""), r.get("source_url", ""))
    return rows, vfiles


TID = re.compile(r"\bt\d{3,}\b")
MATCH_NEGATION = re.compile(r"\b(?:false match|not\b|other\s)", re.I)
TAKEDOWN = re.compile(r"(\b(?:do not|don't|not)\s+)?(?:\btake\s+(?:t\d+\s+)?down\b|\bshould come down\b|\btakedown\b)", re.I)
STATUS_WORDS = (
    (re.compile(r"^(?:stage|staged|pass|passed|verified)\b", re.I), "verified"),
    (re.compile(r"^(?:needs review|need review|flag|flagged|hold|held)\b", re.I), "flagged"),
    (re.compile(r"^(?:reject|rejected)\b", re.I), "rejected"),
    (re.compile(r"^(?:should come down|take\s+(?:t\d+\s+)?down|takedown|remove)\b", re.I), "takedown"),
)


def load_resolutions() -> tuple[list[dict], list[list[str]]]:
    """Parse review resolution rows. Returns (resolutions newest-first, warnings)."""
    out, warns = [], []
    for path in resolution_files():
        for i, row in enumerate(read_tsv(path), start=2):
            rid = clean_id(first_field(row, ("row_id", "id")))
            verdict = first_field(row, ("resolution", "verdict"))
            live_txt = first_field(row, ("live_id", "candidates", "live_match"))
            kind_col = first_field(row, ("conflict_kind", "kind"))
            notes = first_field(row, ("reason/notes", "notes", "note", "reason"))
            where = f"{path.name}:{i}"
            if not rid or not verdict:
                warns.append([rid, where, "unparseable", "missing id or verdict"])
                continue
            choice = None
            for pat, st in STATUS_WORDS:
                if pat.search(verdict.strip()):
                    choice = st
                    break
            if choice is None:
                warns.append([rid, where, "unparseable", f"verdict not recognised: {verdict[:80]}"])
                continue
            takedown = choice == "takedown" or any(not m.group(1) for m in TAKEDOWN.finditer(verdict))
            if kind_col:
                kinds = {kind_col.strip()}
            else:  # kind named verbatim by the reviewer in the resolution text
                kinds = {k for k in CONFLICT_KINDS if re.search(rf"(?<!not )\b{k}\b", notes + " " + verdict)}
            tids = set(TID.findall(live_txt))
            if not live_txt:
                live_choice = None
            elif MATCH_NEGATION.search(live_txt):
                live_choice = "reject_match"
            elif len(tids) == 1:
                live_choice = "confirm"
            else:
                live_choice = None
            out.append({"id": rid, "verdict": verdict, "choice": choice, "takedown": takedown, "kinds": kinds,
                        "tids": tids, "live_choice": live_choice, "file": path, "where": where,
                        "key": f"{path.name}|{rid}|" + hashlib.sha1(json.dumps(row, sort_keys=True).encode()).hexdigest()[:12]})
    return out, warns


def build_records():
    rows, vfiles = load_model()
    triggers, sha = load_triggers()
    plog = load_publish_log()
    conflicts: list[list[str]] = []
    row_conf: list[dict] = []
    resolutions, res_warnings = load_resolutions()
    res_by_id: dict[str, list[dict]] = defaultdict(list)
    for res in resolutions:
        res_by_id[res["id"]].append(res)
    used_res: set[str] = set()
    applied: list[dict] = []

    def conflict(rid, kind, sources, values):
        row_conf.append({"rid": rid, "kind": kind, "line": [rid, kind, " | ".join(sources), " | ".join(values)],
                         "tids": set(TID.findall(" ".join(sources) + " " + " ".join(values)))})

    # live indexes
    by_key: dict[tuple, set[str]] = defaultdict(set)
    by_url: dict[str, set[str]] = defaultdict(set)
    live_by_id: dict[str, dict] = {}
    for t in triggers:
        tid = str(t.get("id") or "")
        if not tid:
            continue
        if tid in live_by_id and live_by_id[tid] != t:
            conflict(tid, "duplicate_live_id", ["triggers.json", "triggers.json"], ["two rows share this id"])
        live_by_id[tid] = t
        inst, typ, day = norm_inst(t.get("institution", "")), (t.get("type") or "").strip(), (t.get("date") or "").strip()
        if inst and typ and day:
            by_key[(inst, typ, day)].add(tid)
        if norm_url(t.get("source_url", "")):
            by_url[norm_url(t.get("source_url", ""))].add(tid)
        if tid in rows:  # a staging/verdict row that already uses the live id
            pass

    url_users: dict[str, set[str]] = defaultdict(set)
    for r in rows.values():
        for u in r.urls:
            url_users[norm_url(u)].add(r.id)

    def live_match(r: Row) -> tuple[set[str], str]:
        """Exact id first, then (institution, type, date), then source URL, then a name-token fuzzy match.

        A planned-branch row never attaches to a different live trigger: two
        events can share an institution, type, date and even a source URL
        (one announcement covering an opening and a separate plan).
        """
        if r.id in live_by_id:
            return {r.id}, "id"
        if is_planned_branch(r.id, r.types):
            return set(), ""
        types = set()
        for t in r.types:
            types |= type_aliases(r.id, t) | type_aliases(r.id, coarse_type(t))
        keys = set()
        for i in r.insts:
            for t in types:
                for d in r.dates:
                    keys |= by_key.get((norm_inst(i), t, d), set())
        if keys:
            return keys, "key"
        urls = set()
        for u in r.urls:
            urls |= by_url.get(norm_url(u), set())
        if len(urls) > 1:  # one release, several live rows: break the tie on institution name
            best = best_by_name(r, urls)
            if len(best) == 1:
                return best, "url+name"
        if urls:
            return urls, "url"
        cands = {tid for tid, t in live_by_id.items()
                 if (t.get("date") or "") in r.dates and (t.get("type") or "") in types}
        best = best_by_name(r, cands)
        if len(best) == 1:
            return best, "fuzzy"
        if best:
            return best, "fuzzy-ambiguous"
        return set(), ""

    def best_by_name(r: Row, tids: set[str]) -> set[str]:
        mine = set().union(*(name_tokens(i) for i in r.insts)) if r.insts else set()
        scored = defaultdict(set)
        for tid in tids:
            t = live_by_id[tid]
            n = len(mine & (name_tokens(t.get("institution", "")) | name_tokens(t.get("fi_name", "") or "")))
            if n:
                scored[n].add(tid)
        return scored[max(scored)] if scored else set()

    records: dict[str, dict] = {}
    claimed: set[str] = set()
    for rid in sorted(rows):
        r = rows[rid]
        rec = {"row_id": rid, "status": "", "verdict_file": "", "pr": "", "date": "", "source": "", "note": "",
               "_conflict": False, "_live": "", "_verdict": None}
        row_conf.clear()

        # duplicate ids with different content across staging files
        if len(r.staging_rows) > 1:
            sig = {(s["institution"], s["type"], s["date"], s["source_url"], s["summary"]) for s in r.staging_rows}
            if len(sig) > 1:
                rec["_conflict"] = True
                conflict(rid, "duplicate_id_different_content", [s["file"].name for s in r.staging_rows],
                         [f'{s["institution"]}/{s["type"]}/{s["date"]}' for s in r.staging_rows])

        # verdicts: newest file day wins; same-day disagreement is a conflict
        verdict = None
        if r.verdicts:
            vs = sorted(r.verdicts, key=lambda v: v["sort_key"])
            newest_day = vs[-1]["day"]
            same_day = [v for v in vs if v["day"] == newest_day]
            verdict = vs[-1]
            if len({v["status"] for v in same_day}) > 1:
                rec["_conflict"] = True
                conflict(rid, "verdict_files_disagree", [str(v["path"]) for v in same_day],
                         [f'{v["verdict"]} ({v["status"]})' for v in same_day])
            rec["_verdict"] = verdict
            rec["verdict_file"] = str(verdict["path"])

        vstatus = None
        vsource = ""
        if verdict:
            vstatus = verdict["status"]
            vsource = f'verdict:{verdict["path"].name}'
            if vstatus == "verified" and notes_say_dropped((r.staging or {}).get("notes", ""), verdict["notes"]):
                vstatus, vsource = "rejected", vsource + " (drop note)"

        # staging-only status
        sstatus, ssource = None, ""
        if r.staging:
            raw = normalize_verdict(r.staging.get("status", ""))
            ssource = f'staging:{r.staging["file"].name}'
            if raw in {"dropped"}:
                sstatus = "rejected"
            elif raw in {"held", "hold"} or raw.startswith("needs review"):
                sstatus = "flagged"
            elif raw == "live":
                sstatus = "live-claim"
            elif notes_say_dropped(r.staging.get("notes", "")):
                sstatus = "rejected"
            else:
                sstatus = "staged"
            if sstatus == "rejected" and vstatus == "verified":
                vstatus, vsource = "rejected", vsource + f" + {ssource} dropped"

        live_ids, how = live_match(r)
        if len(live_ids) > 1:
            rec["_conflict"] = True
            conflict(rid, "ambiguous_live_match", [f"triggers.json@{sha[:10]} ({how} match)"], sorted(live_ids, key=tid_key))
        if live_ids:
            tid = sorted(live_ids, key=tid_key)[0]
            rec["status"] = "live"
            rec["_live"] = tid
            pub = plog.get(tid)
            t = live_by_id[tid]
            if pub:
                rec["date"], rec["pr"] = pub
                rec["source"] = f"triggers.json:{tid} ({how} match; publish-log)"
            else:
                rec["date"] = t.get("added", "")
                rec["source"] = f"triggers.json:{tid} ({how} match; no publish-log entry)"
            if t.get("fi_only"):
                rec["source"] += " fi_only"
            if vstatus in {"rejected", "flagged"}:
                rec["_conflict"] = True
                conflict(rid, f"live_but_{vstatus}", [f"triggers.json:{tid}", vsource], ["live", verdict["verdict"]])
        else:
            if sstatus == "live-claim":
                rec["_conflict"] = True
                conflict(rid, "staging_says_live_not_in_triggers", [ssource, f"triggers.json@{sha[:10]}"],
                         ["Live", "absent"])
            if vstatus:
                rec["status"], rec["source"] = vstatus, vsource
                rec["date"] = verdict["day"].isoformat()
            elif sstatus and sstatus != "live-claim":
                rec["status"], rec["source"] = sstatus, ssource
            else:
                rec["status"], rec["source"] = "staged", ssource or "unknown"
        if rec["_conflict"]:
            rec["source"] = "conflict"

        # ---- review resolutions (apply only what the reviewer wrote) ----
        if row_conf:
            res = None
            matched: list[dict] = []
            for cand in res_by_id.get(rid, []):  # newest file first
                m = [c for c in row_conf if c["kind"] in cand["kinds"] or (cand["tids"] and cand["tids"] == c["tids"])]
                if m:
                    res, matched = cand, m
                    break
            if res:
                used_res.add(res["key"])
                before = rec["status"]
                action = res["choice"]
                tag = f'resolved:{res["file"].name}'
                if res["live_choice"] == "reject_match" and rec["status"] == "live":
                    if how == "id":
                        res_warnings.append([rid, res["where"], "refused", "row id is itself a live t-id"])
                        res = None
                    else:  # the row is not that live row; the live row itself is untouched
                        live_ids = set()
                        rec["_live"], rec["pr"] = "", ""
                        st = action if action in {"verified", "flagged", "rejected"} else (vstatus or sstatus or "staged")
                        rec["status"] = st if st != "live-claim" else "staged"
                        rec["date"] = verdict["day"].isoformat() if verdict else ""
                if res is not None:
                    if rec["status"] == "live":
                        if res["takedown"] or action in {"takedown", "rejected"}:
                            rec["note"] = f'pending_takedown (owner decides; nothing acts on this): {res["verdict"][:120]}'
                            conflicts.append([rid, "pending_takedown", f'{tag} | triggers.json:{rec["_live"]}',
                                              f'live (unchanged) | {res["verdict"][:120]}'])
                        else:
                            rec["note"] = f'verifier: {res["verdict"][:120]} (live unchanged)'
                    else:
                        if action in {"verified", "flagged", "rejected"}:
                            rec["status"] = action
                        rec["note"] = f'verifier: {res["verdict"][:120]}'
                    remaining = [c for c in row_conf if c not in matched]
                    rec["_conflict"] = bool(remaining)
                    rec["source"] = "conflict" if remaining else tag
                    row_conf[:] = remaining
                    applied.append({"row_id": rid, "old": before, "new": rec["status"], "key": res["key"],
                                    "event": f'{tag} ({",".join(sorted(c["kind"] for c in matched))}) -> '
                                             f'{rec["status"]}{" pending_takedown" if "pending_takedown" in rec["note"] else ""}'})
        conflicts.extend(c["line"] for c in row_conf)
        if rec["status"] == "live" and not rec["source"].startswith("triggers.json:"):
            rec["note"] = f'live={rec["_live"]}' + (f'; {rec["note"]}' if rec["note"] else "")
        claimed |= live_ids
        if rec["status"] == "live" and rec["_live"] in live_by_id:
            lt = live_by_id[rec["_live"]]
            rec["_event_date"] = lt.get("date", "") or (r.dates[0] if r.dates else "")
            rec["_added"] = lt.get("added", "")
            rec["_backfill"] = lt.get("backfill") is True
        else:
            rec["_event_date"] = r.dates[0] if r.dates else ""
            rec["_added"] = ""
            rec["_backfill"] = False
        rec["_backfill"] = rec["_backfill"] or any(s["file"] == BACKFILL_STAGING for s in r.staging_rows)
        rec["_urls"] = list(r.urls)
        rec["_staging_only"] = rec["status"] == "staged" and not r.verdicts and not rec["_live"] and not rec["_conflict"]
        if rec["status"] == "flagged":
            rec["status"] = "needs_review"
        records[rid] = rec

    for tid, t in live_by_id.items():
        if tid in records or tid in claimed:
            continue
        pub = plog.get(tid)
        records[tid] = {
            "row_id": tid, "status": "live", "verdict_file": "", "pr": pub[1] if pub else "",
            "date": pub[0] if pub else t.get("added", ""),
            "source": f"triggers.json:{tid}" + (" (publish-log)" if pub else " (no publish-log entry)")
                      + (" fi_only" if t.get("fi_only") else ""),
            "note": "", "_conflict": False, "_live": tid, "_verdict": None,
            "_event_date": t.get("date", ""), "_added": t.get("added", ""), "_backfill": t.get("backfill") is True,
            "_urls": [t.get("source_url", "")] if t.get("source_url") else [],
        }

    # warn about resolutions that matched no current conflict
    for res in resolutions:
        if res["key"] not in used_res and not any(w[1] == res["where"] for w in res_warnings):
            res_warnings.append([res["id"], res["where"], "no_matching_conflict",
                                 f'not applied: {res["verdict"][:100]}'])

    # hard guard: every live t-id must still be live in the ledger
    own_live = {t for t in live_by_id if records.get(t, {}).get("status") in ("live", "corrected")}
    missing = set(live_by_id) - claimed - own_live
    if missing:
        raise RuntimeError(f"guard: live rows would lose live status: {sorted(missing, key=tid_key)[:10]}")
    return records, rows, conflicts, vfiles, sha, applied, res_warnings


def tid_key(rid: str):
    m = re.fullmatch(r"t(\d+)", rid)
    return (0, int(m.group(1)), "") if m else (1, 0, rid)


def read_ledger(path: Path | None = None) -> dict[str, dict]:
    """Read ledger.tsv; old 'flagged' statuses read as needs_review."""
    path = path or LEDGER
    out = {}
    for r in read_tsv(path) if path.is_file() else []:
        r["status"] = canon_status(r.get("status", ""))
        out[r["row_id"]] = r
    return out


def atomic_write_tsv(path: Path, header: list[str], lines: list[list[str]]):
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
            w.writerow(header)
            w.writerows([[str(c).replace("\t", " ").replace("\n", " ") for c in line] for line in lines])
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


HISTORY_COLUMNS = ["row_id", "old", "new", "timestamp", "event"]


def upgrade_history_header() -> None:
    """Add the 'event' column to an older 4-column history file (existing lines keep event empty)."""
    if not HISTORY.is_file() or header_of(HISTORY) == HISTORY_COLUMNS:
        return
    old = read_tsv(HISTORY)
    atomic_write_tsv(HISTORY, HISTORY_COLUMNS, [[r.get(c, "") or "" for c in HISTORY_COLUMNS] for r in old])


def history_seen_dates() -> dict[str, tuple[str, str]]:
    """row_id -> (status, first timestamp of that status) from ledger-history."""
    out = {}
    for r in read_tsv(HISTORY):
        out[r["row_id"]] = (r.get("new", ""), r.get("timestamp", ""))
    return out


def build(quiet: bool = False) -> dict:
    with open(LOCK, "w") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        records, _, conflicts, vfiles, sha, applied, res_warnings = build_records()
        now = now_et().isoformat(timespec="seconds")
        ev_conflicts, ev_warnings = apply_events(records, now)
        conflicts.extend(ev_conflicts)
        prev = read_ledger()

        # history transitions
        trans = []
        for rid in sorted(set(prev) | set(records), key=tid_key):
            old = prev.get(rid, {}).get("status", "")
            new = records.get(rid, {}).get("status", "")
            if old != new:
                trans.append([rid, old, new, now])
        hist = history_seen_dates()
        for rid, old, new, ts in trans:
            hist[rid] = (new, ts)
        for rec in records.values():  # staged rows: date the ledger first saw them staged
            if not rec["date"]:
                h = hist.get(rec["row_id"])
                rec["date"] = (h[1][:10] if h and h[0] == rec["status"] else now[:10])

        lines = [[records[r].get(c, "") for c in COLUMNS] for r in sorted(records, key=tid_key)]
        atomic_write_tsv(LEDGER, COLUMNS, lines)
        atomic_write_tsv(CONFLICTS, ["row_id", "kind", "sources", "values", "detected_at"],
                         [c + [now] for c in sorted(conflicts, key=lambda c: (c[1], tid_key(c[0])))])
        old_meta = {}
        if META.is_file():
            try:
                old_meta = json.loads(META.read_text())
            except ValueError:
                old_meta = {}
        logged = set(old_meta.get("applied_resolutions", []))
        res_events = [[a["row_id"], a["old"], a["new"], now, a["event"]] for a in applied if a["key"] not in logged]
        upgrade_history_header()
        rows_out = [t + [""] for t in trans] + res_events
        if rows_out:
            new_file = not HISTORY.is_file()
            with HISTORY.open("a", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter="\t", lineterminator="\n")
                if new_file:
                    w.writerow(HISTORY_COLUMNS)
                w.writerows(rows_out)
        atomic_write_tsv(RES_WARNINGS, ["row_id", "where", "warning", "detail", "detected_at"],
                         [w + [now] for w in res_warnings])
        files = source_files()
        meta = {"built_at": now, "triggers_sha": sha, "fingerprint": fingerprint(files, sha),
                "verdict_files": [str(p) for p in vfiles],
                "resolution_files": [str(p) for p in resolution_files()],
                "applied_resolutions": sorted(logged | {a["key"] for a in applied})}
        tmp = META.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta, indent=2) + "\n")
        os.replace(tmp, META)
    counts = defaultdict(int)
    for rec in records.values():
        counts[rec["status"]] += 1
    open_conf = [c for c in conflicts if c[1] != "pending_takedown"]
    summary = {"rows": len(records), "counts": dict(counts), "conflicts": len(open_conf), "transitions": len(trans)}
    if not quiet:
        print(f"ledger: {len(records)} rows " + ", ".join(f"{s}={counts.get(s, 0)}" for s in STATUSES)
              + f"; open conflicts={len(open_conf)}; pending_takedown={len(conflicts) - len(open_conf)}"
              + f"; transitions={len(trans)}; resolutions applied={len(applied)}", file=sys.stderr)
    for w in ev_warnings:
        print(f"ledger WARNING event {w}", file=sys.stderr)
    if res_warnings:
        for w in res_warnings:
            print(f"ledger WARNING resolution {w[1]} {w[0]}: {w[2]} ({w[3]})", file=sys.stderr)
    return summary


def is_stale() -> bool:
    if not LEDGER.is_file() or not META.is_file():
        return True
    try:
        meta = json.loads(META.read_text())
        sha = triggers_sha()
        return meta.get("fingerprint") != fingerprint(source_files(), sha)
    except (OSError, ValueError, RuntimeError):
        return True


def ensure_fresh() -> None:
    if is_stale():
        build(quiet=True)


# ---- verified-unpublished ----------------------------------------------

def display_fields(r: Row, verdict: dict) -> dict:
    """Same field choice as legacy attach_staging()."""
    # Collector queue metadata is deliberately NOT used here: legacy only listed
    # rows whose staging row or verdict row carries institution/type/date.
    st = None
    if r.staging:
        typ = r.staging["type"] or verdict["type"]
        return {"id": r.id, "institution": verdict["institution"] or r.staging["institution"],
                "type": board_type(r.id, typ), "date": verdict["date"] or r.staging["date"]}
    if st:
        return {"id": r.id, "institution": verdict["institution"] or st["institution"],
                "type": board_type(r.id, verdict["type"] or st["type"]), "date": verdict["date"] or st["date"]}
    return {"id": r.id, "institution": verdict["institution"], "type": board_type(r.id, verdict["type"]),
            "date": verdict["date"]}


def verified_unpublished_rows() -> tuple[list[dict], list[str], list[str]]:
    ensure_fresh()
    ledger = read_ledger()
    rows, vfiles = load_model()
    out, skipped_conflict = [], []
    for rid, lrow in ledger.items():
        if lrow["status"] != "verified":
            continue
        if lrow["source"] == "conflict":
            skipped_conflict.append(rid)
            continue
        r = rows.get(rid)
        if r is None or not r.verdicts:
            continue
        verdict = sorted(r.verdicts, key=lambda v: v["sort_key"])[-1]
        d = display_fields(r, verdict)
        if not (d["id"] and d["institution"] and d["type"] and d["date"]):
            continue
        d["verdict file"] = lrow["verdict_file"]
        out.append(d)
    out.sort(key=lambda r: (r["date"], r["id"], r["verdict file"]))
    return out, [str(p) for p in vfiles], skipped_conflict


# ---- snapshot -----------------------------------------------------------

def glob_escape(text: str) -> str:
    return re.sub(r"([*?\[])", r"[\1]", text)


def snapshot(target: str) -> Path:
    src = Path(target)
    if not src.is_absolute():
        src = (FI / src) if (FI / src).exists() else src.resolve()
    if not src.is_file():
        raise SystemExit(f"snapshot: no such file: {src}")
    SNAPSHOTS.mkdir(exist_ok=True)
    name = src.name[:-4] if src.name.endswith(".tsv") else src.name
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    taken = [p.name for p in SNAPSHOTS.glob(f"{glob_escape(name)}.{stamp}*.tsv")]
    if not taken:
        dest = SNAPSHOTS / f"{name}.{stamp}.tsv"
    else:  # same second: always move forward so retention order stays correct
        nums = [int(m.group(1)) for t in taken if (m := re.search(r"-(\d+)\.tsv$", t[len(name) + 1 + len(stamp):]))]
        dest = SNAPSHOTS / f"{name}.{stamp}-{max(nums, default=0) + 1}.tsv"
    tmp = dest.with_suffix(".tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dest)
    pat = re.compile(re.escape(name) + r"\.(\d{8}-\d{6})(?:-(\d+))?\.tsv")
    mine = []
    for p in SNAPSHOTS.iterdir():
        m = pat.fullmatch(p.name)
        if m:
            mine.append(((m.group(1), int(m.group(2) or 0)), p))
    mine = [p for _, p in sorted(mine)]
    for old in mine[:-KEEP_SNAPSHOTS]:
        old.unlink()
    print(f"snapshot: {dest}", file=sys.stderr)
    build()
    return dest


# ---- CLI ----------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Row ledger (see module docstring)")
    ap.add_argument("--config", help="JSON config (default: $FISIGNAL_LEDGER_CONFIG)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("build", help="full rebuild of ledger.tsv (also the default with no subcommand)")
    sp = sub.add_parser("snapshot")
    sp.add_argument("file")
    vp = sub.add_parser("verified-unpublished")
    vp.add_argument("--json", action="store_true", dest="as_json")
    vp.add_argument("--quiet", action="store_true")
    sub.add_parser("status")
    ad = sub.add_parser("add", help="record a found or staged item (append-only, deduped by row id)")
    ad.add_argument("row_id")
    ad.add_argument("status", choices=("found", "staged"))
    ad.add_argument("--date", help="event date YYYY-MM-DD (default: the row's date in the staging files)")
    ad.add_argument("--lane", choices=LANES, help="override the derived lane")
    ad.add_argument("--backfill", action="store_true", help="mark as a backfill item (lane backfill)")
    ad.add_argument("--found-at", help="ISO time the item was found (default: now, Eastern)")
    ad.add_argument("--note", default="")
    st = sub.add_parser("set", help="change a row's status")
    st.add_argument("row_id")
    st.add_argument("status", help="staged | verified | needs_review (alias: flagged) | rejected | corrected")
    st.add_argument("--note", default="")
    st.add_argument("--at", help="ISO time of the decision (default: now)")
    st.add_argument("--force", action="store_true", help="skip the transition check (status must still be valid)")
    pb = sub.add_parser("published", help="record published_at for rows that went live")
    pb.add_argument("row_ids", nargs="+")
    pb.add_argument("--at", help="ISO time (default: now)")
    pb.add_argument("--pr", default="")
    sl = sub.add_parser("stale", help="fresh items found/staged for more than 1 business day")
    sl.add_argument("--now", help="ISO time to evaluate at (default: now)")
    sl.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)
    setup(args.config)
    cmd = args.cmd or "build"
    if cmd == "build":
        build()
        return 0
    if cmd == "snapshot":
        snapshot(args.file)
        return 0
    if cmd == "status":
        ensure_fresh()
        counts = defaultdict(int)
        for r in read_ledger().values():
            counts[r["status"]] += 1
        conf = read_tsv(CONFLICTS)
        pend = sum(1 for c in conf if c.get("kind") == "pending_takedown")
        print("\t".join(f"{s}={counts.get(s, 0)}" for s in STATUSES)
              + f"\topen_conflicts={len(conf) - pend}\tpending_takedown={pend}")
        return 0
    if cmd == "verified-unpublished":
        return emit_verified_unpublished(args.as_json, args.quiet)
    if cmd == "add":
        return cmd_add(args)
    if cmd == "set":
        return cmd_set(args)
    if cmd == "published":
        return cmd_published(args)
    if cmd == "stale":
        return cmd_stale(args)
    return 2


def staging_row(rid: str) -> tuple[dict | None, bool]:
    """(row, is_backfill_file) from the staging files, last file wins."""
    found, bf = None, False
    for path in STAGING_FILES:
        for r in read_tsv(path):
            if clean_id(r.get("id", "")) == rid:
                found, bf = r, path == BACKFILL_STAGING
    return found, bf


def cmd_add(args) -> int:
    rid = clean_id(args.row_id)
    if any(e.get("row_id") == rid and e.get("action") == "add" for e in read_events()):
        print(f"add: {rid} already recorded (no change)", file=sys.stderr)
        return 0
    ensure_fresh()
    led = read_ledger()
    srow, bf = staging_row(rid)
    event_date = args.date or (srow or {}).get("date", "")
    if not event_date and rid not in led:
        print(f"add: {rid}: no event date (append the row to the staging file first, or pass --date)", file=sys.stderr)
        return 2
    if event_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_date):
        print(f"add: {rid}: bad event date {event_date!r} (want YYYY-MM-DD)", file=sys.stderr)
        return 2
    found_at = parse_when(args.found_at) if args.found_at else now_et()
    if found_at is None:
        print(f"add: bad --found-at {args.found_at!r}", file=sys.stderr)
        return 2
    lane = args.lane or derive_lane(event_date, found_at, args.backfill or bf)
    ts = now_et().isoformat(timespec="seconds")
    append_event({"event_at": ts, "row_id": rid, "action": "add", "status": args.status, "lane": lane,
                  "found_at": found_at.isoformat(timespec="seconds"), "note": args.note})
    build(quiet=True)
    cur = read_ledger().get(rid, {})
    print(f"add: {rid} {cur.get('status', args.status)} lane={lane} found_at={found_at.isoformat(timespec='seconds')}")
    return 0


def cmd_set(args) -> int:
    rid = clean_id(args.row_id)
    st = canon_status(args.status)
    if st not in SETTABLE:
        print(f"set: {args.status!r} is not settable (use one of: {', '.join(SETTABLE)}; flagged = needs_review)",
              file=sys.stderr)
        return 2
    ensure_fresh()
    led = read_ledger()
    key = rid if rid in led else next((k for k, r in led.items() if f"live={rid}" in r.get("note", "")
                                       or r.get("source", "").startswith(f"triggers.json:{rid} ")), None)
    if key is None:
        print(f"set: unknown row {rid} (record it with `add` first)", file=sys.stderr)
        return 2
    cur = led[key]["status"]
    if st != cur and not args.force and st not in TRANSITIONS.get(cur, set()):
        allowed = ", ".join(sorted(TRANSITIONS.get(cur, set()))) or "none"
        print(f"set: {rid} {cur} -> {st} is not allowed (from {cur}: {allowed})", file=sys.stderr)
        return 2
    if st != "corrected" and cur in ("live", "corrected"):
        print(f"set: {rid} is {cur}; live rows are never demoted", file=sys.stderr)
        return 2
    at = parse_when(args.at) if args.at else now_et()
    if at is None:
        print(f"set: bad --at {args.at!r}", file=sys.stderr)
        return 2
    append_event({"event_at": at.isoformat(timespec="seconds"), "row_id": rid, "action": "set", "status": st,
                  "note": args.note})
    build(quiet=True)
    print(f"set: {rid} {cur} -> {read_ledger().get(key, {}).get('status', st)}")
    return 0


def cmd_published(args) -> int:
    ensure_fresh()
    led = read_ledger()
    at = parse_when(args.at) if args.at else now_et()
    if at is None:
        print(f"published: bad --at {args.at!r}", file=sys.stderr)
        return 2
    bad = 0
    for raw in args.row_ids:
        rid = clean_id(raw)
        known = rid in led or any(f"live={rid}" in r.get("note", "") or r.get("source", "").startswith(f"triggers.json:{rid} ")
                                  for r in led.values())
        if not known:
            print(f"published: unknown row {rid}", file=sys.stderr)
            bad += 1
            continue
        append_event({"event_at": now_et().isoformat(timespec="seconds"), "row_id": rid, "action": "published",
                      "published_at": at.isoformat(timespec="seconds"), "pr": args.pr})
    build(quiet=True)
    print(f"published: {len(args.row_ids) - bad} row(s) at {at.isoformat(timespec='seconds')}")
    return 2 if bad else 0


def stale_rows(ledger: dict[str, dict], now: datetime) -> list[dict]:
    out = []
    for rid, r in ledger.items():
        if r.get("lane", "fresh") != "fresh" or r["status"] not in ("found", "staged"):
            continue
        start = parse_when(r.get("found_at", ""))
        if start is None:
            continue
        secs = business_seconds(start, now)
        if secs > 86400:
            out.append({"row_id": rid, "status": r["status"], "lane": r.get("lane", ""),
                        "found_at": r.get("found_at", ""), "business_days": round(secs / 86400, 1)})
    out.sort(key=lambda x: (x["found_at"], tid_key(x["row_id"])))
    return out


def cmd_stale(args) -> int:
    now = parse_when(args.now) if args.now else now_et()
    if now is None:
        print(f"stale: bad --now {args.now!r}", file=sys.stderr)
        return 2
    ensure_fresh()
    rows = stale_rows(read_ledger(), now)
    if args.as_json:
        json.dump({"count": len(rows), "rows": rows}, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        w = csv.DictWriter(sys.stdout, fieldnames=["row_id", "status", "lane", "found_at", "business_days"],
                           delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
        print(f"stale={len(rows)} (fresh items found or staged for more than 1 business day)")
    return 1 if rows else 0


def emit_verified_unpublished(as_json: bool, quiet: bool) -> int:
    rows, files, skipped = verified_unpublished_rows()
    if not quiet:
        if as_json:
            json.dump([{"id": r["id"], "institution": r["institution"], "type": r["type"], "date": r["date"],
                        "verdict_file": r["verdict file"]} for r in rows], sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
        else:
            w = csv.DictWriter(sys.stdout, fieldnames=["id", "institution", "type", "date", "verdict file"],
                               delimiter="\t", lineterminator="\n", extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"{len(rows)} verified-unpublished row{'s' if len(rows) != 1 else ''} from {len(files)} verdict files",
              file=sys.stderr)
        if skipped:
            print(f"held back {len(skipped)} verified row(s) with open conflicts (see {CONFLICTS}): "
                  + ", ".join(sorted(skipped)), file=sys.stderr)
    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main())
