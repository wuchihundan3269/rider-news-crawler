#!/usr/bin/env python3
"""
transform.py — TrendRadar 输出 → 骑手行业快讯 JSON

用法：
  python scripts/transform.py
    --input  output/news/YYYY-MM-DD.json    (TrendRadar 原始输出)
    --hot    output/hot/YYYY-MM-DD.json     (TrendRadar 热榜输出，可选)
    --output data/YYYY-MM-DD.json           (展示站消费的 JSON)

TrendRadar 原始格式（output/news/YYYY-MM-DD.json）：
{
  "date": "2025-06-10",
  "sources": [
    {
      "name": "骑手权益",
      "category": "rider",
      "items": [
        {
          "title": "...",
          "summary": "...",
          "source": "...",
          "url": "...",
          "published_at": "2025-06-10T09:30:00",
          "image": "..."
        }
      ]
    }
  ]
}

热榜格式（output/hot/YYYY-MM-DD.json）：
{
  "date": "2025-06-10",
  "platforms": [
    {
      "platform": "weibo",
      "name": "微博",
      "link": "https://s.weibo.com/top/summary",
      "items": [{"rank": 1, "text": "...", "hot": 12345678}]
    }
  ]
}

输出格式（data/YYYY-MM-DD.json）：
{
  "date": "2025-06-10",
  "generated_at": "2025-06-10T12:00:00Z",
  "featured": [...],   // 轮播5条（最新 + 最重要）
  "articles": [...],   // 全部文章
  "flash": [...],      // 今日快讯（最近7天文章，按时间倒序，最多40条）
  "hot": [...]         // 全网热点
}
"""

import io
import json
import os
import sys
import argparse
import re
import unicodedata
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Windows GBK 终端下强制 UTF-8 输出，防止零宽字符等导致 UnicodeEncodeError
if sys.stdout.encoding and sys.stdout.encoding.upper() not in ("UTF-8", "UTF8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def _clean_text(s: str) -> str:
    """去除零宽字符、控制字符等不可见字符"""
    if not s:
        return s
    return "".join(c for c in s if not unicodedata.category(c).startswith(("Cf", "Cc", "Cs")))

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

try:
    from bs4 import BeautifulSoup as _BS
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False


def resolve_google_news_url(url: str, timeout: int = 5) -> str:
    """
    将 Google News RSS 中间链接转换为可点击的 Google News 文章链接。
    策略：
      将 /rss/articles/ 替换为 /articles/
      浏览器访问 /articles/ 链接时会自动重定向到真实原文，无需服务端解析。
    """
    if not url or "news.google.com" not in url:
        return url

    # 将 RSS 中间链接转换为可点击的文章链接
    # /rss/articles/CBMi... → /articles/CBMi...
    if "/rss/articles/" in url:
        return url.replace("/rss/articles/", "/articles/")

    return url

def fetch_article_summary(url: str, title: str, timeout: int = 10, max_chars: int = 150) -> str:
    """
    爬取原文页面，提取正文摘要（前 max_chars 字）。
    策略：
      0. 若是 Google News 中间链接，先解析为真实 URL
      1. 优先取 <meta name="description"> / <meta property="og:description">
      2. 其次取正文段落中第一段有实质内容的文字
      3. 失败或内容与标题重复则返回空字符串
    """
    if not url or not _HAS_REQUESTS or not _HAS_BS4:
        return ""
    # 若是 Google News 中间链接，先解析为真实 URL
    if "news.google.com" in url:
        real_url = resolve_google_news_url(url, timeout=timeout)
        if not real_url or "news.google.com" in real_url:
            return ""  # 解析失败，跳过
        url = real_url
    try:
        resp = _requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/124.0 Safari/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return ""
        # 检测编码
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = _BS(resp.text, "lxml")

        # 策略1：meta description
        for attr in (
            {"name": "description"},
            {"property": "og:description"},
            {"name": "twitter:description"},
        ):
            tag = soup.find("meta", attrs=attr)
            if tag and tag.get("content", "").strip():
                text = tag["content"].strip()
                if _is_valid_summary(text, title, max_chars):
                    return text[:max_chars]

        # 策略2：正文段落
        # 移除干扰标签
        for noise in soup(["script", "style", "nav", "header", "footer",
                            "aside", "figure", "figcaption", "noscript"]):
            noise.decompose()

        # 优先在 article / main / .content 等语义容器里找
        containers = (
            soup.find("article") or
            soup.find("main") or
            soup.find(class_=re.compile(r"(article|content|body|text|detail)", re.I)) or
            soup.body
        )
        if containers:
            for p in containers.find_all("p"):
                text = p.get_text(" ", strip=True)
                if _is_valid_summary(text, title, max_chars):
                    return text[:max_chars]

    except Exception:
        pass
    return ""


def _is_valid_summary(text: str, title: str, max_chars: int) -> bool:
    """判断提取到的文本是否是有效摘要（非空、够长、与标题不重复）"""
    if not text or len(text) < 15:
        return False
    # 去掉标题末尾媒体名后缀再比较
    clean_t = re.sub(r'\s*[-–—|｜]\s*\S+$', '', title).strip().lower()
    clean_s = text.lower()
    # 与标题完全相同，或摘要就是「标题+媒体名」（单词结尾）
    if clean_s == clean_t:
        return False
    if clean_s.startswith(clean_t) and len(clean_s) - len(clean_t) < 15:
        return False
    return True


# ===== 标题归一化 & 媒体优先级（去重用）=====
def _normalize_title(title: str) -> str:
    """去掉末尾 ' - 媒体名' 后缀、空白，转小写，用于去重比较。"""
    t = re.sub(r'\s*[-–—|｜]\s*[^\s].{0,20}$', '', title)
    t = re.sub(r'\s+', '', t)
    return t.lower()

_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4, "P5": 5}

