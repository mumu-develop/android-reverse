#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""容量压测：模拟 N 个 worker 跑「详情 + 全量作品列表」，输出 QPS 与日均容量。

不依赖数据库，直接打签名服务 + 抖音接口，所以任何工程都能拿来对标。

用法：
    python bench_workers.py --sec-uids uids.txt --workers 2 3 4 --seconds 90

    # uids.txt 一行一个 sec_user_id（MS4wLjABAAAA...）
    # 也可以 --sec-uid 单个，或 --from-comments <aweme_id> 现场采一批

输出示例：
    workers  QPS   用户/天     视频/天
    2        6.61  203512      3355584
    3        9.28  289782      4699514

说明：
    · 详情用真实 iid（每台设备自己的）
    · 作品列表用匿名 iid=0（见 references/api-matrix.md）
    · QPS 上限 = pool-size ÷ (per-device-interval-ms/1000)
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
import urllib.parse
import urllib.request

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")

SERVICE = os.environ.get("DY_SIGN_SERVICE", "http://127.0.0.1:8099")
HOST = "https://aweme.snssdk.com"
UA = "com.ss.android.ugc.aweme/400200 (Linux; U; Android 13; zh_CN; Pixel 6)"

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

_stats_lock = threading.Lock()
STATS = {"users": 0, "videos": 0, "requests": 0, "errors": 0}


def get_json(url: str, timeout: int = 30):
    with _opener.open(url, timeout=timeout) as r:
        body = r.read()
    return json.loads(body) if body else {}


def load_devices():
    devs = get_json(SERVICE + "/api/devices").get("devices") or []
    if not devs:
        raise SystemExit("签名服务没有可用设备（GET /api/devices 为空）")
    return devs


