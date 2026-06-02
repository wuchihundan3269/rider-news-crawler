#!/usr/bin/env python3
"""
提取 NoCode htmlContent.js 并替换 loadData() 为内嵌数据版本
"""
import json
import re
import os

LOG_FILE = r'C:\Users\LIXIYA~1\AppData\Local\Temp\catpaw-cli-shell\agent-tools\61b8e1f5-d9ab-4cb4-bd45-d33ea5ccbf37-shell-10.log'
DATA_FILE = r'C:\Users\lixiyang02\Desktop\骑手咨询网站\data\2026-06-02.json'
LATEST_FILE = r'C:\Users\lixiyang02\Desktop\骑手咨询网站\data\latest.json'
OUTPUT_FILE = r'C:\Users\lixiyang02\Desktop\骑手咨询网站\src\htmlContent.js'

# 1. 读取 log 文件，提取 htmlContent.js 内容
with open(LOG_FILE, 'r', encoding='utf-8') as f:
    log_content = f.read()

start_marker = '---FILE_CONTENT_START---\n'
end_marker = '\n---FILE_CONTENT_END---'
start_idx = log_content.find(start_marker) + len(start_marker)
end_idx = log_content.find(end_marker)
html_content_js = log_content[start_idx:end_idx]

print(f'[1] 提取 htmlContent.js 成功，长度: {len(html_content_js)} 字符')

# 2. 读取最新数据
with open(DATA_FILE, 'r', encoding='utf-8') as f:
    data = json.load(f)
with open(LATEST_FILE, 'r', encoding='utf-8') as f:
    latest = json.load(f)

print(f'[2] 读取数据成功: {latest["date"]}, 共 {latest["stats"]["total"]} 条')

# 3. 将数据序列化为 JS 字符串（注意转义反引号）
data_json = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
latest_json = json.dumps(latest, ensure_ascii=False, separators=(',', ':'))

# 4. 构建新的 loadData 函数（内嵌数据，不 fetch 外网）
new_load_data = f"""async function loadData(){{
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

# 5. 替换 loadData 函数
# 找到 async function loadData(){ ... } 的范围
old_load_data_pattern = r'async function loadData\(\)\{.*?\n\}'
match = re.search(old_load_data_pattern, html_content_js, re.DOTALL)
if match:
    print(f'[3] 找到 loadData 函数，位置: {match.start()}-{match.end()}')
    new_html_content_js = html_content_js[:match.start()] + new_load_data + html_content_js[match.end():]
    print(f'[3] 替换成功，新长度: {len(new_html_content_js)} 字符')
else:
    print('[3] 未找到 loadData 函数，检查正则...')
    # 尝试更宽松的匹配
    idx = html_content_js.find('async function loadData()')
    print(f'    loadData 位置: {idx}')
    if idx >= 0:
        print(f'    上下文: {html_content_js[idx:idx+200]}')
    exit(1)

# 6. 写入输出文件
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    f.write(new_html_content_js)

print(f'[4] 写入 {OUTPUT_FILE} 成功')
print('[完成] htmlContent.js 已更新，loadData 改为内嵌数据版本')
