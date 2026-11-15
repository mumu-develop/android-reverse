# unidbg 仿真路线（通用方法论）

> 由 `apk-reverse` 按需引用。只在 §2 判定"纯算不可行"、决定走仿真时读这份。

**核心认知**：仿真不是"还原算法"，是**让原库在 PC 上跑起来**。
不需要读懂 VMP/JIT，只要喂对环境。

---

## 1. 什么情况该走仿真

| 判据 | 说明 |
|---|---|
| 算法不在静态二进制里 | VMP + 运行时 JIT，静态搜不到 crypto 常量 |
| 有自毁 handler | 跳未映射地址，静态/动态都难跟 |
| 密钥服务端下发或设备绑定 | 重写算法也拿不到 key |
| 依赖大量 JNI 回调环境值 | 写出来也是半个 unidbg |

**反之不该走仿真**：Java 层明文拼接、SO 只有标准 MD5/HMAC/AES → 纯算更快更稳。

---

## 2. 工程骨架

```
project/
├── pom.xml
├── so/
│   ├── libc++_shared.so       # 目标库的 C++ 运行时，先加载
│   └── lib<target>.so
└── src/main/java/com/xx/
    ├── Signer.java            # 全部逻辑
    └── Main.java              # CLI 入口
```

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

---

## 3. 加载顺序（错一步就静默失败）

```java
AndroidEmulator emulator = AndroidEmulatorBuilder.for64Bit()
        .setProcessName(pkg).build();
Memory memory = emulator.getMemory();
memory.setLibraryResolver(new AndroidResolver(23));   // API level 按目标 App 设

VM vm = emulator.createDalvikVM();
vm.setJni(new MyJni());                               // 见 §4
new AndroidModule(emulator, vm).register(memory);
new JniGraphics(emulator, vm).register(memory);

vm.loadLibrary(new File("so/libc++_shared.so"), false);   // ① 先 C++ 运行时

// ② 提前把目标库会 FindClass 的类声明出来（关键！）
DvmClass core = vm.resolveClass("com/xx/core");
DvmClass impl = vm.resolveClass("com/xx/impl$a", core);
vm.resolveClass("com/xx/PublicApi", impl);

DalvikModule dm = vm.loadLibrary(new File("so/lib<target>.so"), true);
dm.callJNI_OnLoad(emulator);
```

**最容易踩的坑**：native 在 `JNI_OnLoad` 里用
`FindClass("...") → GetSuperClass ×2 → RegisterNatives` 定位注册类。
类不存在时**不报错**，只是后续所有调用返回 null。

判断方法：`vm.setVerbose(true)` 看有没有 `FindClass(...) was called` 且返回非空。

---

## 4. JNI 桩：只实现被调用的，未知的一律返回 null

```java
public class MyJni extends AbstractJni {
    @Override
    public DvmObject<?> callStaticObjectMethodV(BaseVM vm, DvmClass c, String sig, VaList va) {
        // native 回调用一个「op 分发」形式（很多 SDK 都这样）
        if (sig.contains("->b(IIJLjava/lang/String;Ljava/lang/Object;)")) {
            return handleOp(vm, va.getIntArg(0));
        }
        switch (sig) {
            case "java/lang/Thread->currentThread()Ljava/lang/Thread;":
                return vm.resolveClass("java/lang/Thread").newObject(Thread.currentThread());
            case "java/lang/Boolean->valueOf(Z)Ljava/lang/Boolean;":
                return DvmBoolean.valueOf(vm, va.getIntArg(0) != 0);
            case "java/lang/Integer->valueOf(I)Ljava/lang/Integer;":
                return vm.resolveClass("java/lang/Integer").newObject(va.getIntArg(0));
            case "java/lang/Long->valueOf(J)Ljava/lang/Long;":
                return vm.resolveClass("java/lang/Long").newObject(va.getLongArg(0));
        }
        return super.callStaticObjectMethodV(vm, c, sig, va);
    }
}
```

**三条铁律**：

| 铁律 | 原因 |
|---|---|
| 未知 op **返回 null**，不要"造"一个返回值 | 造错类型会让 native 走进意外分支，比 null 更难查 |
| 时间类回调优先返回**真实时间** | 钉死时间戳常导致初始化失败或签名过期 |
| 路径类回调返回**真实存在的目录** | 返回不存在的路径会让 native 走首次启动分支 |

**卡住时**：`vm.setVerbose(true)`，把 native 调过的每个 Java 方法都打出来，
缺哪个补哪个。不要猜。

---

## 5. 铁律：JNI 环境线程绑定

emulator **必须在哪个线程创建，就只能在哪个线程调用**。

跨线程典型报错：

```
NullPointerException: Cannot invoke "UnidbgPointer.toIntPeer()" because "pointer" is null
  at DalvikVM64$NNN.handle(...)
```

