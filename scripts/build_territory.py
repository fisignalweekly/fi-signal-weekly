#!/usr/bin/env python3
"""Build /territory/ and the Eastern Time HQ lookup used by board and directory filters.

Does not touch build_directory.py or /fi/ pages. Re-run after institutions.csv,
providers.csv, or fi/search.json updates.

Eastern Time is assigned by headquarters city / FDIC HQ county, not by the
branch network. Official split-state county lists:

  IN Central: 49 CFR 71.5
  FL, KY, MI, TN: standard U.S. time-zone county lists (USDOT), as published
  e.g. in the Statoids compilation of U.S. time zones.
"""
from __future__ import annotations

import csv
import html
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS_MIN = 1_400_000_000
CACHE = "20261118territory"
CF_BEACON = """<script type='module' src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "<site_token>"}'></script>
"""

PURE_ET = set("ME NH VT MA RI CT NY NJ PA DE MD DC VA WV NC SC GA OH".split())
# Multi-word counties must stay intact (do not .split() these strings).
FL_CT = {
    "BAY", "CALHOUN", "ESCAMBIA", "HOLMES", "JACKSON", "OKALOOSA",
    "SANTAROSA", "WALTON", "WASHINGTON",
}
IN_CT = {
    "GIBSON", "JASPER", "LAKE", "LAPORTE", "NEWTON", "PERRY", "PORTER",
    "POSEY", "SPENCER", "STARKE", "VANDERBURGH", "WARRICK",
}
KY_CT = {
    "ADAIR", "ALLEN", "BALLARD", "BARREN", "BRECKINRIDGE", "BUTLER",
    "CALDWELL", "CALLOWAY", "CARLISLE", "CHRISTIAN", "CLINTON",
    "CRITTENDEN", "CUMBERLAND", "DAVIESS", "EDMONSON", "FULTON", "GRAVES",
    "GRAYSON", "GREEN", "HANCOCK", "HART", "HENDERSON", "HICKMAN",
    "HOPKINS", "LIVINGSTON", "LOGAN", "LYON", "MARSHALL", "MCCRACKEN",
    "MCLEAN", "METCALFE", "MONROE", "MUHLENBERG", "OHIO", "RUSSELL",
    "SIMPSON", "TODD", "TRIGG", "UNION", "WARREN", "WEBSTER",
}
MI_CT = {"DICKINSON", "GOGEBIC", "IRON", "MENOMINEE"}
TN_ET = {
    "ANDERSON", "BLOUNT", "BRADLEY", "CAMPBELL", "CARTER", "CLAIBORNE",
    "COCKE", "GRAINGER", "GREENE", "HAMBLEN", "HAMILTON", "HANCOCK",
    "HAWKINS", "JEFFERSON", "JOHNSON", "KNOX", "LOUDON", "MCMINN", "MEIGS",
    "MONROE", "MORGAN", "POLK", "RHEA", "ROANE", "SCOTT", "SEVIER",
    "SULLIVAN", "UNICOI", "UNION", "WASHINGTON",
}

ST_NAME = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "PR": "Puerto Rico", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "VI": "U.S. Virgin Islands",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def norm_county(s: str) -> str:
    s = (s or "").upper().replace(".", "").replace("'", "").replace("-", "")
    s = re.sub(r"\s+COUNTY$", "", s.strip())
    return re.sub(r"\s+", "", s)


def slugify(s: str) -> str:
    s = s.lower().replace("&", " and ").replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "fi"


def money(usd) -> str:
    if usd is None or usd == "":
        return "Assets not reported"
    usd = int(usd)
    b, m = usd / 1e9, usd / 1e6
    if b >= 1:
        t = f"{b:.0f}" if b >= 100 else f"{b:.1f}"
        return "$" + re.sub(r"\.0$", "", t) + "B"
    t = f"{m:.0f}" if m >= 10 else f"{m:.1f}"
    return "$" + re.sub(r"\.0$", "", t) + "M"


def assets_of(r) -> int:
    try:
        return int(r["total_assets"] or 0)
    except (TypeError, ValueError):
        return 0


def load_counties() -> dict[str, dict]:
    raw = json.loads((ROOT / "data/fdic-hq-counties-split.json").read_text())
    return {str(d["cert"]): d for d in raw}


