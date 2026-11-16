#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中青看点 (kandian.wkandian.com) app-api 加解密客户端.

逆向自 中青看点.apk 4.0.0：
  cn.youth.news.basic.network.impl.YouthApiHelper
    ├─ encrypt(String)                  -> ("zqkd_param", 密文)
    ├─ getSecurityParamsByDes(String)   -> DES + 打乱
    └─ signature(Map, version)          -> sign
  cn.youth.news.basic.utils.PubKeySignature      -> 证书派生密钥 / AES 解响应
  cn.youth.news.basic.utils.YouthSecurityHelper  -> DES/CBC/PKCS5
  cn.youth.news.basic.utils.RandomValidateCode   -> 随机前缀字符
  libencrypt.so : NativeEncrypt.version2Key()    -> sign 的盐

链路：
  入参 map
    → 按 key 排序，拼 "k=v"（无分隔符）+ version2Key → MD5        = sign
    → 加进 map，拼 "k=v&k=v"（值 URL 编码）                      = 明文
    → DES/CBC/PKCS5(key=base36[:8], iv=urlsafe_b64(md5(base36))[:8])
    → 前缀随机字符 + urlsafe_b64(md5后8字节) + urlsafe_b64(密文)  = zqkd_param

  响应: AES/ECB/PKCS5(key=base36[:16])，base64 解码

用法:
    python zqkd_api.py
