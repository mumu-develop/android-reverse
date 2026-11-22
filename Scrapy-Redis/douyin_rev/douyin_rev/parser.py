# -*- coding: utf-8 -*-
"""响应解析（站点专属）。

只做「JSON → dict」的字段搬运，不碰网络、不碰数据库。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _first_url(obj: Any) -> Optional[str]:
    """从 {url_list: [...]} 里取第一个 URL。"""
    if isinstance(obj, dict):
        urls = obj.get("url_list") or []
        if urls:
            return urls[0]
    return None


def parse_profile(raw: Dict[str, Any], sec_user_id: str) -> Optional[Dict[str, Any]]:
    """解析用户详情；拿不到 user 时返回 None。"""
    user = raw.get("user") or {}
    if not isinstance(user, dict) or not user:
        return None
    avatar = (_first_url(user.get("avatar_168x168"))
              or _first_url(user.get("avatar_300x300"))
              or _first_url(user.get("avatar_thumb")))
    return {
        "sec_user_id": sec_user_id,
        "uid": str(user.get("uid") or ""),
        "unique_id": str(user.get("unique_id") or ""),
        "short_id": str(user.get("short_id") or ""),
        "nickname": user.get("nickname") or "",
        "signature": user.get("signature") or "",
        "avatar_url": avatar or "",
        "follower_count": int(user.get("follower_count") or 0),
        "following_count": int(user.get("following_count") or 0),
        "aweme_count": int(user.get("aweme_count") or 0),
        "total_favorited": int(user.get("total_favorited") or 0),
    }


def parse_posts(raw: Dict[str, Any], sec_user_id: str) -> Dict[str, Any]:
    """解析作品列表一页。"""
    items: List[Dict[str, Any]] = []
    for a in raw.get("aweme_list") or []:
        st = a.get("statistics") or {}
        video = a.get("video") or {}
        cover = (_first_url(video.get("cover"))
                 or _first_url(video.get("origin_cover"))
                 or _first_url(video.get("dynamic_cover")))
        play = None
        addr = video.get("play_addr") or {}
        if isinstance(addr, dict):
            urls = addr.get("url_list") or []
            if urls:
                play = urls[0]
        items.append({
            "aweme_id": str(a.get("aweme_id") or ""),
            "sec_user_id": sec_user_id,
            "desc": a.get("desc") or "",
            "create_time": int(a.get("create_time") or 0),
            "duration": int(video.get("duration") or 0),
            "digg_count": int(st.get("digg_count") or 0),
            "comment_count": int(st.get("comment_count") or 0),
            "share_count": int(st.get("share_count") or 0),
            "collect_count": int(st.get("collect_count") or 0),
            "play_url": play or "",
            "cover_url": cover or "",
        })
    return {
        "items": items,
        "max_cursor": int(raw.get("max_cursor") or 0),
        "has_more": bool(raw.get("has_more")),
        "status_code": int(raw.get("status_code") or 0),
    }


def parse_comments(raw: Dict[str, Any], aweme_id: str) -> Dict[str, Any]:
    """解析评论一页。"""
    items: List[Dict[str, Any]] = []
    for c in raw.get("comments") or []:
        u = c.get("user") or {}
        items.append({
            "cid": str(c.get("cid") or ""),
            "aweme_id": aweme_id,
            "text": c.get("text") or "",
            "create_time": int(c.get("create_time") or 0),
            "digg_count": int(c.get("digg_count") or 0),
            "reply_total": int(c.get("reply_comment_total") or 0),
            "uid": str(u.get("uid") or ""),
            "nickname": u.get("nickname") or "",
            "sec_uid": str(u.get("sec_uid") or ""),
        })
    return {
        "items": items,
        "cursor": int(raw.get("cursor") or 0),
        "has_more": bool(raw.get("has_more")),
        "total": int(raw.get("total") or 0),
        "status_code": int(raw.get("status_code") or 0),
    }
