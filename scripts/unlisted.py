"""Pages that stay live at their URLs but are unlisted everywhere.

Each must carry <meta name="robots" content="noindex,nofollow">, stay out of sitemap.xml,
llms/AI index files and feeds, and never be linked (href or URL) from any other page.
Do not add robots.txt Disallow lines naming them. scripts/validate.py enforces all of this.
"""
UNLISTED_PAGES = ("/whats-new/", "/roadmap/", "/territory/", "/r/le4idsoyeldffb/")
ROBOTS_META = '<meta name="robots" content="noindex,nofollow">'

def is_unlisted(href):
    h = (href or "").split("#")[0].split("?")[0]
    if h.startswith("https://fisignalweekly.com"): h = h[len("https://fisignalweekly.com"):]
    if not h.startswith("/"): h = "/" + h
    if not h.endswith("/") and not h.endswith(".html"): h += "/"
    return any(h == p or h.startswith(p) or h == p + "index.html" for p in UNLISTED_PAGES)
