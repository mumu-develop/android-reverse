# -*- coding: utf-8 -*-
"""设备池：从 unidbg 服务取随机设备，保证「请求参数里的设备」和「签名用的设备」同源。

为什么必须同源：签名服务每个实例绑定一台设备的身份，签名头由该设备算出；
如果 URL 里的 device_id 是另一台，服务端会判定设备不一致（返回空 user / -99999）。

数据来源（按优先级）：
    1. GET /api/devices   —— 服务池里每台设备一台实例，含机型画像
    2. GET /api/health    —— 池为空时用配置里的单台设备兜底
    3. GET /api/register  —— 主动注册新设备（写入 devices.jsonl，重启服务后进池）
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from .. import config

#: 设备列表缓存时间（秒）—— 池子不会频繁变化
_DEVICE_CACHE_TTL = 60.0


class DevicePool:
    """线程安全的设备池（爬虫多线程共享）。"""

    def __init__(self, service: Optional[str] = None) -> None:
        self.service = (service or config.SIGN_SERVICE).rstrip("/")
        self._lock = threading.Lock()
        self._devices: List[Dict[str, Any]] = []
        self._fetched_at = 0.0
        self._fallback: Optional[Dict[str, Any]] = None

    # ---------- HTTP ----------

    def _get_json(self, path: str, timeout: int = 30) -> Dict[str, Any]:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(self.service + path, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))

    # ---------- 对外 ----------

    def _read_device_file(self) -> List[Dict[str, Any]]:
        """直接读签名服务的 devices.jsonl（/api/register 追加写的池文件）。

        这样新注册的设备不用重启服务就能参与轮换 —— 池实例只影响签名并发，
        不影响设备身份本身。
        """
        path = config.DEVICE_FILE
        if not path or not os.path.exists(path):
            return []
        out = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if rec.get("device_id"):
                        out.append({
                            "device_id": str(rec.get("device_id")),
                            "install_id": str(rec.get("install_id") or ""),
                            "cdid": str(rec.get("cdid") or ""),
                            "brand": rec.get("brand") or "google",
                            "model": rec.get("model") or "Pixel 6",
                            "os_version": str(rec.get("os_version") or "13"),
                            "os_api": int(rec.get("os_api") or 33),
                            "resolution": rec.get("resolution") or "1080*2209",
                            "dpi": int(rec.get("dpi") or 420),
                            "channel": rec.get("channel") or "huawei_1128_64",
                        })
        except Exception:
            return []
        return out

    def refresh(self) -> List[Dict[str, Any]]:
        """拉一次设备列表（带缓存）：/api/devices + devices.jsonl 合并去重。"""
        with self._lock:
            if self._devices and time.time() - self._fetched_at < _DEVICE_CACHE_TTL:
                return list(self._devices)
            devs: List[Dict[str, Any]] = []
            try:
                data = self._get_json("/api/devices")
                devs = data.get("devices") or []
            except Exception:
                pass
            # 合并池文件里的设备（新注册的还没进实例池，但身份可用）
            seen = {d.get("device_id") for d in devs}
            for d in self._read_device_file():
                if d["device_id"] not in seen:
                    devs.append(d)
                    seen.add(d["device_id"])
            if devs:
                self._devices = devs
                self._fetched_at = time.time()
                return list(devs)
            # 兜底：用 health 里的单台配置设备
            try:
                h = self._get_json("/api/health")
                did = h.get("deviceId")
                if did:
                    self._fallback = {
                        "device_id": did,
                        "install_id": config.get_str("DY_INSTALL_ID", "3594782549750826"),
                        "cdid": config.get_str("DY_CDID", "e3683b4a-3bf8-49c6-9332-6985361a6c4c"),
                        "brand": "google",
                        "model": "Pixel 6",
                        "os_version": "13",
                        "os_api": 33,
                        "resolution": "1080*2209",
                        "dpi": 420,
                        "channel": "huawei_1128_64",
                    }
                    return [self._fallback]
            except Exception:
                pass
            return list(self._devices)

    def random_device(self) -> Dict[str, Any]:
        """随机取一台设备；池空时用兜底设备。"""
        devs = self.refresh()
        if not devs:
            raise RuntimeError("设备池为空，且签名服务不可用")
        return random.choice(devs)

    def count(self) -> int:
        return len(self.refresh())

    def config_device(self) -> Dict[str, Any]:
        """配置里的单台兜底设备（来自 /api/health）。"""
        try:
            h = self._get_json("/api/health")
            did = h.get("deviceId")
        except Exception:
            did = None
        if not did:
            return {}
        return {
            "device_id": did,
            "install_id": config.get_str("DY_INSTALL_ID", "3594782549750826"),
            "cdid": config.get_str("DY_CDID", "e3683b4a-3bf8-49c6-9332-6985361a6c4c"),
            "brand": "google",
            "model": "Pixel 6",
            "os_version": "13",
            "os_api": 33,
            "resolution": "1080*2209",
            "dpi": 420,
            "channel": "huawei_1128_64",
        }

    def register(self, n: int = 1, verify: bool = False) -> List[Dict[str, Any]]:
        """调 unidbg 注册接口造新设备（随机指纹）。

        注意：新设备写入 devices.jsonl，签名服务需要重启才会加载进池。
        """
        out: List[Dict[str, Any]] = []
        q = urllib.parse.urlencode({"verify": "true" if verify else "false"})
        for _ in range(max(1, n)):
            data = self._get_json("/api/register?" + q, timeout=180)
            dev = data.get("device") or data
            if dev.get("device_id"):
                out.append(dev)
        # 注册后设备池已变，强制下次刷新
        with self._lock:
            self._fetched_at = 0.0
        return out
