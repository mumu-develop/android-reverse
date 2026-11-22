# -*- coding: utf-8 -*-
"""用户主页采集 spider（编排层）。

一条任务（user_task 的一行）走三段状态机：

    profile  →  user_profile
       ↓
    videos   →  user_videos（按 max_cursor 翻页）
       ↓
    comments →  user_video_comments（逐个视频按 cursor 翻页）

断点续跑：
    每段结束时把进度写回 user_task（video_cursor / video_pages /
    video_index / comment_aweme_id / comment_cursor / comment_pages），
    进程崩了重新投喂同一 URL，会从断点继续。

任务互斥：
    claim_task() 用 Redis SETNX + DB 行置 running，同一任务只能被
    一个 worker 抓；抓完 complete/fail 时释放锁。
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
from typing import Any, Dict, Iterator, List, Optional

import scrapy
from scrapy import signals
from scrapy.utils.misc import load_object
from scrapy_redis.spiders import RedisSpider
from scrapy_redis.utils import bytes_to_str

from .. import config, parser, query
from ..db import session_scope
from ..db.models import UserVideo, VideoTask
from ..items import CommentItem, ProfileItem, VideoItem
from ..tasks import task_state

log = logging.getLogger(__name__)

_SEC_RE = re.compile(r"MS4wLjABAAAA[\w\-]+")

#: 抖音风控码：出现在「拼接 JSON」的第二个对象里
CODE_RISK = -99999


def decode_stream(text: str):
    """抖音有时把两个 JSON 拼在一起返回：

        { "has_more":0,"status_code":0,"comments":[]}
        {"log_pb":{...},"status_code":-99999,"status_msg":""}

    第一个是页面数据，第二个是风控信号。用 raw_decode 逐个解出来。
    """
    objs = []
    dec = json.JSONDecoder(strict=False)
    idx, n = 0, len(text)
    while idx < n:
        while idx < n and text[idx] in " \r\n\t":
            idx += 1
        if idx >= n:
            break
        try:
            obj, idx = dec.raw_decode(text, idx)
        except Exception:
            break
        objs.append(obj)
    return objs


def extract_sec_uid(text: str) -> Optional[str]:
    m = _SEC_RE.search(text or "")
    return m.group(0) if m else None


class UserSpider(RedisSpider):
    """读 user_task 队列，抓详情 + 作品 + 评论。"""

    name = "user"
    redis_key = "douyin_rev:start_urls"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.worker_id = "%s-%d" % (socket.gethostname(), os.getpid())
        # 0 是有效值（= 关闭该阶段），不能用 or 兜底
        vp = kwargs.get("video_pages")
        cp = kwargs.get("comment_pages")
        self.video_pages_limit = (int(vp) if vp not in (None, "")
                                  else config.DEFAULT_VIDEO_PAGES)
        self.comment_pages_limit = (int(cp) if cp not in (None, "")
                                    else config.DEFAULT_COMMENT_PAGES)
        self.strategy = None
        self.stats = {"profile": 0, "videos": 0, "comments": 0, "tasks": 0}
        # 作品 ID 缓存：item 落库是异步的，评论阶段不能立刻查库，先用内存里的顺序
        self._video_ids_cache = {}
        # 视频评论数缓存：0 评论的视频直接跳过，省一次请求
        self._video_comment_counts = {}

    # ---------- 装配 ----------

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        path = crawler.settings.get(
            "SIGNING_STRATEGY", "douyin_rev.signer.strategy.UnidbgStrategy")
        spider.strategy = load_object(path)()
        try:
            info = spider.strategy.warm()
            log.info("签名策略就绪: %s", info)
        except Exception as e:
            log.warning("签名策略 warm 失败: %r", e)
        # 初始化阶段补齐设备（Crawlab 上由 scrapy 命令触发，无需额外准备步骤）
        try:
            added = spider.strategy.ensure_devices()
            if added:
                log.info("初始化补齐设备 %d 台（现池 %d 台）",
                         added, len(spider.strategy.pool.refresh()))
        except Exception as e:
            log.warning("初始化补设备失败: %r", e)
        spider.redis_key = crawler.settings.get(
            "REDIS_START_URLS_KEY", spider.redis_key)
        crawler.signals.connect(spider.on_closed, signal=signals.spider_closed)
        return spider

    # ---------- 队列入口 ----------

    def make_request_from_data(self, data) -> Optional[scrapy.Request]:
        """队列里只有主页 URL；在这里 claim 任务并直接发第一个接口请求。

        不抓网页本身（抖音 web 是 SPA，抓了也没数据）。
        """
        user_url = bytes_to_str(data, self.redis_encoding).strip()
        if not user_url:
            return None
        task = task_state.find_task_by_url(user_url)
        if task is None:
            log.warning("任务不存在: %s", user_url[:80])
            return None
        tid = task["id"]
        if not task_state.claim_task(tid, self.worker_id):
            log.info("任务 %d 被其他 worker 占用，跳过", tid)
            return None
        snap = task_state.reload_task(tid)
        if snap is None:
            task_state.release_lock(tid)
            return None
        sec = snap.get("sec_user_id") or extract_sec_uid(user_url)
        if not sec:
            task_state.fail_task(tid, "URL 里没有 sec_user_id", self.worker_id)
            return None
        if not snap.get("sec_user_id"):
            task_state.progress(tid, sec_user_id=sec)
        snap["sec_user_id"] = sec
        self.stats["tasks"] += 1
        return self._next_request(snap)

    # ---------- 状态机 ----------

    def _next_request(self, snap: Dict[str, Any]) -> Optional[scrapy.Request]:
        tid = snap["id"]
        sec = snap["sec_user_id"]

        if not snap["profile_done"]:
            return self._req("profile", tid, sec,
                             lambda d: query.profile_url(d, sec),
                             endpoint="profile")

        if not snap["videos_done"]:
            if getattr(self.strategy, "posts_degraded", False):
                self.logger.error("作品列表通道已降级（受信任 iid 全失效），跳过视频列表")
                task_state.progress(tid, videos_done=True)
                snap = task_state.reload_task(tid) or snap
                return self._next_request(snap) if snap else None
            cur = snap["video_cursor"] or 0
            return self._req("videos", tid, sec,
                             lambda d: query.posts_url(d, sec, cursor=cur),
                             endpoint="posts")

        # 评论阶段
        if config.SPLIT_COMMENTS:
            # 拆分模式：评论由 comment spider 负责，user 任务到此为止
            task_state.progress(tid, comments_done=True)
            task_state.complete_task(tid, self.worker_id)
            log.info("任务 %d 完成（详情+作品；评论已拆到 video_task）", tid)
            return None

        if self.comment_pages_limit <= 0:
            task_state.progress(tid, comments_done=True)
            task_state.complete_task(tid, self.worker_id)
            log.info("任务 %d 完成（只抓详情+作品，评论已关闭）", tid)
            return None
        ids = self._video_ids(sec)
        counts = self._video_comment_counts.get(sec, {})
        idx = snap["video_index"] or 0
        # 跳过 0 评论的视频（省请求）；已抓过的也跳过
        while idx < len(ids) and counts.get(ids[idx], -1) == 0:
            idx += 1
        if idx >= len(ids):
            task_state.progress(tid, comments_done=True)
            task_state.complete_task(tid, self.worker_id)
            log.info("任务 %d 完成（视频 %d 个）", tid, len(ids))
            return None
        aweme_id = ids[idx]
        cursor = snap["comment_cursor"] if snap.get("comment_aweme_id") == aweme_id else 0
        task_state.progress(tid, video_index=idx, comment_aweme_id=aweme_id,
                            comment_cursor=cursor, comment_pages=0)
        return self._req("comments", tid, sec,
                         lambda d: query.comments_url(d, aweme_id, cursor=cursor),
                         aweme_id=aweme_id)

    def _req(self, phase: str, tid: int, sec: str, builder,
             aweme_id: str = "", endpoint: str = "general") -> scrapy.Request:
        """选设备 → 用同一台设备拼 URL → 请求带同一台设备（签名时也用这台）。

        endpoint 决定设备档位：
            posts   → 作品列表专用池（新设备会被服务端返空，必须用老设备）
            general → 详情/评论（可轮换）
        """
        device = self.strategy.random_device(endpoint)
        url = builder(device)
        return scrapy.Request(
            url=url,
            callback=self.parse,
            errback=self.on_error,
            dont_filter=True,
            meta={"phase": phase, "task_id": tid, "sec_user_id": sec,
                  "aweme_id": aweme_id, "device": device},
        )

    # ---------- 解析 ----------

    def parse(self, response) -> Iterator[Any]:
        phase = response.meta["phase"]
        objs = decode_stream(response.text)
        data = objs[0] if objs else None
        # 第二个对象带 -99999 = 被风控，这一页是假的「空页」
        blocked = any(o.get("status_code") == CODE_RISK for o in objs[1:])
        if data is None:
            log.warning("响应不是 JSON（%s）: %s", phase, response.text[:120])
            if phase == "comments":
                yield from self._advance_video(response)
            else:
                task_state.fail_task(response.meta["task_id"], "non-json response",
                                     self.worker_id, partial=True)
            return

        if phase == "profile":
            yield from self._parse_profile(response, data)
        elif phase == "videos":
            yield from self._parse_videos(response, data)
        else:
            if blocked:
                yield from self._retry_comments(response)
            else:
                yield from self._parse_comments(response, data)

    def _parse_profile(self, response, data) -> Iterator[Any]:
        tid = response.meta["task_id"]
        sec = response.meta["sec_user_id"]
        item = parser.parse_profile(data, sec)
        iid = (response.meta.get("device") or {}).get("install_id", "")
        if item:
            self.stats["profile"] += 1
            self.strategy.report_profile_result(iid, True)
            yield ProfileItem(**item)
        else:
            # 详情返空：这个 iid 可能被封，隔离它并换设备重试
            self.strategy.report_profile_result(iid, False)
            retry = int(response.meta.get("profile_retry") or 0)
            if retry < 2:
                self.logger.warning("详情返空（iid=%s…），换设备重试 %d/2", iid[-6:], retry + 1)
                req = self._req("profile", tid, sec,
                                lambda d: query.profile_url(d, sec),
                                endpoint="profile")
                req.meta["profile_retry"] = retry + 1
                yield req
                return
            self.logger.error("详情连续返空（iid 可能被封），跳过详情继续抓其它")
        task_state.progress(tid, profile_done=True)
        snap = task_state.reload_task(tid)
        if snap:
            yield self._next_request(snap)

    def _parse_videos(self, response, data) -> Iterator[Any]:
        tid = response.meta["task_id"]
        sec = response.meta["sec_user_id"]
        page = parser.parse_posts(data, sec)
        # 回报作品列表结果：连续空会触发 iid 熔断切换
        self.strategy.report_posts_result(bool(page["items"]))
        cache = self._video_ids_cache.setdefault(sec, [])
        for it in page["items"]:
            self.stats["videos"] += 1
            if it.get("aweme_id"):
                cache.append(it["aweme_id"])
                self._video_comment_counts.setdefault(sec, {})[it["aweme_id"]] = int(
                    it.get("comment_count") or 0)
            yield VideoItem(**it)

        snap = task_state.reload_task(tid) or {}
        pages = int(snap.get("video_pages") or 0) + 1
        task_state.progress(tid, video_cursor=page["max_cursor"], video_pages=pages)

        if page["has_more"] and page["items"] and pages < self.video_pages_limit:
            cursor = page["max_cursor"]
            yield self._req("videos", tid, sec,
                            lambda d: query.posts_url(d, sec, cursor=cursor),
                            endpoint="posts")
        else:
            task_state.progress(tid, videos_done=True, video_index=0,
                                comment_aweme_id=None, comment_cursor=0,
                                comment_pages=0)
            if config.SPLIT_COMMENTS:
                n = self._enqueue_video_tasks(sec)
                task_state.progress(tid, comments_done=True)
                task_state.complete_task(tid, self.worker_id)
                log.info("任务 %d 完成（详情+作品），拆出 %d 条评论任务", tid, n)
                return
            snap = task_state.reload_task(tid)
            if snap:
                yield self._next_request(snap)

    def _parse_comments(self, response, data) -> Iterator[Any]:
        tid = response.meta["task_id"]
        sec = response.meta["sec_user_id"]
        aweme_id = response.meta.get("aweme_id") or ""
        page = parser.parse_comments(data, aweme_id)
        for it in page["items"]:
            self.stats["comments"] += 1
            yield CommentItem(**it)

        snap = task_state.reload_task(tid) or {}
        pages = int(snap.get("comment_pages") or 0) + 1
        task_state.progress(tid, comment_cursor=page["cursor"], comment_pages=pages)

        if page["has_more"] and page["items"] and pages < self.comment_pages_limit:
            next_cursor = page["cursor"]
            yield self._req("comments", tid, sec,
                            lambda d: query.comments_url(d, aweme_id, cursor=next_cursor),
                            aweme_id=aweme_id)
        else:
            yield from self._advance_video(response)

    def _retry_comments(self, response) -> Iterator[Any]:
        """评论被风控（-99999）：换一台设备重试同一页，最多 2 次。

        抖音的限流是按设备算的，换设备往往立刻就能过；超过重试次数就
        把这页当作「到底」，避免死循环。
        """
        tid = response.meta["task_id"]
        sec = response.meta["sec_user_id"]
        aweme_id = response.meta.get("aweme_id") or ""
        dev = (response.meta.get("device") or {}).get("device_id", "")
        strikes = int(response.meta.get("risk_strikes") or 0) + 1
        left = self.strategy.report_risk(dev, strikes) if dev else 0
        attempt = int(response.meta.get("risk_retry") or 0)
        if attempt >= 2:
            log.info("视频 %s 评论连续被风控，跳过", aweme_id)
            yield from self._advance_video(response)
            return
        snap = task_state.reload_task(tid) or {}
        cursor = int(snap.get("comment_cursor") or 0)
        req = self._req("comments", tid, sec,
                        lambda d: query.comments_url(d, aweme_id, cursor=cursor),
                        aweme_id=aweme_id)
        req.meta["risk_retry"] = attempt + 1
        req.meta["risk_strikes"] = strikes
        self.logger.info("设备 %s 被风控，冷却 %ds，换设备重试同页", dev[-6:], left)
        self.stats["risk_retry"] = self.stats.get("risk_retry", 0) + 1
        yield req

    def _advance_video(self, response) -> Iterator[Any]:
        """一个视频的评论抓完（或空页）→ 下一个视频。"""
        tid = response.meta["task_id"]
        sec = response.meta["sec_user_id"]
        snap = task_state.reload_task(tid) or {}
        idx = int(snap.get("video_index") or 0) + 1
        task_state.progress(tid, video_index=idx, comment_cursor=0,
                            comment_pages=0, comment_aweme_id=None)
        snap = task_state.reload_task(tid)
        if snap:
            nxt = self._next_request(snap)
            if nxt is not None:
                yield nxt

    # ---------- 工具 ----------

    def _enqueue_video_tasks(self, sec_user_id: str) -> int:
        """把该用户的视频写成 video_task（幂等：已存在则跳过）。"""
        ids = self._video_ids(sec_user_id)
        if not ids:
            return 0
        added = 0
        with session_scope() as s:
            existing = {r[0] for r in
                        s.query(VideoTask.aweme_id)
                        .filter(VideoTask.aweme_id.in_(ids)).all()}
            for aid in ids:
                if aid in existing:
                    continue
                s.add(VideoTask(aweme_id=aid, sec_user_id=sec_user_id,
                                status="pending"))
                added += 1
        return added

    def _video_ids(self, sec_user_id: str) -> List[str]:
        cached = self._video_ids_cache.get(sec_user_id)
        if cached:
            return list(cached)
        with session_scope() as s:
            rows = (s.query(UserVideo.aweme_id)
                    .filter(UserVideo.sec_user_id == sec_user_id)
                    .order_by(UserVideo.create_time.desc())
                    .all())
            return [r[0] for r in rows]

    # ---------- 异常与收尾 ----------

    def on_error(self, failure):
        req = failure.request
        tid = req.meta.get("task_id")
        log.warning("请求失败 task=%s %s: %s", tid, req.url[:80], failure.value)
        if tid:
            task_state.fail_task(tid, "request failed: %s" % failure.value,
                                 self.worker_id, partial=True)

    def on_closed(self, spider, reason=None):
        """spider_closed：把本 worker 还挂着的 running 行收尾成 partial。"""
        if not self.worker_id:
            return
        try:
            with session_scope() as s:
                rows = (s.query(task_state.UserTask)
                        .filter(task_state.UserTask.status == task_state.ST_RUNNING,
                                task_state.UserTask.assigned_worker == self.worker_id)
                        .all())
                for row in rows:
                    row.status = task_state.ST_PARTIAL
                    row.assigned_worker = None
                    row.last_error = "spider_closed_early"
            log.info("spider 关闭（%s），收尾 running 行 %d 个", reason, len(rows))
        except Exception as e:
            log.warning("收尾失败: %r", e)
        log.info("本次统计: %s", self.stats)
