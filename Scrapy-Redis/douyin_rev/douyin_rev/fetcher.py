# -*- coding: utf-8 -*-
"""抓取策略契约 + requests 实现（样板为主）。

本站不走浏览器、不需要 cookie，直接 HTTPS GET，
所以 Fetcher 只做「带超时 + 重试」的简单封装；
真正的取数由 scrapy 的下载器完成，这里保留契约以便换站时替换。
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import requests


@runtime_checkable
class FetcherStrategy(Protocol):
    def get(self, session: Any, signed_url: str) -> Any:
        ...


class RequestsFetcher:
    """同步 requests 实现（给脚本/自检用；spider 内仍走 scrapy 下载器）。"""

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = False  # 不走系统代理（本机直连）

    def get(self, session: Any, signed_url: str) -> Any:
        s = session or self.session
        return s.get(signed_url, timeout=self.timeout)

    def close(self) -> None:
        self.session.close()
