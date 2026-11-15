# 换版本适配清单

所有硬编码值都是 **40.2.0** 的。换版本时按本清单逐项重新验证，
**不要假设任何一项不变**。

## 快速判断"要不要重做"

| 变化 | 影响 |
|---|---|
| 小版本号变（40.2.0 → 40.3.0） | 通常只需重验 §1 §2 §7 |
| 大版本变（40.x → 41.x） | 全部 8 项重验，偏移大概率变 |
| so 文件大小/sha256 变 | **全部重验**，视为新目标 |
| 只改了 Java 层 | 只有 §6 需要重验 |

```bash
# 拿到 APK 先算指纹，和已知版本对比
sha256sum libmetasec_ml.so
```

已记录的版本：

| 版本 | libmetasec_ml.so | 入口偏移 | 备注 |
|---|---|---|---|
| 40.2.0 | 4,525,552 B<br>`7ed8596e2c9ed642...` | `0x29b2b4` | 已验证端到端 |
| 41.1.0 | 不同 | 不同（`0x20a8ac` 附近） | RPC 跑通，unidbg 未验证 |

---

## §1 找 JNI 入口偏移

**方法 A：静态特征扫描（推荐）**

wrapper 的前 6 条指令是固定的：

```
e1 03 00 aa   mov x1, x0
e0 03 02 2a   mov w0, w2
e2 03 03 2a   mov w2, w3
e3 03 04 aa   mov x3, x4
e4 03 05 aa   mov x4, x5
e5 03 06 aa   mov x5, x6
```

```python
# 在 .text 里搜这 24 字节，命中处即 JNI wrapper 入口
pat = bytes.fromhex("e10300aae003022ae203032ae30304aae40305aae50306aa")
idx = data.find(pat)
print(hex(offset_of(idx)))     # 转成 vaddr
```

**方法 B：动态抓 RegisterNatives**

```java
// unidbg 里 vm.setVerbose(true)，加载后看日志
RegisterNative(ms/bd/c/m, a(IIJLjava/lang/String;Ljava/lang/Object;)Ljava/lang/Object;, RX@0x...)
```

**验证**：该偏移处的字节应是 `e1 03 00 aa ...` 开头。
若读到 `50 00 00 58`（`ldr x16,#8; br x16`）说明是跳板，不是入口。

---

## §2 抓初始化配置 JSON

**必须在真机上抓**，不要猜。

```javascript
// Frida spawn 模式，hook JSONArray.toString
var C = Java.use('org.json.JSONArray');
C.toString.overload().implementation = function () {
    var s = this.toString();
    if (s.charAt(0) === '[' && s.indexOf('1128') >= 0 && s.indexOf('tk_key') >= 0) {
        console.log('[CFG] ' + s);
    }
    return s;
};
```

```bash
frida -U -f com.ss.android.ugc.aweme -l hook.js --no-pause
```

拿到 17 字段数组后，逐字段对比 `sixgod-contract.md` §3：

| 索引 | 要确认什么 |
|---|---|
| 0 | appID 是否仍 1128 |
| 3 | license 是否变（会随 APK 变） |
| 4 | sdkVersion 字符串是否变 |
| 12 | channel code（40.2.0 是 `810`） |
| 16 | kSt 第二个元素是否仍 `douyin` |

**验证**：配置喂进 `0x4000001` 必须返回 `Boolean.TRUE`。
返回 false 或直接退出 = 配置错。

> 37.5.0 的坑：索引 4 必须是 **Java 层静态字段值**（`v06.05.40-dy`），
> 不是 native 解密值。40.2.0 反过来。**每个版本都要抓原文确认。**

---

## §3 解 license

license 是 244 字节左右的 base64，硬编码在 Java 层。

```bash
# 反编译后在 SecApiImpl / metasec 初始化类里找
jadx -d out --no-res base.apk
grep -rn "bo95dJiz\|metasec.*license\|LICENSE" out/sources/ | head
```

特征：base64、长度 300-400 字符、以 `==` 结尾、内容看起来随机。

**验证**：把它填进配置索引 3，能过 `0x4000001` 即为正确。
填错会直接 `exit(1)` 或 VM 死循环。

---

