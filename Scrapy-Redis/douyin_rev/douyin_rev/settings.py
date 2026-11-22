# -*- coding: utf-8 -*-
"""装配根：换站只改 3 行旋钮。

    SIGNING_STRATEGY   签名实现（load_object 注入中间件）
    FETCHER_STRATEGY   抓取实现（预留）
    QUEUE_PREFIX       scrapy-redis 队列前缀
"""
from __future__ import annotations

import os
from pathlib import Path

from . import config

BOT_NAME = "douyin_rev"
SPIDER_MODULES = ["douyin_rev.spiders"]
NEWSPIDER_MODULE = "douyin_rev.spiders"

# ---------- 换站旋钮（3 行） ----------
SIGNING_STRATEGY = os.environ.get(
    "DY_SIGNING_STRATEGY", "douyin_rev.signer.strategy.UnidbgStrategy")
FETCHER_STRATEGY = os.environ.get(
    "DY_FETCHER_STRATEGY", "douyin_rev.fetcher.RequestsFetcher")
QUEUE_PREFIX = os.environ.get("DY_QUEUE_PREFIX", "douyin_rev")

# ---------- 礼貌与并发 ----------
ROBOTSTXT_OBEY = False
CONCURRENT_REQUESTS = config.get_int("DY_CONCURRENT_REQUESTS", 8)
CONCURRENT_REQUESTS_PER_DOMAIN = config.get_int("DY_CONCURRENT_PER_DOMAIN", 8)
DOWNLOAD_DELAY = config.get_float("DY_DELAY", 0.2)
RANDOMIZE_DOWNLOAD_DELAY = False
DOWNLOAD_TIMEOUT = config.get_int("DY_TIMEOUT", 30)

# 自动限速：服务端软限流时自动降速
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 0.2
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 4.0

# 重试：抖音偶发空响应/超时，重试 3 次
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [429, 500, 502, 503, 504, 408]

# ---------- scrapy-redis ----------
SCHEDULER = "scrapy_redis.scheduler.Scheduler"
DUPEFILTER_CLASS = "scrapy_redis.dupefilter.RFPDupeFilter"
SCHEDULER_PERSIST = True          # 队列/去重集合不因退出而清空（断点续跑前提）
SCHEDULER_FLUSH_ON_START = False

REDIS_HOST = config.get_str("REDIS_HOST", "127.0.0.1")
REDIS_PORT = config.get_int("REDIS_PORT", 6379)
REDIS_DB = config.get_int("REDIS_DB", 0)
REDIS_URL = config.get_str("DY_REDIS_URL") or "redis://%s:%d/%d" % (
    REDIS_HOST, REDIS_PORT, REDIS_DB)

# start_urls 队列键（与 tasks/dispatcher.py 保持一致）
REDIS_START_URLS_KEY = "%s:start_urls" % QUEUE_PREFIX
REDIS_START_URLS_AS_SET = False

# ---------- 中间件 / 管道 ----------
DOWNLOADER_MIDDLEWARES = {
    "douyin_rev.middlewares.SignerMiddleware": 543,
}

ITEM_PIPELINES = {
    "douyin_rev.pipelines.ProfilePipeline": 300,
    "douyin_rev.pipelines.VideoPipeline": 310,
    "douyin_rev.pipelines.CommentPipeline": 320,
}

# ---------- 日志 ----------
LOG_LEVEL = os.environ.get("DY_LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

# ---------- 其它 ----------
TELNETCONSOLE_ENABLED = False
COOKIES_ENABLED = False
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"

# 项目根（脚本里定位 .env / db 文件）
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
