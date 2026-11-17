#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书 · 纯离线造号 + 批量采集客户端

依赖：本地已启动 xhs-sign-server（unidbg 签名，默认 8098）

链路（全部离线，不需要手机）：
    随机 AID
      → deviceId = uuid3( uuid3(AID) + 毫秒时间戳 )
      → 无签名请求 /system/device_type → 响应头 Xy-Ter-Str = hmac
      → POST /user/activate（unidbg 签名，带完整头 + body）→ session / user_token / ssk
      → 带会话请求数据接口

用法：
    # 造一套身份（不采集）
    python xhs_batch.py mint

    # 造一套身份并采 5 条
    python xhs_batch.py mint --fetch 5

    # 批量：造 3 套身份，每套采 10 次，结果存 jsonl
    python xhs_batch.py batch --devices 3 --per 10 --out notes.jsonl
"""
import argparse
import base64
import gzip
import hashlib
import json
import os
import random
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

try:
    import socks  # noqa: F401  (可选，用于代理)
except Exception:
    socks = None

BASE = "http://127.0.0.1:8098"
HOME = "https://rec.xiaohongshu.com/api/sns/v6/homefeed?oid=homefeed_recommend"
UA = ("Dalvik/2.1.0 (Linux; U; Android 13; Pixel 6 Build/TQ3A.230901.001.C2) "
      "Resolution/1080*2400 Version/9.54.1 Build/9541801 Device/(Google;Pixel 6) "
      "discover/9.54.1 NetType/WiFi")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPSHandler(context=CTX),
)


def http(url, headers=None, data=None, method=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        r = OPENER.open(req, timeout=timeout)
        return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)
    except Exception as e:
        return -1, str(e).encode(), {}


def maybe_gunzip(body, headers):
    if headers.get("Content-Encoding", "").lower() == "gzip" or body[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(body)
        except Exception:
            pass
    return body


# ---------------------------------------------------------------- 设备身份

def nub(data: bytes) -> str:
    """等价 java.util.UUID.nameUUIDFromBytes"""
    h = bytearray(hashlib.md5(data).digest())
    h[6] = (h[6] & 0x0F) | 0x30
    h[8] = (h[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(h)))


def new_aid() -> str:
    return "%016x" % random.getrandbits(64)


def derive_device_id(aid: str, ts_ms: int = None) -> str:
    ts = ts_ms if ts_ms is not None else int(time.time() * 1000)
    return nub((nub(aid.encode()) + str(ts)).encode())


def common_params(device_id, sid="", id_token="", did=None, gid=""):
    did = did or ("%032x" % random.getrandbits(128))
    now = int(time.time())
    return (
        "fid=&gid=%s&device_model=phone&tz=Asia%%2FShanghai&channel=YingYongBao"
        "&versionName=9.54.1&deviceId=%s&platform=android&sid=%s&identifier_flag=4"
        "&cpu_abi=&nqe_score=&project_id=ECFAAF&x_trace_page_current=&lang=zh-Hans"
        "&app_id=ECFAAF01&uis=dark&teenager=0&active_ctry=&cpu_name=oriole&dlang=zh"
        "&data_ctry=CN&SUE=1&launch_id=%d&id_token=%s&device_level=&origin_channel=YingYongBao"
        "&overseas_channel=0&mlanguage=zh_cn&folder_type=none&auto_trans=0&t=%d"
        "&build=9541801&holder_ctry=CN&did=%s"
    ) % (gid, device_id, urllib.parse.quote(sid, safe=""),
         now, urllib.parse.quote(id_token, safe=""), now, did)


def fetch_hmac(device_id: str, aid: str):
    """无签名请求 device_type，从响应头 Xy-Ter-Str 拿 hmac"""
    url = "https://edith.xiaohongshu.com/api/sns/v1/system/device_type?device_model=Pixel%206"
    code, body, hdrs = http(url, {
        "User-Agent": UA, "Referer": "https://app.xhs.cn/",
        "xy-common-params": common_params(device_id),
    })
    hmac = hdrs.get("Xy-Ter-Str") or hdrs.get("xy-ter-str")
    return hmac, code


# ---------------------------------------------------------------- 签名服务

def sign(device_id, hmac, url, common=None, body=None, ct=None, extra=None):
    q = {"deviceId": device_id, "hmac": hmac, "url": url}
    if common:
        q["common"] = common
    if body is not None:
        q["body"] = body
        q["contentType"] = ct or "application/x-www-form-urlencoded"
    if extra:
        q["extraHeaders"] = json.dumps(extra, ensure_ascii=False)
    code, raw, _ = http(BASE + "/xhs/signFor?" + urllib.parse.urlencode(q), timeout=180)
    d = json.loads(raw.decode("utf-8", "ignore"))
    if not d.get("ok"):
        raise RuntimeError("签名失败: %s" % d.get("error"))
    return d["headers"]


# ---------------------------------------------------------------- 激活会话

TEMPLATE_HEADERS = {}


def load_template(path):
    global TEMPLATE_HEADERS
    if os.path.exists(path):
        rec = json.load(open(path, encoding="utf-8"))
        TEMPLATE_HEADERS = {k: v for k, v in rec["headers"].items()
                            if k.lower() not in ("shield", "xy-platform-info",
                                                 "xy-common-params", "content-length",
                                                 "accept-encoding")}
        return rec.get("body", "")
    return ""


def activate(device_id, hmac, aid, did=None, body_tpl=None):
    did = did or ("%032x" % random.getrandbits(128))
    pub = base64.b64encode(bytes(random.getrandbits(8) for _ in range(32))).decode()
    if body_tpl:
        body = body_tpl
        body = body.replace("android_id=5a1b2c3d4e5f6071", "android_id=" + aid)
        body = body.replace("did_cur_value=e6af67c0198496cb3b9ec17108fabfba",
                            "did_cur_value=" + did)
        if "client_public_key_base64=" in body:
            import re
            body = re.sub(r"client_public_key_base64=[^&]*",
                          "client_public_key_base64=" + urllib.parse.quote(pub, safe=""), body)
    else:
        body = ("idfa=&idfv=&android_id=%s&channel=&pasteboard=&category=&oaid=noNeedOnCreate"
                "&android_version=33&mac=&gaid=&attribution_id=&imei_encrypted="
                "&install_time=%s&install_first_open=true&open_url=&after_register=true"
                "&last_login_user_id=&extra_data=%%7B%%22systemFontSize%%22%%3A1"
                "%%2C%%22em%%22%%3A-1%%7D&source=0&did_cur_value=%s"
                "&did_last_value=default-currentDid&did_cur_source=LOCAL_GEN"
                "&client_public_key_base64=%s") % (
                    aid, urllib.parse.quote(time.strftime("%Y-%m-%d %H:%M:%S"), safe=""),
                    did, urllib.parse.quote(pub, safe=""))

    extra = dict(TEMPLATE_HEADERS)
    extra["x-legacy-did"] = device_id
    cp = common_params(device_id, did=did)
    url = "https://edith.xiaohongshu.com/api/sns/v1/user/activate"
    h = sign(device_id, hmac, url, common=cp, body=body,
             ct="application/x-www-form-urlencoded", extra=extra)
    h.update(extra)
    h["xy-common-params"] = cp
    h["accept-encoding"] = "gzip"
    code, raw, hdrs = http(url, headers=h, data=body.encode(), method="POST")
    raw = maybe_gunzip(raw, hdrs)
    try:
        j = json.loads(raw.decode("utf-8", "ignore"))
    except Exception:
        return None, code, raw[:200]
    data = j.get("data") or {}
    if not data.get("session"):
        return None, code, j
    sid = "session." + str(data["session"])
    return {
        "deviceId": device_id,
        "hmac": hmac,
        "aid": aid,
        "did": did,
        "sid": sid,
        "userToken": data.get("user_token", ""),
        "userId": data.get("userid", ""),
        "secureSession": data.get("secure_session", ""),
        "ssk": data.get("ssk"),
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }, code, j


# ---------------------------------------------------------------- 采集

def fetch(identity, url=HOME, extra=None):
    cp = common_params(identity["deviceId"], sid=identity.get("sid", ""),
                       id_token=identity.get("userToken", ""), did=identity.get("did"))
    extra = dict(TEMPLATE_HEADERS if extra is None else extra)
    h = sign(identity["deviceId"], identity["hmac"], url, common=cp, extra=extra)
    h.update(extra)
    h["xy-common-params"] = cp
    h["accept-encoding"] = "gzip"
    code, raw, hdrs = http(url, headers=h)
    raw = maybe_gunzip(raw, hdrs)
    try:
        return code, json.loads(raw.decode("utf-8", "ignore"))
    except Exception:
        return code, {"_raw": raw[:200].decode("utf-8", "ignore")}


def notes_of(j):
    out = []
    for it in (j.get("data") or []):
        if not isinstance(it, dict):
            continue
        card = it.get("note_card") or {}
        out.append({
            "id": it.get("id"),
            "title": card.get("display_title") or it.get("title") or "",
            "user": (card.get("user") or {}).get("nickname") or "",
            "likes": card.get("interact_info", {}).get("liked_count") or it.get("likes"),
            "type": it.get("model_type") or card.get("type"),
        })
    return out


# ---------------------------------------------------------------- CLI

def cmd_mint(args):
    aid = new_aid()
    dev = derive_device_id(aid)
    print("AID      :", aid)
    print("deviceId :", dev)
    hmac, code = fetch_hmac(dev, aid)
    print("hmac     :", (hmac[:40] + "...") if hmac else None, " (device_type HTTP %s)" % code)
    if not hmac:
        print("❌ 没拿到 hmac"); return 1
    ident, code, j = activate(dev, hmac, aid, body_tpl=args.template_body)
    if not ident:
        print("❌ activate 失败 HTTP", code, str(j)[:200]); return 1
    print("sid      :", ident["sid"])
    print("userToken:", ident["userToken"][:24] + "...")
    print("userId   :", ident["userId"])
    if args.out:
        with open(args.out, "a", encoding="utf-8") as f:
            f.write(json.dumps(ident, ensure_ascii=False) + "\n")
        print("已追加到", args.out)
    if args.fetch:
        code, j = fetch(ident)
        ns = notes_of(j)
        print("采集: HTTP %s code=%s 条数=%d" % (code, j.get("code"), len(ns)))
        for n in ns[:args.fetch]:
            print("   -", n["id"], n["title"][:26], "赞", n["likes"])
    return 0


def cmd_batch(args):
    got = 0
    for i in range(args.devices):
        print("\n=== 设备 %d/%d ===" % (i + 1, args.devices))
        aid = new_aid()
        dev = derive_device_id(aid)
        hmac, _ = fetch_hmac(dev, aid)
        if not hmac:
            print("  拿不到 hmac，跳过"); continue
        ident, code, j = activate(dev, hmac, aid, body_tpl=args.template_body)
        if not ident:
            print("  activate 失败 HTTP", code); continue
        print("  设备就绪:", dev[:13], " sid:", ident["sid"][-10:])
        if args.out:
            with open(args.out, "a", encoding="utf-8") as f:
                f.write(json.dumps(ident, ensure_ascii=False) + "\n")
        for k in range(args.per):
            code, j = fetch(ident)
            ns = notes_of(j)
            if ns:
                got += len(ns)
                print("    [%d] HTTP %s code=%s 条数=%d" % (k + 1, code, j.get("code"), len(ns)))
            else:
                print("    [%d] HTTP %s code=%s msg=%s" % (k + 1, code, j.get("code"), j.get("msg")))
                if str(j.get("code")) in ("-20240855", "-100"):
                    break
            time.sleep(1.2)
    print("\n共采集 %d 条" % got)
    return 0


def main():
    global BASE
    ap = argparse.ArgumentParser(description="小红书纯离线造号 + 批量采集")
    ap.add_argument("--base", default=BASE)
    sub = ap.add_subparsers(dest="cmd")

    p1 = sub.add_parser("mint", help="造一套身份")
    p1.add_argument("--out", default=None, help="身份池 jsonl")
    p1.add_argument("--fetch", type=int, default=0, help="顺便采几条")
    p1.add_argument("--template-body", default=None, help="activate 请求体模板文件")

    p2 = sub.add_parser("batch", help="批量造号 + 采集")
    p2.add_argument("--devices", type=int, default=1)
    p2.add_argument("--per", type=int, default=5, help="每台设备采几次")
    p2.add_argument("--out", default=None)
    p2.add_argument("--template-body", default=None)

    args = ap.parse_args()
    BASE = args.base
    if args.cmd == "mint":
        return cmd_mint(args)
    if args.cmd == "batch":
        return cmd_batch(args)
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
