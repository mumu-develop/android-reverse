---
name: scrapy-reverse-arch
description: >-
  搭建、脚手架或重构 Python scrapy 逆向采集工程的"项目架构层":每个站点一个独立 scrapy 工程,遵循统一
  分层 + 目录格式 + 可插拔 Protocol 契约(SigningStrategy/FetcherStrategy/TaskState),用 scrapy 原生
  from_crawler + load_object 做 settings 驱动装配,换站只改 3 行 settings。强触发:scrapy 标准/架构、
  一套架构多站复用/可插拔、建/重构 scrapy 逆向工程、scrapy 项目脚手架、按标准改造某 spider 工程。
  不用于签名算法逆向/入口定位(camoufox-js-reverse、iv8-web-reverse)、完整协议恢复(web-protocol-recovery)、
  补环境(env-patch)、AST 解混淆(ast-deobfuscate);这些逆向出来后工程怎么搭架子才归本 skill。
argument-hint: "[scrapy 逆向工程目录或站点名]"
compatibility: "Python 3.10+, scrapy 2.18+, twisted;(可选 iv8 / curl_cffi / sqlalchemy / redis)"
---

# Scrapy 逆向工程架构标准

本 skill 只管"已经逆向出签名之后,scrapy 工程怎么搭架子"。**权威标准文档**:`Scrapy-Redis/Scrapy-逆向工程架构标准.md`
(动手前先读它)。参考实现:本仓 tiktok_rev 工程(user+tag 双 spider iv8 mark VIII,容器回归全过)。

## 入口判定

1. **新建站点工程** — 按 `Scrapy-逆向工程架构标准.md` §3 目录 + §9 步骤搭;`scrapy startproject` 起骨架,补逆向模块目录,填站点 slot,改 settings 3 行。**第一拍先做 cookie 依赖判别**(下方 ⚑),决定 strategy 装不装 `cookie_loader`、`reveal_*` 步骤 lazy 不 lazy。
2. **重构/标准化存量工程** — 对照 §3 目录 + §6 样板/slot 清单,把命名对齐(signer/ waf.py parser.py db/ tasks/),抽 `signer/base.py` 契约,改 `middlewares.from_crawler` 走 `load_object(SIGNING_STRATEGY)`;**行为必须不变**,按 §10 回归契约逐 gate 验。
3. **不归本 skill** — 用户要的是 sign 算法逆向 / 入口定位 → `camoufox-js-reverse` / `iv8-web-reverse`;完整协议恢复 / crawler 交付 → `web-protocol-recovery`;补环境 → `env-patch`;AST 解混淆 → `ast-deobfuscate`。本 skill 不接管签名算法本身,只消费已逆向出的签名器做工程装配。

### ⚑ Cookie 依赖判别(动手前先决断)

| 站点分类 | 关键判别 | loader 行为 |
|---|---|---|
| **公共 InnerTube / 公掌 API**(YouTube `/youtubei/v1/browse`,京东 h5st 公开 path,TikTok 公开 web) | 首页 GET 拿到的 server-issued `visitor_data` / `ttwid` 已够用,不存在 user-session 必要 | `cookie_loader` 返回 `{}`;`_do_email / reveal_business_email` 第二阶段 lazy gated,默认 `*=0` 不触发 |
| **强账号绑定 reveal**(YouTube business-email reveal 要 SAPISID cookie,Amazon 公都登录 metadata1) | reveal step 是独立 step(可关),bulk 抓 profile/videos 不依赖账号 | reveal gate 单独 env `*=0/1`,主 spider 不卡 cookie;lazy-import patchright / yolo scraper |
| **登录态强全必须**(淘宝 wap-cart 类) | 业务接口必须带 SAPISID/SAPISIDHASH,跑出空 baggage soft-deny | `cookie_loader` 强制加载并校验,无 cookie 直接 fail-drain 不跑 batch |

