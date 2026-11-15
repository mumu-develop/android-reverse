import json, time, urllib.parse, urllib.request
BASE = "http://127.0.0.1:8099"
def page(cursor=0, count=20, aweme="7688378193157898395"):
    q = urllib.parse.urlencode({"aweme_id": aweme, "cursor": cursor, "count": count})
    try:
        with urllib.request.urlopen(BASE + "/api/comments?" + q, timeout=60) as r:
            j = json.loads(r.read().decode())
        raw = j.get("page", {}).get("raw", "")
        if raw.startswith("<"):
            return None, raw[:60]
        o = json.loads(raw)
        return o, None
    except Exception as e:
        return None, str(e)[:80]
for i in range(1, 4):
    o, err = page(0, 20)
    if o:
        print("第 %d 次: ✅ status=%s 评论=%d" % (i, o.get("status_code"), len(o.get("comments") or [])))
        break
    print("第 %d 次: ❌ %s" % (i, err))
    time.sleep(20)