# 六神签名 · 契约表

抖音 40.2.0 实测值。换版本时**先重新验证本表**再动手。

## 1. JNI 入口

只有一个 native 方法，所有功能靠 `op` 区分：

```
RegisterNatives(ms/bd/c/m, 1 method)
  a(IIJLjava/lang/String;Ljava/lang/Object;)Ljava/lang/Object;
  @ module+0x29b2b4
```

寄存器布局（wrapper 入口）：

```
x0 = JNIEnv*   x1 = jclass   w2 = op   w3 = op2
x4 = handle(jlong)   x5 = String   x6 = Object
```

wrapper 前几条指令（用于静态定位）：

```asm
mov x1, x0        ; e1 03 00 aa
mov w0, w2        ; e0 03 02 2a
mov w2, w3        ; e2 03 03 2a
mov x3, x4        ; e3 03 04 aa
mov x4, x5        ; e4 03 05 aa
mov x5, x6        ; e5 03 06 aa
```

## 2. op 映射表（40.2.0 实测）

| op | 十进制 | 入参 | 返回 | 用途 |
|---|---|---|---|---|
| `0x1000001` | 16777217 | keyhex + byte[] | String | 字符串解密原语 |
| `0x1000003` | 16777219 | Context | — | 上下文初始化 |
| `0x100000c` | 16777228 | — | — | switch 初始化 |
| `0x5000001` | 83886081 | — | int | 库初始化（0=成功） |
| `0x4000001` | 67108865 | 配置 JSON | Boolean | **配置验证（必须 true）** |
| `0x4000002` | 67108866 | — | Long | **取 session handle** |
| `0x2000001` | 33554433 | report 串 | Boolean | 上报（喂 url + stub） |
| `0x2000002` | 33554434 | device_id | — | 设设备 ID |
| `0x2000003` | 33554435 | install_id | — | 设安装 ID |
| `0x2000006` | 33554438 | url | `String[]` | **取六神头（键值对）** |
| `0x200000a` | 33554442 | url | `String[]` | frameSign（中间产物） |
| `0x200000d` | 33554445 | — | Long | 取状态标志（非常量，勿当签名） |
| `0x3000003` | 50331651 | — | Long | 取 handle（同 0x4000002 的值） |

**真机启动序列**（实测抓取）：

```
0x1000003 → 0x1000001 → 0x5000001 → 0x4000001 → 0x4000002
→ 0x200000e → 0x9000001 → 0xa000003 → 0xa000001
→ 0x3000003 → 0x200000d → 0x2000004 → 0x4000004
→ 0x2000002 → 0x2000003
```

**真机不调用 `0x2000001`（report）**。仿真时可省略，签名仍有效，只是头串内容会变。

## 3. 初始化配置 JSON

位置参数数组，17 个元素。40.2.0 真机原文（从 `org.json.JSONArray.toString()` hook 得到）：

```json
["1128","","","<244字节 license base64>","v04.10.04","","","","","",
 "0","-1","810","","0",[],["tk_key","douyin"]]
```

| 索引 | 含义 | 40.2.0 值 |
|---|---|---|
| 0 | appID | `"1128"` |
| 1 | channel | `""` |
| 2 | altAppId | `""`（40.2.0 为空，37.5.0 是 `"1128"`） |
| 3 | **license** | 244 字节 base64（jadx 搜 `SecApiImpl` 静态字段） |
| 4 | **sdkVersion** | `"v04.10.04"`（native 解密 `bebb7f` 得到） |
| 5-9 | 保留 | 全空 |
| 10 | aid | `"0"` |
| 11 | 保留 | `"-1"` |
| 12 | **channel code** | `"810"`（真机值！填 0 也能过配置但签名不同） |
| 13 | 保留 | `""` |
| 14 | 保留 | `"0"` |
| 15 | 空数组 | `[]` |
| 16 | kSt | `["tk_key","douyin"]` |

> 37.5.0 的博客说索引 4 必须是 Java 层静态字段值（如 `v06.05.40-dy`），
> 40.2.0 实测用的是 native 解密值 `v04.10.04`。**换版本必须重新抓一次配置原文**。

抓配置的方法：hook `org.json.JSONArray.toString()`，过滤含 `1128` 且以 `[` 开头的串。

## 4. 六神头

`0x2000006` 返回 `String[]`，按 `[name, value, name, value, ...]` 排列。

| 头 | 形态 |
|---|---|
| `X-Argus` | base64，较短（如 `MzH5ag==`） |
| `X-Gorgon` | **52 位 hex，固定 `8404` 开头** |
| `X-Helios` | base64，约 40 字符 |
| `X-Khronos` | Unix 秒级时间戳 |
| `X-Ladon` | base64，较短 |
| `X-Medusa` | 超长 base64（1KB+） |

