#!/usr/bin/env python3
"""Harvest executive / C-level change CANDIDATES at US banks and credit unions.

No LLM judgment: pure collection + keyword filtering. Output is a candidate list
that a human (or the weekly refresh) must verify by opening each source_url.

Sources (see scripts/refresh_notes.md):
  sec    SEC EDGAR daily index -> 8-K / 8-K/A from bank-SIC filers (6021/6022/6035/6036/6712)
         -> parse Item 5.02 text straight from the filing.      (high precision)
  gnews  Google News RSS searches (wires + trade press + local press), links decoded to publisher URL.
  rss    Direct RSS: PR Newswire, Finextra, ABA Banking Journal, Bank Director, CUInsight,
         American Banker, Banking Dive.

Usage:
  python3 scripts/harvest_exec.py                 # last 14 days, all sources
  python3 scripts/harvest_exec.py --days 60 --no-seen   # backfill, ignore seen-file
  python3 scripts/harvest_exec.py --sources sec,rss
State (outside repo): /workspace/fisignal-state/{seen.json,exec_candidates.json,bank_ciks.json}
"""
import argparse, concurrent.futures as cf, datetime as dt, email.utils, html, json, os, re, sys, time
import urllib.parse, urllib.request, urllib.error
import xml.etree.ElementTree as ET

STATE_DIR = os.environ.get("FISIGNAL_STATE", "/workspace/fisignal-state")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEC_UA = "FI Signal Weekly fisignal@mail.grokbot.com"
BR_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
BANK_SICS = ["6021", "6022", "6035", "6036", "6712"]

ROLE = re.compile(
    r"\b(ceo|cfo|coo|cio|cto|cro|cdo|cxo|chief (?:executive|financial|operating|information|technology|digital|lending|risk|credit|"
    r"banking|revenue|experience|data|innovation|payments?|transformation|retail|commercial|strategy|administrative|"
    r"people|human resources|marketing|compliance|security|operations?|business|member|growth|product|accounting|"
    r"lending|wealth|trust|mortgage|deposit|consumer|digital banking|technology and operations|information security)[a-z ,&/-]{0,30}?officer|"
    r"president|executive vice president|evp|senior vice president|svp|head of (?:retail|commercial|digital|lending|consumer|technology|operations|wealth|payments|treasury)|"
    r"general manager|chair(?:man|woman)? and (?:ceo|chief)|market president|regional president|\w+ chief|chief|top post|top job|c-suite|leader(?:ship)?|head|executives?|officers?|promotions?)\b", re.I)
ACTION = re.compile(
    r"\b(names?|named|appoints?|appointed|appointment|promotes?|promoted|elects?|elected|hires?|hired|taps?|tapped|tabs?|"
    r"selects?|selected|welcomes?|welcomed|joins?|joined|succeed[s]?|successor|retire[s]?|retirement|retiring|resigns?|"
    r"resignation|steps? down|stepping down|departure|departs?|leaves?|exits?|to lead|new ceo|new president|announces? (?:new|the)|"
    r"transition|named as|assumes?|advances?|elevates?|upcoming|incoming|fills?|promotions?|announces?|will become|to become|to succeed|next|announced as|new|shuffle|shakeup|changes?)\b", re.I)
ORG = re.compile(
    r"\b(bank|banks|banking|bancorp|bancorporation|bancshares|bankshares|credit union|credit unions|fcu|cu|"
    r"financial|savings|trust|thrift|federal|national|holding|bancgroup|community|first|capital)\b", re.I)
