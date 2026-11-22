# -*- coding: utf-8 -*-
"""unidbg HTTP 签名策略（本站点专属实现，满足 SigningStrategy 契约）。

链路：
    spider 用设备画像拼出完整 URL（含 device_id/iid/cdid）
      → 本策略调 GET /api/sign?url=...&device=<device_id>
      → unidbg 服务用「同一台设备」的实例算六神头
      → 返回 {X-Argus, X-Gorgon, X-Helios, X-Khronos, X-Ladon, X-Medusa}

设备分级（2026-11-22 A/B 实测结论）：
    · 签名用哪台设备不影响服务端判定（URL 用老设备 + 随便一台签名，照样出数据）
    · 决定权在 URL 里的 device_id
    · 用户详情、评论：新注册设备可用
    · 作品列表：只有"老设备"（配置里那台）可用，新设备返回空 body

所以设备池按接口分两档：
    general_devices  → 详情 / 评论（新设备也能用，可轮换）
    posts_devices    → 作品列表（只挑真正返回 aweme_list 的设备）
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

from .. import config, query
from .base import SignedReq
from .device import DevicePool
from .scheduler import DeviceScheduler


class UnidbgStrategy:
    """通过本地 unidbg 服务签名。"""

    #: 探针用的公开主页与视频
    PROBE_SEC = "MS4wLjABAAAAHdpdxcUy7-J8XUlDMVNJNo3plbZSG8eB0Z3CRAwWZfy4eXcZDNfJcRsr1lthZCj5"
    PROBE_AWEME = "7706919082587489017"

    def __init__(self, service: Optional[str] = None) -> None:
        self.service = (service or config.SIGN_SERVICE).rstrip("/")
        self.pool = DevicePool(self.service)
        self._lock = threading.Lock()
        self.signed = 0
        self.failed = 0
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.scheduler = DeviceScheduler()
        # 设备分级（warm 时填充）
        self.general_devices: List[Dict[str, Any]] = []
        self.posts_devices: List[Dict[str, Any]] = []
        # 作品列表的受信任安装（iid）候选与熔断状态
        self.install_candidates: List[Dict[str, str]] = []
        self.active_install: Optional[Dict[str, str]] = None
        self.posts_degraded = False
        self._posts_empty_streak = 0

    # ---------- 契约方法 ----------

    #: 探针结果缓存（多 worker 共享，避免每个进程都重新探 40+ 次）
    CACHE_TTL = int(os.environ.get("DY_PROBE_TTL", "900"))
    #: 单次 warm 最多探测几台（其余乐观放行，避免启动被慢设备拖死）
    MAX_PROBE = int(os.environ.get("DY_PROBE_MAX", "6"))

    def _cache_path(self) -> str:
        return str(config.PROJECT_ROOT / "device_probe.json")

    def _load_cache(self) -> Dict[str, Any]:
        try:
            with open(self._cache_path(), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_cache(self, cache: Dict[str, Any]) -> None:
        try:
            with open(self._cache_path(), "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
        except Exception:
            pass

    def _cached(self, cache: Dict[str, Any], dev_id: str, kind: str) -> Optional[bool]:
        rec = cache.get(dev_id) or {}
        ts = rec.get(kind + "_ts") or 0
        if time.time() - ts > self.CACHE_TTL:
            return None
        return bool(rec.get(kind))

    def warm(self, cookies: Optional[dict] = None, profile: Optional[dict] = None) -> Dict[str, Any]:
        """预热：刷新设备池 + 按接口探测设备可用性。

        探针都用 count=1，成本很低：
            comments 探针 → 进 general_devices（详情/评论都能用）
            posts    探针 → 进 posts_devices（作品列表能用）
        """
        devices = self.pool.refresh()
        cfg = self.pool.config_device()
        candidates = list(devices)
        if cfg and all(d.get("device_id") != cfg.get("device_id") for d in candidates):
            candidates.append(cfg)

        cache = self._load_cache()
        general: List[Dict[str, Any]] = []
        posts: List[Dict[str, Any]] = []
        probed = 0
        for d in candidates:
            did = d.get("device_id", "")
            ok_c = self._cached(cache, did, "comments")
            if ok_c is None:
                if probed < self.MAX_PROBE:
                    ok_c = self._probe_comments(d)
                    probed += 1
                    cache.setdefault(did, {})["comments"] = ok_c
                    cache[did]["comments_ts"] = time.time()
                else:
                    ok_c = True          # 乐观放行：真不行会被调度器冷却
            if ok_c:
                general.append(d)
            ok_p = self._cached(cache, did, "posts")
            if ok_p is None:
                if probed < self.MAX_PROBE:
                    ok_p = self._probe_posts(d)
                    probed += 1
                    cache.setdefault(did, {})["posts"] = ok_p
                    cache[did]["posts_ts"] = time.time()
                else:
                    ok_p = True
            if ok_p:
                posts.append(d)
        self._save_cache(cache)

        # 探针可能撞上临时限流：可用设备太少时视为探针不准，全部放行
        if len(general) < 2:
            general = list(candidates) or general
        if not posts:
            posts = [cfg] if cfg else list(general)

        self._build_install_candidates(candidates)
        self.posts_degraded = False
        self.active_install = None
        for c in self.install_candidates:
            if self._probe_posts_with(c.get("install_id"), c.get("cdid")):
                self.active_install = c
                break
        if self.active_install is None:
            self.posts_degraded = True

        self.general_devices = general
        self.posts_devices = posts
        return {
            "devices": len(candidates),
            "general": len(general),
            "posts": len(posts),
            "installs": len(self.install_candidates),
            "active_iid": (self.active_install or {}).get("install_id", "")[-6:],
            "posts_degraded": self.posts_degraded,
            "service": self.service,
        }

    def sign(self, *, cursor: int = 0, count: int = 16, **kw: Any) -> SignedReq:
        """给 URL 签名。

        kw:
            url    必填，完整 URL（含设备参数）
            device 可选，设备 ID；不传则由服务池自选
        """
        url = kw.get("url")
        if not url:
            raise ValueError("sign() 需要 url 参数")
        device = kw.get("device")
        params = {"url": url}
        if device:
            params["device"] = device
        q = urllib.parse.urlencode(params)
        try:
            with self._opener.open(self.service + "/api/sign?" + q,
                                   timeout=config.SIGN_TIMEOUT) as r:
                data = json.loads(r.read().decode("utf-8", "ignore"))
            if not data.get("ok"):
                raise RuntimeError(data.get("error") or "签名失败")
            headers = data.get("headers") or {}
            with self._lock:
                self.signed += 1
            return SignedReq(headers)
        except Exception:
            with self._lock:
                self.failed += 1
            raise

    def close(self) -> None:
        return None

    # ---------- 设备准备（spider 初始化阶段调用） ----------

    #: 池里至少保证多少台设备；不足则现注册
    MIN_DEVICES = int(os.environ.get("DY_MIN_DEVICES", "20"))

    def ensure_devices(self, min_count: Optional[int] = None) -> int:
        """启动时补齐设备：不足 min_count 就 /api/register 现造。

        返回本次新增台数。注册写 devices.jsonl，服务侧实例数不受影响
        （签名会 fallback 到任意实例），但设备身份立刻可用于请求。
        """
        target = int(min_count or self.MIN_DEVICES)
        try:
            have = len(self.pool.refresh())
        except Exception:
            return 0
        if have >= target:
            return 0
        need = min(target - have, 50)      # 单次最多补 50 台，防呆
        try:
            made = self.pool.register(need)
            return len(made)
        except Exception:
            return 0

    # ---------- 详情侧：坏 iid 隔离 + 自动补设备 ----------

    #: 被判定为"详情返空"的 iid 冷却时间（秒）
    PROFILE_BAD_TTL = int(os.environ.get("DY_PROFILE_BAD_TTL", "21600"))

    def _profile_bad_key(self, iid: str) -> str:
        return "douyin_rev:iid:%s:profile_bad" % (iid or "")

    def _iid_bad(self, iid: str) -> bool:
        try:
            return bool(self.scheduler.r and self.scheduler.r.exists(self._profile_bad_key(iid)))
        except Exception:
            return False

    def report_profile_result(self, iid: str, ok: bool) -> None:
        """详情接口返空 → 把该 iid 标记坏，后续不再用它拉详情。"""
        if ok or not iid:
            return
        try:
            if self.scheduler.r:
                self.scheduler.r.setex(self._profile_bad_key(iid), self.PROFILE_BAD_TTL, "1")
        except Exception:
            pass

    def profile_device(self) -> Dict[str, Any]:
        """详情用设备：挑一个 iid 没被标记坏的；全坏就现注册一批新设备。

        实测：任何新注册设备的 iid 都能拉详情（不需要"受信任"），
        所以 iid 是可再生的 —— 封了就再造，详情不会断。
        """
        pool = [d for d in (self.general_devices or self.pool.refresh())
                if not self._iid_bad(d.get("install_id", ""))]
        if pool:
            return random.choice(pool)
        # 全部 iid 都被标记坏 → 现造 3 台
        try:
            made = self.pool.register(3)
            fresh = []
            for r in made:
                fresh.append({
                    "device_id": str(r.get("device_id")),
                    "install_id": str(r.get("install_id") or ""),
                    "cdid": str(r.get("cdid") or ""),
                    "brand": r.get("brand") or "google",
                    "model": r.get("model") or "Pixel 6",
                    "os_version": str(r.get("os_version") or "13"),
                    "os_api": int(r.get("os_api") or 33),
                    "resolution": r.get("resolution") or "1080*2209",
                    "dpi": int(r.get("dpi") or 420),
                    "channel": r.get("channel") or "huawei_1128_64",
                })
            if fresh:
                self.general_devices = list(self.general_devices) + fresh
                return random.choice(fresh)
        except Exception:
            pass
        return random.choice(self.general_devices or self.pool.refresh())

    # ---------- 设备选择 ----------

    #: 连续多少次作品列表返回空 → 触发熔断探测
    POSTS_BREAKER = int(os.environ.get("DY_POSTS_BREAKER", "10"))

    def _build_install_candidates(self, candidates: List[Dict[str, Any]]) -> None:
        """受信任 iid 候选：环境变量优先，其次是设备池里各设备自带的 iid。"""
        cfg = self.pool.config_device()
        cands: List[Dict[str, str]] = []
        # ① 匿名（iid=0）——实测作品列表接口接受匿名请求，且不受"新安装"限制
        cands.append({"install_id": "0", "cdid": cfg.get("cdid") or ""})
        # ② 环境变量指定的受信任 iid（真机）
        for iid in config.TRUSTED_IIDS:
            cands.append({"install_id": iid, "cdid": cfg.get("cdid") or ""})
        # ③ 配置里的真机 iid（兜底）
        if cfg.get("install_id"):
            cands.append({"install_id": cfg["install_id"], "cdid": cfg.get("cdid") or ""})
        for d in candidates:
            iid = d.get("install_id")
            if iid and all(c["install_id"] != iid for c in cands):
                cands.append({"install_id": iid, "cdid": d.get("cdid") or ""})
        # 去重保序
        seen, out = set(), []
        for c in cands:
            if c["install_id"] not in seen:
                seen.add(c["install_id"])
                out.append(c)
        self.install_candidates = out

    def report_posts_result(self, ok: bool) -> None:
        """spider 每抓完一页作品回报结果，用于熔断探测。"""
        if ok:
            self._posts_empty_streak = 0
            return
        self._posts_empty_streak += 1
        if self._posts_empty_streak < self.POSTS_BREAKER or self.posts_degraded:
            return
        # 连续空 → 探测当前 iid 是否还能用
        cur = self.active_install or {}
        if self._probe_posts_with(cur.get("install_id"), cur.get("cdid")):
            self._posts_empty_streak = 0
            return
        self._rotate_install()

    def _probe_posts_with(self, install_id: Optional[str], cdid: Optional[str]) -> bool:
        cfg = self.pool.config_device()
        probe = dict(cfg)
        probe["install_id"] = install_id or ""
        probe["cdid"] = cdid or cfg.get("cdid") or ""
        try:
            body = self._fetch(query.posts_url(probe, self.PROBE_SEC, cursor=0, count=1),
                               probe.get("device_id") or cfg.get("device_id"))
            if not body:
                return False
            data = json.loads(body.decode("utf-8", "ignore"))
            return data.get("status_code") == 0 and bool(data.get("aweme_list"))
        except Exception:
            return False

    def _rotate_install(self) -> None:
        """当前 iid 失效：按优先级切下一个；全挂则降级。"""
        current = (self.active_install or {}).get("install_id")
        for c in self.install_candidates:
            if c["install_id"] == current:
                continue
            if self._probe_posts_with(c.get("install_id"), c.get("cdid")):
                self.active_install = c
                self._posts_empty_streak = 0
                return
        self.posts_degraded = True

    def trusted_install(self) -> Dict[str, str]:
        """返回"受信任的安装身份"（iid/cdid）。

        实测（2026-11-22）：作品列表接口按 iid/cdid 判信任，
        新注册的安装被服务端标成 new_user=1，作品列表静默返回空；
        device_id 随便换都能出数据，只要 iid/cdid 是受信任的那一套。
        """
        if self.active_install:
            return dict(self.active_install)
        cfg = self.pool.config_device()
        return {"install_id": cfg.get("install_id") or "", "cdid": cfg.get("cdid") or ""}

    def posts_device(self) -> Dict[str, Any]:
        """作品列表用的设备：随机 device_id + 当前可用的 iid。

        默认 iid=0（匿名）：实测作品列表接受匿名，且不受新安装 new_user 限制；
        匿名失效时熔断会切到真机 iid，全挂则降级。
        """
        d = dict(self.random_device("general"))
        t = self.trusted_install()
        if t["install_id"]:
            d["install_id"] = t["install_id"]
        if t["cdid"]:
            d["cdid"] = t["cdid"]
        return d

    def random_device(self, endpoint: str = "general") -> Dict[str, Any]:
        """按接口挑设备。

        endpoint:
            "posts"    → 作品列表专用池（老设备）
            "general"  → 详情 / 评论池（可轮换，新设备也能用）
        """
        if endpoint == "posts":
            dev = self.posts_device()
            # posts 的设备是 overlay，调度用底层 device_id 判断冷却
            dev["device_id"] = self.scheduler.pick(
                self.general_devices or self.pool.refresh()).get("device_id", dev.get("device_id"))
            return dev
        pool = self.general_devices or self.pool.refresh()
        return self.scheduler.pick(pool)

    def report_risk(self, device_id: str, strikes: int = 1) -> int:
        """上报一次风控（spider 收到 -99999 时调用），返回冷却秒数。"""
        return self.scheduler.report_risk(device_id, strikes)

    def report_ok(self, device_id: str) -> None:
        self.scheduler.report_ok(device_id)

    # ---------- 探针 ----------

    def _fetch(self, url: str, device_id: str) -> bytes:
        headers = dict(self.sign(url=url, device=device_id))
        headers["User-Agent"] = ("com.ss.android.ugc.aweme/400200 "
                                 "(Linux; U; Android 13; zh_CN; Pixel 6)")
        with self._opener.open(urllib.request.Request(url, headers=headers),
                               timeout=6) as r:
            return r.read()

    def _probe_comments(self, device: Dict[str, Any]) -> bool:
        """评论接口探针：能返回 comments 即视为可用。"""
        try:
            url = query.comments_url(device, self.PROBE_AWEME, cursor=0, count=1)
            body = self._fetch(url, device.get("device_id"))
            if not body:
                return False
            data = json.loads(body.decode("utf-8", "ignore"))
            return data.get("status_code") == 0 and bool(data.get("comments"))
        except Exception:
            return False

    def _probe_posts(self, device: Dict[str, Any]) -> bool:
        """作品列表探针：用受信任 iid/cdid 覆盖后再试，能出 aweme_list 即可用。"""
        try:
            probe = dict(device)
            t = self.trusted_install()
            if t.get("install_id"):
                probe["install_id"] = t["install_id"]
            if t.get("cdid"):
                probe["cdid"] = t["cdid"]
            url = query.posts_url(probe, self.PROBE_SEC, cursor=0, count=1)
            body = self._fetch(url, device.get("device_id"))
            if not body:
                return False
            data = json.loads(body.decode("utf-8", "ignore"))
            return data.get("status_code") == 0 and bool(data.get("aweme_list"))
        except Exception:
            return False

    # ---------- 统计 ----------

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {"signed": self.signed, "failed": self.failed}