def tz_for_bank(r, counties: dict) -> str | None:
    """Return 'ET' or None (not Eastern). HQ city / FDIC county, not branches."""
    st = r["state"]
    if st in ("PR", "VI"):
        return None
    if st in PURE_ET:
        return "ET"
    if st not in ("FL", "IN", "KY", "MI", "TN"):
        return None
    if not r["id"].startswith("fdic-"):
        return None
    rec = counties.get(r["id"].split("-", 1)[1])
    if not rec:
        raise SystemExit(f"missing FDIC HQ county for {r['id']} {r['name']} {r['city']} {st}")
    nc = norm_county(rec["county"])
    if st == "FL":
        if nc == "GULF":
            raise SystemExit(f"Gulf County FL is split; classify by hand: {r['id']} {r['name']}")
        return "ET" if nc not in FL_CT else None
    if st == "IN":
        return "ET" if nc not in IN_CT else None
    if st == "KY":
        return "ET" if nc not in KY_CT else None
    if st == "MI":
        return "ET" if nc not in MI_CT else None
    if st == "TN":
        return "ET" if nc in TN_ET else None
    return None


def load_institutions():
    with (ROOT / "data/institutions.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_providers() -> dict[str, list[str]]:
    """Current retail digital values, in file order, for each fi_id."""
    out = defaultdict(list)
    path = ROOT / "data/providers.csv"
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["field"] != "digital" or r["status"] != "current":
                continue
            val = (r["value"] or "").strip()
            if not val or val.lower() in ("not yet identified", "unknown", "n/a"):
                continue
            if val not in out[r["fi_id"]]:
                out[r["fi_id"]].append(val)
    return out


def assign_slugs(inst):
    """Same uniqueness rule as scripts/build_directory.py: name, then name-city, then name-city-<id>."""
    groups = defaultdict(list)
    for x in inst:
        base = slugify(x["name"])
        if x["charter_type"] == "cu" and not re.search(r"(^|-)(cu|fcu|credit-union|federal-credit-union)$", base):
            base += "-cu"
        groups[(x["state"].lower(), base)].append(x)
    used = {k for k, xs in groups.items() if len(xs) == 1}
    for (st, base), xs in sorted(groups.items()):
        cities = defaultdict(int)
        for x in xs:
            cities[slugify(x["city"])] += 1
        for x in xs:
            if len(xs) == 1:
                s = base
            else:
                s = f"{base}-{slugify(x['city'])}"
                if cities[slugify(x["city"])] > 1 or (st, s) in used:
                    s = f"{s}-{x['id'].split('-')[1]}"
                used.add((st, s))
            x["_slug"] = s
            x["_path"] = f"{st}/{s}"


def build():
    counties = load_counties()
    inst = load_institutions()
    assign_slugs(inst)
    providers = load_providers()

    et_banks = []
    for r in inst:
        if r["charter_type"] != "bank":
            continue
        if tz_for_bank(r, counties) != "ET":
            continue
        path = r["_path"]
        et_banks.append({
            "id": r["id"],
            "name": r["name"],
            "city": r["city"],
            "state": r["state"],
            "assets": assets_of(r),
            "assets_as_of": r.get("assets_as_of") or "",
            "path": path,
            "digital": providers.get(r["id"]) or [],
        })

    listed = [b for b in et_banks if b["assets"] > ASSETS_MIN]
    listed.sort(key=lambda b: (b["state"], b["city"].lower(), -b["assets"], b["name"].lower()))
    et_banks.sort(key=lambda b: b["id"])

    as_of = Counter_as_of(listed)
    write_js(et_banks)
    write_json(et_banks, listed, as_of)
    write_html(listed, as_of)
    print(f"ET banks (any size): {len(et_banks)}")
    print(f"ET banks with assets > $1.4B: {len(listed)}")
    print(f"wrote territory/index.html, js/territory-et.js, data/territory-et.json")


def Counter_as_of(listed):
    counts = defaultdict(int)
    for b in listed:
        counts[b["assets_as_of"] or "unknown"] += 1
    return dict(counts)


def write_js(et_banks):
    ids = {b["id"]: 1 for b in et_banks}
    paths = {b["path"]: 1 for b in et_banks}
    body = "window.FI_TERRITORY=" + json.dumps({"ids": ids, "paths": paths}, separators=(",", ":")) + ";\n"
    (ROOT / "js/territory-et.js").write_text(body, encoding="utf-8")


def write_json(et_banks, listed, as_of):
    payload = {
        "rule": "Banks only, Eastern Time by headquarters city, assets strictly above $1.4 billion.",
        "assets_min": ASSETS_MIN,
        "assets_as_of": as_of,
        "et_bank_count": len(et_banks),
        "listed_count": len(listed),
        "listed": [
            {
                "id": b["id"],
                "name": b["name"],
                "city": b["city"],
                "state": b["state"],
                "assets": b["assets"],
                "path": "/fi/" + b["path"] + "/",
                "digital": b["digital"],
            }
            for b in listed
        ],
    }
    (ROOT / "data/territory-et.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_html(listed, as_of):
    n = len(listed)
    as_of_label = as_of_text(as_of)
    # Group: state -> city -> banks (already sorted)
    by_state = defaultdict(lambda: defaultdict(list))
    for b in listed:
        by_state[b["state"]][b["city"]].append(b)
    states = sorted(by_state)

    jump = []
    for st in states:
        jump.append(f'<a href="#st-{st.lower()}">{html.escape(st)}</a>')

    sections = []
    for st in states:
        cities = by_state[st]
        n_st = sum(len(v) for v in cities.values())
        city_names = sorted(cities, key=str.lower)
        sections.append(f'<section id="st-{html.escape(st.lower())}" class="terr-state">')
        sections.append(
            f'<h2 class="state">{html.escape(ST_NAME.get(st, st))} <span>{n_st}</span></h2>'
        )
        for city in city_names:
            banks = cities[city]
            sections.append(f'<h3 class="city">{html.escape(city)}, {html.escape(st)}</h3>')
            sections.append('<ul class="fi-list">')
            for b in banks:
                href = "/fi/" + b["path"] + "/"
                prov = "; ".join(b["digital"]) if b["digital"] else "Not yet identified"
                meta = f'{html.escape(money(b["assets"]))} · {html.escape(st)} · {html.escape(prov)}'
                sections.append(
                    "<li><a href=\"" + html.escape(href, quote=True) + "\">"
                    f'<span class="nm">{html.escape(b["name"])}</span>'
                    f'<span class="sub">{meta}</span></a></li>'
                )
            sections.append("</ul>")
        sections.append("</section>")

    board_q = "/?charter=bank&amp;tz=et&amp;assets_min=1400000000"
    dir_q = "/fi/?charter=bank&amp;tz=et&amp;assets_min=1400000000"

    page = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Eastern Time banks above $1.4 billion — FI Signal Weekly</title>
<meta name="description" content="A territory test list of {n} US banks with total assets above $1.4 billion and an Eastern Time headquarters, grouped by HQ city.">
<meta name="robots" content="noindex,nofollow">
<meta property="og:type" content="website">
<meta property="og:site_name" content="FI Signal Weekly">
<meta property="og:title" content="Eastern Time banks above $1.4 billion — FI Signal Weekly">
<meta property="og:description" content="A territory test list of {n} US banks with total assets above $1.4 billion and an Eastern Time headquarters, grouped by HQ city.">
<meta property="og:url" content="https://fisignalweekly.com/territory/">
<meta property="og:image" content="https://fisignalweekly.com/img/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="FI Signal Weekly: buying-window signals at US banks &amp; credit unions">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Eastern Time banks above $1.4 billion — FI Signal Weekly">
<meta name="twitter:description" content="A territory test list of {n} US banks with total assets above $1.4 billion and an Eastern Time headquarters, grouped by HQ city.">
<meta name="twitter:image" content="https://fisignalweekly.com/img/og-image.png">
<meta name="twitter:image:alt" content="FI Signal Weekly: buying-window signals at US banks &amp; credit unions">
<meta name="theme-color" content="#000F26">
<link rel="canonical" href="https://fisignalweekly.com/territory/">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="/img/favicon-32.png">
<link rel="icon" type="image/png" sizes="16x16" href="/img/favicon-16.png">
<link rel="icon" type="image/png" sizes="192x192" href="/img/mark-192.png">
<link rel="apple-touch-icon" sizes="180x180" href="/img/apple-touch-icon.png">
<meta name="twitter:site" content="@FISignalWeekly">
<meta name="twitter:creator" content="@FISignalWeekly">
<link rel="stylesheet" href="/css/style.css?v={CACHE}">
</head><body>
<header class="site"><div class="wrap">
  <a class="logo" href="/"><img class="mark" src="/img/mark-64.png" width="32" height="32" alt="">FI Signal <span>Weekly</span></a>
  <nav><a href="/#board">Board</a><a class="nav-dir" href="/fi/">Directory</a><a class="nav-opt" href="/about.html">About</a><a class="follow-x" href="https://x.com/FISignalWeekly" target="_blank" rel="noopener" aria-label="Follow @FISignalWeekly on X"><svg class="x-icon" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false"><path fill="currentColor" d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg><span class="fx-text">Follow @FISignalWeekly</span></a></nav>
</div></header>
<main class="wrap terr">
  <header class="hero">
    <h1>Eastern Time banks above $1.4 billion</h1>
    <p class="count">{n} banks. A static territory test: banks only, assets strictly above $1.4 billion, Eastern Time by headquarters city.</p>
  </header>

  <section class="rule" aria-labelledby="rule-h">
    <h2 id="rule-h">The rule we used</h2>
    <p>Credit unions are not on this list. Asset sizes come from the FDIC call report ({html.escape(as_of_label)}). None of the banks in the file have assets of exactly $1.4 billion, so “above $1.4 billion” and a floor of $1,400,000,000 are the same set today.</p>
    <p>Eastern Time is based on the bank’s headquarters city, not its branch network.</p>
    <ul>
      <li><strong>Entirely Eastern Time:</strong> Connecticut, Delaware, Georgia, Maine, Maryland, Massachusetts, New Hampshire, New Jersey, New York, North Carolina, Ohio, Pennsylvania, Rhode Island, South Carolina, Vermont, Virginia, West Virginia, and the District of Columbia.</li>
      <li><strong>Florida, Indiana, Kentucky, Michigan, and Tennessee</strong> are split. For those states we use the bank’s FDIC headquarters county, as follows.
        <ul>
          <li><strong>Florida:</strong> Eastern, except the western panhandle counties of Bay, Calhoun, Escambia, Holmes, Jackson, Okaloosa, Santa Rosa, Walton, and Washington (Central). No bank on this list is headquartered in Gulf County, which is split.</li>
          <li><strong>Indiana:</strong> Eastern, except Gibson, Jasper, Lake, LaPorte, Newton, Perry, Porter, Posey, Spencer, Starke, Vanderburgh, and Warrick counties (Central), per 49 CFR 71.5. The city of Jasper is in Dubois County and is Eastern; Jasper County is Central.</li>
          <li><strong>Kentucky:</strong> Eastern, except these 41 western counties, which are Central: Adair, Allen, Ballard, Barren, Breckinridge, Butler, Caldwell, Calloway, Carlisle, Christian, Clinton, Crittenden, Cumberland, Daviess, Edmonson, Fulton, Graves, Grayson, Green, Hancock, Hart, Henderson, Hickman, Hopkins, Livingston, Logan, Lyon, Marshall, McCracken, McLean, Metcalfe, Monroe, Muhlenberg, Ohio, Russell, Simpson, Todd, Trigg, Union, Warren, and Webster.</li>
          <li><strong>Michigan:</strong> Eastern, except Dickinson, Gogebic, Iron, and Menominee counties in the western Upper Peninsula (Central).</li>
          <li><strong>Tennessee:</strong> Eastern only in these 30 counties: Anderson, Blount, Bradley, Campbell, Carter, Claiborne, Cocke, Grainger, Greene, Hamblen, Hamilton, Hancock, Hawkins, Jefferson, Johnson, Knox, Loudon, McMinn, Meigs, Monroe, Morgan, Polk, Rhea, Roane, Scott, Sevier, Sullivan, Unicoi, Union, and Washington. Nashville, Memphis, and the rest of the state are Central.</li>
        </ul>
      </li>
      <li><strong>Puerto Rico and the U.S. Virgin Islands</strong> use Atlantic Time and are not on this list.</li>
    </ul>
    <p>The digital provider shown on each row is the current retail value from our login-page scan, when we have one. It is not a core-system field. “Not yet identified” means we have not published a current retail provider for that bank.</p>
    <p>The same filter works as a URL on the <a href="{board_q}">board</a> and in the <a href="{dir_q}">directory</a>: <code>?charter=bank&amp;tz=et&amp;assets_min=1400000000</code>.</p>
  </section>

  <nav class="terr-jump" aria-label="Jump to a state">{"".join(jump)}</nav>

  {"".join(sections)}
</main>
<footer><div class="wrap">FI Signal Weekly · Institution data from FDIC BankFind and NCUA call reports; digital providers from public login-page scans. Verify before acting. Not affiliated with any regulator or vendor. · <a href="/">Board</a> · <a href="/fi/">Directory</a> · <a href="/about.html">About</a> · <a href="/#subscribe">Friday digest</a> · <a class="follow-x" href="https://x.com/FISignalWeekly" target="_blank" rel="noopener">Follow @FISignalWeekly</a></div></footer>
{CF_BEACON}</body></html>
"""
    (ROOT / "territory/index.html").write_text(page, encoding="utf-8")


def as_of_text(as_of: dict) -> str:
    # e.g. {"2026Q2": 339} -> "2026 Q2"
    items = sorted(as_of.items(), key=lambda kv: -kv[1])
    parts = []
    for k, n in items:
        if re.match(r"^\d{4}Q[1-4]$", k or ""):
            label = f"{k[:4]} Q{k[-1]}"
        else:
            label = k or "unknown date"
        parts.append(label if len(items) == 1 else f"{label} ({n})")
    return ", ".join(parts)


if __name__ == "__main__":
    build()
