# jadx / IDA MCP 使用手册

> 由 `apk-reverse` 按需引用。只在要用 MCP 查代码、或调用报错需要排查时读这份。

## 0. 依赖的活服务（缺一不可）

| 服务 | 端口 | 前置 |
|---|---|---|
| jadx | `127.0.0.1:8650` | jadx-gui 已打开目标工程，JADX-AI-MCP 插件已启动 |
| ida-pro-mcp | `127.0.0.1:13337` | IDA 已打开目标 so，插件已启动（`Ctrl+Alt+M`） |

**插件只能操作「当前 GUI 里打开的那个 IDB / 工程」** —— 换文件必须人工在 GUI 里打开。

探测方式：

| 服务 | 探测 | 就绪标志 |
|---|---|---|
| jadx | `list_mcp_resources(server="jadx")`，或存在 `mcp__jadx__` 工具 | 返回 `JADX-AI-MCP` |
| IDA | `mcp__ida__check_connection()` | `Successfully connected to IDA Pro (open file: xxx)` |

端口层兜底（MCP 工具没注册时）：

```python
import socket
for p in (8650, 13337):
    s = socket.socket(); s.settimeout(1)
    try: s.connect(("127.0.0.1", p)); print(p, "OPEN")
    except Exception: print(p, "closed")
```

**请用户启动时，直接给这几步（照抄）：**

jadx：

```
1. 用 jadx-gui 打开目标 APK（或 dump 出来的 dex）
2. 确认插件已启用：菜单 JADX-AI → MCP Server → Start Server
3. 验证：浏览器打开 http://127.0.0.1:8650/health 有响应
```

IDA：

```
1. 用 IDA 打开目标 .so（不是 .i64）
2. 按 Ctrl+Alt+M（或 Edit → Plugins → MCP）
3. Output 出现 [MCP] Server started at http://localhost:13337
4. 若菜单里没有 MCP：Alt+F7 运行
   import idaapi; idaapi.load_and_run_plugin(r"<IDA>\plugins\mcp-plugin.py")
```

## 1. jadx MCP

| 目的 | 调用 |
|---|---|
| 按关键字搜类 | `search_classes_by_keyword(search_term, search_in="class"\|"code"\|"method", count)` |
| 拿整类源码 | `get_class_source(class_name)` |
| 列方法 / 字段 | `get_methods_of_class(class_name)` / `get_fields_of_class(...)` |
| 取单个方法 | `get_method_by_name(class_name, method_name)` |
| 谁引用了它 | `get_xrefs_to_method(class_name, method_name)` / `get_xrefs_to_class(...)` |
| smali | `get_smali_of_class(class_name)` |
| 给代码加注释 | `add_comment(class_name, comment, line=...)`（可持久化，便于二轮） |

**坑**：

- 参数名是 `search_term`，不是 `keyword`
- 搜索是**子串匹配**：查 `_sig` 会命中 `signal`/`signature` 上百条；改用更独特的串（`os_rom`、`Asia/Shanghai`、包名、常量 UUID）
- **别调 `get_package_tree`** —— 一次返回 1.2 MB，纯浪费上下文
- 类名必须精确（`cn.thecover.lib.common.utils.LogShutDown`，写成 `...manager.` 会 404）
- 打开的是纯 dex（非 APK）时，`get_android_manifest` 会报 `AndroidManifest.xml not found`，正常

## 2. IDA MCP

| 目的 | 调用 |
|---|---|
| 按符号定位 | `get_function_by_name(name)` |
| 伪代码 | `decompile_function(address)` |
| 汇编 | `disassemble_function(start_address)` |
| 引用 / 调用者 | `get_xrefs_to(address)` / `get_callers(function_address)` / `get_callees(...)` |
| 字符串 / 导入 | `list_strings_filter(filter, offset, count)` / `list_imports(...)` |
| 读内存（解密钥/常量） | `read_memory_bytes(memory_address, size)` |
| 改名/改类型/打补丁 | `rename_function` / `set_function_prototype` / `patch_address_assembles` |

**坑**：

- 地址传**十六进制字符串**（`"0x1AF20"`）
- `get_function_by_name` 是精确匹配：要找的 `init_proc` 在 IDA 里可能叫 `.init_proc`
- **C++ 名字要按 mangled 形式查**：`HNASignature::parseParamJSON` 要写成
  `_ZN12HNASignature14parseParamJSONERKNSt6__ndk112basic_stringIcNS0_11char_traitsIcEENS0_9allocatorIcEEEE`；
  猜不对就先 `decompile_function` 看调用点的 `bl` 目标，或用 `list_functions` 过滤
- 只能查当前打开的 IDB；查另一个 so 要请用户在 GUI 里切换
- 遇到加壳 so（自定义段 `.gnu.fragment` / `.gnu.draft`）反汇编是乱码 → 静态到此为止，转动态

## 3. 典型串法（dex → so）

```
1. jadx: search_classes_by_keyword("loadLibrary", search_in="code")
2. jadx: get_class_source(<命中类>)          → 确认 native 方法与参数
3. IDA : get_function_by_name("Java_<pkg>_<Cls>_<method>")
4. IDA : decompile_function(addr)             → 伪代码里读常量/分支
5. 需要常量时: read_memory_bytes(0x...)       → 解出 XOR 密钥/明文串
6. 回到 jadx 验证调用顺序，或直接写客户端复现
```

## 4. 什么时候不要用 MCP

| 任务 | 用什么 |
|---|---|
| 批量找类/方法（几万文件） | jadx CLI + grep |
| 跨多个 so 离线比对 | capstone 脚本 |
| 需要批量反汇编 | capstone |
| 定点看一个类/一个函数 | **MCP** |
