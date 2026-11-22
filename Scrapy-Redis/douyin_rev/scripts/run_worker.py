# -*- coding: utf-8 -*-
"""worker：dispatcher + scrapy 爬虫一起跑。

用法：
    python scripts/run_worker.py                    # 一直跑（dispatcher 持续投喂）
    python scripts/run_worker.py --until-done       # 队列空了就退出（测日均量用）
    python scripts/run_worker.py --video-pages 5 --comment-pages 3
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapy.crawler import CrawlerProcess              # noqa: E402
from scrapy.utils.project import get_project_settings  # noqa: E402

from douyin_rev.db import init_db                      # noqa: E402
from douyin_rev.tasks import dispatcher, task_state    # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("worker")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--until-done", action="store_true",
                    help="待抓任务和队列都空就退出")
    ap.add_argument("--video-pages", type=int, default=None)
    ap.add_argument("--comment-pages", type=int, default=None)
    ap.add_argument("--idle-sec", type=int, default=20,
                    help="队列空多久后退出（配合 --until-done）")
    ap.add_argument("--run-seconds", type=int, default=0,
                    help="跑满 N 秒后自动停（压测用）")
    args = ap.parse_args()

    os.environ.setdefault("DY_LOG_LEVEL", "INFO")
    init_db()

    d = dispatcher.Dispatcher(interval=3.0, limit=50)
    d.start()

    settings = get_project_settings()
    if args.run_seconds:
        settings.set("CLOSESPIDER_TIMEOUT", args.run_seconds, priority="cmdline")
    process = CrawlerProcess(settings)
    kwargs = {}
    if args.video_pages is not None:
        kwargs["video_pages"] = args.video_pages
    if args.comment_pages is not None:
        kwargs["comment_pages"] = args.comment_pages
    crawler = process.create_crawler("user")

    if not args.until_done:
        process.crawl(crawler, **kwargs)
        process.start()          # 阻塞
        return

    # 轮询模式：队列空了且没有 running，就停
    r = task_state.redis_client()
    from douyin_rev.settings import REDIS_START_URLS_KEY

    crawl_done = {"v": False}

    def _run():
        process.crawl(crawler, **kwargs)
        process.start()
        crawl_done["v"] = True

    import threading
    t = threading.Thread(target=_run, daemon=True)
    t.start()

    idle_since = None
    while not crawl_done["v"]:
        time.sleep(2)
        pending = r.llen(REDIS_START_URLS_KEY)
        with task_state.session_scope() as s:
            running = (s.query(task_state.UserTask)
                       .filter(task_state.UserTask.status == task_state.ST_RUNNING)
                       .count())
            waiting = (s.query(task_state.UserTask)
                       .filter(task_state.UserTask.status.in_(
                           [task_state.ST_PENDING, task_state.ST_PARTIAL]))
                       .count())
        if pending == 0 and running == 0 and waiting == 0:
            idle_since = idle_since or time.time()
            if time.time() - idle_since > args.idle_sec:
                log.info("队列与任务都空了，停止爬虫")
                d.stop()
                process.stop()
                break
        else:
            idle_since = None

    t.join(timeout=60)


if __name__ == "__main__":
    main()
