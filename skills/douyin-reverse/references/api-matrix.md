# 业务接口对照表（40.2.0 实测）

只写「能直接拿去发请求」的部分：路径、必需参数、返回字段、身份要求、坑。

> 签名统一走六神（X-Argus 等六个头），这里不重复；参数里的设备身份必须与签名设备一致，
> 或者按本文的「身份要求」列走匿名。

---

## 1. 用户详情（profile）

```
GET https://aweme.snssdk.com/aweme/v1/user/profile/other/
```

| 参数 | 说明 |
|---|---|
| `sec_user_id` | 必填，`MS4wLjABAAAA...`（主页链接里那一段） |
| `from` | `0` |
| `enter_from` | `others_homepage` |
| `source` | `UserProfileFragment_loadAheadExp_SLIDE_PROFILE` |
| 公共参数 | `aid=1128`、`app_name=aweme`、`version_code=400200`、`device_platform=android`、`device_id`、`iid`、`cdid`、`device_type`、`device_brand`、`os_api`、`os_version`、`channel`、`resolution`、`dpi`、`host_abi`、`cpu_support64`、`language`、`ac`、`_rticket`、`ts` |

**身份要求：必须真实 `iid`。** `iid=0` 会返回 `status_code=0` 但 `user` 为空对象 ——
不报错，只是没数据，最容易误判。

返回（`status_code=0` 时）：

```json
{"status_code":0, "user": {
   "uid":"26032275471998", "sec_uid":"MS4wLjABAAAA...", "unique_id":"txt.bighitent",
   "short_id":"0", "nickname":"...", "signature":"...",
   "avatar_168x168":{"url_list":["https://p3.douyinpic.com/..."]},
   "follower_count":1770662, "following_count":0,
   "aweme_count":1000, "total_favorited":178571234,
   "account_cert_info":"{\"label_style\":3,\"label_text\":\"...\"}"
}}
```

- 大小约 16-17KB，136-141 个字段
- `unique_id` 就是「抖音号」，但**不能用它反查**：接口只认 `sec_user_id`
- `sec_user_id` 从哪来：主页链接 `/user/MS4wLjABAAAA...`，或评论返回里的 `user.sec_uid`

---

## 2. 作品列表（posts）

```
GET https://aweme.snssdk.com/aweme/v1/aweme/post/
```

| 参数 | 说明 |
|---|---|
| `sec_user_id` | 必填 |
| `max_cursor` | 首页 `0`，之后用上一页返回的 `max_cursor` |
| `count` | 建议 20（最大 50） |
| `is_other` | `1` |
| `source` | `0` |
| `page_from` | `2` |
| `publish_video_strategy_type` | `2` |
| `user_avatar_shrink` / `video_cover_shrink` | `96_96` / `285_379` |
| 公共参数 | 同 profile |

**身份要求：匿名 `iid=0` 即可。** 这是反直觉但实测最稳的一条：

| `iid` | 结果 |
|---|---|
| 真机 iid | ✅ |
| 新注册 iid（`new_user=1`） | ❌ HTTP 200 + **空 body（0 字节）** |
| `iid=0` | ✅（100 次压测 100/100 成功） |

返回：

```json
{"status_code":0, "aweme_list":[{ "aweme_id":"7705042600633553316", "desc":"...",
   "create_time":1792..., "statistics":{"digg_count":103630,"comment_count":1400,...},
   "video":{"duration":..., "cover":{"url_list":[...]}, "play_addr":{"url_list":[...]}},
   "author":{ "uid":"...", "sec_uid":"...", "nickname":"...", "unique_id":"...",
              "signature":"...", "avatar_168x168":{...} } }],
 "max_cursor":1792464169000, "has_more":1}
```

- `max_cursor` 是**毫秒时间戳**（BIGINT），不是页码
- 响应体大：20 条约 500KB
- `author` 里有昵称/uid/sec_uid/签名/头像，但**没有粉丝数/作品数/获赞** ——
  所以作品列表不能替代详情做统计字段

