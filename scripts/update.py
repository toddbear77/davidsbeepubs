#!/usr/bin/env python3
"""
Daily updater for David Raphael's Babylon Bee tribute page.

What it does (run by .github/workflows/daily-update.yml every morning):
  1. Downloads the Babylon Bee's article list (the same data babylonbee.com/news uses).
  2. Opens every article from the last LOOKBACK_DAYS that isn't already listed and
     checks it for "David Raphael contributed to this report". Matches are added.
  3. Refreshes each headline's comment count and its "Most Discussed" percentile:
     the share of Bee articles published within +/-30 days that it out-commented.
  4. Writes site/headlines.json.

Safety rules: it never deletes a headline, never edits the text of an entry marked
"manual": true, and stops with an error (changing nothing) if the Bee's data looks
wrong. A failed run makes GitHub email the repository owner.

Uses only the Python standard library.
"""
import datetime as dt
import html
import http.cookiejar
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "headlines.json"
BASE = "https://babylonbee.com"
LOOKBACK_DAYS = 10      # how far back to look for new articles each run
WINDOW_DAYS = 30        # comparison window for the "Most Discussed" percentile
PAGE_SIZE = 200
MAX_PAGES = 60
CREDIT = re.compile(r"David\s+Raphael\s+contributed\s+to\s+this\s+report", re.I)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")


# The Bee's site (Laravel) rejects data requests with HTTP 419 unless they carry the
# session cookie and anti-forgery token a browser gets when it first loads a page.
# So we keep cookies like a browser and load /news once before asking for data.
JAR = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR))
CSRF = {"meta": ""}


def xsrf_cookie():
    for c in JAR:
        if c.name == "XSRF-TOKEN":
            return urllib.parse.unquote(c.value)
    return ""


def start_session():
    page = request(f"{BASE}/news", session=False)
    m = re.search(r'<meta name="csrf-token" content="([^"]+)"', page)
    CSRF["meta"] = m.group(1) if m else ""
    if not (CSRF["meta"] or xsrf_cookie()):
        raise RuntimeError("Loaded babylonbee.com/news but got no anti-forgery token - "
                           "the site may have changed.")


def request(url, body=None, tries=4, session=True):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9",
               "Accept-Language": "en-US,en;q=0.9"}
    if data is not None:
        headers.update({
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": BASE,
            "Referer": f"{BASE}/news",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
        })
    last = None
    for attempt in range(tries):
        if data is not None:
            tok = xsrf_cookie()
            if tok:
                headers["X-XSRF-TOKEN"] = tok
            if CSRF["meta"]:
                headers["X-CSRF-TOKEN"] = CSRF["meta"]
        try:
            req = urllib.request.Request(url, data=data, headers=headers,
                                         method="POST" if data else "GET")
            with OPENER.open(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code == 419 and session:   # token expired: get a fresh one and retry
                start_session()
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Could not reach {url}: {last}")


def parse_time(s):
    return dt.datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")


def fetch_listing(oldest_needed):
    """Article list, newest first, back to `oldest_needed`."""
    arts, skip = [], 0
    for _ in range(MAX_PAGES):
        raw = request(f"{BASE}/loadArticles", {"category": "latest", "sort": "desc",
                                               "skip": skip, "take": PAGE_SIZE,
                                               "isAuthor": False})
        batch = json.loads(raw).get("articles") or []
        if not batch:
            break
        for a in batch:
            if a.get("is_video") or not str(a.get("path", "")).startswith("/news/"):
                continue
            arts.append({
                "path": a["path"],
                "title": html.unescape(a.get("title", "")).strip(),
                "time": parse_time(a["published_on"]),
                "img": a.get("imagePath") or "",
                "comments": int(a.get("commentCount") or 0),
            })
        skip += len(batch)
        if parse_time(batch[-1]["published_on"]) < oldest_needed:
            break
        time.sleep(1)
    return arts


def slug(url):
    return "/news/" + url.split("/news/", 1)[1].split("?")[0].strip("/")


def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    items = data["headlines"]
    known = {slug(h["url"]) for h in items}

    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    start_session()
    oldest_entry = min(dt.datetime.strptime(h["date"], "%Y-%m-%d") for h in items)
    listing = fetch_listing(oldest_entry - dt.timedelta(days=WINDOW_DAYS + 2))

    # Sanity check: the Bee publishes ~8 articles a day. If the list is tiny,
    # something is wrong (blocked, site changed) - stop instead of writing bad data.
    if len(listing) < 300:
        raise RuntimeError(f"Only {len(listing)} articles came back from the Bee - "
                           "the site may be blocking this job or has changed. "
                           "Nothing was updated.")
    by_path = {a["path"]: a for a in listing}

    # 1) look for new credited articles
    added = []
    cutoff = now - dt.timedelta(days=LOOKBACK_DAYS)
    for a in listing:
        if a["time"] < cutoff or a["path"] in known:
            continue
        page = request(BASE + a["path"])
        text = re.sub(r"<[^>]+>", " ", page)
        if CREDIT.search(text):
            items.append({
                "headline": a["title"],
                "date": a["time"].strftime("%Y-%m-%d"),
                "img": a["img"],
                "url": BASE + a["path"],
            })
            known.add(a["path"])
            added.append(a["title"])
        time.sleep(0.5)

    # 2) refresh comment counts and percentiles
    for h in items:
        a = by_path.get(slug(h["url"]))
        if not a:
            continue  # keep whatever it had
        win = [b for b in listing if b["path"] != a["path"]
               and abs((b["time"] - a["time"]).total_seconds()) <= WINDOW_DAYS * 86400]
        if not win:
            continue
        below = sum(1 for b in win if b["comments"] < a["comments"])
        ties = sum(1 for b in win if b["comments"] == a["comments"])
        h["comments"] = a["comments"]
        h["pct"] = round(100 * (below + ties / 2) / len(win))

    items.sort(key=lambda h: h["date"], reverse=True)
    data["headlines"] = items
    data["updated"] = now.replace(microsecond=0).isoformat() + "Z"
    DATA.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Checked {len(listing)} Bee articles; {len(items)} headlines listed.")
    print("New today: " + ("; ".join(added) if added else "none"))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # make the GitHub run fail loudly (-> email)
        print(f"UPDATE FAILED: {e}", file=sys.stderr)
        sys.exit(1)
