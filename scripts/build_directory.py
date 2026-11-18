#!/usr/bin/env python3
"""Build the public FI directory: static pages under fi/ plus sitemap.xml and robots.txt.

    python3 scripts/build_directory.py           # write fi/, sitemap.xml, robots.txt (re-runnable)
    python3 scripts/build_directory.py --check   # exit 3 if anything would change (no write)

Inputs (nothing else, no network):
  data/institutions.json  every active FDIC bank and NCUA credit union (scripts/build_fi_db.py)
  data/triggers.json      board rows; a row belongs to an institution through its fi_id (scripts/link_institutions.py)
  data/providers.csv      core and digital banking provider evidence per institution (data/README-providers.md)
  data/callreports.json   FDIC/NCUA call report history, offices, members, FDIC history events (scripts/fetch_callreports.py)

Outputs:
  fi/index.html                     directory landing page with client-side search (js/fi-search.js)
  fi/search.json                    compact search index for every institution
  fi/linked.json                    fi_id -> page path for institutions with signals (the board links names with it)
  fi/<st>/index.html                one index page per state / territory
  fi/<st>/<slug>/index.html         one page per institution
  fi/assets/<tier>/index.html       one index page per asset tier (same tiers as the board filter)
  sitemap.xml, robots.txt

Pages for institutions with no signals get <meta name="robots" content="noindex,follow"> and stay out of
sitemap.xml. Output has no timestamps and is sorted, so unchanged data gives byte-identical files; files under
fi/ that the build no longer produces (e.g. an institution that merged away) are deleted.
Exit codes: 0 ok, 1 bad input, 3 (--check only) output is out of date.
"""
import argparse, csv, hashlib, html, json, math, os, re, sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://fisignalweekly.com"
OUT = "fi"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trigger_types import TYPES as TYPE_LABEL  # one list of board types and labels
import fi_sections as S
TIERS = [("lt500m", "Under $500M", 0, 5e8), ("500m-1b", "$500M–$1B", 5e8, 1e9), ("1b-10b", "$1B–$10B", 1e9, 1e10),
         ("10b-50b", "$10B–$50B", 1e10, 5e10), ("50b+", "$50B+", 5e10, float("inf")), ("na", "Assets not reported", None, None)]
TIER_LIST_MAX = 1500   # tiers bigger than this list the largest TIER_TOP plus everything with signals, then link to search
TIER_TOP = 300
STATES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
          "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
          "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
          "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
          "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
          "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
          "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
          "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
          "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
          "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico", "VI": "US Virgin Islands",
          "GU": "Guam", "AS": "American Samoa", "MP": "Northern Mariana Islands", "FM": "Micronesia",
          "MH": "Marshall Islands", "PW": "Palau"}
