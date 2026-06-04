#!/usr/bin/env python3
"""
_test_rss.py — 测试所有 RSS 源可用性
用法：python scripts/_test_rss.py
在 GitHub Actions 环境运行效果最准确（境外服务器）
"""
import sys
import time
import yaml
import feedparser
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH  = PROJECT_ROOT / "trendradar-config" / "config.yaml"

with open(CONFIG_PATH, encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

feeds = cfg["rss"]["feeds"]
print(f"共 {len(feeds)} 个 RSS 源，开始测试...\n")

ok_list   = []
fail_list = []

for feed in feeds:
    name = feed["name"]
    url  = feed["url"]
    pri  = feed["priority"]
    try:
        result = feedparser.parse(url, request_headers={
            "User-Agent": "Mozilla/5.0 (compatible; RiderNewsBot/3.0)"
        })
        count = len(result.entries)
        status = result.get("status", 0)
        if count > 0:
            ok_list.append((pri, name, count, url))
            print(f"  ✓ [{pri}] {name}: {count} 条")
        elif status in (200, 301, 302):
            ok_list.append((pri, name, 0, url))
            print(f"  △ [{pri}] {name}: 可访问但 0 条 (status={status})")
        else:
            fail_list.append((pri, name, f"status={status}", url))
            print(f"  ✗ [{pri}] {name}: 失败 status={status}")
    except Exception as e:
        fail_list.append((pri, name, str(e)[:60], url))
        print(f"  ✗ [{pri}] {name}: 异常 {str(e)[:60]}")
    time.sleep(0.3)

print(f"\n{'='*60}")
print(f"可用: {len(ok_list)} / {len(feeds)}  失败: {len(fail_list)}")
if fail_list:
    print("\n【失败列表】")
    for pri, name, err, url in fail_list:
        print(f"  [{pri}] {name}: {err}")
        print(f"         {url}")
