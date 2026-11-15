import json, urllib.parse, urllib.request
BASE = "http://127.0.0.1:8099"
AWEME = "7688378193157898395"
def page(cursor, count=50):
    q = urllib.parse.urlencode({"aweme_id": AWEME, "cursor": cursor, "count": count})
    with urllib.request.urlopen(BASE + "/api/comments?" + q, timeout=90) as r:
        j = json.loads(r.read().decode())
    raw = j.get("page", {}).get("raw", "")
    if raw.strip().startswith("<"): return "DENIED"
    try: o = json.loads(raw)
    except Exception: return "BADJSON"
    return (o.get("status_code"), len(o.get("comments") or []), o.get("has_more"))
for cur in (5800, 6000, 6200, 6500, 6800, 7000, 7200, 7500, 8000):
    print("cursor=%-6d -> %s" % (cur, page(cur)))