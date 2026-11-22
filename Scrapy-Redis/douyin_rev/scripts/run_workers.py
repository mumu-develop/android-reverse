# -*- coding: utf-8 -*-
"""水平扩展：1 个 dispatcher + N 个 spider 进程。

用法：
    python scripts/run_workers.py --workers 3 --seconds 180 --video-pages 2 --comment-pages 3

所有进程共享：
    · Redis 队列（scrapy-redis）
    · 设备冷却状态（signer/scheduler.py 的 Redis 键）
    · DB 行锁（task_lock / dispatch_guard）
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
PY = sys.executable


def spawn(args):
    return subprocess.Popen([PY] + args, cwd=str(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seconds", type=int, default=180)
    ap.add_argument("--video-pages", type=int, default=2)
    ap.add_argument("--comment-pages", type=int, default=3)
    args = ap.parse_args()

    procs = []
    # dispatcher 多跑 20 秒，保证队列喂得比消费久
    procs.append(spawn([str(SCRIPTS / "run_dispatcher.py"),
                        "--seconds", str(args.seconds + 20)]))
    time.sleep(1)
    for _ in range(args.workers):
        procs.append(spawn([str(SCRIPTS / "run_spider.py"),
                            "--run-seconds", str(args.seconds),
                            "--video-pages", str(args.video_pages),
                            "--comment-pages", str(args.comment_pages)]))
    print("[run_workers] 启动 %d 个进程（1 dispatcher + %d spider），跑 %ds"
          % (len(procs), args.workers, args.seconds))
    for p in procs:
        p.wait()
    print("[run_workers] 全部退出")


if __name__ == "__main__":
    main()
