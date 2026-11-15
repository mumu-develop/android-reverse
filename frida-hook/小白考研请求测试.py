import base64
import time

import requests
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import serialization

def rsa_encode(text: str) -> str:
    # 硬编码的公钥 Base64 字符串（与 Java 中一致）
    public_key_b64 = (
        "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAzNeplg5ePk1LrFBCvt7z\n"
        "Tn1aNrXkKACNM/femFrR9FQ7sNktkqFacUiX7DbG2Vyp0bvkN7bDzHXyXnxYVA2m\n"
        "W/zaOvhRxRVElznm9KOO+/fYzRDsa0CxAj7hpxzkVo8Vb/XgcxkcxwDUM/JYEaJB\n"
        "BJ2VLl5+oP5w+3b7XJjSNCBAgpR2WItXlR32Xe2a1s6PgogFtoP0up3bDTZhinxO\n"
        "gSMVgpHwmj9EKaLjqCZGdP6I5Fqv59ogxPIYeKNb+BCkSXykHtip0TziNSIr7bQS\n"
        "A7QacFTYByCqLHthCr1ACNJSazVreDOBDyAS/PceOwGN6iiyx8U2mVPC8io1aVr1\n"
        "xwIDAQAB"
    )

    # 1. Base64 解码得到 DER 字节
    der_bytes = base64.b64decode(public_key_b64)

    # 2. 加载公钥
    public_key = serialization.load_der_public_key(der_bytes)

    # 3. 明文转 UTF-8 字节
    plaintext = text.encode("utf-8")

    # 4. 使用 PKCS1v15 填充加密（对应 Java 的 RSA/ECB/PKCS1Padding）
    ciphertext = public_key.encrypt(
        plaintext,
        padding.PKCS1v15()
    )

    # 5. Base64 编码，模拟 Android Base64.DEFAULT（每 76 字符换行，末尾换行）
    b64_bytes = base64.encodebytes(ciphertext)
    return b64_bytes.decode("utf-8")

time_stamp = round(time.time() * 1000)
text = f'{{"_t":"{time_stamp}","pn":"1"}}'
rsa_data = rsa_encode(text)
headers = {
    "Authorization": "",
    "platform": "Android",
    "model": "25102RKBEC",
    "brand": "REDMI",
    "system": "PQ3A.190605.07291804",
    "appVersion": "6.6.7",
    "Content-Type": "application/json; charset=utf-8",
    "Host": "api.app.xiaobaitech.cn",
    "User-Agent": "okhttp/5.0.0-alpha.6"
}
url = 'https://api.app.xiaobaitech.cn/api/schInfo/findAllByTime'
data = f'{{"data":"{rsa_data}"}}'.encode('utf-8', 'surrogateescape')
response = requests.post(url, headers=headers, data=data)

print(response.text)
print(response)