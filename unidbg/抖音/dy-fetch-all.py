#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抖音评论全量并发抓取（限流友好版）

相比初版的三处优化：
  1. 全局令牌桶：整体速率受控（默认 8 req/s），而不是"每个设备各自限速后一起爆发"
  2. 提前止损：连续 N 页空结果就停，不白打请求
  3. 断点续抓：每页落盘，中断后 --resume 从断点继续

用法：
    python dy-fetch-all.py <aweme_id|分享链接> [-o out.json]
    python dy-fetch-all.py <...> --resume          # 从断点继续
    python dy-fetch-all.py <...> -c 4 -r 8 -m 150  # 并发4 / 8req每秒 / 最多150页

实测（13013 条的视频）：
    并发 4、8 req/s、150 页 → 约 20-40 秒，能拿到 6000-7000 条（服务端深度上限）
"""
import argparse
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.environ.get("DY_SERVICE", "http://127.0.0.1:8099").rstrip("/")
UA_MOBILE = ("Mozilla/5.0 (Linux; Android 13; Pixel 6) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")


class TokenBucket:
    """全局令牌桶：整体速率上限"""

    def __init__(self, rate_per_sec):
        self.rate = max(0.1, float(rate_per_sec))
        self.capacity = max(1.0, self.rate)
        self.tokens = self.capacity
        self.last = time.time()
        self.lock = threading.Lock()

    def take(self):
        while True:
            with self.lock:
                now = time.time()
                self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
                self.last = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                need = (1 - self.tokens) / self.rate
            time.sleep(min(need, 0.5))


def resolve_aweme_id(text):
    text = text.strip()
    if re.fullmatch(r"\d{15,}", text):
        return text
    m = re.search(r"(https?://v\.douyin\.com/[\w\-]+/?)", text)
    url = m.group(1) if m else text
    req = urllib.request.Request(url, headers={"User-Agent": UA_MOBILE})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=30) as r:
        final = r.geturl()
        html = r.read().decode("utf-8", "ignore")
    m = re.search(r"/video/(\d{15,})", final)
    if m:
        return m.group(1)
    for pat in (r'"aweme_id"\s*:\s*"(\d{15,})"', r"aweme_id=(\d{15,})",
                r"/share/video/(\d{15,})"):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    raise RuntimeError("无法从链接解析 aweme_id")


def fetch_page(bucket, aweme_id, cursor, count, timeout=180, max_wait=6):
    """返回 (cursor, comments, has_more, total, 是否失败)

    服务端在冷却时会返回 ok=false + "冷却中"，这里自动等待重试，
    不把这个计入"空页"，避免误判提前停止。
    """
    for _ in range(max_wait):
        bucket.take()
        q = urllib.parse.urlencode({"aweme_id": aweme_id, "cursor": cursor, "count": count})
        url = BASE + "/api/comments?" + q
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                j = json.loads(r.read().decode("utf-8"))
            if not j.get("ok"):
                err = str(j.get("error", ""))
                if "冷却" in err:
                    m = re.search(r"剩余 (\d+) 秒", err)
                    wait = int(m.group(1)) + 2 if m else 15
                    print("      [~] 服务端冷却中，等待 %d 秒" % wait, flush=True)
                    time.sleep(min(wait, 130))
                    continue
                return cursor, [], None, None, True
            raw = j["page"]["raw"]
            if raw.strip().startswith("<"):
                return cursor, [], None, None, True
            o = json.loads(raw)
            if o.get("status_code") != 0:
                return cursor, [], None, None, True
            return cursor, o.get("comments") or [], o.get("has_more"), o.get("total"), False
        except Exception:
            return cursor, [], None, None, True
    return cursor, [], None, None, True


def main():
    ap = argparse.ArgumentParser(description="抖音评论并发抓取（限流友好版）")
    ap.add_argument("target", help="aweme_id 或分享链接")
    ap.add_argument("-c", "--concurrency", type=int, default=4, help="并发（默认 4）")
    ap.add_argument("-r", "--rate", type=float, default=8.0, help="全局请求速率上限（默认 8/s）")
    ap.add_argument("-n", "--count", type=int, default=50, help="每页条数（上限 50）")
    ap.add_argument("-m", "--max-pages", type=int, default=150, help="最大页数（默认 150，覆盖约 7500 条）")
    ap.add_argument("--stop-empty", type=int, default=5, help="连续多少页空结果就停（默认 5）")
    ap.add_argument("-o", "--out", default="comments.json", help="输出文件")
    ap.add_argument("--resume", action="store_true", help="从断点文件继续")
    args = ap.parse_args()

    aweme_id = resolve_aweme_id(args.target)
    print("[*] aweme_id =", aweme_id)

    state_path = args.out + ".parts.jsonl"
    done_cursors = set()
    comments_by_cid = {}

    if args.resume and os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                done_cursors.add(rec["cursor"])
                for c in rec.get("comments", []):
                    comments_by_cid[c.get("cid")] = c
        print("[*] 续抓：已有 %d 页 / %d 条" % (len(done_cursors), len(comments_by_cid)))

    bucket = TokenBucket(args.rate)
    print("[*] 限速 %.1f req/s，并发 %d，最多 %d 页" % (args.rate, args.concurrency, args.max_pages))

    # 首屏
    _, first, has_more, total, failed = fetch_page(bucket, aweme_id, 0, args.count)
    if failed or total is None:
        print("[!] 首屏失败，检查服务（python dy-unidbg.py health）")
        return 1
    for c in first:
        comments_by_cid[c.get("cid")] = c
    print("[*] total=%d，首屏 %d 条" % (total, len(first)))

    pages = min(args.max_pages, max(1, -(-total // args.count)))
    cursors = [i * args.count for i in range(1, pages)
               if i * args.count not in done_cursors]
    print("[*] 待抓 %d 页\n" % len(cursors))

    state_lock = threading.Lock()
    state_file = open(state_path, "a", encoding="utf-8")
    progress = {"n": 0}
    empty_streak = {"v": 0}
    stop = threading.Event()
    t0 = time.time()

    def record(cur, cs):
        with state_lock:
            state_file.write(json.dumps({"cursor": cur, "comments": cs},
                                        ensure_ascii=False) + "\n")
            state_file.flush()

    def work(cur):
        if stop.is_set():
            return None
        r = fetch_page(bucket, aweme_id, cur, args.count)
        return r

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futs = {ex.submit(work, c): c for c in cursors}
        for f in as_completed(futs):
            r = f.result()
            if r is None:
                continue
            cur, cs, hm, tot, failed = r
            with state_lock:
                progress["n"] += 1
                for c in cs:
                    comments_by_cid[c.get("cid")] = c
                if not failed:
                    record(cur, cs)
                n = progress["n"]

            if failed or not cs:
                empty_streak["v"] += 1
                if empty_streak["v"] >= args.stop_empty:
                    stop.set()
                    for ff in futs:
                        ff.cancel()
                    print("  [!] 连续 %d 页空/失败，提前停止（服务端深度上限或限流）"
                          % args.stop_empty)
                    break
            else:
                empty_streak["v"] = 0

            if n % 10 == 0:
                el = time.time() - t0
                print("  [%3d/%3d] 已抓 %5d 条  %.1fs  %.0f 条/s"
                      % (n, len(cursors), len(comments_by_cid), el,
                         len(comments_by_cid) / el if el else 0), flush=True)

    state_file.close()
    wall = time.time() - t0
    allc = list(comments_by_cid.values())
    print("\n[*] 完成：%d 条（去重后），用时 %.1fs" % (len(allc), wall))
    if total:
        print("[*] 覆盖率 %.1f%%（%d/%d）" % (100.0 * len(allc) / total, len(allc), total))

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"aweme_id": aweme_id, "total": total, "fetched": len(allc),
                   "elapsed_s": round(wall, 1), "comments": allc},
                  f, ensure_ascii=False, indent=1)
    print("[*] 已写入 %s (%.1f MB)" % (args.out, os.path.getsize(args.out) / 1048576))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
