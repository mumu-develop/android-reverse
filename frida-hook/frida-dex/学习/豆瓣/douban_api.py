"""豆瓣 frodo API 客户端 — _sig 算法已还原并验证。

_sig = base64( HMAC-SHA1( key="bf7dddc7c9cfe6f7",
                          msg = "METHOD&urlencode(path)&_ts" ) )

注意：签名只跟 **方法 + 路径 + _ts** 有关，跟 query 参数无关。
"""

import base64
import hashlib
import hmac
import time
import urllib.parse
import urllib.request

KEY = "bf7dddc7c9cfe6f7"
APIKEY = "0dad551ec0f84ed02907ff5c42e8ec70"
HOST = "https://frodo.douban.com"

UDID = "144cb63932af0ee9b809b85cdfaa49d5d097e17b"
DOUBAN_UDID = "26d025c51187d7f7d0330d6d3a3f4cbd3017cf02"


def make_sig(method: str, path: str, ts: str) -> str:
    msg = "%s&%s&%s" % (method.upper(), urllib.parse.quote(path, safe=""), ts)
    digest = hmac.new(KEY.encode(), msg.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def user_agent() -> str:
    return (
        "api-client/1 com.douban.frodo/7.136.0(365) Android/28 "
        " udid/%s  douban_udid/%s model/25102RKBEC brand/REDMI "
        " rom/android  network/wifi  platform/mobile  foldable/0 nd/1 "
        "product/25102RKBEC vendor/REDMI" % (UDID, DOUBAN_UDID)
    )


def request(path: str, params: dict = None, method: str = "GET", timeout=15) -> str:
    ts = str(int(time.time()))
    q = dict(params or {})
    q.update({
        "apikey": APIKEY,
        "_ts": ts,
        "_sig": make_sig(method, path, ts),
        "udid": UDID,
        "douban_udid": DOUBAN_UDID,
        "os_rom": "android",
        "channel": "ali_market",
        "timezone": "Asia/Shanghai",
    })
    url = HOST + path + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={
        "Host": "frodo.douban.com",
        "User-Agent": user_agent(),
    }, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


if __name__ == "__main__":
    # 先做一次离线自检：用抓包里的样本验证算法
    sample = make_sig("GET", "/api/v2/home_banner", "1793457533")
    print("自检:", sample, "->", "OK" if sample == "uIQ1hNHPnblknHhqQoJAxpguhHk=" else "FAIL")

    body = request("/api/v2/home_banner", {"count": "1", "tab": "rec"})
    print("HTTP OK, %d bytes" % len(body))
    print(body[:400])
