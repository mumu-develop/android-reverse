# -*- coding: utf-8 -*-
"""评论任务状态机（video_task）。

与 task_state.py 同构，只是作用在「一个视频的评论采集」上：
    claim_video_task      抢占（SETNX + 行置 running）
    progress_video_task   推进 cursor / pages / fetched
    complete_video_task   完成
    fail_video_task       失败（partial 保留断点）
    reclaim_stale_running_video_task  卡死自愈
    list_pending_video_tasks          取待抓
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .. import config
from ..db import session_scope
from ..db.models import VideoTask

#: 任务状态（与 user_task 一致）
ST_PENDING = "pending"
ST_RUNNING = "running"
ST_PAUSED = "paused"
ST_PARTIAL = "partial"
ST_COMPLETED = "completed"
ST_FAILED = "failed"

LOCK_TTL = config.get_int("DY_VIDEO_LOCK_TTL", 900)
STALE_RUNNING_SEC = config.get_int("DY_VIDEO_STALE_RUNNING_SEC", 1200)


def _lock_key(task_id: int) -> str:
    return "douyin_rev:video_task_lock:%d" % task_id


def _redis():
    from .task_state import redis_client
    return redis_client()


def claim_video_task(task_id: int, worker: str) -> bool:
    """抢占一条评论任务。"""
    r = _redis()
    if not r.set(_lock_key(task_id), worker, nx=True, ex=LOCK_TTL):
        return False
    try:
        with session_scope() as s:
            row = s.get(VideoTask, task_id)
            if row is None or row.status == ST_COMPLETED:
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


def find_video_task(aweme_id: str) -> Optional[Dict[str, Any]]:
    with session_scope() as s:
        row = s.query(VideoTask).filter(VideoTask.aweme_id == aweme_id).first()
        if row is None:
            return None
        return {"id": row.id, "aweme_id": row.aweme_id,
                "sec_user_id": row.sec_user_id, "status": row.status}


def reload_video_task(task_id: int) -> Optional[Dict[str, Any]]:
    with session_scope() as s:
        row = s.get(VideoTask, task_id)
        if row is None:
            return None
        return {
            "id": row.id, "aweme_id": row.aweme_id, "sec_user_id": row.sec_user_id,
            "status": row.status, "cursor": int(row.cursor or 0),
            "pages": int(row.pages or 0), "fetched": int(row.fetched or 0),
            "total": int(row.total or 0), "attempts": int(row.attempts or 0),
        }


def progress_video_task(task_id: int, **fields: Any) -> None:
    allowed = {"cursor", "pages", "fetched", "total", "status", "last_error"}
    with session_scope() as s:
        row = s.get(VideoTask, task_id)
        if row is None:
            return
        for k, v in fields.items():
            if k in allowed:
                setattr(row, k, v)
        row.updated_at = datetime.now()


def complete_video_task(task_id: int) -> None:
    with session_scope() as s:
        row = s.get(VideoTask, task_id)
        if row is not None:
            row.status = ST_COMPLETED
            row.assigned_worker = None
            row.updated_at = datetime.now()
    _redis().delete(_lock_key(task_id))


def fail_video_task(task_id: int, error: str, partial: bool = False) -> None:
    with session_scope() as s:
        row = s.get(VideoTask, task_id)
        if row is not None:
            row.status = ST_PARTIAL if partial else ST_FAILED
            row.last_error = (error or "")[:500]
            row.assigned_worker = None
            row.updated_at = datetime.now()
    _redis().delete(_lock_key(task_id))


def release_video_lock(task_id: int) -> None:
    _redis().delete(_lock_key(task_id))


def reclaim_stale_running_video_task(threshold_sec: Optional[int] = None) -> int:
    """卡死自愈：running 超时翻回 pending，保留 cursor/pages/fetched。"""
    thr = int(threshold_sec or STALE_RUNNING_SEC)
    cutoff = datetime.now() - timedelta(seconds=thr)
    try:
        with session_scope() as s:
            rows = (s.query(VideoTask)
                    .filter(VideoTask.status == ST_RUNNING,
                            VideoTask.updated_at < cutoff)
                    .all())
            for row in rows:
                row.status = ST_PENDING
                row.assigned_worker = None
                row.updated_at = datetime.now()
            return len(rows)
    except Exception:
        return 0


def list_pending_video_tasks(limit: int = 50) -> List[Dict[str, Any]]:
    with session_scope() as s:
        rows = (s.query(VideoTask)
                .filter(VideoTask.status == ST_PENDING)
                .order_by(VideoTask.priority.desc(), VideoTask.id.asc())
                .limit(limit)
                .all())
        return [{"id": r.id, "aweme_id": r.aweme_id, "sec_user_id": r.sec_user_id}
                for r in rows]
