import json, urllib.parse, urllib.request
BASE = "http://127.0.0.1:8099"
AWEME = "7688378193157898395"
def page(cursor, count=50):
    q = urllib.parse.urlencode({"aweme_id": AWEME, "cursor": cursor, "count": count})
    with urllib.request.urlopen(BASE + "/api/comments?" + q, timeout=60) as r:
        j = json.loads(r.read().decode())
    raw = j.get("page", {}).get("raw", "")
    if raw.strip().startswith("<"):
        return "DENIED", 0, None
    try:
        o = json.loads(raw)
    except Exception:
        return "BADJSON", 0, None
    return o.get("status_code"), len(o.get("comments") or []), o.get("has_more")
for cur in (0, 2500, 2700, 3000, 3500, 5000, 8000, 12000):
    st, n, hm = page(cur)
    print("cursor=%-6d status=%-4s 返回=%-3d has_more=%s" % (cur, st, n, hm))