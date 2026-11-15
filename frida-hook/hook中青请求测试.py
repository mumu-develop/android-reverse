import hashlib
import random
import json
import base64
import time
import urllib.parse
import requests
from Crypto.Cipher import DES, AES
from Crypto.Util.Padding import pad, unpad


# ==================== 常量 ====================
S_PUBLIC_KEY = "6HPjSZFH8RLv4dBj0YlmC2wFUySX"
SIGN_SALT = "jdvylqchJZrfw0o2DgAbsmCGUapF1YChc"   # 自检通过后确认
CHARS = list("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")


# ==================== 工具 ====================
def java_url_encode(s: str) -> str:
    """对齐 Java URLEncoder.encode"""
    return urllib.parse.quote_plus(s, safe="*").replace("~", "%7E")


def make_sign(m: dict) -> str:
    """i=1~5 分支：排序 → 拼 key=value → + 盐 → MD5"""
    sb = "".join(
        f"{k}={m[k]}"
        for k in sorted(m.keys())
        if m[k] is not None and len(str(m[k])) > 0
    )
    return hashlib.md5((sb + SIGN_SALT).encode("utf-8")).hexdigest()


def encrypt_des(key: str, plain: str) -> str:
    """对齐 Java encryptDES：DES/CBC/PKCS5，IV=base64(MD5(key)[:8])[:8]"""
    key_bytes = key.encode("utf-8")
    str3 = base64.urlsafe_b64encode(hashlib.md5(key_bytes).digest()[:8]).decode("ascii")
    iv = str3[:8].encode("ascii")
    cipher = DES.new(key_bytes[:8], DES.MODE_CBC, iv)
    ct = cipher.encrypt(pad(plain.encode("utf-8"), 8))
    return str3 + base64.urlsafe_b64encode(ct).decode("ascii")


def get_random_code() -> str:
    return random.choice(CHARS)


def get_disturb_string(s: str, c: str) -> str:
    n = (ord(c) % 10) % 3
    result = c + s
    for _ in range(n):
        result += random.choice(CHARS)
    return result


def build_zqkd_param(params: dict):
    """完整链路：sign → 明文 → DES → 混淆"""
    # 1. 算 sign
    sign = make_sign(params)
    params["sign"] = sign

    # 2. 拼明文（插入顺序，value 做 URL 编码）
    parts = []
    for k, v in params.items():
        if v is None or len(str(v)) == 0:
            continue
        if parts:
            parts.append("&")
        parts.append(f"{k}={java_url_encode(str(v))}")
    plain = "".join(parts)

    # 3. DES 加密
    encrypted = encrypt_des(S_PUBLIC_KEY, plain)

    # 4. 混淆（随机前缀 + 尾部 0~2 填充）
    random_code = get_random_code()
    return get_disturb_string(encrypted, random_code), sign


def decrypt_response(text: str) -> str:
    """响应解密：AES-ECB，key = sPublicKey[:16]"""
    key = S_PUBLIC_KEY[:16].encode("utf-8")
    cipher = AES.new(key, AES.MODE_ECB)
    return unpad(cipher.decrypt(base64.b64decode(text)), AES.block_size).decode("utf-8")


# ==================== 参数（按 hook 顺序）====================
def make_params():
    return {
        "ab_client": "",
        "ab_feature": "",
        "ab_version": "",
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
        "jssdk_version": "",
        "language": "zh-CN",
        "memory": "5",
        "mi": "0",
        "mobile_type": "1",
        "network_type": "WIFI",
        "oaid": "",
        "openudid": "f3218b338c7a6a7b",
        "os_api": "28",
        "os_version": "PQ3A.190605.07291804 release-keys",
        "phone_sim": "1",
        "request_time": str(int(time.time())),   # 动态
        "resolution": "1440x2560",
        "rom_version": "PQ3A.190605.07291804 release-keys",
        "s_ad": "J2JgR8oZr6IU=d2EEVsXyxbZKEjtuMZRp20VL--z2qRpWN",
        "s_im": "b2JgR8oZr6IU=IpLXM152lGc43RTM7NbiBA==HD",
        "sim": "1",
        "sm_device_id": "2026091521132251a4a94a6dbff095cd90132580c16e5e01d5668fc49199df",
        "storage": "49.32",
        "uid": "101677591",
        "version_code": "74",
        "zqkey": "MDAwMDAwMDAwMJCMpN-w09Wtg5-Bb36eh6CPqHualq2jm7Caraqwp3lrhbKYl7C5ppyDaIFvhHSgmY68hM6LZobWw4i5m7KVn2-EjJiasLm2ZYOJhW2EdKVp",
        "zqkey_id": "a3a07f54221e3af2e7640fbbe834c16e",
        "catid": "0",
        "op": "0",
        "behot_time": "0",
        "oid": "0",
        "video_catid": "1453",
    }


# ==================== 主流程 ====================
if __name__ == "__main__":
    params = make_params()
    zqkd, sign = build_zqkd_param(params)
    print(f"sign       = {sign}")
    print(f"zqkd_param = {zqkd}")

    url = "https://kandian.wkandian.com/v3/article/lists.json"
    headers = {
        "device-platform": "android",
        "Host": "kandian.wkandian.com",
        "User-Agent": "okhttp/3.12.2",
    }
    resp = requests.get(url, headers=headers, params={"zqkd_param": zqkd})
    print(f"status = {resp.status_code}")
    print(f"body   = {resp.text[:300]}")

    try:
        result = decrypt_response(resp.text)
        print(json.dumps(json.loads(result), ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"decrypt failed: {e}")