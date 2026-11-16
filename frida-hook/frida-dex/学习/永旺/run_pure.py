#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AeonBuy app-api 加解密工具 (单文件, 零第三方依赖)

================================================================================
 用法
================================================================================

【场景 1】抓到了一个请求, 想还原成明文
    python run_pure.py --file capture_curl.txt

  capture_curl.txt 里放 Charles 的 "Copy cURL Request" 全文, 例如:

    curl -H "x-client-nonce: rsGiGsK9egT6a0EaippTMkJakrOvVC8n" \\
         -H "x-http-encryption: 1" \\
         --data-binary "XcnjEn0ZYP2xJ8Xg..." \\
         "https://delivery.aeonbuy.com/api/app-api/delivery/search/categoryProductList"

  脚本会自动从中提取 x-client-nonce 和密文。

【场景 2】解出明文后, 立刻用它重新发一次请求
    python run_pure.py --file capture_curl.txt --send

【场景 3】用它内置的 PARAMS 发请求 (参数写在文件顶部的 PARAMS 里)
    python run_pure.py

【场景 4】只给密文, nonce 手工传
    python run_pure.py --decrypt "<密文>" --nonce "<x-client-nonce>"
    python run_pure.py --decrypt - --nonce "<x-client-nonce>" < body.txt

【场景 5】解响应 (nonce 和公钥都从响应头取)
    python run_pure.py --decrypt "<响应密文>" --nonce "<x-server-nonce>" --pubkey "<x-server-pubkey>"

【场景 6】在别的 Python 代码里调用
    from run_pure import decrypt_request, send_request
    import json

    plain  = decrypt_request(open("capture_curl.txt", encoding="utf-8").read())
    params = json.loads(plain)
    params["categoryId"] = "24"
    print(send_request(params))

================================================================================
 说明
================================================================================
  * 加密算法 X25519 + XSalsa20-Poly1305, 全部内联在本文件, 不 import 本地模块
  * 请求密文必须配合请求头里的 x-client-nonce 才能解 (nonce 不在 body 里)
  * 密文里的空格/换行会自动去掉, 直接粘贴即可
  * 报 "MAC 校验失败" = nonce 抄错了; 报 "找不到 x-client-nonce" = 没给 nonce
