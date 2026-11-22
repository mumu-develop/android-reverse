# -*- coding: utf-8 -*-
"""契约与自愈回归测试（对应架构标准 §10 的 3 道本地 gate）。

    1. 签名策略能从 settings 注入，且结构化满足 SigningStrategy
    2. stale-running 行被翻回 pending，且断点列保留
    3. fresh-running 行不被误收

跑法：
    python -m pytest tests/ -q
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 测试用独立 SQLite，避免污染开发库
_TMP = tempfile.mkdtemp(prefix="douyin_rev_test_")
os.environ["DY_DB_URL"] = "sqlite:///" + (Path(_TMP) / "test.db").as_posix()


@pytest.fixture(scope="module")
def db():
    from douyin_rev.db import init_db
    init_db()
    return True


def test_signing_strategy_is_settings_injected():
    """settings 里的字符串能被 load_object 实例化，且满足契约。"""
    from scrapy.utils.misc import load_object
    from douyin_rev.settings import SIGNING_STRATEGY
    from douyin_rev.signer.base import SigningStrategy

    strategy = load_object(SIGNING_STRATEGY)()
    assert isinstance(strategy, SigningStrategy)
    for m in ("warm", "sign", "close"):
        assert hasattr(strategy, m)


def test_reclaim_stale_running_keeps_resume_columns(db):
    """stale-running 翻回 pending，断点列一个都不能丢。"""
    from douyin_rev.db import session_scope
    from douyin_rev.db.models import UserTask
    from douyin_rev.tasks import task_state

    with session_scope() as s:
        row = UserTask(
            user_url="https://www.douyin.com/user/TEST_STALE",
            sec_user_id="MS4wLjABAAAAstale",
            status=task_state.ST_RUNNING,
            assigned_worker="w1",
            video_cursor=1787324406000,
            video_pages=7,
            video_index=3,
            comment_aweme_id="7704123225416945530",
            comment_cursor=40,
            comment_pages=2,
            updated_at=datetime.now() - timedelta(seconds=7200),
        )
        s.add(row)
        s.flush()
        tid = row.id

    n = task_state.reclaim_stale_running_user_task(threshold_sec=900)
    assert n >= 1

    with session_scope() as s:
        r = s.get(UserTask, tid)
        assert r.status == task_state.ST_PENDING
        assert r.assigned_worker is None
        # 断点列必须保留
        assert r.video_cursor == 1787324406000
        assert r.video_pages == 7
        assert r.video_index == 3
        assert r.comment_aweme_id == "7704123225416945530"
        assert r.comment_cursor == 40
        assert r.comment_pages == 2


def test_reclaim_does_not_touch_fresh_running(db):
    """刚更新的 running 行不能被误收。"""
    from douyin_rev.db import session_scope
    from douyin_rev.db.models import UserTask
    from douyin_rev.tasks import task_state

    with session_scope() as s:
        row = UserTask(
            user_url="https://www.douyin.com/user/TEST_FRESH",
            status=task_state.ST_RUNNING,
            assigned_worker="w2",
            updated_at=datetime.now(),
        )
        s.add(row)
        s.flush()
        tid = row.id

    task_state.reclaim_stale_running_user_task(threshold_sec=900)

    with session_scope() as s:
        r = s.get(UserTask, tid)
        assert r.status == task_state.ST_RUNNING
        assert r.assigned_worker == "w2"


def test_dispatcher_guard_ttl_ge_lock_ttl():
    """投喂 guard TTL 必须 ≥ 任务锁 TTL（否则会重复投喂）。"""
    from douyin_rev.tasks import dispatcher, task_state
    assert dispatcher.DISPATCH_GUARD_TTL >= task_state.LOCK_TTL


# ---------- video_task（评论拆分） ----------

def test_video_task_reclaim_keeps_cursor(db):
    """评论任务卡死自愈：翻回 pending 且保留 cursor/pages/fetched。"""
    from douyin_rev.db import session_scope
    from douyin_rev.db.models import VideoTask
    from douyin_rev.tasks import video_task_state as vts

    with session_scope() as s:
        row = VideoTask(aweme_id="TEST_VIDEO_STALE", status=vts.ST_RUNNING,
                        assigned_worker="w1", cursor=120, pages=6, fetched=115,
                        updated_at=datetime.now() - timedelta(seconds=3600))
        s.add(row)
        s.flush()
        tid = row.id

    n = vts.reclaim_stale_running_video_task(threshold_sec=600)
    assert n >= 1
    with session_scope() as s:
        r = s.get(VideoTask, tid)
        assert r.status == vts.ST_PENDING
        assert r.assigned_worker is None
        assert r.cursor == 120 and r.pages == 6 and r.fetched == 115


def test_video_task_lock_ttl_gt_lock(db):
    """自愈阈值必须大于锁 TTL（否则锁没释放就被回收）。"""
    from douyin_rev.tasks import video_task_state as vts
    assert vts.STALE_RUNNING_SEC > vts.LOCK_TTL


def test_video_task_claim_mutex(db):
    """同一个视频任务只能被一个 worker 抢到。"""
    import pytest
    from douyin_rev.db import session_scope
    from douyin_rev.db.models import VideoTask
    from douyin_rev.tasks import video_task_state as vts

    try:
        vts._redis().ping()
    except Exception:
        pytest.skip("Redis 不可用，跳过互斥测试")

    with session_scope() as s:
        row = VideoTask(aweme_id="TEST_VIDEO_LOCK", status=vts.ST_PENDING)
        s.add(row)
        s.flush()
        tid = row.id

    assert vts.claim_video_task(tid, "worker-A") is True
    assert vts.claim_video_task(tid, "worker-B") is False
    vts.complete_video_task(tid)
    with session_scope() as s:
        assert s.get(VideoTask, tid).status == vts.ST_COMPLETED
