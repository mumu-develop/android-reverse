import json, time, urllib.parse, urllib.request
BASE = "http://127.0.0.1:8099"
AWEME = "7688378193157898395"
def page(cursor=0, count=20):
    q = urllib.parse.urlencode({"aweme_id": AWEME, "cursor": cursor, "count": count})
    with urllib.request.urlopen(BASE + "/api/comments?" + q, timeout=90) as r:
        j = json.loads(r.read().decode())
    raw = j.get("page", {}).get("raw", "")
    if raw.strip().startswith("<"): return "DENIED"
    try: o = json.loads(raw)
    except Exception: return "BADJSON"
    return (o.get("status_code"), len(o.get("comments") or []))
t0 = time.time()
for i in range(10):
    r = page()
    el = time.time() - t0
    print("  +%4.0fs -> %s" % (el, r))
    if r != (0, 0) and r != "DENIED":
        print("  ✅ 已恢复，冷却约 %.0f 秒" % el)
        break
    time.sleep(30)