# -*- coding: utf-8 -*-
"""下载中间件（标准样板）：签名 + UA。

只认 `signer/base.py` 契约，不 import 具体实现 ——
具体策略由 settings.SIGNING_STRATEGY 通过 load_object 注入。

签名是同步 HTTP 调用（几十毫秒），放到 Twisted 线程池里做，
避免阻塞 reactor；并发上限由 CONCURRENT_REQUESTS 控制。
"""
from __future__ import annotations

import logging

from scrapy import signals
from scrapy.exceptions import IgnoreRequest
from scrapy.utils.misc import load_object
from twisted.internet import threads

log = logging.getLogger(__name__)

UA = "com.ss.android.ugc.aweme/400200 (Linux; U; Android 13; zh_CN; Pixel 6)"


class SignerMiddleware:
    """给每个请求签上六神头。"""

    def __init__(self, signing_strategy) -> None:
        self.strategy = signing_strategy
        self.signed = 0
        self.failed = 0

    @classmethod
    def from_crawler(cls, crawler):
        s = crawler.settings
        strategy_path = s.get("SIGNING_STRATEGY", "douyin_rev.signer.strategy.UnidbgStrategy")
        strategy = load_object(strategy_path)()
        try:
            strategy.warm()
        except Exception as e:  # 服务没起来先告警，请求时会再失败
            log.warning("签名策略 warm 失败: %r", e)
        mw = cls(strategy)
        crawler.signals.connect(mw.on_spider_closed, signal=signals.spider_closed)
        return mw

    # ---------- 中间件钩子 ----------

    def process_request(self, request, spider):
        device = request.meta.get("device") or {}
        url = request.url
        d = threads.deferToThread(self._sign, url, device)
        d.addCallback(lambda headers: self._apply(request, headers))
        d.addErrback(self._on_sign_error, request)
        return d

    def _sign(self, url: str, device: dict):
        headers = self.strategy.sign(url=url, device=device.get("device_id"))
        out = dict(headers)
        out["User-Agent"] = UA
        return out

    def _apply(self, request, headers: dict):
        for k, v in headers.items():
            request.headers[k] = v
        self.signed += 1
        return None

    def _on_sign_error(self, failure, request):
        self.failed += 1
        log.warning("签名失败 %s: %s", request.url[:80], failure.value)
        raise IgnoreRequest("sign failed")

    def on_spider_closed(self, spider, reason=None):
        try:
            self.strategy.close()
        except Exception:
            pass
        log.info("签名统计: 成功=%d 失败=%d", self.signed, self.failed)
