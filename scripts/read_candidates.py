#!/usr/bin/env python3
"""Fetch each candidate's source_url and print the article text around the leadership-change sentence,
so a human can verify quickly (named US bank/CU, role, real date). Reading only: no judgment here.

  python3 scripts/read_candidates.py [--file /workspace/fisignal-state/exec_candidates.json] [--start 0] [--n 25] [--chars 700]
Caches page text in /workspace/fisignal-state/pages/.
"""
import argparse, hashlib, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harvest_exec as H

def page_text(url):
    d = os.path.join(H.STATE_DIR, "pages"); os.makedirs(d, exist_ok=True)
    f = os.path.join(d, hashlib.md5(url.encode()).hexdigest() + ".txt")
    if os.path.exists(f): return open(f).read()
    ua = H.SEC_UA if "sec.gov" in url else H.BR_UA
    raw = H.http(url, ua, maxbytes=900000, timeout=25, tries=2, throttle=0.12 if "sec.gov" in url else 0)
    t = ""
    if raw:
        m = re.search(r"(?is)<article.*?</article>", raw)
        t = H.strip(m.group(0) if m else raw)
        md = re.findall(r'(?:article:published_time|datePublished|"dateCreated"|og:updated_time)["\'\s:=content]*["\']?(\d{4}-\d{2}-\d{2})', raw)
        t = ("[META-DATE %s] " % ",".join(sorted(set(md))[:3]) if md else "") + t
    open(f, "w").write(t)
    return t

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=os.path.join(H.STATE_DIR, "exec_candidates.json"))
    ap.add_argument("--idx", help="comma list of candidate indexes (overrides --start/--n)")
    ap.add_argument("--start", type=int, default=0); ap.add_argument("--n", type=int, default=25); ap.add_argument("--chars", type=int, default=700)
    a = ap.parse_args()
    cands = json.load(open(a.file))["candidates"]
    sel = [(i, cands[i]) for i in map(int, a.idx.split(","))] if a.idx else list(enumerate(cands[a.start:a.start + a.n], a.start))
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(6) as ex: list(ex.map(lambda ic: page_text(ic[1]["source_url"]), sel))  # prefetch
    for i, c in sel:
        t = page_text(c["source_url"])
        head = set(re.findall(r"[a-z0-9]{3,}", (c.get("headline") or c.get("institution") or "").lower())) - {"the","names","named","announces","appoints","promotes","and","for","with","new"}
        sents = re.split(r"(?<=[.!?])\s+", t)
        scored = []
        for j, se in enumerate(sents):
            if len(se) < 40 or len(se) > 700: continue
            w = set(re.findall(r"[a-z0-9]{3,}", se.lower()))
            sc = len(head & w) + 2 * bool(H.ROLE.search(se)) + 2 * bool(H.ACTION.search(se)) + bool(H.STRONG_ORG.search(se))
            scored.append((sc, j, se))
        top = sorted(scored, reverse=True)[:3]
        top = [x[2] for x in sorted(top, key=lambda x: x[1])]
        dates = re.findall(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.? \d{1,2},? \d{4}\b|\b\d{1,2}/\d{1,2}/\d{4}\b", t[:3000])[:3]
        meta = re.match(r"\[META-DATE ([^\]]*)\]", t)
        out = ("[dates: %s%s] " % (",".join(dates), (" meta:" + meta.group(1)) if meta else "")) + " ".join(top)[:a.chars * 2] if top else ""
        print(f"#{i} [{c['date']}] {c.get('headline') or c.get('institution')} | {c['source']}\n  {c['source_url']}\n  >> {out or '(could not fetch / no text)'}\n")

if __name__ == "__main__":
    main()
