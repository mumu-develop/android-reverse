# -*- coding: utf-8 -*-
"""worker：dispatcher + scrapy 爬虫一起跑（支持 user + comment 两个 spider）。

用法：
    python scripts/run_worker.py                       # 一直跑（dispatcher 持续投喂）
    python scripts/run_worker.py --run-seconds 300     # 跑满 N 秒自动停（压测）
    python scripts/run_worker.py --until-done          # 队列/任务都空了就退出
    python scripts/run_worker.py --spiders user        # 只跑 user（内联评论模式）
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapy.crawler import CrawlerProcess               # noqa: E402
from scrapy.utils.project import get_project_settings   # noqa: E402

from douyin_rev.db import init_db, session_scope        # noqa: E402
from douyin_rev.db.models import UserTask, VideoTask    # noqa: E402
from douyin_rev.tasks import dispatcher, task_state     # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("worker")


def _pending_counts():
    """(用户队列, 视频队列, 用户待抓, 视频待抓, 运行中)"""
    r = task_state.redis_client()
    with session_scope() as s:
        u_wait = (s.query(UserTask)
                  .filter(UserTask.status.in_([task_state.ST_PENDING,
                                               task_state.ST_PARTIAL])).count())
        v_wait = (s.query(VideoTask)
                  .filter(VideoTask.status.in_(["pending", "partial"])).count())
        running = (s.query(UserTask).filter(UserTask.status == task_state.ST_RUNNING).count()
                   + s.query(VideoTask).filter(VideoTask.status == "running").count())
    return (r.llen(dispatcher.start_urls_key()),
            r.llen(dispatcher.video_start_urls_key()),
            u_wait, v_wait, running)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spiders", default="user,comment",
                    help="逗号分隔：user,comment（拆分模式）或 user（内联模式）")
    ap.add_argument("--until-done", action="store_true")
    ap.add_argument("--video-pages", type=int, default=None)
    ap.add_argument("--comment-pages", type=int, default=None)
    ap.add_argument("--run-seconds", type=int, default=0, help="跑满 N 秒自动停")
    ap.add_argument("--idle-sec", type=int, default=20, help="队列空多久后退出")
    args = ap.parse_args()

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

    names = [x.strip() for x in args.spiders.split(",") if x.strip()]
    for name in names:
        process.crawl(name, **kwargs)
    log.info("启动 spider: %s", names)

    if not args.until_done:
        process.start()          # 阻塞到爬虫结束
        d.stop()
        return

    idle_since = {"t": None}
    stopped = {"v": False}

    def monitor():
        while not stopped["v"]:
            time.sleep(3)
            try:
                uq, vq, uw, vw, running = _pending_counts()
            except Exception as e:
                log.warning("监控统计失败: %r", e)
                continue
            if not (uq or vq or uw or vw or running):
                idle_since["t"] = idle_since["t"] or time.time()
                if time.time() - idle_since["t"] > args.idle_sec:
                    log.info("队列与任务都空了，停止爬虫")
                    stopped["v"] = True
                    d.stop()
                    try:
                        process.stop()          # 内部走已安装的 asyncio reactor
                    except Exception as e:
                        log.warning("停止爬虫失败: %r", e)
                    return
            else:
                idle_since["t"] = None

    threading.Thread(target=monitor, daemon=True).start()
    process.start()
    d.stop()


if __name__ == "__main__":
    main()
