#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书 unidbg 离线签名 · 演示脚本

前提：
  1. xhs-sign-server 已启动（默认 http://127.0.0.1:8098）
  2. 有一份真实的 xy-common-params（含 sid/id_token），用 --common 或 --common-file 传入

用法：
  python xhs_unidbg_demo.py doctor
  python xhs_unidbg_demo.py sign    --url "https://rec.xiaohongshu.com/api/sns/v6/homefeed?oid=homefeed_recommend" --common-file cp.txt
  python xhs_unidbg_demo.py fetch   --url "..." --common-file cp.txt
  python xhs_unidbg_demo.py stress  --n 20 --common-file cp.txt

说明：
  · shield 由本地 unidbg 仿真 libxyass.so 生成，不依赖手机
  · xy-common-params 里的会话信息需要从真机抓一次（Sekiro 模块的 common action）
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "http://127.0.0.1:8098"
HOME = "https://rec.xiaohongshu.com/api/sns/v6/homefeed?oid=homefeed_recommend"


def http_get(url, timeout=300):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def load_common(args):
    if args.common:
        return args.common
    if args.common_file:
        return open(args.common_file, encoding="utf-8").read().strip()
    return None


def cmd_doctor(args):
    ok = True
    print("== 自检 ==")
    try:
        p = http_get(BASE + "/xhs/ping", timeout=30)
        dev = p.get("device") or {}
        print("  [1] 服务         ✅ %s" % BASE)
        print("      deviceId     %s" % dev.get("deviceId"))
        print("      hmac 长度     %s" % dev.get("hmacLen"))
        print("      版本          %s / %s" % (dev.get("versionName"), dev.get("buildId")))
    except Exception as e:
        ok = False
        print("  [1] 服务         ❌ %s" % e)
        return 1

    cp = load_common(args)
    if cp:
        print("  [2] common       ✅ %d 字符" % len(cp))
    else:
        ok = False
        print("  [2] common       ⚠ 未提供（匿名接口可试，登录态接口会 -100）")

    try:
        r = http_get(BASE + "/xhs/shield?" + urllib.parse.urlencode({"url": HOME}))
        if r.get("ok"):
            print("  [3] 签名         ✅ len=%s cost=%sms" % (r.get("len"), r.get("costMs")))
            print("      %s..." % r["shield"][:70])
        else:
            ok = False
            print("  [3] 签名         ❌ %s" % r.get("error"))
    except Exception as e:
        ok = False
        print("  [3] 签名         ❌ %s" % e)

    print("== %s ==" % ("就绪" if ok else "有问题，见上"))
    return 0 if ok else 1


def do_fetch(url, cp, method="GET", body=None):
    q = {"url": url, "method": method}
    if cp:
        q["common"] = cp
    if body:
        q["body"] = body
    r = http_get(BASE + "/xhs/request?" + urllib.parse.urlencode(q))
    return r


def cmd_sign(args):
    cp = load_common(args)
    q = {"url": args.url}
    if cp:
        q["common"] = cp
    r = http_get(BASE + "/xhs/headers?" + urllib.parse.urlencode(q))
    if not r.get("ok"):
        print("失败:", r.get("error"))
        return 1
    h = r["headers"]
    print("签名头 %d 个（耗时 %sms）:" % (len(h), r.get("costMs")))
    for k in sorted(h):
        v = str(h[k])
        print("  %-22s %s" % (k, v if len(v) <= 100 else v[:100] + "..."))
    return 0


def cmd_fetch(args):
    cp = load_common(args)
    r = do_fetch(args.url, cp, args.method, args.body)
    body = r.get("body") or ""
    print("HTTP %s  耗时 %sms  响应 %d 字节" % (r.get("httpCode"), r.get("costMs"), len(body)))
    try:
        j = json.loads(body)
        print("  code=%s success=%s msg=%s" % (j.get("code"), j.get("success"), j.get("msg")))
        d = j.get("data")
        if isinstance(d, list):
            print("  数据 %d 条:" % len(d))
            for it in d[:5]:
                print("    - %s  %s  赞%s" % (it.get("id"),
                                              (it.get("title") or "")[:26], it.get("likes")))
        elif isinstance(d, dict):
            print("  data keys:", list(d)[:12])
    except Exception:
        print("  " + body[:400])
    return 0


def cmd_stress(args):
    cp = load_common(args)
    ok = 0
    t0 = time.time()
    times = []
    for i in range(args.n):
        a = time.time()
        try:
            r = do_fetch(args.url, cp)
            body = r.get("body") or ""
            j = json.loads(body) if body.startswith("{") else {}
            if r.get("httpCode") == 200 and j.get("code") == 0:
                ok += 1
        except Exception:
            pass
        times.append(time.time() - a)
        if (i + 1) % 5 == 0:
            print("  %d/%d ..." % (i + 1, args.n))
    total = time.time() - t0
    print("成功 %d/%d   总耗时 %.1fs   平均 %.2fs   最快 %.2fs"
          % (ok, args.n, total, total / args.n, min(times)))
    return 0 if ok == args.n else 1


def main():
    global BASE
    ap = argparse.ArgumentParser(description="小红书 unidbg 离线签名演示")
    ap.add_argument("--base", default=BASE, help="签名服务地址")
    ap.add_argument("--common", default=None, help="xy-common-params 字符串")
    ap.add_argument("--common-file", dest="common_file", default=None, help="从文件读 common")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("doctor")

    for name in ("sign", "fetch"):
        p = sub.add_parser(name)
        if name == "fetch":
            p.add_argument("--url", required=True)
            p.add_argument("--method", default="GET")
            p.add_argument("--body", default=None)
        else:
            p.add_argument("--url", default=HOME)

    p = sub.add_parser("stress")
    p.add_argument("--url", default=HOME)
    p.add_argument("--n", type=int, default=20)

    args = ap.parse_args()
    BASE = args.base
    if not args.cmd:
        ap.print_help()
        return 1
    return {"doctor": cmd_doctor, "sign": cmd_sign,
            "fetch": cmd_fetch, "stress": cmd_stress}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
