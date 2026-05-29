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
  "flash": [...],      // 今日快讯（当天文章，按时间倒序）
  "hot": [...]         // 全网热点
}
"""

import json
import os
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

# ===== 一级分类映射（category → 页面展示信息）=====
CATEGORY_MAP = {
    "rider":    {"category": "rider",    "tag": "骑手新闻", "tagClass": "tag-yellow"},
    "platform": {"category": "platform", "tag": "平台动作", "tagClass": "tag-red"},
    "industry": {"category": "industry", "tag": "行业动态", "tagClass": "tag-blue"},
    "opinion":  {"category": "opinion",  "tag": "舆情信息", "tagClass": "tag-purple"},
    # 兼容其他分类名
    "policy":   {"category": "industry", "tag": "政策",     "tagClass": "tag-blue"},
    "media":    {"category": "opinion",  "tag": "媒体",     "tagClass": "tag-gray"},
    "hot":      {"category": "opinion",  "tag": "热点",     "tagClass": "tag-purple"},
}

# ===== 子分类打标规则 =====
# 格式：(sub_tag, label, keywords_any)
# 匹配逻辑：标题或摘要中包含 keywords_any 中任意一个词组（词组内所有词同时出现）则命中
# 优先级：列表顺序，先匹配先得
SUB_TAG_RULES: list[tuple[str, str, list[list[str]]]] = [
    # ── 骑手新闻 ──────────────────────────────────────────────────
    ("rider.positive",  "正面事迹",   [["骑手","好人好事"],["骑手","见义勇为"],["最美骑手"],["骑手","救人"],["骑手","拾金不昧"],["骑手","公益"],["骑手","正能量"]]),
    ("rider.accident",  "安全事故",   [["骑手","交通事故"],["骑手","猝死"],["骑手","过劳"],["骑手","受伤"],["骑手","工伤"],["骑手","意外"]]),
    ("rider.incident",  "群体事件",   [["骑手","罢工"],["骑手","讨薪"],["骑手","欠薪"],["骑手","停工"],["站点","跑路"],["骑手","骗押金"]]),
    ("rider.story",     "生活故事",   [["骑手","故事"],["骑手","经历"],["骑手","大学生"],["骑手","高学历"],["骑手","春节"],["骑手","家庭"]]),
    ("rider.career",    "职业发展",   [["骑手","技能大赛"],["骑手","职业发展"],["骑手","转型"],["骑手","学历"],["骑手","考证"],["骑手","培训"]]),
    # ── 行业动态 ──────────────────────────────────────────────────
    ("industry.policy", "监管政策",   [["新就业形态","政策"],["人社部","骑手"],["骑手","两会"],["骑手","提案"],["平台经济","监管"],["市场监管","外卖"]]),
    ("industry.labor",  "劳动法规",   [["骑手","社保"],["职业伤害","保障"],["灵活就业","立法"],["新就业形态","工会"],["劳动关系","外卖"]]),
    ("industry.std",    "行业标准",   [["电动自行车","新国标"],["即时配送","服务规范"],["骑手","安全装备","标准"],["配送","行业标准"]]),
    ("industry.market", "竞争格局",   [["京东外卖"],["抖音外卖"],["闪送","新动作"],["顺丰同城","新动作"],["外卖","新玩家"],["即时配送","市场格局"]]),
    ("industry.local",  "地方政策",   [["骑手","驿站"],["骑手","休息站"],["骑手","关爱"],["城市","外卖","管理办法"]]),
    ("industry.season", "季节影响",   [["高温","骑手"],["暴雨","骑手"],["极端天气","骑手"],["寒潮","骑手"],["节假日","外卖","爆单"]]),
    # ── 平台动作 ──────────────────────────────────────────────────
    ("platform.ops",    "运力调整",   [["美团","众包","调整"],["美团","专送","众包"],["美团","畅跑"],["美团","乐跑"],["骑手","接单模式","调整"],["运力","调度"]]),
    ("platform.algo",   "算法规则",   [["美团","派单算法"],["美团","超时规则"],["骑手","申诉","机制"],["配送时间","算法"]]),
    ("platform.pay",    "收入费用",   [["美团","配送费","调整"],["骑手","单价","变动"],["骑手","奖励","规则"],["骑手","提现","规则"],["配送费","计价"]]),
    ("platform.recruit","招募合作",   [["美团","骑手","招募"],["美团","骑手","扩招"],["京东","骑手","招聘"],["众包","注册","门槛"]]),
    ("platform.safety", "安全合规",   [["美团","骑手","安全培训"],["平台","骑手","保险"],["美团","交通安全"],["平台","头盔"],["平台","反光衣"]]),
    ("platform.welfare","福利保障",   [["美团","骑手","高温补贴"],["平台","骑手","节日福利"],["骑手","健康体检"],["骑手","助学"],["骑手","帮扶"]]),
    # ── 舆情信息 ──────────────────────────────────────────────────
    ("opinion.rights",  "权益争议",   [["骑手","权益","争议"],["配送费","不透明"],["骑手","收入","降低"],["骑手","扣罚"],["骑手","仲裁"],["骑手","维权"]]),
    ("opinion.media",   "媒体曝光",   [["骑手","暗访"],["骑手","曝光"],["骑手","纪录片"],["央视","外卖","骑手"],["媒体","骑手","调查"]]),
    ("opinion.viral",   "热搜发声",   [["骑手","热搜"],["骑手","大V","发声"],["骑手","短视频","爆火"],["外卖骑手","社会关注"]]),
    ("opinion.consumer","消费者矛盾", [["骑手","差评","争议"],["骑手","投诉"],["外卖","超时","消费者"],["骑手","物业","门禁"],["骑手","写字楼","上楼"]]),
    ("opinion.merchant","商家摩擦",   [["商家","骑手","冲突"],["商家","骑手","纠纷"],["出餐慢","骑手"],["商家","取消订单","骑手"]]),
    ("opinion.crisis",  "舆情发酵",   [["骑手","舆论","风暴"],["骑手","全网关注"],["骑手","极端事件"],["骑手","社会反思"],["骑手","集体","不满"]]),
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

# 轮播背景渐变（按分类）
GRAD_MAP = {
    "rider":    "linear-gradient(135deg,#1a2e1a 0%,#0d2b0d 45%,#1a3a1a 100%)",
    "platform": "linear-gradient(135deg,#1a1a2e 0%,#16213e 45%,#0f3460 100%)",
    "industry": "linear-gradient(135deg,#0d1b2e 0%,#0a1628 45%,#0f2040 100%)",
    "opinion":  "linear-gradient(135deg,#1e0a2e 0%,#180820 45%,#2a0f3a 100%)",
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

    title   = item.get("title", "").strip()
    summary = item.get("summary", item.get("description", "")).strip()

    # 子分类打标：优先使用 feed 自带的 tag 字段，否则关键词匹配
    sub_tag = item.get("tag") or detect_sub_tag(title, summary)
    sub_label = SUB_TAG_LABEL.get(sub_tag, "") if sub_tag else ""

    return {
        "title":        title,
        "summary":      summary,
        "source":       item.get("source", item.get("feed_name", "")).strip(),
        "url":          item.get("url", item.get("link", "")),
        "published_at": pub,
        "category":     cat_info["category"],
        "tag":          cat_info["tag"],
        "tagClass":     cat_info["tagClass"],
        "sub_tag":      sub_tag,       # 细粒度子分类，如 "rider.positive"
        "sub_label":    sub_label,     # 子分类中文标签，如 "正面事迹"
        "img":          item.get("image", item.get("img", None)),
        "grad":         GRAD_MAP.get(cat_info["category"], GRAD_MAP["industry"]),
    }


def transform(input_path: str, hot_path: str | None, output_path: str):
    # 读取新闻数据
    with open(input_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    date_str = raw.get("date", datetime.now().strftime("%Y-%m-%d"))
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── 格式检测：如果输入已经是网站格式（含 articles 字段），直接透传 ──
    if "articles" in raw and isinstance(raw["articles"], list):
        # 补充 sub_tag 打标（已有则保留，没有则重新检测）
        articles = []
        for a in raw["articles"]:
            if not a.get("sub_tag"):
                sub_tag = detect_sub_tag(a.get("title", ""), a.get("summary", ""))
                a = {**a, "sub_tag": sub_tag, "sub_label": SUB_TAG_LABEL.get(sub_tag, "") if sub_tag else ""}
            articles.append(a)
        flash    = raw.get("flash", [])
        featured = raw.get("featured", _pick_featured(articles))
        hot      = raw.get("hot", [])
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
            cat_info = CATEGORY_MAP.get(cat_key, CATEGORY_MAP["industry"])
            for item in src.get("items", []):
                a = parse_article(item, cat_info, date_str)
                if a["title"]:
                    articles.append(a)
    else:
        # 格式B：扁平列表
        for item in sources:
            cat_key = item.get("category", "industry").lower()
            cat_info = CATEGORY_MAP.get(cat_key, CATEGORY_MAP["industry"])
            a = parse_article(item, cat_info, date_str)
            if a["title"]:
                articles.append(a)

    # 按时间倒序
    articles.sort(key=lambda x: x.get("published_at", ""), reverse=True)

    # 去重（按标题）
    seen_titles = set()
    deduped = []
    for a in articles:
        if a["title"] not in seen_titles:
            seen_titles.add(a["title"])
            deduped.append(a)
    articles = deduped

    # 今日快讯：当天文章，按时间倒序，最多40条
    flash = [a for a in articles if a.get("published_at", "").startswith(date_str)][:40]

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


def _pick_featured(articles: list, n: int = 5) -> list:
    """从文章列表中挑选轮播精选：优先有图，各分类均衡"""
    cats = ["platform", "industry", "rider", "opinion"]
    buckets = {c: [] for c in cats}
    others = []
    for a in articles:
        c = a.get("category", "industry")
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
    parser.add_argument("--input",  required=True, help="TrendRadar 新闻输出 JSON 路径")
    parser.add_argument("--hot",    default=None,  help="TrendRadar 热榜输出 JSON 路径（可选）")
    parser.add_argument("--output", required=True, help="输出 JSON 路径（如 data/2025-06-10.json）")
    args = parser.parse_args()
    transform(args.input, args.hot, args.output)