def common(dev, iid):
    p = {
        "aid": "1128", "app_name": "aweme", "version_code": "400200",
        "version_name": "40.2.0", "manifest_version_code": "400201",
        "update_version_code": "40209900", "device_platform": "android",
        "device_type": dev.get("model") or "Pixel 6",
        "device_brand": dev.get("brand") or "google",
        "os": "android", "os_api": str(dev.get("os_api") or 33),
        "os_version": str(dev.get("os_version") or "13"),
        "channel": dev.get("channel") or "huawei_1128_64",
        "device_id": str(dev.get("device_id") or ""), "iid": iid,
        "cdid": str(dev.get("cdid") or ""),
        "resolution": dev.get("resolution") or "1080*2209",
        "dpi": str(dev.get("dpi") or 420), "host_abi": "arm64-v8a",
        "cpu_support64": "true", "language": "zh", "ac": "wifi",
    }
    ts = int(time.time() * 1000)
    p["_rticket"] = str(ts)
    p["ts"] = str(ts // 1000)
    return p


def call(path, params, dev):
    url = HOST + path + "?" + urllib.parse.urlencode(params)
    try:
        q = urllib.parse.urlencode({"url": url, "device": dev.get("device_id")})
        sign = get_json(SERVICE + "/api/sign?" + q, timeout=120)
        if not sign.get("ok"):
            raise RuntimeError(sign.get("error"))
        headers = dict(sign["headers"])
        headers["User-Agent"] = UA
        with _opener.open(urllib.request.Request(url, headers=headers), timeout=30) as r:
            body = r.read()
        with _stats_lock:
            STATS["requests"] += 1
        return json.loads(body) if body else {}
    except Exception:
        with _stats_lock:
            STATS["errors"] += 1
        return {}


def worker(users: "queue.Queue", stop_at: float, devices):
    while time.time() < stop_at:
        try:
            sec = users.get_nowait()
        except queue.Empty:
            return
        dev = devices[0]
        # 详情（真实 iid）
        p = common(dev, dev.get("install_id") or "")
        p.update({"sec_user_id": sec, "from": "0", "enter_from": "others_homepage"})
        prof = call("/aweme/v1/user/profile/other/", p, dev)
        if prof.get("user"):
            with _stats_lock:
                STATS["users"] += 1
        # 作品列表（匿名 iid=0）
        cursor, pages = 0, 0
        while time.time() < stop_at and pages < 200:
            p = common(dev, "0")
            p.update({"sec_user_id": sec, "max_cursor": cursor, "count": 20,
                      "is_other": "1", "source": "0", "page_from": "2",
                      "publish_video_strategy_type": "2"})
            j = call("/aweme/v1/aweme/post/", p, dev)
            lst = j.get("aweme_list") or []
            with _stats_lock:
                STATS["videos"] += len(lst)
            pages += 1
            if not lst or not j.get("has_more"):
                break
            cursor = j.get("max_cursor") or 0


def run_round(users_list, workers, seconds, devices, warmup_reqs=10):
    for k in STATS:
        STATS[k] = 0
    q = queue.Queue()
    for u in users_list:
        q.put(u)
    stop_at = time.time() + seconds

    # 预热签名（避免首轮把冷启动算进吞吐）
    for i in range(min(warmup_reqs, len(users_list))):
        call("/aweme/v1/user/profile/other/",
             dict(common(devices[i % len(devices)], devices[i % len(devices)].get("install_id") or ""),
                  sec_user_id=users_list[i], **{"from": "0"}), devices[i % len(devices)])
    for k in STATS:
        STATS[k] = 0

    t0 = time.time()
    threads = [threading.Thread(target=worker, args=(q, stop_at, devices), daemon=True)
               for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = max(1e-6, time.time() - t0)
    return {
        "workers": workers,
        "wall": wall,
        "users": STATS["users"],
        "videos": STATS["videos"],
        "requests": STATS["requests"],
        "errors": STATS["errors"],
        "qps": STATS["requests"] / wall,
        "users_per_day": STATS["users"] / wall * 86400,
        "videos_per_day": STATS["videos"] / wall * 86400,
    }


def harvest_uids(aweme_id: str, pages: int = 10) -> list:
    """从评论里捞一批 sec_uid（当没有现成 uid 列表时用）。"""
    seen, out = set(), []
    cursor = 0
    for _ in range(pages):
        p = {"aweme_id": aweme_id, "cursor": str(cursor), "count": "20",
             "aid": "1128", "app_name": "aweme", "device_platform": "android"}
        j = call("/aweme/v2/comment/list/", p, load_devices()[0])
        for c in j.get("comments") or []:
            sec = (c.get("user") or {}).get("sec_uid")
            if sec and sec not in seen:
                seen.add(sec)
                out.append(sec)
        if not j.get("has_more"):
            break
        cursor = j.get("cursor") or 0
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--service", default=SERVICE)
    ap.add_argument("--sec-uids", help="一行一个 sec_user_id 的文件")
    ap.add_argument("--sec-uid", action="append", default=[])
    ap.add_argument("--from-comments", help="现场从该视频评论里采一批用户")
    ap.add_argument("--workers", type=int, nargs="+", default=[2, 3, 4])
    ap.add_argument("--seconds", type=int, default=90)
    args = ap.parse_args()

    globals()["SERVICE"] = args.service.rstrip("/")

    users = list(args.sec_uid)
    if args.sec_uids:
        with open(args.sec_uids, encoding="utf-8") as f:
            users += [l.strip() for l in f if l.strip()]
    if args.from_comments:
        users += harvest_uids(args.from_comments)
    if not users:
        raise SystemExit("没有用户可测：用 --sec-uids / --sec-uid / --from-comments")

    devices = load_devices()
    print("设备 %d 台，用户 %d 个，每轮 %ds" % (len(devices), len(users), args.seconds))
    rows = []
    for w in args.workers:
        r = run_round(users, w, args.seconds, devices)
        rows.append(r)
        print("workers=%d  QPS=%.2f  用户=%.0f/天  视频=%.0f/天  请求=%d  错误=%d" % (
            r["workers"], r["qps"], r["users_per_day"], r["videos_per_day"],
            r["requests"], r["errors"]))

    print("\n%-8s %-8s %-12s %-12s" % ("workers", "QPS", "用户/天", "视频/天"))
    for r in rows:
        print("%-8d %-8.2f %-12.0f %-12.0f" % (
            r["workers"], r["qps"], r["users_per_day"], r["videos_per_day"]))


if __name__ == "__main__":
    main()
