#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""作品列表通道健康检查（可挂定时任务/告警）。

背景：作品列表对「新安装 iid」静默返回 200 + 空 body，不报错。
没有探针的话，通道挂了也看不出来（任务照跑，只是没有视频）。

用法：
    # 检查匿名通道（iid=0，默认路径）
    python check_posts_health.py --sec-uid MS4wLjABAAAA...

    # 同时检查某个真实 iid
    python check_posts_health.py --sec-uid ... --iid 3594782549750826

    # 循环检查（每 5 分钟）
    python check_posts_health.py --sec-uid ... --loop 300

退出码：0 健康 / 1 不健康（方便接监控）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")

SERVICE = os.environ.get("DY_SIGN_SERVICE", "http://127.0.0.1:8099")
HOST = "https://aweme.snssdk.com"
UA = "com.ss.android.ugc.aweme/400200 (Linux; U; Android 13; zh_CN; Pixel 6)"
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get_json(url: str, timeout: int = 30):
    with _opener.open(url, timeout=timeout) as r:
        body = r.read()
    return json.loads(body) if body else {}


def pick_device():
    devs = get_json(SERVICE + "/api/devices").get("devices") or []
    if not devs:
        raise RuntimeError("签名服务无可用设备")
    return devs[0]


def common(dev, iid):
    ts = int(time.time() * 1000)
    return {
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
        "_rticket": str(ts), "ts": str(ts // 1000),
    }


def probe(sec_uid: str, iid: str) -> dict:
    dev = pick_device()
    p = common(dev, iid)
    p.update({"sec_user_id": sec_uid, "max_cursor": 0, "count": 1,
              "is_other": "1", "source": "0", "page_from": "2",
              "publish_video_strategy_type": "2"})
    url = HOST + "/aweme/v1/aweme/post/?" + urllib.parse.urlencode(p)
    try:
        q = urllib.parse.urlencode({"url": url, "device": dev.get("device_id")})
        sign = get_json(SERVICE + "/api/sign?" + q, timeout=120)
        if not sign.get("ok"):
            return {"ok": False, "reason": "签名失败: %s" % sign.get("error")}
        headers = dict(sign["headers"])
        headers["User-Agent"] = UA
        with _opener.open(urllib.request.Request(url, headers=headers), timeout=30) as r:
            body = r.read()
        if not body:
            return {"ok": False, "reason": "空 body（iid 不被信任或被限流）"}
        data = json.loads(body.decode("utf-8", "ignore"))
        n = len(data.get("aweme_list") or [])
        return {"ok": data.get("status_code") == 0 and n > 0,
                "posts": n, "status_code": data.get("status_code")}
    except Exception as e:
        return {"ok": False, "reason": repr(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--service", default=SERVICE)
    ap.add_argument("--sec-uid", required=True, help="一个已知有作品的用户 sec_user_id")
    ap.add_argument("--iid", action="append", default=[],
                    help="额外检查的 iid（可多次）；默认总是检查匿名 iid=0")
    ap.add_argument("--loop", type=int, default=0, help="每 N 秒检查一次")
    args = ap.parse_args()

    globals()["SERVICE"] = args.service.rstrip("/")
    iids = ["0"] + [x for x in args.iid if x]

    while True:
        all_ok = True
        for iid in iids:
            r = probe(args.sec_uid, iid)
            tag = "OK " if r.get("ok") else "BAD"
            all_ok = all_ok and bool(r.get("ok"))
            print("[%s] %s iid=%-16s posts=%s %s" % (
                tag, time.strftime("%H:%M:%S"), iid,
                r.get("posts"), r.get("reason", "")))
        if not args.loop:
            sys.exit(0 if all_ok else 1)
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
