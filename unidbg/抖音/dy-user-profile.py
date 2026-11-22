# -*- coding: utf-8 -*-
"""抖音 · 用户详情

接口：GET https://aweme.snssdk.com/aweme/v1/user/profile/other/
签名：本地 unidbg 服务 /api/sign
用法：
    python dy-user-profile.py <sec_user_id> [-o out.json]

sec_user_id 从哪来：
    · 评论接口返回的 user.sec_uid
    · 抖音主页链接 /user/MS4wLjABAAAA...
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import re

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

SERVICE = os.environ.get("DY_SERVICE", "http://127.0.0.1:8099")
HOST = "https://aweme.snssdk.com"
PATH = "/aweme/v1/user/profile/other/"
UA = "com.ss.android.ugc.aweme/400200 (Linux; U; Android 13; zh_CN; Pixel 6)"

# 设备身份（与签名服务里的设备保持一致，否则可能 status_code != 0）
IID = "3594782549750826"
CDID = "e3683b4a-3bf8-49c6-9332-6985361a6c4c"


def parse_sec_uid(text):
    """支持直接传 sec_uid，或传抖音主页链接/分享链接"""
    text = (text or "").strip()
    m = re.search(r"MS4wLjABAAAA[\w\-]+", text)
    if m:
        return m.group(0)
    if text.startswith("MS4w") and len(text) > 40:
        return text
    raise SystemExit("无法从输入解析 sec_user_id: %s" % text[:80])


def service_health():
    with OPENER.open(SERVICE + "/api/health", timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def base_params():
    """公共参数：从服务读 device_id，保证与签名机一致"""
    h = service_health()
    return {
        "aid": "1128", "app_name": "aweme", "version_code": "400200",
        "version_name": "40.2.0", "manifest_version_code": "400201",
        "update_version_code": "40209900", "device_platform": "android",
        "device_type": "Pixel 6", "device_brand": "google", "os": "android",
        "os_api": "33", "os_version": "13", "channel": "huawei_1128_64",
        "device_id": h.get("deviceId"), "iid": IID, "cdid": CDID,
        "resolution": "1080*2209", "dpi": "420", "host_abi": "arm64-v8a",
        "cpu_support64": "true", "language": "zh", "ac": "wifi",
    }


def sign(url):
    q = urllib.parse.urlencode({"url": url})
    with OPENER.open(SERVICE + "/api/sign?" + q, timeout=180) as r:
        j = json.loads(r.read().decode("utf-8"))
    if not j.get("ok"):
        raise RuntimeError("签名失败: %s" % j.get("error"))
    return j["headers"]


def fetch_profile(sec_uid, retries=3):
    for i in range(1, retries + 1):
        p = base_params()
        p["sec_user_id"] = sec_uid
        p["from"] = "0"
        p["source"] = "UserProfileFragment_loadAheadExp_SLIDE_PROFILE"
        ts = int(time.time() * 1000)
        p["_rticket"] = str(ts)
        p["ts"] = str(ts // 1000)

        url = HOST + PATH + "?" + urllib.parse.urlencode(p)
        try:
            h = dict(sign(url))
            h["User-Agent"] = UA
            with OPENER.open(urllib.request.Request(url, headers=h), timeout=30) as r:
                j = json.loads(r.read().decode("utf-8", "ignore"))
            if j.get("status_code") == 0:
                return j
            print("  第 %d 次: status_code=%s" % (i, j.get("status_code")), file=sys.stderr)
        except Exception as e:
            print("  第 %d 次异常: %r" % (i, e), file=sys.stderr)
        time.sleep(1.5)
    raise RuntimeError("用户详情接口连续失败")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sec_uid")
    ap.add_argument("-o", "--out", help="保存 JSON 到文件")
    args = ap.parse_args()

    sec_uid = parse_sec_uid(args.sec_uid)
    j = fetch_profile(sec_uid)
    u = j.get("user") or {}

    print("昵称     :", u.get("nickname"))
    print("uid      :", u.get("uid"))
    print("sec_uid  :", u.get("sec_uid"))
    print("抖音号   :", u.get("unique_id") or u.get("short_id"))
    print("粉丝     :", u.get("follower_count"))
    print("关注     :", u.get("following_count"))
    print("作品数   :", u.get("aweme_count"))
    print("获赞     :", u.get("total_favorited"))
    sig = (u.get("signature") or "").replace("\n", " ")
    print("签名     :", sig[:60])

    if args.out:
        json.dump(j, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("[+] 已保存", args.out)


if __name__ == "__main__":
    main()
