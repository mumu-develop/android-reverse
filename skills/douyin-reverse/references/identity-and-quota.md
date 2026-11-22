# 设备身份（iid）与配额：生命周期、封禁形态、容错设计

这一份解决三个高频问题：

1. 新设备为什么拿不到作品列表？
2. iid 被封了怎么办？
3. 注册出来的设备到底怎么用？

---

## 一、三个标识，别混

| 标识 | 例子 | 谁生成 | 作用 |
|---|---|---|---|
| `device_id` | `2891094710596916` | 服务端（`device_register`） | 设备主键 |
| `iid`（install_id） | `3594782549750826` | 服务端 | **安装身份**，信任分级靠它 |
| `cdid` | `e3683b4a-3bf8-...` | 客户端 UUID | 只做设备指纹的一部分 |

实测结论：**信任只看 `iid`**，`cdid` 换成新的不影响（`iid=config + cdid=new` 照样出数据）。

---

## 二、iid 的生命周期

```
真机/模拟器装 App
   → POST/GET log.snssdk.com/service/2/device_register/
   → 服务端下发 device_id + install_id + device_token
   → 返回体里带 "new_user": 0 | 1
        new_user=0  → 老用户，作品列表可用
        new_user=1  → 新用户，作品列表静默返空（200 + 0 字节）
   → 真实使用若干天（登录、刷 feed、播放…）后可能被升级成 0（时长未知，18 小时不够）
```

脚本注册（`/api/register`）拿到的一律是 `new_user=1`。

---

## 三、三个接口对 iid 的要求

| 接口 | 真实 iid | `iid=0` | 新 iid（new_user=1） |
|---|---|---|---|
| 用户详情 | ✅ | ❌ user 空 | ✅ |
| 作品列表 | ✅ | ✅ | ❌ 空 body |
| 评论 | ✅ | ✅ | ✅ |

**记住这一条就够了：详情要真实 iid，作品列表要匿名，评论随意。**

---

## 四、被封的判定与处理

### 4.1 判定

| 现象 | 含义 |
|---|---|
| 详情 `status_code=0` 但 `user={}` | 该 iid 被限（或失效） |
| 作品列表 200 + 0 字节 | 该 iid 不被信任（新安装）**或**被封 |
| 评论 `-99999` + 空页 | 设备请求过密（限流，不是永久封） |

### 4.2 处理：iid 池 + 隔离 + 自动补给

iid 是**可再生**的：任何新注册设备的 iid 都能拉详情（实测：新 iid 拿到昵称 + 粉丝 177 万）。
所以"封了"不是终点：

```
详情请求
  ├─ 从池里挑 iid 未被标记坏的设备
  └─ 全部被标记坏 → /api/register 现造 3 台 → 用新 iid
失败结果 → Redis 标记 douyin_rev:iid:<iid>:profile_bad（TTL 6h）
         → 换设备重试同一任务（2 次）
         → 仍失败才跳过详情，继续抓作品
```

作品列表：

```
iid=0 匿名 → 失败累积 10 次触发探测 → 切真机 iid →
           全挂 → posts_degraded=True（跳过作品列表，只抓详情+评论）
```

评论：

```
-99999 → 该设备进冷却（90s 起，指数退避到 300s）→ 换设备重试同页（不推进 cursor）
```

### 4.3 端到端验证

把池里 29 个 iid 全部标记为坏，再跑 2 个任务：

```
tasks    completed / completed
profiles TOMORROW X TOGETHER（粉丝 198 万）
         爱吃火锅（粉丝 13,856）
videos   999 条
```

详情、作品列表都没断。

---

## 五、注册设备怎么用（三个容易踩的点）

### 5.1 注册写的是文件，不是内存池

`/api/register` 把设备追加到 `devices.jsonl`，**签名服务启动时才从该文件建实例**。
所以：

- 注册后**立刻可用**的是"设备身份"（拼参数、签名会 fallback 到任意实例）
- 想让它在服务里成为**独立实例**，需要重启服务（`pool-size` 决定实例数）

客户端可以直接读 `devices.jsonl` 拿设备身份，不必等重启：

```python
for line in open("devices.jsonl", encoding="utf-8"):
    d = json.loads(line)
    # device_id / install_id / cdid / brand / model / os_version / resolution / dpi / channel
```

### 5.2 `pool-size` 决定签名并发

```
签名吞吐(次/秒) ≈ pool-size ÷ (per-device-interval-ms / 1000)
```

| 配置 | 吞吐 |
|---|---|
| 6 × 1500ms | 4.2 次/秒 |
| 12 × 500ms | 21 次/秒 |

内存：每实例约 120-150MB。

### 5.3 新注册设备的画像质量

`/api/register` 从 19 个真实机型画像里随机抽，品牌/型号/系统/分辨率/ROM 自洽，
`cdid`/`openudid`/`clientudid`/`mcc_mnc`/首次启动时间都随机。
注册响应里带 `device_token`（部分接口要），但**作品列表的信任不看 token**（实测加 `X-Tt-Token` 无效）。

---

## 六、健康检查

```bash
python scripts/check_posts_health.py           # 单次，退出码 0=健康
python scripts/check_posts_health.py --loop 300
```

输出：

```
[OK ] 2026-11-22 19:13:42 iid=750826 候选=23 降级=False
```

挂到定时任务/监控，作品列表通道一挂就能立刻知道。

---

## 七、别做的事

| 做法 | 为什么不行 |
|---|---|
| 改指纹 + 重装刷新 iid | 会生成新 iid，但仍是 `new_user=1`，作品列表照样空 |
| 注册后等一等 | 实测 18 小时仍 `new_user=1` |
| 给新 iid 加 `X-Tt-Token` / `ttwid` | 实测无效 |
| 参数里加 `new_user=0` | 无效，服务端按 iid 判 |
| 把 `-99999` 当空页跳过 | 会静默丢数据（限流≠到底） |
