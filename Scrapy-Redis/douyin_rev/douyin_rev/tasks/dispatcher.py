# -*- coding: utf-8 -*-
"""分发器（标准样板）：MySQL → Redis。

每拍顺序：
    1. reclaim_stale_running_user_task()   卡死行翻回 pending（同 tick 可被投喂）
    2. list_pending_tasks(limit)           取待抓
    3. SETNX guard                         防止同一任务在队列里被重复 LPUSH
    4. LPUSH 到 scrapy-redis 的 start_urls 队列

guard TTL ≥ LOCK_TTL，避免「pending 行在止血期内被每拍重复投喂」。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict

from .. import config
from . import task_state, video_task_state

log = logging.getLogger(__name__)

#: scrapy-redis 消费的队列键（spider 的 redis_key）
def start_urls_key() -> str:
    prefix = config.get_str("DY_QUEUE_PREFIX", "douyin_rev") or "douyin_rev"
    return prefix + ":start_urls"


#: 投喂去重 guard 的 TTL（秒），必须 ≥ LOCK_TTL
DISPATCH_GUARD_TTL = config.get_int("DY_DISPATCH_GUARD_TTL", 600)


def video_start_urls_key() -> str:
    """评论任务队列（video_task）。"""
    prefix = config.get_str("DY_QUEUE_PREFIX", "douyin_rev") or "douyin_rev"
    return prefix + ":video_start_urls"


def _video_guard_key(task_id: int) -> str:
    return "douyin_rev:video_dispatch_guard:%d" % task_id


def _guard_key(task_id: int) -> str:
    return "douyin_rev:dispatch_guard:%d" % task_id


def poll_pending_and_dispatch(limit: int = 50, dry_run: bool = False) -> Dict[str, Any]:
    """执行一拍分发，返回统计。"""
    reclaimed = task_state.reclaim_stale_running_user_task()
    rows = task_state.list_pending_tasks(limit=limit)
    r = task_state.redis_client()
    key = start_urls_key()

    pushed = 0
    skipped = 0
    for row in rows:
        tid = row["id"]
        if not r.set(_guard_key(tid), "1", nx=True, ex=DISPATCH_GUARD_TTL):
            skipped += 1
            continue
        if not dry_run:
            r.lpush(key, row["user_url"])
        pushed += 1

    if pushed:
        log.info("dispatch: reclaimed=%d pushed=%d skipped=%d queue=%d",
                 reclaimed, pushed, skipped, r.llen(key))
    return {
        "reclaimed": reclaimed,
        "pushed": pushed,
        "skipped": skipped,
        "queue": r.llen(key) if not dry_run else 0,
    }


def poll_pending_video_and_dispatch(limit: int = 100, dry_run: bool = False) -> Dict[str, Any]:
    """评论任务的一拍分发：video_task → Redis。"""
    reclaimed = video_task_state.reclaim_stale_running_video_task()
    rows = video_task_state.list_pending_video_tasks(limit=limit)
    r = task_state.redis_client()
    key = video_start_urls_key()

    pushed = skipped = 0
    for row in rows:
        tid = row["id"]
        if not r.set(_video_guard_key(tid), "1", nx=True, ex=DISPATCH_GUARD_TTL):
            skipped += 1
            continue
        if not dry_run:
            r.lpush(key, row["aweme_id"])
        pushed += 1

    if pushed:
        log.info("dispatch-video: reclaimed=%d pushed=%d skipped=%d queue=%d",
                 reclaimed, pushed, skipped, r.llen(key))
    return {"reclaimed": reclaimed, "pushed": pushed, "skipped": skipped,
            "queue": r.llen(key) if not dry_run else 0}


class Dispatcher(threading.Thread):
    """后台分发线程（和 scrapy 爬虫同进程跑）。"""

    def __init__(self, interval: float = 3.0, limit: int = 50) -> None:
        super().__init__(name="douyin-dispatcher", daemon=True)
        self.interval = interval
        self.limit = limit
        self._stop = threading.Event()

    def run(self) -> None:
        log.info("dispatcher 启动，队列=%s，间隔=%.1fs", start_urls_key(), self.interval)
        while not self._stop.is_set():
            try:
                poll_pending_and_dispatch(limit=self.limit)
                poll_pending_video_and_dispatch(limit=self.limit * 2)
            except Exception as e:  # 分发失败不能拖垮线程
                log.warning("dispatch 失败: %r", e)
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()