# ===== 内容黑名单（永久屏蔽）=====
# URL 黑名单：完整或部分匹配，只要 article["url"] 包含其中任意一项即屏蔽
_BLOCKED_URL_FRAGMENTS: set[str] = {
    "news.cn/fortune/2022-12/13/c_1129203735",   # 农民工年龄统计老文章，反复出现
}

# 标题关键词黑名单：标题同时包含指定词组（AND逻辑）则屏蔽
# 每项是一个词语列表，列表内所有词同时出现才屏蔽
_BLOCKED_TITLE_PATTERNS: list[list[str]] = [
    # 法院判决/以案说法类（纯法律案例，与行业资讯关联度低）
    ["法院", "判了"],
    ["以案释法"],
    ["以案说法"],
    ["宜案说法"],
    ["法院", "赔偿", "骑手"],
    ["法院", "担责"],
    ["法院", "认定"],
    ["裁判", "骑手"],
    ["判决", "骑手", "赔"],
    # 事故死亡/刑拘类（个案新闻，负面情绪强，不适合展示）
    ["骑手", "身亡"],
    ["骑手", "死亡"],
    ["骑手", "遇难"],
    ["骑手", "被刑拘"],
    ["配送站", "被刑拘"],
    ["骑手", "刑拘"],
    ["骑手", "交通事故", "亡"],
    ["骑手", "撞车", "身亡"],
    ["骑手", "撞车", "死亡"],
    ["负责人", "被刑拘"],
    # 责任/追责/赔偿类
    ["平台失职"],
    ["重大责任事故"],
    ["涉嫌重大责任"],
    # 骑手封号/投诉争议负面类
    ["骑手", "被封号"],
    ["骑手", "封号"],
    # 职业伤害认定争议
    ["骑手", "职业伤害", "工伤"],
    ["骑手", "遭遇交通事故", "伤害"],
]

def _is_blocked(article: dict) -> bool:
    """判断文章是否命中黑名单（URL 或 标题关键词）"""
    url = article.get("url", "")
    for frag in _BLOCKED_URL_FRAGMENTS:
        if frag in url:
            return True
    title = article.get("title", "")
    for pattern in _BLOCKED_TITLE_PATTERNS:
        if all(kw in title for kw in pattern):
            return True
    return False


# ===== 一级分类映射（category → 页面展示信息）=====
# Wiki 六分类体系：骑手新闻 / 骑手关怀 / 行业观察 / 宏观报告 / 平台动作 / 舆论信息
CATEGORY_MAP = {
    # ── 六分类正式名称 ──
    "rider_story": {"category": "rider_story", "tag": "骑手新闻", "tagClass": "tag-orange"},
    "care":        {"category": "care",        "tag": "骑手关怀", "tagClass": "tag-green"},
    "policy":      {"category": "policy",      "tag": "行业观察", "tagClass": "tag-blue"},
    "report":      {"category": "report",      "tag": "宏观报告", "tagClass": "tag-teal"},
    "platform":    {"category": "platform",    "tag": "平台动作", "tagClass": "tag-purple"},
    "opinion":     {"category": "opinion",     "tag": "舆论信息", "tagClass": "tag-red"},
    # ── 旧分类兼容映射 ──
    "rider":       {"category": "rider_story", "tag": "骑手新闻", "tagClass": "tag-orange"},
    "industry":    {"category": "policy",      "tag": "行业观察", "tagClass": "tag-blue"},
    "media":       {"category": "opinion",     "tag": "舆论信息", "tagClass": "tag-red"},
    "hot":         {"category": "opinion",     "tag": "舆论信息", "tagClass": "tag-red"},
}

