# -*- coding: utf-8 -*-
"""任务状态机（标准样板，依赖 db 契约）。

职责：
    claim            抢占任务（SETNX 互斥 + 行置 running）
    progress         推进断点（cursor / 页码 / 阶段标记）
    complete / fail  终态回写
    reclaim_stale_running_user_task  卡死自愈（running 超时翻回 pending）

自愈只针对「喂源表」user_task（被 dispatcher LPUSH 的那张），
不动分页指纹（本站没有第二张表，规则天然满足）。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import redis

from .. import config
from ..db import session_scope
from ..db.models import UserTask

#: 任务状态
ST_PENDING = "pending"
ST_RUNNING = "running"
ST_PAUSED = "paused"
ST_PARTIAL = "partial"
ST_COMPLETED = "completed"
ST_FAILED = "failed"

#: SETNX 锁 TTL（秒）
LOCK_TTL = config.get_int("DY_LOCK_TTL", 600)

#: 自愈阈值必须 > LOCK_TTL，否则锁还没过期就把行翻回 pending
STALE_RUNNING_SEC = config.get_int("DY_STALE_RUNNING_SEC", 900)


def redis_client() -> redis.Redis:
    url = config.get_str("DY_REDIS_URL")
    if url:
        return redis.Redis.from_url(url, decode_responses=True)
    return redis.Redis(
        host=config.get_str("REDIS_HOST", "127.0.0.1"),
        port=config.get_int("REDIS_PORT", 6379),
        db=config.get_int("REDIS_DB", 0),
        decode_responses=True,
    )


def _lock_key(task_id: int) -> str:
    return "douyin_rev:task_lock:%d" % task_id


def claim_task(task_id: int, worker: str) -> bool:
    """抢占任务：Redis SETNX 互斥 + DB 行置 running。

    返回 True 表示抢到（可以开始抓），False 表示别的 worker 正在抓。
    """
    r = redis_client()
    if not r.set(_lock_key(task_id), worker, nx=True, ex=LOCK_TTL):
        return False
    try:
        with session_scope() as s:
            row = s.get(UserTask, task_id)
            if row is None:
                r.delete(_lock_key(task_id))
                return False
            if row.status in (ST_COMPLETED,):
                r.delete(_lock_key(task_id))
                return False
            row.status = ST_RUNNING
            row.assigned_worker = worker
            row.attempts = (row.attempts or 0) + 1
            row.updated_at = datetime.now()
            return True
    except Exception:
        r.delete(_lock_key(task_id))
        raise


def reload_task(task_id: int) -> Optional[Dict[str, Any]]:
    """取任务快照（dict），供 spider 读断点。"""
    with session_scope() as s:
        row = s.get(UserTask, task_id)
        if row is None:
            return None
        return {
            "id": row.id,
            "user_url": row.user_url,
            "sec_user_id": row.sec_user_id,
            "status": row.status,
            "profile_done": bool(row.profile_done),
            "videos_done": bool(row.videos_done),
            "comments_done": bool(row.comments_done),
            "video_cursor": int(row.video_cursor or 0),
            "video_pages": int(row.video_pages or 0),
            "video_index": int(row.video_index or 0),
            "comment_aweme_id": row.comment_aweme_id,
            "comment_cursor": int(row.comment_cursor or 0),
            "comment_pages": int(row.comment_pages or 0),
            "attempts": int(row.attempts or 0),
        }


def find_task_by_url(user_url: str) -> Optional[Dict[str, Any]]:
    """按主页链接查任务（dispatcher 只投 URL）。"""
    with session_scope() as s:
        row = (s.query(UserTask)
               .filter(UserTask.user_url == user_url)
               .first())
        if row is None:
            return None
        return {"id": row.id, "sec_user_id": row.sec_user_id, "status": row.status}


def touch(task_id: int) -> None:
    """刷新 updated_at（长翻页时防止被自愈误收）。"""
    with session_scope() as s:
        row = s.get(UserTask, task_id)
        if row is not None:
            row.updated_at = datetime.now()


def progress(task_id: int, **fields: Any) -> None:
    """推进断点。

    允许的字段：
        profile_done / videos_done / comments_done
        video_cursor / video_pages / video_index
        comment_aweme_id / comment_cursor / comment_pages
    """
    allowed = {
        "profile_done", "videos_done", "comments_done",
        "video_cursor", "video_pages", "video_index",
        "comment_aweme_id", "comment_cursor", "comment_pages",
        "status",
    }
    with session_scope() as s:
        row = s.get(UserTask, task_id)
        if row is None:
            return
        for k, v in fields.items():
            if k in allowed:
                setattr(row, k, v)
        row.updated_at = datetime.now()


def complete_task(task_id: int, worker: str) -> None:
    with session_scope() as s:
        row = s.get(UserTask, task_id)
        if row is not None:
            row.status = ST_COMPLETED
            row.assigned_worker = None
            row.updated_at = datetime.now()
    redis_client().delete(_lock_key(task_id))


def fail_task(task_id: int, error: str, worker: str = "", partial: bool = False) -> None:
    with session_scope() as s:
        row = s.get(UserTask, task_id)
        if row is not None:
            row.status = ST_PARTIAL if partial else ST_FAILED
            row.last_error = (error or "")[:500]
            row.assigned_worker = None
            row.updated_at = datetime.now()
    redis_client().delete(_lock_key(task_id))


def release_lock(task_id: int) -> None:
    redis_client().delete(_lock_key(task_id))


# ---------- 自愈 / 投喂 ----------


def reclaim_stale_running_user_task(threshold_sec: Optional[int] = None) -> int:
    """把卡死的 running 行翻回 pending（保留全部断点列）。

    吞异常返回 0 —— 绝不能因为自愈失败卡住 dispatcher 主循环。
    """
    thr = int(threshold_sec or STALE_RUNNING_SEC)
    cutoff = datetime.now() - timedelta(seconds=thr)
    try:
        with session_scope() as s:
            rows = (s.query(UserTask)
                    .filter(UserTask.status == ST_RUNNING,
                            UserTask.updated_at < cutoff)
                    .all())
            for row in rows:
                row.status = ST_PENDING
                row.assigned_worker = None
                row.updated_at = datetime.now()
            return len(rows)
    except Exception:
        return 0


def list_pending_tasks(limit: int = 50) -> List[Dict[str, Any]]:
    """取待抓任务（pending 优先，其次 paused 冷却够的）。"""
    with session_scope() as s:
        rows = (s.query(UserTask)
                .filter(UserTask.status == ST_PENDING)
                .order_by(UserTask.priority.desc(), UserTask.id.asc())
                .limit(limit)
                .all())
        return [{"id": r.id, "user_url": r.user_url, "sec_user_id": r.sec_user_id}
                for r in rows]
