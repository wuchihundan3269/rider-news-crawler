# -*- coding: utf-8 -*-
"""
hot_crawler.py  -  热搜爬虫
定时抓取微博/抖音/百度/知乎 TOP10 热搜，写入 Supabase hot_search 表
"""
import os, re, requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

SUPABASE_URL = os.environ["SUPABASE_URL"]
SERVICE_KEY  = os.environ["SUPABASE_SERVICE_KEY"]

HDR = {
    "apikey":        SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "resolution=merge-duplicates",
}

COMMON_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def fetch_weibo():
    """微博热搜 - 官方接口"""
    try:
        url = "https://weibo.com/ajax/side/hotSearch"
        r = requests.get(url, timeout=15, headers={"User-Agent": COMMON_UA, "Referer": "https://weibo.com/"})
        r.raise_for_status()
        data = r.json()
        items = data.get("data", {}).get("realtime", [])
        rows = []
        rank = 1
        for item in items:
            word = item.get("word", "")
            if not word or item.get("is_ad"):
                continue
            hot = str(item.get("num", ""))
            link = f"https://s.weibo.com/weibo?q=%23{requests.utils.quote(word)}%23"
            rows.append({
                "id": f"weibo_{rank:02d}",
                "platform": "weibo",
                "rank": rank,
                "title": word,
                "hot_score": hot,
                "url": link,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            rank += 1
            if rank > 10:
                break
        return rows
    except Exception as e:
        print(f"  [weibo] 报错: {e}")
        return []


def fetch_baidu():
    """百度热搜 - 官方实时热点 JSON 接口（三层嵌套结构）"""
    try:
        url = "https://top.baidu.com/api/board?platform=wise&tab=realtime"
        r = requests.get(url, timeout=15, headers={
            "User-Agent": COMMON_UA,
            "Referer": "https://top.baidu.com/board?tab=realtime",
        })
        r.raise_for_status()
        data = r.json()
        # 返回结构: {data: {cards: [{content: [{content: [{word, hotScore, url}]}]}]}}
        cards = data.get("data", {}).get("cards", [])
        items = []
        for card in cards:
            for outer in card.get("content", []):
                items.extend(outer.get("content", []))
        rows = []
        rank = 1
        for item in items:
            word = item.get("word", "")
            if not word:
                continue
            hot = str(item.get("hotScore", ""))
            link = item.get("url", f"https://www.baidu.com/s?wd={requests.utils.quote(word)}")
            rows.append({
                "id": f"baidu_{rank:02d}",
                "platform": "baidu",
                "rank": rank,
                "title": word,
                "hot_score": hot,
                "url": link,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            rank += 1
            if rank > 10:
                break
        return rows
    except Exception as e:
        print(f"  [baidu] 报错: {e}")
        return []


def fetch_zhihu():
    """知乎热榜 - 60s-api.viki.moe（Deno Deploy，GitHub Actions 可访问）"""
    try:
        url = "https://60s-api.viki.moe/v2/zhihu"
        r = requests.get(url, timeout=15, headers={"User-Agent": COMMON_UA})
        r.raise_for_status()
        data = r.json()
        items = data.get("data", [])
        rows = []
        for i, item in enumerate(items[:10]):
            word = item.get("title", "")
            hot  = str(item.get("heat", item.get("hot", "")))
            link = item.get("url", "https://www.zhihu.com/hot")
            if word:
                rows.append({
                    "id": f"zhihu_{i+1:02d}",
                    "platform": "zhihu",
                    "rank": i + 1,
                    "title": word,
                    "hot_score": hot,
                    "url": link,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
        return rows
    except Exception as e:
        print(f"  [zhihu] 报错: {e}")
        return []


def fetch_douyin():
    """抖音热搜 - 官方接口"""
    try:
        url = "https://www.douyin.com/aweme/v1/web/hot/search/list/?device_platform=webapp&aid=6383&channel=channel_pc_web&detail_list=1"
        r = requests.get(url, timeout=15, headers={
            "User-Agent": COMMON_UA,
            "Referer": "https://www.douyin.com/",
        })
        r.raise_for_status()
        data = r.json()
        items = data.get("data", {}).get("word_list", [])
        rows = []
        for i, item in enumerate(items[:10]):
            word = item.get("word", "")
            hot = str(item.get("hot_value", ""))
            link = f"https://www.douyin.com/search/{requests.utils.quote(word)}"
            if word:
                rows.append({
                    "id": f"douyin_{i+1:02d}",
                    "platform": "douyin",
                    "rank": i + 1,
                    "title": word,
                    "hot_score": hot,
                    "url": link,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
        return rows
    except Exception as e:
        print(f"  [douyin] 报错: {e}")
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


PLATFORMS = [
    ("微博", fetch_weibo),
    ("百度", fetch_baidu),
    ("知乎", fetch_zhihu),
    ("抖音", fetch_douyin),
]


def main():
    print(f"hot_crawler start: {datetime.now(timezone.utc).isoformat()}")
    for name, fn in PLATFORMS:
        print(f"fetching {name}...")
        rows = fn()
        print(f"  got {len(rows)} items")
        upsert(rows)
    print("done.")


if __name__ == "__main__":
    main()
