# -*- coding: utf-8 -*-
"""设备调度器：按接口分档 + 设备级冷却（Redis 共享，多 worker 通用）。

为什么需要它：
    · 评论接口的限流是「按设备」算的，单设备约 15-20 请求/窗口，超出返回 -99999
    · 被风控的设备如果继续用，只会一直拿空页；换一台设备往往立刻能过
    · 多 worker 同时跑时，冷却状态必须共享，否则 A 进程刚封的设备 B 进程又去撞

数据结构：
    douyin_rev:dev:<device_id>:cool   TTL=冷却秒数   （存在 = 冷却中）
    douyin_rev:dev:<device_id>:hits   窗口内请求计数（用于主动限速，可选）
"""
from __future__ import annotations

import random
import threading
import time
from typing import Any, Dict, List, Optional

try:
    import redis
except Exception:  # pragma: no cover
    redis = None

#: 被风控后的默认冷却（秒）；按指数退避，上限 300
COOLDOWN_BASE = 90
COOLDOWN_MAX = 300


class DeviceScheduler:
    """线程安全的设备选择器。"""

    def __init__(self, redis_client=None, prefix: str = "douyin_rev") -> None:
        self._r = redis_client
        self.prefix = prefix
        self._lock = threading.Lock()
        #: 本地兜底冷却（Redis 不可用时用）
        self._local_cool: Dict[str, float] = {}

    # ---------- Redis ----------

    @property
    def r(self):
        if self._r is None and redis is not None:
            try:
                self._r = redis.Redis(host="127.0.0.1", port=6379, db=0,
                                      decode_responses=True, socket_timeout=2)
            except Exception:
                self._r = False
        return self._r or None

    def _cool_key(self, device_id: str) -> str:
        return "%s:dev:%s:cool" % (self.prefix, device_id)

    def in_cooldown(self, device_id: str) -> bool:
        r = self.r
        if r:
            try:
                return bool(r.exists(self._cool_key(device_id)))
            except Exception:
                pass
        with self._lock:
            until = self._local_cool.get(device_id, 0)
            return until > time.time()

    def cooldown_left(self, device_id: str) -> int:
        r = self.r
        if r:
            try:
                return int(r.ttl(self._cool_key(device_id)) or 0)
            except Exception:
                pass
        with self._lock:
            return max(0, int(self._local_cool.get(device_id, 0) - time.time()))

    # ---------- 选择 ----------

    def pick(self, devices: List[Dict[str, Any]], endpoint: str = "general") -> Dict[str, Any]:
        """从候选里挑一台不在冷却中的；全都在冷却则挑剩余时间最短的。"""
        if not devices:
            raise RuntimeError("设备池为空")
        free = [d for d in devices if not self.in_cooldown(d.get("device_id", ""))]
        if free:
            return random.choice(free)
        # 全冷却：挑最早恢复的，避免死等
        return min(devices, key=lambda d: self.cooldown_left(d.get("device_id", "")))

    # ---------- 反馈 ----------

    def report_risk(self, device_id: str, strikes: int = 1) -> int:
        """标记设备被风控：指数退避冷却，返回冷却秒数。"""
        sec = min(COOLDOWN_BASE * (2 ** max(0, strikes - 1)), COOLDOWN_MAX)
        r = self.r
        if r:
            try:
                r.setex(self._cool_key(device_id), sec, "1")
                return sec
            except Exception:
                pass
        with self._lock:
            self._local_cool[device_id] = time.time() + sec
        return sec

    def report_ok(self, device_id: str) -> None:
        """一次成功：清掉本地冷却记录（Redis 冷却不主动清，让它自然过期）。"""
        with self._lock:
            self._local_cool.pop(device_id, None)

    # ---------- 观测 ----------

    def snapshot(self, devices: List[Dict[str, Any]]) -> Dict[str, int]:
        return {d.get("device_id", ""): self.cooldown_left(d.get("device_id", ""))
                for d in devices}
