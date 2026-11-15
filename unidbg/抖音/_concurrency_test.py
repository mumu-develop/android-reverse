import json, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "http://127.0.0.1:8099"
AWEME = "7688378193157898395"

def page(cursor, count=20):
    q = urllib.parse.urlencode({"aweme_id": AWEME, "cursor": cursor, "count": count})
    t0 = time.time()
    try:
        with urllib.request.urlopen(BASE + "/api/comments?" + q, timeout=120) as r:
            j = json.loads(r.read().decode())
        dt = time.time() - t0
        if not j.get("ok"):
            return (cursor, dt, False, 0, str(j.get("error"))[:40])
        raw = j["page"]["raw"]
        o = json.loads(raw)
        return (cursor, dt, o.get("status_code") == 0, len(o.get("comments") or []), o.get("total"))
    except Exception as e:
        return (cursor, time.time() - t0, False, 0, str(e)[:40])

# 单页探底
print("=== count 上限测试 ===")
for c in (20, 50, 100):
    r = page(0, c)
    print("  count=%-4d status_ok=%s 返回=%d total=%s" % (c, r[2], r[3], r[4]))
    if not r[2]:
        print("     错误:", r[4])

# 并发测试
for n in (4, 8, 16):
    cursors = [i * 20 for i in range(n)]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=n) as ex:
        results = list(ex.map(lambda c: page(c), cursors))
    wall = time.time() - t0
    ok = sum(1 for r in results if r[2])
    got = sum(r[3] for r in results)
    avg = sum(r[1] for r in results) / len(results)
    print("\n=== 并发 %d ===" % n)
    print("  成功 %d/%d  评论 %d 条  墙钟 %.1fs  单请求均值 %.2fs" % (ok, n, got, wall, avg))
    bad = [r for r in results if not r[2]]
    if bad:
        print("  失败样例:", bad[:2])