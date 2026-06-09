#!/usr/bin/env python3
"""
fetch_news_v3.py — 骑手行业新闻独立抓取脚本
数据来源方案：学城文档 2765848623

功能：
  - 直接读取 trendradar-config/config.yaml，无需 TrendRadar
  - 三管道：RSS订阅(P0-P5媒体) + 搜索引擎关键词(Bing News) + 热榜平台
  - 六分类：骑手故事(rider_story) / 骑手关怀(care) / 行业观察(policy) / 宏观报告(report) / 平台动作(platform) / 舆论信息(opinion)
  - 媒体优先级：P0→P5，去重时保留最高优先级来源
  - 排序：时效优先，同天按P0→P5
  - 输出：TrendRadar 兼容格式（output/news/YYYY-MM-DD.json）

用法：
  python scripts/fetch_news_v3.py
  python scripts/fetch_news_v3.py --date 2025-06-15
  python scripts/fetch_news_v3.py --output output/news/2025-06-15.json
"""

import os
import sys
import json
import hashlib
import argparse
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser
import requests
import yaml
from dateutil import parser as dateparser
try:
    from bs4 import BeautifulSoup as _BS
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False


def fetch_og_image(url: str, timeout: int = 6) -> str | None:
    """抓取文章页面的 og:image 元标签，返回图片 URL 或 None"""
    if not url or not _HAS_BS4:
        return None
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        soup = _BS(resp.text, "html.parser")
        # 优先 og:image
        tag = soup.find("meta", property="og:image")
        if tag and tag.get("content"):
            return tag["content"].strip()
        # 备选 twitter:image
        tag = soup.find("meta", attrs={"name": "twitter:image"})
        if tag and tag.get("content"):
            return tag["content"].strip()
    except Exception:
        pass
    return None


def resolve_google_news_url(url: str, timeout: int = 5) -> str:
    """将 Google News RSS 中间链接解析为真实原始 URL

    Google News 重定向链：
      第1次 GET → 302 → 同一 URL（加 hl/gl/ceid 参数）
      第2次 GET → 302 → 真实原文 URL（仅在境外服务器上）
    因此必须手动跟随每一步重定向，不能用 allow_redirects=True。
    """
    if not url or "news.google.com" not in url:
        return url

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    current = url
    session = requests.Session()
    session.headers.update(headers)

    for _ in range(6):  # 最多跟随 6 次重定向
        try:
            resp = session.get(current, allow_redirects=False, timeout=timeout)
        except Exception:
            break

        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location", "")
            if not location:
                break
            # 处理相对路径
            if location.startswith("/"):
                from urllib.parse import urljoin
                location = urljoin(current, location)
            # 找到非 Google 的真实 URL
            if "news.google.com" not in location and location.startswith("http"):
                return location
            current = location
        else:
            # 非重定向响应，无法继续跟随
            break

    return url

# ── 路径配置 ──────────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
CONFIG_PATH  = PROJECT_ROOT / "trendradar-config" / "config.yaml"
WORDS_PATH   = PROJECT_ROOT / "trendradar-config" / "frequency_words.txt"
OUTPUT_DIR   = PROJECT_ROOT / "trendradar" / "output" / "news"

# ── 媒体优先级映射 ─────────────────────────────────────────────────────────────

PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4, "P5": 5}

# ── 工具函数 ──────────────────────────────────────────────────────────────────

def url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def clean_html(text: str, max_len: int = 300) -> str:
    """去除 HTML 标签，截断"""
    text = re.sub(r"<[^>]+>", "", text or "")
    text = text.strip().replace("\n", " ").replace("\r", "")
    text = re.sub(r"\s+", " ", text)
    return text[:max_len] + "…" if len(text) > max_len else text


