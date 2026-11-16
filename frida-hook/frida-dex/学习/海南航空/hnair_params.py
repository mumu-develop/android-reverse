# -*- coding: utf-8 -*-
"""
海南航空 10.14.1 接口参数还原（纯 Python，无需 so / unidbg）

    hnairSign : HMAC-SHA1
    sens      : AES-256-CBC
    AppStamp  : RSA(PKCS#1)

用法：
    python hnair_params.py verify        # 三个参数全部对照抓包自检
    python hnair_params.py sign          # 生成 hnairSign
    python hnair_params.py sens          # 生成 sens
    python hnair_params.py stamp <sign>  # 生成 AppStamp
"""
import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile

# ---------- 常量 ----------
SALT = "21047C596EAD45209346AE29F0350491"          # ApiConfig.SALT，同时是 HMAC 的 key
APP_SIGN = "F6B15ABD66F91951036C955CB25B069F"      # AppUtil.a() = MD5(证书DER)，拼在待签名串末尾
AES_PASSPHRASE = "YNp0Kj71J2ZgWVnR4rMTUhBZcUQq3y0b"  # HnaAppProxy.onCreate -> ApiEncryption.init
VERSION_NAME = "10.14.1"                            # 参与 AppStamp

RSA_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCziHP+DnK5og1PAxmgKbrN/dChW6Pq1/8TxKKnc2e2qifoMZbsYy+/I2o6HnzGm3QNxA6ernkU9DptfQ9j+mIv6nmEmMXu0qusTs8hKVzOaX9z7BgwlpvgoN6ZN++lWc2DQVhJs8fafcG0hJuQmsbaKH3mvEQBqJnE0vQHAuBe8wIDAQAB
-----END PUBLIC KEY-----"""


# ======================= hnairSign（纯算） =======================
def _flatten(obj):
    """
    对应 so 里的 HNASignature::parseParamJSON：
      只取标量成员（str/int/float/bool），对象和数组整段跳过，
      按键名排序后把「值」依次拼接（键名不参与）。
    """
    out = []
    for k in sorted(obj.keys(), key=lambda s: s.lower()):
        v = obj[k]
        if isinstance(v, bool):
            out.append("true" if v else "false")
        elif isinstance(v, (str, int, float)):
            out.append(str(v))
    return "".join(out)


def _as_obj(x):
    return json.loads(x) if isinstance(x, str) else x


def make_hnair_sign(headers, query, body, salt=SALT, app_sign=APP_SIGN, want_mid=False):
    """
    hnairSign = HMAC-SHA1(key=SALT, msg=值拼接(headers)+值拼接(query)+值拼接(body)+appSign).upper()
    headers / query / body 可以是 dict，也可以是 JSON 字符串。
    """
    mid = _flatten(_as_obj(headers)) + _flatten(_as_obj(query)) + _flatten(_as_obj(body))
    sign = hmac.new(salt.encode(), (mid + app_sign).encode(), hashlib.sha1).hexdigest().upper()
    return (sign, mid) if want_mid else sign


# ======================= sens（AES） =======================
def _run(cmd):
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("命令失败: %s\n%s" % (" ".join(cmd), r.stderr.decode("utf-8", "replace")))
    return r


def make_sens(stime, akey, req_flag=0, resp_flag=0):
    key = AES_PASSPHRASE[:32].encode()
    iv = (stime + akey)[:16].encode()
    plain = ("%s,%d,%d" % (stime, req_flag, resp_flag)).encode()

    with tempfile.TemporaryDirectory() as d:
        pin, pout = os.path.join(d, "in"), os.path.join(d, "out")
        open(pin, "wb").write(plain)
        _run(["openssl", "enc", "-aes-256-cbc", "-nosalt",
              "-K", key.hex(), "-iv", iv.hex(), "-in", pin, "-out", pout])
        return "%hna%" + base64.b64encode(open(pout, "rb").read()).decode()


# ======================= AppStamp（RSA） =======================
def make_appstamp(hnair_sign, version=VERSION_NAME):
    raw = hashlib.md5(("AD_" + hnair_sign + "_" + version).encode()).hexdigest()
    with tempfile.TemporaryDirectory() as d:
        pem, pin, pout = (os.path.join(d, x) for x in ("pub.pem", "in", "out"))
        open(pem, "w").write(RSA_PUBLIC_KEY_PEM)
        open(pin, "wb").write(raw.encode())
        _run(["openssl", "pkeyutl", "-encrypt", "-pubin", "-inkey", pem,
              "-pkeyopt", "rsa_padding_mode:pkcs1", "-in", pin, "-out", pout])
        return base64.b64encode(open(pout, "rb").read()).decode()


# ======================= 自检 =======================
BODY = ('{"akey":"184C5F04D8BE43DCBD2EE3ABC928F616","aname":"com.rytong.hnair","atarget":"standard",'
        '"aver":"10.14.1","did":"629DB67741E0AC50F870DB85725F9826","dname":"REDMI_25102RKBEC",'
        '"mchannel":"official","schannel":"AD","slang":"zh-CN",'
        '"sname":"Android/aosp_marlin/marlin:9/PQ3A.190605.07291804/3793265:user/release-keys",'
        '"stime":"1793667784125","sver":"9","system":"AD","szone":"+0800","abuild":"67038",'
        '"riskToken":"6aeb105fA4iwXhGoG9N0iTywpwKI2yKsFFjrQcg3","blackBox":"1793790043023GPHvUhvwgvHbd",'
        '"hver":"10.14.0.48458.36e7faa6b3.standard",'
        '"sens":"%hna%fmlDP4irUgmjOAVb/zArEuBRY7PWtObax/QjI4O15Ho=",'
        '"originDestinations":[{"destination":"SHA","destinationType":"1","origin":"PEK",'
        '"departureDate":"2026-11-04","originType":"1"},{"destination":"PEK","destinationType":"1",'
        '"origin":"SHA","departureDate":"2026-11-11","originType":"1"}],'
        '"passenger":"ADT:1,CNN:1,INF:1"}')


def _selftest():
    sig, mid = make_hnair_sign({"app": "APP", "channel": "AD"}, {}, BODY, want_mid=True)
    print("mid   =", mid[:80], "...")
    print("hnairSign 计算 =", sig)
    print("hnairSign 抓包 = 12CF4546C195451144287347DF1FA536E20DEE3C")
    print("  一致 =", sig == "12CF4546C195451144287347DF1FA536E20DEE3C")

    tiny = [('{"a":"A1"}', '{"q":"Q1"}', '{"b":"B1"}', 'S1', 'P1', 'D94196426C4872B682C502196F6E1D133FAA5477'),
            ('{"a":"A2"}', '{"q":"Q1"}', '{"b":"B1"}', 'S1', 'P1', '3C66CDC15331BE75867306911A6065A54F440B82'),
            ('{}', '{}', '{}', '', '', 'FBDB1D1B18AA6C08324B7D64B71FB76370690E1D')]
    for h, q, b, s, a, exp in tiny:
        print("  unidbg 小输入对照:", make_hnair_sign(h, q, b, s, a) == exp)

    sens = make_sens("1793667784125", "184C5F04D8BE43DCBD2EE3ABC928F616")
    print("sens 计算 =", sens)
    print("sens 抓包 = %hna%fmlDP4irUgmjOAVb/zArEuBRY7PWtObax/QjI4O15Ho=")
    print("  一致 =", sens == "%hna%fmlDP4irUgmjOAVb/zArEuBRY7PWtObax/QjI4O15Ho=")

    stamp = make_appstamp(sig)
    print("AppStamp 长度 =", len(stamp), "(抓包 172)")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "verify":
        _selftest()
    elif args[0] == "sign":
        print(make_hnair_sign({"app": "APP", "channel": "AD"}, {}, BODY))
    elif args[0] == "sens":
        print(make_sens(args[1] if len(args) > 1 else "1793667784125",
                        args[2] if len(args) > 2 else "184C5F04D8BE43DCBD2EE3ABC928F616"))
    elif args[0] == "stamp":
        print(make_appstamp(args[1]))
    else:
        print(__doc__)
