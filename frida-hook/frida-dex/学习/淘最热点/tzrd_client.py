"""淘最热点 (com.maihan.tredian) 接口签名 · 纯 Python 实现

算法出自 lib/armeabi-v7a/libtre.so
    Java_com_maihan_tredian_util_TreUtil_sign  @ 0x17d8

    strcpy(buf, 入参串);
    strcat(buf, SALT);                 // 64 字符常量，长得像 base64 表，实际是盐
    base64_encode_new(buf, out, len);  // 标准 base64，带 '=' 填充
    SHA1Input(ctx, out, strlen(out));  // 哈希的是 base64 之后的字符串
    SHA1Result(ctx, digest);
    for (i = 0; i < 20; i++) sprintf(hex, "%02x", digest[i]);   // 小写 hex

即  sign = sha1( base64( 待签串 + SALT ) )

待签串由 com.maihan.tredian.net.MhRequestUtil.a(map, false, false) 生成：
    key 按 String.compareTo 升序，拼成 k=v&k=v，跳过 null/""/"null"，不做 urlencode。
    注意 sign 自身不参与签名（先算 sign 再 put 进 map）。
"""

import base64
import hashlib
import random
import string
import time

BASE = "https://api.news.taozuiredian.com/api/v1/news/hot"

SALT = "b2qKgtaW4,9z9D`Fmst?K5JZbLYOY]NP6ssGf2U~;zk9oCNgoytV!}wW7ia+`w9g"

UA = "Dalvik/2.1.0 (Linux; U; Android 9; 25102RKBEC Build/PQ3A.190605.07291804)"

# 固定设备参数，换设备只改这里
DEVICE = {
    "android_id": "f3218b338c7a6a7b",
    "app_ver": "87",
    "channel": "aliapp",
    "device_id": "bfc21e7dce6a8b582b3c200a2c7e4629",
    "device_udid": "d1b9e2ecb7ec98baa7edc20f1dda6e9",
    "first_time": "1706003627",
    "from": "app",
    "last_time": "1695778037",
    "limit": "8",
    "mac": "00:DB:8D:E2:17:A5",
    "os_ver_code": "28",
    "system": "1",
    "with_super": "0",
    "with_video": "1",
}


def nonce():
    """6 位 [a-z0-9] 随机 + 毫秒时间戳，对应 MhRequestUtil.a()"""
    head = "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(6))
    return head + str(int(time.time() * 1000))


def sign(raw):
    """raw = 已排序拼接好的待签串"""
    return hashlib.sha1(base64.b64encode((raw + SALT).encode())).hexdigest()


def build_params(extra=None):
    p = dict(DEVICE)
    p["nonce"] = nonce()
    p["timestamp"] = str(int(time.time()))
    if extra:
        p.update(extra)

    raw = "&".join(f"{k}={p[k]}" for k in sorted(p) if p[k] not in (None, "", "null"))
    p["sign"] = sign(raw)
    return p, raw


def news_hot(**extra):
    """取热门列表；extra 可覆盖任意参数，如 limit=20"""
    p, raw = build_params(extra)

    try:
        from curl_cffi import requests
        r = requests.get(BASE, params=p, headers={"User-Agent": UA}, impersonate="chrome", timeout=15)
    except ImportError:
        import urllib.parse
        import urllib.request
        url = BASE + "?" + urllib.parse.urlencode(p)
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=15)

    body = r.text if hasattr(r, "text") else r.read().decode()
    return r.status_code, body, raw, p["sign"]


if __name__ == "__main__":
    st, body, raw, sg = news_hot()
    print("待签串 ->", raw)
    print("sign   ->", sg)
    print("status ->", st)
    print("body   ->", body[:300])
