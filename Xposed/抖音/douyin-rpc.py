#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抖音评论 RPC 客户端（Sekiro 版）

架构：
  PC python ──HTTP──▶ Sekiro 服务端(127.0.0.1:5612) ──WebSocket──▶ 抖音进程
                                                          （Xposed 模块内 SekiroClient）
                                                                    │
                                                                    ▼
                                                        抖音自己的 CommentListApi（自动签名）

前提（4 个，缺一不可）：
  1. PC 上 Sekiro 服务端已启动（启动Sekiro服务端.bat，端口 5612）
  2. 手机 LSPosed 里模块已启用，作用域含抖音
  3. adb reverse tcp:5612 tcp:5612
  4. 抖音进程在运行

先跑自检：
  python douyin-rpc.py doctor

用法：
  python douyin-rpc.py resolve "5.17 复制打开抖音... https://v.douyin.com/xxx/"
  python douyin-rpc.py ping
  python douyin-rpc.py comments <aweme_id 或分享文案> --pages 3
  python douyin-rpc.py dump <aweme_id 或分享文案> --pages 5 -o out.json
"""
import argparse
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

# Windows 控制台默认 GBK，强制 UTF-8，避免中文乱码
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SEKIRO = "http://127.0.0.1:5612"
GROUP = "douyin"
ADB = "adb"

MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
             "Mobile/15E148 Safari/604.1")

# 短链（分享文案里那种）
SHORT_LINK_RE = re.compile(r"https?://v\.douyin\.com/[A-Za-z0-9_\-]+/?")
# 任意 douyin 链接
ANY_LINK_RE = re.compile(r"https?://[^\s\"'<>]+")
# 各种形态里的 aweme_id
ID_RES = [
    re.compile(r"/video/(\d{15,20})"),
    re.compile(r"modal_id=(\d{15,20})"),
    re.compile(r"aweme_id=(\d{15,20})"),
    re.compile(r"/share/video/(\d{15,20})"),
]


def _http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": MOBILE_UA,
        "Accept": "text/html,application/xhtml+xml,*/*",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.geturl(), r.read().decode("utf-8", "ignore")


def _extract_id(text):
    for r in ID_RES:
        m = r.search(text)
        if m:
            return m.group(1)
    return None


def resolve_aweme_id(text):
    """把分享文案 / 短链 / 视频链接 / 纯数字，统一解析成 aweme_id"""
    text = (text or "").strip()
    if not text:
        raise ValueError("输入为空")
    if text.isdigit() and 15 <= len(text) <= 20:
        return text

    m = SHORT_LINK_RE.search(text)
    url = m.group(0) if m else None
    if not url:
        m2 = ANY_LINK_RE.search(text)
        if m2:
            url = m2.group(0)

    if url:
        try:
            final, html = _http_get(url)
        except Exception as e:
            raise RuntimeError("访问链接失败: %s (%s)" % (url, e))
        hit = _extract_id(final) or _extract_id(html)
        if hit:
            return hit
        raise RuntimeError("链接里没找到 aweme_id: %s" % final)

    hit = _extract_id(text)
    if hit:
        return hit
    raise RuntimeError("无法从输入里解析 aweme_id")


def invoke(action, timeout=120, **params):
    """调用 Sekiro 上的 action，返回 data（已二次解析）"""
    q = {"group": GROUP, "action": action}
    for k, v in params.items():
        if v is not None:
            q[k] = v
    url = "%s/business/invoke?%s" % (SEKIRO, urllib.parse.urlencode(q))
    with urllib.request.urlopen(url, timeout=timeout) as r:
        outer = json.loads(r.read().decode("utf-8"))

    status = outer.get("status")
    if status != 0:
        raise RuntimeError("Sekiro 错误 status=%s message=%s" % (status, outer.get("message")))

    data = outer.get("data")
    if isinstance(data, str):
        try:
            return json.loads(data)
        except Exception:
            return data
    return data


def ping():
    return invoke("ping", timeout=10)


def fetch_page(aweme_id, cursor=0, count=20):
    return invoke("comment", aweme_id=aweme_id, cursor=cursor, count=count)


def fetch_pages(aweme_id, pages=1, count=20, delay=0.6, verbose=True):
    out = []
    cursor = 0
    meta = {"total": None, "pages": 0, "has_more": True}
    for i in range(pages):
        j = fetch_page(aweme_id, cursor, count)
        if not isinstance(j, dict):
            raise RuntimeError("返回不是 JSON: %r" % (j,))
        cmts = j.get("comments") or []
        out.extend(cmts)
        meta["pages"] = i + 1
        meta["total"] = j.get("total", meta["total"])
        meta["has_more"] = bool(j.get("has_more"))
        if verbose:
            print("  第 %d 页: %d 条, cursor=%s, has_more=%s"
                  % (i + 1, len(cmts), j.get("cursor"), meta["has_more"]), file=sys.stderr)
        cursor = j.get("cursor") or (cursor + len(cmts))
        if not meta["has_more"] or not cmts:
            break
        time.sleep(delay)
    return out, meta


def simplify(c):
    user = c.get("user") or {}
    return {
        "cid": c.get("cid"),
        "text": c.get("text"),
        "digg_count": c.get("digg_count"),
        "create_time": c.get("create_time"),
        "reply_comment_total": c.get("reply_comment_total"),
        "nickname": user.get("nickname"),
        "uid": user.get("uid"),
    }


def _sh(args):
    try:
        p = subprocess.run([ADB] + args, capture_output=True, text=True, timeout=15)
        return (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return "执行 adb 失败: %s" % e


def cmd_doctor(_a):
    ok = True
    print("== 环境自检 ==")

    try:
        with urllib.request.urlopen(SEKIRO + "/", timeout=5) as r:
            code = r.status
        print("[1] Sekiro 服务端  OK (HTTP %s)" % code)
    except Exception as e:
        ok = False
        print("[1] Sekiro 服务端  FAIL: %s" % e)
        print("    -> 双击 启动Sekiro服务端.bat（保持窗口不关）")

    rev = _sh(["reverse", "--list"])
    if "5612" in rev:
        print("[2] adb reverse     OK (%s)" % rev.strip())
    else:
        ok = False
        print("[2] adb reverse     FAIL: 没有 5612 映射")
        print("    -> 执行: adb reverse tcp:5612 tcp:5612")

    pid = _sh(["shell", "pidof com.ss.android.ugc.aweme"]).strip()
    if pid:
        print("[3] 抖音进程        OK (pid %s)" % pid.split()[0])
    else:
        ok = False
        print("[3] 抖音进程        FAIL: 没在运行")
        print("    -> 手动打开抖音，等它进入推荐页")

    if ok:
        try:
            p = ping()
            print("[4] 模块连接        OK (%s)" % json.dumps(p, ensure_ascii=False))
        except Exception as e:
            ok = False
            print("[4] 模块连接        FAIL: %s" % e)
            print("    -> 检查 LSPosed 里模块已启用、作用域含抖音；再强制停止并重开抖音")

    print()
    print("结论: " + ("全部正常，可以抓数据" if ok else "有环节没打通，按上面提示处理"))
    return 0 if ok else 1


def cmd_resolve(a):
    aweme_id = resolve_aweme_id(a.text)
    print(aweme_id)
    return 0


def cmd_ping(_a):
    print(json.dumps(ping(), ensure_ascii=False))


def cmd_comments(a):
    aweme_id = resolve_aweme_id(a.aweme_id)
    cmts, meta = fetch_pages(aweme_id, pages=a.pages, count=a.count)
    print("aweme_id=%s" % aweme_id)
    print("共 %d 条（总评论数 %s，%d 页）" % (len(cmts), meta["total"], meta["pages"]))
    for c in cmts[: a.show]:
        s = simplify(c)
        print("  [%s] %s  (赞 %s)" % (s["cid"], (s["text"] or "")[:50].replace("\n", " "), s["digg_count"]))
    if len(cmts) > a.show:
        print("  ... 还有 %d 条" % (len(cmts) - a.show))


def cmd_dump(a):
    aweme_id = resolve_aweme_id(a.aweme_id)
    cmts, meta = fetch_pages(aweme_id, pages=a.pages, count=a.count)
    data = {
        "aweme_id": aweme_id,
        "fetched_at": int(time.time()),
        "total": meta["total"],
        "count": len(cmts),
        "comments": [simplify(c) for c in cmts],
        "raw": cmts,
    }
    out = a.output or ("comments_%s.json" % aweme_id)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("已保存 %d 条 -> %s" % (len(cmts), out))


def main():
    ap = argparse.ArgumentParser(description="抖音评论 RPC 客户端（Sekiro）")
    sub = ap.add_subparsers(dest="cmd", required=False)

    pd = sub.add_parser("doctor", help="一键体检")
    pd.set_defaults(func=cmd_doctor)

    pr = sub.add_parser("resolve", help="把分享文案/短链解析成 aweme_id")
    pr.add_argument("text", help="分享文案、短链或视频链接")
    pr.set_defaults(func=cmd_resolve)

    p1 = sub.add_parser("ping")
    p1.set_defaults(func=cmd_ping)

    p2 = sub.add_parser("comments")
    p2.add_argument("aweme_id", help="aweme_id 或分享文案/链接")
    p2.add_argument("--pages", type=int, default=1)
    p2.add_argument("--count", type=int, default=20)
    p2.add_argument("--show", type=int, default=20)
    p2.set_defaults(func=cmd_comments)

    p3 = sub.add_parser("dump")
    p3.add_argument("aweme_id", help="aweme_id 或分享文案/链接")
    p3.add_argument("--pages", type=int, default=1)
    p3.add_argument("--count", type=int, default=20)
    p3.add_argument("-o", "--output")
    p3.set_defaults(func=cmd_dump)

    a = ap.parse_args()

    if not getattr(a, "cmd", None):
        print(__doc__)
        print("常用命令：")
        print("  python douyin-rpc.py doctor")
        print("  python douyin-rpc.py resolve \"<整段分享文案>\"")
        print("  python douyin-rpc.py comments 7702113333822688890 --pages 2")
        print("  python douyin-rpc.py dump \"<分享文案>\" --pages 5 -o out.json")
        return 0

    try:
        return a.func(a) or 0
    except urllib.error.URLError as e:
        print("连不上 Sekiro（%s）\n先跑: python douyin-rpc.py doctor" % e, file=sys.stderr)
        return 2
    except Exception as e:
        print("错误: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
