#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书游客态凭据刷新

App 在未登录状态也能刷内容，靠的是这几个头：
  x-mini-gid / x-mini-s1 / x-mini-sig / x-mini-mua   ← libtiny 生成，设备级，可复用
  xy-common-params                                    ← 含游客 sid / id_token / did

这些值会随时间失效（实测至少十几分钟内可复用），所以定期从 App 抓一份最新的。

流程：
  1. 触发 App 刷新（可选）
  2. 从 logcat 读最近一条 [XHS-HDRS]（Xposed 模块打印的全部请求头）
  3. 写出 guest_mini.json（x-mini-*）和 cp.txt（xy-common-params）
  4. 调用签名服务 /xhs/reload 热加载

用法：
  python xhs_guest_refresh.py --serial <序列号>
  python xhs_guest_refresh.py --serial <序列号> --base http://127.0.0.1:8098
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
MINI_KEYS = ("x-mini-gid", "x-mini-s1", "x-mini-sig", "x-mini-mua", "x-legacy-did", "x-legacy-sid")


def adb(serial, *args, timeout=60):
    cmd = ["adb"] + (["-s", serial] if serial else []) + list(args)
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    return r.stdout.decode("utf-8", "ignore")


def trigger(serial):
    adb(serial, "shell", "input swipe 540 1400 540 600 300")
    time.sleep(3)


def parse_headers(line):
    start = line.find("[XHS-HDRS]")
    if start < 0:
        return {}
    body = line[start + len("[XHS-HDRS]"):]
    out = {}
    for part in body.split("||"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        k, v = part.split(":", 1)
        k, v = k.strip(), v.strip()
        if k:
            out[k.lower()] = v
    return out


def fetch_headers(serial):
    for attempt in range(3):
        log = adb(serial, "logcat", "-d", "-s", "DouyinRpc")
        lines = [l for l in log.splitlines() if "XHS-HDRS" in l]
        if lines:
            h = parse_headers(lines[-1])
            if h.get("xy-common-params") and h.get("x-mini-sig"):
                return h
        trigger(serial)
    return {}


def main():
    ap = argparse.ArgumentParser(description="刷新小红书游客态凭据")
    ap.add_argument("--serial", default=None)
    ap.add_argument("--base", default="http://127.0.0.1:8098")
    ap.add_argument("--mini-out", default=os.path.join(OUT_DIR, "guest_mini.json"))
    ap.add_argument("--cp-out", default=os.path.join(OUT_DIR, "cp.txt"))
    args = ap.parse_args()

    print("== 从 App 抓请求头 ==")
    h = fetch_headers(args.serial)
    if not h:
        print("失败：logcat 里没有 [XHS-HDRS]。确认 Xposed 模块已启用并抓过一次请求。")
        return 1

    cp = h.get("xy-common-params", "")
    mini = {k: v for k, v in h.items() if k in MINI_KEYS and v}

    print("  cp      : %d 字符" % len(cp))
    print("  x-mini  : %d 个 (%s)" % (len(mini), ", ".join(mini)))
    sid = cp.split("sid=")[1].split("&")[0] if "sid=" in cp else ""
    did = cp.split("deviceId=")[1].split("&")[0] if "deviceId=" in cp else ""
    print("  sid     : %s" % sid)
    print("  deviceId: %s" % did)

    with open(args.cp_out, "w", encoding="utf-8") as f:
        f.write(cp)
    with open(args.mini_out, "w", encoding="utf-8") as f:
        json.dump(mini, f, ensure_ascii=False, indent=2)
    print("  已写入 %s / %s" % (os.path.basename(args.cp_out), os.path.basename(args.mini_out)))

    print("== 通知签名服务热加载 ==")
    try:
        with urllib.request.urlopen(args.base + "/xhs/reload", timeout=30) as r:
            d = json.loads(r.read().decode())
        print("  ok=%s 加载 %s 个额外头" % (d.get("ok"), d.get("count")))
    except Exception as e:
        print("  ⚠ 热加载失败（服务未启动？）: %s" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
