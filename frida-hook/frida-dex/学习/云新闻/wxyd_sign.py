"""云新闻 (com.yndaily.wxyd) sign 生成 — 实测验证版

公式（libwtf.so 的 Java_..._getSign 反编译 + 运行时 3/3 比对通过）：

    appSign = UPPER(MD5( hex(证书DER) ))          # LogShutDown.getAppSign()
    inner   = UPPER(MD5( appSign ))                # libwtf 内部
    sign    = UPPER(MD5( inner + account + token + timestamp ))

参数来源：SafeWebView.Y(JSMethod.SignParams)
    account   = 登录用户 id，未登录时为 ""
    token     = 登录 token，未登录时为 ""
    timestamp = 秒级时间戳字符串
"""
import hashlib

# getAppSign() 实测返回值，等价于 UPPER(MD5(证书DER的hex))
APP_SIGN = "71418DA91E43A6F8C811F57A35CD744B"


def md5_upper(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest().upper()


def app_sign_from_cert(cert_der_hex: str) -> str:
    """等价于 LogShutDown.getAppSign()：证书 DER 的 hex 再 MD5 大写"""
    return md5_upper(cert_der_hex.lower())


def make_sign(account: str, token: str, timestamp: str,
              app_sign: str = APP_SIGN) -> str:
    inner = md5_upper(app_sign)
    return md5_upper(inner + account + token + timestamp)


# ---- 实测向量自测（值来自 libwtf.so 的真实调用）----
VECTORS = [
    ("", "", "1700000000", "1C9A7CC2C228A8E3F2DF42E3DD284817"),
    ("alice", "tok123", "1700000001", "5E473A3701640C173A7FAB0D62F0259D"),
    ("123456", "", "1700000002", "F4DEF62E07B75C36A85D8B49EA0AC6DE"),
]

if __name__ == "__main__":
    print("appSign :", APP_SIGN)
    print("inner   :", md5_upper(APP_SIGN))
    ok = 0
    for acc, tok, ts, want in VECTORS:
        got = make_sign(acc, tok, ts)
        flag = "OK" if got == want else "FAIL"
        ok += got == want
        print(f"[{flag}] acc={acc!r:<10} tok={tok!r:<10} ts={ts} -> {got}")
    print(f"\n{ok}/{len(VECTORS)} 通过")
