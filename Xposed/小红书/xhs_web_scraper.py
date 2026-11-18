#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书 · 免登录采集（Web SSR + TLS 指纹模拟）

原理：
    1. curl_cffi 用 Chrome 的 TLS 指纹访问网页
    2. 页面里 <script>window.__INITIAL_STATE__=...</script> 内嵌了数据
       - 发现页: .feed.feeds        → 推荐流笔记列表
       - 用户页: .user.notes        → 该作者的笔记列表
       - 笔记页: .note.noteDetailMap → 笔记详情（正文/图片/互动数/评论）
    3. 全程不登录、不签名、不碰手机

用法：
    python xhs_web_scraper.py feed                 # 推荐流 20 条
    python xhs_web_scraper.py feed --detail 5      # 前 5 条再取详情
    python xhs_web_scraper.py note <id> <xsec_token>
    python xhs_web_scraper.py user <user_id>       # 作者主页的笔记列表
    python xhs_web_scraper.py batch --pages 3 --out notes.jsonl
"""
import argparse
import json
import re
import sys
import time

from curl_cffi import requests as cr

BASE = "https://www.xiaohongshu.com"
IMPERSONATE = "chrome"
TIMEOUT = 30


def _get(url: str, **kw):
    return cr.get(url, impersonate=IMPERSONATE, timeout=TIMEOUT, verify=False,
                  allow_redirects=True, **kw)


def _state(html: str):
    """从页面中提取 window.__INITIAL_STATE__"""
    i = html.find("__INITIAL_STATE__=")
    if i < 0:
        return None
    s = html[i + len("__INITIAL_STATE__="):]
    # 找到与之匹配的 JSON 结束位置（后面是 </script>）
    end = s.find("</script>")
    raw = s[:end].rstrip().rstrip(";")
    raw = raw.replace("undefined", "null")
    try:
        return json.loads(raw)
    except Exception:
        # 兜底：截到最后一个 } 再试
        for cut in range(len(raw), 0, -1):
            if raw[cut - 1] == "}":
                try:
                    return json.loads(raw[:cut])
                except Exception:
                    continue
    return None


def _note_from_card(card: dict) -> dict:
    nc = card.get("noteCard") or {}
    user = nc.get("user") or {}
    inter = nc.get("interactInfo") or {}
    cover = nc.get("cover") or {}
    return {
        "id": card.get("id"),
        "xsecToken": card.get("xsecToken"),
        "type": nc.get("type"),
        "title": nc.get("displayTitle") or nc.get("title") or "",
        "user": {
            "id": user.get("userId"),
            "name": user.get("nickname") or user.get("nickName"),
            "xsecToken": user.get("xsecToken"),
        },
        "likes": inter.get("likedCount"),
        "collected": inter.get("collectedCount"),
        "comments": inter.get("commentCount"),
        "cover": cover.get("urlDefault") or cover.get("url"),
        "url": "%s/explore/%s?xsec_token=%s&xsec_source=pc_feed" % (
            BASE, card.get("id"), card.get("xsecToken") or ""),
    }


# ------------------------------------------------------------------ 推荐流

def fetch_feed() -> list:
    r = _get(BASE + "/explore")
    st = _state(r.text)
    if not st:
        return []
    feeds = ((st.get("feed") or {}).get("feeds")) or []
    return [_note_from_card(c) for c in feeds if c.get("modelType", "note") == "note"]


# ------------------------------------------------------------------ 笔记详情

def fetch_note(note_id: str, xsec_token: str = "", xsec_source: str = "pc_feed") -> dict:
    url = "%s/explore/%s" % (BASE, note_id)
    if xsec_token:
        url += "?xsec_token=%s&xsec_source=%s" % (xsec_token, xsec_source)
    r = _get(url)
    st = _state(r.text)
    if not st:
        return {"id": note_id, "error": "无 __INITIAL_STATE__"}
    note_map = ((st.get("note") or {}).get("noteDetailMap")) or {}
    data = note_map.get(note_id) or (list(note_map.values())[0] if note_map else {})
    if not data:
        return {"id": note_id, "error": "noteDetailMap 为空（可能已删除或无权限）"}
    note = data.get("note") or {}
    user = note.get("user") or {}
    inter = note.get("interactInfo") or {}
    images = [i.get("urlDefault") or i.get("url") for i in (note.get("imageList") or [])]
    tags = [t.get("name") for t in (note.get("tagList") or [])]
    comments = []
    for c in ((data.get("comments") or {}).get("list") or []):
        comments.append({
            "id": c.get("id"),
            "content": c.get("content"),
            "user": (c.get("userInfo") or {}).get("nickname"),
            "likes": c.get("likeCount"),
        })
    return {
        "id": note.get("noteId") or note_id,
        "title": note.get("title") or "",
        "desc": note.get("desc") or "",
        "type": note.get("type"),
        "time": note.get("time"),
        "ipLocation": note.get("ipLocation"),
        "user": {"id": user.get("userId"), "name": user.get("nickname") or user.get("nickName")},
        "interact": {
            "liked": inter.get("likedCount"),
            "collected": inter.get("collectedCount"),
            "comment": inter.get("commentCount"),
            "share": inter.get("shareCount"),
        },
        "tags": tags,
        "images": images,
        "video": ((note.get("video") or {}).get("media") or {}).get("stream"),
        "comments": comments,
        "url": url,
    }


# ------------------------------------------------------------------ 作者主页

def fetch_user(user_id: str, xsec_token: str = "") -> dict:
    url = "%s/user/profile/%s" % (BASE, user_id)
    if xsec_token:
        url += "?xsec_token=%s&xsec_source=pc_note" % xsec_token
    r = _get(url)
    st = _state(r.text)
    if not st:
        return {"user_id": user_id, "notes": [], "error": "无 __INITIAL_STATE__"}
    u = st.get("user") or {}
    page = u.get("userPageData") or {}
    basic = page.get("basicInfo") or page.get("result", {}).get("basicInfo") or {}
    notes = []
    for group in (u.get("notes") or []):
        if not isinstance(group, list):
            continue
        for card in group:
            if isinstance(card, dict) and card.get("noteCard"):
                notes.append(_note_from_card(card))
    queries = u.get("noteQueries") or []
    return {
        "user_id": user_id,
        "nickname": basic.get("nickname") or (page.get("basicInfo") or {}).get("nickname"),
        "desc": basic.get("desc"),
        "fans": page.get("interactions", [{}])[0].get("count") if page.get("interactions") else None,
        "notes": notes,
        "hasMore": bool(queries and queries[0].get("hasMore")),
        "cursor": (queries[0].get("cursor") if queries else None),
        "url": url,
    }


# ------------------------------------------------------------------ CLI

def cmd_feed(args):
    items = fetch_feed()
    print("推荐流: %d 条" % len(items))
    for it in items[:args.limit]:
        print("  %s  赞%-6s %-22s %s" % (it["id"], it["likes"], (it["user"]["name"] or "")[:20], it["title"][:30]))
    if args.out and items:
        with open(args.out, "a", encoding="utf-8") as f:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
        print("已写入", args.out)
    for it in items[:args.detail]:
        time.sleep(0.8)
        d = fetch_note(it["id"], it["xsecToken"])
        if d.get("error"):
            print("  详情失败 %s: %s" % (it["id"], d["error"]))
        else:
            print("  详情 %s | %s | 赞%s 藏%s 评%s | 图%d 标签%d" % (
                d["id"], (d["title"] or d["desc"])[:24],
                d["interact"]["liked"], d["interact"]["collected"], d["interact"]["comment"],
                len(d["images"]), len(d["tags"])))
    return 0


def cmd_note(args):
    d = fetch_note(args.note_id, args.token)
    print(json.dumps(d, ensure_ascii=False, indent=1)[:2500])
    return 0


def cmd_user(args):
    u = fetch_user(args.user_id, args.token or "")
    print("作者: %s (%s)  笔记 %d 条  hasMore=%s" % (u.get("nickname"), args.user_id, len(u["notes"]), u.get("hasMore")))
    for n in u["notes"][:args.limit]:
        print("  %s  赞%-6s %s" % (n["id"], n["likes"], n["title"][:34]))
    if args.out:
        with open(args.out, "a", encoding="utf-8") as f:
            for n in u["notes"]:
                f.write(json.dumps(n, ensure_ascii=False) + "\n")
        print("已写入", args.out)
    return 0


def cmd_batch(args):
    total = 0
    for p in range(args.pages):
        items = fetch_feed()
        print("[第 %d 轮] 推荐流 %d 条" % (p + 1, len(items)))
        for it in items:
            d = fetch_note(it["id"], it["xsecToken"])
            if d.get("error"):
                continue
            total += 1
            if args.out:
                with open(args.out, "a", encoding="utf-8") as f:
                    f.write(json.dumps(d, ensure_ascii=False) + "\n")
            print("   %s %s" % (d["id"], (d["title"] or d["desc"])[:30]))
            time.sleep(args.delay)
        time.sleep(2)
    print("共采集 %d 条笔记" % total)
    return 0


def main():
    ap = argparse.ArgumentParser(description="小红书免登录采集（Web SSR）")
    sub = ap.add_subparsers(dest="cmd")

    p1 = sub.add_parser("feed")
    p1.add_argument("--limit", type=int, default=10)
    p1.add_argument("--detail", type=int, default=0)
    p1.add_argument("--out", default=None)

    p2 = sub.add_parser("note")
    p2.add_argument("note_id")
    p2.add_argument("token", nargs="?", default="")

    p3 = sub.add_parser("user")
    p3.add_argument("user_id")
    p3.add_argument("--token", default="")
    p3.add_argument("--limit", type=int, default=20)
    p3.add_argument("--out", default=None)

    p4 = sub.add_parser("batch")
    p4.add_argument("--pages", type=int, default=2)
    p4.add_argument("--delay", type=float, default=1.0)
    p4.add_argument("--out", default="notes.jsonl")

    args = ap.parse_args()
    if args.cmd == "feed":
        return cmd_feed(args)
    if args.cmd == "note":
        return cmd_note(args)
    if args.cmd == "user":
        return cmd_user(args)
    if args.cmd == "batch":
        return cmd_batch(args)
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
