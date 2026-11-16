"""dachuan (达川观察) API client — sign 已还原。

sign = MD5( MD5( MD5(certDER.toCharsString()) ).upper()
            + account + token + timestamp ).upper()

其中：
  - certDER.toCharsString() = 签名证书 DER 的小写十六进制
  - appSign = MD5(那串hex).upper()        （Java 侧 LogShutDown.getAppSign）
  - stage1  = MD5(appSign).upper()        （libwtf 的第一段）
  - sign    = MD5(stage1 + account + token + timestamp).upper()
"""
import hashlib
import json
import time
import urllib.request
import uuid

HOST = "https://rmt-api.dachuan.org.cn"
APPSIGN = "A262FA6ED59F60E49FD49E205F68426D"   # 该 APK 的证书指纹（已从 META-INF/DACHUAN.RSA 验证）
CHANNEL = "yingyongbao_1025"
VNO = "1.3.0"


def make_sign(account: str, token: str, ts: str, app_sign: str = APPSIGN) -> str:
    stage1 = hashlib.md5(app_sign.encode()).hexdigest().upper()
    return hashlib.md5((stage1 + account + token + ts).encode()).hexdigest().upper()


def build_entity(payload: dict, deviceid: str, token: str = "") -> dict:
    account = str(uuid.uuid4())
    ts = str(int(time.time() * 1000))
    return {
        "data": json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        "vno": VNO,
        "app_vno": VNO,
        "sign": make_sign(account, token, ts),
        "channel": CHANNEL,
        "client": "android",
        "teen_mode": "0",
        "switch_suggest": "1",
        "deviceid": deviceid,
        "account": account,
        "timestamp": ts,
        "token": token,
    }


def post(path: str, params: dict, timeout=20):
    body = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        HOST + path,
        data=body,
        headers={
            "User-Agent": "covermedia-android",
            "tenantId": "15",
            "fmio_token": "",
            "fmio_appid": "",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


if __name__ == "__main__":
    import urllib.parse

    payload = {
        "ad_id": 0, "operation_type": 0, "page": 1, "channel_type": 1,
        "channel_id": 9, "news_id": 64755, "list_style": 1, "page_size": 16,
        "lastUpdateTime": "2026-10-31 14:58:53",
    }
    ent = build_entity(payload, deviceid="ac31ba23-9db9-33ec-bfcc-b8efafd51d46-EAPE")
    print("account  :", ent["account"])
    print("timestamp:", ent["timestamp"])
    print("sign     :", ent["sign"])
    try:
        code, text = post("/getList", ent)
        print("HTTP", code)
        print(text[:600])
    except Exception as e:
        print("request failed:", type(e).__name__, e)
