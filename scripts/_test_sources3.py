#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试各新闻源可用性（设计用于 GitHub Actions 境外服务器运行）
本地运行结果仅供参考，以 Actions 运行结果为准
"""
import sys, urllib.request, urllib.parse, ssl, re
sys.stdout.reconfigure(encoding='utf-8')

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

TESTS = [
    # ── 已知可用（Actions 实测）──
    ("Google-外卖骑手[已用]",  "https://news.google.com/rss/search?q=%E5%A4%96%E5%8D%96%E9%AA%91%E6%89%8B&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"),
    ("新华网-财经[已用]",       "http://www.xinhuanet.com/fortune/news_fortune.xml"),
    # ── 待测：Bing News RSS ──
    ("Bing-外卖骑手",          "https://www.bing.com/news/search?q=%E5%A4%96%E5%8D%96%E9%AA%91%E6%89%8B&format=rss&mkt=zh-CN"),
    ("Bing-骑手权益",          "https://www.bing.com/news/search?q=%E9%AA%91%E6%89%8B+%E6%9D%83%E7%9B%8A&format=rss&mkt=zh-CN"),
    ("Bing-灵活就业",          "https://www.bing.com/news/search?q=%E7%81%B5%E6%B4%BB%E5%B0%B1%E4%B8%9A+%E9%AA%91%E6%89%8B&format=rss&mkt=zh-CN"),
    # ── 待测：联合早报（新加坡中文媒体，境外友好）──
    ("联合早报-中国",           "https://www.zaobao.com.sg/rss/china"),
    ("联合早报-财经",           "https://www.zaobao.com.sg/rss/finance"),
    # ── 待测：BBC/DW/RFI 中文 ──
    ("BBC中文",                "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml"),
    ("DW中文",                 "https://rss.dw.com/xml/rss-zh-all"),
    ("RFI中文",                "https://www.rfi.fr/cn/rss"),
    # ── 待测：网易新闻 RSS ──
    ("网易-新闻",               "https://news.163.com/special/00011K6L/rss_newstop.xml"),
    # ── 待测：澎湃新闻 ──
    ("澎湃-RSS",               "https://www.thepaper.cn/rss_cn.jsp"),
    # ── 待测：财新国际 ──
    ("财新-国际",               "https://www.caixinglobal.com/rss/"),
    # ── 待测：南华早报 ──
    ("SCMP-中文",              "https://cn.scmp.com/rss/5/feed"),
    # ── 待测：香港01 ──
    ("香港01-社会",             "https://www.hk01.com/rss/%E7%A4%BE%E6%9C%83%E6%96%B0%E8%81%9E"),
    # ── 待测：端传媒 ──
    ("端传媒",                  "https://theinitium.com/feed/"),
    # ── 待测：明报 ──
    ("明报-中国",               "https://news.mingpao.com/rss/pns/s00013.xml"),
]

print(f"{'来源':<22} {'状态':<7} {'格式':<10} {'条目数':<6} 第一条标题")
print("-" * 110)
for name, url in TESTS:
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; Feedfetcher-Google; +http://www.google.com/feedfetcher.html)',
            'Accept': 'application/rss+xml, application/xml, text/xml, */*',
        })
        resp = urllib.request.urlopen(req, context=ctx, timeout=12)
        content = resp.read(8000)
        is_xml = b'<?xml' in content or b'<rss' in content or b'<feed' in content
        fmt = '[RSS]  ' if is_xml else '[HTML] '
        if is_xml:
            items = re.findall(rb'<item[^>]*>.*?</item>', content, re.DOTALL)
            count = len(items)
            titles = re.findall(rb'<title[^>]*><!\[CDATA\[([^\]]+)\]\]></title>|<title[^>]*>([^<]{5,80})</title>', content)
            first = ''
            for t in titles[1:3]:
                candidate = (t[0] or t[1]).decode('utf-8', 'replace').strip()
                if len(candidate) > 5:
                    first = candidate[:55]
                    break
        else:
            count = 0
            first = content[80:160].decode('utf-8','replace').replace('\n',' ')[:55]
        print(f"{name:<22} {resp.status:<7} {fmt:<10} {count:<6} {first}")
    except Exception as e:
        print(f"{name:<22} ERROR   {str(e)[:75]}")