**处理**：每个实例绑一条专属线程，构造和调用都提交到该线程。

```java
ExecutorService exec = Executors.newSingleThreadExecutor(r -> {
    Thread t = new Thread(r, "signer-1");
    t.setDaemon(true);
    return t;
});
exec.submit(() -> { signer = new Signer(...); signer.init(); return null; }).get();
Map<String,String> r = exec.submit(() -> signer.sign(url)).get(60, SECONDS);
```

---

## 6. 铁律：初始化失败是「粘性」的

**现象**：同一份代码跑 6 次只成功 2 次；失败时签名返回 null 或直接 `svc` 退出。

**性质**：失败后**重试调用无效**——同一个 emulator 实例已经坏了。

**处理**：探针验证 + **重建整个 emulator**。

```java
for (int attempt = 1; attempt <= 15; attempt++) {
    Signer s = new Signer(so, cpp, cert);     // 全新实例
    s.init();
    Map<String,String> probe = s.sign(PROBE_URL);
    if (probe != null && probe.containsKey(<关键字段>)) {
        this.signer = s;
        return;                                // 成功
    }
    // 失败 → 丢弃，下一轮重建
}
```

实测：单次成功率 1/3 左右，15 次重建必成功。平均 2-3 次。

**代价**：每次重建 3-8 秒。所以常驻服务的预热要按"最坏 15 次"估时间。

---

## 7. 自毁 handler / 异常退出

| 现象 | 原因 | 处理 |
|---|---|---|
| 跳到 `0x1000` / `0x4000` / `0x8000` 崩溃 | 自毁 handler | patch 掉：把 handler 前 8 字节改成 `adr x0,#0; ret` |
| `svc #0x1a0`（exit） | native 判定环境非法 | 常见原因：设备 ID 未注册、配置项错、时间戳异常 |
| 静默返回 null | 某个 Phase 没通过 | 开 verbose 看最后一个成功的调用 |

**自毁 handler 的识别**：反汇编里 `add x1, x0, #0x34; br x1`，`x0` 来自 `bl get_pc`，
跳转目标落在 `.text` 之外的低地址。

---

## 8. 常驻服务形态（需要 >10 次/秒 时）

```
Config → SignService（一个 emulator + 一台身份）
        → SignServicePool（N 个实例）
        → Controller（REST）
```

三条设计要点：

| 要点 | 说明 |
|---|---|
| 每实例一条线程 | 见 §5 |
| 每实例一个"身份" | 签名和请求参数必须同源，否则服务端拒绝 |
| 池大小 = 实际并发 | 每实例约 120MB，预热 3-8 秒/个（含重试更久） |

参考实现：任一已完成仿真的项目里的「Signer + 常驻服务」骨架；
最小骨架见本技能同级的专项技能目录（如 `assets/minimal-harness`）。

---

## 9. 验收（仿真最容易自欺的地方）

**"能出签名"完全不等于"服务端接受"。**

| 层级 | 判据 |
|---|---|
| ① 库加载 | `JNI_OnLoad` 返回 OK |
| ② 初始化 | 配置验证返回 `true`，拿到 session handle（非 0） |
| ③ 产出 | 签名函数返回非空，形态符合预期（长度/前缀） |
| ④ **真实请求** | HTTP 200 + 业务码 0 + **数据非空** |

只到 ③ 就宣布成功，是最常见的错误。

---

## 10. 仿真特有陷阱速查

| 陷阱 | 症状 | 处理 |
|---|---|---|
| 喂真实设备的状态文件 | VM 崩溃 / `svc` 退出 | 状态文件常被设备绑定加密，**不要提供**，让库自己生成 |
| 用假设备 ID | `svc` 直接退出 | 必须是已注册的真实 ID，或自己先注册 |
| 每次调用启一次 JVM | 5-10 秒/次 | 改常驻，单次降到 50ms 内 |
| 实例数拍脑袋 | 12 个实例只用 4 个 | 按并发定，见 delivery-principles |
| 只验证"出签名" | 服务端一直拒绝 | 必须做 §9 第 ④ 层 |
| 静态 xref 找不到 | 字符串走间接表 | 改用运行时 hook 或特征码扫描 |
| ADRP 解码漏扫 | xref 为 0 | 掩码 `(w & 0x9F000000) == 0x90000000`，别加 `0x1F` |
| 把跳板当函数入口 | 字节是 `ldr x16,#8; br x16` | 读 `+8` 处的指针才是真函数 |

---

## 11. 一句话

> 仿真的成败在于 **JNI 环境喂得对不对**，不在于读懂算法。
> 卡住时开 verbose 看缺哪个回调；不稳定就重建实例；最后一定要真实请求验收。
