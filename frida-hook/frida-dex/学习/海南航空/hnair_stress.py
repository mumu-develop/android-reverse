# -*- coding: utf-8 -*-
"""
并发压测（curl_cffi 版）：多日期 × 多档并发，观察成功率 / 吞吐 / 是否触发限流。

用法：python hnair_stress.py
"""
import datetime
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from curl_cffi import requests as creq

import hnair_search as H

_tl = threading.local()


def sess():
    """每线程一个 Session，复用连接"""
    if not hasattr(_tl, "s"):
        _tl.s = creq.Session(impersonate=H.IMPERSONATE)
    return _tl.s


BASE_DATE = datetime.date(2026, 11, 20)


def one(index):
    date = (BASE_DATE + datetime.timedelta(days=index)).isoformat()
    t0 = time.time()
    try:
        res, _ = H.fetch("PEK", "SHA", date, session=sess(), with_risk=False)
        n = 0
        if res.get("data"):
            od = (res.get("data") or {}).get("originDestinations") or [{}]
            n = len(od[0].get("airItineraries") or [])
        return dict(ok=bool(res.get("success")), code=res.get("errorCode") or "",
                    n=n, t=time.time() - t0)
    except Exception as e:
        return dict(ok=False, code="EXC:" + type(e).__name__, n=0, t=time.time() - t0)


def wave(concurrency, count=24):
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        rs = list(ex.map(one, range(count)))
    wall = time.time() - t0
    ok = sum(1 for r in rs if r["ok"])
    costs = sorted(r["t"] for r in rs)
    errs = dict(Counter(r["code"] for r in rs if r["code"])) or "无"
    print("并发=%-2d 成功=%2d/%d 墙钟=%5.1fs 吞吐=%.2f req/s p50=%.1fs max=%.1fs 航班=%d 错误=%s"
          % (concurrency, ok, count, wall, count / wall,
             costs[len(costs) // 2], costs[-1], sum(r["n"] for r in rs), errs))
    return rs


if __name__ == "__main__":
    print("航线 PEK->SHA，日期 %s 起 %d 天\n" % (BASE_DATE, 24))
    for c in (4, 8, 16):
        wave(c)
        time.sleep(1)
