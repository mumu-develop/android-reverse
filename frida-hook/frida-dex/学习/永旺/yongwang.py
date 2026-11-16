#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""直接跑就行: 入参写死在这个文件里, 用明文通道(不需要加密).

python run_request.py
"""
import json
import ssl
import urllib.request

URL = "https://delivery.aeonbuy.com/api/app-api/delivery/search/categoryProductList"

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

HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "x-http-encryption": "0",
    "x-http-channel": "app",
    "x-http-devicetype": "android",
    "x-http-locale": "zh-cn",
    "x-http-version": "2.3.72",
    "x-http-osversion": "9",
    "x-http-vendortype": "REDMI",
    "x-http-deviceuid": "1104a89793fd854c51a",
    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; 25102RKBEC Build/PQ3A.190605.07291804)",
}


def main():
    body = json.dumps(PARAMS, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(URL, data=body, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
        raw = resp.read().decode("utf-8")
        print("HTTP", resp.status)

    data = json.loads(raw)
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()