# FDIC BKCLASS and NCUA charter types, worded from the regulators' own definitions
CLASS_LABEL = {"N": "National bank (OCC)", "NM": "State-chartered bank, not a Fed member (FDIC)",
               "SM": "State-chartered bank, Fed member (Federal Reserve)", "SB": "Federal savings bank (OCC)",
               "SI": "State-chartered savings bank (FDIC)", "SL": "State-chartered savings and loan (FDIC)",
               "SA": "Savings association", "OI": "Insured US branch of a foreign bank",
               "NC": "Non-insured bank or trust company",
               "FCU": "Federal credit union", "FISCU": "Federally insured, state-chartered credit union",
               "NFICU": "Privately insured, state-chartered credit union"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December"]

e = lambda s: html.escape(str(s), quote=True)


def slugify(s):
    s = s.lower().replace("&", " and ").replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "fi"


def money(usd):
    if usd is None or usd == "":
        return None
    b, m = usd / 1e9, usd / 1e6
    if b >= 1:
        t = f"{b:.0f}" if b >= 100 else f"{b:.1f}"
        return "$" + re.sub(r"\.0$", "", t) + "B"
    t = f"{m:.0f}" if m >= 10 else f"{m:.1f}"
    return "$" + re.sub(r"\.0$", "", t) + "M"


def fmt_date(d, long=False):
    y, m, dd = d.split("-")
    return f"{(MONTHS_LONG if long else MONTHS)[int(m) - 1]} {int(dd)}, {y}"


def tier_of(usd):
    if usd is None or usd == "":
        return "na"
    for k, _, lo, hi in TIERS:
        if lo is not None and lo <= usd < hi:
            return k
    return "na"


def charter_word(x):
    return "credit union" if x["charter_type"] == "cu" else "bank"


def website_href(w):
    w = (w or "").strip()
    if not w:
        return None
    return w if re.match(r"https?://", w, re.I) else "http://" + w


def record_link(x):
    num = x["id"].split("-", 1)[1]
    if x["charter_type"] == "bank":
        return f"https://banks.data.fdic.gov/bankfind-suite/bankfind/details/{num}", f"FDIC BankFind record (CERT {num})"
    return f"https://mapping.ncua.gov/CreditUnionDetails/{num}", f"NCUA record (charter {num})"


def asset_hash():
    h = hashlib.sha1()
    for p in ("css/style.css", "css/fi-v2.css", "js/fi-search.js", "js/fi-chart.js"):
        with open(os.path.join(ROOT, p), "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:10]


# ---------------------------------------------------------------- page shell
def page(title, desc, path, body, noindex=False, extra_head="", scripts=""):
    url = SITE + path
    robots = '<meta name="robots" content="noindex,follow">\n' if noindex else ""
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
{robots}<link rel="canonical" href="{e(url)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="FI Signal Weekly">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(url)}">
<meta property="og:image" content="{SITE}/img/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="FI Signal Weekly: buying-window signals at US banks &amp; credit unions">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@FISignalWeekly">
<meta name="twitter:title" content="{e(title)}">
<meta name="twitter:description" content="{e(desc)}">
<meta name="twitter:image" content="{SITE}/img/og-image.png">
<meta name="theme-color" content="#000F26">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="/img/favicon-32.png">
<link rel="apple-touch-icon" sizes="180x180" href="/img/apple-touch-icon.png">
<link rel="stylesheet" href="/css/style.css?v={V}">{extra_head}
</head><body class="dir">
<header class="site"><div class="wrap">
  <a class="logo" href="/"><img class="mark" src="/img/mark-64.png" width="32" height="32" alt="">FI Signal <span>Weekly</span></a>
  <nav><a href="/#board">Board</a><a class="nav-dir" href="/fi/">Directory</a><a class="nav-opt" href="/about.html">About</a><a class="follow-x" href="https://x.com/FISignalWeekly" target="_blank" rel="noopener" aria-label="Follow @FISignalWeekly on X"><svg class="x-icon" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false"><path fill="currentColor" d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg><span class="fx-text">Follow @FISignalWeekly</span></a></nav>
</div></header>
<main class="wrap">
{body}
</main>
<footer><div class="wrap">FI Signal Weekly · Institution data from FDIC BankFind and NCUA call reports; signals from public sources. Verify before acting. Not affiliated with any regulator or vendor. · <a href="/">Board</a> · <a href="/fi/">Directory</a> · <a href="/about.html">About</a> · <a href="/#subscribe">Friday digest</a> · <a class="follow-x" href="https://x.com/FISignalWeekly" target="_blank" rel="noopener">Follow @FISignalWeekly</a></div></footer>
{scripts}</body></html>
"""


def crumbs(items):
    parts = []
    for label, href in items:
        parts.append(f'<a href="{e(href)}">{e(label)}</a>' if href else f'<span aria-current="page">{e(label)}</span>')
    return '<nav class="crumbs" aria-label="Breadcrumb">' + '<span class="sep" aria-hidden="true">›</span>'.join(parts) + "</nav>"


def fi_li(x, show_state=False):
    a = money(x["total_assets"])
    bits = [e(x["city"]) + (", " + e(x["state"]) if show_state else ""), "Credit union" if x["charter_type"] == "cu" else "Bank"]
    if a:
        bits.append(e(a))
    sig = f'<span class="sigs">{x["_n"]} signal{"s" if x["_n"] != 1 else ""}</span>' if x["_n"] else ""
    return (f'<li><a href="{e(x["_path"])}"><span class="nm">{e(x["name"])}</span>{sig}'
            f'<span class="sub">{" · ".join(bits)}</span></a></li>')


def sig_li(r, show_inst=False):
    inst = f'<span class="sig-inst">{e(r["institution"])}</span>' if show_inst else ""
    return (f'<li class="sig {e(r["type"])}"><div class="meta"><span class="badge {e(r["type"])}">{e(TYPE_LABEL.get(r["type"], r["type"]))}</span>'
            f'<span>{fmt_date(r["date"])}</span></div>{inst}<p>{e(r["summary"])}</p>'
            f'<p class="sig-links"><a href="/#{e(r["id"])}">See on the board</a><a href="{e(r["source_url"])}" target="_blank" rel="noopener noreferrer">Source ↗</a></p></li>')


# ---------------------------------------------------------------- providers (data/providers.csv)
PROV_FIELDS = [("digital", "Digital banking (retail)"), ("digital_business", "Digital banking (business)"),
               ("core", "Core provider"), ("billpay", "Bill pay provider")]


def load_providers():
    """fi_id -> field -> list of rows. See data/README-providers.md."""
    out = defaultdict(lambda: defaultdict(list))
    p = os.path.join(ROOT, "data", "providers.csv")
    if not os.path.exists(p):
        return out
    with open(p, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["fi_id"]][r["field"]].append(r)
    return out


def resolve_provider(rows):
    """(shown row, earlier current row it replaces or None). A verified announced change wins over the current
    value unless a later current row already shows the new value (the change has happened)."""
    cur = sorted((r for r in rows if r["status"] == "current"), key=lambda r: (r["last_updated"], r["source_type"] != "Login page scan"), reverse=True)
    ann = sorted((r for r in rows if r["status"] == "announced"), key=lambda r: r["last_updated"], reverse=True)
    if ann:
        a = ann[0]
        if not any(c["value"] == a["value"] and c["last_updated"] >= a["last_updated"] for c in cur):
            old = next((c for c in cur if c["value"] != a["value"]), None)
            return a, old
    return (cur[0], None) if cur else (None, None)


def provider_block(x, prov, board_by_url):
    items = []
    for field, label in PROV_FIELDS:
        shown, old = resolve_provider(prov.get(x["id"], {}).get(field, []))
        if not shown:
            why = ("No separate business login identified." if field == "digital_business" else
                   "No verified public source yet." if field in ("core", "billpay") else "No login platform identified yet.")
            items.append(f'<div class="prov-item prov-empty"><h3>{label}</h3><p class="prov-val prov-none">Not yet identified</p>'
                         f'<p class="prov-meta">{why}</p></div>')
            continue
        val = e(shown["value"])
        if shown["status"] == "announced":
            val += f' <span class="prov-when">(announced {fmt_date(shown["last_updated"])})</span>'
        note = shown["note"].strip()
        note_html = f'<p class="prov-note">{e(note[:1].upper() + note[1:])}</p>' if note else ""
        links = []
        if shown["source_url"]:
            links.append(f'<a href="{e(shown["source_url"])}" target="_blank" rel="noopener nofollow">'
                         f'{"Page scanned" if shown["source_type"] == "Login page scan" else "Source"} ↗</a>')
        sig = board_by_url.get((x["id"], shown["source_url"]))
        if sig:
            links.append(f'<a href="/#{e(sig)}">See the signal</a>')
        was = (f'<p class="prov-was">Before the change: {e(old["value"])} <span class="muted-inline">({e(old["source_type"].lower())}, '
               f'{fmt_date(old["last_updated"])})</span></p>') if old else ""
        cls = "prov-item prov-chg" if shown["status"] == "announced" else "prov-item"
        items.append(f'<div class="{cls}"><h3>{label}</h3><p class="prov-val">{val}</p>'
                     f'<p class="prov-meta">Updated {fmt_date(shown["last_updated"])} · {e(shown["source_type"])}</p>{note_html}{was}'
                     + (f'<p class="prov-links">{"".join(links)}</p>' if links else "") + "</div>")
    return ('<section class="prov" aria-labelledby="prov-h"><h2 id="prov-h">Technology stack</h2>'
            f'<div class="prov-grid">{"".join(items)}</div>'
            '<p class="note prov-how">Core and bill pay come only from verified public announcements. Digital banking comes from a scan of the '
            'online banking login links on the institution&#39;s public website (hostname and DNS), or from a verified announcement; '
            'a business login is shown separately only when it sits on its own business or treasury hostname. '
            'Announced changes are shown in place of the current value. We never infer one field from another.</p></section>')


# ---------------------------------------------------------------- builders
def build(files):
    db = json.load(open(os.path.join(ROOT, "data", "institutions.json")))
    trig = json.load(open(os.path.join(ROOT, "data", "triggers.json")))
    cols = db["columns"]
    inst = sorted((dict(zip(cols, r)) for r in db["rows"]), key=lambda x: (x["charter_type"], int(x["id"].split("-")[1])))
    by_id = {x["id"]: x for x in inst}
    sigs = defaultdict(list)
    for r in trig["rows"]:
        if r.get("fi_id") in by_id:
            sigs[r["fi_id"]].append(r)
    for k in sigs:
        sigs[k].sort(key=lambda r: (r["date"], r["id"]), reverse=True)
    prov = load_providers()
    crj = json.load(open(os.path.join(ROOT, "data", "callreports.json")))
    CR, QS, AS_OF = crj["fi"], crj["quarters"], crj["as_of"]
    SHOWCASE = S.load_showcase(ROOT)  # showcase pages get SHOWCASE_ONLY features first (S.feature_on)
    social = {}
    sp = os.path.join(ROOT, "data", "social.csv")
    if os.path.exists(sp):
        with open(sp, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                social.setdefault(r["fi_id"], {})[r["network"]] = r
    board_by_url = {(r["fi_id"], r["source_url"]): r["id"] for r in trig["rows"] if r.get("fi_id")}

    # slugs: name, then name-city, then name-city-<number>, unique within a state
    groups = defaultdict(list)
    for x in inst:
        base = slugify(x["name"])
        # NCUA names drop "Credit Union" ("Chartway"); add "-cu" so the path says what it is
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
            x["_path"] = f"/fi/{st}/{s}/"
            x["_slug"] = s
            x["_n"] = len(sigs.get(x["id"], []))
            x["_tier"] = tier_of(x["total_assets"])
    by_assets = lambda x: (-(x["total_assets"] if x["total_assets"] != "" else -1), x["name"])
    tier_name = dict((t[0], t[1]) for t in TIERS)

    # peer ranks: by total assets among the same charter type in the state and in the asset tier; 1-year asset growth in the tier
    def yoy(x):
        a = CR.get(x["id"], {}).get("a") or []
        return S.pct(a[-1], a[-5]) if len(a) >= 5 else None
    st_groups, tier_groups = defaultdict(list), defaultdict(list)
    for x in inst:
        if x["total_assets"] != "":
            st_groups[(x["state"], x["charter_type"])].append(x)
            tier_groups[(x["_tier"], x["charter_type"])].append(x)
    for g in list(st_groups.values()) + list(tier_groups.values()):
        g.sort(key=by_assets)
    rank_st = {x["id"]: (i + 1, len(g)) for g in st_groups.values() for i, x in enumerate(g)}
    rank_tier = {x["id"]: (i + 1, len(g)) for g in tier_groups.values() for i, x in enumerate(g)}
    rank_gr = {}
    for (tk, ct), g in tier_groups.items():
        gg = sorted(((yoy(x), x) for x in g if yoy(x) is not None), key=lambda t: (-t[0], t[1]["name"]))
        for i, (p_, x) in enumerate(gg):
            rank_gr[x["id"]] = (i + 1, len(gg), p_)

    def scan_vendor(x):
        rows_ = [r for r in prov.get(x["id"], {}).get("digital", []) if r["source_type"] == "Login page scan"]
        return rows_[0]["value"] if rows_ else ""
    sim_groups = defaultdict(list)
    for x in inst:
        if x["total_assets"] != "":
            sim_groups[(x["state"], x["_tier"], scan_vendor(x))].append(x)

    def similar(x):
        if x["total_assets"] == "":
            return [], ""
        v = scan_vendor(x)
        pool = [y for y in sim_groups[(x["state"], x["_tier"], v)] if y["id"] != x["id"]]
        if not pool and v:  # nobody else on that platform here: fall back to state + tier, said plainly on the page
            v = ""
            pool = [y for k_, ys in sim_groups.items() if k_[:2] == (x["state"], x["_tier"]) for y in ys if y["id"] != x["id"]]
        la = math.log(max(x["total_assets"], 1))
        pool.sort(key=lambda y: (abs(math.log(max(y["total_assets"], 1)) - la), y["name"]))
        return pool[:6], v

    # institution pages
    for x in inst:
        rows = sigs.get(x["id"], [])
        st_name = STATES.get(x["state"], x["state"])
        cw = charter_word(x)
        a = money(x["total_assets"])
        board_names = sorted({r["institution"].split(" / ")[0].strip() for r in rows} - {x["name"]})
        facts = [("Type", ("Credit union" if x["charter_type"] == "cu" else "Bank") + " · " + e(CLASS_LABEL.get(x["charter_class"], x["charter_class"]))),
                 ("Main office", e(f'{x["city"]}, {x["state"]}'))]
        if a:
            facts.append(("Total assets", f'{a} <span class="muted-inline">(${x["total_assets"]:,}, call report {e(x["assets_as_of"])}, {fmt_date(x["assets_report_date"], True)})</span>'))
        else:
            facts.append(("Total assets", "Not reported in the latest call report"))
        web = website_href(x["website"])
        facts.append(("Website", f'<a href="{e(web)}" target="_blank" rel="noopener nofollow">{e(x["website"])}</a>' if web else "Not listed by the regulator"))
        rec, rec_label = record_link(x)
        facts.append(("Regulator record", f'<a href="{e(rec)}" target="_blank" rel="noopener">{e(rec_label)} ↗</a>'))
        if x["holding_company"]:
            facts.append(("Holding company", e(x["holding_company"]) + ' <span class="muted-inline">(as FDIC lists it)</span>'))
        if x["also_known_as"]:
            facts.append(("Also known as", e(", ".join(x["also_known_as"].split("|")))))
        if board_names:
            facts.append(("Named on the board as", e(", ".join(board_names))))
        cr = CR.get(x["id"], {"a": [None] * len(QS), "d": [None] * len(QS), "l": [None] * len(QS)})
        if x["charter_type"] == "bank" and cr.get("off") is not None:
            facts.append(("Offices", f'{cr["off"]:,} <span class="muted-inline">(FDIC, incl. main office)</span>'))
        elif cr.get("sites"):
            b_, c_ = cr["sites"].get("Branch Office", 0), cr["sites"].get("Corporate Office", 0)
            facts.append(("Offices", f'{b_ + c_:,} <span class="muted-inline">({b_:,} branch, {c_:,} corporate; NCUA)</span>'))
        if cr.get("m") and cr["m"][-1] is not None:
            m_ = cr["m"]
            g_ = S.pct(m_[-1], m_[-5]) if len(m_) >= 5 else None
            facts.append(("Members", f'{m_[-1]:,} <span class="muted-inline">(NCUA, {S.qname(AS_OF)}' + (f', {"+" if g_ > 0 else "−" if g_ < 0 else ""}{abs(g_):.1f}% in 1 yr' if g_ is not None else "") + ")</span>"))
        if cr.get("est"):
            facts.append(("Established", e(cr["est"][:4]) + f' <span class="muted-inline">({"FDIC" if x["charter_type"] == "bank" else "NCUA"})</span>'))
        li_ = social.get(x["id"], {}).get("linkedin")
        if li_:
            facts.append(("LinkedIn", f'<a href="{e(li_["url"])}" target="_blank" rel="nofollow noopener">{e(li_["url"].split("linkedin.com")[1])} ↗</a> '
                                      f'<span class="muted-inline">(linked from the {cw}&#39;s own website, checked {fmt_date(li_["checked"])})</span>'))
        if cr.get("rssd") and cr["rssd"] not in ("0", ""):
            facts.append(("Call report summary", f'<a href="https://www.ibanknet.com/scripts/callreports/getbank.aspx?ibnid=usa_{e(cr["rssd"])}" target="_blank" rel="nofollow noopener">iBanknet ↗</a> <span class="muted-inline">(third-party site, RSSD {e(cr["rssd"])})</span>'))
        peer = []
        if x["id"] in rank_st:
            r_, n_ = rank_st[x["id"]]
            peer.append(f'<strong>#{r_:,}</strong> of {n_:,} {"credit unions" if x["charter_type"] == "cu" else "banks"} in {e(st_name)} by total assets')
        if x["id"] in rank_tier:
            r_, n_ = rank_tier[x["id"]]
            peer.append(f'<strong>#{r_:,}</strong> of {n_:,} {"credit unions" if x["charter_type"] == "cu" else "banks"} with {e(tier_name[x["_tier"]])} in assets')
        if x["id"] in rank_gr:
            r_, n_, p_ = rank_gr[x["id"]]
            peer.append(f'1-year asset growth {S.pct_html(p_)}: <strong>#{r_:,}</strong> of {n_:,} in that tier')
        if peer:
            peer.append(f'<span class="note">Call report assets, {S.qname(AS_OF)}. Rank 1 = largest or fastest growing.</span>')
        sim, sim_v = similar(x)
        showcase = x["id"] in SHOWCASE  # pass to S.feature_on(<flag>, showcase) when a new section is showcase-only
        dl = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in facts)
        if rows:
            hist = (f'<h2>Signals <span class="count-pill">{len(rows)}</span></h2><ul class="sig-list">' + "".join(sig_li(r) for r in rows) + "</ul>")
        else:
            hist = (f'<h2>Signals</h2><p class="empty-note">No signals on the board yet for {e(x["name"])}. New signals go up every weekday. '
                    f'<a href="/#subscribe">Get the Friday digest</a>.</p>')
        body = (crumbs([("Directory", "/fi/"), (st_name, f'/fi/{x["state"].lower()}/'), (x["name"], None)]) +
                f'<article class="fi-page"><h1>{e(x["name"])}</h1>'
                f'<p class="fi-sub">{"Credit union" if x["charter_type"] == "cu" else "Bank"} · {e(x["city"])}, {e(x["state"])}' + (f" · {e(a)} in assets" if a else "") + "</p>"
                + S.header_trend(cr, AS_OF) +
                f'<dl class="facts">{dl}</dl>' + S.trend_section(cr, QS, AS_OF, x["charter_type"]) + S.peer_section(peer) +
                provider_block(x, prov, board_by_url) + S.exec_section(rows, TYPE_LABEL) +
                S.history_section(cr.get("hist"), rows, CLASS_LABEL, x["charter_type"], TYPE_LABEL) + hist +
                S.similar_section(x, sim, sim_v, st_name, tier_name[x["_tier"]], fi_li) +
                f'<p class="more-links"><a href="/?state={e(x["state"])}">{e(st_name)} on the board</a><a href="/fi/{x["state"].lower()}/">All {e(st_name)} institutions</a><a href="/fi/assets/{e(x["_tier"])}/">{e(dict((t[0], t[1]) for t in TIERS)[x["_tier"]])}</a></p></article>')
        place = f'{x["city"]}, {x["state"]}'
        if rows:
            latest = rows[0]
            title = f'{x["name"]} ({place}): {len(rows)} signal{"s" if len(rows) > 1 else ""} | FI Signal Weekly'
            desc = (f'{x["name"]} is a {place} {cw}' + (f" with {a} in assets ({x['assets_as_of']})" if a else "") +
                    f'. Latest signal: {TYPE_LABEL.get(latest["type"], latest["type"])}, {fmt_date(latest["date"])}. Every signal links to its public source.')
        else:
            title = f'{x["name"]} ({place} {cw}) | FI Signal Weekly'
            desc = (f'{x["name"]} is a {place} {cw}' + (f" with {a} in assets ({x['assets_as_of']} call report)" if a else "") +
                    f'. Charter, website and {"NCUA" if x["charter_type"] == "cu" else "FDIC"} record.')
        files[x["_path"].lstrip("/") + "index.html"] = page(title, desc, x["_path"], body, noindex=not rows,
                                                            extra_head=f'\n<link rel="stylesheet" href="/css/fi-v2.css?v={V}">',
                                                            scripts=f'<script src="/js/fi-chart.js?v={V}" defer></script>\n')

    # state pages
    by_state = defaultdict(list)
    for x in inst:
        by_state[x["state"]].append(x)
    state_rows = []
    for st in sorted(by_state):
        xs = by_state[st]
        name = STATES.get(st, st)
        with_sig = sorted([x for x in xs if x["_n"]], key=by_assets)
        banks = sorted([x for x in xs if x["charter_type"] == "bank"], key=by_assets)
        cus = sorted([x for x in xs if x["charter_type"] == "cu"], key=by_assets)
        nsig = sum(x["_n"] for x in xs)
        state_rows.append((st, name, len(banks), len(cus), nsig))
        sig_block = (f'<h2>With signals <span class="count-pill">{len(with_sig)}</span></h2><ul class="fi-list">' + "".join(fi_li(x) for x in with_sig) + "</ul>"
                     if with_sig else f'<p class="empty-note">No signals on the board yet for {e(name)} institutions.</p>')
        sec = lambda label, ys, anchor: (f'<h2 id="{anchor}">{label} <span class="count-pill">{len(ys)}</span></h2><p class="note">Largest first, by total assets.</p><ul class="fi-list">' + "".join(fi_li(y) for y in ys) + "</ul>") if ys else ""
        body = (crumbs([("Directory", "/fi/"), (name, None)]) +
                f'<h1>{e(name)} banks &amp; credit unions</h1>'
                f'<p class="fi-sub">{len(banks):,} bank{"s" if len(banks) != 1 else ""} and {len(cus):,} credit union{"s" if len(cus) != 1 else ""}. {nsig} signal{"s" if nsig != 1 else ""} on the board.</p>'
                f'<p class="more-links"><a href="/?state={e(st)}">{e(name)} on the board</a><a href="/fi/?state={e(st)}">Search {e(name)}</a>' +
                (f'<a href="#banks">Banks</a>' if banks else "") + (f'<a href="#cus">Credit unions</a>' if cus else "") + "</p>" +
                sig_block + sec("Banks", banks, "banks") + sec("Credit unions", cus, "cus"))
        title = f"{name} banks & credit unions: {len(xs):,} institutions | FI Signal Weekly"
        desc = (f"All {len(banks):,} banks and {len(cus):,} credit unions in {name}, with assets from the latest call reports"
                + (f" and {nsig} buying-window signal{'s' if nsig != 1 else ''} from public sources." if nsig else "."))
        files[f"fi/{st.lower()}/index.html"] = page(title, desc, f"/fi/{st.lower()}/", body)

    # asset tier pages
    tier_counts = []
    for k, label, _, _ in TIERS:
        xs = sorted([x for x in inst if x["_tier"] == k], key=by_assets)
        if not xs:
            continue
        tier_counts.append((k, label, len(xs), sum(x["_n"] for x in xs)))
        with_sig = [x for x in xs if x["_n"]]
        heading = label if k != "na" else "Assets not reported"
        sig_block = (f'<h2>With signals <span class="count-pill">{len(with_sig)}</span></h2><ul class="fi-list">' + "".join(fi_li(x, True) for x in with_sig) + "</ul>") if with_sig else ""
        if len(xs) > TIER_LIST_MAX:
            listing = (f'<h2>Largest {TIER_TOP} <span class="count-pill">of {len(xs):,}</span></h2><p class="note"><a href="/fi/?assets={e(k)}">Search all {len(xs):,}</a> by name, state or city.</p><ul class="fi-list">'
                       + "".join(fi_li(x, True) for x in xs[:TIER_TOP]) + "</ul>")
        else:
            listing = (f'<h2>All {len(xs):,} <span class="count-pill">largest first</span></h2><ul class="fi-list">' + "".join(fi_li(x, True) for x in xs) + "</ul>")
        nb = sum(1 for x in xs if x["charter_type"] == "bank")
        body = (crumbs([("Directory", "/fi/"), (heading, None)]) +
                f'<h1>{"Banks &amp; credit unions: " + e(label) + " in assets" if k != "na" else "Banks &amp; credit unions with no reported assets"}</h1>'
                f'<p class="fi-sub">{nb:,} banks and {len(xs) - nb:,} credit unions. Call report assets, mostly 2026Q2.</p>'
                f'<p class="more-links"><a href="/?assets={e(k)}">This size on the board</a><a href="/fi/?assets={e(k)}">Search this size</a></p>' + sig_block + listing)
        title = (f"Banks & credit unions with {label} in assets | FI Signal Weekly" if k != "na" else "Banks & credit unions with no reported assets | FI Signal Weekly")
        desc = f"{len(xs):,} US banks and credit unions" + (f" with {label} in total assets" if k != "na" else " with no assets in the latest call report") + ", from FDIC and NCUA call reports, with their buying-window signals."
        files[f"fi/assets/{k}/index.html"] = page(title, desc, f"/fi/assets/{k}/", body)

    # landing page with search
    with_sig = sorted([x for x in inst if x["_n"]], key=lambda x: x["name"])
    with_sig.sort(key=lambda x: sigs[x["id"]][0]["date"], reverse=True)
    st_opts = "".join(f'<option value="{e(s)}">{e(n)}</option>' for s, n, *_ in sorted(state_rows, key=lambda t: t[1]))
    tier_opts = "".join(f'<option value="{e(k)}">{e(l)}</option>' for k, l, *_ in tier_counts)
    states_html = "".join(f'<li><a href="/fi/{s.lower()}/"><span class="nm">{e(n)}</span>' + (f'<span class="sigs">{ns}</span>' if ns else "") + f'<span class="sub">{b + c:,} FIs</span></a></li>' for s, n, b, c, ns in sorted(state_rows, key=lambda t: t[1]))
    tiers_html = "".join(f'<li><a href="/fi/assets/{e(k)}/"><span class="nm">{e(l)}</span><span class="sub">{n:,} FIs</span></a></li>' for k, l, n, _ in tier_counts)
    n_b = sum(1 for x in inst if x["charter_type"] == "bank")
    body = (f'<section class="dir-hero"><h1>US bank &amp; credit union directory</h1>'
            f'<p class="fi-sub">All {n_b:,} FDIC-insured banks and {len(inst) - n_b:,} credit unions, with call report assets, regulator records and every buying-window signal from the board.</p>'
            '<form class="panel fi-search" id="fi-search" role="search" onsubmit="return false">'
            '<div class="fs-q"><label for="fs-q">Search</label><input id="fs-q" type="search" placeholder="Name, city or state" autocomplete="off" enterkeyhint="search"></div>'
            f'<div><label for="fs-state">State</label><select id="fs-state"><option value="">All states</option>{st_opts}</select></div>'
            '<div><label for="fs-charter">Bank or CU</label><select id="fs-charter"><option value="">Banks &amp; credit unions</option><option value="bank">Banks</option><option value="cu">Credit unions</option></select></div>'
            f'<div><label for="fs-assets">Asset size</label><select id="fs-assets"><option value="">All sizes</option>{tier_opts}</select></div>'
            '<div class="fs-sig"><label class="check"><input id="fs-signals" type="checkbox"> Only with signals</label></div>'
            '</form><p class="count" id="fs-count" aria-live="polite"></p>'
            '<ul class="fi-list" id="fs-results" hidden></ul><p id="fs-more-wrap" hidden><button id="fs-more" class="ghost" type="button">Show more</button></p></section>'
            f'<section id="fs-default"><h2>Latest signals <span class="count-pill">{len(with_sig)} institutions</span></h2><p class="note">Institutions with signals on the board, most recent first.</p>'
            '<ul class="fi-list">' + "".join(fi_li(x, True) for x in with_sig) + "</ul>"
            f'<h2>By asset size</h2><ul class="fi-list fi-grid">{tiers_html}</ul>'
            f'<h2>By state</h2><ul class="fi-list fi-grid">{states_html}</ul></section>')
    files["fi/index.html"] = page("US bank & credit union directory | FI Signal Weekly",
                                  f"Search {len(inst):,} US banks and credit unions: charter, call report assets, website, FDIC or NCUA record, and every buying-window signal from public sources.",
                                  "/fi/", body, scripts=f'<script src="/js/fi-search.js?v={V}"></script>\n')

    # search index: per row [state, slug, name, city, cu(0/1), assets $M or -1, signals, extra search text]
    srows = []
    for x in sorted(inst, key=by_assets):
        extra = " ".join(sorted({*(x["also_known_as"].split("|") if x["also_known_as"] else []),
                                 *(r["institution"].split(" / ")[0].strip() for r in sigs.get(x["id"], []))} - {x["name"]}))
        srows.append([x["state"], x["_slug"], x["name"], x["city"], 1 if x["charter_type"] == "cu" else 0,
                      round(x["total_assets"] / 1e6) if x["total_assets"] != "" else -1, x["_n"], extra])
    files["fi/search.json"] = json.dumps({"cols": ["state", "slug", "name", "city", "cu", "assets_musd", "signals", "aka"],
                                          "as_of": sorted({x["assets_as_of"] for x in inst if x["assets_as_of"]})[-1],
                                          "rows": srows}, ensure_ascii=False, separators=(",", ":")).replace('],[', '],\n[') + "\n"
    files["fi/linked.json"] = json.dumps({x["id"]: x["_path"] for x in inst if x["_n"]}, ensure_ascii=False, indent=0, sort_keys=True) + "\n"

    # sitemap: board, about, directory indexes, and institution pages with signals only
    urls = ["/", "/about.html", "/fi/"] + [f"/fi/{s.lower()}/" for s, *_ in sorted(state_rows)] + [f"/fi/assets/{k}/" for k, *_ in tier_counts] + sorted(x["_path"] for x in inst if x["_n"])
    files["sitemap.xml"] = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
                            "".join(f"  <url><loc>{e(SITE + u)}</loc></url>\n" for u in urls) + "</urlset>\n")
    files["robots.txt"] = f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n"
    return {"institutions": len(inst), "core_filled": sum(1 for x in inst if resolve_provider(prov.get(x["id"], {}).get("core", []))[0]),
            "digital_filled": sum(1 for x in inst if resolve_provider(prov.get(x["id"], {}).get("digital", []))[0]), "with_signals": sum(1 for x in inst if x["_n"]), "states": len(state_rows),
            "tiers": len(tier_counts), "signals_linked": sum(len(v) for v in sigs.values()), "sitemap_urls": len(urls)}


def main():
    global V
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    try:
        V = asset_hash()
        files = {}
        stats = build(files)
    except (OSError, KeyError, ValueError) as ex:
        print("error:", ex, file=sys.stderr)
        return 1
    # data/fi-pinned.txt: committed pages the build must not rewrite or delete (one-page previews)
    pinned = set()
    pp = os.path.join(ROOT, "data", "fi-pinned.txt")
    if os.path.exists(pp):
        pinned = {ln.strip() for ln in open(pp, encoding="utf-8") if ln.strip() and not ln.startswith("#")}
    for rel in pinned:
        files.pop(rel, None)
    existing = set()
    for d, _, fs in os.walk(os.path.join(ROOT, OUT)):
        for f in fs:
            existing.add(os.path.relpath(os.path.join(d, f), ROOT))
    changed, removed = [], sorted(existing - set(files) - pinned)
    for rel, content in files.items():
        p = os.path.join(ROOT, rel)
        try:
            with open(p, encoding="utf-8") as f:
                if f.read() == content:
                    continue
        except FileNotFoundError:
            pass
        changed.append(rel)
    if a.check:
        print(f"{len(changed)} files would change, {len(removed)} would be removed")
        return 3 if changed or removed else 0
    for rel in changed:
        p = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(files[rel])
    for rel in removed:
        os.remove(os.path.join(ROOT, rel))
    for d, ds, fs in sorted(os.walk(os.path.join(ROOT, OUT)), reverse=True):
        if not ds and not fs:
            os.rmdir(d)
    print(f"directory: {stats['institutions']:,} institution pages ({stats['with_signals']} with signals, indexed; the rest noindex), "
          f"{stats['states']} state pages, {stats['tiers']} asset-tier pages, {stats['signals_linked']} signals, "
          f"{stats['sitemap_urls']} sitemap URLs, providers filled: core {stats['core_filled']:,}, digital {stats['digital_filled']:,}. {len(changed)} files written, {len(removed)} removed.")
    return 0


V = ""
if __name__ == "__main__":
    sys.exit(main())
