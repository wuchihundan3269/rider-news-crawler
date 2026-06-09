#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试境外可用的中文新闻RSS源"""
import sys, urllib.request, ssl
sys.stdout.reconfigure(encoding='utf-8')

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

TESTS = [
    # 必应新闻 RSS（微软，境外服务器友好）
    ("Bing-外卖骑手",       "https://www.bing.com/news/search?q=%E5%A4%96%E5%8D%96%E9%AA%91%E6%89%8B&format=rss&setlang=zh-CN&cc=CN"),
    ("Bing-骑手权益",       "https://www.bing.com/news/search?q=%E9%AA%91%E6%89%8B+%E6%9D%83%E7%9B%8A&format=rss&setlang=zh-CN"),
    ("Bing-新就业形态",     "https://www.bing.com/news/search?q=%E6%96%B0%E5%B0%B1%E4%B8%9A%E5%BD%A2%E6%80%81&format=rss&setlang=zh-CN"),
    # FT中文网
    ("FT中文-RSS",          "https://www.ftchinese.com/rss/news"),
    ("FT中文-经济",         "https://www.ftchinese.com/rss/economy"),
    # 财新国际（英文版，境外可用）
    ("Caixin Global",       "https://www.caixinglobal.com/rss/"),
    # 南华早报中文
    ("SCMP中文",            "https://cn.scmp.com/rss/5/feed"),
    # 路透中文
    ("Reuters中文",         "https://feeds.reuters.com/reuters/CNTopNews"),
    # 香港01
    ("香港01-社会",         "https://www.hk01.com/rss/社會新聞"),
    # 端传媒
    ("端传媒",              "https://theinitium.com/feed/"),
    # 澎湃新闻（测试境外是否可用）
    ("澎湃-RSS",            "https://www.thepaper.cn/rss_cn.jsp"),
    # 搜狐新闻RSS
    ("搜狐-RSS",            "https://rss.sohu.com/rss/"),
    # 网易新闻RSS
    ("网易-RSS",            "https://news.163.com/special/00011K6L/rss_newstop.xml"),
    # 凤凰网RSS
    ("凤凰-RSS",            "https://rss.ifeng.com/"),
]

print(f"{'来源':<20} {'状态':<8} {'格式':<8} {'Content-Type':<35} 预览")
print("-" * 110)
for name, url in TESTS:
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; Feedfetcher-Google)',
            'Accept': 'application/rss+xml, application/xml, text/xml, */*',
        })
        resp = urllib.request.urlopen(req, context=ctx, timeout=10)
        content = resp.read(400)
        is_xml = b'<?xml' in content or b'<rss' in content or b'<feed' in content or b'<atom' in content
        ct = resp.headers.get('Content-Type', '')[:33]
        fmt = '[XML/RSS]' if is_xml else '[HTML]  '
        preview = content[50:180].decode('utf-8', errors='replace').replace('\n', ' ')[:70]
        print(f"{name:<20} {resp.status:<8} {fmt:<8} {ct:<35} {preview}")
    except Exception as e:
        print(f"{name:<20} ERROR    {str(e)[:80]}")