"""
import base64
import hashlib
import json
import os
import random
import ssl
import sys
import time
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives.ciphers import Cipher, modes
from cryptography.hazmat.primitives.ciphers.algorithms import AES

BASE = "https://kandian.wkandian.com"

# ---------------------------------------------------------------------------
# 1) 从 APK 签名证书派生的 36 字符 base36
#    PubKeySignature.parseSignature():
#      b64 = Base64(pubKey.getEncoded())
#      b64 = b64[9:] -> b64[:-5] -> 取最后 36 个字符
# ---------------------------------------------------------------------------
BASE36 = "6HPjSZFH8RLv4dBj0YlmC2wFUySXrwkcloQI"

# 2) libencrypt.so 里 NativeEncrypt.version2Key() 的返回值
SIGN_KEY = "jdvylqchJZrfw0o2DgAbsmCGUapF1YChc"

# 3) 响应解密密钥 = getSingInfo(app,'a').substring(0,16)
RESP_KEY = BASE36[:16].encode()

# 4) 打乱用的字符表 (RandomValidateCode.chars)
CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

HEADERS = {
    "device-platform": "android",
    "User-Agent": "okhttp/3.12.2",
}

# ---------------------------------------------------------------------------
# 公共参数（取自真实抓包；device 相关字段服务端只做弱校验，保持原样即可）
# ---------------------------------------------------------------------------
COMMON = {
    "access": "WIFI",
    "app-version": "4.0.0",
    "app_name": "zqkd_app",
    "app_version": "4.0.0",
    "carrier": "CHINA MOBILE",
    "channel": "c4015",
    "device_brand": "REDMI",
    "device_id": "96198035",
    "device_model": "25102RKBEC",
    "device_platform": "android",
    "device_type": "android",
    "dpi": "640",
    "inner_version": "202203070952",
    "language": "zh-CN",
    "memory": "5",
    "mi": "0",
    "mobile_type": "1",
    "network_type": "WIFI",
    "openudid": "f3218b338c7a6a7b",
    "os_api": "28",
    "os_version": "PQ3A.190605.07291804 release-keys",
    "phone_sim": "1",
    "request_time": "1793204394",
    "resolution": "1440x2560",
    "rom_version": "PQ3A.190605.07291804 release-keys",
    "s_ad": "1YdVi_XPUOzA=s65xgKISvEkiT84iOeiyCoFb-npvtXXr",
    "s_im": "pYdVi_XPUOzA=wuUJ7qSBa0xilZ6XRKEg6A==vP",
    "sim": "1",
    "sm_device_id": "2026091521132251a4a94a6dbff095cd90132580c16e5e01d5668fc49199df",
    "storage": "49.32",
    "uid": "101677591",
    "version_code": "74",
    "zqkey": "MDAwMDAwMDAwMJCMpN-w09Wtg5-Bb36eh6CPqHualq2jm7Caraqwp3lrhbKYl7C5ppyDaIFvhHSgmY68hM6LZobWw4i5m7KVn2-EjJibrt-mq4Gvm7ODhKVp",
    "zqkey_id": "93aad56b181e89097bf63068c438b1c7",
    "catid": "20008",
    "op": "1",
    "behot_time": "1793203875164",
    "video_catid": "1453",
    "sign": "e2f99ba540dc893c6427ad821ab16eb4",
}

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------------------
# 签名
# ---------------------------------------------------------------------------
def make_sign(params: dict) -> str:
    """sign = MD5( 排序后 k=v 直接拼接（无分隔符） + version2Key )"""
    s = "".join("%s=%s" % (k, params[k]) for k in sorted(params)
                if k != "sign" and str(params[k]) != "")
    return hashlib.md5((s + SIGN_KEY).encode()).hexdigest()


# ---------------------------------------------------------------------------
# 入参加密
# ---------------------------------------------------------------------------
def _pkcs5_pad(data: bytes, block: int = 8) -> bytes:
    n = block - len(data) % block
    return data + bytes([n]) * n


def decrypt_param(param: str) -> str:
    """zqkd_param -> 明文 query string（自动试出密钥长度、自动去掉尾部填充字符）"""
    param = "".join(param.split())
    ch, rest = param[0], param[1:]
    md5_seg, ct_b64 = rest[:12], rest[12:]

    key = None
    for k in range(10):
        cand = BASE36[: 36 - k]
        if base64.urlsafe_b64encode(hashlib.md5(cand.encode()).digest()[:8]).decode() == md5_seg:
            key = cand
            break
    if key is None:
        raise ValueError("md5 段与任何密钥长度都不匹配，可能 base36 不对（证书换过？）")

    from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
    iv = md5_seg[:8].encode()

    last_err = None
    for trim in range(3):                       # 尾部可能有 0~2 个随机字符
        body = ct_b64[: len(ct_b64) - trim] if trim else ct_b64
        try:
            raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
            if len(raw) % 8:
                continue
            dec = Cipher(TripleDES(key[:8].encode() * 3), modes.CBC(iv)).decryptor()
            plain = dec.update(raw) + dec.finalize()
            pad = plain[-1]
            if 0 < pad <= 8:
                plain = plain[:-pad]
            return plain.decode("utf-8")
        except Exception as exc:                 # noqa: BLE001
            last_err = exc
    raise ValueError("DES 解密失败: %s" % last_err)


def encrypt_param(plain: str) -> str:
    """明文 query string -> zqkd_param"""
    ch = random.choice(CHARS)
    key = BASE36[: 36 - (ord(ch) % 10)]          # 服务端按首字符还原同样长度
    iv = base64.urlsafe_b64encode(hashlib.md5(key.encode()).digest()[:8]).decode()[:8].encode()

    from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
    enc = Cipher(TripleDES(key[:8].encode() * 3), modes.CBC(iv)).encryptor()
    raw = enc.update(_pkcs5_pad(plain.encode())) + enc.finalize()

    md5_part = base64.urlsafe_b64encode(hashlib.md5(key.encode()).digest()[:8]).decode()
    body = base64.urlsafe_b64encode(raw).decode()

    pad_len = (ord(ch) % 10) % 3
    return ch + md5_part + body + "".join(random.choice(CHARS) for _ in range(pad_len))


# ---------------------------------------------------------------------------
# 响应解密
# ---------------------------------------------------------------------------
def decrypt_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("{"):                      # 未加密
        return json.loads(text)
    raw = base64.b64decode(text + "=" * (-len(text) % 4))
    dec = Cipher(AES(RESP_KEY), modes.ECB()).decryptor()
    plain = dec.update(raw) + dec.finalize()
    pad = plain[-1]
    if 0 < pad <= 16:
        plain = plain[:-pad]
    return json.loads(plain.decode("utf-8"))


# ---------------------------------------------------------------------------
# 请求
# ---------------------------------------------------------------------------
def call(path: str, params: dict = None, timeout: int = 25) -> dict:
    merged = dict(COMMON)
    if params:
        merged.update({k: str(v) for k, v in params.items()})
    merged["request_time"] = str(int(time.time()))
    merged["sign"] = make_sign(merged)

    plain = "&".join("%s=%s" % (k, urllib.parse.quote_plus(str(v)))
                     for k, v in merged.items())
    url = BASE + path + "?zqkd_param=" + encrypt_param(plain)

    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
        return decrypt_response(resp.read().decode("utf-8", "replace"))


def main():
    data = call("/v3/article/lists.json", {"catid": "20008", "op": "0", "behot_time": "0", "oid": "0"})
    print(json.dumps({k: data[k] for k in ("success", "message", "count") if k in data},
                     ensure_ascii=False, indent=2))
    for it in data.get("items", [])[:3]:
        print("-", it.get("id"), it.get("title")[:40], "| cmt", it.get("cmt_num"))


if __name__ == "__main__":
    plain = decrypt_param("LYdVi_XPUOzA=cmEU2wd-Oc7Ne4apw1WrWujGkpodE-ali3LriI_3CUsbRE_85-fWvvjL_7kT0JI-WFkZakMEukUwuk2cEW6MTxtBn6RNxUkWkuivVHFuLcWk5y2djViVJIpDbO1pftSiZpXK3c5QnACRXz0Htki2PaCxxM8v5dwTnzOs5AnsWNckqhFKh-W9jgCKghDTPvuDp-U2R2GNX0uOvmtPFvO8kKn1n0cqxQyT2f8VENd_lANFAdb6VzJkj-AJqfyQBjYy3UbsZiZox8_LohTjzOHnC1voorzpUZoogvnTPQYyOS7239lu_fa-TgQ_I4KNTclz8fSY6E1kGd8ZlVA_XRTT2jOOFI8qNNrOMZINoDOyT5cRHzHQ4TQ-ky6llw_GY-aZeEPO_dd8PAmVvhvQYhTrgj3mhTBMAljBdZB7sNO85DGwzfH5gLN0LAqNZg0tT0HAF1e6xjoOybzUp72rjgzbFhPtBmMCYy93qg2uWOJfuNcvOxbk1G7h0ZBh2xrxkXO5f6DLbTPh6uaXUoe7vSQY4DRWvhOzHyO4PD5_ebxIgf0ludtGxU4VqQbIhcsHUxZgNo3CuK9waQ95M-5e2C6-E99Ef5_yNdyAPqKUE8lg8XGHeSoWwc4l2J6ERVdfNcuTPRz7XQUT-uHCki2iB8W28MDJiQJ3noEuli4thDYwwa7jYp-nMIN4kLzRYjMR3q74uJMHHEAL6swf3FuuqPMvxuHbRTaJ5cSjM2VmrdZ0SPRPCbikK871sIJeCUogjZpKgSvgfvGo13rrJeT5rRbuxyeh6LQfE2KCCW2ZpNlH60VhxhofgQdzFaTBfFWiRZVx2fuEHBMNlWvGRHvPhs-LjnXmBA2bP_J_y2ajT9Lj8eJQi4nWQ-w3-uNYcCg9rVtXrwvX9gqDI1ekOThE9ViTdQTPGCpZrmv6kT9DEyklv0AnKaVqaV4XdwBZddZ8OqEaRs57DemCCIvmyidpNytErqmb902DIe5tWVz94tOSrfbMimEVYBjhGIrHDib_h3bLBNu22n043dqPFSp_KXvHS4FvRASpIAf4VbCSiF81ni4f0UbQzTSvUup0LI6w-GKco38Gx7Qhuy4nEv7Wq0qNDnKYtNUcldQymeSVc1APPbWQJ0pnKNtgGxs1C5QRcKmJQZCcJdSqqruJwJXIRnylYHF81sViKgIe8zTsmuJ1LXWAtS4slJWFNXqYTcIaJ_azxNob0YeD5RKdDomFyrhUzRE-08Dudm6p7f0JzsKaiUQ51Q2x0DQJjz-ESLrfGjC2F3XCGZQuWOOUPD2N7eGokukBzs4wU9DSDNadwJ-vQ58=")
    print(plain)
    sys.exit(main())