判别错位类型 A(站本身 cookieless 装了 full cookie 路径) wastes 一个 chrome@9222;类型 B(cookieless 假设被踩到强 cookie 站)会让你 200+[] 一通空转,误判为 iv8 sign 错位。

## 核心契约(全工程一致,改它必须同步所有站)

```python
# signer/base.py
from typing import Any, Optional, Protocol, runtime_checkable

class SignedReq(dict): ...

@runtime_checkable
class SigningStrategy(Protocol):           # 注意:只放方法,非方法类属性会被 isinstance 强制要求
    def warm(self, cookies: Optional[dict] = None, profile: Optional[dict] = None) -> Any: ...
    def sign(self, *, cursor: int = 0, count: int = 16, **kw: Any) -> "SignedReq": ...
    def close(self) -> None: ...

# fetcher.py
class FetcherStrategy(Protocol):
    def get(self, session, signed_url) -> Any: ...
```

```python
# settings.py(换站只改这里)
SIGNING_STRATEGY = "tiktok_rev.signer.strategy.MarkVIIIPipeline"   # → load_object 实例化
QUEUE_PREFIX      = "tiktok_rev"

# middlewares.py(样板,只认契约,不 import 具体实现)
from scrapy.utils.misc import load_object
@classmethod
def from_crawler(cls, crawler):
    mw._signing_class = load_object(crawler.settings.get("SIGNING_STRATEGY", "...MarkVIIIPipeline"))
    reactor.suggestThreadPoolSize(crawler.settings.getint("CONCURRENT_REQUESTS", 2))   # 原生并发
    crawler.signals.connect(mw._on_spider_closed, signals.spider_closed)
    return mw
```

## TaskState 自愈回收(卡死 running 必须自动回 pending —— 状态机闭环)

每个 TaskState 模块(`tasks/task_state.py` / `tasks/search_task_state.py` / …)MUST 提供一组 `reclaim_stale_running_*` 自愈函数:把 `status='running' AND updated_at < NOW()-STALE_SEC` 的行翻回 `pending`、清 `assigned_worker`、**保留 `cursor_resume / page_resume / next_cursor / search_id`**(断点指针);`dispatcher.poll_pending_and_dispatch()` 每拍**开头**先调自愈、再跑 `*_list_pending*` —— 让刚翻回的 pending 在同 tick 内被重新投喂。

踩过的坑、阈值约束、回归 gate 都在权威标准 §11(TaskState 自愈回收)。机制缺这一拍就闭不上:进程硬崩 → running 孤儿 → dispatcher 永远不喂 → 断点续跑在 crash 场景直接失效。

**`spider_closed` 钩主动 finalize 还在 running 的 row**(实测坑:youtube_rev task clean-close 后仍有 6 行 channel_task stuck on `running`,因 BLPOP 拉过来但 parse 没走完就 close_spider_timeout 砍了):

- `spider_closed` 钩里 dump 一遍 `SELECT * WHERE status='running' AND assigned_worker=<self>` 的 row,对每条:**未走完分页就翻 `partial`(保留所有 resume 列)+ 释 SETNX 锁**,**彻底无意义的 demo seed 就翻 `failed`** + 写 `last_error='spider_closed_early'`。
- 不要等自愈 threshold(`STALE_RUNNING_SEC` 默认 15min)兜底,因为与 dispatcher 共用时,新派遣 spider 不会容忍同 row 时间差 30min(运维 dashboard 会看到长期亮红),也会拖断点续跑判定。
- 标准样板可对齐 youtube_rev 的 `_on_spider_closed` + tiktok_rev 的 worker pool `stopped_on_spider_closed` 双重 hook:先 finalize 本 worker 持有的 running 行 → 再 关 thread pool → 再关 strategy.close()。

## 不可动红线(改动前必查)

