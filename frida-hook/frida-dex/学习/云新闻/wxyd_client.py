"""云新闻 getList 接口客户端（sign 已还原并验证）"""
import gzip, hashlib, json, time, urllib.parse, urllib.request, uuid

APP_SIGN = "71418DA91E43A6F8C811F57A35CD744B"
BASE_URL = "https://ynrb-api.yndaily.com"

FMIO_TOKEN = ("eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9."
              "eyJ1aWQiOiIyMTMxIiwidW5hbWUiOiJ5bnJiIiwiYXBwS2V5IjoiY1NFUjVwQnVsS0N1Wko5IiwiYXBwU2VjcmV0IjoiTlR6VnBURzd4bFMzV2FYIiwiaWF0IjoxNzAyOTcxMzk5fQ."
              "b6WMbSaekVYf8FTENOtUy_pjWqBcZpdMGqbCbIO45ss")


def md5u(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest().upper()


def make_sign(account: str, token: str, timestamp: str) -> str:
    return md5u(md5u(APP_SIGN) + account + token + timestamp)


def get_list(page: int = 1, page_size: int = 16, channel_id: int = 9,
             news_id: int = 3065891, last_update: str = "2026-11-08 18:00:53",
             deviceid: str = "ac31ba23-9db9-33ec-bfcc-b8efafd51d46-EAPE"):
    account = str(uuid.uuid4())                  # 每次请求随机 UUID
    token = ""                                   # 未登录为空
    timestamp = str(int(time.time() * 1000))     # 毫秒
    sign = make_sign(account, token, timestamp)

    payload = {
        "ad_id": 0, "operation_type": 0, "last_video_id": 0,
        "page": page, "channel_type": 1, "channel_id": channel_id,
        "news_id": news_id, "list_style": 2, "page_size": page_size,
        "lastUpdateTime": last_update,
    }
    fields = [
        ("switch_suggest", "1"),
        ("data", json.dumps(payload, separators=(",", ":"), ensure_ascii=False)),
        ("vno", "7.1.4"),
        ("sign", sign),
        ("channel", "huaweiyingyongzhongxin_517"),
        ("client", "android"),
        ("teen_mode", "0"),
        ("app_vno", "7.1.4"),
        ("deviceid", deviceid),
        ("account", account),
        ("timestamp", timestamp),
        ("token", token),
    ]
    body = urllib.parse.urlencode(fields).encode()

    req = urllib.request.Request(
        BASE_URL + "/getList", data=body, method="POST",
        headers={
            "User-Agent": "covermedia-android",
            "tenantId": "35",
            "fmio_token": FMIO_TOKEN,
            "fmio_appid": "rmt_yunnan",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Encoding": "gzip",
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 强制直连，绕过环境代理
    with opener.open(req, timeout=20) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return r.status, raw.decode("utf-8", "replace")


if __name__ == "__main__":
    status, text = get_list()
    print("HTTP", status, " len=", len(text))
    print(text[:600])