# ===== 子分类打标规则 =====
# 格式：(sub_tag, label, keywords_any)
# 匹配逻辑：标题或摘要中包含 keywords_any 中任意一个词组（词组内所有词同时出现）则命中
# 优先级：列表顺序，先匹配先得
SUB_TAG_RULES: list[tuple[str, str, list[list[str]]]] = [
    # ── 骑手故事（rider_story）────────────────────────────────────
    ("rider_story.positive", "正面事迹",   [["骑手","好人好事"],["骑手","见义勇为"],["最美骑手"],["骑手","救人"],["骑手","拾金不昧"],["骑手","公益"],["骑手","正能量"],["骑手","暖心"],["骑手","英雄"]]),
    ("rider_story.accident", "安全事故",   [["骑手","交通事故"],["骑手","猝死"],["骑手","过劳"],["骑手","受伤"],["骑手","工伤"],["骑手","意外"],["骑手","车祸"],["骑手","身亡"]]),
    ("rider_story.incident", "群体事件",   [["骑手","罢工"],["骑手","讨薪"],["骑手","欠薪"],["骑手","停工"],["站点","跑路"],["骑手","骗押金"],["骑手","聚集"]]),
    ("rider_story.life",     "生活百态",   [["骑手","故事"],["骑手","经历"],["骑手","大学生"],["骑手","高学历"],["骑手","春节"],["骑手","家庭"],["骑手","日常"],["骑手","生活"]]),
    ("rider_story.career",   "职业发展",   [["骑手","技能大赛"],["骑手","职业发展"],["骑手","转型"],["骑手","学历"],["骑手","考证"],["骑手","培训"],["骑手","救护"],["骑手","新角色"]]),
    # ── 骑手关怀（care）──────────────────────────────────────────
    ("care.welfare",   "平台福利",   [["骑手","福利"],["骑手","保险"],["骑手","帮扶"],["骑手","助学"],["骑手","节日","礼包"],["骑手","高温补贴"],["骑手","关爱","计划"]]),
    ("care.health",    "健康安全",   [["骑手","健康体检"],["骑手","心理健康"],["骑手","防暑"],["骑手","头盔","发放"],["骑手","安全装备","发放"]]),
    ("care.station",   "驿站设施",   [["骑手","驿站"],["骑手","休息站"],["骑手","爱心驿站"],["骑手","服务站"],["骑手","充电站"],["骑手","友好场景"]]),
    ("care.social",    "社会关爱",   [["骑手","关爱"],["骑手","关怀"],["骑手","送温暖"],["骑手","法律援助"],["骑手","权益","保障网"],["工会","骑手"]]),
    # ── 行业观察（policy）────────────────────────────────────────
    ("policy.national", "国家政策",  [["新就业形态","政策"],["人社部","骑手"],["骑手","两会"],["骑手","提案"],["平台经济","监管"],["市场监管","外卖"],["骑手","立法"],["骑手","新规"]]),
    ("policy.labor",    "劳动法规",  [["骑手","社保"],["职业伤害","保障"],["灵活就业","立法"],["新就业形态","工会"],["劳动关系","外卖"],["骑手","劳动合同"],["骑手","工伤保险"]]),
    ("policy.local",    "地方政策",  [["骑手","管理办法"],["城市","外卖","管理"],["地方","骑手","政策"],["骑手","试点"],["骑手","巡防"],["骑手","平安哨兵"]]),
    ("policy.standard", "行业标准",  [["电动自行车","新国标"],["即时配送","服务规范"],["骑手","安全装备","标准"],["配送","行业标准"],["电动车","新规"]]),
    # ── 宏观报告（report）────────────────────────────────────────
    ("report.market",   "市场格局",  [["京东外卖"],["抖音外卖"],["闪送","新动作"],["顺丰同城","新动作"],["外卖","新玩家"],["即时配送","市场格局"],["外卖","竞争"]]),
    ("report.economy",  "宏观经济",  [["灵活就业","规模"],["新就业形态","规模"],["骑手","就业","人数"],["平台经济","就业"],["骑手","过剩"],["骑手","暴涨"]]),
    ("report.research", "行业报告",  [["外卖","行业","报告"],["外卖","白皮书"],["即时配送","蓝皮书"],["骑手","调研","报告"],["外卖","行业","分析"]]),
    ("report.season",   "季节趋势",  [["高温","骑手"],["暴雨","骑手"],["极端天气","骑手"],["寒潮","骑手"],["节假日","外卖","爆单"]]),
    # ── 平台动作（platform）──────────────────────────────────────
    ("platform.ops",    "运力调整",  [["美团","众包","调整"],["美团","专送","众包"],["美团","畅跑"],["美团","乐跑"],["骑手","接单模式","调整"],["运力","调度"]]),
    ("platform.algo",   "算法规则",  [["美团","派单算法"],["美团","超时规则"],["骑手","申诉","机制"],["配送时间","算法"]]),
    ("platform.pay",    "收入费用",  [["美团","配送费","调整"],["骑手","单价","变动"],["骑手","奖励","规则"],["骑手","提现","规则"],["配送费","计价"],["骑手","收入","断崖"],["骑手","收入","下跌"]]),
    ("platform.recruit","招募合作",  [["美团","骑手","招募"],["美团","骑手","扩招"],["京东","骑手","招聘"],["众包","注册","门槛"]]),
    ("platform.safety", "安全合规",  [["美团","骑手","安全培训"],["平台","骑手","保险"],["美团","交通安全"],["平台","头盔"],["平台","反光衣"],["骑手","救护培训"],["骑手","应急"]]),
    ("platform.data",   "经营数据",  [["美团","财报"],["美团","单量"],["美团","订单量"],["美团","营收"],["饿了么","财报"],["即时配送","订单量"]]),
    # ── 舆论信息（opinion）───────────────────────────────────────
    ("opinion.rights",  "权益争议",  [["骑手","权益","争议"],["配送费","不透明"],["骑手","收入","降低"],["骑手","扣罚"],["骑手","仲裁"],["骑手","维权"],["骑手","权益","受损"]]),
    ("opinion.media",   "媒体曝光",  [["骑手","暗访"],["骑手","曝光"],["骑手","纪录片"],["央视","外卖","骑手"],["媒体","骑手","调查"],["骑手","深度","报道"]]),
    ("opinion.viral",   "热搜发声",  [["骑手","热搜"],["骑手","大V","发声"],["骑手","短视频","爆火"],["外卖骑手","社会关注"],["骑手","刷屏"]]),
    ("opinion.consumer","消费者矛盾",[["骑手","差评","争议"],["骑手","投诉"],["外卖","超时","消费者"],["骑手","物业","门禁"],["骑手","写字楼","上楼"],["骑手","顾客","冲突"]]),
    ("opinion.merchant","商家摩擦",  [["商家","骑手","冲突"],["商家","骑手","纠纷"],["出餐慢","骑手"],["商家","取消订单","骑手"]]),
    ("opinion.crisis",  "舆论发酵",  [["骑手","舆论","风暴"],["骑手","全网关注"],["骑手","极端事件"],["骑手","社会反思"],["骑手","集体","不满"],["骑手","封签"],["骑手","罚款","不合理"]]),
]

