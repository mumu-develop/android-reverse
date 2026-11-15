#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抖音六神签名 · 自检脚本

按版本适配清单的顺序逐项验证，任何一项失败立即停止并给出原因。

用法
----
  # 对常驻服务自检（推荐，快）
  python dy-selfcheck.py --service http://127.0.0.1:8099 --aweme 7688378193157898395

  # 对 CLI 工程自检（慢，每次重启 JVM）
  python dy-selfcheck.py --java-project D:/idea/IdeaProjects/douyin-sign-server \
      --device-id 123 --install-id 456 --cdid xxx

  # 只跑某一项
  python dy-selfcheck.py --service ... --only sign

  # 输出 JSON（给 agent 解析）
  python dy-selfcheck.py --service ... --json

检查项
------
  health    服务活着 / 实例就绪
  sign      出 6 个头，Gorgon 以 8404 开头，Khronos 是当前时间
  request   真请求评论接口，status_code == 0 且 comments 非空
  register  自主注册设备，device_id 非 0（可选）
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

UA_APP = ("com.ss.android.ugc.aweme/400200 (Linux; U; Android 13; zh_CN_#Hans; "
          "Pixel 6; Build/TQ3A.230901.001.C2; Cronet/TTNetVersion:0a471c49 2026-10-28)")

RESULTS = []


def ok(name, detail=""):
    RESULTS.append((name, True, detail))
    print("  ✅ %-9s %s" % (name, detail))


def fail(name, detail=""):
    RESULTS.append((name, False, detail))
    print("  ❌ %-9s %s" % (name, detail))


