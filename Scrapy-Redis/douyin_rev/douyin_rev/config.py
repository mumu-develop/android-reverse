# -*- coding: utf-8 -*-
"""环境变量读取（样板文件，站点无关）。

所有配置只从环境变量取，不读死值；`.env` 由 python-dotenv 在导入时加载。
命名前缀统一 DY_，换站时改常量即可。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# 项目根目录（douyin_rev/ 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:  # 可选依赖：没有 python-dotenv 也能跑
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)
except Exception:  # pragma: no cover
    pass


def get_str(name: str, default: Optional[str] = None) -> Optional[str]:
    """读字符串；空字符串视为未设置。"""
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v


def get_int(name: str, default: int) -> int:
    """读整数；解析失败回落默认值。"""
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


def get_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def get_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# ---------- 本工程常用常量（换站只改这里） ----------

#: unidbg 签名服务地址
SIGN_SERVICE = get_str("DY_SIGN_SERVICE", "http://127.0.0.1:8099") or "http://127.0.0.1:8099"

#: 签名服务请求超时（秒）
SIGN_TIMEOUT = get_int("DY_SIGN_TIMEOUT", 120)

#: App 版本参数
APP_VERSION_CODE = get_str("DY_APP_VERSION_CODE", "400200") or "400200"
APP_VERSION_NAME = get_str("DY_APP_VERSION_NAME", "40.2.0") or "40.2.0"
APP_MANIFEST_VERSION_CODE = get_str("DY_APP_MANIFEST", "400201") or "400201"
APP_UPDATE_VERSION_CODE = get_str("DY_APP_UPDATE_CODE", "40209900") or "40209900"

#: 签名服务的设备池文件（/api/register 会追加写，这里直接读，省得重启服务）
DEVICE_FILE = get_str(
    "DY_DEVICE_FILE",
    r"D:\PythonProject\安卓-逆向\unidbg\抖音\devices.jsonl",
)

#: 作品列表可用的「受信任安装」iid 列表（逗号分隔，按优先级）
#: 第一个不行会自动切下一个；全都不行则进入降级模式（只抓详情+评论）
TRUSTED_IIDS = [
    x.strip() for x in (get_str("DY_TRUSTED_IIDS", "") or "").split(",") if x.strip()
]

#: 设备目标数：签名实例有多少个，就保证有多少台设备（不足自动补齐，多了不动）
DEVICE_TARGET = get_int("DY_DEVICE_TARGET", 12)

#: 抓取节奏
DEFAULT_VIDEO_PAGES = get_int("DY_VIDEO_PAGES", 50)      # 单用户最多翻多少页作品（20/页）
DEFAULT_COMMENT_PAGES = get_int("DY_COMMENT_PAGES", 335)  # 单视频最多翻多少页评论（20/页）
REQUEST_DELAY = get_float("DY_DELAY", 0.25)               # 请求间隔（秒）
