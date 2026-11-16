# -*- coding: utf-8 -*-
"""xhs_probe.py —— 小红书 frida 探针（spawn 后一直盯着，进程一死立刻报）

为什么要这个：frida 命令行 `-q` 模式下 stdin 一 EOF 就退出，
没法"无人值守地看它什么时候死"。这个脚本 spawn 完 resume，
然后每 0.5 秒查一次 pid 是否还在，死了立刻打印存活时长。

用法：
    python xhs_probe.py spawn trap.js
    python xhs_probe.py spawn libs.js trap.js
    python xhs_probe.py <pid> trap.js          # attach 到已运行的进程
    python xhs_probe.py spawn trap.js --sec 60

输出：所有 console.log 原样打印，JS 错误打印堆栈。
"""
import io
import os
import sys
import time

import frida

PKG = "com.xingin.xhs"


def on_message(msg, data):
    t = msg.get("type")
    if t == "log":
        print(msg.get("payload", ""), flush=True)
    elif t == "send":
        print(msg.get("payload"), flush=True)
    elif t == "error":
        print("[js-error] " + msg.get("stack", msg.get("description", "")), flush=True)
    else:
        print("[msg] %r" % (msg,), flush=True)


def alive(dev, pid):
    try:
        for p in dev.enumerate_processes():
            if p.pid == pid:
                return True
        return False
    except Exception:
        return True


def main():
    argv = sys.argv[1:]
    seconds = 45
    if "--sec" in argv:
        i = argv.index("--sec")
        seconds = int(argv[i + 1])
        del argv[i:i + 2]
    if not argv:
        print(__doc__)
        return 2

    mode, scripts = argv[0], argv[1:]
    dev = frida.get_usb_device(timeout=10)

    if mode == "spawn":
        pid = dev.spawn([PKG])
        print("[probe] spawned %s pid=%d" % (PKG, pid), flush=True)
    else:
        pid = int(mode)
        print("[probe] attaching pid=%d" % pid, flush=True)

    session = dev.attach(pid)
    for js in scripts:
        with io.open(js, "r", encoding="utf-8") as f:
            src = f.read()
        s = session.create_script(src, name=os.path.basename(js))
        s.on("message", on_message)
        s.load()
        print("[probe] loaded %s (%d bytes)" % (os.path.basename(js), len(src)), flush=True)

    if mode == "spawn":
        dev.resume(pid)
        print("[probe] resumed, watching for %ds ..." % seconds, flush=True)

    t0 = time.time()
    gone_at = None
    try:
        while time.time() - t0 < seconds:
            time.sleep(0.5)
            if not alive(dev, pid):
                gone_at = time.time() - t0
                print("\n[probe] !!! PROCESS GONE after %.1fs (pid=%d) !!!" % (gone_at, pid),
                      flush=True)
                break
        else:
            print("\n[probe] still alive after %ds" % seconds, flush=True)
    except KeyboardInterrupt:
        print("\n[probe] interrupted", flush=True)
    finally:
        try:
            session.detach()
        except Exception:
            pass
        if gone_at is not None:
            # 顺手把系统侧的崩溃记录捞一下
            print("[probe] 提示: 可执行 adb logcat -d | findstr xingin 看系统侧记录", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
