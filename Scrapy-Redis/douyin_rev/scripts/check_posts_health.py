# -*- coding: utf-8 -*-
"""作品列表通道健康检查（可挂定时任务/告警）。

用法：
    python scripts/check_posts_health.py            # 检查一次
    python scripts/check_posts_health.py --loop 300 # 每 5 分钟检查一次

判据：
    · 用当前「受信任 iid」请求一个已知有作品的用户
    · 返回 aweme_list 非空 → 健康
    · 返回空 body / 空列表 → 不健康（老设备可能被风控）

退出码：0 健康 / 1 不健康（方便接监控）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from douyin_rev.signer.strategy import UnidbgStrategy   # noqa: E402


def check() -> dict:
    st = UnidbgStrategy()
    info = st.warm()
    dev = st.posts_device()
    try:
        url = __import__("douyin_rev.query", fromlist=["posts_url"]).posts_url(
            dev, st.PROBE_SEC, cursor=0, count=1)
        body = st._fetch(url, dev.get("device_id"))
        ok = False
        if body:
            data = json.loads(body.decode("utf-8", "ignore"))
            ok = data.get("status_code") == 0 and bool(data.get("aweme_list"))
        return {
            "ok": ok,
            "degraded": st.posts_degraded,
            "active_iid": (st.active_install or {}).get("install_id", "")[-6:],
            "candidates": len(st.install_candidates),
            "detail": info,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        return {"ok": False, "error": repr(e), "ts": time.strftime("%Y-%m-%d %H:%M:%S")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=0, help="每 N 秒检查一次")
    args = ap.parse_args()

    while True:
        r = check()
        flag = "OK " if r.get("ok") else "BAD"
        print("[%s] %s iid=%s 候选=%d 降级=%s %s" % (
            flag, r.get("ts"), r.get("active_iid"), r.get("candidates", 0),
            r.get("degraded"), r.get("error", "")))
        if not args.loop:
            sys.exit(0 if r.get("ok") else 1)
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
