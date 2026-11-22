# -*- coding: utf-8 -*-
"""抖音 · 视频评论

接口：本地 unidbg 服务 /api/comments（内部拼 /aweme/v2/comment/list/ 并签名）
用法：
    python dy-video-comments.py <aweme_id|分享链接> [-p 页数] [-c 每页条数] [-o out.json]

注意（实测上限）：
    · 单个视频的评论有「可见深度」上限，大约 cursor 6000-8000 之后返回空页
    · 覆盖率通常 50-60%，不是脚本 bug
    · count 建议 20（50 也可以，服务端对深度更敏感）
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

SERVICE = os.environ.get("DY_SERVICE", "http://127.0.0.1:8099")


def resolve_aweme_id(text):
    """支持纯数字 ID / 分享链接 / 含 aweme_id 的文本"""
    text = (text or "").strip()
    if text.isdigit():
        return text
    for pat in (r'"aweme_id"\s*:\s*"(\d{15,})"', r"aweme_id=(\d{15,})",
                r"/video/(\d{15,})", r"/note/(\d{15,})", r"(\d{19})"):
        m = re.search(pat, text)
        if m:
            return m.group(1)
    raise SystemExit("无法从输入解析 aweme_id: %s" % text[:80])


def fetch_page(aweme_id, cursor, count, retries=3):
    """返回 (comments, next_cursor, has_more, total)"""
    q = urllib.parse.urlencode({"aweme_id": aweme_id, "cursor": cursor, "count": count})
    for i in range(1, retries + 1):
        try:
            with OPENER.open(SERVICE + "/api/comments?" + q, timeout=180) as r:
                outer = json.loads(r.read().decode("utf-8", "ignore"))
            if not outer.get("ok"):
                print("  第 %d 次: 服务返回 ok=false: %s" %
                      (i, str(outer)[:200]), file=sys.stderr)
            else:
                page = outer.get("page") or {}
                raw = page.get("raw") or "{}"
                j = json.loads(raw) if isinstance(raw, str) else raw
                if j.get("status_code") == 0:
                    return (j.get("comments") or [],
                            j.get("cursor", page.get("cursor")),
                            j.get("has_more"), j.get("total"))
                print("  第 %d 次: status_code=%s" %
                      (i, j.get("status_code")), file=sys.stderr)
        except Exception as e:
            print("  第 %d 次异常: %r" % (i, e), file=sys.stderr)
        time.sleep(1.5)
    raise RuntimeError("评论接口连续失败 cursor=%s" % cursor)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="aweme_id 或分享链接")
    ap.add_argument("-p", "--pages", type=int, default=1, help="最多翻几页")
    ap.add_argument("-c", "--count", type=int, default=20, help="每页条数")
    ap.add_argument("-o", "--out", help="保存 JSON 到文件")
    args = ap.parse_args()

    aweme_id = resolve_aweme_id(args.target)
    print("aweme_id:", aweme_id)

    all_comments, cursor, total = [], 0, None
    for page in range(1, args.pages + 1):
        comments, cursor, has_more, total = fetch_page(aweme_id, cursor, args.count)
        all_comments.extend(comments)
        print("第 %d 页: %d 条  has_more=%s  cursor=%s  total=%s" %
              (page, len(comments), has_more, cursor, total))
        if not comments or not has_more:
            break
        cursor = cursor or 0
        time.sleep(0.3)

    print("\n共 %d 条评论（服务端 total=%s）" % (len(all_comments), total))
    for c in all_comments[:5]:
        u = c.get("user") or {}
        print("  %s  %-8s  %s" % (
            c.get("cid"), u.get("nickname", "")[:8],
            (c.get("text") or "").replace("\n", " ")[:40]))

    if args.out:
        json.dump({"aweme_id": aweme_id, "total": total,
                   "comments": all_comments},
                  open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("[+] 已保存", args.out)


if __name__ == "__main__":
    main()
