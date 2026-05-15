# -*- coding: utf-8 -*-
"""
hot_crawler.py  -  热搜爬虫
定时抓取微博/抖音/百度/知乎 TOP10 热搜，写入 Supabase hot_search 表
"""
import os, requests
from datetime import datetime, timezone

SUPABASE_URL = os.environ["SUPABASE_URL"]
SERVICE_KEY  = os.environ["SUPABASE_SERVICE_KEY"]

HDR = {
    "apikey":        SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "resolution=merge-duplicates",
}

# tenapi.cn 各平台接口
PLATFORMS = [
    {"id": "weibo",  "url": "https://tenapi.cn/v2/weibohot",  "name": "微博"},
    {"id": "douyin", "url": "https://tenapi.cn/v2/douyinhot", "name": "抖音"},
    {"id": "baidu",  "url": "https://tenapi.cn/v2/baiduhot",  "name": "百度"},
    {"id": "zhihu",  "url": "https://tenapi.cn/v2/zhihuhot",  "name": "知乎"},
]

# 平台对应的搜索链接模板
SEARCH_URL = {
    "weibo":  "https://s.weibo.com/weibo?q={}",
    "douyin": "https://www.douyin.com/search/{}",
    "baidu":  "https://www.baidu.com/s?wd={}",
    "zhihu":  "https://www.zhihu.com/search?type=content&q={}",
}

def fetch_hot(platform):
    try:
        r = requests.get(
            platform["url"],
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        )
        r.raise_for_status()
        data = r.json()
        items = data.get("data", [])
        rows = []
        for i, item in enumerate(items[:10]):
            title = item.get("name") or item.get("title") or item.get("word") or ""
            hot   = str(item.get("hot") or item.get("hotScore") or item.get("heat") or "")
            url   = item.get("link") or item.get("url") or SEARCH_URL[platform["id"]].format(
                requests.utils.quote(title)
            )
            if title:
                rows.append({
                    "id":         f"{platform['id']}_{i+1:02d}",
                    "platform":   platform["id"],
                    "rank":       i + 1,
                    "title":      title,
                    "hot_score":  hot,
                    "url":        url,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
        return rows
    except Exception as e:
        print(f"  [{platform['id']}] 报错: {e}")
        return []

def upsert(rows):
    if not rows:
        return
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/hot_search",
        headers=HDR,
        json=rows
    )
    print(f"  upsert {r.status_code}: {len(rows)} rows")
    if r.status_code not in (200, 201):
        print(f"  error: {r.text[:300]}")

def main():
    print(f"hot_crawler start: {datetime.now(timezone.utc).isoformat()}")
    for p in PLATFORMS:
        print(f"fetching {p['name']}...")
        rows = fetch_hot(p)
        print(f"  got {len(rows)} items")
        upsert(rows)
    print("done.")

if __name__ == "__main__":
    main()
