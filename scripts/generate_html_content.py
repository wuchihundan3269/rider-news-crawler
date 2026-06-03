#!/usr/bin/env python3
"""
generate_html_content.py
从最新爬虫数据生成 htmlContent.js，供 NoCode 项目使用。

用法：
  python scripts/generate_html_content.py \
    --template src/htmlContent.js \
    --data data/2026-06-02.json \
    --latest data/latest.json \
    --output /path/to/nocode-repo/src/htmlContent.js
"""
import argparse
import json
import re
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False


def load_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def save_file(path, content):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def resolve_google_news_url(url: str, timeout: int = 8) -> str:
    """将 Google News RSS 中间链接解析为真实原始 URL

    Google News 重定向链：
      第1次 GET → 302 → 同一 URL（加 hl/gl/ceid 参数）
      第2次 GET → 302 → 真实原文 URL（仅在境外服务器上）
    因此必须手动跟随每一步重定向，不能用 allow_redirects=True。
    """
    if not url or "news.google.com" not in url:
        return url

    if not _HAS_REQUESTS:
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
    session = _requests.Session()
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


def resolve_all_urls(data: dict) -> dict:
    """批量解析 data 中所有 Google News URL（并发执行）"""
    # 收集所有需要解析的 URL
    url_set = set()
    for key in ("featured", "articles", "flash"):
        for a in data.get(key, []):
            url = a.get("url", "")
            if url and "news.google.com" in url:
                url_set.add(url)

    if not url_set:
        print("[URL] 无需解析 Google News URL")
        return data

    print(f"[URL] 开始解析 {len(url_set)} 个 Google News URL（并发）...")
    url_map = {}

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_url = {executor.submit(resolve_google_news_url, u): u for u in url_set}
        for future in as_completed(future_to_url):
            orig = future_to_url[future]
            try:
                resolved = future.result()
                url_map[orig] = resolved
                if resolved != orig:
                    print(f"  ✓ {resolved[:80]}")
                else:
                    print(f"  ✗ 未解析: {orig[:60]}...")
            except Exception as e:
                url_map[orig] = orig
                print(f"  ✗ 异常: {e}")

    resolved_count = sum(1 for k, v in url_map.items() if k != v)
    print(f"[URL] 解析完成：{resolved_count}/{len(url_set)} 条成功")

    # 替换数据中的 URL
    def fix_list(lst):
        return [{**a, "url": url_map.get(a.get("url", ""), a.get("url", ""))} for a in lst]

    return {
        **data,
        "featured": fix_list(data.get("featured", [])),
        "articles": fix_list(data.get("articles", [])),
        "flash":    fix_list(data.get("flash", [])),
    }


def build_new_load_data(data: dict, latest: dict) -> str:
    """构建内嵌数据的 loadData 函数"""
    data_json = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    latest_json = json.dumps(latest, ensure_ascii=False, separators=(',', ':'))

    return f"""async function loadData(){{
  try {{
    // 内嵌数据（由 GitHub Actions 每小时自动更新）
    const latest = {latest_json};
    const data = {data_json};

    // 转换格式
    const articles = (data.articles || []).map((a, i) => apiToNews(a, i));
    const featured  = (data.featured  || []).map((a, i) => apiToNews(a, i));
    const flash     = (data.flash     || data.articles || []).map((a, i) => apiToNews(a, i));

    // featured 优先用于轮播，不足则从 articles 补
    NEWS = featured.length ? featured : articles.slice(0, 5);
    if(NEWS.length === 0) NEWS = articles.slice(0, 5);

    // FLASH_DATA：今日快讯，按时间倒序
    FLASH_DATA = flash.length ? flash : articles;
    FLASH_DATA.sort((a,b) => b.ts - a.ts);

    // 把全量 articles 也挂到全局供历史页面用
    window._allArticles = articles;
    window._dataDate = latest.date;
    window._dataUpdatedAt = latest.updated_at;

    _dataLoaded = true;
    console.log('[data] 内嵌数据加载成功', latest.date, '共', articles.length, '条');
  }} catch(e) {{
    console.warn('[data] 加载失败，使用 fallback 数据', e.message);
    NEWS = SAMPLE_NEWS;
    FLASH_DATA = SAMPLE_FLASH;
    window._allArticles = SAMPLE_NEWS.concat(SAMPLE_FLASH);
    window._dataDate = null;
    _dataLoaded = true;
  }}
}}"""


def main():
    parser = argparse.ArgumentParser(description='生成含内嵌数据的 htmlContent.js')
    parser.add_argument('--template', required=True, help='模板文件路径（当前 htmlContent.js）')
    parser.add_argument('--data', required=True, help='当天数据 JSON 文件路径')
    parser.add_argument('--latest', required=True, help='latest.json 文件路径')
    parser.add_argument('--output', required=True, help='输出文件路径')
    args = parser.parse_args()

    # 读取模板
    template = load_file(args.template)
    print(f'[1] 读取模板: {len(template)} 字符')

    # 读取数据
    with open(args.data, 'r', encoding='utf-8') as f:
        data = json.load(f)
    with open(args.latest, 'r', encoding='utf-8') as f:
        latest = json.load(f)
    print(f'[2] 读取数据: {latest["date"]}, 共 {latest["stats"]["total"]} 条')

    # 解析 Google News URL 为真实原始 URL
    data = resolve_all_urls(data)

    # 构建新的 loadData 函数
    new_load_data = build_new_load_data(data, latest)

    # 替换 loadData 函数
    pattern = r'async function loadData\(\)\{.*?\n\}'
    match = re.search(pattern, template, re.DOTALL)
    if not match:
        print('[ERROR] 未找到 loadData 函数，请检查模板文件', file=sys.stderr)
        sys.exit(1)

    new_content = template[:match.start()] + new_load_data + template[match.end():]
    print(f'[3] 替换 loadData 成功，新长度: {len(new_content)} 字符')

    # 验证
    if 'fetch(' in new_content:
        fetch_count = new_content.count('fetch(')
        print(f'[WARNING] 仍有 {fetch_count} 处 fetch() 调用，请检查')
    else:
        print('[4] 验证通过：无 fetch() 调用')

    # 写入输出
    save_file(args.output, new_content)
    print(f'[5] 写入 {args.output} 成功')


if __name__ == '__main__':
    main()
