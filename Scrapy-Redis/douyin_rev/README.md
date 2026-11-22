# douyin_rev · 抖音用户采集（Scrapy-Redis + unidbg）

按 `Scrapy-逆向工程架构标准.md` 搭的站点工程：一个用户主页 = 一条任务，
抓 **用户详情 → 作品列表 → 每个视频的评论**，落三张表，支持断点续跑与任务互斥。

签名不自己做：调本地 unidbg 服务（`douyin-sign-server`，端口 8099）拿六神头，
并支持**按设备签名**（`/api/sign?device=<id>`），保证「请求参数里的 device_id」和
「签名用的设备」同源。

## 目录

```
douyin_rev/
├── scrapy.cfg  requirements.txt  .env.example
├── sql/01_init.sql                  MySQL 建表（SQLite 自动建）
├── runtime/                         内置签名服务（jar + so，开箱验证用）
│   ├── DouyinSign.jar               unidbg 常驻签名服务
│   ├── so/libmetasec_ml.so          六神签名库
│   ├── so/libEncryptor.so           设备注册加密库
│   ├── so/libc++_shared.so          C++ 运行库
│   └── devices.jsonl                （运行时生成，注册的设备追加写入）
├── scripts/
│   ├── start_sign_server.py         启动内置签名服务
│   ├── seed_user_task.py            往 user_task 插任务
│   └── run_worker.py                dispatcher + spider
├── tests/test_contracts.py          契约 + 自愈回归
└── douyin_rev/
    ├── settings.py                  3 行换站旋钮
    ├── signer/{base,device,strategy}.py   契约 / 设备池 / unidbg 签名
    ├── tasks/{task_state,dispatcher}.py   状态机 + 投喂
    ├── db/{__init__,models}.py      引擎工厂 + 四张表
    ├── spiders/user_spider.py       编排（三段状态机）
    └── query.py parser.py items.py middlewares.py pipelines.py config.py
```

## 快速开始

```bash
# 1. 起 unidbg 签名服务（jar 和 so 都在本工程 runtime/ 下，开箱即用）
python scripts/start_sign_server.py --wait
#   默认 8099、12 实例、500ms 间隔；可改 --port/--pool-size/--interval-ms

# 2. 起 Redis（scrapy-redis 队列）
D:\tools\redis\redis-server.exe

# 3. 装依赖
pip install -r requirements.txt

# 4. 播种任务
python scripts/seed_user_task.py "https://www.douyin.com/user/MS4wLjABAAAA..."

# 5. 跑 worker（dispatcher 自动投喂，爬虫消费）
python scripts/run_worker.py
```

单次调试（不经过 dispatcher）：

```bash
redis-cli lpush douyin_rev:start_urls "https://www.douyin.com/user/MS4wLjABAAAA..."
python -m scrapy crawl user -a video_pages=1 -a comment_pages=2
```

## 四张表

| 表 | 内容 | 唯一键 |
|---|---|---|
| `user_task` | 任务 + 断点（cursor / 页码 / 阶段） | `user_url` |
| `user_profile` | 用户详情（昵称/uid/抖音号/粉丝/获赞） | `sec_user_id` |
| `user_videos` | 作品列表（aweme_id/描述/点赞/评论数/播放地址） | `aweme_id` |
| `user_video_comments` | 评论（cid/内容/点赞/作者） | `cid` |

MySQL 建表用 `sql/01_init.sql`；不配 `DY_DB_URL` 时自动落 SQLite（`douyin_rev.db`）。

## 断点续跑

`user_task` 上的断点列：

```
video_cursor      作品列表 max_cursor（毫秒时间戳，BIGINT）
video_pages       已翻页数
video_index       评论阶段：处理到第几个视频
comment_aweme_id  当前视频
comment_cursor    评论 cursor（整数）
comment_pages     该视频已翻页数
```

进程崩了之后，`dispatcher` 每拍开头先跑 `reclaim_stale_running_user_task()`，
把 `running` 且超过 `DY_STALE_RUNNING_SEC`（默认 900s）没更新的行翻回 `pending`，
保留全部断点列，下一拍自动续抓。

## 任务互斥

- `claim_task()`：Redis `SETNX douyin_rev:task_lock:<id>`（TTL 600s）+ 行置 `running`
- 抓完 `complete_task()` / `fail_task()` 时删锁
- `dispatcher` 另有 `douyin_rev:dispatch_guard:<id>`（TTL 600s），防止同一任务在队列里被重复 LPUSH

## 设备与匿名请求（关键发现）

三个接口对「设备身份」的要求不一样，实测结论：

| 接口 | 需要的身份 | 说明 |
|---|---|---|
| 用户详情 | 真实 `iid` | `iid=0` 会返回空 user |
| 作品列表 | **匿名即可（`iid=0`）** | 新注册 iid 会返空，但匿名反而能过 |
| 评论 | 真实或匿名都行 | 新设备也能抓 |

### 为什么会这样

脚本注册的新设备被服务端标成 `new_user=1`，作品列表接口对这类安装**静默返回空 body**；
而**匿名请求（iid=0）不受此限制**——100 次压测 100/100 成功。

所以作品列表不再依赖「受信任 iid」：

```
posts_device() = 随机 device_id + iid=0（匿名）
                ↓ 匿名失效时
                熔断切到真机 iid（DY_TRUSTED_IIDS）→ 再失败则降级（只抓详情+评论）
```

### 熔断与降级

- 连续 `DY_POSTS_BREAKER`（默认 10）次作品列表为空 → 探测当前 iid
- 探测失败 → 按优先级换下一个 iid
- 全部失败 → `posts_degraded=True`，spider 跳过作品列表继续抓详情/评论
- `scripts/check_posts_health.py` 可挂定时任务做健康检查

## 环境变量

见 `.env.example`。常用：

```
DY_SIGN_SERVICE=http://127.0.0.1:8099
DY_CONCURRENT_REQUESTS=8
DY_VIDEO_PAGES=50        单用户最多翻多少页作品
DY_COMMENT_PAGES=5       单视频最多翻多少页评论
DY_STALE_RUNNING_SEC=900
```

## 测试

```bash
python -m pytest tests/ -q
```

覆盖：settings 注入契约、stale-running 自愈（保留断点）、fresh-running 不误收、
dispatcher guard TTL ≥ 锁 TTL。