STRONG_ORG = re.compile(r"\b(bank|bancorp|bancorporation|bancshares|bankshares|credit union|fcu|savings|financial holdings?|financial corp|financial group|bancgroup|thrift)\b|\bcu\b", re.I)
NOISE = re.compile(
    r"\b(football|basketball|baseball|soccer|hockey|nfl|nba|mlb|school district|university|hospital|health|medical|county commission|"
    r"city council|police|sheriff|church|chamber of commerce|bank of england|bank of canada|reserve bank of india|european central|"
    r"world bank|federal reserve board|fed governor|ecb|boe|rbi|nigeria|india|pakistan|kenya|uk|u\.k\.|australia|canada|canadian|"
    r"dubai|saudi|singapore|hong kong|africa|ghana|malaysia|philippines|ireland|irish|london|ontario|british|german|deutsche|"
    r"japan|china|brazil|mexico|egypt|turkey|ukraine|indonesia|bangladesh|sri lanka|nepal|uganda|zambia|tanzania|"
    r"new zealand|spain|banco|credit union of new zealand|building society)\b", re.I)

STRICT_ROLE = re.compile(r"\b(chief [a-z ,&/-]{3,40}?officer|chief executive|president|ceo|cfo|coo|cio|cto|cro|(?:senior )?executive vice president|evp|head of [a-z ]{3,30}|general manager)\b", re.I)
CHANGE = re.compile(r"\b(retire[sd]?|retirement|resign(?:s|ed|ation)?|depart(?:s|ure|ed)?|leav(?:e|es|ing)|step(?:s|ping)? down|terminat\w+|appoint(?:s|ed|ment)?|nam(?:e|es|ed)|promot\w+|succeed\w*|assum\w+|hire[sd]?|join(?:s|ed)?|elect(?:s|ed)?|transition\w*)\b", re.I)
COMP_ONLY = re.compile(r"\b(employment agreement|salary continuation|bonus plan|incentive plan|restricted stock|equity award|supplemental executive|change[- ]in[- ]control|severance|consulting agreement|non-?renewal)\b", re.I)

def officer_change(text):
    """True if an executive role appears within ~170 chars of a change verb and the context is not purely pay/agreements/board seats."""
    for m in STRICT_ROLE.finditer(text):
        ctx = text[max(0, m.start() - 170): m.end() + 170]
        if not CHANGE.search(ctx): continue
        if COMP_ONLY.search(ctx) and not re.search(r"\b(retire|resign|appoint|nam(?:e|ed)|promot|succeed|hire|depart|step)\w*", ctx, re.I): continue
        return True
    return False

def log(*a):
    print(*a, file=sys.stderr, flush=True)

