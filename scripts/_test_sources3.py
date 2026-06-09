#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 Bing News RSS 可用性（设计用于 GitHub Actions 境外服务器运行）
"""
import sys, urllib.request, ssl, re
sys.stdout.reconfigure(encoding='utf-8')

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

BASE = "https://www.bing.com/news/search?format=rss&mkt=zh-CN&setlang=zh-CN&cc=CN&q="

KEYWORDS = [
    ("外卖骑手",     "%E5%A4%96%E5%8D%96%E9%AA%91%E6%89%8B"),
    ("骑手权益",     "%E9%AA%91%E6%89%8B+%E6%9D%83%E7%9B%8A"),
    ("骑手收入",     "%E9%AA%91%E6%89%8B+%E6%94%B6%E5%85%A5"),
    ("骑手社保",     "%E9%AA%91%E6%89%8B+%E7%A4%BE%E4%BF%9D"),
    ("新就业形态",   "%E6%96%B0%E5%B0%B1%E4%B8%9A%E5%BD%A2%E6%80%81"),
    ("即时配送",     "%E5%8D%B3%E6%97%B6%E9%85%8D%E9%80%81"),
    ("美团骑手",     "%E7%BE%8E%E5%9B%A2%E9%AA%91%E6%89%8B"),
    ("灵活就业骑手", "%E7%81%B5%E6%B4%BB%E5%B0%B1%E4%B8%9A+%E9%AA%91%E6%89%8B"),
]

print(f"{'关键词':<16} {'状态':<7} {'格式':<10} {'条目数':<6} 最新一条标题")
print("-" * 100)

total_ok = 0
for kw, encoded in KEYWORDS:
    url = BASE + encoded
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; Feedfetcher-Google)',
            'Accept': 'application/rss+xml, application/xml, text/xml, */*',
        })
        resp = urllib.request.urlopen(req, context=ctx, timeout=12)
        content = resp.read(10000)
        is_xml = b'<?xml' in content or b'<rss' in content or b'<feed' in content
        fmt = '[RSS]  ' if is_xml else '[HTML] '
        if is_xml:
            items = re.findall(rb'<item[^>]*>.*?</item>', content, re.DOTALL)
            count = len(items)
            titles = re.findall(rb'<title[^>]*><!\[CDATA\[([^\]]+)\]\]></title>|<title[^>]*>([^<]{5,80})</title>', content)
            first = ''
            for t in titles[1:4]:
                candidate = (t[0] or t[1]).decode('utf-8', 'replace').strip()
                if len(candidate) > 5:
                    first = candidate[:60]
                    break
            total_ok += 1
        else:
            count = 0
            first = content[80:180].decode('utf-8', 'replace').replace('\n', ' ')[:60]
        print(f"{kw:<16} {resp.status:<7} {fmt:<10} {count:<6} {first}")
    except Exception as e:
        print(f"{kw:<16} ERROR   {str(e)[:75]}")

print()
print(f"==> Bing RSS 可用关键词: {total_ok}/{len(KEYWORDS)}")
if total_ok > 0:
    print("==> 结论: Bing News RSS 境外可用，可加入数据源")
else:
    print("==> 结论: Bing News RSS 境外不可用，放弃")
