"""Holt alle Feeds aus feeds.json und schreibt docs/news.json.

Nur Python-Standardbibliothek, damit es ueberall ohne Installation laeuft.
"""
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "docs" / "news.json"
MAX_AGE_DAYS = 3
MAX_PER_FEED = 40
UA = "Mozilla/5.0 (compatible; NachrichtenApp/1.0)"

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "media": "http://search.yahoo.com/mrss/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}
TAG_RE = re.compile(r"<[^>]+>")
IMG_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)


def clean(text, limit=None):
    if not text:
        return ""
    text = html.unescape(TAG_RE.sub(" ", text))
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + " …"
    return text


def parse_date(value):
    if not value:
        return None
    value = value.strip()
    try:
        d = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def find_image(item, raw_html):
    for path in ("media:content", "media:thumbnail", "media:group/media:content"):
        for el in item.findall(path, NS):
            url = el.get("url")
            if url and (el.get("medium") in (None, "image") or "image" in (el.get("type") or "image")):
                return url
    enc = item.find("enclosure")
    if enc is not None and (enc.get("type") or "").startswith("image"):
        return enc.get("url")
    m = IMG_RE.search(raw_html or "")
    return html.unescape(m.group(1)) if m else None


def text_of(item, *paths):
    for p in paths:
        el = item.find(p, NS)
        if el is not None and (el.text or "").strip():
            return el.text
    return ""


def parse_feed(data, feed):
    root = ET.fromstring(data)
    items = []
    if root.tag.endswith("feed"):  # Atom
        for e in root.findall("atom:entry", NS):
            link = ""
            for l in e.findall("atom:link", NS):
                if l.get("rel") in (None, "alternate"):
                    link = l.get("href")
                    break
            raw = text_of(e, "atom:summary", "atom:content")
            items.append({
                "title": text_of(e, "atom:title"),
                "link": link,
                "date": text_of(e, "atom:published", "atom:updated"),
                "raw": raw,
                "el": e,
            })
    else:  # RSS 2.0 / RDF
        for e in root.iter():
            if e.tag in ("item", "{http://purl.org/rss/1.0/}item"):
                raw = text_of(e, "description", "content:encoded", "{http://purl.org/rss/1.0/}description")
                items.append({
                    "title": text_of(e, "title", "{http://purl.org/rss/1.0/}title"),
                    "link": text_of(e, "link", "{http://purl.org/rss/1.0/}link"),
                    "date": text_of(e, "pubDate", "dc:date"),
                    "raw": raw,
                    "el": e,
                })
    out = []
    for it in items[:MAX_PER_FEED]:
        title = clean(it["title"])
        link = (it["link"] or "").strip()
        if not title or not link:
            continue
        d = parse_date(it["date"])
        summary = clean(it["raw"], 280)
        if summary.lower() in ("none", "null", title.lower()):
            summary = ""
        out.append({
            "title": title,
            "link": link,
            "summary": summary,
            "image": find_image(it["el"], it["raw"]),
            "date": d.isoformat() if d else None,
            "source": feed["name"],
            "category": feed["category"],
        })
    return out


def fetch(feed):
    req = urllib.request.Request(feed["url"], headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            items = parse_feed(r.read(), feed)
        print(f"OK    {feed['name']:<16} {len(items)} Artikel")
        return items, None
    except Exception as exc:  # ein kaputter Feed soll die anderen nicht stoppen
        print(f"FEHLER {feed['name']:<15} {exc}", file=sys.stderr)
        return [], feed["name"]


def main():
    cfg = json.loads((BASE / "feeds.json").read_text(encoding="utf-8"))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch, cfg["feeds"]))

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    seen, articles = set(), []
    # Speziellere Feeds zuerst, damit Doppelte in der genaueren Kategorie landen
    rank = {"news": 2, "business": 1}  # alle anderen (Märkte, Technik, Regional) = 0
    for items, _ in sorted(results, key=lambda r: rank.get(r[0][0]["category"], 0) if r[0] else 0):
        for a in items:
            key = a["link"].split("?")[0]
            if key in seen:
                continue
            if a["date"] and datetime.fromisoformat(a["date"]) < cutoff:
                continue
            seen.add(key)
            articles.append(a)
    articles.sort(key=lambda a: a["date"] or "", reverse=True)

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "updated": datetime.now(timezone.utc).isoformat(),
        "categories": cfg["categories"],
        "sources": [{"name": f["name"], "category": f["category"]} for f in cfg["feeds"]],
        "failed": [name for _, name in results if name],
        "articles": articles,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"\n{len(articles)} Artikel gespeichert in {OUT}")


if __name__ == "__main__":
    main()
