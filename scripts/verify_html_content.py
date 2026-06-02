with open('src/htmlContent.js', 'r', encoding='utf-8') as f:
    content = f.read()
print('文件大小:', len(content), '字符')
if '内嵌数据' in content:
    print('loadData 已替换为内嵌数据版本 OK')
else:
    print('ERROR: loadData 未替换')
if '2026-06-02' in content:
    print('数据日期 2026-06-02 存在 OK')
if content.startswith('export const htmlContent'):
    print('export 语句正确 OK')
else:
    print('ERROR: export 语句不正确')
    print('开头:', content[:200])
# 检查fetch是否还存在
fetch_count = content.count('fetch(')
print(f'fetch() 调用次数: {fetch_count} (应为0)')
