# 海南航空 (com.rytong.hnair 10.14.1) 接口参数还原与取数

接口：`POST https://app.hnair.com/ticket/lfs/airLowerPriceShop`（另有 `/lfs/airLowFareSearch` 等）

**状态：已打通。纯 Python 计算签名 + `curl_cffi` 发请求即可取数，不依赖 App、设备或风控 SDK。**

| 参数 | 位置 | 算法 | 状态 |
|---|---|---|---|
| `hnairSign` | query | HMAC-SHA1（纯算） | 三份抓包逐字节复现 |
| `sens` | body.common | AES-256-CBC（纯算） | 解密 + 重加密一致 |
| `AppStamp` | header | RSA/ECB/PKCS1（纯算） | 公式已还原 |
| `riskToken` / `blackBox` | body.common | 顶象风控 SDK 产出 | **实测非必需** |
| `ekingcode` | header | 顶象服务端下发 | **实测非必需** |
| 其余 common 字段 | body | 明文 / 本机值 | 可直接自定义 |

---

## 1. hnairSign（HMAC-SHA1）

```
mid  = 值拼接(headers) + 值拼接(query) + 值拼接(body 扁平合并) + appSign
sign = HMAC-SHA1(key = SALT, msg = mid).hexdigest().upper()
```

`值拼接(json)`（对应 so 中 `HNASignature::parseParamJSON`）：

1. 只解析 JSON 对象
2. 只取**标量**成员（字符串 / 整数 / 浮点 / 布尔），对象和数组整段跳过
3. 按键名排序后，只把**值**依次拼接（键名不参与）

常量：

| 名称 | 值 | 出处 |
|---|---|---|
| SALT（HMAC key） | `21047C596EAD45209346AE29F0350491` | `ApiConfig.SALT` |
| AppUtil.a() | `F6B15ABD66F91951036C955CB25B069F` | `MD5(证书DER)`，拼在 msg 末尾 |

**关键**：签名对象是 `data` 平铺进 `common` 后的扁平 JSON，不是发出去的嵌套 body。

三份抓包验证全部命中：

```
12CF4546C195451144287347DF1FA536E20DEE3C   ✓
46F977FD4CDE2C68242994E92B986CF01AAFEE3B   ✓
8E076E7644002BC7839C3911DFEE33670CD4CBEA   ✓
```

IDA 证据（`libsignature.so` 0x63ae0）：

```c
tmp  = parseParamJSON(headers) + parseParamJSON(query) + parseParamJSON(body);
data = tmp + appSignature;
hmacSha(this, data, salt);
result = sign + ">>" + tmp + ">>" + appSignature;   // >> 后面只是调试展示
```

## 2. sens（AES-256-CBC）

```
iv    = (stime + akey)[0:16]
key   = "YNp0Kj71J2ZgWVnR4rMTUhBZcUQq3y0b"[0:32]
plain = stime + "," + reqFlag + "," + respFlag      // 常见 "1793667784125,0,0"
sens  = "%hna%" + Base64(AES/CBC/PKCS5Padding(plain, key, iv))
```

细节：IV 前 13 字节是 stime，明文前 13 字节也是 stime，CBC 首块里两者**相互抵消**，
所以 `(0,0)` 时 sens 密文与时间无关——多份抓包的 sens 完全一样，是数学性质不是缓存。

## 3. AppStamp（RSA）

```
raw      = MD5("AD_" + hnairSign + "_" + versionName).lower()
AppStamp = Base64(RSA/ECB/PKCS1Padding(raw, 1024 位公钥))
```

---

## 4. 客户端指纹（踩得最深的坑）

同样的字节、同样的签名，换客户端结果完全不同：

| 客户端 | 结果 | 备注 |
|---|---|---|
| Python `urllib` / `requests` | `E00001 验签失败` | TLS 指纹被拦 |
| `curl.exe`（子进程） | 正常返回数据 | 每次起进程，慢（2.9s/条） |
| **`curl_cffi`** | **正常返回数据** | 进程内、连接复用，0.4~0.6s/条，**首选** |

`curl_cffi` 实测各档指纹均可通过：`chrome` / `chrome120` / `safari` / `firefox` / `edge101` / 不指定。
说明服务端拦的不是某个特定浏览器指纹，而是"像不像正常的 TLS 客户端"。

`hnair_search.py` 默认用 `curl_cffi`，未安装时自动降级到 curl 子进程。

## 5. 并发与 QPS 实测

每档 16 次请求，日期在销售期内：

| 并发 | QPS | p50 延迟 |
|---|---|---|
| 1 | 0.33 | 2.6 s |
| 4 | 0.76 | 4.4 s |
| **8** | **1.36** | 5.1 s |
| 12 | 1.03 | 9.6 s |
| 16 | 1.07 | 12.4 s |

**结论**：

1. **没有风控/限流**：累计 150+ 次请求，0 个 `E00001`、0 个 429
2. **吞吐上限 ≈ 1.3~1.4 QPS**，最优并发 8；再高只是排队（16 并发 p50 12s+）
3. 反推服务端并行度：`QPS × 单条耗时 ≈ 3.5`，即只有 **3~4 路并行**
4. 瓶颈与设备无关（见下）

### 设备/机型对照实验

16 并发，各 16 次：

| 变量 | QPS | p50 |
|---|---|---|
| 固定 did（抓包设备） | 0.87 | 16.0 s |
| 每次随机 did | 1.04 | 14.1 s |
| 随机 did + 随机机型 | 1.04 | 13.9 s |

随机 did/机型只带来 0.17 QPS 提升（在波动范围内），**说明不是按设备维度限流**。
瓶颈在服务端：单条 2.6s + 约 3 路并行槽位。

剩下「按 IP 限」还是「后端全局容量」未区分：需要换出口 IP 复测（手机热点跑一次同样脚本，
QPS 明显上升则为按 IP 限流，否则为后端全局瓶颈）。

---

## 文件

| 文件 | 用途 |
|---|---|
| `hnair_params.py` | 纯算 `hnairSign` / `sens` / `AppStamp`，自带 `verify` 自检 |
| `hnair_search.py` | 真实取数（curl_cffi 发请求 + 解析航班列表） |
| `hnair_stress.py` | 并发压测（多日期 × 多档并发） |

## 用法

```bash
python hnair_params.py verify                  # 自检：三参数对照抓包
python hnair_search.py                         # 默认 PEK->SHA 后天
python hnair_search.py PEK SHA 2026-11-20      # 指定航线日期
python hnair_stress.py                         # 并发压测
```

实测输出：

```
URL: https://app.hnair.com/ticket/lfs/airLowerPriceShop?hnairSign=15D9E65CAC1DADF6DA16244924004524F4BDA131
耗时: 2.37s
success = True | errorCode = ''
  7601  2026-11-20 07:25->09:35  最低价 665 元   (空客330)
  7603  2026-11-20 08:25->10:35  最低价 199 元   (波音787)
  7605  2026-11-20 15:55->18:00  最低价 1226 元  (波音787)
```
