# -*- coding: utf-8 -*-
"""ORM 表（站点专属）。

四张表：
    user_task            任务队列（主页链接）
    user_profile         用户详情
    user_videos          作品（视频）列表
    user_video_comments  视频评论

断点续跑字段都在 user_task 上：
    video_cursor       作品列表的 max_cursor（抖音是毫秒时间戳，BigInteger）
    video_pages        已翻页数
    video_index        评论阶段：处理到第几个视频
    comment_aweme_id   评论阶段：当前视频 ID
    comment_cursor     评论 cursor（纯数字，Integer）
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def _now() -> datetime:
    return datetime.now()


class UserTask(Base):
    """任务表：一行 = 一个用户主页。"""

    __tablename__ = "user_task"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_url = Column(String(512), nullable=False, unique=True)
    sec_user_id = Column(String(128), index=True)

    # pending / running / paused / partial / completed / failed
    status = Column(String(16), nullable=False, default="pending", index=True)
    priority = Column(Integer, nullable=False, default=0)
    assigned_worker = Column(String(64))

    # 阶段完成标记
    profile_done = Column(Boolean, nullable=False, default=False)
    videos_done = Column(Boolean, nullable=False, default=False)
    comments_done = Column(Boolean, nullable=False, default=False)

    # 断点（作品翻页）
    video_cursor = Column(BigInteger, nullable=False, default=0)
    video_pages = Column(Integer, nullable=False, default=0)

    # 断点（评论翻页）
    video_index = Column(Integer, nullable=False, default=0)
    comment_aweme_id = Column(String(64))
    comment_cursor = Column(Integer, nullable=False, default=0)
    comment_pages = Column(Integer, nullable=False, default=0)

    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String(512))
    created_at = Column(DateTime, nullable=False, default=_now)
    updated_at = Column(DateTime, nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        Index("idx_user_task_status_prio", "status", "priority"),
    )


class UserProfile(Base):
    """用户详情。"""

    __tablename__ = "user_profile"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sec_user_id = Column(String(128), nullable=False, unique=True)
    uid = Column(String(64), index=True)
    unique_id = Column(String(64), index=True)      # 抖音号
    short_id = Column(String(64))
    nickname = Column(String(255))
    signature = Column(Text)
    avatar_url = Column(String(1024))
    follower_count = Column(BigInteger, default=0)
    following_count = Column(BigInteger, default=0)
    aweme_count = Column(BigInteger, default=0)
    total_favorited = Column(BigInteger, default=0)
    fetched_at = Column(DateTime, nullable=False, default=_now)


class UserVideo(Base):
    """作品列表。"""

    __tablename__ = "user_videos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    aweme_id = Column(String(64), nullable=False, unique=True)
    sec_user_id = Column(String(128), nullable=False, index=True)
    desc = Column(Text)
    create_time = Column(BigInteger, default=0)
    duration = Column(Integer, default=0)
    digg_count = Column(BigInteger, default=0)
    comment_count = Column(BigInteger, default=0)
    share_count = Column(BigInteger, default=0)
    collect_count = Column(BigInteger, default=0)
    play_url = Column(String(1024))
    cover_url = Column(String(1024))
    fetched_at = Column(DateTime, nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint("aweme_id", name="uq_user_videos_aweme_id"),
    )


class UserVideoComment(Base):
    """视频评论。"""

    __tablename__ = "user_video_comments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cid = Column(String(64), nullable=False, unique=True)
    aweme_id = Column(String(64), nullable=False, index=True)
    text = Column(Text)
    create_time = Column(BigInteger, default=0)
    digg_count = Column(BigInteger, default=0)
    reply_total = Column(Integer, default=0)
    uid = Column(String(64))
    nickname = Column(String(255))
    sec_uid = Column(String(128))
    fetched_at = Column(DateTime, nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint("cid", name="uq_user_video_comments_cid"),
    )


ALL_TABLES = (UserTask, UserProfile, UserVideo, UserVideoComment)