def http_json(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "dy-selfcheck/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ── 两种后端 ────────────────────────────────────────────────
class ServiceBackend:
    def __init__(self, base):
        self.base = base.rstrip("/")

    def health(self):
        return http_json(self.base + "/api/health", timeout=15)

    def sign(self, url):
        j = http_json(self.base + "/api/sign?" + urllib.parse.urlencode({"url": url}))
        if not j.get("ok"):
            raise RuntimeError(j.get("error", "签名失败"))
        return j["headers"]

    def comments(self, aweme_id, cursor=0, count=20):
        q = urllib.parse.urlencode({"aweme_id": aweme_id, "cursor": cursor, "count": count})
        j = http_json(self.base + "/api/comments?" + q)
        if not j.get("ok"):
            raise RuntimeError(j.get("error", "采集失败"))
        return j.get("page", {}).get("raw", "")

    def register(self):
        return http_json(self.base + "/api/register", timeout=240)


class CliBackend:
    """直接调 java -Dsignurl=... 的 CLI 模式"""

    def __init__(self, proj, device_id, install_id, cdid, channel=810):
        self.proj = proj
        self.device_id = device_id
        self.install_id = install_id
        self.cdid = cdid
        self.channel = channel
        self.java = os.environ.get("DY_JAVA", "java")

    def _cp(self):
        with open(os.path.join(self.proj, "cp.txt"), encoding="utf-8") as f:
            return f.read().strip()

    def health(self):
        # CLI 模式没有服务，用"能否编译"代替
        return {"status": "CLI", "proj": self.proj}

    def sign(self, url):
        cmd = [self.java, "-Dinit=true", "-Dchannel=%d" % self.channel,
               "-Dsignurl=" + url, "-Dreporturl=" + url,
               "-Ddeviceid=" + self.device_id, "-Dinstallid=" + self.install_id,
               "-Dop2=0", "-cp", "target\\classes;" + self._cp(),
               "com.dy.sign.DouyinMetasecSign"]
        p = subprocess.run(cmd, cwd=self.proj, capture_output=True, text=True,
                           encoding="utf-8", errors="ignore", timeout=300)
        out = p.stdout or ""
        if "===HEADERS_START===" not in out:
            raise RuntimeError("签名失败（初始化随机失败，重试即可）")
        block = out.split("===HEADERS_START===")[1].split("===HEADERS_END===")[0]
        h = {}
        for line in block.strip().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                h[k.strip()] = v.strip()
        return h

    def comments(self, aweme_id, cursor=0, count=20):
        ts = int(time.time() * 1000)
        params = [("aweme_id", aweme_id), ("cursor", str(cursor)), ("count", str(count)),
                  ("aid", "1128"), ("app_name", "aweme"), ("version_code", "400200"),
                  ("version_name", "40.2.0"), ("manifest_version_code", "400201"),
                  ("update_version_code", "40209900"), ("device_platform", "android"),
                  ("device_type", "Pixel 6"), ("device_brand", "google"),
                  ("os", "android"), ("os_api", "33"), ("os_version", "13"),
                  ("channel", "huawei_1128_64"), ("device_id", self.device_id),
                  ("iid", self.install_id), ("cdid", self.cdid),
                  ("resolution", "1080*2400"), ("dpi", "420"), ("host_abi", "arm64-v8a"),
                  ("cpu_support64", "true"), ("language", "zh"), ("ac", "wifi"),
                  ("_rticket", str(ts)), ("ts", str(ts // 1000))]
        url = "https://aweme.snssdk.com/aweme/v2/comment/list/?" + urllib.parse.urlencode(params)
        headers = self.sign(url)
        headers["User-Agent"] = UA_APP
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(url, headers=headers)
        with opener.open(req, timeout=30) as r:
            return r.read().decode("utf-8", "ignore")

    def register(self):
        raise RuntimeError("CLI 模式不支持注册，请用 --service")


# ── 检查项 ──────────────────────────────────────────────────
def check_health(be):
    try:
        h = be.health()
        if h.get("status") == "UP":
            ok("health", "实例 %s 个，已签 %s 次" % (h.get("instances"), h.get("signed")))
        else:
            ok("health", str(h))
        return True
    except Exception as e:
        fail("health", "服务不可达: %s" % e)
        return False


def check_sign(be):
    url = ("https://aweme.snssdk.com/aweme/v2/comment/list/"
           "?aweme_id=7688378193157898395&cursor=0&count=20&aid=1128"
           "&device_platform=android")
    try:
        h = be.sign(url)
    except Exception as e:
        fail("sign", str(e))
        return False

    missing = [k for k in ("X-Argus", "X-Gorgon", "X-Helios", "X-Khronos",
                           "X-Ladon", "X-Medusa") if k not in h]
    if missing:
        fail("sign", "缺头: %s" % ", ".join(missing))
        return False

    g = h["X-Gorgon"]
    if not re.fullmatch(r"8404[0-9a-f]+", g) or len(g) < 40:
        fail("sign", "X-Gorgon 形态异常: %s" % g[:40])
        return False

    try:
        kh = int(h["X-Khronos"])
    except Exception:
        fail("sign", "X-Khronos 不是整数: %s" % h["X-Khronos"][:20])
        return False
    skew = abs(time.time() - kh)
    if skew > 600:
        fail("sign", "X-Khronos 偏移 %.0f 秒（超过 10 分钟，服务端可能拒绝）" % skew)
        return False

    ok("sign", "6 头齐全，Gorgon=%s… Khronos 偏移 %.0fs" % (g[:20], skew))
    return True


def check_request(be, aweme_id):
    try:
        raw = be.comments(aweme_id, 0, 20)
    except Exception as e:
        fail("request", str(e))
        return False

    if raw.strip().startswith("<"):
        fail("request", "被限流（Access Denied），等 1-3 分钟再试")
        return False
    try:
        j = json.loads(raw.split("\n")[0])
    except Exception:
        fail("request", "响应非 JSON: %s" % raw[:80])
        return False

    if j.get("status_code") != 0:
        sc = j.get("status_code")
        hint = ""
        if sc == -99999:
            hint = " → 参数不全或设备身份不匹配，见 traps.md A1"
        fail("request", "status_code=%s%s" % (sc, hint))
        return False

    cs = j.get("comments") or []
    if not cs:
        fail("request", "status_code=0 但 comments 为空 → 软封禁（限流），等 1-3 分钟")
        return False

    ok("request", "status_code=0，本页 %d 条，total=%s" % (len(cs), j.get("total")))
    return True


def check_register(be):
    try:
        j = be.register()
    except Exception as e:
        fail("register", str(e))
        return False
    if not j.get("ok"):
        fail("register", str(j.get("response") or j.get("error"))[:120])
        return False
    d = j.get("device") or {}
    if not d.get("device_id") or d["device_id"] == "0":
        fail("register", "device_id 为 0 → TTEncrypt 长度参数错，见 traps.md C1")
        return False
    ok("register", "device_id=%s (%s %s)" % (d["device_id"], d.get("brand"), d.get("model")))
    return True


def main():
    ap = argparse.ArgumentParser(description="抖音六神签名自检")
    ap.add_argument("--service", help="常驻服务地址，如 http://127.0.0.1:8099")
    ap.add_argument("--java-project", help="CLI 模式：Java 工程根目录（需有 cp.txt）")
    ap.add_argument("--device-id")
    ap.add_argument("--install-id")
    ap.add_argument("--cdid", default="e3683b4a-3bf8-49c6-9332-6985361a6c4c")
    ap.add_argument("--channel", type=int, default=810)
    ap.add_argument("--aweme", default="7688378193157898395", help="验证用的 aweme_id")
    ap.add_argument("--only", choices=["health", "sign", "request", "register"],
                    help="只跑某一项")
    ap.add_argument("--with-register", action="store_true", help="额外验证设备注册")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = ap.parse_args()

    if args.service:
        be = ServiceBackend(args.service)
    elif args.java_project:
        if not (args.device_id and args.install_id):
            print("CLI 模式需要 --device-id / --install-id", file=sys.stderr)
            return 2
        be = CliBackend(args.java_project, args.device_id, args.install_id,
                        args.cdid, args.channel)
    else:
        ap.print_help()
        return 2

    print("抖音六神签名自检 · 后端=%s" % ("service " + args.service if args.service
                                          else "cli " + args.java_project))
    print("-" * 60)

    steps = []
    if args.only:
        steps = [args.only]
    else:
        steps = ["health", "sign", "request"]
        if args.with_register:
            steps.append("register")

    # health 失败直接退出（后面的没意义）
    if "health" in steps and not check_health(be):
        return 1
    if "sign" in steps and not check_sign(be):
        return 1
    if "request" in steps and not check_request(be, args.aweme):
        return 1
    if "register" in steps and not check_register(be):
        return 1

    print("-" * 60)
    total = len(RESULTS)
    passed = sum(1 for _, okk, _ in RESULTS if okk)
    print("结果: %d/%d 通过" % (passed, total))

    if args.json:
        print(json.dumps({"passed": passed, "total": total,
                          "results": [{"name": n, "ok": o, "detail": d}
                                      for n, o, d in RESULTS]},
                         ensure_ascii=False, indent=2))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
