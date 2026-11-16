# 云新闻 (com.yndaily.wxyd) sign 算法

## 结论

```
appSign = UPPER(MD5( hex(证书DER) ))                      # LogShutDown.getAppSign()
inner   = UPPER(MD5( appSign ))
sign    = UPPER(MD5( inner + account + token + timestamp ))
```

本质是**两层 MD5**：协议层 MD5 的输入里，第一段是 appSign 的 MD5。

## 证据链

| 步骤 | 结果 |
|---|---|
| Java 入口 | `cn.thecover.lib.common.manager.SignManager.getSign(a,b,c)` → `native` |
| JNI 符号 | `Java_cn_thecover_lib_common_manager_SignManager_getSign` @ **0x45B48** (size 1072) |
| IDA 伪代码 | `md5(getAppSign())` → 大写 → 拼 account+token+timestamp → `md5` → 大写 |
| 运行时比对 | 3/3 MATCH（见 wxyd_sign.py 的 VECTORS） |
| appSign 来源 | `PackageManager.getPackageInfo(pkg,64).signatures[0].toCharsString()` 再 MD5 大写，实测 MATCH |

本次安装的常量：

```
APP_SIGN = 71418DA91E43A6F8C811F57A35CD744B
inner    = 589956D116926909620F2F4BAD96B05D
证书 DER hex 长度 = 1758，以 3082036b 开头
```

## 两个调用点，参数语义不同

**① HTTP 请求** — `cn.thecover.lib.http.data.entity.HttpRequestEntity`

```java
account   = UUID.randomUUID().toString();                 // 随机 UUID
timestamp = String.valueOf(System.currentTimeMillis());   // 毫秒，13 位
token     = 登录 token（未登录为空串）
sign      = getSign(account, token, timestamp)
```

请求参数全集（`getMapParams`）：

```
timestamp, token, sign, data, client=android, account,
deviceid, channel, vno, app_vno, teen_mode, switch_suggest
```

**② WebView 桥** — `cn.thecover.www.covermedia.ui.widget.webview.SafeWebView.Y`

```java
account   = 登录 user_id，未登录为 ""
token     = 登录 token
timestamp = JS 传入的 signParams.timestamp
```

## 复现

```python
import hashlib
APP_SIGN = "71418DA91E43A6F8C811F57A35CD744B"

def md5u(s): return hashlib.md5(s.encode()).hexdigest().upper()

def sign(account, token, ts):
    return md5u(md5u(APP_SIGN) + account + token + ts)
```

`wxyd_sign.py` 里带 3 组实测向量，直接 `python wxyd_sign.py` 自测。

## 注意

- 换了签名证书 / 重新打包，`APP_SIGN` 会变，需重新取
- HTTP 请求的 account 是随机 UUID，重放时**必须重新生成并重算 sign**
- timestamp 单位：HTTP 是毫秒；WebView 由 JS 决定

---

## 线上验证（2026-11-08）

用还原的算法重算真实抓包请求，签名完全一致：

```
account   = 2fbfc37e-cd7a-45e0-9ed0-7d27b153f2a9
token     = (空)
timestamp = 1794132062519
concat    = 589956D116926909620F2F4BAD96B05D + account + "" + timestamp
calc      = 934CEBB1F019B1B4945D8118E4B9492A
抓包的 sign= 934CEBB1F019B1B4945D8118E4B9492A      ← MATCH
```

客户端实测（wxyd_client.py）：

```
HTTP 200   size=90355
data 字段: banner, column_entry_list, container_index, event_contexts,
           from_db, lastUpdateTime, last_news_id, list, partition_list,
           subject_entry_list, subject_module, top_roll
list 条数: 36
```

### 接口

```
POST https://ynrb-api.yndaily.com/getList
Content-Type: application/x-www-form-urlencoded

switch_suggest=1
data={"ad_id":0,...,"page":1,"page_size":16,"lastUpdateTime":"2026-11-08 18:00:53"}
vno=7.1.4
sign=<UPPER(MD5(UPPER(MD5(APP_SIGN)) + account + token + timestamp))>
channel=huaweiyingyongzhongxin_517
client=android
teen_mode=0
app_vno=7.1.4
deviceid=ac31ba23-9db9-33ec-bfcc-b8efafd51d46-EAPE
account=<每次随机 UUID>
timestamp=<毫秒>
token=
```

必带头：`User-Agent: covermedia-android`、`tenantId: 35`、`fmio_token: <JWT>`、`fmio_appid: rmt_yunnan`

### 三个坑

1. **必须直连**：走系统代理时 TLS 隧道会被对端断开（`RemoteDisconnected`）
2. **account 每次随机 UUID**，不是用户 id，重放时必须重新生成并重算 sign
3. **timestamp 是毫秒**（13 位）