翻页：`has_more=1` 才继续，下一页传上一页的 `max_cursor`。

---

## 3. 视频评论（comments）

```
GET https://aweme.snssdk.com/aweme/v2/comment/list/
```

| 参数 | 说明 |
|---|---|
| `aweme_id` | 必填，视频 ID |
| `cursor` | 首页 `0`，之后用返回的 `cursor` |
| `count` | 20（最大 50） |
| 公共参数 | 同 profile |

**身份要求：任意。** 真实 iid 或 `iid=0` 都能抓，新设备也可用。

返回：

```json
{"status_code":0, "comments":[{"cid":"...", "text":"...", "aweme_id":"...",
   "create_time":1794..., "digg_count":2, "reply_comment_total":0,
   "user":{"uid":"...","sec_uid":"...","nickname":"...","avatar_thumb":{...}}}],
 "cursor":20, "has_more":1, "total":11272}
```

- 单视频深度上限：约 6688 条（`cursor≈6680` 处 `has_more=0`），覆盖率约 59%
- 限流时返回「两个 JSON 拼接」（见 `traps.md` A1）

---

## 4. 三接口对比速查

| 维度 | 详情 | 作品列表 | 评论 |
|---|---|---|---|
| 身份要求 | 真实 iid | **匿名 iid=0** | 任意 |
| `iid=0` 表现 | user 空 | ✅ 正常 | ✅ 正常 |
| 新注册 iid | ✅ 正常 | ❌ 空 body | ✅ 正常 |
| 分页字段 | 无 | `max_cursor`（毫秒时间戳） | `cursor`（整数） |
| 单页大小 | 16-17KB | 约 500KB | 约 20-40KB |
| 单次耗时 | 0.5-0.6s | 1.0-1.3s | 0.23-0.55s |
| 深度上限 | — | 无（可翻到底） | 约 6688 条 |

## 5. 最小可跑示例（Python，本机签名服务）

```python
import os, json, time, urllib.parse, urllib.request
os.environ["NO_PROXY"] = "127.0.0.1,localhost"          # 否则会被系统代理劫持
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))

SVC  = "http://127.0.0.1:8099"
HOST = "https://aweme.snssdk.com"
SEC  = "MS4wLjABAAAA..."                                # 主页链接里那段

def common(dev, iid):
    p = {"aid":"1128","app_name":"aweme","version_code":"400200","version_name":"40.2.0",
         "manifest_version_code":"400201","update_version_code":"40209900",
         "device_platform":"android","device_type":dev["model"],"device_brand":dev["brand"],
         "os":"android","os_api":str(dev["os_api"]),"os_version":dev["os_version"],
         "channel":dev["channel"],"device_id":dev["device_id"],"iid":iid,"cdid":dev["cdid"],
         "resolution":dev["resolution"],"dpi":str(dev["dpi"]),"host_abi":"arm64-v8a",
         "cpu_support64":"true","language":"zh","ac":"wifi"}
    ts = int(time.time()*1000); p["_rticket"] = str(ts); p["ts"] = str(ts//1000)
    return p

def call(path, params, dev_id):
    url = HOST + path + "?" + urllib.parse.urlencode(params)
    h = json.loads(op.open(SVC + "/api/sign?" + urllib.parse.urlencode(
        {"url": url, "device": dev_id})).read())["headers"]
    h["User-Agent"] = "com.ss.android.ugc.aweme/400200 (Linux; U; Android 13; zh_CN; Pixel 6)"
    with op.open(urllib.request.Request(url, headers=h), timeout=30) as r:
        return json.loads(r.read() or b"{}")

# 详情：真实 iid
p = common(dev, dev["install_id"]); p.update(sec_user_id=SEC, **{"from":"0"})
profile = call("/aweme/v1/user/profile/other/", p, dev["device_id"])

# 作品列表：匿名 iid=0
p = common(dev, "0"); p.update(sec_user_id=SEC, max_cursor=0, count=20, is_other=1)
posts = call("/aweme/v1/aweme/post/", p, dev["device_id"])

# 评论：任意
p = common(dev, dev["install_id"]); p.update(aweme_id="7706919082587489017", cursor=0, count=20)
comments = call("/aweme/v2/comment/list/", p, dev["device_id"])
```