# 子分类 → 页面显示标签文字
SUB_TAG_LABEL: dict[str, str] = {rule[0]: rule[1] for rule in SUB_TAG_RULES}


def detect_sub_tag(title: str, summary: str) -> str | None:
    """根据标题+摘要关键词匹配子分类 tag，返回第一个命中的 sub_tag 或 None"""
    text = title + " " + summary
    for sub_tag, _label, keyword_groups in SUB_TAG_RULES:
        for kw_group in keyword_groups:
            if all(kw in text for kw in kw_group):
                return sub_tag
    return None

# 轮播背景渐变（按分类，Wiki 六分类体系）
GRAD_MAP = {
    # 六分类正式名称
    "rider_story": "linear-gradient(135deg,#1a2e1a 0%,#0d2b0d 45%,#1a3a1a 100%)",
    "care":        "linear-gradient(135deg,#0d2e1a 0%,#0a2818 45%,#0f3a20 100%)",
    "policy":      "linear-gradient(135deg,#0d1b2e 0%,#0a1628 45%,#0f2040 100%)",
    "report":      "linear-gradient(135deg,#0d2a2e 0%,#0a2228 45%,#0f3038 100%)",
    "platform":    "linear-gradient(135deg,#1a1a2e 0%,#16213e 45%,#0f3460 100%)",
    "opinion":     "linear-gradient(135deg,#1e0a2e 0%,#180820 45%,#2a0f3a 100%)",
    # 旧分类兼容
    "rider":       "linear-gradient(135deg,#1a2e1a 0%,#0d2b0d 45%,#1a3a1a 100%)",
    "industry":    "linear-gradient(135deg,#0d1b2e 0%,#0a1628 45%,#0f2040 100%)",
}

