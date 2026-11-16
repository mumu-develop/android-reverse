"""从签名证书推算 appSign（不需要跑 app）

用法：
    # 1. 从 APK 里取出 v1 签名块
    adb shell "unzip -p <apk> META-INF/XXX.RSA > /sdcard/cert.rsa"
    adb pull /sdcard/cert.rsa .

    # 2. 转成 PEM
    keytool -printcert -rfc -file cert.rsa > cert.pem

    # 3. 算 appSign
    python get_appsign.py cert.pem

原理（libwtf.so 里 getAppSign 的等价实现）：
    appSign = UPPER( MD5( hex(证书DER) ) )
    其中 hex 就是 Java Signature.toCharsString() 的返回值（小写，无分隔）
"""
import base64, hashlib, re, sys


def appsign_from_pem(pem_text: str) -> str:
    b64 = "".join(re.findall(
        r"-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----", pem_text, re.S))
    if not b64:
        raise ValueError("PEM 里没找到 CERTIFICATE 块")
    der = base64.b64decode(re.sub(r"\s+", "", b64))
    return hashlib.md5(der.hex().encode()).hexdigest().upper(), len(der)


if __name__ == "__main__":
    pem = open(sys.argv[1], encoding="utf-8", errors="ignore").read()
    sign, n = appsign_from_pem(pem)
    print(f"证书 DER  : {n} 字节")
    print(f"appSign   : {sign}")
