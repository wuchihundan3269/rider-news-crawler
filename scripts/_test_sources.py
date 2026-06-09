#!/usr/bin/env python3
"""测试各新闻源在本地/境外的可用性"""
import urllib.request, ssl, socket

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

SOURCES = [
    # 百度新闻搜索
    ("百度新闻-骑手搜索",     "https://news.baidu.com/ns?word=%E9%AA%91%E6%89%8B&tn=news&sr=0&cl=2&rn=20&ct=1&clk=sortbytime"),
    ("百度新闻-外卖骑手搜索", "https://news.baidu.com/ns?word=%E5%A4%96%E5%8D%96%E9%AA%91%E6%89%8B&tn=news&sr=0&cl=2&rn=20&ct=1"),
    # 必应新闻 RSS（境外可用）
    ("必应新闻-骑手",         "https://www.bing.com/news/search?q=%E5%A4%96%E5%8D%96%E9%AA%91%E6%89%8B&format=rss&setlang=zh-CN"),
    ("必应新闻-外卖骑手",     "https://www.bing.com/news/search?q=%E5%A4%96%E5%8D%96%E9%AA%91%E6%89%8B+%E6%9D%83%E7%9B%8A&format=rss&setlang=zh-CN"),
    # 搜狗新闻 RSS
    ("搜狗新闻-骑手",         "https://news.sogou.com/news?query=%E5%A4%96%E5%8D%96%E9%AA%91%E6%89%8B&mode=1"),
    # 微博超话 RSS (rsshub)
    ("微博-骑手话题",          "https://rsshub.app/weibo/keyword/%E5%A4%96%E5%8D%96%E9%AA%91%E6%89%8B"),
    # 今日头条 RSS (rsshub)
    ("头条-骑手搜索",          "https://rsshub.app/toutiao/search/%E5%A4%96%E5%8D%96%E9%AA%91%E6%89%8B"),
    # 澎湃新闻搜索
    ("澎湃-骑手搜索",          "https://www.thepaper.cn/searchResult.jsp?searchword=%E9%AA%91%E6%89%8B"),
    # 腾讯新闻 RSS
    ("腾讯新闻-骑手",          "https://xw.qq.com/cgi-bin/news_list?versionFlag=1&chanid=0&subid=0&offset=0&num=20"),
]

print(f"{'来源':<22} {'状态':<8} {'内容类型':<30} {'前80字节'}")
print("-" * 100)
for name, url in SOURCES:
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/rss+xml, application/xml, text/xml, */*',
        })
        resp = urllib.request.urlopen(req, context=ctx, timeout=8)
        content = resp.read(200)
        ct = resp.headers.get('Content-Type', '')[:28]
        preview = content[:80].decode('utf-8', errors='replace').replace('\n', ' ')
        is_xml = b'<?xml' in content or b'<rss' in content or b'<feed' in content
        flag = '[XML]' if is_xml else '[HTML]'
        print(f"{name:<22} {resp.status} {flag:<7} {ct:<30} {preview[:55]}")
    except Exception as e:
        print(f"{name:<22} ERROR  {str(e)[:70]}")
