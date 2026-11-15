# unidbg 路线 · 全流程

目标：在 PC 上加载 `libmetasec_ml.so`，离线产出六神签名头；并可自主注册设备。

## 0. 环境

| 项 | 值 |
|---|---|
| JDK | 21 |
| unidbg | `com.github.zhkl0228:unidbg-android:0.9.10-SNAPSHOT` + `unidbg-unicorn2` |
| Maven | 任意 3.9.x |
| 必须的 so | `libmetasec_ml.so`、`libc++_shared.so`、`libEncryptor.so` |

```xml
<dependency>
  <groupId>com.github.zhkl0228</groupId>
  <artifactId>unidbg-android</artifactId>
  <version>0.9.10-SNAPSHOT</version>
</dependency>
<dependency>
  <groupId>com.github.zhkl0228</groupId>
  <artifactId>unidbg-unicorn2</artifactId>
  <version>0.9.10-SNAPSHOT</version>
</dependency>
```

## 1. 加载 so

```java
AndroidEmulator emulator = AndroidEmulatorBuilder.for64Bit()
        .setProcessName("com.ss.android.ugc.aweme").build();
Memory memory = emulator.getMemory();
memory.setLibraryResolver(new AndroidResolver(23));

VM vm = emulator.createDalvikVM();
vm.setJni(new MyJni());            // 见 §2
new AndroidModule(emulator, vm).register(memory);
new JniGraphics(emulator, vm).register(memory);

vm.loadLibrary(new File("so/libc++_shared.so"), false);

// 先"注册"三个类，否则 native 找不到会静默失败
DvmClass m = vm.resolveClass("ms/bd/c/m");
DvmClass a4a = vm.resolveClass("ms/bd/c/a4$a", m);
vm.resolveClass("com/bytedance/mobsec/metasec/ml/MS", a4a);

DalvikModule dm = vm.loadLibrary(new File("so/libmetasec_ml.so"), true);
dm.callJNI_OnLoad(emulator);
```

**关键**：`ms/bd/c/a4$a` 和 `MS` 的父子关系必须提前声明，native 在
`JNI_OnLoad` 里通过 `FindClass("...MS") → GetSuperClass ×2` 找注册类，
类不存在时整个链路静默失败。

## 2. JNI 桩（必须实现的最小集合）

native 会回调 Java，**每个都返回 null 会导致 NPE 或静默失败**。

```java
private DvmObject<?> handleMS(BaseVM vm, int op) {
    switch (op) {
        case 65539:    return new StringObject(vm, FILES + "/.msdata");  // getFilesDir
        case 33554433:                                        // 0x2000001
        case 33554434: return DvmBoolean.valueOf(vm, true);    // 0x2000002
        case 16777232: return vm.resolveClass("java/lang/Integer").newObject(VERCODE); // 800
        case 16777233: return new StringObject(vm, VER);       // "40.2.0"
        case 16777218: return certFile != null ? new ByteArray(vm, readAll(certFile)) : null;
        case 268435470: return vm.resolveClass("java/lang/Long").newObject(System.currentTimeMillis());
        default:        return null;   // 注意：未知 op 返回 null 是常态，别乱造返回值
    }
}
```

还要处理：

| 签名 | 返回 |
|---|---|
| `com/bytedance/mobsec/metasec/ml/MS->b(IIJLjava/lang/String;Ljava/lang/Object;)Ljava/lang/Object;` | 走 `handleMS` |
| `java/lang/Thread->currentThread()Ljava/lang/Thread;` | `newObject(Thread.currentThread())` |
| `java/lang/Boolean->valueOf(Z)Ljava/lang/Boolean;` | `DvmBoolean.valueOf(...)` |
| `java/lang/Integer->valueOf(I)` | `newObject(...)` |
| `java/lang/Long->valueOf(J)` | `newObject(...)` |
| `java/util/UUID->randomUUID()` | 固定 UUID（可选，减随机性） |
| `java/lang/System->currentTimeMillis()J` | 真实时间（**别钉死**，见 traps） |

## 3. 驱动初始化

顺序不能乱，任何一步失败后面全废：