def parse_time(entry) -> str:
    """解析 RSS 条目时间，返回 ISO 格式字符串"""
    for attr in ("published", "updated"):
        val = getattr(entry, attr, None)
        if val:
            try:
                dt = dateparser.parse(val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                # 转换为北京时间
                bj_tz = timezone(timedelta(hours=8))
                dt = dt.astimezone(bj_tz)
                return dt.strftime("%Y-%m-%dT%H:%M:%S")
            except Exception:
                pass
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%dT%H:%M:%S")


def title_similarity(a: str, b: str) -> float:
    """简单的标题相似度（基于字符集合 Jaccard）"""
    if not a or not b:
        return 0.0
    set_a = set(a)
    set_b = set(b)
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


# ── 关键词文件解析 ─────────────────────────────────────────────────────────────

def load_keyword_rules(words_path: Path) -> dict:
    """
    解析 frequency_words.txt，返回：
    {
      "rules": [(sub_tag, [[词1,词2], [词3]]), ...],  # AND组列表
      "global_filter": [词, ...]
    }
    """
    rules = []
    global_filter = []
    current_tag = None
    in_global = False

    if not words_path.exists():
        print(f"WARNING: 关键词文件不存在: {words_path}")
        return {"rules": [], "global_filter": []}

    with open(words_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[GLOBAL_FILTER]"):
                in_global = True
                current_tag = None
                continue
            if line.startswith("[") and line.endswith("]"):
                in_global = False
                current_tag = line[1:-1]
                rules.append((current_tag, []))
                continue
            if in_global:
                # 去掉行首的 '!' 前缀（frequency_words.txt 用 !词 表示过滤词）
                word = line.lstrip("!")
                if word:
                    global_filter.append(word)
            elif current_tag:
                # 解析 AND 词组（空格分隔）和 OR（| 分隔）
                if "|" in line:
                    # OR：每个词单独作为一个 AND 组
                    for word in line.split("|"):
                        word = word.strip()
                        if word:
                            rules[-1][1].append([word])
                else:
                    words = [w for w in line.split() if w]
                    if words:
                        rules[-1][1].append(words)

    return {"rules": rules, "global_filter": global_filter}


def match_sub_tags(title: str, summary: str, rules: list) -> list[str]:
    """
    根据标题+摘要匹配所有命中的子分类 tag（支持多标签共存）。

    优先级规则（来自 Wiki）：
    1. 舆论(opinion.*) 具有最高优先级——只要命中任意 opinion.* 标签，
       最终 category 强制为 opinion，但其他标签仍保留用于细粒度展示。
    2. 同一条新闻可同时命中多个标签（如 rider_story.positive + care.welfare）。
    """
    text = title + " " + summary
    matched = []
    seen_tags = set()
    for sub_tag, keyword_groups in rules:
        if sub_tag in seen_tags:
            continue
        for kw_group in keyword_groups:
            if all(kw in text for kw in kw_group):
                matched.append(sub_tag)
                seen_tags.add(sub_tag)
                break  # 该子分类已命中，跳到下一个子分类
    return matched


def match_sub_tag(title: str, summary: str, rules: list) -> str | None:
    """兼容旧调用：返回第一个命中的子分类 tag（已被 match_sub_tags 取代）"""
    tags = match_sub_tags(title, summary, rules)
    return tags[0] if tags else None


def is_global_filtered(title: str, summary: str, global_filter: list) -> bool:
    """检查是否命中全局过滤词"""
    text = title + " " + summary
    return any(word in text for word in global_filter)


def matches_base_keywords(title: str, summary: str, base_keywords: list) -> bool:
    """检查是否命中基础关键词（任意一个即可）
    支持空格分隔的 AND 复合词，如 '即时配送 骑手' 表示两个词都要出现
    """
    text = title + " " + summary
    for kw in base_keywords:
        parts = kw.split()
        if all(p in text for p in parts):
            return True
    return False


# 非外卖骑手排除词：含这些词说明是摩托车/自行车/赛车等无关骑手内容
_NON_DELIVERY_RIDER_WORDS = [
    "摩托车骑手", "摩托车手", "摩托车赛", "摩托车事故",
    "自行车骑手", "自行车手", "单车骑手",
    "赛车骑手", "越野骑手", "公路骑手", "山地骑手",
    "骑马", "马术骑手", "赛马骑手",
    "骑行爱好者", "骑行活动", "骑行比赛",
    "摩托骑手", "摩托手",
]

def is_non_delivery_rider(title: str, summary: str) -> bool:
    """判断是否为非外卖骑手内容（摩托车/自行车/赛车骑手等），是则返回 True（应丢弃）
    注意：只在文章已命中 base_keywords 后才调用，避免误杀
    """
    text = title + " " + summary
    # 如果含明确的外卖标识词，直接放行（不误杀）
    delivery_anchors = ["外卖", "配送", "美团", "饿了么", "京东外卖", "顺丰", "闪送", "达达", "即时配送"]
    if any(w in text for w in delivery_anchors):
        return False
    # 含非外卖骑手词则丢弃
    return any(w in text for w in _NON_DELIVERY_RIDER_WORDS)


# 外媒/聚合平台黑名单：标题末尾 " - 媒体名" 命中则丢弃
# 规则：含非中文字母域名后缀(.it/.com/.org 等)、已知外媒名、聚合平台
_FOREIGN_MEDIA_BLACKLIST = {
    # 聚合平台
    "MSN", "Yahoo", "Yahoo News", "Yahoo Finance",
    "Google News", "Apple News", "SmartNews", "Flipboard",
    "今日头条", "腾讯新闻", "网易新闻", "百度新闻", "搜狐新闻",
    # 已知外媒（英文名）
    "China Digital Times", "Radio Free Asia", "RFA",
    "Voice of America", "VOA", "BBC", "BBC Chinese",
    "Reuters", "AP", "AFP", "Bloomberg", "The Guardian",
    "New York Times", "Washington Post", "Financial Times",
    "South China Morning Post", "SCMP",
    "Nikkei", "Nikkei Asia",
    "Deutsche Welle", "DW",
    "The Diplomat", "Foreign Policy",
    "Asia Times", "Asia Nikkei",
}

import re as _re
_FOREIGN_DOMAIN_RE = _re.compile(
    r'\.(it|fr|de|jp|uk|au|ca|ru|kr|tw|hk|sg|us|eu|net|org|io|co)\s*$',
    _re.IGNORECASE
)

def is_foreign_media(title: str) -> bool:
    """从标题末尾 ' - 媒体名' 判断是否为外媒或聚合平台，是则返回 True（应丢弃）"""
    di = title.rfind(" - ")
    if di <= 0:
        return False
    media_name = title[di + 3:].strip()
    # 命中黑名单
    if media_name in _FOREIGN_MEDIA_BLACKLIST:
        return True
    # 媒体名含境外域名后缀（如 L'Unione Sarda.it）
    if _FOREIGN_DOMAIN_RE.search(media_name):
        return True
    # 媒体名全为 ASCII 且不在已知国内英文媒体白名单内
    _DOMESTIC_EN = {
        "Sina finance", "Sina Finance", "Sina News", "Sina",
        "People's Daily", "Xinhua", "Xinhua News",
        "CCTV", "CGTN", "China Daily", "Global Times",
        "Caixin", "Caixin Global", "The Paper", "Jiemian",
        "Yicai", "Yicai Global", "36Kr", "36kr",
        "Huxiu", "LatePost", "Titanium Media",
        "China News Service", "CNS",
    }
    if media_name and media_name.isascii() and media_name not in _DOMESTIC_EN:
        return True
    return False


# ── 分类映射 ──────────────────────────────────────────────────────────────────

# 子分类 → 一级分类（六分类体系 v2）
SUB_TAG_TO_CATEGORY = {
    # 骑手故事
    "rider_story.life":      "rider_story",
    "rider_story.positive":  "rider_story",
    "rider_story.accident":  "rider_story",
    "rider_story.incident":  "rider_story",
    "rider_story.career":    "rider_story",
    # 骑手关怀
    "care.welfare":          "care",
    "care.health":           "care",
    "care.station":          "care",
    "care.social":           "care",
    # 行业政策
    "policy.national":       "policy",
    "policy.labor":          "policy",
    "policy.local":          "policy",
    "policy.standard":       "policy",
    # 宏观报告（并入行业观察）
    "report.market":         "policy",
    "report.economy":        "policy",
    "report.research":       "policy",
    "report.season":         "policy",
    # 平台动作
    "platform.ops":          "platform",
    "platform.algo":         "platform",
    "platform.pay":          "platform",
    "platform.recruit":      "platform",
    "platform.safety":       "platform",
    "platform.data":         "platform",   # 经营数据/财报/公关
    # 舆论信息
    "opinion.rights":        "opinion",
    "opinion.media":         "opinion",
    "opinion.viral":         "opinion",
    "opinion.consumer":      "opinion",
    "opinion.merchant":      "opinion",
    "opinion.crisis":        "opinion",
}

# 子分类中文标签
SUB_TAG_LABEL = {
    # 骑手故事
    "rider_story.life":      "生活百态",
    "rider_story.positive":  "正面事迹",
    "rider_story.accident":  "安全事故",
    "rider_story.incident":  "群体事件",
    "rider_story.career":    "职业发展",
    # 骑手关怀
    "care.welfare":          "平台福利",
    "care.health":           "健康安全",
    "care.station":          "驿站设施",
    "care.social":           "社会关爱",
    # 行业政策
    "policy.national":       "国家政策",
    "policy.labor":          "劳动法规",
    "policy.local":          "地方政策",
    "policy.standard":       "行业标准",
    # 宏观报告
    "report.market":         "市场格局",
    "report.economy":        "宏观经济",
    "report.research":       "行业报告",
    "report.season":         "季节趋势",
    # 平台动作
    "platform.ops":          "运力调整",
    "platform.algo":         "算法规则",
    "platform.pay":          "收入费用",
    "platform.recruit":      "招募合作",
    "platform.safety":       "安全合规",
    "platform.data":         "经营数据",
    # 舆论信息
    "opinion.rights":        "权益争议",
    "opinion.media":         "媒体曝光",
    "opinion.viral":         "热搜发声",
    "opinion.consumer":      "消费者矛盾",
    "opinion.merchant":      "商家摩擦",
    "opinion.crisis":        "舆论发酵",
}


# ── RSS 抓取 ──────────────────────────────────────────────────────────────────

def _resolve_feed_url(url: str, timeout: int = 15) -> str:
    """对会返回 301/302 的 RSS URL（如百度新闻），用 requests 跟随重定向拿到真实 URL。
    feedparser 默认不跟随重定向，导致百度新闻 RSS 返回 0 条。
    """
    if not url:
        return url
    try:
        resp = requests.get(
            url,
            allow_redirects=True,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            }
        )
        # 如果最终 URL 与原始不同，说明发生了重定向
        if resp.url and resp.url != url:
            return resp.url
        # 如果内容是 XML/RSS，直接返回原 URL（feedparser 可以处理）
        ct = resp.headers.get("Content-Type", "")
        if "xml" in ct or "rss" in ct or "atom" in ct:
            return url
        # 否则返回最终 URL
        return resp.url or url
    except Exception:
        return url


def fetch_rss_feed(feed_cfg: dict, keyword_rules: dict, base_keywords: list,
                   max_age_days: int = 3) -> list[dict]:
    """抓取单个 RSS 源，返回过滤后的文章列表"""
    url      = feed_cfg.get("url", "")
    feed_id  = feed_cfg.get("id", "unknown")
    name     = feed_cfg.get("name", feed_id)
    priority = feed_cfg.get("priority", "P5")
    category = feed_cfg.get("category", "auto")
    tag      = feed_cfg.get("tag", "auto")

    if not url:
        return []

    # 对百度新闻等会 301 重定向的 URL，先用 requests 跟随重定向
    # feedparser 默认不跟随重定向，导致百度新闻 RSS 返回 0 条
    fetch_url = url
    if "news.baidu.com" in url or "163.com" in url:
        fetch_url = _resolve_feed_url(url)

    try:
        feed = feedparser.parse(fetch_url, request_headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        entries = feed.entries
        print(f"  [{priority}] {name}: 获取 {len(entries)} 条")
    except Exception as e:
        print(f"  [{priority}] {name}: 抓取失败 - {e}")
        return []

    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    for entry in entries:
        title   = entry.get("title", "").strip()
        summary = clean_html(entry.get("summary", entry.get("description", "")))
        url_str = entry.get("link", "").strip()

        if not title or not url_str:
            continue

        # 解析 Google News 中间链接为真实原始 URL
        url_str = resolve_google_news_url(url_str)

        # 时效过滤
        pub_str = parse_time(entry)
        try:
            pub_dt = datetime.fromisoformat(pub_str).replace(tzinfo=timezone.utc)
            if pub_dt < cutoff:
                continue
        except Exception:
            pass

        # 全局过滤
        if is_global_filtered(title, summary, keyword_rules["global_filter"]):
            continue

        # 基础关键词过滤：所有分类的源都必须命中骑手相关词才保留
        # （防止"新就业形态""平台用工"等宽泛关键词抓入大量无关文章）
        if not matches_base_keywords(title, summary, base_keywords):
            continue

        # 外媒/聚合平台过滤：只保留国内媒体来源
        if is_foreign_media(title):
            continue

        # 非外卖骑手过滤：排除摩托车/自行车/赛车骑手等无关内容
        if is_non_delivery_rider(title, summary):
            continue

        # 子分类打标（多标签）
        if tag != "auto":
            sub_tags = [tag]
        else:
            sub_tags = match_sub_tags(title, summary, keyword_rules["rules"])

        # 一级分类：
        #   - 固定分类源直接使用配置的 category
        #   - auto 源：按优先级规则决定分类
        #
        # 优先级规则（从高到低）：
        #   1. policy / care 有豁免权：事实性动作（政策发布、关爱落地）优先于观点性讨论
        #      只要同时命中 policy.* 或 care.* 标签，opinion 不得覆盖
        #   2. opinion 次优先：未被 policy/care 豁免时，opinion 仍高于 platform/report/rider_story
        #   3. 其余按第一个命中的子分类决定
        if category == "auto":
            if sub_tags:
                opinion_tags    = [t for t in sub_tags if t.startswith("opinion.")]
                policy_tags     = [t for t in sub_tags if t.startswith("policy.")]
                care_tags       = [t for t in sub_tags if t.startswith("care.")]
                # policy/care 豁免：同时命中 opinion 和 policy/care 时，policy/care 胜出
                if opinion_tags and (policy_tags or care_tags):
                    if policy_tags:
                        final_category = "policy"
                        primary_tag    = policy_tags[0]
                    else:
                        final_category = "care"
                        primary_tag    = care_tags[0]
                elif opinion_tags:
                    # 纯 opinion（无 policy/care 豁免）
                    final_category = "opinion"
                    primary_tag    = opinion_tags[0]
                else:
                    final_category = SUB_TAG_TO_CATEGORY.get(sub_tags[0], "policy")
                    primary_tag    = sub_tags[0]
            else:
                final_category = "policy"
                primary_tag    = ""
        else:
            final_category = category
            # 固定分类源：主标签取第一个命中标签（opinion 不覆盖固定分类）
            if sub_tags:
                primary_tag = sub_tags[0]
            else:
                primary_tag = ""

        # 尝试从 RSS 条目中获取图片（media:content / enclosure / media:thumbnail）
        img_url = None
        media_content = entry.get("media_content", [])
        if media_content and isinstance(media_content, list):
            for mc in media_content:
                if mc.get("url") and mc.get("medium") in ("image", None):
                    img_url = mc["url"]
                    break
        if not img_url:
            enclosures = entry.get("enclosures", [])
            for enc in enclosures:
                if enc.get("type", "").startswith("image/") and enc.get("href"):
                    img_url = enc["href"]
                    break
        if not img_url:
            media_thumbnail = entry.get("media_thumbnail", [])
            if media_thumbnail and isinstance(media_thumbnail, list):
                img_url = media_thumbnail[0].get("url")

        # RSS 中没有图片时，抓取文章页面的 og:image（仅对非 Google News 链接）
        if not img_url and "news.google.com" not in url_str:
            img_url = fetch_og_image(url_str)

        items.append({
            "title":        title,
            "summary":      summary or title,
            "source":       name,
            "url":          url_str,
            "published_at": pub_str,
            "category":     final_category,
            "tag":          primary_tag,
            "tags":         sub_tags,          # 所有命中的子分类（多标签）
            "priority":     priority,
            "feed_id":      feed_id,
            "url_hash":     url_hash(url_str),
            "image":        img_url or None,
        })

    return items


# ── 去重与排序 ────────────────────────────────────────────────────────────────

def dedup_and_sort(items: list[dict], threshold: float = 0.85) -> list[dict]:
    """
    去重：同一事件保留最高优先级来源（P0 > P1 > ... > P5）
    排序：时效优先，同天按 P0→P5
    """
    # 先按优先级排序（P0 最优先）
    items.sort(key=lambda x: (
        x.get("published_at", ""),  # 时间倒序（后面 reverse=True）
        PRIORITY_ORDER.get(x.get("priority", "P5"), 5)
    ))
    items.reverse()  # 时间倒序

    # 去重：标题相似度
    deduped = []
    seen_hashes = set()

    for item in items:
        # URL 精确去重
        h = item["url_hash"]
        if h in seen_hashes:
            continue
        seen_hashes.add(h)

        # 标题相似度去重
        is_dup = False
        for existing in deduped:
            sim = title_similarity(item["title"], existing["title"])
            if sim >= threshold:
                # 保留优先级更高的
                existing_pri = PRIORITY_ORDER.get(existing.get("priority", "P5"), 5)
                item_pri     = PRIORITY_ORDER.get(item.get("priority", "P5"), 5)
                if item_pri < existing_pri:
                    # 当前条目优先级更高，替换
                    deduped.remove(existing)
                    deduped.append(item)
                is_dup = True
                break

        if not is_dup:
            deduped.append(item)

    # 最终排序：时效优先，同天按优先级
    deduped.sort(key=lambda x: (
        x.get("published_at", "")[:10],  # 日期
        PRIORITY_ORDER.get(x.get("priority", "P5"), 5)
    ), reverse=True)

    return deduped


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="骑手行业新闻独立抓取脚本 v3")
    parser.add_argument("--date",   default=None, help="目标日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--output", default=None, help="输出文件路径，默认 output/news/YYYY-MM-DD.json")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="配置文件路径")
    parser.add_argument("--words",  default=str(WORDS_PATH),  help="关键词文件路径")
    args = parser.parse_args()

    # 日期
    bj_tz = timezone(timedelta(hours=8))
    today = datetime.now(bj_tz).strftime("%Y-%m-%d")
    date_str = args.date or today

    # 输出路径
    output_path = Path(args.output) if args.output else OUTPUT_DIR / f"{date_str}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"=== 骑手行业新闻抓取 v3 ===")
    print(f"目标日期: {date_str}")
    print(f"配置文件: {args.config}")
    print(f"输出路径: {output_path}")
    print()

    # 加载配置
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: 配置文件不存在: {config_path}")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 加载关键词规则
    keyword_rules = load_keyword_rules(Path(args.words))
    print(f"关键词规则: {len(keyword_rules['rules'])} 个子分类，{len(keyword_rules['global_filter'])} 个全局过滤词")

    # 基础关键词
    base_keywords = config.get("filter", {}).get("base_keywords", [
        "外卖骑手", "外卖小哥", "配送员", "骑手权益", "骑手收入",
        "骑手政策", "骑手社保", "骑手事故", "骑手关爱", "骑手驿站",
        "美团骑手", "饿了么骑手"
    ])

    # RSS 配置
    rss_config = config.get("rss", {})
    max_age_days = rss_config.get("freshness_filter", {}).get("max_age_days", 3)
    feeds = rss_config.get("feeds", [])

    print(f"\n── RSS 抓取（{len(feeds)} 个源，保留 {max_age_days} 天内）──")
    all_items = []

    for feed_cfg in feeds:
        items = fetch_rss_feed(feed_cfg, keyword_rules, base_keywords, max_age_days)
        all_items.extend(items)

    print(f"\n原始抓取: {len(all_items)} 条")

    # 去重与排序
    dedup_config = config.get("report", {}).get("dedup", {})
    threshold = dedup_config.get("threshold", 0.85)
    final_items = dedup_and_sort(all_items, threshold)

    print(f"去重后: {len(final_items)} 条")

    # 统计各分类
    cat_stats = {}
    for item in final_items:
        c = item.get("category", "unknown")
        cat_stats[c] = cat_stats.get(c, 0) + 1
    print(f"分类统计: {cat_stats}")

    # 构建 TrendRadar 兼容输出格式
    # 按分类分组
    sources_map = {}
    for item in final_items:
        cat = item.get("category", "policy")
        if cat not in sources_map:
            sources_map[cat] = {
                "name":     {
                    "rider_story": "骑手故事",
                    "care":        "骑手关怀",
                    "policy":      "行业观察",
                    "report":      "宏观报告",
                    "platform":    "平台动作",
                    "opinion":     "舆论信息",
                }.get(cat, cat),
                "category": cat,
                "items":    []
            }
        sources_map[cat]["items"].append({
            "title":        item["title"],
            "summary":      item["summary"],
            "source":       item["source"],
            "url":          item["url"],
            "published_at": item["published_at"],
            "tag":          item.get("tag", ""),
            "tags":         item.get("tags", []),   # 多标签（用于前端细粒度筛选）
            "priority":     item.get("priority", "P5"),
            "image":        item.get("image"),      # og:image 或 RSS 媒体图片
        })

    output = {
        "date":       date_str,
        "generated_at": datetime.now(bj_tz).strftime("%Y-%m-%dT%H:%M:%S"),
        "total":      len(final_items),
        "by_category": cat_stats,
        "sources":    list(sources_map.values()),
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    CAT_NAMES = {
        "rider_story": "骑手故事",
        "care":        "骑手关怀",
        "policy":      "行业观察",
        "report":      "宏观报告",
        "platform":    "平台动作",
        "opinion":     "舆论信息",
    }
    print(f"\n[OK] 输出完成: {output_path}")
    print(f"     总计: {len(final_items)} 条")
    for cat, count in cat_stats.items():
        print(f"     {CAT_NAMES.get(cat, cat)}: {count} 条")


if __name__ == "__main__":
    main()
