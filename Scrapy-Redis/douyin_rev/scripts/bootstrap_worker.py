# -*- coding: utf-8 -*-
"""Crawlab 入口：起签名服务 → 补齐设备 → 跑 scrapy。

Crawlab 的任务命令直接写这个脚本即可，例如：

    python scripts/bootstrap_worker.py --pool-size 12 --min-devices 20 \
        --video-pages 999 --comment-pages 0

它做三件事（幂等，可重复执行）：
    1. 探活 8099；没起来就用 runtime/ 里的 jar 拉起（cwd=runtime，so 相对路径）
    2. 调 strategy.ensure_devices()：设备不足 MIN_DEVICES 就 /api/register 补齐
    3. subprocess 跑 `python -m scrapy crawl user -a ...`

退出码跟随 scrapy。
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

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")

RUNTIME = ROOT / "runtime"
JAR = RUNTIME / "DouyinSign.jar"


def health(port: int):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:%d/api/health" % port, timeout=3) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def wait_health(port: int, timeout: int = 180) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if health(port):
            return True
        time.sleep(2)
    return False


def start_service(port: int, pool_size: int, interval_ms: int) -> subprocess.Popen:
    java = os.environ.get("JAVA_HOME")
    exe = str(Path(java) / "bin" / ("java.exe" if os.name == "nt" else "java")) if java else "java"
    cmd = [exe, "-jar", JAR.name,
           "--server.port=%d" % port,
           "--douyin.sign.pool-size=%d" % pool_size,
           "--douyin.sign.per-device-interval-ms=%d" % interval_ms]
    print("[bootstrap] 启动签名服务: %s" % " ".join(cmd), flush=True)
    return subprocess.Popen(cmd, cwd=str(RUNTIME),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--pool-size", type=int, default=12)
    ap.add_argument("--interval-ms", type=int, default=500)
    ap.add_argument("--device-target", type=int, default=12,
                    help="设备目标数（默认= pool-size；已有则只补差额，不动多余设备）")
    ap.add_argument("--video-pages", type=int, default=None)
    ap.add_argument("--comment-pages", type=int, default=None)
    ap.add_argument("--spider", default="user")
    ap.add_argument("--no-scrapy", action="store_true", help="只准备环境，不跑爬虫")
    args = ap.parse_args()

    # 1. 服务
    proc = None
    if health(args.port) is None:
        if not JAR.exists():
            raise SystemExit("签名服务未运行，且缺少 %s" % JAR)
        proc = start_service(args.port, args.pool_size, args.interval_ms)
        if not wait_health(args.port):
            proc.terminate()
            raise SystemExit("签名服务启动超时")
        started_by_us = True
    else:
        started_by_us = False
        h = health(args.port)
        print("[bootstrap] 复用已有服务: instances=%s" % h.get("instances"), flush=True)

    # 2. 设备
    from douyin_rev.signer.strategy import UnidbgStrategy  # noqa: E402
    from douyin_rev.db import init_db                      # noqa: E402

    init_db()
    st = UnidbgStrategy("http://127.0.0.1:%d" % args.port)
    st.warm()
    before = len(st.pool.refresh())
    added = st.ensure_devices(args.device_target)
    after = len(st.pool.refresh())
    print("[bootstrap] 设备：%d → %d（本次注册 %d）" % (before, after, added), flush=True)

    # 服务启动时会按 pool-size 自动补齐设备（新 jar 内置），这里只做兜底校验：
    # 若服务是外部常驻的（不是本脚本拉起），新设备不会增加实例数，但立即可用于请求。
    if added and not started_by_us:
        print("[bootstrap] 提示：服务由外部启动，新增设备不改变实例数；"
              "如需提升签名并行度请重启服务并调 --pool-size", flush=True)

    if args.no_scrapy:
        return 0

    # 3. scrapy
    cmd = [sys.executable, "-m", "scrapy", "crawl", args.spider]
    if args.video_pages is not None:
        cmd += ["-a", "video_pages=%d" % args.video_pages]
    if args.comment_pages is not None:
        cmd += ["-a", "comment_pages=%d" % args.comment_pages]
    print("[bootstrap] 执行: %s" % " ".join(cmd), flush=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    rc = subprocess.call(cmd, cwd=str(ROOT), env=env)
    print("[bootstrap] scrapy 退出码 %d" % rc, flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
