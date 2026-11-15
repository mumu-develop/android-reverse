import json, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
BASE = "http://127.0.0.1:8099"
AWEME = "7688378193157898395"
def page(cursor, count=50):
    q = urllib.parse.urlencode({"aweme_id": AWEME, "cursor": cursor, "count": count})
    t0 = time.time()
    try:
        with urllib.request.urlopen(BASE + "/api/comments?" + q, timeout=180) as r:
            j = json.loads(r.read().decode())
        if not j.get("ok"):
            return (cursor, time.time()-t0, False, 0, str(j.get("error"))[:30])
        o = json.loads(j["page"]["raw"])
        return (cursor, time.time()-t0, o.get("status_code")==0, len(o.get("comments") or []), o.get("status_code"))
    except Exception as e:
        return (cursor, time.time()-t0, False, 0, str(e)[:30])
for n in (32, 64):
    cursors = [i*50 for i in range(n)]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=n) as ex:
        res = list(ex.map(lambda c: page(c), cursors))
    wall = time.time()-t0
    ok = sum(1 for r in res if r[2]); got = sum(r[3] for r in res)
    print("并发 %-3d 成功 %d/%d  评论 %d  墙钟 %.1fs  吞吐 %.1f 条/秒"
          % (n, ok, n, got, wall, got/wall if wall else 0))
    bad = [r for r in res if not r[2]]
    if bad: print("   失败样例:", bad[:3])