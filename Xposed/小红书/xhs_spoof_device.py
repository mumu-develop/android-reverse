#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书设备身份「指纹伪造」铸造工具

原理（已实测）：
  服务端按 ANDROID_ID 下发 (deviceId, main_hmac) 这一对密钥。
  用 Xposed 钩 Settings.Secure.getString("android_id")，返回一个伪造值，
  再清掉 s.xml / pre_device.xml.xml，App 就会以为自己是全新设备，
  自动向服务端注册出一对全新的 (deviceId, hmac)。

  实测：伪造 ad8210c6f197c497 → 得到 3efdd6e1-81f3-3013-80a8-d958536e194b
        签名被服务端接受（HTTP 200，不是 406）

相比多用户方案：
  · 不用创建 Android 用户（不会卡 system_server）
  · 不用点 UI（没有隐私弹窗）
  · 一轮约 40 秒

前置：
  · 手机已 root
  · 已安装并启用 sekiro-rpc-hook 模块（含 ANDROID_ID 伪造钩子）

用法：
  # 铸造 5 台，存到设备池
  python xhs_spoof_device.py --serial <序列号> --count 5 --out devices.jsonl

  # 铸造 1 台并保留（不恢复原身份）
  python xhs_spoof_device.py --count 1 --keep

  # 只恢复备份的身份
  python xhs_spoof_device.py --restore
