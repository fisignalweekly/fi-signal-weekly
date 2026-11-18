#!/usr/bin/env python3
"""Published-only guarantees for the MCP data bundle. Run: python3 mcp/test/test_bundle.py"""
import json, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import build_bundle as B

ROOT = B.ROOT
SIGNAL_FIELDS = {"id", "type", "type_label", "type_group", "institution", "state", "event_date", "added", "backfill", "summary",
                 "source_url", "fi_id", "fi_name", "charter_type", "assets_usd", "assets_basis", "assets_as_of", "fi_page_url", "board_url"}


class BundleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.read = staticmethod(B.reader(None))
        cls.b = B.build(cls.read)
        cls.src = json.loads(cls.read("data/triggers.json"))["rows"]

    def test_fi_only_rows_never_included(self):
        ids = {s["id"] for s in self.b["signals"]}
        fi_only = [r["id"] for r in self.src if r.get("fi_only") is True or r["type"] == "branch_opening"]
        self.assertTrue(fi_only, "expected fi_only rows in the source to test against")
        self.assertFalse(ids & set(fi_only))
        self.assertNotIn("branch_opening", {t["type"] for t in self.b["types"]})
        self.assertNotIn("branch_opening", {s["type"] for s in self.b["signals"]})

    def test_signal_fields_are_allowlisted(self):
        for s in self.b["signals"]:
            self.assertEqual(set(s), SIGNAL_FIELDS, s["id"])

    def test_every_board_row_is_included(self):
        types, fi_only = B.load_types(self.read("scripts/trigger_types.py"))
        board = {r["id"] for r in self.src if r.get("fi_only") is not True and r["type"] not in fi_only}
        self.assertEqual(board, {s["id"] for s in self.b["signals"]})

    def test_non_public_markers_drop_rows(self):
        types, fi_only = B.load_types(self.read("scripts/trigger_types.py"))
        row = dict(next(r for r in self.src if r["type"] == "merger"))
        self.assertTrue(B.is_public_signal(row, types, fi_only))
        for k in B.NON_PUBLIC_MARKERS:
            self.assertFalse(B.is_public_signal({**row, k: True}, types, fi_only), k)
        self.assertFalse(B.is_public_signal({**row, "type": "branch_opening"}, types, fi_only))
        self.assertFalse(B.is_public_signal({**row, "type": "made_up"}, types, fi_only))

    def test_internal_strings_absent(self):
        text = json.dumps(self.b)
        for needle in ("assets_note", "assets_source", "fi_match", "public_display", "/workspace/"):
            self.assertNotIn(needle, text)

    def test_only_allowlisted_inputs_readable(self):
        with self.assertRaises(ValueError):
            self.read("data/not-an-input.tsv")

    def test_type_order_ma_then_exec(self):
        groups = [t["group"] for t in self.b["types"]]
        self.assertEqual(groups[:5], ["m_and_a"] * 3 + ["executive"] * 2)

    def test_page_paths_match_built_site(self):
        cols = self.b["institutions"]["cols"]
        pi = cols.index("path")
        missing = [r[0] for r in self.b["institutions"]["rows"]
                   if not os.path.exists(os.path.join(ROOT, r[pi].strip("/"), "index.html"))]
        self.assertEqual(missing, [])

    def test_provider_rows_carry_evidence(self):
        for fid, fields in self.b["providers"].items():
            self.assertTrue(set(fields) <= set(B.PROVIDER_FIELDS))
            for rows in fields.values():
                for r in rows:
                    self.assertEqual(set(r), {"value", "status", "source_type", "source_url", "last_updated", "note"})
                    self.assertTrue(r["source_type"])


if __name__ == "__main__":
    unittest.main()
