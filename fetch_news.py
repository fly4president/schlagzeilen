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
MAX_AGE_BY_CATEGORY = {"health": 7, "science": 7}  # Bereiche mit wenigen neuen Artikeln
MAX_PER_FEED = 40
UA = "Mozilla/5.0 (compatible; NachrichtenApp/1.0)"

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "media": "http://search.yahoo.com/mrss/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}
TAG_RE = re.compile(r"<[^>]+>")
AD_RE = re.compile(r"\s*\(?(anzeige|werbung|sponsored|advertorial|deal|deals)\b\)?\s*[:|–-]", re.I)
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
        if AD_RE.match(title):  # bezahlte Beitraege, die manche Feeds untermischen
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


# ---------- "Mehr zum Thema": aehnliche Artikel anderer Quellen ----------
STOP = set("""
aber alle allem allen aller alles also auch auf aus bei beim bereits bis bisher bleibt dabei damit dann
darf darum dass davon dazu dem den denen der deren des deshalb dessen diese diesem diesen dieser dieses doch
dort durch eine einem einen einer eines einige erst erste ersten etwa etwas euro fast ganz gegen geht gibt
gilt haben habe hat hatte hätte heute hier hinter immer ihre ihrem ihren ihrer jahr jahre jahren jetzt kann
kein keine keinen könnte kommt lange lassen lässt laut mehr mehrere sich mehr muss müssen nach nachdem neue
neuen neuer neues nicht noch nun nur oder ohne rund schon sehr seid sein seine seinem seinen seiner seit
selbst sich sind sollen soll sondern sowie statt steht über unter viel viele vielen vom von vor wahl wann
war waren warum was weil weiter weitere welche wenn werden wieder wird wurde wurden zum zur zwei zwischen
diesem dürfen will wollen woche wochen montag dienstag mittwoch donnerstag freitag samstag sonntag
news live ticker liveblog newsblog aktuell aktuelle meldung bericht prozent millionen milliarden menschen
deutschland deutschen deutsche heißt sagt sagte zeigt zeigen neu ersten letzten künftig künftigen gerade
""".split())
WORD_RE = re.compile(r"[a-zäöüß0-9]+")


def tokens(text):
    out = []
    for w in WORD_RE.findall(text.lower()):
        if len(w) < 4 or w in STOP or w.isdigit():
            continue
        out.append(w[:7])  # grober Wortstamm: "Stabschefs" ~ "Stabschef"
    return out


def add_related(articles, threshold=0.36, max_related=8, max_hours=48):
    import math
    from collections import Counter
    vecs = []
    for a in articles:
        tf = Counter(tokens(a["title"]) * 2 + tokens(a["summary"]))
        vecs.append(tf)
    df = Counter(t for v in vecs for t in v)
    n = len(articles)
    idf = {t: math.log(n / c) for t, c in df.items() if c > 1}  # Wort nur in 1 Artikel: hilft nicht
    weighted = []
    for v in vecs:
        w = {t: c * idf[t] for t, c in v.items() if t in idf}
        norm = math.sqrt(sum(x * x for x in w.values())) or 1
        weighted.append({t: x / norm for t, x in w.items()})
    index = {}
    for i, w in enumerate(weighted):
        for t in w:
            index.setdefault(t, []).append(i)
    times = [datetime.fromisoformat(a["date"]) if a["date"] else None for a in articles]
    for i, w in enumerate(weighted):
        scores = {}
        for t, x in w.items():
            for j in index[t]:
                if j != i:
                    scores[j] = scores.get(j, 0) + x * weighted[j][t]
        best = {}
        for j, s in scores.items():
            if s < threshold or articles[j]["source"] == articles[i]["source"]:
                continue
            if times[i] and times[j] and abs(times[i] - times[j]) > timedelta(hours=max_hours):
                continue
            # pro Zeitung nur der passendste Artikel (Spiegel und Spiegel Ausland zaehlen als eine)
            paper = articles[j]["source"].split()[0]
            if paper == articles[i]["source"].split()[0]:
                continue
            if s > best.get(paper, (0, None))[0]:
                best[paper] = (s, j)
        ranked = sorted(best.values(), reverse=True)[:max_related]
        articles[i]["related"] = [articles[j]["id"] for _, j in ranked]


def main():
    cfg = json.loads((BASE / "feeds.json").read_text(encoding="utf-8"))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch, cfg["feeds"]))

    now = datetime.now(timezone.utc)
    seen, articles = set(), []
    # Speziellere Feeds zuerst, damit Doppelte in der genaueren Kategorie landen
    # Allgemeine Bereiche zuletzt; alle anderen (z. B. Märkte, Gesundheit, Regional) = 0
    rank = {"news": 2, "business": 1, "science": 1, "world": 1}
    for items, _ in sorted(results, key=lambda r: rank.get(r[0][0]["category"], 0) if r[0] else 0):
        for a in items:
            key = a["link"].split("?")[0]
            if key in seen:
                continue
            max_age = timedelta(days=MAX_AGE_BY_CATEGORY.get(a["category"], MAX_AGE_DAYS))
            if a["date"] and datetime.fromisoformat(a["date"]) < now - max_age:
                continue
            seen.add(key)
            articles.append(a)
    articles.sort(key=lambda a: a["date"] or "", reverse=True)
    import hashlib
    for a in articles:
        a["id"] = hashlib.sha1(a["link"].encode()).hexdigest()[:10]
    add_related(articles)

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