40.2.0 **只有这 6 个**（无 Perseus / Neptune）。

`op2` 参数会改变输出：`op2=0/1/2` 产出三组不同的 Gorgon（对应不同 frame 类型），默认用 0。

## 5. 签名函数（内部，非 JNI）

`libsscronet.so` 把 frameSign 材料组装成最终头。头字段名只在这个库里：

```
x-gorgon   @ 0x8b3ed      x-argus   @ 0x8429f
x-khronos  @ 0x85796      x-ladon   @ 0x8b3f6
```

每个名字**全库只出现一次**，唯一代码引用点：

```asm
0x30673c:  add  x1, x1, #0x3ed   ; → "x-gorgon"
0x306740:  bl   0xfe46c          ; std::string 赋值
```

所在函数 `0x306498` 是在构建 **header 名值表**（键含 `x-common-params-v2`、`x-ss-stub`、
`tt-config-version`、`x-tt-store-region` 等）。**值在别处写入**，静态追了 4 层没到底。

> 结论：不要试图静态还原 sscronet 的组装逻辑，性价比极低。
> 直接仿真 metasec 拿 `0x2000006` 的输出即可。

## 6. 设备注册契约

### 端点与格式

```
POST https://log.snssdk.com/service/2/device_register/?<params>
Body: TTEncrypt(GZIP(指纹 JSON))
Headers: 六神头 + x-ss-stub = MD5(body).hex() + Content-Type: application/octet-stream
```

URL 参数：`aid=1128&device_platform=android&version_code=400200&version_name=40.2.0`
`&manifest_version_code=400201&update_version_code=40209900`
`&device_type=<urlencode(model)>&device_brand=<brand>&os=android&os_api=33&os_version=13`
`&channel=<channel>&_rticket=<ms>&ts=<s>`

### 指纹 JSON 结构

```json
{
  "magic_tag": "ss_app_log",
  "header": { ... 39 个字段 ... },
  "_gen_time": <毫秒时间戳>
}
```

`header` 必需字段：

```
device_id(0) install_id(0) aid(1128) app_name("aweme")
version_code(400200) version_name("40.2.0")
manifest_version_code(400201) update_version_code(40209900)
channel device_platform("android")
os("android") os_version os_api
device_model device_brand device_manufacturer device_type
cpu_abi("arm64-v8a") resolution dpi
language("zh") app_language("zh") timezone(8) access("wifi")
carrier_region("CN") region("CN") mcc_mnc
rom_version
cdid openudid clientudid
sig_hash sdk_version("v04.10.04")
app_type("normal") is_pad(0) is_guest_mode(0) is_preinstall(0)
first_launch_timestamp
```

### 返回

```json
{"device_id":4210509376169546,"install_id":4210509376173642,"new_user":1,
 "device_token":"AAA...","dtrait_pk1":"LS0t...","klink_egdi":"..."}
```

`device_token` 要存下来（部分接口可能需要），当前用途未验证。

### sig_hash

APK 签名证书 MD5。40.2.0 = `aea615ab910015038f73c47e45d21466`。
**填错不会报错，但设备可能被风控降权。**

真机取值方法：

```bash
adb shell su -c "grep -rho 'sig_hash\":\"[0-9a-f]*' /data/data/com.ss.android.ugc.aweme"
```

## 7. TTEncrypt

```
libEncryptor.so
  RegisterNatives(com/bytedance/frameworks/encryptor/EncryptorUtil, 1)
  ttEncrypt([BI)[B  @ module+0x7d8c
```

调用（unidbg）：

```java
DvmClass cls = vm.resolveClass("com/bytedance/frameworks/encryptor/EncryptorUtil");
ByteArray input = new ByteArray(vm, gzipData);
DvmObject<?> ret = cls.callStaticJniMethodObject(emulator,
        "ttEncrypt([BI)[B", input, gzipData.length);   // 第二个参数是长度！
```

**输出格式**：`74 63 05 10 00 00`（6 字节魔数）+ 32 字节 seed + 密文

输入必须是**已 GZIP 压缩**的明文。

## 8. 评论接口的最小可用参数集

缺任何一项都可能返回 `-99999`：

```
aweme_id cursor count aid app_name version_code version_name
manifest_version_code update_version_code
device_platform device_type device_brand os os_api os_version
channel device_id iid cdid resolution dpi
host_abi cpu_support64 language ac _rticket ts
```

`count` 上限 **50**（传 100 仍返回 50）。
