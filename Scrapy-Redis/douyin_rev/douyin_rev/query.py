# -*- coding: utf-8 -*-
"""URL 构造（站点专属）。

三个接口：
    用户详情  GET https://aweme.snssdk.com/aweme/v1/user/profile/other/
    作品列表  GET https://aweme.snssdk.com/aweme/v1/aweme/post/
    视频评论  GET https://aweme.snssdk.com/aweme/v2/comment/list/

公共参数里的设备字段必须来自 DevicePool 选中的那台设备，
签名时再把同一个 device_id 传给 /api/sign。
"""
from __future__ import annotations

import time
import urllib.parse
from typing import Any, Dict

HOST = "https://aweme.snssdk.com"

PROFILE_PATH = "/aweme/v1/user/profile/other/"
POSTS_PATH = "/aweme/v1/aweme/post/"
COMMENTS_PATH = "/aweme/v2/comment/list/"


def base_params(device: Dict[str, Any]) -> Dict[str, str]:
    """公共参数：设备画像 + App 版本。"""
    return {
        "aid": "1128",
        "app_name": "aweme",
        "version_code": "400200",
        "version_name": "40.2.0",
        "manifest_version_code": "400201",
        "update_version_code": "40209900",
        "device_platform": "android",
        "device_type": str(device.get("model") or "Pixel 6"),
        "device_brand": str(device.get("brand") or "google"),
        "os": "android",
        "os_api": str(device.get("os_api") or 33),
        "os_version": str(device.get("os_version") or "13"),
        "channel": str(device.get("channel") or "huawei_1128_64"),
        "device_id": str(device.get("device_id") or ""),
        "iid": str(device.get("install_id") or ""),
        "cdid": str(device.get("cdid") or ""),
        "resolution": str(device.get("resolution") or "1080*2209"),
        "dpi": str(device.get("dpi") or 420),
        "host_abi": "arm64-v8a",
        "cpu_support64": "true",
        "language": "zh",
        "ac": "wifi",
    }


def _with_ts(params: Dict[str, str]) -> Dict[str, str]:
    """加时间戳参数（防重放）。"""
    ts = int(time.time() * 1000)
    params["_rticket"] = str(ts)
    params["ts"] = str(ts // 1000)
    return params


def profile_url(device: Dict[str, Any], sec_user_id: str) -> str:
    p = base_params(device)
    p.update({
        "sec_user_id": sec_user_id,
        "from": "0",
        "enter_from": "others_homepage",
        "source": "UserProfileFragment_loadAheadExp_SLIDE_PROFILE",
    })
    return HOST + PROFILE_PATH + "?" + urllib.parse.urlencode(_with_ts(p))


def posts_url(device: Dict[str, Any], sec_user_id: str, cursor: int = 0, count: int = 20) -> str:
    p = base_params(device)
    p.update({
        "sec_user_id": sec_user_id,
        "max_cursor": str(cursor),
        "count": str(count),
        "is_other": "1",
        "source": "0",
        "page_from": "2",
        "publish_video_strategy_type": "2",
        "user_avatar_shrink": "96_96",
        "video_cover_shrink": "285_379",
        "need_time_list": "0",
        "show_live_replay_strategy": "1",
    })
    return HOST + POSTS_PATH + "?" + urllib.parse.urlencode(_with_ts(p))


def comments_url(device: Dict[str, Any], aweme_id: str, cursor: int = 0, count: int = 20) -> str:
    p = base_params(device)
    p.update({
        "aweme_id": aweme_id,
        "cursor": str(cursor),
        "count": str(count),
    })
    return HOST + COMMENTS_PATH + "?" + urllib.parse.urlencode(_with_ts(p))
