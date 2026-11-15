# minimal-harness

抖音六神签名的最小可运行工程。**不是玩具**——这套代码结构和正式项目一致，
换版本时改几个常量就能继续用。

**399 行，已剔除所有探测/基准代码**（`probeOps`/`probeOne`/`directSign`/`ResidentBench` 只保留在开发分支）。

## 文件

```
minimal-harness/
├── pom.xml
├── src/main/java/com/dy/sign/DouyinMetasecSign.java   # 全部逻辑都在这里
└── so/                                                # 需要你放进来
    ├── libmetasec_ml.so
    └── libc++_shared.so
```

`so/` 目录要自己建并放文件（从 APK 的 `lib/arm64-v8a/` 解出来）：

```bash
unzip -o base.apk "lib/arm64-v8a/libmetasec_ml.so" "lib/arm64-v8a/libc++_shared.so" -d so/
mv so/lib/arm64-v8a/*.so so/ && rm -rf so/lib
```

## 编译运行

```bash
mvn -q -DskipTests package

java -Dinit=true \
     -Dsignurl="https://aweme.snssdk.com/aweme/v2/comment/list/?aweme_id=xxx&cursor=0&count=20&aid=1128&device_platform=android&device_id=xxx&iid=xxx" \
     -Ddeviceid=<真实 device_id> \
     -Dinstallid=<真实 install_id> \
     -Dchannel=810 \
     -cp "target/classes;target/deps/*" com.dy.sign.DouyinMetasecSign
```

Windows 用 `;` 分隔 classpath，Linux/macOS 用 `:`。

## 期望输出

```
[*] s4.LIZ (SDK ver) = "v04.10.04"
[*] init returned = true
[+] INIT OK — session handle = 314318848
===HEADERS_START===
X-Argus=...
X-Gorgon=8404...
X-Helios=...
X-Khronos=...
X-Ladon=...
X-Medusa=...
===HEADERS_END===
```

## 换版本要改什么

打开源码搜 `VERSION-SPECIFIC`：

| # | 常量 | 40.2.0 值 | 怎么重新拿 |
|---|---|---|---|
| 1 | `LICENSE` | 244 字节 base64 | jadx 搜 `SecApiImpl` 静态字段，见 `version-adaptation.md` §3 |
| 2 | `s4` 解密参数 | keyhex `bebb7f` + seed 9 字节 | 见 §4，或直接抄配置 JSON 索引 4 |
| 3 | `VER` / `VERCODE` | `"40.2.0"` / `800` | `adb shell dumpsys package ... \| grep version` |
| 4 | `channel` | `810` | 真机配置 JSON 索引 12 |
| 5 | op 码 | 见 `sixgod-contract.md` §2 | 静态没变就不用动 |
| 6 | 请求参数集 | 见 `sixgod-contract.md` §8 | 从真机 WebSocket URL 抓 |

## 已知行为（不是 bug）

### 初始化有约 1/3 成功率

同一份代码连跑 6 次可能只成功 2 次。**这是 so 的非确定性行为**，不是你的错。

单次失败表现为：
- `frameSign returned: null`
- 或直接 `svc #0x1a0` 退出

**处理**：外面套一层重建循环（正式项目里是 15 次），详见 `unidbg-route.md` §4。
本模板为了保持可读性没有内置重建，**生产用必须加**。

### 不要喂 `.msdata`

`IOResolver` 里对 `.msdata/` 路径返回 null。真机的状态文件被设备绑定加密，
喂进去会让 VM 崩溃。

### device_id 必须是已注册的

假 id 会触发 `svc #0x1a0` 直接退出。

没有真实 id 时，先按 `unidbg-route.md` §6 自己注册一台。

## 加重建逻辑的最小改法

```java
public static DouyinMetasecSign createWithRetry(String url) {
    for (int i = 0; i < 15; i++) {
        DouyinMetasecSign s = new DouyinMetasecSign(so, cpp, null);
        s.initIfNeeded();
        if (s.signHeaders(url, 0, 3) != null) return s;
        // 失败 → 丢弃，下一轮全新实例
    }
    throw new IllegalStateException("15 次重建都失败");
}
```

## 下一步

跑通后要：
- **常驻服务**（48ms/次、多设备轮换）→ 参考 `unidbg-route.md` §5
- **设备注册**（自主造设备池）→ 参考 `unidbg-route.md` §6
