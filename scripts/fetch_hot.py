#!/usr/bin/env python3
"""
fetch_hot.py — 抓取各平台热榜，输出 data/hot.json
支持平台：微博、百度、抖音、快手
在 GitHub Actions 环境中运行，无 CORS 限制。

用法：
  python scripts/fetch_hot.py --output data/hot.json
"""

import json
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

BJ_TZ = timezone(timedelta(hours=8))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

PLATFORM_META = {
    "weibo":    {"name": "微博",  "logo_url": "https://favicon.im/weibo.com?larger=true",    "link": "https://s.weibo.com/top/summary"},
    "baidu":    {"name": "百度",  "logo_url": "https://favicon.im/baidu.com?larger=true",    "link": "https://top.baidu.com/board?tab=realtime"},
    "douyin":   {"name": "抖音",  "logo_url": "https://favicon.im/tiktok.com?larger=true",   "link": "https://www.douyin.com/search/%E7%83%AD%E6%90%9C"},
    "kuaishou": {"name": "快手",  "logo_url": "https://favicon.im/kuaishou.com?larger=true", "link": "https://www.kuaishou.com/"},
}


def fetch_weibo(timeout=10):
    """微博热搜（官方接口）"""
    try:
        r = requests.get(
            "https://weibo.com/ajax/side/hotSearch",
            headers={**HEADERS, "Referer": "https://weibo.com/"},
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        realtime = data.get("data", {}).get("realtime", [])
        items = []
        for i, item in enumerate(realtime[:10]):
            word = item.get("word", "").strip()
            if not word:
                continue
            items.append({
                "rank": i + 1,
                "text": word,
                "url": f"https://s.weibo.com/weibo?q={requests.utils.quote(word)}",
            })
        print(f"[weibo] {len(items)} 条")
        return items
    except Exception as e:
        print(f"[weibo] 失败: {e}")
        return []


def fetch_baidu(timeout=10):
    """百度热搜（官方接口）"""
    try:
        r = requests.get(
            "https://top.baidu.com/api/board?platform=wise&tab=realtime",
            headers={**HEADERS, "Referer": "https://top.baidu.com/"},
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        # 结构：data.cards[].content[].content[].word
        raw_items = []
        for card in data.get("data", {}).get("cards", []):
            for section in card.get("content", []):
                for item in section.get("content", []):
                    word = item.get("word", "").strip()
                    if word and word != "undefined":
                        raw_items.append(item)
        items = []
        for i, item in enumerate(raw_items[:10]):
            word = item.get("word", "").strip()
            url = item.get("url") or f"https://www.baidu.com/s?wd={requests.utils.quote(word)}"
            items.append({"rank": i + 1, "text": word, "url": url})
        print(f"[baidu] {len(items)} 条")
        return items
    except Exception as e:
        print(f"[baidu] 失败: {e}")
        return []


def fetch_douyin(timeout=10):
    """抖音热榜（freejk API）"""
    try:
        r = requests.get(
            "https://api.freejk.com/shuju/hotlist/douyin",
            headers=HEADERS,
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 200 or not isinstance(data.get("data"), list):
            raise ValueError(f"格式异常: code={data.get('code')}")
        items = []
        for i, item in enumerate(data["data"][:10]):
            text = (item.get("title") or item.get("name") or "").strip()
            if not text:
                continue
            items.append({
                "rank": i + 1,
                "text": text,
                "url": item.get("url") or item.get("mobileUrl") or PLATFORM_META["douyin"]["link"],
            })
        print(f"[douyin] {len(items)} 条")
        return items
    except Exception as e:
        print(f"[douyin] 失败: {e}")
        return []


def fetch_kuaishou(timeout=10):
    """快手热榜（freejk API）"""
    try:
        r = requests.get(
            "https://api.freejk.com/shuju/hotlist/kuaishou",
            headers=HEADERS,
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 200 or not isinstance(data.get("data"), list):
            raise ValueError(f"格式异常: code={data.get('code')}")
        items = []
        for i, item in enumerate(data["data"][:10]):
            text = (item.get("title") or item.get("name") or "").strip()
            if not text:
                continue
            items.append({
                "rank": i + 1,
                "text": text,
                "url": item.get("url") or item.get("mobileUrl") or PLATFORM_META["kuaishou"]["link"],
            })
        print(f"[kuaishou] {len(items)} 条")
        return items
    except Exception as e:
        print(f"[kuaishou] 失败: {e}")
        return []


FETCHERS = {
    "weibo":    fetch_weibo,
    "baidu":    fetch_baidu,
    "douyin":   fetch_douyin,
    "kuaishou": fetch_kuaishou,
}


def main():
    parser = argparse.ArgumentParser(description="抓取热榜数据")
    parser.add_argument("--output", default="data/hot.json", help="输出文件路径")
    args = parser.parse_args()

    now = datetime.now(BJ_TZ)
    platforms = []
    for pid, fetcher in FETCHERS.items():
        meta = PLATFORM_META[pid]
        items = fetcher()
        platforms.append({
            "id":       pid,
            "name":     meta["name"],
            "logo_url": meta["logo_url"],
            "link":     meta["link"],
            "items":    items,
        })

    output = {
        "updated_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "platforms":  platforms,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] hot.json 已生成: {args.output}")
    for p in platforms:
        print(f"     {p['name']}: {len(p['items'])} 条")


if __name__ == "__main__":
    main()
