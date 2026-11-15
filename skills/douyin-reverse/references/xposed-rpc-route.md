# Xposed + RPC 路线

目标：在真机上跑抖音的签名逻辑，通过 Sekiro 把结果 RPC 出来给 PC 用。

**优点**：最真实（就是真机），2 小时能通。
**缺点**：依赖手机常开、单进程串行、不能批量。

## 0. 前置

| 项 | 要求 |
|---|---|
| 手机 | root（APatch / Magisk 均可）+ LSPosed |
| 抖音 | 目标版本已安装并**登录过一次**（保证已注册/有网络） |
| PC | Android Studio、JDK 17+、Python 3.10+ |
| Sekiro 服务端 | `sekiro-server`（Java），端口默认 5603 |
| 通信 | `adb reverse tcp:5603 tcp:5603`（PC 与手机不同网段时必需） |

## 1. 定位要 hook 的调用点

用 jadx 打开 APK，按接口路径反查：

```bash
grep -rn "aweme/v2/comment/list" sources/ | head
```

抖音的网络层是壳化的，直接搜 URL 往往搜不到，改搜**接口常量类**或
`CommentListApi`、`AwemeApi` 这类命名：

```bash
grep -rn "class CommentListApi" sources/
grep -rn "loadMoreComments" sources/ | head
```

典型结构：

```java
// 接口定义
public interface CommentListApi {
    @GET("/aweme/v2/comment/list/")
    Observable<CommentResponse> loadMoreComments(@Query("aweme_id") String awemeId, ...);
}
// 实例获取：单例藏在 LIZ 里
CommentListApi api = CommentListApi.LIZ.LIZIZ;   // 命名因版本而异，需实测
```

**定位实例的通用办法**：hook 接口的任意方法，在 `onEnter` 里取
`thisObject` 的类型，或用 Frida 先枚举 `Java.choose('...CommentListApi', ...)`。

## 2. 搭 Xposed 模块

### Gradle

```kotlin
// app/build.gradle.kts
dependencies {
    compileOnly(files("libs/xposed-api-stub.jar"))            // 本地 stub
    implementation("cn.iinti.sekiro3.business:sekiro-business-api:1.7")
}
android {
    packaging {
        resources {
            pickFirsts += "META-INF/io.netty.versions.properties"
            pickFirsts += "META-INF/LICENSE*"
        }
    }
}
```

```kotlin
// settings.gradle.kts
repositories {
    maven { url = uri("https://nexus.iinti.cn/repository/maven-public/") }  // Sekiro 依赖
}
```

### 目录约定（纯 Java，不要 Kotlin/Compose）

```
app/src/main/
├── assets/xposed_init                       # 一行：入口类全名
└── java/com/example/myapplication/
    ├── core/
    │   ├── XposedEntry.java                 # IXposedHookLoadPackage
    │   ├── AppPlugin.java                   # 每包一次的装载逻辑
    │   └── SekiroRegistrar.java             # 注册 RPC action
    └── plugin/
        ├── DouyinPlugin.java                # 抖音专用
        └── TemplatePlugin.java              # 复制模板
```

### 入口

```java
public class XposedEntry implements IXposedHookLoadPackage {
    @Override public void handleLoadPackage(LoadPackageParam lpparam) {
        if (!"com.ss.android.ugc.aweme".equals(lpparam.packageName)) return;
        // 用 Application.attach 时机，避免类加载过早
        XposedHelpers.findAndHookMethod(Application.class, "attach",
                Context.class, new XC_MethodHook() {
            @Override protected void afterHookedMethod(MethodHookParam param) {
                SekiroRegistrar.start((Context) param.args[0]);
            }
        });
    }
}
```

### RPC action

```java
SekiroClient client = new SekiroClient("0.0.0.0", 5612, "douyin-" + androidId);
client.registerHandler("comments", (request, response) -> {
    String awemeId = request.getStringParams().get("aweme_id");
    // 反射调 CommentListApi.loadMoreComments(...) —— 28 个参数，缺一不可
    Object api = getCommentApi();
    Object result = ReflectHelper.invoke(api, "loadMoreComments", args...);
    response.sendSuccess(result.toString());
});
client.start();
```

**要点**：
- action 名自己定，Python 侧对应
- 参数用 `request.getStringParams()`
- 返回值塞 JSON 字符串，别塞二进制

### 出包

```kotlin
tasks.register<Copy>("exportApk") {
    from("$buildDir/outputs/apk/debug/app-debug.apk")
    into("$rootDir/dist")
    rename { "DouyinRpc-debug.apk" }
}
```

## 3. 部署

```bash
adb install -r dist/DouyinRpc-debug.apk
# LSPosed 里启用模块，勾选抖音作用域
# ⚠️ 必须"停止抖音再启动"，模块不会热注入
adb shell am force-stop com.ss.android.ugc.aweme
adb shell am start -n com.ss.android.ugc.aweme/.splash.SplashActivity
```

验证注入：

```bash
adb logcat -s XposedTag   # 看模块自己的日志
```

## 4. 起 Sekiro 服务端

```bat
:: 启动Sekiro服务端.bat
java -jar sekiro-server.jar
```

客户端连的是**模块里 `SekiroClient` 的端口**（示例 5612），PC 侧要：

```bash
adb reverse tcp:5612 tcp:5612
```

## 5. Python 客户端

```python
from sekiro import SekiroClient          # 或直接用 requests 打 HTTP 网关
cli = SekiroClient("127.0.0.1", 5612, "douyin-pc")
resp = cli.invoke("comments", {"aweme_id": "7xxxxxxxxxxxxxxxxxx"})
print(resp)
```

实战里更省事的是直接走 Sekiro 的 HTTP 网关：

```python
r = requests.post("http://127.0.0.1:5612/business/invoke",
                  json={"clientId": "douyin-pc", "action": "comments",
                        "params": {"aweme_id": aweme_id}})
```

## 6. 验收

```bash
curl http://127.0.0.1:5612/business  # 能看到 client 注册信息
python douyin-rpc.py --ping          # 通
python douyin-rpc.py --aweme <id>    # 返回评论 JSON（实测 233KB+）
```

## 7. 这条路线的坑

| 坑 | 现象 | 处理 |
|---|---|---|
| 模块不生效 | 装完没日志 | 必须 force-stop 再启动，LSPosed 不热注入 |
| 作用域没勾 | 模块加载但 hook 不到 | LSPosed 里给抖音勾上，重启 App |
| 类找不到 | `ClassNotFoundException` | 抖音壳化，类名带混淆；用 jadx 确认后用字符串类名加载 |
| 参数不匹配 | 反射报 `IllegalArgumentException` | 28 个参数的类型必须逐一核对（含 `long`/`int`/`String`/`Object`） |
| Sekiro 连不上 | `connection refused` | `adb reverse` 没做，或手机与 PC 不同网段 |
| 单进程瓶颈 | 并发上不去 | 这是路线本身的限制；要并发换 unidbg |

## 8. 什么时候选这条

- 只要几百~几千条，当天要结果
- 手机常开、可以接受单机
- 想先确认"接口到底返回什么"，再决定是否投入 unidbg

要批量/长期/离线 → 转 `unidbg-route.md`。
