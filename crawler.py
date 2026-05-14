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
CATS = ["琛屼笟鍔ㄦ€?, "鏀跨瓥娉曡", "鏀跺叆绂忓埄", "瀹夊叏淇濋殰"]

def fetch(url):
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        root = ElementTree.fromstring(r.content)
        out = []
        for item in root.findall(".//item")[:8]:
            title = re.sub(r"\s*-\s*[^-]+$", "", item.findtext("title","")).strip()
            link  = item.findtext("link","").strip()
            if title and link:
                out.append({"title": title, "url": link})
        return out
    except Exception as e:
        print(f"fetch error {url}: {e}"); return []

def upsert(articles):
    rows = [{
        "id":           hashlib.md5(a["url"].encode()).hexdigest()[:16],
        "title":        a["title"],
        "summary":      a["title"],
        "category":     CATS[i % len(CATS)],
        "source":       "Google News",
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