"""
import base64
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request

# ---------------------------------------------------------------- 入参写这里
PARAMS = {
    "aggVals": "",
    "cacheKey": "f340f1b1f65b6df5b5e3f94d95b11daf",
    "categoryId": "24",
    "deliveryTimeType": 3,
    "lastCategoryUpQuery": 0,
    "maxPrice": "",
    "method": 1,
    "minPrice": "",
    "pageNum": 1,
    "pageSize": 10,
    "rankType": "1",
    "storeCode": "7013",
}
# ---------------------------------------------------------------- 入参结束

URL = "https://delivery.aeonbuy.com/api/app-api/delivery/search/categoryProductList"

CLIENT_SK_HEX = "1a4707734824a0957987f1e731aa75518ac203c9092ab50f5c216607f7fd6017"
CLIENT_PK_HEX = "c2dcb063d3339acf27e7e4749438fc8d6826bd9d5e02d1673028790939391d1e"
SERVER_PK_HEX = "aa042a1c6116cf60813d5d098496d909f366bb6c01bfe53ec1c6c69da3461f3b"

SHOW_CIPHERTEXT = True

HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "x-http-encryption": "1",
    "x-http-channel": "app",
    "x-http-devicetype": "android",
    "x-http-locale": "zh-cn",
    "x-http-version": "2.3.72",
    "x-http-osversion": "9",
    "x-http-vendortype": "REDMI",
    "x-http-deviceuid": "1104a89793fd854c51a",
    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; 25102RKBEC Build/PQ3A.190605.07291804)",
}


# ================================================================
# 以下为纯 Python 的 libsodium crypto_box 实现 (X25519 + XSalsa20-Poly1305)
# ================================================================
_P = 2 ** 255 - 19
_A24 = 121665
_M32 = 0xFFFFFFFF
_SIGMA = [0x61707865, 0x3320646E, 0x79622D32, 0x6B206574]


def _clamp(k):
    b = bytearray(k)
    b[0] &= 248
    b[31] &= 127
    b[31] |= 64
    return int.from_bytes(bytes(b), "little")


def x25519(scalar, u_bytes):
    k = _clamp(scalar)
    x1 = int.from_bytes(u_bytes, "little") & ((1 << 255) - 1)
    x2, z2, x3, z3 = 1, 0, x1, 1
    swap = 0
    for t in range(254, -1, -1):
        kt = (k >> t) & 1
        swap ^= kt
        if swap:
            x2, x3 = x3, x2
            z2, z3 = z3, z2
        swap = kt
        a = (x2 + z2) % _P
        aa = a * a % _P
        b = (x2 - z2) % _P
        bb = b * b % _P
        e = (aa - bb) % _P
        c = (x3 + z3) % _P
        d = (x3 - z3) % _P
        da = d * a % _P
        cb = c * b % _P
        x3 = (da + cb) ** 2 % _P
        z3 = x1 * (da - cb) ** 2 % _P
        x2 = aa * bb % _P
        z2 = e * (aa + _A24 * e) % _P
    if swap:
        x2, z2 = x3, z3
    return (x2 * pow(z2, _P - 2, _P) % _P).to_bytes(32, "little")


def _rotl(v, c):
    return ((v << c) & _M32) | (v >> (32 - c))


def _rounds(x):
    for _ in range(10):
        x[4] ^= _rotl((x[0] + x[12]) & _M32, 7)
        x[8] ^= _rotl((x[4] + x[0]) & _M32, 9)
        x[12] ^= _rotl((x[8] + x[4]) & _M32, 13)
        x[0] ^= _rotl((x[12] + x[8]) & _M32, 18)
        x[9] ^= _rotl((x[5] + x[1]) & _M32, 7)
        x[13] ^= _rotl((x[9] + x[5]) & _M32, 9)
        x[1] ^= _rotl((x[13] + x[9]) & _M32, 13)
        x[5] ^= _rotl((x[1] + x[13]) & _M32, 18)
        x[14] ^= _rotl((x[10] + x[6]) & _M32, 7)
        x[2] ^= _rotl((x[14] + x[10]) & _M32, 9)
        x[6] ^= _rotl((x[2] + x[14]) & _M32, 13)
        x[10] ^= _rotl((x[6] + x[2]) & _M32, 18)
        x[3] ^= _rotl((x[15] + x[11]) & _M32, 7)
        x[7] ^= _rotl((x[3] + x[15]) & _M32, 9)
        x[11] ^= _rotl((x[7] + x[3]) & _M32, 13)
        x[15] ^= _rotl((x[11] + x[7]) & _M32, 18)
        x[1] ^= _rotl((x[0] + x[3]) & _M32, 7)
        x[2] ^= _rotl((x[1] + x[0]) & _M32, 9)
        x[3] ^= _rotl((x[2] + x[1]) & _M32, 13)
        x[0] ^= _rotl((x[3] + x[2]) & _M32, 18)
        x[6] ^= _rotl((x[5] + x[4]) & _M32, 7)
        x[7] ^= _rotl((x[6] + x[5]) & _M32, 9)
        x[4] ^= _rotl((x[7] + x[6]) & _M32, 13)
        x[5] ^= _rotl((x[4] + x[7]) & _M32, 18)
        x[11] ^= _rotl((x[10] + x[9]) & _M32, 7)
        x[8] ^= _rotl((x[11] + x[10]) & _M32, 9)
        x[9] ^= _rotl((x[8] + x[11]) & _M32, 13)
        x[10] ^= _rotl((x[9] + x[8]) & _M32, 18)
        x[12] ^= _rotl((x[15] + x[14]) & _M32, 7)
        x[13] ^= _rotl((x[12] + x[15]) & _M32, 9)
        x[14] ^= _rotl((x[13] + x[12]) & _M32, 13)
        x[15] ^= _rotl((x[14] + x[13]) & _M32, 18)
    return x


def _state(key, nonce8, counter):
    k = [int.from_bytes(key[i:i + 4], "little") for i in range(0, 32, 4)]
    n = [int.from_bytes(nonce8[i:i + 4], "little") for i in range(0, 8, 4)]
    return [_SIGMA[0], k[0], k[1], k[2],
            k[3], _SIGMA[1], n[0], n[1],
            counter & _M32, (counter >> 32) & _M32, _SIGMA[2], k[4],
            k[5], k[6], k[7], _SIGMA[3]]


def salsa20_stream(key, nonce8, length):
    out = bytearray()
    counter = 0
    while len(out) < length:
        st = _state(key, nonce8, counter)
        s = _rounds(list(st))
        out += b"".join(((s[i] + st[i]) & _M32).to_bytes(4, "little") for i in range(16))
        counter += 1
    return bytes(out[:length])


def hsalsa20(key, in16):
    k = [int.from_bytes(key[i:i + 4], "little") for i in range(0, 32, 4)]
    i4 = [int.from_bytes(in16[i:i + 4], "little") for i in range(0, 16, 4)]
    st = [_SIGMA[0], k[0], k[1], k[2],
          k[3], _SIGMA[1], i4[0], i4[1],
          i4[2], i4[3], _SIGMA[2], k[4],
          k[5], k[6], k[7], _SIGMA[3]]
    out = _rounds(list(st))
    return b"".join(out[i].to_bytes(4, "little") for i in (0, 5, 10, 15, 6, 7, 8, 9))


def _poly1305(msg, key):
    r = int.from_bytes(key[:16], "little") & 0x0ffffffc0ffffffc0ffffffc0fffffff
    s = int.from_bytes(key[16:32], "little")
    p = (1 << 130) - 5
    acc = 0
    for i in range(0, len(msg), 16):
        acc = ((acc + int.from_bytes(msg[i:i + 16] + b"\x01", "little")) * r) % p
    return ((acc + s) % (1 << 128)).to_bytes(16, "little")


def _beforenm(pk, sk):
    return hsalsa20(x25519(sk, pk), bytes(16))


def box_easy(msg, nonce24, pk, sk):
    key = _beforenm(pk, sk)
    sub = hsalsa20(key, nonce24[:16])
    stream = salsa20_stream(sub, nonce24[16:24], len(msg) + 32)
    poly_key, keystream = stream[:32], stream[32:]
    ct = bytes(a ^ b for a, b in zip(msg, keystream))
    return _poly1305(ct, poly_key) + ct


def box_open_easy(box, nonce24, pk, sk):
    key = _beforenm(pk, sk)
    sub = hsalsa20(key, nonce24[:16])
    stream = salsa20_stream(sub, nonce24[16:24], len(box) - 16 + 32)
    poly_key, keystream = stream[:32], stream[32:]
    tag, ct = box[:16], box[16:]
    if _poly1305(ct, poly_key) != tag:
        raise ValueError("MAC 校验失败")
    return bytes(a ^ b for a, b in zip(ct, keystream))


CLIENT_SK = None  # 延迟初始化, 见 _client_sk()


def _client_sk():
    global CLIENT_SK
    if CLIENT_SK is None:
        CLIENT_SK = bytes.fromhex(CLIENT_SK_HEX)
    return CLIENT_SK


def decrypt_body(body_b64, nonce_b64, server_pk_hex=None):
    """把一段密文 body 还原成明文 str.

    body_b64      : 抓到的 body (base64), 允许带换行/空白
    nonce_b64     : 请求用 x-client-nonce, 响应用 x-server-nonce
    server_pk_hex : 服务端公钥 hex. 请求可不填(用内置默认值);
                    响应应传 x-server-pubkey
    """
    pk = bytes.fromhex(server_pk_hex or SERVER_PK_HEX)
    sealed = base64.b64decode("".join(body_b64.split()))
    nonce = base64.b64decode("".join(nonce_b64.split()))
    if len(nonce) != 24:
        raise ValueError("nonce 解出 %d 字节, 应为 24" % len(nonce))
    return box_open_easy(sealed, nonce, pk, _client_sk()).decode("utf-8")


def decrypt_request(text, nonce_b64=None, server_pk_hex=None):
    """请求密文 -> 明文. 支持三种输入:

        decrypt_request(整段 curl)                       # Charles "Copy cURL Request"
        decrypt_request(整段请求文本, 含 x-client-nonce 行)
        decrypt_request(密文, "YbdF3yVgH1j3W/...")       # 手工给 nonce

    自动识别, 自动跳过密文里的空格和换行。
    """
    headers = {}
    body = None

    if text.lstrip().lower().startswith("curl"):
        headers, body = _parse_curl(text)
        nonce_b64 = nonce_b64 or headers.get("x-client-nonce") or headers.get("x-server-nonce")
    else:
        nonce_b64 = nonce_b64 or _find_nonce(text, "x-client-nonce") \
            or _find_nonce(text, "x-server-nonce")
        body = _find_body(text)

    if not nonce_b64:
        raise ValueError(
            "找不到 x-client-nonce。请求密文必须配合请求头里的 x-client-nonce 才能解, "
            "请把那一行一起贴进来, 或者用 nonce_b64 参数传入")

    pk = server_pk_hex or headers.get("x-server-pubkey")
    return decrypt_body(body, nonce_b64, pk)


def _parse_curl(text):
    """解析 Charles 的 Copy cURL Request, 返回 (headers, body)。"""
    import shlex

    try:
        parts = shlex.split(text.replace("\\\n", " "))
    except ValueError:
        parts = text.split()
    headers, body = {}, None
    i = 0
    while i < len(parts):
        p = parts[i]
        if p in ("-H", "--header") and i + 1 < len(parts):
            k, _, v = parts[i + 1].partition(":")
            headers[k.strip().lower()] = v.strip()
            i += 2
            continue
        if p in ("-d", "--data", "--data-binary", "--data-raw", "--data-ascii") and i + 1 < len(parts):
            body = parts[i + 1]
            i += 2
            continue
        i += 1
    return headers, "".join((body or "").split())


def _find_nonce(text, name):
    m = re.search(name + r"\s*:\s*([A-Za-z0-9+/=]+)", text, re.I)
    return m.group(1) if m else None


def _find_body(text):
    """从粘贴内容里取出 body; 没有头就整段当 body。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if "\n\n" in text:
        _, _, body = text.partition("\n\n")
    else:
        # 逐行找最像 base64 的那一段 (跳过 header 行)
        lines = [ln for ln in text.split("\n") if ln and ":" not in ln]
        body = "\n".join(lines) if lines else text
    return "".join(body.split())