## §4 解 sdkVersion（`s4`）

40.2.0 用 `op 0x1000001` 解密 `"bebb7f"`：

```java
DvmObject<?> r = mm.callStaticJniMethodObject(emulator,
        "a(IIJLjava/lang/String;Ljava/lang/Object;)Ljava/lang/Object;",
        0x1000001, 0, 0L, "bebb7f",
        new ByteArray(vm, new byte[]{101,55,69,88,89,33,47,20,103}));
// → "v04.10.04"
```

**换版本要重新找 (keyhex, seed) 对**：

1. jadx 里找调用 `MS.a(...)` 或 `decrypt(...)` 的地方
2. 参数里有一个短十六进制串（keyhex）和一个 byte 数组（seed）
3. 挨个试，解出来是 `v\d+\.\d+\.\d+` 形态的就是

**也可以直接用配置 JSON 里抓到的索引 4 的值**，省掉解密。

---

## §5 确认 op 表

```java
// 逐个试探，看返回类型
0x1000003  → 无返回（Context）
0x100000c  → 无返回
0x5000001  → Integer（0 = 成功）
0x4000001  → Boolean（必须 TRUE）
0x4000002  → Long（session handle）
0x2000002/3 → 设 id，无返回
0x2000006  → String[]（六神头）
```

**验证**：`0x4000002` 必须返回非 0 的 Long（40.2.0 = `314318848`）。
返回 null 说明前面的初始化没成功。

如果 `0x2000006` 返回 null 但 init 成功，试 `0x200000a`（frameSign）看是否正常，
再回头查参数。

---

## §6 确认请求参数集

从真机抓：hook `org.json.JSONObject.toString()`，过滤含 `device_id=` 的串
（抖音 WebSocket 连接串里有全量参数）。

必查是否新增/改名字段：

```
device_type device_brand channel resolution dpi os_api
manifest_version_code update_version_code version_name
host_abi cpu_support64 language ac cdid
```

**验证**：用真机的完整参数 + 自己的签名请求，必须 `status_code=0`。
缺参数 → `-99999`。

---

## §7 确认 sig_hash

```bash
adb shell su -c "grep -rho 'sig_hash\":\"[0-9a-f]*' /data/data/com.ss.android.ugc.aweme"
```

或从 APK 算签名证书 MD5。

**验证**：注册请求带上它，返回的 `device_id` 非 0。
填错不报错，但设备可能被降权（无法直接验证，只能靠注册后用一段时间观察）。

---

## §8 确认注册链路（如果要做设备池）

```bash
# 1. libEncryptor.so 还在不在
adb shell su -c 'ls /data/app/*/com.ss.android.ugc.aweme*/lib/arm64/ | grep -i enc'

# 2. 注册方法名和偏移
#    静态搜字符串 "ttEncrypt" 看是否还在；动态开 verbose 看 RegisterNatives
#    40.2.0: com/bytedance/frameworks/encryptor/EncryptorUtil
#            ttEncrypt([BI)[B  @ module+0x7d8c

# 3. 端点是否变
grep -a "device_register" base.apk | head     # 或 unzip 后 grep dex
```

**验证**：`POST /service/2/device_register/` 返回 `device_id_str` 非空。

---

## 适配完成的自检顺序

**严格按这个顺序，前一步不过不要做后一步：**

```
① so 能加载 + JNI_OnLoad 返回 OK
② 配置验证 0x4000001 → TRUE
③ 拿到 handle（非 0）
④ 0x2000006 出 6 个头，Gorgon 以 8404 开头
⑤ 拼完整参数请求 → status_code 0 + 有 comments
⑥ （可选）注册 → device_id 非 0
⑦ （可选）用新设备再走 ⑤
```

每步用 `scripts/dy-selfcheck.py` 对应子命令验证。

## 常见"看起来过了其实没过"

| 假象 | 真相 |
|---|---|
| `init returned = true` | 只说明配置通过，不代表能签名 |
| `0x2000006` 返回数组 | 不代表服务端接受，必须真请求 |
| 请求 `status_code:0` 但 `comments:[]` | 被限流的软封禁 |
| 注册返回 200 但 `device_id:0` | TTEncrypt 输入/长度错 |