```java
String cfg = "[" + appID + ",\"\",\"\"," + jstr(LICENSE) + "," + jstr(s4)
        + ",\"\",\"\",\"\",\"\",\"\",\"0\",\"-1\",\"" + channel + "\",\"\",\"0\",[],"
        + "[\"tk_key\",\"douyin\"]]";

// 1) 子初始化
mm.callStaticJniMethodObject(emulator, SIG, 0x1000003, 0, 0L, null, appContext);
mm.callStaticJniMethodObject(emulator, SIG, 0x100000c, 0, 0L, null, appContext);

// 2) 配置验证，必须返回 Boolean.TRUE
DvmObject<?> ret = mm.callStaticJniMethodObject(emulator, SIG, 0x4000001, 0, 0L,
        new StringObject(vm, cfg), null);
if (!Boolean.TRUE.equals(ret.getValue())) { /* 配置错，见 contract 表 */ }

// 3) 取 handle
DvmObject<?> h = mm.callStaticJniMethodObject(emulator, SIG, 0x4000002, 0, 0L, null, null);
long handle = (Long) h.getValue();     // 40.2.0 = 314318848

// 4) 设身份
mm.callStaticJniMethodObject(emulator, SIG, 0x2000002, 0, handle, deviceId, null);
mm.callStaticJniMethodObject(emulator, SIG, 0x2000003, 0, handle, installId, null);

// 5) 取头
DvmObject<?> r = mm.callStaticJniMethodObject(emulator, SIG,
        0x2000006, op2, handle, url, null);
```

`s4` 的来源：`op 0x1000001` 解密 `"bebb7f"` + seed `{101,55,69,88,89,33,47,20,103}`
→ `"v04.10.04"`（40.2.0）。

## 4. 初始化失败的应对（最重要的一条）

**现象**：同样的代码，跑 6 次只成功 2 次；失败时 `frameSign` / `0x2000006` 返回 null，
或者直接 `svc #0x1a0` 退出。

**性质**：失败是**粘性**的——同一 emulator 实例一旦失败，后续所有签名都失败，重试无效。

**解法**：用探针验证，失败就**丢弃整个 emulator 重建**：

```java
for (int attempt = 1; attempt <= 15; attempt++) {
    DouyinMetasecSign s = new DouyinMetasecSign(so, cpp, cert);   // 全新实例
    s.initIfNeeded();
    Map<String,String> probe = s.signHeaders(PROBE_URL, 0, 3);
    if (probe != null && probe.containsKey("X-Gorgon")) {
        this.signer = s;   // 成功
        return;
    }
    // 失败 → 下一轮重建
}
```

实测：平均 2-3 次成功，最坏遇到第 8 次。**单次成功率约 1/3，重建后必然成功。**

## 5. 常驻服务（生产用法）

不要每次启动 JVM（5-10 秒），做成常驻：

```
SignProperties（配置）
  └─ DouyinSignService     ← 一个 emulator + 一台设备身份（线程绑定 + 探针重建）
      └─ SignServicePool   ← 实例池，每实例一个设备
          └─ SignController ← REST
```

### 铁律一：JNI 环境线程绑定

emulator 必须在哪个线程创建，就只能在哪个线程调用。跨线程会抛：

```
NullPointerException: Cannot invoke "UnidbgPointer.toIntPeer()" because "pointer" is null
```

→ 每个实例绑一条专属线程（`Executors.newSingleThreadExecutor`），
构造和签名都 `submit` 到这条线程。

### 铁律二：设备身份与请求参数必须同源

签名用的 `device_id/iid/cdid` 和拼 URL 用的必须一致，否则 `-99999`。
所以池的 `borrow()` 要返回「设备身份 + 签名器」整体，不能分开取。

### 性能实测

| 指标 | 值 |
|---|---|
| 单次签名 | 48ms（37-68ms） |
| 每实例内存 | 约 120MB |
| 12 实例预热 | 150 秒 |
| 单页采集（签名+请求） | 约 550ms |

## 6. 设备注册（自主造设备）

```java
DeviceProfiles.Profile p = DeviceProfiles.random();   // 真实机型池
String cdid = UUID.randomUUID().toString();
String openudid = randomHex(40);

Map header = ...39 个字段...;
byte[] raw = json.writeValueAsBytes(Map.of("magic_tag","ss_app_log","header",header,"_gen_time",now));
byte[] gz = gzip(raw);
byte[] body = TtEncryptCli.encrypt(gz);      // 见 contract §7

String url = "https://log.snssdk.com/service/2/device_register/?" + params;
Map<String,String> headers = pool.sign(url, 0);
headers.put("x-ss-stub", md5(body));
POST body=body
```

**机型画像池要自洽**：品牌↔型号↔系统/API↔分辨率↔DPI↔ROM↔channel 必须成组，
不能随机拼接（`Pixel 6` 配 MIUI 会被识别）。见项目里的 `DeviceProfiles.java`（19 个真实组合）。

## 7. 验收

```bash
# 1. 签名
curl "http://127.0.0.1:8099/api/sign?url=<完整URL>"   # ok=true, 有 X-Gorgon
# 2. 真请求（唯一有效验收）
curl "http://127.0.0.1:8099/api/comments?aweme_id=<id>&pages=1"
#    → status_code 0 且有 comments
# 3. 注册
curl "http://127.0.0.1:8099/api/register?verify=true"  # ok=true, verify.ok=true
```

只做到第 1 步不算成功。
