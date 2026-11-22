# -*- coding: utf-8 -*-
"""抖音 Scrapy-Redis 采集工程（douyin_rev）。

分层与目录遵循 `Scrapy-逆向工程架构标准.md`：
    spiders/  编排
    signer/   签名契约 + unidbg HTTP 签名实现 + 设备池
    tasks/    任务状态机 + 分发器（含 stale-running 自愈）
    db/       引擎工厂 + ORM 表
    middlewares/pipelines  scrapy 粘合
"""

__version__ = "1.0.0"
