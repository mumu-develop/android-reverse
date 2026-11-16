#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书设备身份铸造工具（多用户方案）

原理：
  Android 的 ANDROID_ID 是「按 用户+应用签名」隔离的。
  新建一个 Android 用户并安装小红书，App 会以为这是一台全新设备，
  自己向服务端注册 → 生成全新的 deviceId 与 main_hmac。
  主用户的账号和数据完全不受影响。

  实测：user 10 铸出 fc5a28d7-... / X7Jt8EZ0e3Yk...，
        用它在 unidbg 里签名 + 真实会话请求 → HTTP 200 / code=0 / 10 条数据。

用法：
  # 铸一台新设备，追加到设备池
  python xhs_mint_device.py --out devices.jsonl

  # 指定序列号和用户别名
  python xhs_mint_device.py --serial 1A111FDF600C8J --name xhs3 --out devices.jsonl

  # 只读当前设备（不新建用户）
  python xhs_mint_device.py --harvest-only

  # 清理某个用户
  python xhs_mint_device.py --remove 10
"""
import argparse
import json
import re
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PKG = "com.xingin.xhs"
ACT = "com.xingin.xhs/.index.v2.IndexActivityV2"
MAIN_ACT = "com.xingin.xhs/.index.v2.IndexActivityV2"

# 隐私弹窗「同意」按钮坐标（1080x2400 实测）
CONSENT_X, CONSENT_Y = 540, 1580


def adb(serial, *args, timeout=120):
    cmd = ["adb"] + (["-s", serial] if serial else []) + list(args)
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    return r.returncode, r.stdout.decode("utf-8", "ignore"), r.stderr.decode("utf-8", "ignore")


def su(serial, cmd, timeout=120):
    code, out, err = adb(serial, "shell", "su -c '%s'" % cmd.replace("'", "'\\''"), timeout=timeout)
    return out if out.strip() else err


def prefs_path(user):
    base = "/data/data" if user == 0 else "/data/user/%d" % user
    return "%s/%s/shared_prefs" % (base, PKG)


def pick(xml, key):
    m = re.search(r'<string name="%s">([^<]*)</string>' % re.escape(key), xml)
    return m.group(1) if m else None


def read_identity(serial, user):
    p = prefs_path(user)
    hmac_xml = su(serial, "cat %s/s.xml 2>/dev/null" % p)
    dev_xml = su(serial, "cat %s/pre_device.xml.xml 2>/dev/null" % p)
    return pick(dev_xml, "device_id"), pick(hmac_xml, "main_hmac")


def list_users(serial):
    out = su(serial, "pm list users")
    return {int(m.group(1)): m.group(2) for m in re.finditer(r"UserInfo\{(\d+):([^:}]*):", out)}


def wait_identity(serial, user, timeout=150):
    t0 = time.time()
    while time.time() - t0 < timeout:
        d, h = read_identity(serial, user)
        if d and h:
            return d, h
        time.sleep(3)
    return read_identity(serial, user)


def mint(serial, name, out_file):
    users = list_users(serial)
    print("现有用户:", users)

    code, stdout, stderr = adb(serial, "shell", "su -c 'pm create-user %s'" % name)
    m = re.search(r"id (\d+)", stdout + stderr)
    if not m:
        print("创建用户失败:", stdout, stderr)
        return None
    uid = int(m.group(1))
    print("  · 新用户 id =", uid)

    print("  · 启动用户")
    su(serial, "am start-user -w %d" % uid)
    time.sleep(3)

    print("  · 为该用户安装小红书")
    print("   ", su(serial, "pm install-existing --user %d %s" % (uid, PKG)).strip())

    print("  · 切到该用户")
    su(serial, "am switch-user %d" % uid)
    time.sleep(4)

    print("  · 启动 App")
    su(serial, "am start --user %d -n %s" % (uid, ACT))
    time.sleep(12)

    print("  · 点「同意」隐私协议")
    su(serial, "input tap %d %d" % (CONSENT_X, CONSENT_Y))
    time.sleep(4)
    su(serial, "input tap %d %d" % (CONSENT_X, CONSENT_Y))   # 第二次兜底

    print("  · 等待设备注册（最多 150s）")
    d, h = wait_identity(serial, uid)

    print("  · 切回主用户")
    su(serial, "am switch-user 0")

    if not d or not h:
        print("  ✗ 没拿到身份")
        return None

    rec = {
        "deviceId": d,
        "hmac": h,
        "androidUser": uid,
        "collectedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": "mint",
    }
    print("\n  ✓ deviceId : %s" % d)
    print("  ✓ hmac     : %s...（%d）" % (h[:40], len(h)))
    if out_file:
        with open(out_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print("  已追加到 %s" % out_file)
    return rec


def main():
    ap = argparse.ArgumentParser(description="小红书设备身份铸造（多用户）")
    ap.add_argument("--serial", default=None)
    ap.add_argument("--name", default="xhsdev")
    ap.add_argument("--out", default=None, help="设备池文件（jsonl，追加）")
    ap.add_argument("--harvest-only", action="store_true", help="只读当前设备，不新建用户")
    ap.add_argument("--user", type=int, default=0, help="--harvest-only 时读哪个用户")
    ap.add_argument("--remove", type=int, default=None, help="删除指定用户")
    args = ap.parse_args()

    if args.remove is not None:
        print(su(args.serial, "am switch-user 0; pm remove-user %d" % args.remove))
        print("已删除用户", args.remove)
        return 0

    if args.harvest_only:
        d, h = read_identity(args.serial, args.user)
        if not d or not h:
            print("读不到身份"); return 1
        rec = {"deviceId": d, "hmac": h, "androidUser": args.user,
               "collectedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "source": "harvest"}
        print(json.dumps(rec, ensure_ascii=False))
        if args.out:
            with open(args.out, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return 0

    rec = mint(args.serial, args.name, args.out)
    return 0 if rec else 1


if __name__ == "__main__":
    sys.exit(main())
