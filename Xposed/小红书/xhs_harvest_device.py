#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书设备身份采集工具

从已 root 的手机上读出离线签名所需的两个关键值：
  deviceId  ← /data/data/com.xingin.xhs/shared_prefs/pre_device.xml.xml 的 device_id
  main_hmac ← /data/data/com.xingin.xhs/shared_prefs/s.xml 的 main_hmac

一条 (deviceId, main_hmac) 可以脱离手机长期使用（unidbg 离线签名），
被封后换下一条。

用法：
  # 读取当前设备的身份
  python xhs_harvest_device.py

  # 指定设备序列号、写入设备池文件
  python xhs_harvest_device.py --serial 1A111FDF600C8J --out devices.jsonl

  # 【破坏性】清掉小红书数据 → 启动 → 等它生成新身份 → 采集
  #   会丢失登录态，游客身份也能拿到 hmac
  python xhs_harvest_device.py --clear --out devices.jsonl

设备池文件每行一条 JSON，可直接喂给 xhs-sign-server 配置：
  {"deviceId": "...", "hmac": "...", "collectedAt": "..."}
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
PREFS = "/data/data/%s/shared_prefs" % PKG
FILE_DEV = PREFS + "/pre_device.xml.xml"
FILE_HMAC = PREFS + "/s.xml"


def adb(serial, *args, timeout=60):
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    return r.returncode, r.stdout.decode("utf-8", "ignore"), r.stderr.decode("utf-8", "ignore")


def su_cat(serial, path):
    code, out, err = adb(serial, "shell", "su -c 'cat %s 2>/dev/null'" % path)
    return out if out.strip() else ""


def pick(xml, key):
    m = re.search(r'<string name="%s">([^<]*)</string>' % re.escape(key), xml)
    return m.group(1) if m else None


def harvest(serial):
    dev_xml = su_cat(serial, FILE_DEV)
    hmac_xml = su_cat(serial, FILE_HMAC)
    device_id = pick(dev_xml, "device_id")
    hmac = pick(hmac_xml, "main_hmac")
    return device_id, hmac


def app_running(serial):
    code, out, _ = adb(serial, "shell", "pidof %s" % PKG)
    return bool(out.strip())


def clear_and_launch(serial):
    print("  · 停止 App")
    adb(serial, "shell", "am force-stop %s" % PKG)
    time.sleep(1)
    print("  · 清除数据（登录态会丢失）")
    adb(serial, "shell", "pm clear %s" % PKG)
    time.sleep(2)
    print("  · 启动 App")
    adb(serial, "shell", "monkey -p %s -c android.intent.category.LAUNCHER 1" % PKG)
    # 等它完成首次初始化 / 设备注册
    for i in range(30):
        time.sleep(2)
        d, h = harvest(serial)
        if d and h:
            print("  · 第 %d 秒拿到身份" % ((i + 1) * 2))
            return d, h
        if i % 5 == 4:
            print("  · 等待中... %ds" % ((i + 1) * 2))
    return harvest(serial)


def main():
    ap = argparse.ArgumentParser(description="小红书设备身份采集")
    ap.add_argument("--serial", default=None, help="adb 设备序列号")
    ap.add_argument("--out", default=None, help="设备池文件（jsonl，追加）")
    ap.add_argument("--clear", action="store_true", help="【破坏性】清数据后采集新身份")
    args = ap.parse_args()

    if args.clear:
        print("== 清数据造新身份 ==")
        device_id, hmac = clear_and_launch(args.serial)
    else:
        print("== 读取当前设备身份 ==")
        device_id, hmac = harvest(args.serial)

    if not device_id or not hmac:
        print("失败：")
        if not device_id:
            print("  · 读不到 device_id（%s）—— 需要 root，且 App 至少要启动过一次" % FILE_DEV)
        if not hmac:
            print("  · 读不到 main_hmac（%s）" % FILE_HMAC)
        return 1

    rec = {
        "deviceId": device_id,
        "hmac": hmac,
        "collectedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": "clear" if args.clear else "current",
    }
    print("\ndeviceId : %s" % device_id)
    print("hmac     : %s...（%d 字符）" % (hmac[:40], len(hmac)))

    if args.out:
        with open(args.out, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print("\n已追加到 %s" % args.out)
    else:
        print("\n" + json.dumps(rec, ensure_ascii=False))

    print("\n填进 xhs-sign-server 的 application.yml：")
    print("  device-id: %s" % device_id)
    print("  main-hmac: %s" % hmac)
    return 0


if __name__ == "__main__":
    sys.exit(main())