# 热榜平台 logo（favicon）
HOT_LOGO_MAP = {
    "weibo":    "https://favicon.im/weibo.com?larger=true",
    "douyin":   "https://favicon.im/tiktok.com?larger=true",
    "kuaishou": "https://favicon.im/kuaishou.com?larger=true",
    "baidu":    "https://favicon.im/baidu.com?larger=true",
    "zhihu":    "https://favicon.im/zhihu.com?larger=true",
    "bilibili": "https://favicon.im/bilibili.com?larger=true",
    "weixin":   "https://favicon.im/weixin.qq.com?larger=true",
    "toutiao":  "https://favicon.im/toutiao.com?larger=true",
}

HOT_LINK_MAP = {
    "weibo":    "https://s.weibo.com/top/summary",
    "douyin":   "https://www.douyin.com/search/%E7%83%AD%E6%90%9C",
    "kuaishou": "https://www.kuaishou.com/",
    "baidu":    "https://top.baidu.com/board?tab=realtime",
    "zhihu":    "https://www.zhihu.com/hot",
    "bilibili": "https://www.bilibili.com/v/popular/rank/all",
    "weixin":   "https://weixin.sogou.com/",
    "toutiao":  "https://www.toutiao.com/",
}


def parse_article(item: dict, cat_info: dict, date_str: str) -> dict:
    """将 TrendRadar 单条文章转换为页面格式"""
    # 时间处理
    pub = item.get("published_at") or item.get("pub_date") or item.get("pubDate") or ""
    if pub:
        try:
            # 尝试多种格式
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    ts = datetime.strptime(pub[:19], fmt)
                    pub = ts.isoformat()
                    break
                except ValueError:
                    continue
        except Exception:
            pub = date_str + "T12:00:00"
    else:
        pub = date_str + "T12:00:00"

    title   = _clean_text(item.get("title", "").strip())
    summary = _clean_text(item.get("summary", item.get("description", "")).strip())

    # ── 从标题末尾提取真实媒体名（Google News RSS 格式：「标题 - 媒体名」）
    raw_source = item.get("source", item.get("feed_name", "")).strip()
    real_source = raw_source
    raw_url_check = item.get("url", item.get("link", ""))
    if "news.google.com" in raw_url_check or raw_source.startswith("Google新闻"):
        # Google News 标题格式：「文章标题 - 媒体名」
        _m = re.search(r'\s[-\u2013\u2014]\s*([^\-\u2013\u2014]{2,30})\s*$', title)
        if _m:
            real_source = _m.group(1).strip()
            title = title[:_m.start()].strip()

    # 子分类打标：优先使用 feed 自带的 tag 字段，否则关键词匹配
    sub_tag = item.get("tag") or detect_sub_tag(title, summary)
    sub_label = SUB_TAG_LABEL.get(sub_tag, "") if sub_tag else ""

    raw_url = item.get("url", item.get("link", ""))
    resolved_url = resolve_google_news_url(raw_url)
    # Google News 链接无法解析为直链，改用百度搜索标题作为可点击的 fallback
    if "news.google.com" in resolved_url:
        resolved_url = "https://www.baidu.com/s?wd=" + urllib.parse.quote(title)

    # 摘要增强：若 summary 为空或与标题重复，爬取原文提取真实摘要
    if not _is_valid_summary(summary, title, 200):
        fetched = fetch_article_summary(resolved_url, title)
        if fetched:
            summary = fetched
            print(f"    [摘要] {title[:30]}… → {summary[:40]}…")

    return {
        "title":        title,
        "summary":      summary,
        "source":       real_source,
        "url":          resolved_url,
        "published_at": pub,
        "category":     cat_info["category"],
        "tag":          cat_info["tag"],
        "tagClass":     cat_info["tagClass"],
        "sub_tag":      sub_tag,       # 细粒度子分类，如 "rider.positive"
        "sub_label":    sub_label,     # 子分类中文标签，如 "正面事迹"
        "priority":     item.get("priority", "P5"),  # 媒体优先级 P0-P5
        "img":          item.get("image", item.get("img", None)),
        "grad":         GRAD_MAP.get(cat_info["category"], GRAD_MAP.get("industry", "")),
    }


