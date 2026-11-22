# -*- coding: utf-8 -*-
"""数据库引擎工厂（标准样板）。

换库只改环境变量 DY_DB_URL：
    sqlite:///douyin_rev.db                       ← 本地默认，零依赖
    mysql+pymysql://user:pass@127.0.0.1:3306/dy   ← 生产
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .. import config
from .models import ALL_TABLES, Base

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None
_lock = threading.RLock()  # 可重入：get_session 持锁时会再调 get_engine


def db_url() -> str:
    """数据库连接串；默认落地到项目根目录的 sqlite 文件。"""
    url = config.get_str("DY_DB_URL")
    if url:
        return url
    path = config.PROJECT_ROOT / "douyin_rev.db"
    return "sqlite:///" + str(path).replace("\\", "/")


def get_engine(echo: bool = False) -> Engine:
    global _engine
    with _lock:
        if _engine is None:
            url = db_url()
            kwargs = {"echo": echo, "future": True}
            if url.startswith("sqlite"):
                kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
            else:
                kwargs["pool_pre_ping"] = True
                kwargs["pool_recycle"] = 1800
            _engine = create_engine(url, **kwargs)
            if url.startswith("sqlite"):
                from sqlalchemy import event

                @event.listens_for(_engine, "connect")
                def _sqlite_pragma(dbapi_conn, _rec):  # noqa: ANN001
                    cur = dbapi_conn.cursor()
                    cur.execute("PRAGMA journal_mode=WAL")     # 读写并行
                    cur.execute("PRAGMA synchronous=NORMAL")   # 少 fsync，快很多
                    cur.execute("PRAGMA busy_timeout=30000")
                    cur.close()
        return _engine


def init_db(echo: bool = False) -> Engine:
    """建表（幂等）。"""
    engine = get_engine(echo)
    Base.metadata.create_all(engine, tables=[t.__table__ for t in ALL_TABLES])
    return engine


def get_session() -> Session:
    global _session_factory
    if _session_factory is None:
        with _lock:
            if _session_factory is None:
                _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory()


@contextmanager
def session_scope() -> Iterator[Session]:
    """事务上下文：异常回滚，正常提交。"""
    s = get_session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


__all__ = ["Base", "get_engine", "init_db", "get_session", "session_scope", "db_url"]
