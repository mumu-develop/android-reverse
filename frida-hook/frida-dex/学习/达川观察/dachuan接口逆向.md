# 达川观察 1.3.0 接口逆向（/getList）

**结论：sign 已完全还原，并用重写代码请求线上接口，返回 HTTP 200 真实数据。**

---

## 1. 参数来源（jadx 定位）

类：`cn.thecover.lib.http.data.entity.HttpRequestEntity`
来源：`frida-dex\dump_dex_com.dachuan.news\class3.dex`（APK 是 360 加固，需运行时 dump）

```java
public HttpRequestEntity(Context context, HashMap map, String token, String deviceid) {
    this.token     = token;
    this.account   = UUID.randomUUID().toString();          // 每次请求随机
    String ts      = String.valueOf(System.currentTimeMillis());
    this.timestamp = ts;
    this.sign      = getSign(this.account, this.token, ts); // ← native
    this.data      = new Gson().toJson(map);                // 业务参数 JSON
    this.client    = "android";
    this.deviceid  = deviceid != null ? deviceid : e.a(context);
    this.channel   = b.a(context);
    this.vno       = t.h().m();      // "1.3.0"
    this.app_vno   = t.h().s();
    this.teen_mode = t.h().n();
    this.switch_suggest = t.h().k();
}
```

| 参数 | 来源 | 说明 |
|---|---|---|
| `data` | 业务 map 的 Gson 序列化 | 广告位/page/channel_id 等 |
| `vno` / `app_vno` | 版本号常量 | `1.3.0` |
| `channel` | `b.a(context)` | 应用宝渠道 `yingyongbao_1025` |
| `client` | 常量 | `android` |
| `teen_mode` / `switch_suggest` | 配置 | `0` / `1` |
| `deviceid` | `e.a(context)` | UUID + `-XXXX` 后缀 |
| `account` | `UUID.randomUUID()` | **每次请求都变** |
| `timestamp` | `System.currentTimeMillis()` | 毫秒 |
| `token` | 登录态 | 未登录为空 |
| **`sign`** | **native `libwtf.so`** | 见下 |

请求头（拦截器里加）：

```
User-Agent: covermedia-android
tenantId:   15
fmio_token: <登录 token>
fmio_appid: <appid>
```

---

## 2. sign 的调用链

```
HttpRequestEntity.getSign(account, token, timestamp)
  └─ e.a.b.a.k.a.b(...)
       └─ cn.thecover.lib.common.manager.SignManager.a(...)
            └─ native  SignManager.getSign  [System.loadLibrary("wtf") → libwtf.so]
                 ├─ JNI FindClass("cn/thecover/lib/common/utils/LogShutDown")
                 ├─ GetStaticMethodID("getAppSign", "()Ljava/lang/String;")
                 ├─ → 证书指纹 appSign
                 ├─ md5(appSign) → toUpperCase()          ← 第一段
                 ├─ 再拼 account / token / timestamp
                 └─ md5(那串) → toUpperCase()             ← 第二段，返回 jstring
```

Java 侧 `LogShutDown.getAppSign()`：

```java
Signature[] arr = pm.getPackageInfo(pkg, GET_SIGNATURES).signatures;
StringBuilder sb = ...;  for (Signature s : arr) sb.append(s.toCharsString());
return shut(sb.toString());          // shut = MD5(...).toUpperCase()
```

即 **appSign = MD5(证书 DER 的小写十六进制).toUpperCase()**

---

## 3. libwtf.so 定位（IDA / 反汇编）

文件：`lib/arm64-v8a/libwtf.so`（5.3 MB，符号未 strip）

| 地址 | 符号 | 作用 |
|---|---|---|
| `0x45B48` | `Java_cn_thecover_lib_common_manager_SignManager_getSign` | JNI 入口，1072 字节 |
| `0x43E50` | `_Z3md5NSt6__ndk112basic_string...` | `md5(std::string)` |
| `0x43AA4` | `_ZNK3MD59hexdigestEv` | `MD5::hexdigest()` |
| `0x4621C` / `0x461D0` | 局部函数 | 字符串拼接辅助 |
| PLT `0x41250` | `toUpperCase(std::string)` | 转大写 |

关键调用序列（capstone 反汇编，PLT 已解析）：

```
0x45b84  bl FindClass("cn/thecover/lib/common/utils/LogShutDown")
0x45bf8  bl GetStaticMethodID(..., "getAppSign", "()Ljava/lang/String;")
0x45c60  bl CallStaticObjectMethod
0x45c74  bl GetStringUTFChars
0x45c8c  bl basic_string(const char*)          ← appSign 建串
0x45c98  bl md5(std::string)                    ← 第一段 MD5
0x45ca8  bl toUpperCase(std::string)
0x45ccc  bl GetStringUTFChars                   ┐
0x45cec  bl GetStringUTFChars                   ├ 取 account / token / timestamp
0x45d0c  bl GetStringUTFChars                   ┘
0x45d2c  bl sub_4621C                           ← 拼接
0x45d84  bl md5(std::string)                    ← 第二段 MD5
0x45d94  bl toUpperCase(std::string)
0x45e40  bl NewStringUTF                        ← 返回
```

---

## 4. 最终算法

```
appSign = MD5( certDER.toCharsString() ).upper()      # 证书 DER 的小写 hex
stage1  = MD5( appSign ).upper()
sign    = MD5( stage1 + account + token + timestamp ).upper()
```

- 无分隔符
- 全部大写十六进制
- `account` 每次请求随机 UUID，`timestamp` 是毫秒
- token 为空时占位为空串

### 该 APK 的常量

```
appSign = A262FA6ED59F60E49FD49E205F68426D
stage1  = F2FD87D83151721B48E869DBFF113AC8
```

（已用两种方式核对：`META-INF/DACHUAN.RSA` 与设备上安装的 APK，证书一致）

### 验证样本

```
account   = bf631db6-033c-4284-b6a9-9b6871e06d60
timestamp = 1793429940268
token     = ""
→ sign    = 1F7622ADE63AD9BB332B0832A1E74029   ✅ 与抓包一致
```

---

## 5. 可运行代码

见 `work/dc_client.py`，核心：

```python
def make_sign(account, token, ts, app_sign=APPSIGN):
    stage1 = hashlib.md5(app_sign.encode()).hexdigest().upper()
    return hashlib.md5((stage1 + account + token + ts).encode()).hexdigest().upper()
```

实测：

```
account  : f73d347c-2f3a-4ebc-a56d-d7d6397231b0
timestamp: 1793431932538
sign     : C0EB534A35A0B0569072563F958E3818
HTTP 200 {"data":{"columns":[...]}}
```

---

## 6. 复现步骤

1. APK 360 加固 → 必须 `frida-dexdump` 拿真实 dex
2. jadx 打开 dump 出的 `class3.dex`，定位 `HttpRequestEntity`
3. `getSign` 是 native → 提取 `lib/arm64-v8a/libwtf.so`
4. 该 so 符号未 strip，直接看 `Java_..._getSign`
5. 反汇编看到两段 `md5 + toUpperCase`，中间夹一个 JNI 调 `LogShutDown.getAppSign()`
6. `getAppSign` 返回证书指纹 → 用 APK 的签名证书算出来
7. 三段拼起来验证即可