设备画像（`dev`）从签名服务的 `GET /api/devices` 拿，或自己维护一份。

---

## 6. 搜索（40.2.0 实测）

搜索有**两个列表接口**，按 tab 分工，别找错：

| 用途 | 接口 | 方法 | 关键参数位置 |
|---|---|---|---|
| 综合首屏 | `/aweme/v2/search/general/single/` | GET | query（`keyword`） |
| 综合滚动加载 | `/aweme/v2/search/general/stream/` | GET | query |
| **视频 tab / 翻页** | **`/aweme/v2/search/item/`** | **POST** | **表单 body** |
| 联想词 | `tsearch.amemv.com/aweme/v1/search/vtag/` | POST | body |
| 相关搜索 | `/aweme/v1/search/refresh_related_search/` | GET | query |
| 热榜 | `api.amemv.com/aweme/v1/hot/search/list/` | GET | query |
| 预取回执 | `/aweme/v2/search/general/prefetch/ack/` | GET | query（无数据，只有 `ok`） |

### 6.1 `search/item` 请求（列表主力）

```
POST https://aweme.snssdk.com/aweme/v2/search/item/?<公共参数>
Content-Type: application/x-www-form-urlencoded

keyword=火锅&cursor=0&count=12&search_scene=douyin_search
&query_correct_type=1&token=search&enter_from=...
```

| body 字段 | 说明 |
|---|---|
| `keyword` | 搜索词（URL 编码） |
| `cursor` | 首页 `0`，之后用上一页返回的 `cursor`，实测每页 **+12** |
| `count` | 实测 **12** |
| `search_scene` | `douyin_search` |
| `query_correct_type` | `1` |
| `token` | `search` |
| 其它 | `location_access` / `device_score` / `bcm_chain` / `enter_from`，非必需 |

> **注意**：`keyword` 在 body 里，URL 上只有一个 `klink_egdi` 和公共参数。
> 只看 URL 会误判「没抓到关键词」。

### 6.2 响应结构

```jsonc
{
  "business_data": [
    {"data_id":"0","type":1,"data":{"type":1,
      "aweme_info":{ "aweme_id":"...", "desc":"...",
                     "author":{"nickname":"...","sec_uid":"..."},
                     "statistics":{"digg_count":595,"comment_count":11} }}}
  ],
  "business_config": {
    "keyword": "火锅",          // 服务端回显，可校验请求是否被正确识别
    "has_more": 1,
    "card_count": 2,
    "next_page": {"cursor": 10, "search_id": "2026...", "keyword": "火锅"}
  },
  "status_code": 0
}
```

`business_config.keyword` 是最省事的**校验点**：返回里带的就是服务端认为的搜索词。

### 6.3 已验证的对应关系

页面卡片 ↔ `business_data[].data.aweme_info`：
`desc` / `author.nickname` / `statistics.digg_count` 三项与屏幕完全一致。

### 6.4 抓包要点（用 hook 验证时）

| 现象 | 原因 |
|---|---|
| URL 里没有 `keyword` | 参数在 POST body |
| hook 显示 `GET` | method 没抓到，默认成了 GET；实际是 POST |
| 只看到 `{"vote":false...}` | 命中的是回执接口，不是列表 |
| 列表数据看不到 | 响应 50 万字节，hook 预览截断在 1300 字符 |

请求体只能在 **Retrofit 层**（`com.bytedance.retrofit2.CallServerInterceptor`）拿，
Cronet 层的 body 走 native，抓不到。详见 `traps.md` A8。
