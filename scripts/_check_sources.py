#!/usr/bin/env python3
"""查看当前数据文件中各来源和分类分布"""
import json
from collections import Counter
from pathlib import Path

# 找最新的数据文件
data_files = sorted(Path("data").glob("2026-*.json"))
latest = data_files[-1] if data_files else None
if not latest:
    print("没有找到数据文件")
    exit()

print(f"数据文件: {latest}")
with open(latest, encoding="utf-8") as f:
    d = json.load(f)

articles = d.get("articles", [])
print(f"总文章数: {len(articles)}")
print(f"生成时间: {d.get('generated_at', '?')}")
print()

print("=== 各来源分布 ===")
sources = Counter(a.get("source", "?") for a in articles)
for s, n in sources.most_common():
    print(f"  {n}条  {s}")

print()
print("=== 各分类分布 ===")
cats = Counter(a.get("category", "?") for a in articles)
for c, n in cats.most_common():
    print(f"  {n}条  {c}")

print()
print("=== 最新5条文章 ===")
for a in articles[:5]:
    print(f"  [{a.get('published_at','')[:16]}] {a.get('source','?')} | {a.get('title','')[:50]}")
