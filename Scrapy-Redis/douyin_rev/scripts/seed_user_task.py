# -*- coding: utf-8 -*-
"""往 user_task 里插入任务（幂等）。

用法：
    python scripts/seed_user_task.py <主页链接> [更多链接...]
    python scripts/seed_user_task.py --file urls.txt
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# 让脚本能在工程根目录外运行
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from douyin_rev.db import init_db, session_scope          # noqa: E402
from douyin_rev.db.models import UserTask                 # noqa: E402

SEC_RE = re.compile(r"MS4wLjABAAAA[\w\-]+")


def seed(urls):
    init_db()
    added = skipped = 0
    with session_scope() as s:
        for url in urls:
            url = url.strip()
            if not url:
                continue
            m = SEC_RE.search(url)
            if m is None:
                print("[跳过] 不是用户主页链接:", url[:80])
                skipped += 1
                continue
            sec = m.group(0)
            exists = s.query(UserTask).filter(UserTask.user_url == url).one_or_none()
            if exists is not None:
                skipped += 1
                continue
            s.add(UserTask(user_url=url, sec_user_id=sec, status="pending"))
            added += 1
    print("插入 %d 条，跳过 %d 条" % (added, skipped))
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="*", help="抖音用户主页链接")
    ap.add_argument("--file", help="从文本文件读（一行一个链接）")
    args = ap.parse_args()

    urls = list(args.urls)
    if args.file:
        urls.extend(Path(args.file).read_text(encoding="utf-8").splitlines())
    if not urls:
        ap.error("至少给一个链接，或用 --file")
    seed(urls)


if __name__ == "__main__":
    main()
