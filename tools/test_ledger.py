#!/usr/bin/env python3
"""Tests for tools/ledger.py and tools/source_health.py. Run: python3 tools/test_ledger.py"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ledger  # noqa: E402
import source_health  # noqa: E402

STAGING_HEADER = "id\tinstitution\tstate\ttrigger_type\tdate\tsummary\tsource_url\tstatus\tnotes\n"
VERDICT_HEADER = "id\tinstitution\ttrigger_type\tdate\tverdict\tnotes\tsource_url\n"


def run(fn, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = fn(argv)
    return code, out.getvalue(), err.getvalue()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data, self.site = root / "data", root / "site"
        self.data.mkdir()
        (self.site / "data").mkdir(parents=True)
        self.write_triggers([
            {"id": "t001", "institution": "Alpha Bank", "type": "merger", "date": "2026-11-02",
             "added": "2026-11-03", "source_url": "https://example.com/a"},
            {"id": "t002", "institution": "Old Bank", "type": "merger", "date": "2026-03-01",
             "added": "2026-11-18", "backfill": True, "source_url": "https://example.com/old"},
        ])
        (self.data / "staging.tsv").write_text(
            STAGING_HEADER
            + "w-1\tBeta Credit Union\tMI\tmerger\t2026-11-16\tBeta merges.\thttps://example.com/b\tPending\t\n"
            + "w-2\tGamma Bank\tOH\tmerger\t2026-11-17\tGamma.\thttps://example.com/g\tPending\t\n"
            + "w-3\tDelta Bank\tOH\tmerger\t2026-11-17\tDelta.\thttps://example.com/d\tPending\t\n")
        (self.data / "staging-backfill.tsv").write_text(
            STAGING_HEADER + "bf-1\tEpsilon Bank\tTX\tmerger\t2026-02-01\tEpsilon.\thttps://example.com/e\tPending\t\n")
        (self.data / "verify-batch-2026-11-18.tsv").write_text(
            VERDICT_HEADER
            + "w-2\tGamma Bank\tmerger\t2026-11-17\tPass\t\thttps://example.com/g\n"
            + "w-3\tDelta Bank\tmerger\t2026-11-17\tFlag: date unclear\t\thttps://example.com/d\n")
        self.cfg = root / "cfg.json"
        self.cfg.write_text(json.dumps({"data_dir": str(self.data), "site_dir": str(self.site)}))

    def tearDown(self):
        self.tmp.cleanup()

    def write_triggers(self, rows):
        (self.site / "data" / "triggers.json").write_text(json.dumps({"rows": rows}))
        g = ["git", "-C", str(self.site), "-c", "user.name=t", "-c", "user.email=t@example.com"]
        if not (self.site / ".git").exists():
            subprocess.run(["git", "init", "-q", str(self.site)], check=True)
        subprocess.run(g + ["add", "-A"], check=True)
        subprocess.run(g + ["commit", "-qm", "x", "--allow-empty"], check=True)
        subprocess.run(["git", "-C", str(self.site), "update-ref", "refs/remotes/origin/main", "HEAD"], check=True)

    def L(self, *argv):
        return run(ledger.main, ["--config", str(self.cfg), *argv])

    def rows(self):
        return ledger.read_ledger()


class StatusTests(Fixture):
    def test_status_list(self):
        self.assertEqual(ledger.STATUSES,
                         ("found", "staged", "verified", "needs_review", "rejected", "live", "corrected"))

    def test_derived_statuses_and_flagged_reads_as_needs_review(self):
        self.L("build")
        r = self.rows()
        self.assertEqual(r["t001"]["status"], "live")
        self.assertEqual(r["w-1"]["status"], "staged")
        self.assertEqual(r["w-2"]["status"], "verified")
        self.assertEqual(r["w-3"]["status"], "needs_review")
        # an older ledger file that still says flagged reads as needs_review
        text = ledger.LEDGER.read_text().replace("\tneeds_review\t", "\tflagged\t")
        ledger.LEDGER.write_text(text)
        self.assertEqual(ledger.read_ledger()["w-3"]["status"], "needs_review")

    def test_flagged_input_alias(self):
        self.L("build")
        code, out, err = self.L("set", "w-1", "flagged", "--at", "2026-11-19T10:00:00-05:00")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.rows()["w-1"]["status"], "needs_review")

    def test_transitions(self):
        self.assertEqual(self.L("add", "n-1", "found", "--date", "2026-11-18",
                                "--found-at", "2026-11-19T08:00:00-05:00")[0], 0)
        self.assertEqual(self.rows()["n-1"]["status"], "found")
        code, _, err = self.L("set", "n-1", "verified")
        self.assertEqual(code, 2)  # found -> verified skips staging
        self.assertIn("not allowed", err)
        self.assertEqual(self.L("set", "n-1", "staged", "--at", "2026-11-19T09:00:00-05:00")[0], 0)
        self.assertEqual(self.L("set", "n-1", "verified", "--at", "2026-11-19T10:00:00-05:00")[0], 0)
        self.assertEqual(self.rows()["n-1"]["status"], "verified")
        # explicit writes survive a full rebuild
        self.L("build")
        self.assertEqual(self.rows()["n-1"]["status"], "verified")
        self.assertEqual(self.L("set", "n-1", "live")[0], 2)  # live is derived only
        self.assertEqual(self.L("set", "t001", "rejected")[0], 2)  # live is never demoted
        self.assertEqual(self.L("set", "t001", "corrected", "--note", "date fixed")[0], 0)
        self.assertEqual(self.rows()["t001"]["status"], "corrected")
        self.assertEqual(self.L("set", "nope", "staged")[0], 2)

    def test_newer_verdict_file_beats_older_event(self):
        self.L("build")
        self.assertEqual(self.L("set", "w-2", "rejected", "--at", "2026-11-17T12:00:00-05:00")[0], 0)
        self.assertEqual(self.rows()["w-2"]["status"], "verified")  # verdict file is dated Nov 18

    def test_add_found_on_staging_row_and_dedupe(self):
        code, out, _ = self.L("add", "w-1", "found", "--found-at", "2026-11-18T09:00:00-05:00")
        self.assertEqual(code, 0)
        r = self.rows()["w-1"]
        self.assertEqual(r["status"], "found")
        self.assertEqual(r["found_at"], "2026-11-18T09:00:00-05:00")
        code, _, err = self.L("add", "w-1", "staged", "--found-at", "2026-11-19T09:00:00-05:00")
        self.assertEqual(code, 0)
        self.assertIn("already recorded", err)
        adds = [e for e in ledger.read_events() if e["row_id"] == "w-1" and e["action"] == "add"]
        self.assertEqual(len(adds), 1)
        self.assertEqual(self.rows()["w-1"]["found_at"], "2026-11-18T09:00:00-05:00")

    def test_add_needs_a_date(self):
        self.assertEqual(self.L("add", "x-9", "found")[0], 2)

    def test_published(self):
        self.L("build")
        self.assertEqual(self.L("published", "t001", "--at", "2026-11-20T11:05:00-05:00", "--pr", "https://example.com/pr/1")[0], 0)
        r = self.rows()["t001"]
        self.assertEqual(r["published_at"], "2026-11-20T11:05:00-05:00")

    def test_verified_unpublished_lists_only_verified_not_live(self):
        code, out, _ = self.L("verified-unpublished")
        self.assertEqual(code, 1)
        ids = [line.split("\t")[0] for line in out.strip().splitlines()[1:]]
        self.assertEqual(ids, ["w-2"])

    def test_bare_invocation_builds(self):
        code, _, _ = self.L()
        self.assertEqual(code, 0)
        self.assertTrue(ledger.LEDGER.is_file())


class LaneTests(Fixture):
    def setUp(self):
        super().setUp()
        ledger.setup(str(self.cfg))

    def test_rule(self):
        ref = ledger.parse_when("2026-11-19T10:00:00-05:00")
        self.assertEqual(ledger.derive_lane("2026-11-05", ref, False), "fresh")   # 14 days
        self.assertEqual(ledger.derive_lane("2026-11-04", ref, False), "backlog")  # 15 days
        self.assertEqual(ledger.derive_lane("2026-11-19", ref, True), "backfill")
        self.assertEqual(ledger.derive_lane("", ref, False), "fresh")

    def test_lanes_in_ledger(self):
        self.L("add", "w-1", "found", "--found-at", "2026-11-19T09:00:00-05:00")
        self.L("add", "old-1", "found", "--date", "2026-10-01", "--found-at", "2026-11-19T09:00:00-05:00")
        self.L("add", "bf-1", "found", "--found-at", "2026-11-19T09:00:00-05:00")
        r = self.rows()
        self.assertEqual(r["w-1"]["lane"], "fresh")
        self.assertEqual(r["old-1"]["lane"], "backlog")
        self.assertEqual(r["bf-1"]["lane"], "backfill")   # row is in the backfill staging file
        self.assertEqual(r["t002"]["lane"], "backfill")   # backfill flag on the live row


class StaleTests(Fixture):
    def test_business_day_clock_fri_to_mon(self):
        ledger.setup(str(self.cfg))
        fri = ledger.parse_when("2026-11-20T09:00:00-05:00")
        self.assertEqual(ledger.business_seconds(fri, ledger.parse_when("2026-11-23T08:59:00-05:00")), 86340)
        self.assertEqual(ledger.business_seconds(ledger.parse_when("2026-11-21T09:00:00-05:00"),
                                                 ledger.parse_when("2026-11-22T20:00:00-05:00")), 0)

    def test_stale_command(self):
        self.L("add", "f-1", "found", "--date", "2026-11-19", "--found-at", "2026-11-20T09:00:00-05:00")
        self.L("add", "f-2", "staged", "--date", "2026-11-19", "--found-at", "2026-11-20T09:00:00-05:00")
        self.L("add", "f-3", "found", "--date", "2026-10-01", "--found-at", "2026-11-20T09:00:00-05:00")  # backlog
        def ids(now):
            code, out, _ = self.L("stale", "--now", now, "--json")
            got = {r["row_id"] for r in json.loads(out)["rows"]}
            return code, {i for i in got if i.startswith("f-")}

        # fixture staging rows were first seen at test time, so only the f- rows are checked
        self.assertEqual(ids("2026-11-23T08:59:00-05:00")[1], set())   # Fri 9 AM -> Mon 8:59 AM: under 1 business day
        code, got = ids("2026-11-23T09:01:00-05:00")
        self.assertEqual(code, 1)
        self.assertEqual(got, {"f-1", "f-2"})   # f-3 is backlog, never stale
        self.L("set", "f-2", "verified", "--at", "2026-11-23T09:00:00-05:00")   # decided items are not stale
        self.assertEqual(ids("2026-11-23T09:01:00-05:00")[1], {"f-1"})
        code, out, _ = self.L("stale", "--now", "2026-11-23T09:01:00-05:00")
        self.assertIn("stale=", out.splitlines()[-1])




class LiveMatchTests(Fixture):
    """A planned-branch row must not be collapsed into a different live trigger
    that happens to share institution, type, date and source URL. A normal
    unpublished row with the same key still matches."""

    SHARED_URL = "https://example.com/opening-and-plan"

    def setUp(self):
        super().setUp()
        # opened branch already live (same key+URL as the planned row below)
        self.write_triggers([
            {"id": "t010", "institution": "Example National Bank", "type": "branch_opening",
             "date": "2026-07-13", "added": "2026-07-13", "fi_only": True,
             "source_url": self.SHARED_URL,
             "summary": "Example National Bank opened a Westside branch on July 13, 2026."},
            {"id": "t011", "institution": "Other State Bank", "type": "merger",
             "date": "2026-11-01", "added": "2026-11-02",
             "source_url": "https://example.com/other-merger",
             "summary": "Other State Bank merged on Nov 1, 2026."},
        ])
        (self.data / "staging.tsv").write_text(
            (self.data / "staging.tsv").read_text()
            + "\t".join([
                "bf-example-branch-planned-2026-07-13", "Example National Bank", "FL",
                "branch_opening", "2026-07-13",
                "Example National Bank plans to open a Downtown branch.",
                self.SHARED_URL, "Pending", "",
            ]) + "\n"
            + "\t".join([
                "w-normal-1", "Other State Bank", "OH", "merger", "2026-11-01",
                "Other State Bank merged.", "https://example.com/other-merger", "Pending", "",
            ]) + "\n")
        (self.data / "verify-batch-2026-11-18.tsv").write_text(
            VERDICT_HEADER
            + "\t".join([
                "bf-example-branch-planned-2026-07-13", "Example National Bank",
                "branch_opening", "2026-07-13", "Pass", "announced plan only", self.SHARED_URL,
            ]) + "\n")

    def test_id_pattern_and_type(self):
        self.assertTrue(ledger.is_planned_branch("bf-example-branch-planned-2026-07-13", ["branch_opening"]))
        self.assertTrue(ledger.is_planned_branch("x-1", ["planned_branch"]))
        self.assertFalse(ledger.is_planned_branch("t010", ["branch_opening"]))
        self.assertFalse(ledger.is_planned_branch("w-normal-1", ["merger"]))

    def test_planned_branch_stays_off_the_other_live_row(self):
        self.L("build")
        r = self.rows()
        planned = r["bf-example-branch-planned-2026-07-13"]
        self.assertEqual(planned["status"], "verified")
        self.assertNotIn("t010", planned.get("source", ""))
        self.assertEqual(r["t010"]["status"], "live")
        self.assertEqual(r["t010"]["source"].split()[0], "triggers.json:t010")
        # a normal row with the same institution+type+date as a live trigger still matches
        self.assertEqual(r["w-normal-1"]["status"], "live")
        self.assertIn("t011", r["w-normal-1"]["source"])
        # set verified must not re-attach it, and the live t-id stays put
        code, _, err = self.L("set", "bf-example-branch-planned-2026-07-13", "verified")
        self.assertEqual(code, 0, err)
        r = self.rows()
        self.assertEqual(r["bf-example-branch-planned-2026-07-13"]["status"], "verified")
        self.assertEqual(r["t010"]["status"], "live")

    def test_verified_unpublished_includes_the_planned_row(self):
        code, out, _ = self.L("verified-unpublished")
        self.assertEqual(code, 1)
        ids = [line.split("\t")[0] for line in out.strip().splitlines()[1:]]
        self.assertIn("bf-example-branch-planned-2026-07-13", ids)
        self.assertNotIn("w-normal-1", ids)
        self.assertNotIn("t010", ids)

class SourceHealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / "source-health.tsv"

    def tearDown(self):
        self.tmp.cleanup()

    def results(self, name, rows):
        p = self.root / name
        p.write_text("source\tstatus\tparsed\tmatched\tqueued\trejected\tdetail\n"
                     + "".join("\t".join(r) + "\n" for r in rows))
        return str(p)

    def run_sweep(self, rows, at, name="r.tsv"):
        return run(source_health.main, ["--results", self.results(name, rows), "--out", str(self.out), "--at", at])

    def test_columns(self):
        self.assertEqual(source_health.COLUMNS, ["sweep_at", "sweep_id", "source", "status", "parsed", "matched",
                                                 "queued", "rejected", "http", "detail", "fail_streak", "flag"])

    def test_fail_two_in_a_row(self):
        ok = ["ncua", "ok", "10", "2", "2", "0", ""]
        code, out, _ = self.run_sweep([["edgar", "fail", "", "", "", "", "timeout"], ok], "2026-11-19T07:00")
        self.assertEqual(code, 0, out)
        code, out, _ = self.run_sweep([["edgar", "000", "", "", "", "", "timeout"], ok], "2026-11-19T09:30")
        self.assertEqual(code, 1)
        self.assertIn("fail_2_in_row edgar", out)
        rows = source_health.read_tsv(self.out)
        self.assertEqual([r["fail_streak"] for r in rows if r["source"] == "edgar"], ["1", "2"])

    def test_recovery_resets_streak(self):
        ok = ["ncua", "ok", "10", "2", "2", "0", ""]
        self.run_sweep([["edgar", "fail", "", "", "", "", ""], ok], "2026-11-18T07:00")
        self.run_sweep([["edgar", "ok", "5", "1", "1", "0", ""], ok], "2026-11-18T17:00")
        code, out, _ = self.run_sweep([["edgar", "fail", "", "", "", "", ""], ok], "2026-11-19T07:00")
        self.assertEqual(code, 0, out)

    def test_weekday_zero_yield(self):
        zero = [["edgar", "ok", "40", "0", "0", "0", ""], ["ncua", "ok", "12", "0", "0", "0", ""]]
        code, out, _ = self.run_sweep(zero, "2026-11-19T07:00")   # Thursday
        self.assertEqual(code, 1)
        self.assertIn("weekday_zero_yield", out)
        code, out, _ = self.run_sweep(zero, "2026-11-21T07:00", "s.tsv")   # Saturday
        self.assertEqual(code, 0, out)
        all_rows = [r for r in source_health.read_tsv(self.out) if r["source"] == "ALL"]
        self.assertEqual(all_rows[0]["flag"], "weekday_zero_yield")

    def test_yield_not_recorded_from_status_dir(self):
        d = self.root / "sweep"
        d.mkdir()
        (d / "e8k-0.status").write_text("200 https://example.com 1.0\n")
        (d / "e8k-40.status").write_text("000 https://example.com 45.0CURL_FAIL\n")
        (d / "fdic.status").write_text("200 https://example.com 0.5\n")
        code, out, _ = run(source_health.main, ["--sweep-dir", str(d), "--out", str(self.out),
                                                "--at", "2026-11-19T07:00"])
        self.assertEqual(code, 1)
        self.assertIn("yield_not_recorded", out)
        rows = {r["source"]: r for r in source_health.read_tsv(self.out)}
        self.assertEqual(rows["e8k"]["status"], "partial")
        self.assertEqual(rows["fdic"]["status"], "ok")

    def test_old_format_file_is_kept(self):
        self.out.write_text("sweep_date\tsource_group\n2026-11-02\tALL\n")
        self.run_sweep([["ncua", "ok", "1", "1", "1", "0", ""]], "2026-11-19T07:00")
        self.assertEqual(source_health.read_tsv(self.out)[0]["source"], "ncua")
        self.assertEqual(len(list(self.root.glob("source-health.pre-*.tsv"))), 1)



class SnapshotPruneTests(Fixture):
    def setUp(self):
        super().setUp()
        (self.data / "publish-log.tsv").write_text(
            "date\tpr_url\tids\tinstitutions\n"
            "2026-11-18\thttps://example.com/pr/1\tt001\tAlpha Bank\n"
            "2026-11-20\thttps://example.com/pr/2\tt010\tExample National Bank\n")
        self.snap = self.data / "snapshots"
        self.snap.mkdir()
        # two sources: "staging" has old, same-day, and newer; "queue" is all older
        self.files = {
            "staging.20261119-095924.tsv": "old staging",
            "staging.20261119-175438.tsv": "also old staging",
            "staging.20261120-065915.tsv": "same day as publish",
            "staging.20261121-000535.tsv": "newest staging",
            "queue.20261119-173806.tsv": "older queue",
            "queue.20261119-193321.tsv": "newest queue, still before publish",
            "queue.20261119-193321-1.tsv": "same-second later queue (newest)",
        }
        for name, text in self.files.items():
            (self.snap / name).write_text(text)

    def names(self, output, section):
        lines = output.splitlines()
        start = next(i for i, l in enumerate(lines) if l.startswith(section))
        out = []
        for l in lines[start + 1:]:
            if l.startswith("  "):
                out.append(l.split()[0])
            elif l and not l.startswith(" "):
                break
        return out

    def test_dry_run_does_not_delete(self):
        code, out, err = self.L("snapshot", "--prune")
        self.assertEqual(code, 0, err)
        self.assertIn("dry run", out)
        self.assertIn("latest publish: 2026-11-20", out)
        kept = self.names(out, "kept")
        drop = self.names(out, "would delete")
        self.assertEqual(kept, [
            "queue.20261119-193321-1.tsv",
            "staging.20261120-065915.tsv",
            "staging.20261121-000535.tsv",
        ])
        self.assertEqual(drop, [
            "queue.20261119-173806.tsv",
            "queue.20261119-193321.tsv",
            "staging.20261119-095924.tsv",
            "staging.20261119-175438.tsv",
        ])
        # newest queue is kept even though it is older than the publish date
        self.assertIn("newest for queue", out)
        self.assertTrue(all((self.snap / n).is_file() for n in self.files))

    def test_yes_deletes_only_the_listed_files(self):
        # dry run first on a copy of the list, then apply
        self.L("snapshot", "--prune")
        code, out, err = self.L("snapshot", "--prune", "--yes")
        self.assertEqual(code, 0, err)
        self.assertIn("deleted (4):", out)
        self.assertFalse((self.snap / "staging.20261119-095924.tsv").exists())
        self.assertFalse((self.snap / "queue.20261119-173806.tsv").exists())
        self.assertTrue((self.snap / "staging.20261121-000535.tsv").is_file())
        self.assertTrue((self.snap / "staging.20261120-065915.tsv").is_file())
        self.assertTrue((self.snap / "queue.20261119-193321-1.tsv").is_file())
        self.assertEqual((self.snap / "staging.20261121-000535.tsv").read_text(), "newest staging")

    def test_yes_without_prune_is_an_error(self):
        code, _, err = self.L("snapshot", "--yes")
        self.assertEqual(code, 2)
        self.assertIn("--yes", err)



if __name__ == "__main__":
    unittest.main(verbosity=1)