1. JSVMP 反爬核心(`signer/strategy.py` 嵌入 JS / vendor 加载顺序 / `byted_acrawler.init`):**只改路径不改字节**。
2. `__file__` 相对 vendor 路径**深度中性**:`parent.parent/<vendor>` 必须仍指向同一 vendor(同深度搬迁安全;跨深度必须改路径)。改结构前先过 §10 vendor-path 断言。
3. iv8 ctx 线绑:整进程 1 个共享策略实例 + 1 条 `ThreadPool(1,1)`(`_IV8_POOL`)摸 ctx;HTTP 走 reactor 主池;`spider_closed` 序贯 close。别在 reactor 池/新线程建 ctx(`threading.local` 是泄露源)。
4. TaskState 自愈合约束:回收阈值 `<NS>_STALE_RUNNING_SEC` 必须 > SETNX `LOCK_TTL`;只回收喂源表(被 dispatcher LPUSH 的表,如 user_task/tag_task),不回收分页指纹表(spider `_task_claim` 携 running 的 per-row 状态表),否则同名 username 被双路 LPUSH 重复抓(详见 §11.3);resume 列(`cursor_resume/page_resume/next_cursor/search_id`)必须保留,否则断点续跑失效。
5. **resume 列类型必须与目标站 cursor 数据类型对齐**(实测坑 youtube_rev:cursor_resume 声明 `BigInteger`,YT continuation token 是 `CBoQ…` 那 JWT 风格的长字符串 → SQLAlchemy 静默 debug-log 回滚 → rewrite 全部 NULL → spider 重启续页从 page 0 重抓,dashboard 是 ok 但死做 ~50% redundant scrape)。规则:opaque / signed-string continuation token(YouTube / 京东 h5st appid pair / 抖音 `web_search_code 内嵌的 traceId`)→ `String(1024)`;纯数字 cursor(TikTok cursor=0/12/24 / 自增 offset)→ `BigInteger`。新起表时直接审"目标站 list 接口最后一页的 continuation 字段长什么样",不要拍脑袋选 BigInteger。
6. **`SigningStrategy` 实现必须撑 `*_REQUEST_BUDGET` 与 `*_PROXY` env 钩**(实测坑 youtube_rev:`YoutubeClient.request_budget=200` 硬编码 + spider 进程共享 → 50 channel ≥ 200 HTTP 第一次 batch 就爆 → 5 row `failed: request budget exhausted`,跑大 batch 必爆)。Push 站点的 strategy / fetcher 构造:middlewares 同样从 env 读 `*_REQUEST_BUDGET`(默认 200 兼旧行为,生产建议设 ≥ 50000)和 `*_PROXY`(空 = 不走代理;非空 = 同 curl_cffi ` Session.proxies = {"http": ..., "https": ...}`),并把 `proxy` 灌进 `YoutubeClient.session.proxies`(or 等价 transport layer)。**没有 proxy env 钩**的纯 cookieless 公共 API 站,实际持续 5-10 min 也是会触发 server-edge `Could not resolve host` 限流,生产 IP 池轮换装不进来就是天花板打不上去。

## 失败/限流护栏红线(运行态会复发,工程类 —— 动手后必查)

瑞数 / Akamai / Slardar 类 edge 反爬下,工程层护栏缺一拍要么把本机 IP 轰进边缘冷却、要么把整 run 跑成空转、要么诊断把运营带偏。每条都对应实踩过的坑(均来自 cnipa_patent 双层 spider 压测):

