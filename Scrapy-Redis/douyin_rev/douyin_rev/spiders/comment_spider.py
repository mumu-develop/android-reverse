# -*- coding: utf-8 -*-
"""视频评论 spider（video_task）。

一条任务 = 一个视频的评论翻页。

为什么单独拆出来：
    user spider 里「详情 → 作品 → 逐个视频评论」是串行链，一个用户的评论
    有几千个请求时会占着一条链几小时。拆成独立任务后，同一用户的多个视频
    可以并行，断点粒度也从「视频级」细化到「评论页级」。

队列：douyin_rev:video_start_urls（元素是 aweme_id）
"""
from __future__ import annotations

import logging
import os
import socket
from typing import Any, Iterator

import scrapy
from scrapy import signals
from scrapy.utils.misc import load_object
from scrapy_redis.spiders import RedisSpider
from scrapy_redis.utils import bytes_to_str

from .. import config, parser, query
from ..db import session_scope
from ..db.models import VideoTask, UserVideoComment
from ..items import CommentItem
from ..tasks import video_task_state

log = logging.getLogger(__name__)


def decode_stream(text: str):
    """抖音有时把两个 JSON 拼在一起返回（第二个是 -99999 风控信号）。"""
    import json
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


class CommentSpider(RedisSpider):
    """按 video_task 抓评论。"""

    name = "comment"
    redis_key = "douyin_rev:video_start_urls"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.worker_id = "%s-%d" % (socket.gethostname(), os.getpid())
        cp = kwargs.get("comment_pages")
        self.comment_pages_limit = (int(cp) if cp not in (None, "")
                                    else config.DEFAULT_COMMENT_PAGES)
        self.strategy = None
        self.stats = {"comments": 0, "tasks": 0, "risk": 0}

    # ---------- 装配 ----------

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        path = crawler.settings.get(
            "SIGNING_STRATEGY", "douyin_rev.signer.strategy.UnidbgStrategy")
        spider.strategy = load_object(path)()
        try:
            log.info("评论 spider 签名策略: %s", spider.strategy.warm())
        except Exception as e:
            log.warning("签名策略 warm 失败: %r", e)
        spider.redis_key = crawler.settings.get(
            "REDIS_VIDEO_START_URLS_KEY", spider.redis_key)
        crawler.signals.connect(spider.on_closed, signal=signals.spider_closed)
        return spider

    # ---------- 队列入口 ----------

    def make_request_from_data(self, data):
        aweme_id = bytes_to_str(data, self.redis_encoding).strip()
        if not aweme_id:
            return None
        task = video_task_state.find_video_task(aweme_id)
        if task is None:
            log.warning("视频任务不存在: %s", aweme_id)
            return None
        tid = task["id"]
        if not video_task_state.claim_video_task(tid, self.worker_id):
            log.debug("视频任务 %d 被占用，跳过", tid)
            return None
        snap = video_task_state.reload_video_task(tid)
        if snap is None:
            video_task_state.release_video_lock(tid)
            return None
        self.stats["tasks"] += 1
        return self._req(snap, snap["cursor"])

    def _req(self, snap: dict, cursor: int, risk_retry: int = 0) -> scrapy.Request:
        device = self.strategy.random_device("general")
        url = query.comments_url(device, snap["aweme_id"], cursor=cursor)
        return scrapy.Request(
            url=url, callback=self.parse, errback=self.on_error, dont_filter=True,
            meta={"task_id": snap["id"], "aweme_id": snap["aweme_id"],
                  "device": device, "risk_retry": risk_retry},
        )

    # ---------- 解析 ----------

    def parse(self, response) -> Iterator[Any]:
        tid = response.meta["task_id"]
        aweme_id = response.meta["aweme_id"]
        objs = decode_stream(response.text)
        if not objs:
            log.warning("评论响应无法解析: %s", response.text[:100])
            video_task_state.fail_video_task(tid, "non-json", partial=True)
            return
        data = objs[0]
        blocked = any(o.get("status_code") == -99999 for o in objs[1:])

        if blocked:
            yield from self._retry_risk(response)
            return

        page = parser.parse_comments(data, aweme_id)
        for it in page["items"]:
            self.stats["comments"] += 1
            yield CommentItem(**it)

        snap = video_task_state.reload_video_task(tid) or {}
        pages = int(snap.get("pages") or 0) + 1
        fetched = int(snap.get("fetched") or 0) + len(page["items"])
        video_task_state.progress_video_task(
            tid, cursor=page["cursor"], pages=pages, fetched=fetched,
            total=page["total"])

        if page["items"] and page["has_more"] and pages < self.comment_pages_limit:
            snap["cursor"] = page["cursor"]
            yield self._req(snap, page["cursor"])
        else:
            video_task_state.complete_video_task(tid)
            log.debug("视频 %s 评论完成：%d 页 / %d 条（total=%s）",
                      aweme_id, pages, fetched, page["total"])

    def _retry_risk(self, response) -> Iterator[Any]:
        """被风控（-99999）：换设备重试同页，不推进 cursor。"""
        tid = response.meta["task_id"]
        attempt = int(response.meta.get("risk_retry") or 0)
        dev = (response.meta.get("device") or {}).get("device_id", "")
        if dev:
            self.strategy.report_risk(dev, attempt + 1)
        self.stats["risk"] += 1
        if attempt >= 2:
            log.info("视频 %s 评论连续被风控，跳过", response.meta["aweme_id"])
            video_task_state.fail_video_task(tid, "risk_limited", partial=True)
            return
        snap = video_task_state.reload_video_task(tid) or {}
        yield self._req(snap, int(snap.get("cursor") or 0), risk_retry=attempt + 1)

    # ---------- 异常与收尾 ----------

    def on_error(self, failure):
        req = failure.request
        tid = req.meta.get("task_id")
        log.warning("评论请求失败 task=%s: %s", tid, failure.value)
        if tid:
            video_task_state.fail_video_task(tid, "request failed: %s" % failure.value,
                                             partial=True)

    def on_closed(self, spider, reason=None):
        try:
            with session_scope() as s:
                rows = (s.query(VideoTask)
                        .filter(VideoTask.status == video_task_state.ST_RUNNING,
                                VideoTask.assigned_worker == self.worker_id)
                        .all())
                for row in rows:
                    row.status = video_task_state.ST_PARTIAL
                    row.assigned_worker = None
                    row.last_error = "spider_closed_early"
            log.info("评论 spider 关闭（%s），收尾 running %d 个", reason, len(rows))
        except Exception as e:
            log.warning("评论 spider 收尾失败: %r", e)
        log.info("评论统计: %s", self.stats)
