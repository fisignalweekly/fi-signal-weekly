#!/usr/bin/env python3
"""Board must never carry fi-only rows (branch_opening / fi_only: true). Run: python3 scripts/test_board_rows.py

Checks the live triggers.json and synthetic rows against both filters (scripts/trigger_types.is_board_row and
js/boardrows.js via node), that index.html has no branch_opening filter option, and that the built sitemap /
fi/linked.json only count board rows."""
import json, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from trigger_types import is_board_row, FI_ONLY_TYPES
rows = json.load(open(os.path.join(ROOT, "data", "triggers.json")))["rows"]
synthetic = [{"id": "x1", "type": "branch_opening", "fi_only": True}, {"id": "x2", "type": "branch_opening"},
             {"id": "x3", "type": "executive", "fi_only": True}, {"id": "x4", "type": "executive"}, {"id": "x5", "type": "merger", "fi_only": False}]
allrows = rows + synthetic
py = [r["id"] for r in allrows if is_board_row(r)]
js = json.loads(subprocess.check_output(["node", "-e",
    "var b=require(process.argv[1]);var rows=JSON.parse(require('fs').readFileSync(0,'utf8'));"
    "console.log(JSON.stringify(b.boardRows(rows).map(function(r){return r.id})))", os.path.join(ROOT, "js", "boardrows.js")],
    input=json.dumps(allrows).encode()))
assert py == js, "python and js board filters disagree"
board = [r for r in allrows if r["id"] in set(py)]
assert not any(r["type"] in FI_ONLY_TYPES or r.get("fi_only") is True for r in board), "fi-only row on the board"
assert {"x4", "x5"} <= set(py) and not {"x1", "x2", "x3"} & set(py), "synthetic rows filtered wrong"
idx = open(os.path.join(ROOT, "index.html")).read()
assert 'value="branch_opening"' not in idx and "js/boardrows.js" in idx and idx.index("js/boardrows.js") < idx.index("js/app.js"), "index.html wiring"
assert "FIBoard.boardRows(data.rows)" in open(os.path.join(ROOT, "js", "app.js")).read(), "app.js must filter with FIBoard.boardRows"
fi_only_ids = {r.get("fi_id") for r in rows if not is_board_row(r)} - {r.get("fi_id") for r in rows if is_board_row(r)}
linked = json.load(open(os.path.join(ROOT, "fi", "linked.json")))
assert not (fi_only_ids & set(linked)), "an FI with only fi-only rows is in fi/linked.json"
print(f"ok: {len(rows)} live rows, {sum(1 for r in rows if is_board_row(r))} on the board, 0 branch_opening / fi_only rows on the board")