def transform(input_path: str, hot_path: str | None, output_path: str, existing_path: str | None = None):
    # 读取新闻数据
    with open(input_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    date_str = raw.get("date", datetime.now().strftime("%Y-%m-%d"))
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── 格式检测：如果输入已经是网站格式（含 articles 字段），直接透传 ──
    if "articles" in raw and isinstance(raw["articles"], list):
        # 补充 sub_tag 打标（已有则保留，没有则重新检测）；同时解析 Google News URL
        articles = []
        for a in raw["articles"]:
            updates = {}
            if not a.get("sub_tag"):
                sub_tag = detect_sub_tag(a.get("title", ""), a.get("summary", ""))
                updates["sub_tag"] = sub_tag
                updates["sub_label"] = SUB_TAG_LABEL.get(sub_tag, "") if sub_tag else ""
            # 解析 Google News 中间链接，修复 source 字段
            raw_url = a.get("url", "")
            resolved_url = raw_url
            title = a.get("title", "")
            if raw_url and "news.google.com" in raw_url:
                resolved_url = resolve_google_news_url(raw_url)
                # 从标题末尾提取真实媒体名
                _m = re.search(r'\s[-\u2013\u2014]\s*([^\-\u2013\u2014]{2,30})\s*$', title)
                if _m:
                    updates["source"] = _m.group(1).strip()
                    title = title[:_m.start()].strip()
                    updates["title"] = title
                # 仍是 Google News 链接则改用百度搜索 fallback
                if "news.google.com" in resolved_url:
                    resolved_url = "https://www.baidu.com/s?wd=" + urllib.parse.quote(title)
                updates["url"] = resolved_url
            summary = a.get("summary", "")
            if not _is_valid_summary(summary, title, 200):
                fetched = fetch_article_summary(resolved_url, title)
                if fetched:
                    updates["summary"] = fetched
                    print(f"    [摘要] {title[:30]}… → {fetched[:40]}…")
            if updates:
                a = {**a, **updates}
            articles.append(a)
        def _resolve_list(lst):
            result = []
            for a in lst:
                raw_url = a.get("url", "")
                if raw_url and "news.google.com" in raw_url:
                    a = {**a, "url": resolve_google_news_url(raw_url)}
                result.append(a)
            return result

        flash    = _resolve_list(raw.get("flash", []))
        featured = _resolve_list(raw.get("featured", _pick_featured(articles)))
        hot      = raw.get("hot", [])
        # ── 合并已有数据（累积追加模式）──────────────────────────────
        articles = _merge_with_existing(articles, existing_path, date_str)

        flash    = articles[:40]   # 取最近40条，不限当天
        featured = _pick_featured(articles, n=5)

        output = {
            "date":         date_str,
            "generated_at": generated_at,
            "featured":     featured,
            "articles":     articles,
            "flash":        flash,
            "hot":          hot,
        }
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"[OK] passthrough done: {output_path}")
        print(f"     articles : {len(articles)}")
        print(f"     flash    : {len(flash)}")
        print(f"     featured : {len(featured)}")
        print(f"     hot      : {len(hot)}")
        return

    # 解析文章（TrendRadar 原始格式）
    articles = []
    sources = raw.get("sources", raw.get("items", []))

    # 兼容两种格式：
    # 格式A: {"sources": [{"category": "rider", "items": [...]}]}
    # 格式B: {"items": [...]}  （扁平列表，每条有 category 字段）
    if sources and isinstance(sources[0], dict) and "items" in sources[0]:
        # 格式A：按 source 分组
        for src in sources:
            cat_key = src.get("category", "industry").lower()
            cat_info = CATEGORY_MAP.get(cat_key, CATEGORY_MAP["policy"])
            for item in src.get("items", []):
                a = parse_article(item, cat_info, date_str)
                if a["title"]:
                    articles.append(a)
    else:
        # 格式B：扁平列表
        for item in sources:
            cat_key = item.get("category", "industry").lower()
            cat_info = CATEGORY_MAP.get(cat_key, CATEGORY_MAP["policy"])
            a = parse_article(item, cat_info, date_str)
            if a["title"]:
                articles.append(a)

    # 按时间倒序
    articles.sort(key=lambda x: x.get("published_at", ""), reverse=True)

    # 去重（归一化标题 + 优先级择优，同一事件多来源只保留最高优先级）
    best_in_batch: dict[str, dict] = {}
    for a in articles:
        raw_title = a.get("title", "").strip()
        if not raw_title:
            continue
        norm = _normalize_title(raw_title)
        if norm not in best_in_batch:
            best_in_batch[norm] = a
        else:
            cur_p = _PRIORITY_ORDER.get(best_in_batch[norm].get("priority", "P5"), 5)
            new_p = _PRIORITY_ORDER.get(a.get("priority", "P5"), 5)
            if new_p < cur_p:
                best_in_batch[norm] = a
    articles = sorted(best_in_batch.values(), key=lambda x: x.get("published_at", ""), reverse=True)

    # 今日快讯：最近40条，不限当天（文章时间戳经常是昨天/前天）
    flash = articles[:40]

    # 轮播：优先有图 + 各分类均衡，取5条
    featured = _pick_featured(articles, n=5)

    # 热榜数据
    hot = []
    if hot_path and os.path.exists(hot_path):
        with open(hot_path, "r", encoding="utf-8") as f:
            hot_raw = json.load(f)
        platforms = hot_raw.get("platforms", hot_raw.get("hot", []))
        for p in platforms:
            pid = p.get("platform", p.get("id", "")).lower()
            hot.append({
                "platform": pid,
                "name":     p.get("name", pid),
                "logo_url": p.get("logo_url", HOT_LOGO_MAP.get(pid, "")),
                "link":     p.get("link", HOT_LINK_MAP.get(pid, "#")),
                "items":    [
                    {"rank": item.get("rank", i+1), "text": item.get("text", item.get("title", ""))}
                    for i, item in enumerate(p.get("items", [])[:10])
                ]
            })

    # ── 合并已有数据（累积追加模式）──────────────────────────────────
    articles = _merge_with_existing(articles, existing_path, date_str)

    # 今日快讯：最近40条，不限当天（合并后重新计算）
    flash = articles[:40]

    # 轮播：合并后重新挑选
    featured = _pick_featured(articles, n=5)

    # 构建输出
    output = {
        "date":         date_str,
        "generated_at": generated_at,
        "featured":     featured,
        "articles":     articles,
        "flash":        flash,
        "hot":          hot,
    }

    # 写入
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[OK] transform done: {output_path}")
    print(f"     articles : {len(articles)}")
    print(f"     flash    : {len(flash)}")
    print(f"     featured : {len(featured)}")
    print(f"     hot      : {len(hot)}")


