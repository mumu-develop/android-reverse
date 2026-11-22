# -*- coding: utf-8 -*-
"""按 worker 数分别跑「全量作品列表」压测，输出日均容量。

用法：
    python scripts/bench_workers.py --workers 2 3 4 --seconds 240

流程（每个 worker 数一轮）：
    1. 清 Redis（队列/去重/冷却/guard）
    2. 重置 DB 与 user_task（全部 pending）
    3. 起 N 个 worker，跑 --seconds 秒（作品列表翻到底，评论关闭）
    4. 统计用户/视频条数与窗口，折算日均
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from douyin_rev.db import session_scope                       # noqa: E402
from douyin_rev.db.models import (                             # noqa: E402
    UserProfile, UserTask, UserVideo, UserVideoComment)
from douyin_rev.tasks import task_state                        # noqa: E402

PY = sys.executable


def signed_count() -> int:
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with op.open("http://127.0.0.1:8099/api/health", timeout=5) as r:
            return int(json.loads(r.read().decode()).get("signed") or 0)
    except Exception:
        return 0


def clear_redis() -> None:
    r = task_state.redis_client()
    for k in r.keys("douyin_rev*"):
        r.delete(k)


def reset_db() -> None:
    with session_scope() as s:
        s.query(UserVideoComment).delete()
        s.query(UserVideo).delete()
        s.query(UserProfile).delete()
        s.query(UserTask).update({
            "status": "pending", "profile_done": False, "videos_done": False,
            "comments_done": False, "video_cursor": 0, "video_pages": 0,
            "video_index": 0, "comment_pages": 0, "comment_cursor": 0,
            "comment_aweme_id": None, "assigned_worker": None,
        }, synchronize_session=False)


def seed(urls_file: Path) -> int:
    urls = [l.strip() for l in urls_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    with session_scope() as s:
        s.query(UserVideoComment).delete()
        s.query(UserVideo).delete()
        s.query(UserProfile).delete()
        s.query(UserTask).delete()
        for u in urls:
            sec = u.rsplit("/", 1)[-1]
            s.add(UserTask(user_url=u, sec_user_id=sec, status="pending"))
    return len(urls)


def stats() -> dict:
    with session_scope() as s:
        p = s.query(UserProfile).count()
        v = s.query(UserVideo).count()
        ts = [r[0] for r in s.query(UserProfile.fetched_at).all() if r[0]]
        ts += [r[0] for r in s.query(UserVideo.fetched_at).all() if r[0]]
    if not ts:
        return {"users": 0, "videos": 0, "window": 0}
    ts.sort()
    win = max(1.0, (ts[-1] - ts[0]).total_seconds())
    return {"users": p, "videos": v, "window": win}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, nargs="+", default=[2, 3, 4])
    ap.add_argument("--seconds", type=int, default=240)
    ap.add_argument("--urls", default="urls_full.txt")
    ap.add_argument("--video-pages", type=int, default=999)
    args = ap.parse_args()

    urls_file = ROOT / args.urls
    if not urls_file.exists():
        raise SystemExit("缺少任务文件: %s" % urls_file)

    rows = []
    for w in args.workers:
        print("\n=== %d worker ===" % w, flush=True)
        clear_redis()
        n = seed(urls_file)
        print("  任务: %d" % n, flush=True)

        before = signed_count()
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT)
        env["DY_DISPATCH_GUARD_TTL"] = "8"
        proc = subprocess.Popen(
            [PY, str(ROOT / "scripts" / "run_workers.py"),
             "--workers", str(w), "--seconds", str(args.seconds),
             "--video-pages", str(args.video_pages), "--comment-pages", "0"],
            cwd=str(ROOT), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc.wait()
        after = signed_count()

        st = stats()
        req = max(0, after - before)
        # 有效请求速率用「签名次数 / 实际写入窗口」，避免把启动/空转算进去
        win = st["window"]
        row = {
            "workers": w,
            "users": st["users"],
            "videos": st["videos"],
            "window": win,
            "req": req,
            "users_per_s": st["users"] / win,
            "videos_per_s": st["videos"] / win,
        }
        row["users_per_day"] = row["users_per_s"] * 86400
        row["videos_per_day"] = row["videos_per_s"] * 86400
        row["req_per_s"] = req / win
        rows.append(row)
        print("  用户 %d / 视频 %d / 窗口 %.0fs / 请求 %d" %
              (row["users"], row["videos"], win, req), flush=True)
        print("  → 用户 %.2f/s（%.0f/天）  视频 %.2f/s（%.0f/天）" %
              (row["users_per_s"], row["users_per_day"],
               row["videos_per_s"], row["videos_per_day"]), flush=True)
        time.sleep(2)

    print("\n===== 汇总 =====")
    print("%-8s %-8s %-10s %-12s %-12s %-12s" %
          ("worker", "窗口s", "请求", "用户/天", "视频/天", "请求/秒"))
    for r in rows:
        print("%-8d %-8.0f %-10d %-12.0f %-12.0f %-12.2f" %
              (r["workers"], r["window"], r["req"],
               r["users_per_day"], r["videos_per_day"], r["req_per_s"]))
    out = ROOT / "bench_workers_result.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n结果已写入", out)


if __name__ == "__main__":
    main()
