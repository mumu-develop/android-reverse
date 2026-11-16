# -*- coding: utf-8 -*-
"""
海南航空 低价航班查询 —— 真实取数（curl_cffi 版）

    POST https://app.hnair.com/ticket/lfs/airLowerPriceShop

用法:
    python hnair_search.py                      # PEK -> SHA, 后天
    python hnair_search.py PEK SHA 2026-11-15   # 指定航线和日期

为什么用 curl_cffi：Python 内置 urllib/requests 的 TLS 指纹会被服务端拒绝（返回 E00001 验签失败），
curl_cffi 基于 curl-impersonate，能伪装浏览器指纹，实测各档 impersonate 与默认均可通过。
"""
import json
import sys
import time

from hnair_params import make_sens, make_hnair_sign, make_appstamp

try:
    from curl_cffi import requests as http
except ImportError:  # 降级：用 curl 命令行
    http = None
    import os
    import subprocess
    import tempfile

BASE = "https://app.hnair.com/ticket/lfs/airLowerPriceShop"
VERSION = "10.14.1"
AKEY = "184C5F04D8BE43DCBD2EE3ABC928F616"
DID = "629DB67741E0AC50F870DB85725F9826"
DNAME = "REDMI_25102RKBEC"
SNAME = "Android/aosp_marlin/marlin:9/PQ3A.190605.07291804/3793265:user/release-keys"
SVER = "9"
IMPERSONATE = "chrome"


def build(dep, arr, date, with_risk=True, risk_token="", black_box="", ekingcode=None):
    """构造 URL / body / headers（参数全部本地计算）"""
    stime = str(int(time.time() * 1000))
    common = {
        "akey": AKEY, "aname": "com.rytong.hnair", "atarget": "standard", "aver": VERSION,
        "did": DID, "dname": DNAME, "mchannel": "official", "schannel": "AD",
        "slang": "zh-CN", "sname": SNAME, "stime": stime, "sver": SVER,
        "system": "AD", "szone": "+0800", "abuild": "67038",
        "hver": "10.14.0.48458.36e7faa6b3.standard",
        "sens": make_sens(stime, AKEY),
    }
    if with_risk:
        common["riskToken"] = risk_token
        common["blackBox"] = black_box

    data = {"originDestinations": [{"destination": arr, "destinationType": "1", "origin": dep,
                                    "departureDate": date, "originType": "1"}],
            "passenger": "ADT:1"}

    flat = dict(common)
    flat.update(data)
    sign = make_hnair_sign({"app": "APP", "channel": "AD"}, {}, flat)

    body = json.dumps({"common": common, "data": data}, ensure_ascii=False, separators=(",", ":"))
    headers = {
        "appver": VERSION, "hna-app": "APP", "hna-channel": "AD",
        "appstamp": make_appstamp(sign),
        "content-type": "application/json; charset=UTF-8",
        "user-agent": "okhttp/4.9.1",
    }
    if ekingcode:
        headers["ekingcode"] = ekingcode
    return "%s?hnairSign=%s" % (BASE, sign), body, headers


def fetch(dep="PEK", arr="SHA", date=None, session=None, **kw):
    """发一次查询，返回 (json, url)"""
    date = date or time.strftime("%Y-%m-%d", time.localtime(time.time() + 2 * 86400))
    url, body, headers = build(dep, arr, date, **kw)
    payload = body.encode("utf-8")

    if http is not None:
        post = (session or http).post
        r = post(url, data=payload, headers=headers, timeout=30,
                 **({} if session else {"impersonate": IMPERSONATE}))
        return r.json(), url

    # 降级：curl 命令行（同样能过，但每次要起进程）
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "body.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        cmd = ["curl.exe", "-sS", "-X", "POST", url, "--data-binary", "@" + path]
        for k, v in headers.items():
            cmd += ["-H", "%s: %s" % (k, v)]
        out = subprocess.run(cmd, capture_output=True).stdout.decode("utf-8", "replace")
    return json.loads(out), url


def show(result):
    print("success =", result.get("success"), "| errorCode =", repr(result.get("errorCode")))
    if not result.get("success"):
        print("message:", result.get("errorMessage"))
        return
    for od in (result.get("data") or {}).get("originDestinations") or []:
        for it in od.get("airItineraries") or []:
            seg = (it.get("flightSegments") or [{}])[0]
            print("  %-6s %s %s->%s  最低价 %s 元  (%s)" % (
                seg.get("flightNumber", "?"), seg.get("departureDate", ""),
                seg.get("departureTime", ""), seg.get("arrivalTime", ""),
                it.get("minLowPrice", "?"), seg.get("aircraftName", "")))


if __name__ == "__main__":
    dep = sys.argv[1] if len(sys.argv) > 1 else "PEK"
    arr = sys.argv[2] if len(sys.argv) > 2 else "SHA"
    date = sys.argv[3] if len(sys.argv) > 3 else None
    t0 = time.time()
    res, url = fetch(dep, arr, date)
    print("URL:", url)
    print("耗时: %.2fs" % (time.time() - t0))
    show(res)
