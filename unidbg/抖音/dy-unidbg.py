#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抖音 unidbg 签名 + 数据抓取

对应常驻服务 DouyinSign.jar（同目录），脚本会自动拉起。

用法:
    python dy-unidbg.py serve                     # 只启动服务（前台）
    python dy-unidbg.py health                    # 查看服务状态
    python dy-unidbg.py sign <url>                # 对任意 URL 生成六神签名
    python dy-unidbg.py comments <aweme_id> [-p 3] [-o out.json]
    python dy-unidbg.py register                  # 自主注册一个新设备
    python dy-unidbg.py bench [-n 10]             # 签名吞吐测试

环境变量:
    DY_SERVICE  服务地址（默认 http://127.0.0.1:8099）
    DY_JAVA     java 可执行文件（默认 java）
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
JAR = os.path.join(HERE, "DouyinSign.jar")
BASE = os.environ.get("DY_SERVICE", "http://127.0.0.1:8099").rstrip("/")
JAVA = os.environ.get("DY_JAVA", "java")


# ── 服务管理 ────────────────────────────────────────────────
def _get(path, params=None, timeout=180):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "dy-unidbg/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def health():
    return _get("/api/health", timeout=10)


def ensure_service(wait=120):
    """服务没起来就自动拉起，返回是否可用"""
    try:
        health()
        return True
    except Exception:
        pass
    if not os.path.exists(JAR):
        print("找不到 %s" % JAR, file=sys.stderr)
        return False
    print("[*] 启动签名服务 ...", flush=True)
    # 必须在本目录启动，so/ 用相对路径
    subprocess.Popen([JAVA, "-jar", JAR], cwd=HERE,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0 = time.time()
    while time.time() - t0 < wait:
        time.sleep(2)
        try:
            h = health()
            print("[*] 服务就绪（%d 秒，实例 %d 个）" % (time.time() - t0, h["instances"]))
            return True
        except Exception:
            continue
    print("[!] 服务启动超时", file=sys.stderr)
    return False


# ── 业务接口 ────────────────────────────────────────────────
def sign(url, op2=0):
    j = _get("/api/sign", {"url": url, "op2": op2})
    if not j.get("ok"):
        raise RuntimeError(j.get("error", "签名失败"))
    return j["headers"]


def comments(aweme_id, pages=1, count=20):
    j = _get("/api/comments", {"aweme_id": aweme_id, "pages": pages, "count": count})
    if not j.get("ok"):
        raise RuntimeError(j.get("error", "采集失败"))
    return j["data"]


def register(verify=False):
    return _get("/api/register", {"verify": "true" if verify else "false"}, timeout=300)


# ── CLI ────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="抖音 unidbg 签名与采集")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("serve", help="前台启动服务")
    sub.add_parser("health", help="服务状态")

    p_sign = sub.add_parser("sign", help="对 URL 签名")
    p_sign.add_argument("url")
    p_sign.add_argument("--op2", type=int, default=0)

    p_c = sub.add_parser("comments", help="采集评论")
    p_c.add_argument("aweme_id")
    p_c.add_argument("-p", "--pages", type=int, default=1)
    p_c.add_argument("-n", "--count", type=int, default=20)
    p_c.add_argument("-o", "--out")

    p_r = sub.add_parser("register", help="注册新设备")
    p_r.add_argument("-n", "--count", type=int, default=1, help="注册数量")
    p_r.add_argument("--verify", action="store_true", help="注册后用该设备实拉一页评论验证（慢，约 10 秒/台）")

    p_b = sub.add_parser("bench", help="签名吞吐测试")
    p_b.add_argument("-n", type=int, default=10)

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return 1

    if args.cmd == "serve":
        if not os.path.exists(JAR):
            print("找不到 %s" % JAR)
            return 1
        os.chdir(HERE)
        return subprocess.call([JAVA, "-jar", JAR])

    if args.cmd == "health":
        try:
            print(json.dumps(health(), ensure_ascii=False, indent=2))
        except Exception as e:
            print("服务未运行:", e)
            return 1
        return 0

    if not ensure_service():
        return 1

    if args.cmd == "sign":
        h = sign(args.url, args.op2)
        print(json.dumps(h, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "comments":
        data = comments(args.aweme_id, args.pages, args.count)
        total = 0
        for p in data["pages"]:
            try:
                j = json.loads(p["raw"])
            except Exception:
                continue
            cs = j.get("comments") or []
            total += len(cs)
            print("[cursor=%-4d] status=%s 本页=%d has_more=%s"
                  % (p["cursor"], j.get("status_code"), len(cs), j.get("has_more")))
        print("共 %d 条评论" % total)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print("已写入", args.out)
        return 0

    if args.cmd == "register":
        rows = []
        for i in range(args.count):
            try:
                j = register(args.verify)
            except Exception as e:
                print("  #%-2d 失败: %s" % (i + 1, e))
                continue
            if not j.get("ok"):
                print("  #%-2d 失败: %s" % (i + 1, j.get("response")))
                continue
            d = j["device"]
            v = j.get("verify") or {}
            tag = ""
            if args.verify:
                tag = "  验证=%s" % ("OK" if v.get("ok") else "FAIL")
            print("  #%-2d %-16s %-10s %-9s Android%-3s %-11s@%-4s dpi %s%s"
                  % (i + 1, d["device_id"], d["brand"], d["model"], d["os_version"],
                     d["resolution"], d["dpi"], d["channel"], tag))
            rows.append(d)
        print("\n共注册 %d 台，已写入 devices.jsonl" % len(rows))
        return 0

    if args.cmd == "bench":
        url = ("https://aweme.snssdk.com/aweme/v2/comment/list/"
               "?aweme_id=7706919082587489017&cursor=0&count=20&aid=1128"
               "&device_platform=android")
        times, ok = [], 0
        for i in range(args.n):
            t0 = time.time()
            try:
                h = sign(url)
                dt = (time.time() - t0) * 1000
                times.append(dt)
                ok += 1
                print("  #%-2d %6.0f ms  %s" % (i + 1, dt, h.get("X-Gorgon", "")[:24]))
            except Exception as e:
                print("  #%-2d FAIL %s" % (i + 1, e))
        if times:
            print("成功 %d/%d，平均 %.0f ms" % (ok, args.n, sum(times) / len(times)))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
