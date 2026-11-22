# -*- coding: utf-8 -*-
"""落库管道（站点专属）。

三类 Item 分别 upsert 到三张表：
    ProfileItem → user_profile   （按 sec_user_id）
    VideoItem   → user_videos    （按 aweme_id）
    CommentItem → user_video_comments（按 cid）

用「先查后改」的 upsert，保证重复抓同一用户不会产生重复行。
"""
from __future__ import annotations

import logging
from datetime import datetime

from .db import session_scope
from .db.models import UserProfile, UserVideo, UserVideoComment
from .items import CommentItem, ProfileItem, VideoItem

log = logging.getLogger(__name__)


class PrintItemPipeline:
    """调试用：打一行日志（样板保留）。"""

    def process_item(self, item, spider):
        spider.logger.debug("item: %s", type(item).__name__)
        return item


class ProfilePipeline:
    def process_item(self, item, spider):
        if not isinstance(item, ProfileItem):
            return item
        with session_scope() as s:
            row = (s.query(UserProfile)
                   .filter(UserProfile.sec_user_id == item["sec_user_id"])
                   .one_or_none())
            if row is None:
                row = UserProfile(sec_user_id=item["sec_user_id"])
                s.add(row)
            for f in ("uid", "unique_id", "short_id", "nickname", "signature",
                      "avatar_url", "follower_count", "following_count",
                      "aweme_count", "total_favorited"):
                if f in item:
                    setattr(row, f, item[f])
            row.fetched_at = datetime.now()
        return item


class VideoPipeline:
    def process_item(self, item, spider):
        if not isinstance(item, VideoItem):
            return item
        aweme_id = item.get("aweme_id")
        if not aweme_id:
            return item
        with session_scope() as s:
            row = (s.query(UserVideo)
                   .filter(UserVideo.aweme_id == aweme_id)
                   .one_or_none())
            if row is None:
                row = UserVideo(aweme_id=aweme_id)
                s.add(row)
            for f in ("sec_user_id", "desc", "create_time", "duration",
                      "digg_count", "comment_count", "share_count",
                      "collect_count", "play_url", "cover_url"):
                if f in item:
                    setattr(row, f, item[f])
            row.fetched_at = datetime.now()
        return item


class CommentPipeline:
    def process_item(self, item, spider):
        if not isinstance(item, CommentItem):
            return item
        cid = item.get("cid")
        if not cid:
            return item
        with session_scope() as s:
            row = (s.query(UserVideoComment)
                   .filter(UserVideoComment.cid == cid)
                   .one_or_none())
            if row is None:
                row = UserVideoComment(cid=cid)
                s.add(row)
            for f in ("aweme_id", "text", "create_time", "digg_count",
                      "reply_total", "uid", "nickname", "sec_uid"):
                if f in item:
                    setattr(row, f, item[f])
            row.fetched_at = datetime.now()
        return item
