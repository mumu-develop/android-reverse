# -*- coding: utf-8 -*-
"""只跑 spider（不启 dispatcher），配合 run_dispatcher.py 做多 worker。

用法：
    python scripts/run_spider.py --video-pages 2 --comment-pages 3
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapy.crawler import CrawlerProcess              # noqa: E402
from scrapy.utils.project import get_project_settings  # noqa: E402

from douyin_rev.db import init_db                      # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video-pages", type=int, default=None)
    ap.add_argument("--comment-pages", type=int, default=None)
    ap.add_argument("--run-seconds", type=int, default=0)
    args = ap.parse_args()

    init_db()
    settings = get_project_settings()
    if args.run_seconds:
        settings.set("CLOSESPIDER_TIMEOUT", args.run_seconds, priority="cmdline")
    if args.video_pages is not None:
        settings.set("DY_VIDEO_PAGES", args.video_pages, priority="cmdline")
    if args.comment_pages is not None:
        settings.set("DY_COMMENT_PAGES", args.comment_pages, priority="cmdline")

    process = CrawlerProcess(settings)
    kwargs = {}
    if args.video_pages is not None:
        kwargs["video_pages"] = args.video_pages
    if args.comment_pages is not None:
        kwargs["comment_pages"] = args.comment_pages
    process.crawl("user", **kwargs)
    process.start()


if __name__ == "__main__":
    main()
