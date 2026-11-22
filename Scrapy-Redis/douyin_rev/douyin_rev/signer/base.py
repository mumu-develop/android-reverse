# -*- coding: utf-8 -*-
"""签名策略契约（宪法文件，全工程不改）。

只放方法，不放类属性 —— `@runtime_checkable` 的 isinstance 会强制要求非方法属性。
站点不需要显式继承，方法签名匹配即满足（结构化子类型）。
"""
from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable


class SignedReq(dict):
    """签名产物：请求头键值对（X-Gorgon / X-Argus 等）。

    用 dict 子类而不是普通 dict，方便以后加属性（如签名耗时）而不破坏调用方。
    """


@runtime_checkable
class SigningStrategy(Protocol):
    """签名策略插槽。

    抖音实现走 HTTP 调用 unidbg 服务；TikTok 实现走 iv8 子进程。
    两者对 spider 暴露同一组方法。
    """

    def warm(self, cookies: Optional[dict] = None, profile: Optional[dict] = None) -> Any:
        """预热：建立连接 / 拉起子进程 / 刷新设备池。"""

    def sign(self, *, cursor: int = 0, count: int = 16, **kw: Any) -> "SignedReq":
        """给一个 URL（含 device 身份）签出请求头。"""

    def close(self) -> None:
        """释放资源（spider_closed 时调用）。"""