1. **long-run worker 必须落盘 stdout,禁 `| head -N`**:`python -m worker | head -50` 里 head 读满即退、闭管,worker 下次写 stdout 收 SIGPIPE 被 kill,上层却以为还在跑(整 run 白做 + 无日志可查)。长跑一律 `| tee xxx.log`(或重定向文件)。
2. **退避必须非阻塞:`reactor.callLater → engine.crawl`,禁 callback 内 `time.sleep`**:AsyncioSelector 下 `parse_*` 跑在 reactor 线程,`time.sleep` 堵 event loop,其他 in-flight 全卡死。挑战(202/412/521)重试一律 `reactor.callLater(delay, lambda: engine.crawl(req, spider))` + errback,延迟期间释放 worker 线程、其他请求照常并发;公式对齐 tiktok_rev `collector/waf.py` 的 `min(base*2**n, cap)`,`spiders/_backoff.py` 是可复用样板。
3. **dispatcher dedupe guard TTL ≥ claim 窗 + 退避封顶**:guard TTL < claim 等待时间 → pending 行止血期内被每拍重复 LPUSH(实测 redis queue 546 vs DB pending 88,× in-flight 重试 ≈ 18× 拒绝/pub,88 pub 把本机 IP 轰进瑞数边缘冷却)。`*_DISPATCH_GUARD_TTL` 默认应 ≥ `*_LOCK_TTL`。**queue 长度 ≫ DB pending 数 = 过推警报**,看见就先治 guard TTL。
4. **全站边缘封探针 + 整 dispatcher 挂起,不只 per-item 412**:challenge 状态机只识 202/412/521(软拒);但 IP 被 server-edge 封时**首页直接 400 / 连接超时**(带不带 cookie 都一样)。spider 若只按每条 per-item 退避重试,永远不知道「首页都打不开了」,会一直空转过 budget。必须周期 homepage liveness 探针,连续 N 次硬拒 → 整 dispatcher 挂起 + 长冷却,别让 per-item 退避蒙住全站失效。
5. **计数完整性:mark/progress 推进态必须同步涨行计**:offset 并行 `mark_page_done` 只推进 cursor 不带 `fetched_delta` → 跑了 200 条 `cnipa_patent.fetched` 显示 0,dashboard 直接骗运维。任何 done/progress 路径都要 raise 行计(顺序/offset 两路都要)。
6. **iv8 stage1 并发冷启动 = 串行瓶颈**(续「不可动红线#3」 iv8 ctx 线绑):stage1 warm 是 per-thread-local session 首次冷启,8 并发 = 8 次冷启在 iv8 ctx 锁上排队 → 并发度塌到 ~1。取舍两条:① warm **一个共享 session** + GET 串行(高成功低并发);② 预建 **session pool** 到并发数,冷启摊在启动期。别让首跑去发现 cold-start 串行化。
7. **压测别用你逆向的同一个 IP**:reverse 期间已把 IP 用热,再同 IP 放并发压测会先把自己打废;边缘 gate 请求率 ≈ pending_pushes/s × (1+in_flight_retryN),持续 >N/s 必边缘 trip。压测前先清队列/锁、低并发 warm 确认 throughput 基线,否则误诊成因(本次把「边缘冷却」误归因成「并发烧 long-T」,白跑一轮验证才证伪)。
8. **内置吞吐仪表**:每 spider 周期 log `success / 412 / paused / req-per-sec`,别靠手搓 sqlite 时间戳双窗口采样算 throughput(长 run 不可观测 = 调优瞎子)。

## 交付物与回归契约(重构/搬迁必过)

动手后按 `Scrapy-逆向工程架构标准.md` §10 七道 gate 验:**compileall(语法)→ 容器 pytest(不低于基线通过数 + 无新增 fail)→ 契约单测(`test_signing_strategy_is_settings_injected`)→ vendor 路径断言(missing==[])→ `_ensure_ctx` JSVMP warm(无网络)无异常 → TaskState 自愈(stale/fresh 双探针:刚插入的 stale-running 行被翻 pending 且 resume 列保留、fresh-running 行不被误收) → crawlab 真实 E2E(crawlab runner 注入 TK_PROXY/DB,交互 shell 替不了)**。

只有前 5 道 gate 能在交互式环境跑;真实 E2E 交交付 crawlab task。回归未过绝不算交付完成。

## 样板 vs 站点 slot(漂移面控制)

- 标准样板(~10 文件,可漂,但接口契约 `signer/base.py` 不漂):`signer/base.py` `signer/runner.py` `fetcher.py` `tasks/*` `db/__init__.py`(工厂)`middlewares.py`(双池)`pipelines.py`(PrintItemPipeline)`config.py`
- 站点专属(每站重写):`signer/strategy.py` `signer/js/` `signer/vendor/` `waf.py` `parser.py` `query*.py` `db/models.py` `items.py` `spiders/*.py` `settings.py` 3 行

## Crawlab fork 实战附录

爬爬 fork(crawlab)与上游 crawlab 不同,task dispatch / log retrieval 失常有坑,卡点不在 skill 触发范围但却是 §10 第 7 道 gate(crawlab 真实 E2E)必踩。**忠实于已实测四个事实**:

1. **POST `/api/spiders/{id}/run` + body `{cmd: "bash -c '...' "}` 才能真正起 task**;`POST /api/tasks` 一律返回 `data:_id` 但 **MongoDB tasks 集合根本不 persist**,task 在 admin UI 也看不到(`db.tasks.countDocuments({_id: "<str>"})=0` 同 `_id: ObjectId("<id>")=1`)。早期 LLM / 用上游 crawlab API 文档的人必踩。
2. **`POST /api/spiders/{id}/files/save`** 是重传 .py 的真路径(`path: "/youtube_rev/db/__init__.py"`、`data: <text>`,gridfs crawl 模式 fork 把 .py 落到 `/fs/<spider_id>/…` 起下次任务时拉去 worker 的 `crawlab_workspace/<spider_id>/<task_id>/` 一份**文件快照**)。改完代码必须重传到每条相关 spider 的 spider_id(双 spider 各传一份)。
3. **`/api/tasks/{id}/logs` 返 `{"status":"ok","message":"success","total":N,"data":null}`**:total 有数但 data 永远 null(fork 缓存到 seaweedfs/seaweedfs 但 query path 缺)。**排错走 DB col + ps -ef 在 worker**:看 `channel_task.status / last_error / assigned_worker` 配 `pgrep -af "scrapy"` + `ss -tn | grep youtube`(`CLOSE-WAIT` 状态 = curl_cffi stuck on cooldown socket)。
4. **`mode: random`** 在 crawl-fork 里要带 `node_ids: [...available_node_id]` 才不早挂 `status=''` 等 mongo 完整 persist;不带 node_ids 的纯 random 命令可能跟到 master node(qemu-x86 single)直接 `mode=""` 死循环,task 永远 status="(空字串)"。

四条已编进 youtube_rev task 的 selectors:持续 grab `youtube_channel` spider_id `6b0010973cbd85688634cc74` 实测中 task `6b001f3` / `6b00274` / `6b002b46` 等;破裂状态时 docker exec `kill -9 /proc/<pid>` 把 worker 内 stuck pid 收,distinguished 由 channel_task.status 自动止损下一拍 crawler tick(配合 §11 STALE_RUNNING_SEC 900s 自愈补回 pending)。

## 参考实现

- 本仓 tiktok_rev(强 cookieled iv8 标准样板):`tiktok_rev/signer/{base,strategy,search_strategy,_sign_worker}.py`、`tiktok_rev/middlewares.py`、`tiktok_rev/tasks/`、`tiktok_rev/db/`、`tiktok_rev/settings.py`(`SIGNING_STRATEGY`)。新建站点照它抄"标准样板"文件,只填站点 slot。
- 本仓 youtube_rev(cookieless 分支的最小两 spider 标准样板):无 iv8 / 无 waf.py / 无 `byted_acrawler.init`,与 tiktok_rev 的强 cookieled iv8 分支成对照;新增 `YOUTUBE_REQUEST_BUDGET` 与 `YOUTUBE_PROXY` env 钩实现 (`signer/strategy.py` `YouTubeInnerTubeStrategy.__init__`)对应本 skill 不可动红线 #6。
- End-to-end 案例 playbooks(`.codex/skills/web-protocol-recovery/references/`):`youtube-inner-tube-public-endpoint-playbook.md`(cookieless 公共 InnerTube adaptive path 完整 case)、`tiktok-mark-viii-collector-playbook.md`(SlardarWAF PoW → iv8 mark VIII JSVMP signing → Scrapy-Redis 2-spider + 自愈集成全链案例)。
