#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书 RPC 客户端（Sekiro 版）

架构：
  PC python ──HTTP──▶ Sekiro 服务端(127.0.0.1:5612) ──WebSocket──▶ 小红书进程
                                                        （Xposed 模块内 SekiroClient）
                                                                  │
                                                                  ▼
                                                  小红书自己的 OkHttp 拦截器链（shield / x-mini 自动签）

前提（4 个，缺一不可）：
  1. PC 上 Sekiro 服务端已启动（sekiro-server\\bin\\sekiro.bat，端口 5612）
  2. 手机 LSPosed 里 sekiro-rpc-hook 已启用，作用域含 com.xingin.xhs
  3. adb reverse tcp:5612 tcp:5612
  4. 小红书进程在运行，并且已经发过至少一个网络请求（用于捕获 OkHttpClient）

先跑自检：
  python xhs-rpc.py doctor

用法：
  python xhs-rpc.py ping
  python xhs-rpc.py sign  --url "https://edith.xiaohongshu.com/api/sns/v1/system_service/config?launchtimes=1"
  python xhs-rpc.py request --url "https://edith.xiaohongshu.com/api/sns/v6/homefeed?oid=homefeed_recommend" -o out.json
  python xhs-rpc.py request --method POST --url "https://..." --body '{"a":1}'
"""
import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SEKIRO = "http://127.0.0.1:5612"
GROUP = "xhs"
ADB = "adb"
DEVICE = None          # 可用 --device 指定


def invoke(action, timeout=120, **params):
    """调用手机端 action，返回 data"""
    q = {"group": GROUP, "action": action}
    for k, v in params.items():
        if v is not None:
            q[k] = v
    url = "%s/business/invoke?%s" % (SEKIRO, urllib.parse.urlencode(q))
    with urllib.request.urlopen(url, timeout=timeout) as r:
        outer = json.loads(r.read().decode("utf-8"))

    status = outer.get("status")
    if status != 0:
        raise RuntimeError("Sekiro 错误 status=%s message=%s"
                           % (status, outer.get("message")))

    data = outer.get("data")
    if isinstance(data, str):
        try:
            return json.loads(data)
        except Exception:
            return data
    return data


def adb(*args, timeout=15):
    cmd = [ADB]
    if DEVICE:
        cmd += ["-s", DEVICE]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ---------------- 自检 ----------------

def doctor():
    ok = True
    print("== 小红书 RPC 自检 ==")

    # 1. Sekiro 服务端
    try:
        import socket
        s = socket.create_connection(("127.0.0.1", 5612), timeout=2)
        s.close()
        print("  [1] Sekiro 服务端 127.0.0.1:5612      ✅ 在监听")
    except Exception as e:
        ok = False
        print("  [1] Sekiro 服务端 127.0.0.1:5612      ❌ 没启动 (%s)" % e)
        print("      启动: D:\\PythonProject\\安卓-逆向\\Xposed\\sekiro-server\\bin\\sekiro.bat")

    # 2. adb reverse
    try:
        out = adb("reverse", "--list").stdout.strip()
        if "5612" in out:
            print("  [2] adb reverse 5612                   ✅")
        else:
            ok = False
            print("  [2] adb reverse 5612                   ❌ 缺失")
            print("      执行: adb reverse tcp:5612 tcp:5612")
    except Exception as e:
        ok = False
        print("  [2] adb reverse                        ❌ %s" % e)

    # 3. 小红书进程
    try:
        pid = adb("shell", "pidof com.xingin.xhs").stdout.strip()
        if pid:
            print("  [3] 小红书进程                          ✅ pid=%s" % pid.split()[0])
        else:
            ok = False
            print("  [3] 小红书进程                          ❌ 没在运行")
    except Exception as e:
        ok = False
        print("  [3] 小红书进程                          ❌ %s" % e)

    # 4. 模块 ping
    try:
        r = invoke("ping", timeout=15)
        print("  [4] 模块 ping                           ✅ %s" % json.dumps(r, ensure_ascii=False))
        if isinstance(r, dict) and not r.get("clientCaptured"):
            print("      ⚠ OkHttpClient 还没捕获：在小红书里刷新一次（打开首页即可）")
    except Exception as e:
        ok = False
        print("  [4] 模块 ping                           ❌ %s" % e)
        print("      检查: LSPosed 里模块已启用 + 作用域含小红书 + 已 force-stop 重启 App")

    print("== 结论: %s ==" % ("全部就绪" if ok else "有缺失，见上"))
    return 0 if ok else 1


# ---------------- 命令 ----------------

def cmd_ping(_args):
    print(json.dumps(invoke("ping", timeout=15), ensure_ascii=False, indent=2))


def cmd_sign(args):
    r = invoke("sign",
               method=args.method,
               url=args.url,
               body=args.body,
               content_type=args.content_type)
    headers = (r or {}).get("headers") or {}
    print(json.dumps(headers, ensure_ascii=False, indent=2))
    print("\n--- 关键头 ---")
    for k in sorted(headers):
        lk = k.lower()
        if lk == "shield" or lk.startswith("xy-") or lk.startswith("x-mini") or lk.startswith("x-legacy"):
            v = headers[k]
            print("  %-22s %s" % (k, v if len(v) <= 120 else v[:120] + "..."))


def cmd_request(args):
    r = invoke("request",
               method=args.method,
               url=args.url,
               body=args.body,
               content_type=args.content_type)
    code = (r or {}).get("code")
    body = (r or {}).get("body") or ""
    print("HTTP %s   响应 %d 字节" % (code, len(body)))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(body)
        print("已写入 %s" % args.out)
    else:
        try:
            j = json.loads(body)
            print(json.dumps(j, ensure_ascii=False, indent=2)[:args.max_chars])
        except Exception:
            print(body[:args.max_chars])


def main():
    ap = argparse.ArgumentParser(description="小红书 RPC 客户端")
    ap.add_argument("--device", help="adb 设备序列号")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("doctor", help="环境自检")
    sub.add_parser("ping", help="模块存活检查")

    for name, helptext in (("sign", "只签名，返回最终请求头"),
                           ("request", "代发请求，返回响应")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--url", required=True)
        p.add_argument("--method", default="GET")
        p.add_argument("--body", default=None)
        p.add_argument("--content-type", dest="content_type",
                       default="application/json; charset=utf-8")
        if name == "request":
            p.add_argument("-o", "--out", help="响应写入文件")
            p.add_argument("--max-chars", dest="max_chars", type=int, default=4000)

    args = ap.parse_args()
    global DEVICE
    DEVICE = args.device

    if not args.cmd:
        ap.print_help()
        return 1
    try:
        if args.cmd == "doctor":
            return doctor()
        if args.cmd == "ping":
            cmd_ping(args); return 0
        if args.cmd == "sign":
            cmd_sign(args); return 0
        if args.cmd == "request":
            cmd_request(args); return 0
    except Exception as e:
        print("失败: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
