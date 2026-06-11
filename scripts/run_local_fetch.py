#!/usr/bin/env python3
"""
run_local_fetch.py — 本地定时抓取 + 自动推送脚本

功能：
  1. 运行 fetch_news_v3.py 抓取新闻（含百度新闻，本地可访问）
  2. 运行 fetch_hot.py 抓取热榜
  3. 运行 transform.py 转换为网站格式（累积追加）
  4. git pull → git add → git commit → git push

用法：
  python scripts/run_local_fetch.py
  python scripts/run_local_fetch.py --date 2025-06-10
  python scripts/run_local_fetch.py --dry-run   # 只抓取不推送，用于测试

由 Windows 计划任务每小时调用，无需人工干预。
日志写入：logs/local_fetch.log（自动滚动，保留最近 7 天）
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 路径常量 ──────────────────────────────────────────────────────────────────
REPO_ROOT   = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
CONFIG_FILE = REPO_ROOT / "trendradar-config" / "config.yaml"
WORDS_FILE  = REPO_ROOT / "trendradar-config" / "frequency_words.txt"
NEWS_DIR    = REPO_ROOT / "trendradar" / "output" / "news"
DATA_DIR    = REPO_ROOT / "data"
LOG_DIR     = REPO_ROOT / "logs"

# ── 日志配置 ──────────────────────────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
log_file = LOG_DIR / "local_fetch.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def run(cmd: list[str], cwd: Path = REPO_ROOT, check: bool = True) -> subprocess.CompletedProcess:
    """运行子进程，实时打印输出，失败时抛出异常。"""
    log.info("运行: %s", " ".join(str(c) for c in cmd))
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"命令失败 (exit {result.returncode}): {' '.join(str(c) for c in cmd)}")
    return result


def get_beijing_date() -> str:
    """返回当前北京时间日期字符串 YYYY-MM-DD。"""
    tz_beijing = timezone(timedelta(hours=8))
    return datetime.now(tz_beijing).strftime("%Y-%m-%d")


def get_beijing_datetime() -> str:
    """返回当前北京时间字符串 YYYY-MM-DD HH:MM。"""
    tz_beijing = timezone(timedelta(hours=8))
    return datetime.now(tz_beijing).strftime("%Y-%m-%d %H:%M")


def cleanup_old_logs(days: int = 7):
    """清理超过 days 天的日志行（按日期前缀过滤）。"""
    if not log_file.exists():
        return
    cutoff = datetime.now() - timedelta(days=days)
    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    kept = []
    for line in lines:
        try:
            line_date = datetime.strptime(line[:10], "%Y-%m-%d")
            if line_date >= cutoff:
                kept.append(line)
        except ValueError:
            kept.append(line)  # 无法解析日期的行保留
    log_file.write_text("".join(kept), encoding="utf-8")


def step_fetch_news(date: str, skip_baidu: bool = False):
    """步骤1：抓取新闻。skip_baidu=True 时跳过百度管道，只抓 RSS/Google。"""
    log.info("=" * 60)
    mode = "仅RSS/Google（夜间模式）" if skip_baidu else "百度+RSS/Google（白天模式）"
    log.info("步骤1：抓取新闻 (date=%s, 模式=%s)", date, mode)
    NEWS_DIR.mkdir(parents=True, exist_ok=True)
    output_file = NEWS_DIR / f"{date}.json"
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "fetch_news_v3.py"),
        "--date",   date,
        "--output", str(output_file),
        "--config", str(CONFIG_FILE),
        "--words",  str(WORDS_FILE),
    ]
    if skip_baidu:
        cmd.append("--skip-baidu")
    run(cmd)
    if output_file.exists():
        with open(output_file, encoding="utf-8") as f:
            d = json.load(f)
        log.info("抓取完成：共 %d 条，分类=%s", d.get("total", 0), d.get("by_category", {}))
    else:
        raise FileNotFoundError(f"抓取输出文件不存在: {output_file}")
    return output_file


def step_fetch_hot():
    """步骤2：抓取热榜数据。"""
    log.info("步骤2：抓取热榜数据")
    hot_file = DATA_DIR / "hot.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    result = run([
        sys.executable,
        str(SCRIPTS_DIR / "fetch_hot.py"),
        "--output", str(hot_file),
    ], check=False)
    if result.returncode != 0:
        log.warning("热榜抓取失败（不影响主流程），继续执行")
    else:
        log.info("热榜抓取完成: %s", hot_file)


def step_transform(date: str, news_file: Path):
    """步骤3：转换为网站格式（累积追加）。"""
    log.info("步骤3：转换数据格式 (累积追加)")
    output_file = DATA_DIR / f"{date}.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "transform.py"),
        "--input",  str(news_file),
        "--output", str(output_file),
    ]
    if output_file.exists():
        log.info("已有数据文件，执行累积追加合并: %s", output_file)
        cmd += ["--existing", str(output_file)]
    else:
        log.info("首次生成: %s", output_file)
    run(cmd)
    if output_file.exists():
        with open(output_file, encoding="utf-8") as f:
            d = json.load(f)
        articles = d.get("articles", [])
        log.info("转换完成：共 %d 篇文章", len(articles))
    return output_file


def step_update_latest(date: str, data_file: Path):
    """步骤4：更新 latest.json 指针。"""
    log.info("步骤4：更新 latest.json")
    with open(data_file, encoding="utf-8") as f:
        d = json.load(f)
    articles = d.get("articles", [])
    cats: dict[str, int] = {}
    for a in articles:
        c = a.get("category", "unknown")
        cats[c] = cats.get(c, 0) + 1

    latest = {
        "date":       date,
        "updated_at": get_beijing_datetime(),
        "file":       f"data/{date}.json",
        "stats": {
            "total":       len(articles),
            "by_category": cats,
        },
    }
    latest_file = DATA_DIR / "latest.json"
    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)
    log.info("latest.json 已更新: %s", latest)


def _sync_data_to_ghpages(datetime_str: str, dry_run: bool = False):
    """
    把 data/*.json 直接 checkout 到 gh-pages 分支并 push。
    策略：worktree 方式，不切换当前分支，避免影响工作区。
    """
    import shutil
    worktree_dir = REPO_ROOT / "_ghpages_worktree"

    try:
        # 清理可能残留的 worktree
        if worktree_dir.exists():
            run(["git", "worktree", "remove", "--force", str(worktree_dir)], check=False)
            shutil.rmtree(worktree_dir, ignore_errors=True)

        # 拉取最新 gh-pages
        run(["git", "fetch", "origin", "gh-pages"], check=False)

        # 添加 worktree（指向 gh-pages 分支）
        run(["git", "worktree", "add", str(worktree_dir), "origin/gh-pages"])

        # 把 data/*.json 复制进 worktree
        src_data = REPO_ROOT / "data"
        dst_data = worktree_dir / "data"
        dst_data.mkdir(parents=True, exist_ok=True)
        copied = 0
        for f in src_data.glob("*.json"):
            shutil.copy2(f, dst_data / f.name)
            copied += 1
        log.info("复制 %d 个 JSON 文件到 gh-pages worktree", copied)

        if dry_run:
            log.info("[dry-run] 跳过 gh-pages commit & push")
            return

        # 在 worktree 里 commit & push
        run(["git", "add", "data/"], cwd=worktree_dir)
        result = run(["git", "diff", "--staged", "--quiet"], cwd=worktree_dir, check=False)
        if result.returncode == 0:
            log.info("gh-pages data/ 无变化，跳过")
            return

        run(["git", "commit", "-m", f"deploy-data: {datetime_str} 本地直推（含百度新闻）"],
            cwd=worktree_dir)
        _git_push_with_retry_cwd("gh-pages", worktree_dir)
        log.info("[OK] gh-pages 已更新，网站将在数秒内刷新")

    finally:
        # 清理 worktree
        run(["git", "worktree", "remove", "--force", str(worktree_dir)], check=False)
        shutil.rmtree(worktree_dir, ignore_errors=True)


def _git_push_with_retry_cwd(branch: str, cwd: Path, max_retry: int = 3):
    """在指定目录 push 分支，失败时重试。"""
    import time
    for attempt in range(1, max_retry + 1):
        log.info("第 %d 次尝试 push %s...", attempt, branch)
        result = run(["git", "push", "origin", f"HEAD:{branch}"], cwd=cwd, check=False)
        if result.returncode == 0:
            log.info("push %s 成功！", branch)
            return
        log.warning("push 失败，%d 秒后重试...", attempt * 10)
        time.sleep(attempt * 10)
    raise RuntimeError(f"git push {branch} 失败，已重试 {max_retry} 次")


def _git_push_with_retry(branch: str, max_retry: int = 3):
    """push 指定分支，失败时 pull --rebase 后重试。"""
    import time
    for attempt in range(1, max_retry + 1):
        log.info("第 %d 次尝试 push %s...", attempt, branch)
        result = run(["git", "push", "origin", branch], check=False)
        if result.returncode == 0:
            log.info("push %s 成功！", branch)
            return
        log.warning("push 失败，%d 秒后重试...", attempt * 10)
        time.sleep(attempt * 10)
        run(["git", "pull", "--rebase", "origin", branch], check=False)
    raise RuntimeError(f"git push {branch} 失败，已重试 {max_retry} 次")


def step_git_push(date: str, dry_run: bool = False):
    """步骤5：push main + 直接同步 data/ 到 gh-pages（立即部署，无需等 Actions）。"""
    log.info("步骤5：Git 推送")
    datetime_str = get_beijing_datetime()

    # ── 5a. 同步 main 分支 ──────────────────────────────────────────
    run(["git", "stash"], check=False)
    run(["git", "pull", "--rebase", "origin", "main"], check=False)
    run(["git", "stash", "pop"], check=False)

    run(["git", "add", "data/"])

    result = run(["git", "diff", "--staged", "--quiet"], check=False)
    has_changes = (result.returncode != 0)

    commit_msg = f"data: {datetime_str} 本地自动更新（含百度新闻）"
    if dry_run:
        log.info("[dry-run] 跳过 commit & push，commit message 将是: %s", commit_msg)
        return

    if has_changes:
        run(["git", "commit", "-m", commit_msg])
        _git_push_with_retry("main")
    else:
        log.info("main 分支没有新数据，跳过提交")

    # ── 5b. 直接把 data/ 同步到 gh-pages，立即触发网站更新 ─────────
    # gh-pages 分支由 peaceiris/actions-gh-pages 管理，结构是整个网站根目录
    # 我们只需要把 data/*.json 覆盖进去即可，其余文件不动
    log.info("步骤5b：同步 data/ 到 gh-pages 分支（立即部署）")
    _sync_data_to_ghpages(datetime_str, dry_run)


def get_beijing_hour() -> int:
    """返回当前北京时间的小时数（0-23）。"""
    tz_beijing = timezone(timedelta(hours=8))
    return datetime.now(tz_beijing).hour


def main():
    parser = argparse.ArgumentParser(description="本地定时抓取 + 自动推送")
    parser.add_argument("--date",        default="",    help="目标日期 YYYY-MM-DD，默认今天（北京时间）")
    parser.add_argument("--dry-run",     action="store_true", help="只抓取不推送，用于测试")
    parser.add_argument("--skip-baidu",  action="store_true", help="强制跳过百度抓取")
    parser.add_argument("--force-baidu", action="store_true", help="强制开启百度抓取（忽略时间判断）")
    args = parser.parse_args()

    date = args.date.strip() or get_beijing_date()

    # 白天模式（10:00-18:59 北京时间）：抓百度；其他时间：仅RSS/Google
    hour = get_beijing_hour()
    if args.force_baidu:
        skip_baidu = False
    elif args.skip_baidu:
        skip_baidu = True
    else:
        skip_baidu = not (10 <= hour <= 18)  # 19:00 起进入夜间模式

    mode_label = "夜间(仅RSS/Google)" if skip_baidu else "白天(百度+RSS/Google)"
    log.info("=" * 60)
    log.info("[START] 本地自动抓取启动  date=%s  hour=%d  模式=%s  dry_run=%s",
             date, hour, mode_label, args.dry_run)
    log.info("=" * 60)

    try:
        cleanup_old_logs(days=7)
        news_file  = step_fetch_news(date, skip_baidu=skip_baidu)
        step_fetch_hot()
        data_file  = step_transform(date, news_file)
        step_update_latest(date, data_file)
        step_git_push(date, dry_run=args.dry_run)
        log.info("[OK] 全部完成！%s", get_beijing_datetime())
    except Exception as e:
        log.error("[FAIL] 执行失败: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