# ================================================================


def send_request(params=None):
    params = params if params is not None else PARAMS
    sk = bytes.fromhex(CLIENT_SK_HEX)
    plaintext = json.dumps(params, ensure_ascii=False, separators=(",", ":"))
    nonce = os.urandom(24)
    body_b64 = base64.b64encode(
        box_easy(plaintext.encode("utf-8"), nonce, bytes.fromhex(SERVER_PK_HEX), sk)).decode()

    headers = dict(HEADERS)
    headers["x-client-nonce"] = base64.b64encode(nonce).decode()
    headers["x-client-pubkey"] = CLIENT_PK_HEX

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(URL, data=body_b64.encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            status = resp.status
            resp_body = resp.read().decode("utf-8", "replace")
            resp_nonce = resp.headers.get("x-server-nonce")
            resp_pk = resp.headers.get("x-server-pubkey")
    except urllib.error.HTTPError as exc:
        print("HTTPError %s: %s" % (exc.code, exc.read().decode("utf-8", "replace")[:200]),
              file=sys.stderr)
        return 1

    print("HTTP %s" % status)
    if SHOW_CIPHERTEXT:
        print("\n[1] 入参明文:\n%s" % plaintext)
        print("\n[2] 加密后 body:\n%s" % body_b64)
        print("\n[3] x-client-nonce: %s" % headers["x-client-nonce"])

    if not resp_nonce:
        print("\n[4] 响应未加密:\n%s" % resp_body)
        return 0

    if SHOW_CIPHERTEXT:
        print("\n[4] 响应密文(前80): %s..." % resp_body[:80])
        print("[5] x-server-nonce: %s" % resp_nonce)
        print("[6] x-server-pubkey: %s" % resp_pk)

    plain = box_open_easy(
        base64.b64decode(resp_body),
        base64.b64decode(resp_nonce),
        bytes.fromhex(resp_pk or SERVER_PK_HEX),
        sk).decode("utf-8")

    print("\n[7] 响应明文:")
    try:
        print(json.dumps(json.loads(plain), ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print(plain)
    return 0


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(
        description="AeonBuy 加解密工具: 默认发加密请求; 传 --decrypt/--file 则只解密",
        epilog=(
            "常用示例:\n"
            "  python run_pure.py --file capture_curl.txt\n"
            "  python run_pure.py --file capture_curl.txt --send\n"
            "  python run_pure.py\n"
            "  python run_pure.py --decrypt \"<密文>\" --nonce \"<x-client-nonce>\"\n"
            "\n"
            "capture_curl.txt 里放 Charles 的 'Copy cURL Request' 全文即可,\n"
            "脚本会自动提取 x-client-nonce 和密文。\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--decrypt", metavar="BODY_B64",
                    help="要解密的密文 body (base64); 传 - 从 stdin 读")
    ap.add_argument("--file", metavar="PATH", help="从文件读密文 body")
    ap.add_argument("--nonce", metavar="B64",
                    help="请求用 x-client-nonce; 响应用 x-server-nonce")
    ap.add_argument("--pubkey", metavar="HEX",
                    help="服务端公钥; 解响应时传 x-server-pubkey, 否则用内置默认值")
    ap.add_argument("--raw", action="store_true", help="原样输出, 不美化 JSON")
    ap.add_argument("--send", action="store_true",
                    help="解密后直接用解出的明文发一次请求")
    a = ap.parse_args(argv)

    # ---- 解密模式 ----
    if a.decrypt is not None or a.file:
        if a.file:
            with open(a.file, "r", encoding="utf-8-sig") as fh:
                text = fh.read()
        elif a.decrypt == "-":
            text = sys.stdin.read()
        else:
            text = a.decrypt
        try:
            plain = decrypt_request(text, a.nonce, a.pubkey)
        except Exception as exc:
            print("解密失败: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
            return 1
        if a.raw:
            print(plain)
        else:
            try:
                print(json.dumps(json.loads(plain), ensure_ascii=False, indent=2))
            except json.JSONDecodeError:
                print(plain)

        if a.send:
            print("\n=== 用解出的明文重新发请求 ===")
            return send_request(json.loads(plain))
        return 0

    # ---- 默认: 发请求 ----
    return send_request()


if __name__ == "__main__":
    sys.exit(main())