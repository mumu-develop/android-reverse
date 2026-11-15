import json, urllib.parse, urllib.request
BASE = "http://127.0.0.1:8099"
AWEME = "7688378193157898395"
def page(cursor, count=50):
    q = urllib.parse.urlencode({"aweme_id": AWEME, "cursor": cursor, "count": count})
    with urllib.request.urlopen(BASE + "/api/comments?" + q, timeout=120) as r:
        j = json.loads(r.read().decode())
    raw = j.get("page", {}).get("raw", "")
    try:
        return json.loads(raw), raw
    except Exception:
        return None, raw
for cur in (0, 50, 5000, 7000, 7500, 8000, 10000, 12900):
    o, raw = page(cur)
    if o is None:
        print("cursor=%-6d 解析失败, 原始前 120: %r" % (cur, raw[:120]))
        continue
    cs = o.get("comments") or []
    print("cursor=%-6d 返回=%-3d has_more=%-2s server_cursor=%-12s total=%s"
          % (cur, len(cs), o.get("has_more"), o.get("cursor"), o.get("total")))