_AGGREGATOR_SOURCES = {"MSN", "Yahoo", "Yahoo News", "Yahoo Finance",
                       "Google News", "Apple News", "SmartNews", "Flipboard",
                       "今日头条", "腾讯新闻", "网易新闻", "百度新闻", "搜狐新闻"}

def _is_aggregator(article: dict) -> bool:
    """判断文章是否来自聚合平台（标题末尾 ' - 媒体名' 或 source 字段）"""
    title = article.get("title", "")
    # 从标题末尾提取媒体名（Google News RSS 格式）
    di = title.rfind(" - ")
    if di > 0:
        name = title[di + 3:].strip()
        if name in _AGGREGATOR_SOURCES:
            return True
    return False

def _merge_with_existing(new_articles: list, existing_path: str | None, date_str: str) -> list:
    """
    将新抓取的文章与已有数据文件中的文章合并去重，实现累积追加。
    去重键：归一化标题（去掉末尾媒体名后缀后比较）。
    同标题多来源：保留媒体优先级最高（P0 > P5）的那条。
    排序：按 published_at 倒序。
    """
    existing_articles: list[dict] = []
    if existing_path:
        try:
            ep = Path(existing_path)
            if ep.exists():
                with open(ep, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)
                existing_articles = existing_data.get("articles", [])
                print(f"[merge] 已有数据: {len(existing_articles)} 条，本次新抓取: {len(new_articles)} 条")
        except Exception as e:
            print(f"[merge] 读取已有数据失败，跳过合并: {e}")
            existing_articles = []

    # 合并所有文章（新数据在前，已有数据在后）
    all_articles = new_articles + existing_articles

    # 修复存量数据中的遗留问题
    for a in all_articles:
        # 1. published_at = "unknown" → 补全兜底时间
        if a.get("published_at") == "unknown":
            a["published_at"] = date_str + "T12:00:00"
        # 2. source 仍是 RSS 频道名（如「Google新闻-xxx」）→ 从标题末尾提取真实媒体名
        src = a.get("source", "")
        title = a.get("title", "")
        if src.startswith("Google新闻") or "news.google.com" in a.get("url", ""):
            _m = re.search(r'\s[-\u2013\u2014]\s*([^\-\u2013\u2014]{2,30})\s*$', title)
            if _m:
                a["source"] = _m.group(1).strip()
                a["title"]  = title[:_m.start()].strip()
            # URL 无法解析则改为百度搜索 fallback
            if "news.google.com" in a.get("url", ""):
                clean_title = a.get("title", title)
                a["url"] = "https://www.baidu.com/s?wd=" + urllib.parse.quote(clean_title)

    # ── 黑名单过滤 + 日期过滤 ──
    now_iso = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%dT%H:%M:%S")
    filtered = []
    for a in all_articles:
        # 1. 黑名单过滤（URL + 标题关键词）
        if _is_blocked(a):
            print(f"  [blocked] {a.get('title','')[:40]}")
            continue
        # 2. 严格当日过滤：published_at 的日期部分必须等于 date_str
        #    兜底时间（T12:00:00）日期已经是 date_str，不受影响
        pub = a.get("published_at", "")
        if pub and pub[:10] != date_str:
            print(f"  [skip-old] {pub[:10]} {a.get('title','')[:35]}")
            continue
        # 3. 过滤未来时间（published_at 晚于当前时间，视为错误时间）
        if pub and pub > now_iso and not pub.endswith("T12:00:00"):
            print(f"  [future-time] {pub} {a.get('title','')[:30]}")
            a["published_at"] = date_str + "T12:00:00"
        filtered.append(a)
    all_articles = filtered

    # 按归一化标题去重，同标题保留优先级最高的那条
    best: dict[str, dict] = {}
    for a in all_articles:
        raw_title = a.get("title", "").strip()
        if not raw_title:
            continue
        norm = _normalize_title(raw_title)
        if norm not in best:
            # 新文章首次入库：若时间是相对时间解析出的抓取时刻（秒数非零且是当天），
            # 统一归为当天T12:00:00，避免「6小时前」每次算出不同时间
            pub = a.get("published_at", "")
            if (pub.startswith(date_str) and
                    len(pub) >= 19 and pub[17:19] != "00" and
                    not pub.endswith("T12:00:00")):
                # 有秒数说明是相对时间解析结果，不是原始精确时间（原始一般到分钟）
                a = dict(a)
                a["published_at"] = date_str + "T12:00:00"
            best[norm] = a
        else:
            cur_p = _PRIORITY_ORDER.get(best[norm].get("priority", "P5"), 5)
            new_p = _PRIORITY_ORDER.get(a.get("priority", "P5"), 5)
            if new_p < cur_p:
                merged_article = dict(a)
                # 无论优先级如何，只要已有数据有精确时间就保留——
                # 防止每次重新抓取时「X小时前」相对时间算出不同值覆盖掉稳定时间
                existing_pub = best[norm].get("published_at", "")
                new_pub = a.get("published_at", "")
                if existing_pub and not existing_pub.endswith("T12:00:00"):
                    merged_article["published_at"] = existing_pub
                best[norm] = merged_article
            else:
                # 优先级相同或新数据更低：保留已有，但若已有是兜底时间而新数据更精确则更新
                existing_pub = best[norm].get("published_at", "")
                new_pub = a.get("published_at", "")
                if existing_pub.endswith("T12:00:00") and new_pub and not new_pub.endswith("T12:00:00"):
                    best[norm]["published_at"] = new_pub

    merged = list(best.values())
    merged.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    print(f"[merge] 合并后共 {len(merged)} 条（去重前 {len(all_articles)} 条）")
    return merged


