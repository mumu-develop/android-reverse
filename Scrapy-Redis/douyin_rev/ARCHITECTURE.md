# 架构说明（douyin_rev）

对照 `Scrapy-逆向工程架构标准.md` 的落地说明。本文只说「本工程怎么套标准」，标准原文见仓库根目录。

## 1. 分层映射

| 标准层 | 本工程文件 | 说明 |
|---|---|---|
| application 编排 | `spiders/user_spider.py` | 三段状态机：profile → videos → comments |
| 契约（插槽） | `signer/base.py` | `SigningStrategy` / `SignedReq`，全工程不改 |
| 适配器（插头） | `signer/strategy.py` | `UnidbgStrategy`：调 HTTP 服务签名 |
| 站点逆向基建 | `query.py` `parser.py` | 三个接口的 URL 构造 + JSON 解析 |
| 数据层 | `db/__init__.py` `db/models.py` | 引擎工厂（样板）+ 四张表（站点） |
| 任务生命周期 | `tasks/task_state.py` `tasks/dispatcher.py` | claim/progress/complete/fail + 自愈 + 投喂 |
| scrapy 粘合 | `middlewares.py` `pipelines.py` | 签名中间件 + 三类 Item 落库 |
| 装配根 | `settings.py` | 3 行旋钮 |

## 2. 装配根（3 行）

```python
SIGNING_STRATEGY = "douyin_rev.signer.strategy.UnidbgStrategy"
FETCHER_STRATEGY = "douyin_rev.fetcher.RequestsFetcher"
QUEUE_PREFIX     = "douyin_rev"
```

`middlewares.SignerMiddleware.from_crawler` 用 `load_object` 注入签名实现，
中间件只 import `signer/base` 的契约，不 import 具体策略 —— 换站只改 settings 一行。

## 3. 一次任务的生命周期

```
dispatcher.poll_pending_and_dispatch()
  ├─ reclaim_stale_running_user_task()      卡死行翻回 pending（保留断点）
  ├─ list_pending_tasks(limit)
  ├─ SETNX dispatch_guard:<id> TTL 600       防止重复投喂
  └─ LPUSH douyin_rev:start_urls <user_url>

spider.make_request_from_data(url)
  ├─ find_task_by_url + claim_task（SETNX task_lock + 行置 running）
  ├─ 选设备 → 拼 URL → 请求（带 same device）
  └─ 按断点决定先抓哪段

profile → user_profile
videos  → user_videos（max_cursor 翻页）
comments→ user_video_comments（cursor 翻页，逐视频推进 video_index）

完成后 complete_task（删锁）；异常 fail_task(partial=True)（保留断点）
```

## 4. 并发模型

- 签名是同步 HTTP（~50-150ms），放在 Twisted 线程池里（`threads.deferToThread`），
  不阻塞 reactor；并发上限 `CONCURRENT_REQUESTS=8`。
- unidbg 服务侧是 6 个常驻实例，天然支持 6 路并行签名。
- `AUTOTHROTTLE` 打开：被软限流会自动降速。

## 5. 设备同源（本工程的关键约束）

```
选设备（DevicePool）
  → query.xxx_url(device)          参数里带 device_id / iid / cdid
  → /api/sign?url=...&device=<id>  服务用同一台设备的实例签名
  → 请求头 X-Gorgon 等
```

若签名设备与参数设备不一致，服务端会返回空 user 或 -99999。
`strategy.warm()` 用作品列表接口做探针，只把"真能取到数据"的设备放进可用池。

## 6. 断点续跑与自愈

| 机制 | 实现 |
|---|---|
| 断点字段 | `video_cursor / video_pages / video_index / comment_aweme_id / comment_cursor / comment_pages` |
| 崩溃恢复 | `reclaim_stale_running_user_task()`：`running` 且 `updated_at` 超阈值 → `pending`（保留断点） |
| 阈值约束 | `DY_STALE_RUNNING_SEC(900) > DY_LOCK_TTL(600)` |
| 只回收喂源表 | 只回收 `user_task`（被 dispatcher 投喂的那张） |
| spider 早退收尾 | `spider_closed` 把本 worker 的 running 行翻 `partial`，错误写 `spider_closed_early` |

## 7. 与 tiktok_rev 的差异

| 项 | tiktok_rev | douyin_rev |
|---|---|---|
| 签名 | iv8 跑 JSVMP（`signer/js/`） | HTTP 调 unidbg 服务 |
| Cookie | 强依赖（ttwid 暖态） | 不需要 |
| 设备 | 单一真机身份 | 可注册设备池 + 可用性探针 |
| 任务表 | user_task + tiktok_task 双表 | 单表 user_task（自带断点列） |
| 数据表 | tiktok_video 等 | user_profile / user_videos / user_video_comments |

## 8. 内置运行时（runtime/）

工程自带签名服务，克隆下来即可跑：

```
runtime/
├── DouyinSign.jar       unidbg 常驻签名服务（Spring Boot，监听 8099）
├── so/libmetasec_ml.so  六神签名库
├── so/libEncryptor.so   设备注册加密库
└── so/libc++_shared.so  C++ 运行库
```

启动：

```bash
python scripts/start_sign_server.py --wait
# 等价于在 runtime/ 下执行：
#   java -jar DouyinSign.jar --douyin.sign.pool-size=12 \
#        --douyin.sign.per-device-interval-ms=500
```

为什么必须 `cwd=runtime/`：`application.yml` 里 `so-path` 是相对路径（`so/libmetasec_ml.so`），
脚本已处理。`devices.jsonl` 也会生成在 `runtime/` 下。

> 签名吞吐 ≈ `pool-size ÷ (interval/1000)`。12 实例 × 500ms ≈ 21 次/秒。
