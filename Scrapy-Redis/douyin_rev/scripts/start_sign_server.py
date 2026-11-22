# -*- coding: utf-8 -*-
"""启动内置的 unidbg 签名服务（runtime/DouyinSign.jar）。

用法：
    python scripts/start_sign_server.py                 # 前台启动（Ctrl+C 停）
    python scripts/start_sign_server.py --wait          # 启动后等健康检查通过再返回
    python scripts/start_sign_server.py --pool-size 12 --interval-ms 500
    python scripts/start_sign_server.py --port 8100     # 换端口（避免和已有实例冲突）

说明：
    · 必须把工作目录切到 runtime/，因为 application.yml 里的 so 路径是 `so/xxx.so` 相对路径
    · devices.jsonl 也会落在 runtime/ 下（/api/register 追加写入）
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

ROOT = Path(__file__).resolve().parent.parent          # douyin_rev/
RUNTIME = ROOT / "runtime"
JAR = RUNTIME / "DouyinSign.jar"


def find_java() -> str:
    """优先用 JAVA_HOME，其次 PATH。"""
    home = os.environ.get("JAVA_HOME")
    if home:
        exe = Path(home) / "bin" / ("java.exe" if os.name == "nt" else "java")
        if exe.exists():
            return str(exe)
    return "java"


def wait_health(port: int, timeout: int = 180) -> bool:
    url = "http://127.0.0.1:%d/api/health" % port
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with opener.open(url, timeout=3) as r:
                data = json.loads(r.read().decode())
            if data.get("instances"):
                print("[+] 服务就绪：instances=%s idle=%s（%.0fs）" % (
                    data.get("instances"), data.get("idle"), time.time() - t0))
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--pool-size", type=int, default=12)
    ap.add_argument("--interval-ms", type=int, default=500,
                    help="单设备两次签名的最小间隔（吞吐 ≈ pool-size ÷ interval）")
    ap.add_argument("--wait", action="store_true", help="等健康检查通过再返回")
    args = ap.parse_args()

    if not JAR.exists():
        raise SystemExit("缺少 %s —— 请先确认 runtime/ 下有 jar 和 so/" % JAR)
    if not (RUNTIME / "so" / "libmetasec_ml.so").exists():
        raise SystemExit("缺少 runtime/so/libmetasec_ml.so")

    cmd = [
        find_java(), "-jar", JAR.name,
        "--server.port=%d" % args.port,
        "--douyin.sign.pool-size=%d" % args.pool_size,
        "--douyin.sign.per-device-interval-ms=%d" % args.interval_ms,
    ]
    print("[*] 启动签名服务：%s" % " ".join(cmd))
    print("[*] 工作目录：%s" % RUNTIME)

    if args.wait:
        proc = subprocess.Popen(cmd, cwd=str(RUNTIME),
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        ok = wait_health(args.port)
        if not ok:
            proc.terminate()
            raise SystemExit("服务启动超时（%d 秒）" % 180)
        print("[+] 后台运行中，pid=%d，端口=%d" % (proc.pid, args.port))
        return

    subprocess.run(cmd, cwd=str(RUNTIME))


if __name__ == "__main__":
    main()