def _pick_featured(articles: list, n: int = 5) -> list:
    """从文章列表中挑选轮播精选：优先有图，各分类均衡（Wiki 六分类体系）"""
    # 先过滤掉聚合平台来源（MSN、Yahoo 等不是真实媒体）
    articles = [a for a in articles if not _is_aggregator(a)]
    cats = ["rider_story", "care", "policy", "report", "platform", "opinion"]
    buckets = {c: [] for c in cats}
    others = []
    for a in articles:
        c = a.get("category", "policy")
        if c in buckets:
            buckets[c].append(a)
        else:
            others.append(a)

    # 优先有图的
    def prefer_img(lst):
        with_img = [x for x in lst if x.get("img")]
        without_img = [x for x in lst if not x.get("img")]
        return with_img + without_img

    result = []
    # 轮流从各分类取
    for c in cats:
        buckets[c] = prefer_img(buckets[c])
    idx = {c: 0 for c in cats}
    round_cats = cats[:]
    while len(result) < n and round_cats:
        next_round = []
        for c in round_cats:
            if len(result) >= n:
                break
            if idx[c] < len(buckets[c]):
                result.append(buckets[c][idx[c]])
                idx[c] += 1
                next_round.append(c)
        round_cats = next_round

    # 不足则从 others 补
    if len(result) < n:
        for a in prefer_img(others):
            if len(result) >= n:
                break
            result.append(a)

    return result[:n]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TrendRadar → 骑手快讯 JSON 转换器")
    parser.add_argument("--input",    required=True, help="TrendRadar 新闻输出 JSON 路径")
    parser.add_argument("--hot",      default=None,  help="TrendRadar 热榜输出 JSON 路径（可选）")
    parser.add_argument("--output",   required=True, help="输出 JSON 路径（如 data/2025-06-10.json）")
    parser.add_argument("--existing", default=None,  help="已有数据 JSON 路径，用于累积追加（如 data/2025-06-10.json）")
    args = parser.parse_args()
    transform(args.input, args.hot, args.output, args.existing)