_last = {}
def http(url, ua=BR_UA, timeout=25, data=None, headers=None, maxbytes=None, throttle=0.0, tries=3):
    host = urllib.parse.urlparse(url).netloc
    for i in range(tries):
        if throttle:
            w = _last.get(host, 0) + throttle - time.time()
            if w > 0: time.sleep(w)
            _last[host] = time.time()
        req = urllib.request.Request(url, data=data, headers={"User-Agent": ua, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read(maxbytes) if maxbytes else r.read()
                return raw.decode(r.headers.get_content_charset() or "utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410): return None
            time.sleep(1 + i * 2)
        except Exception:
            time.sleep(1 + i * 2)
    return None

def strip(s):
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()

def load(path, default):
    try:
        with open(path) as f: return json.load(f)
    except Exception: return default

def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(obj, f, indent=1)
    os.replace(tmp, path)

TITLE_PERSON = re.compile(r"\b((?:[A-Z][a-z]+\.?|[A-Z]\.)(?:\s(?:[A-Z]\.?|[A-Z][a-z'’\-]+|Mc[A-Z][a-z]+|De[A-Z][a-z]+|Van|Von|de|la)){1,3})\b")
def guess_person(text):
    m = re.search(r"\b(?:Mr|Ms|Mrs|Dr)\.\s+([A-Z][\w'’\-]+(?:\s+[A-Z][\w\.'’\-]+){0,2})", text)
    if m: return m.group(1)
    m = re.search(r"\b(?:names?|named|appoints?|appointed|promotes?|promoted|elects?|hires?|taps?|welcomes?|selects?)\s+((?:[A-Z][\w\.'’\-]+\s+){1,3}[A-Z][\w'’\-]+)", text)
    if m: return m.group(1)
    m = re.search(r"^((?:[A-Z][\w\.'’\-]+\s+){1,3}[A-Z][\w'’\-]+)\s+(?:named|appointed|promoted|joins|to|elected|tapped|hired|succeeds)", text)
    return m.group(1) if m else ""

def guess_title(text):
    m = ROLE.search(text)
    return m.group(0).strip() if m else ""

def guess_institution(title):
    # "X names Y CEO" / "Y named CEO of X" / "X Bank appoints ..." -> best effort only
    m = re.search(r"^(.{3,70}?)\s+(?:names?|appoints?|promotes?|elects?|hires?|taps?|welcomes?|announces?|selects?|adds?)\b", title)
    if m and STRONG_ORG.search(m.group(1)): return m.group(1).strip(" ,:-–|")
    m = re.search(r"\b(?:of|at|for|with)\s+((?:[A-Z][\w&'’\.\-]+\s*){1,6}(?:Bank|Bancorp|Bancshares|Credit Union|FCU|Financial|Savings|Trust)[\w&'’\.\-\s]{0,25})", title)
    return m.group(1).strip(" ,:-–|") if m else ""

# ---------------------------------------------------------------- SEC
def sec_bank_ciks(maxage_days=30):
    p = os.path.join(STATE_DIR, "bank_ciks.json")
    c = load(p, {})
    if c.get("fetched") and (time.time() - c["fetched"]) < maxage_days * 86400 and c.get("ciks"):
        return c["ciks"]
    ciks = {}
    for sic in BANK_SICS:
        start = 0
        while True:
            u = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC={sic}&type=&dateb=&owner=include&count=100&start={start}"
            h = http(u, SEC_UA, throttle=0.15)
            if not h: break
            rows = re.findall(r'CIK=(\d+)&amp;owner=include[^>]*>\d+</a></td>\s*<td scope="row">(.*?)</td>\s*<td valign="top" scope="row"><a[^>]*>([A-Z]{2})?', h, re.S)
            if not rows: break
            for cik, name, st in rows:
                ciks[str(int(cik))] = {"name": html.unescape(name).strip(), "state": st or "", "sic": sic}
            if "start=%d" % (start + 100) not in h: break
            start += 100
    log(f"[sec] bank CIK list refreshed: {len(ciks)}")
    save(p, {"fetched": time.time(), "ciks": ciks})
    return ciks

def sec_daily_index(day):
    q = (day.month - 1) // 3 + 1
    u = f"https://www.sec.gov/Archives/edgar/daily-index/{day.year}/QTR{q}/form.{day:%Y%m%d}.idx"
    return http(u, SEC_UA, throttle=0.12)

def sec_extract_502(txt):
    m = re.search(r"(?i)item\s*5\.02[\.\s:\-–—]*(departure of directors.{0,120}?)?", txt)
    if not m: return ""
    rest = txt[m.start():]
    # stop at next item
    n = re.search(r"(?i)\bitem\s*(?:5\.0[3-9]|5\.[1-9]|6\.|7\.01|8\.01|9\.01)\b", rest[20:])
    sec = rest[: (n.start() + 20) if n else 3000]
    return sec[:3500]

def harvest_sec(days, since):
    out = []
    ciks = sec_bank_ciks()
    today = dt.date.today()
    filings = []
    for d in range(days + 1):
        day = today - dt.timedelta(days=d)
        if day.weekday() >= 5: continue
        idx = sec_daily_index(day)
        if not idx: continue
        for ln in idx.splitlines():
            if not ln.startswith("8-K"): continue
            mm = re.search(r"^(8-K(?:/A)?)\s+(.*?)\s+(\d{3,8})\s+(\d{8})\s+(edgar/data/\S+)", ln)
            if not mm: continue
            form, name, cik, fdate, path = mm.groups()
            if str(int(cik)) in ciks:
                filings.append((form, name.strip(), str(int(cik)), fdate, path))
    log(f"[sec] bank 8-K filings in window: {len(filings)}")
    def one(f):
        form, name, cik, fdate, path = f
        raw = http("https://www.sec.gov/Archives/" + path, SEC_UA, maxbytes=450000, throttle=0.12, timeout=40)
        if not raw: return None
        hdr = raw[:6000]
        if not re.search(r"(?i)departure of directors or certain officers", hdr): return None
        period = re.search(r"CONFORMED PERIOD OF REPORT:\s*(\d{8})", hdr)
        state = re.search(r"BUSINESS ADDRESS:.*?STATE:\s*([A-Z]{2})", hdr, re.S)
        acc = re.search(r"ACCESSION NUMBER:\s*(\S+)", hdr)
        fname = re.search(r"<FILENAME>\s*(\S+)", raw)
        body = strip(raw[raw.find("<DOCUMENT>"):]) if "<DOCUMENT>" in raw else strip(raw)
        sec = sec_extract_502(body)
        if not sec: return None
        # require officer-ish language: a role and an action
        if not officer_change(sec): return None
        accn = acc.group(1) if acc else path.split("/")[-1].replace(".txt", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-','')}/{fname.group(1)}" if fname else "https://www.sec.gov/Archives/" + path
        ev = period.group(1) if period else fdate
        date = f"{ev[:4]}-{ev[4:6]}-{ev[6:]}"
        fd = f"{fdate[:4]}-{fdate[4:6]}-{fdate[6:]}"
        return {"institution": ciks[cik]["name"].title() if ciks[cik]["name"].isupper() else ciks[cik]["name"],
                "person": guess_person(sec), "title": guess_title(sec), "date": min(date, fd) if date > fd else date,
                "filed": fd, "state": state.group(1) if state else ciks[cik].get("state", ""),
                "source_url": url, "snippet": re.sub(r"(?i)^item\s*5\.02[\.\s:]*departure of directors or certain officers;?.*?compensatory arrangements of certain officers\.?\s*", "", sec)[:700], "source": "sec-8k-5.02",
                "key": "sec:" + accn, "sec_cik": cik}
    with cf.ThreadPoolExecutor(4) as ex:
        for r in ex.map(one, filings):
            if r: out.append(r)
    return out

# ---------------------------------------------------------------- RSS helpers
def parse_feed(xmltext):
    items = []
    if not xmltext: return items
    try:
        root = ET.fromstring(xmltext.encode("utf-8") if isinstance(xmltext, str) else xmltext)
    except ET.ParseError:
        try: root = ET.fromstring(re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#)", "&amp;", xmltext).encode("utf-8"))
        except ET.ParseError: return items
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"): continue
        d = {}
        for c in it:
            t = c.tag.split("}")[-1]
            if t == "link": d["link"] = c.attrib.get("href") or (c.text or "").strip()
            elif t in ("title", "description", "summary", "content", "pubDate", "published", "updated", "date"):
                d.setdefault(t, (c.text or "").strip())
            elif t == "source": d["src_name"] = (c.text or "").strip(); d["src_url"] = c.attrib.get("url", "")
        items.append(d)
    return items

def parse_date(s):
    if not s: return None
    try:
        t = email.utils.parsedate_to_datetime(s)
        if t.tzinfo: t = t.astimezone(dt.timezone(dt.timedelta(hours=-4)))
        return t.date()
    except Exception: pass
    try: return dt.date.fromisoformat(s[:10])
    except Exception: return None

def qualifies(title, desc=""):
    t = title or ""
    blob = t + " " + (desc or "")
    if NOISE.search(t): return False
    return bool(ROLE.search(t) and ACTION.search(t))

def org_hint(*texts):
    return bool(STRONG_ORG.search(" ".join(texts)))

RSS_FEEDS = {
    "prnewswire-rss": ["https://www.prnewswire.com/rss/news-releases-list.rss",
                       "https://www.prnewswire.com/rss/financial-services-latest-news/banking-latest-news-list.rss"],
    "finextra": ["https://www.finextra.com/rss/headlines.aspx"],
    "aba-banking-journal": ["https://bankingjournal.aba.com/feed/"],
    "bank-director": ["https://www.bankdirector.com/feed/"],
    "cuinsight": ["https://www.cuinsight.com/feed"],
    "american-banker": ["https://www.americanbanker.com/feed?rss=true", "https://www.americanbanker.com/feed"],
    "banking-dive": ["https://www.bankingdive.com/feeds/news/"],
}

PRN_LIST = "https://www.prnewswire.com/news-releases/financial-services-latest-news/banking-financial-services-list/?page=%d&pagesize=100"

def harvest_prn_html(since, maxpages=130):
    """PR Newswire banking category (paged, ~100/page, newest first) -> goes back as far as `since`."""
    out, n_all = [], 0
    for pg in range(1, maxpages + 1):
        h = http(PRN_LIST % pg)
        if not h: break
        cards = re.split(r'<div role="group" aria-label="News Release"', h)[1:]
        if not cards: break
        oldest = None
        for c in cards:
            n_all += 1
            m = re.search(r'href="(/news-releases/[^"]+)"', c)
            d = re.search(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4}), \d+:\d+ ET", c)
            if not (m and d): continue
            day = dt.datetime.strptime(f"{d.group(1)} {d.group(2)} {d.group(3)}", "%b %d %Y").date()
            oldest = day if oldest is None or day < oldest else oldest
            if day < since: continue
            txt = strip(re.sub(r"<img[^>]*>", "", c))
            txt = re.sub(r"^.*?ET\s*", "", txt, count=1)
            title = html.unescape(re.sub(r"\s+", " ", strip(re.search(r'<h3[^>]*>(.*?)</h3>', c, re.S).group(1)))) if re.search(r'<h3[^>]*>(.*?)</h3>', c, re.S) else txt[:140]
            title = re.sub(r"^[A-Z][a-z]{2} \d{1,2}, \d{4}, \d+:\d+ ET\s*", "", title)
            if not qualifies(title, txt[:300]) or not org_hint(title, txt[:300]): continue
            link = "https://www.prnewswire.com" + m.group(1)
            out.append({"institution": guess_institution(title), "person": guess_person(title), "title": guess_title(title), "date": day.isoformat(),
                        "source_url": link, "headline": title, "snippet": txt[:500], "org_hint": org_hint(title, txt[:300]),
                        "source": "prnewswire", "key": "url:" + link})
        if oldest and oldest < since: break
    log(f"[prn] banking category: {n_all} releases scanned")
    return out

def harvest_rss(since):
    out = harvest_prn_html(since)
    for name, urls in RSS_FEEDS.items():
        n_all = 0
        for u in urls:
            for it in parse_feed(http(u)):
                n_all += 1
                title = html.unescape(it.get("title", ""))
                desc = strip(it.get("description") or it.get("summary") or "")
                d = parse_date(it.get("pubDate") or it.get("published") or it.get("updated"))
                if not d or d < since: continue
                if not qualifies(title, desc[:400]): continue
                out.append({"institution": guess_institution(title), "person": guess_person(title), "title": guess_title(title),
                            "date": d.isoformat(), "source_url": it.get("link", ""), "headline": title, "snippet": desc[:500],
                            "org_hint": org_hint(title, desc[:400]), "source": "rss:" + name, "key": "url:" + it.get("link", "")})
        log(f"[rss] {name}: {n_all} feed items scanned")
    return out

# ---------------------------------------------------------------- Google News
ROLE_GROUPS = [
    '"chief executive officer" OR CEO', 'president', '"chief financial officer" OR CFO', '"chief operating officer" OR COO',
    '"chief information officer" OR CIO OR "chief technology officer" OR CTO', '"chief digital officer" OR "chief digital banking officer" OR "chief innovation officer"',
    '"chief lending officer" OR "chief credit officer" OR "chief risk officer"', '"chief banking officer" OR "chief retail officer" OR "chief experience officer"',
    '"executive vice president"', '"head of retail" OR "head of commercial banking" OR "commercial banking president"',
    '"chief revenue officer" OR "chief strategy officer" OR "chief transformation officer" OR "chief payments officer"',
    '"chief administrative officer" OR "chief human resources officer" OR "chief marketing officer" OR "chief data officer"',
]
ACTIONS = 'names OR appoints OR promotes OR hires OR elects OR taps OR announces OR retire OR succeeds OR "steps down" OR resigns'
SITES = ["prnewswire.com", "businesswire.com", "globenewswire.com", "accesswire.com", "cutimes.com", "cutoday.info", "cuinsight.com", "americanbanker.com",
         "bankingdive.com", "finextra.com", "bankdirector.com", "bankingjournal.aba.com", "cuna.org", "news.cuna.org", "thefinancialbrand.com",
         "bizjournals.com", "independentbanker.org", "bankersonline.com", "paymentsdive.com", "pymnts.com", "creditunions.com"]

def gnews_queries(days, when=None):
    when = when or f"when:{days}d"
    qs = []
    for inst in ('"credit union"', '(bank OR bancorp OR bancshares OR "financial corp")'):
        for rg in ROLE_GROUPS:
            qs.append(f"{inst} ({rg}) ({ACTIONS}) {when}")
    for site in SITES:
        for inst in ('"credit union"', '(bank OR bancorp OR bancshares)'):
            qs.append(f"site:{site} {inst} (names OR appoints OR promotes OR elects OR hires OR taps OR retire OR succeeds) (CEO OR president OR \"chief\" OR \"executive vice president\") {when}")
    return qs

_resolve_cache = {}
def gnews_resolve(url):
    if url in _resolve_cache: return _resolve_cache[url]
    res = url
    try:
        gid = re.search(r"/articles/([^?/]+)", url).group(1)
        h = http(f"https://news.google.com/rss/articles/{gid}", BR_UA, tries=2)
        sg = re.search(r'data-n-a-sg="([^"]+)"', h or ""); ts = re.search(r'data-n-a-ts="([^"]+)"', h or "")
        if sg and ts:
            payload = ["Fbv4je", '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],"%s",%s,"%s"]' % (gid, ts.group(1), sg.group(1)), None, "generic"]
            body = "f.req=" + urllib.parse.quote(json.dumps([[payload]]))
            t = http("https://news.google.com/_/DotsSplashUi/data/batchexecute", BR_UA, data=body.encode(),
                     headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}, tries=2)
            m = re.search(r'\\"(https?://[^"\\]+)\\"', t or "")
            if m: res = m.group(1)
    except Exception: pass
    _resolve_cache[url] = res
    return res

def harvest_gnews(days, since):
    seen_titles, cands = set(), []
    qs = []
    if days <= 15:
        qs = gnews_queries(days)
    else:  # Google News caps ~100 items/query: split into <=15-day windows
        end = dt.date.today() + dt.timedelta(days=1)
        start = dt.date.today() - dt.timedelta(days=days)
        while start < end:
            e2 = min(start + dt.timedelta(days=15), end)
            qs += gnews_queries(days, f"after:{start.isoformat()} before:{e2.isoformat()}")
            start = e2
    def run(q):
        u = "https://news.google.com/rss/search?q=" + urllib.parse.quote(q) + "&hl=en-US&gl=US&ceid=US:en"
        return parse_feed(http(u, BR_UA))
    n_all = 0
    with cf.ThreadPoolExecutor(4) as ex:
        for items in ex.map(run, qs):
            for it in items:
                n_all += 1
                title = html.unescape(it.get("title", ""))
                d = parse_date(it.get("pubDate"))
                if not d or d < since: continue
                norm = re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+-\s+[^-]+$", "", title.lower()))
                if norm in seen_titles: continue
                seen_titles.add(norm)
                core = re.sub(r"\s+-\s+[^-]+$", "", title)
                if not qualifies(core): continue
                cands.append((core, it, d))
    log(f"[gnews] {len(qs)} queries, {n_all} raw items, {len(cands)} pass title filter -> resolving links")
    def res(c):
        core, it, d = c
        url = gnews_resolve(it.get("link", ""))
        return {"institution": guess_institution(core), "person": guess_person(core), "title": guess_title(core),
                "date": d.isoformat(), "source_url": url, "headline": core, "snippet": core,
                "org_hint": org_hint(core), "source": "gnews:" + (it.get("src_name") or ""), "key": "url:" + url}
    with cf.ThreadPoolExecutor(4) as ex:
        return list(ex.map(res, cands))

# ---------------------------------------------------------------- main
def norm_url(u):
    u = (u or "").split("#")[0].rstrip("/")
    return re.sub(r"^https?://(www\.)?", "", u).lower()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--sources", default="sec,rss,gnews")
    ap.add_argument("--no-seen", action="store_true", help="ignore seen-file (still dedupe vs triggers.json)")
    ap.add_argument("--out", default=os.path.join(STATE_DIR, "exec_candidates.json"))
    ap.add_argument("--no-mark-seen", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    since = dt.date.today() - dt.timedelta(days=a.days)
    srcs = set(a.sources.split(","))
    cands, counts = [], {}
    for name, fn in (("sec", lambda: harvest_sec(a.days, since)), ("rss", lambda: harvest_rss(since)), ("gnews", lambda: harvest_gnews(a.days, since))):
        if name in srcs:
            try: r = fn()
            except Exception as e:
                log(f"[{name}] FAILED: {e!r}"); r = []
            counts[name] = len(r); cands += r
    trig = load(os.path.join(REPO, "data", "triggers.json"), {"rows": []})["rows"]
    known_urls = {norm_url(r["source_url"]) for r in trig}
    known_acc = {re.search(r"/(\d{18})/", r["source_url"]).group(1) for r in trig if re.search(r"/(\d{18})/", r["source_url"])}
    seen = load(os.path.join(STATE_DIR, "seen.json"), {})
    final, dup, sd, pub, title_sets = [], 0, 0, set(), []
    for c in sorted(cands, key=lambda c: (c["source"] != "sec-8k-5.02", c["date"]), reverse=False):
        pk = norm_url(c["source_url"])
        acc = re.search(r"/(\d{18})/", c["source_url"] or "")
        if pk in known_urls or (acc and acc.group(1) in known_acc): dup += 1; continue
        if not a.no_seen and c["key"] in seen: sd += 1; continue
        if pk in pub: continue
        toks = set(re.findall(r"[a-z0-9]+", (c.get("headline") or "").lower())) - {"the","a","of","to","and","as","for","names","named","new","at","in"}
        if toks and any(len(toks & o) / max(1, len(toks | o)) > 0.7 for o in title_sets): continue
        pub.add(pk)
        if toks: title_sets.append(toks)
        c["harvested"] = dt.date.today().isoformat()
        final.append(c)
    final.sort(key=lambda c: c["date"], reverse=True)
    save(a.out, {"generated": dt.datetime.now().isoformat(timespec="seconds"), "lookback_days": a.days,
                 "counts_by_source_raw": counts, "n_candidates": len(final), "candidates": final})
    if not a.no_mark_seen:
        for c in final: seen[c["key"]] = c["harvested"]
        save(os.path.join(STATE_DIR, "seen.json"), seen)
    by = {}
    for c in final: by[c["source"].split(":")[0]] = by.get(c["source"].split(":")[0], 0) + 1
    print(json.dumps({"candidates": len(final), "by_source": by, "raw_by_source": counts, "already_in_triggers": dup,
                      "already_seen": sd, "seconds": round(time.time() - t0, 1), "out": a.out}))

if __name__ == "__main__":
    main()
