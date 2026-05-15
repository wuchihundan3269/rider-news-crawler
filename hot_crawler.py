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
    """知乎热榜 - daily-hot-api (Vercel)，降级用 weibo-hot-api 镜像"""
    # 方案1: daily-hot-api（GitHub Actions 境外服务器可访问 Vercel）
    candidates = [
        "https://daily-hot-api.vercel.app/zhihu",
        "https://hot-api.vercel.app/zhihu",
        "https://api.hotlist.online/zhihu",
    ]
    for api_url in candidates:
        try:
            r = requests.get(api_url, timeout=12, headers={"User-Agent": COMMON_UA})
            if r.status_code == 200:
                data = r.json()
                # 通用结构尝试: data 为列表，或 {data: [...]}
                raw = data if isinstance(data, list) else data.get("data", [])
                if raw:
                    rows = []
                    for i, item in enumerate(raw[:10]):
                        word = item.get("title", item.get("name", item.get("word", "")))
                        hot  = str(item.get("hot", item.get("hotScore", item.get("num", ""))))
                        link = item.get("url", item.get("link", "https://www.zhihu.com/hot"))
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
                    if rows:
                        return rows
        except Exception:
            continue

    # 方案2: 爬 tophub.today 知乎热榜
    try:
        r = requests.get("https://tophub.today/n/Q1Vd5Ko85D", timeout=15,
                         headers={"User-Agent": COMMON_UA})
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            rows = []
            for i, row in enumerate(soup.select("tr")[:10]):
                a = row.find("a")
                if not a:
                    continue
                word = a.get_text(strip=True)
                link = a.get("href", "https://www.zhihu.com/hot")
                tds = row.find_all("td")
                cell_text = tds[2].get_text(strip=True) if len(tds) > 2 else ""
                m = re.search(r"(\d+)\s*万?热度", cell_text)
                hot = m.group(1) if m else ""
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
            if rows:
                return rows
    except Exception as e:
        print(f"  [zhihu-tophub] 报错: {e}")

    print("  [zhihu] 所有数据源均失败")
    return []


def fetch_douyin():
    """抖音热搜 - tophub.today（稳定爬虫，含真实视频链接和播放量）"""
    try:
        url = "https://tophub.today/n/DpQvNABoNE"
        r = requests.get(url, timeout=15, headers={"User-Agent": COMMON_UA})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        rows = []
        rank = 1
        for row in soup.select("tr"):
            a = row.find("a")
            if not a:
                continue
            word = a.get_text(strip=True)
            link = a.get("href", f"https://www.douyin.com/search/{requests.utils.quote(word)}")
            tds = row.find_all("td")
            cell_text = tds[2].get_text(strip=True) if len(tds) > 2 else ""
            m = re.search(r"(\d+)次播放", cell_text)
            hot = m.group(1) if m else ""
            if word:
                rows.append({
                    "id": f"douyin_{rank:02d}",
                    "platform": "douyin",
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
