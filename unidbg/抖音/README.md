# 抖音 unidbg 签名 + 数据抓取

纯 PC 完成，不依赖真机、不依赖 RPC。

- **六神签名**：unidbg 加载 `libmetasec_ml.so`，产出 X-Argus / X-Gorgon / X-Helios / X-Khronos / X-Ladon / X-Medusa
- **设备注册**：unidbg 加载 `libEncryptor.so`，TTEncrypt 指纹后注册，拿到全新 device_id
- **数据抓取**：用签名头请求官方接口，解析评论、支持翻页

---

## 文件

| 文件 | 说明 |
|---|---|
| `dy-unidbg.py` | 主脚本（自动拉起服务、注册设备、签名） |
| `dy-user-profile.py` | **用户详情** |
| `dy-user-posts.py` | **用户作品（视频）列表** |
| `dy-video-comments.py` | **视频评论** |
| `DouyinSign.jar` | 常驻签名服务（Spring Boot，端口 8099） |
| `so/libmetasec_ml.so` | 六神签名 |
| `so/libEncryptor.so` | TTEncrypt（设备注册） |
| `so/libc++_shared.so` | C++ 运行库 |
| `math_comments.json` | 评论样本数据（11 MB，可删） |

无第三方 Python 依赖，只用标准库。

---

## 用法

### 三个接口脚本（推荐）

```bash
# 1. 用户详情：昵称/uid/粉丝/作品数/获赞
python dy-user-profile.py <sec_user_id> -o user.json

# 2. 用户作品列表：自动按 max_cursor 翻页
python dy-user-posts.py <sec_user_id> -p 3 -o posts.json

# 3. 视频评论：支持传 aweme_id 或分享链接，按 cursor 翻页
python dy-video-comments.py <aweme_id|分享链接> -p 5 -o comments.json
```

`sec_user_id` 从哪来：评论接口返回的 `user.sec_uid`，或抖音主页链接 `/user/MS4wLjABAAAA...`。

### 签名服务相关

```bash
# 对任意 URL 生成签名
python dy-unidbg.py sign "https://aweme.snssdk.com/aweme/v2/comment/list/?..."

# 自主注册一个新设备
python dy-unidbg.py register

# 签名吞吐测试
python dy-unidbg.py bench -n 10

# 前台启动服务 / 查看状态
python dy-unidbg.py serve
python dy-unidbg.py health
```

输出示例：

```
[*] 启动签名服务 ...
[*] 服务就绪（29 秒，实例 2 个）
[cursor=0   ] status=0 本页=20 has_more=1
[cursor=20  ] status=0 本页=21 has_more=1
共 41 条评论
```

---

## 实测性能

| 指标 | 结果 |
|---|---|
| 单次签名 | 平均 48-60 ms |
| 签名成功率 | 10/10 |
| 单页采集 | 约 550 ms |
| 设备注册 | 约 1.4 秒 |

---

## 设备身份与设备池

服务默认用配置里写死的身份（`application.yml` 内嵌在 jar 里），
也可以现场注册新设备：

```bash
python dy-unidbg.py register                 # 注册 1 台
python dy-unidbg.py register -n 5            # 注册 5 台
python dy-unidbg.py register -n 3 --verify   # 注册并逐台验证能否取数据（慢，约 10 秒/台）
```

输出：

```
#1  3154978215331079 google  Pixel 7  Android13 1080*2400@420dpi google_1128_64  验证=OK
#2  3295715703395587 vivo    V2254A   Android14 1260*2800@453dpi vivo_1128_64    验证=OK
```

### 指纹多样性

从 **19 个真实机型画像**里随机抽，字段互相自洽：

| 品牌 | 型号 | 系统 | 分辨率 | DPI |
|---|---|---|---|---|
| Xiaomi | 2211133C | Android 13 | 1080*2400 | 440 |
| Redmi | 22127RK46C | Android 13 | 1220*2712 | 526 |
| HUAWEI | MNA-AL00 | Android 12 | 1224*2700 | 458 |
| HONOR | PGT-AN10 | Android 13 | 1224*2688 | 461 |
| OPPO | PGT-AN00 | Android 13 | 1240*2772 | 450 |
| vivo | V2254A | Android 14 | 1260*2800 | 453 |
| samsung | SM-S9110 | Android 13 | 1080*2340 | 425 |
| OnePlus | PHB110 | Android 13 | 1440*3216 | 525 |
| google | Pixel 7 / 8 | Android 13/14 | 1080*2400 | 420/428 |
| motorola | XT2308-4 | Android 13 | 1080*2400 | 402 |
| … | 共 19 个 | | | |

每次注册随机的部分：

- 机型画像（品牌/型号/系统/API/分辨率/DPI/ROM/渠道）
- `cdid`、`openudid`、`clientudid`
- 运营商 `mcc_mnc`、首次启动时间（近 1-90 天）

### 设备池文件

注册结果（含 `device_token`）追加写入 `devices.jsonl`，一行一台：

```json
{"device_id":"3154978215331079","install_id":"...","cdid":"...",
 "device_token":"AAA...","brand":"google","model":"Pixel 7",
 "os_version":"13","resolution":"1080*2400","dpi":420,"channel":"google_1128_64"}
```

### 用新设备

把 `device-id` / `install-id` / `cdid` 写进
`D:\idea\IdeaProjects\douyin-sign-server\src\main\resources\application.yml`
后重新打包，或直接用 `/api/register` 返回的 `suggest_config`。

---

## 注意

1. **必须在本目录启动服务**（脚本已处理），因为 `so/` 用的是相对路径。
2. **端口 8099 会冲突**：本目录和 `D:\idea\IdeaProjects\douyin-sign-server` 各自都能拉起服务，
   同时只能跑一个。
3. 已验证的接口：
   - `/aweme/v1/user/profile/other/`（用户详情）
   - `/aweme/v1/aweme/post/`（作品列表）
   - `/aweme/v2/comment/list/`（评论）
   其他接口换 URL 即可，但参数要自己补齐。
4. **评论有可见深度上限**：cursor 到 6000-8000 后返回空页，覆盖率约 50-60%，不是 bug。
5. **设备级限流**：每台设备约 15-20 请求/窗口，超出软封 1-3 分钟，翻页多时要放慢或换设备。
6. 请遵守目标站点的服务条款，仅用于学习研究。