"""
import argparse
import json
import os
import random
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
PREFS = "/data/data/%s/shared_prefs" % PKG
FAKE_FILE = "/data/data/%s/files/fake_aid.txt" % PKG
BACKUP = "/sdcard/xhs_identity_backup"


def adb(serial, *args, timeout=90):
    cmd = ["adb"] + (["-s", serial] if serial else []) + list(args)
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    return r.returncode, r.stdout.decode("utf-8", "ignore"), r.stderr.decode("utf-8", "ignore")


def su(serial, cmd, timeout=120):
    code, out, err = adb(serial, "shell", "su -c '%s'" % cmd.replace("'", "'\\''"), timeout=timeout)
    return out


def pick(xml, key):
    m = re.search(r'<string name="%s">([^<]*)</string>' % re.escape(key), xml)
    return m.group(1) if m else None


def read_identity(serial):
    p = "%s/shared_prefs" % ("/data/data/" + PKG)
    hmac = pick(su(serial, "cat %s/s.xml 2>/dev/null" % p), "main_hmac")
    dev = pick(su(serial, "cat %s/pre_device.xml.xml 2>/dev/null" % p), "device_id")
    return dev, hmac


def backup(serial, tag):
    su(serial, "mkdir -p %s/%s" % (BACKUP, tag))
    su(serial, "cp -f %s/s.xml %s/%s/s.xml 2>/dev/null" % (PREFS, BACKUP, tag))
    su(serial, "cp -f %s/pre_device.xml.xml %s/%s/pre_device.xml.xml 2>/dev/null" % (PREFS, BACKUP, tag))


def restore(serial, tag):
    su(serial, "am force-stop %s" % PKG)
    time.sleep(1)
    su(serial, "rm -f %s" % FAKE_FILE)
    su(serial, "cp -f %s/%s/s.xml %s/s.xml 2>/dev/null" % (BACKUP, tag, PREFS))
    su(serial, "cp -f %s/%s/pre_device.xml.xml %s/pre_device.xml.xml 2>/dev/null" % (BACKUP, tag, PREFS))
    su(serial, "chown u0_a259:u0_a259 %s/s.xml %s/pre_device.xml.xml 2>/dev/null" % (PREFS, PREFS))
    su(serial, "chmod 660 %s/s.xml %s/pre_device.xml.xml 2>/dev/null" % (PREFS, PREFS))
    su(serial, "am start -n %s >/dev/null 2>&1" % ACT)
    return read_identity(serial)


def mint_one(serial, timeout=120):
    aid = "%016x" % random.getrandbits(64)
    print("  · 伪造 ANDROID_ID = %s" % aid)

    su(serial, "am force-stop %s" % PKG)
    time.sleep(1)
    su(serial, "mkdir -p %s/files" % ("/data/data/" + PKG))
    su(serial, "printf '%%s' '%s' > %s" % (aid, FAKE_FILE))
    su(serial, "chown u0_a259:u0_a259 %s; chmod 660 %s; restorecon %s 2>/dev/null"
       % (FAKE_FILE, FAKE_FILE, FAKE_FILE))

    # 移走旧身份，强制重新注册
    su(serial, "mv -f %s/s.xml %s/s.xml.mint 2>/dev/null" % (PREFS, PREFS))
    su(serial, "mv -f %s/pre_device.xml.xml %s/pre_device.xml.xml.mint 2>/dev/null" % (PREFS, PREFS))

    # 清 MMKV：游客会话（sid）存在这里，清掉后 App 会为新设备重新申请，
    # 从而拿到新的一份配额（实测每台设备约 47 次请求）
    base = "/data/data/%s" % PKG
    su(serial, "rm -rf %s/files/mmkv; mkdir -p %s/files/mmkv" % (base, base))
    su(serial, "chown u0_a259:u0_a259 %s/files/mmkv; restorecon %s/files/mmkv 2>/dev/null"
       % (base, base))

    su(serial, "am start -n %s >/dev/null 2>&1" % ACT)

    t0 = time.time()
    while time.time() - t0 < timeout:
        d, h = read_identity(serial)
        if d and h:
            # 第二次启动：清掉 MMKV 再重启，让 App 为这台新设备申请游客会话
            # （实测一次启动只会得到空 id_token 的会话，需要第二次才可用）
            base = "/data/data/%s" % PKG
            su(serial, "am force-stop %s" % PKG)
            time.sleep(2)
            su(serial, "rm -rf %s/files/mmkv; mkdir -p %s/files/mmkv" % (base, base))
            su(serial, "chown u0_a259:u0_a259 %s/files/mmkv; restorecon %s/files/mmkv 2>/dev/null"
               % (base, base))
            su(serial, "am start -n %s >/dev/null 2>&1" % ACT)
            time.sleep(15)
            return d, h, aid
        time.sleep(3)
    return read_identity(serial)[0], read_identity(serial)[1], aid


def main():
    ap = argparse.ArgumentParser(description="小红书设备身份铸造（ANDROID_ID 伪造）")
    ap.add_argument("--serial", default=None)
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--out", default=None, help="设备池 jsonl（追加）")
    ap.add_argument("--keep", action="store_true", help="保留最后一台铸造的身份，不恢复原身份")
    ap.add_argument("--restore", default=None, metavar="TAG", help="恢复某个备份标签的身份")
    args = ap.parse_args()

    if args.restore:
        d, h = restore(args.serial, args.restore)
        print("已恢复: deviceId=%s" % d)
        return 0

    tag = time.strftime("mint_%Y%m%d_%H%M%S")
    orig_dev, orig_hmac = read_identity(args.serial)
    print("原设备: %s" % orig_dev)
    backup(args.serial, tag)
    print("已备份到 %s/%s" % (BACKUP, tag))

    minted = []
    for i in range(args.count):
        print("\n[%d/%d] 铸造中..." % (i + 1, args.count))
        d, h, aid = mint_one(args.serial)
        if not d or not h:
            print("  ✗ 失败（没拿到身份）")
            continue
        print("  ✓ deviceId = %s" % d)
        print("    hmac     = %s... (%d)" % (h[:36], len(h)))
        rec = {"deviceId": d, "hmac": h, "fakeAndroidId": aid,
               "collectedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "source": "spoof"}
        minted.append(rec)
        if args.out:
            with open(args.out, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print("\n本轮铸造 %d 台" % len(minted))

    if not args.keep:
        print("\n恢复原身份 ...")
        d, _ = restore(args.serial, tag)
        print("已恢复: %s" % d)
    else:
        print("\n保留最后一台身份（原身份备份在 %s/%s）" % (BACKUP, tag))
    return 0 if minted else 1


if __name__ == "__main__":
    sys.exit(main())
