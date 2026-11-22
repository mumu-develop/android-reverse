# -*- coding: utf-8 -*-
"""抖音 · 用户作品列表（视频列表）

接口：GET https://aweme.snssdk.com/aweme/v1/aweme/post/
签名：本地 unidbg 服务 /api/sign
分页：返回里的 max_cursor 给下一页用，has_more=1 才继续

用法：
    python dy-user-posts.py <sec_user_id> [-p 页数] [-o out.json]

sec_user_id 从哪来：
    · 用户详情接口的 user.sec_uid
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
PATH = "/aweme/v1/aweme/post/"
UA = "com.ss.android.ugc.aweme/400200 (Linux; U; Android 13; zh_CN; Pixel 6)"

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


def fetch_page(sec_uid, cursor, count, retries=3):
    for i in range(1, retries + 1):
        p = base_params()
        p.update({
            "sec_user_id": sec_uid,
            "max_cursor": str(cursor),
            "count": str(count),
            "is_other": "1",
            "source": "0",
            "page_from": "2",
            "publish_video_strategy_type": "2",
            "user_avatar_shrink": "96_96",
            "video_cover_shrink": "285_379",
            "need_time_list": "0",
            "show_live_replay_strategy": "1",
        })
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
    raise RuntimeError("作品列表接口连续失败 cursor=%s" % cursor)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sec_uid")
    ap.add_argument("-p", "--pages", type=int, default=1, help="最多翻几页")
    ap.add_argument("-c", "--count", type=int, default=20, help="每页条数")
    ap.add_argument("-o", "--out", help="保存 JSON 到文件")
    args = ap.parse_args()

    sec_uid = parse_sec_uid(args.sec_uid)
    all_items, cursor = [], 0
    for page in range(1, args.pages + 1):
        j = fetch_page(sec_uid, cursor, args.count)
        items = j.get("aweme_list") or []
        all_items.extend(items)
        print("第 %d 页: %d 条  has_more=%s  max_cursor=%s" %
              (page, len(items), j.get("has_more"), j.get("max_cursor")))
        if not items or not j.get("has_more"):
            break
        cursor = j.get("max_cursor") or 0
        time.sleep(0.3)

    print("\n共 %d 个作品" % len(all_items))
    for a in all_items[:10]:
        st = a.get("statistics") or {}
        print("  %s  %-40s 赞%-6s 评%-5s" % (
            a.get("aweme_id"),
            (a.get("desc") or "").replace("\n", " ")[:40],
            st.get("digg_count"), st.get("comment_count")))

    if args.out:
        json.dump({"aweme_list": all_items}, open(args.out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("[+] 已保存", args.out)


if __name__ == "__main__":
    main()
