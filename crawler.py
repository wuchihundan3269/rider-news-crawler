# -*- coding: utf-8 -*-
import os, re, requests, hashlib
from datetime import datetime, timezone
from xml.etree import ElementTree

SUPABASE_URL         = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

HDR = {
    "apikey":        SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "resolution=ignore-duplicates",
}

FEEDS = [
    "https://news.google.com/rss/search?q=%E9%AA%91%E6%89%8B+%E7%BE%8E%E5%9B%A2&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
    "https://news.google.com/rss/search?q=%E9%AA%91%E6%89%8B%E5%A4%96%E5%8D%96&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
    "https://news.google.com/rss/search?q=%E9%AA%91%E6%89%8B%E9%85%8D%E9%80%81&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
]
CATS = ["\u884c\u4e1a\u52a8\u6001", "\u653f\u7b56\u6cd5\u89c4", "\u6536\u5165\u798f\u5229", "\u5b89\u5168\u4fdd\u969c"]

def extract_source(item):
    # \u5c1d\u8bd5\u4ece <source> \u6807\u7b7e\u8bfb\u53d6
    src_el = item.find("source")
    if src_el is not None:
        src = (src_el.text or "").strip()
        if src and src.lower() not in ("google news", ""):
            return src
    # \u4ece\u539f\u59cb\u6807\u9898\u5c3e\u90e8\u63d0\u53d6\uff08\u683c\u5f0f\uff1a\u6807\u9898 - \u5a92\u4f53\u540d\uff09
    raw_title = item.findtext("title", "")
    m = re.search(r"\s+-\s+([^-]+)$", raw_title)
    if m:
        src = m.group(1).strip()
        if src:
            return src
    return "\u7efc\u5408\u5a92\u4f53"

def fetch(url):
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        root = ElementTree.fromstring(r.content)
        out = []
        for item in root.findall(".//item")[:8]:
            raw_title = item.findtext("title", "")
            title = re.sub(r"\s*-\s*[^-]+$", "", raw_title).strip()
            link  = item.findtext("link", "").strip()
            source = extract_source(item)
            if title and link:
                out.append({"title": title, "url": link, "source": source})
        return out
    except Exception as e:
        print(f"fetch error {url}: {e}"); return []

def upsert(articles):
    rows = [{
        "id":           hashlib.md5(a["url"].encode()).hexdigest()[:16],
        "title":        a["title"],
        "summary":      a["title"],
        "category":     CATS[i % len(CATS)],
        "source":       a.get("source", "\u7efc\u5408\u5a92\u4f53"),
        "url":          a["url"],
        "published_at": datetime.now(timezone.utc).isoformat(),
        "is_hot":       i < 3,
    } for i, a in enumerate(articles)]
    if not rows: return
    r = requests.post(f"{SUPABASE_URL}/rest/v1/news", headers=HDR, json=rows)
    print(f"upsert {r.status_code}: {len(rows)} rows")
    if r.status_code not in (200, 201): print(r.text[:300])

def main():
    all_a = []
    for f in FEEDS:
        a = fetch(f); all_a.extend(a); print(f"  {len(a)} from {f}")
    seen, dedup = set(), []
    for a in all_a:
        if a["url"] not in seen:
            seen.add(a["url"]); dedup.append(a)
    print(f"unique: {len(dedup)}")
    upsert(dedup[:20])

if __name__ == "__main__":
    main()
