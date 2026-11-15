import hashlib
import time


def MD5(s: str) -> str:
    digest = hashlib.md5(s.encode('utf-8')).digest()
    hex_str = ''.join(f'{b:02x}' for b in digest)
    print(f"MD5({s}) = {hex_str}")
    return hex_str


hbrb_app_amc_md5 = "hbrb-app-amc$" + str(round(time.time()*1000))
android_id = "d37867cf3b31460eba14173f0572a783"
time_stamp = round(time.time() * 1000)
token = MD5(android_id + "$" + hbrb_app_amc_md5 + "$" + str(time_stamp))


import requests


headers = {
    "requestTime": str(time_stamp),
    "deviceId": android_id,
    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; 25102RKBEC Build/PQ3A.190605.07291804)",
    "token": token,
    "reqdeviceid": "2a6c2563f9784944b33151b510f33749",
    "reqsign": "NFKk2Rzz8w8GJT7eEGjC2BkkSJeNxjSRuBSmQhJ79ltZBU6QpVgBn/b6LBGeogKgA5NIDKd00BwcgYrkOFmf455H7j7VYUQzJ4atuKGPDNZA+Rbj+McF/Kbpi6vCNujW4WgrF/iHjlotoEVR5D3OZsiSPctKg6PiDFTluP/XXuPYcKtc5FXI4A5b3Kp3XwRWlVYI0oa/8R+ebJ2ZqVywAz25lbmzMrewbRPjfbehTITZwu3nO7Q4HE5qopa0VpAW8s4RaD3tTWS3RB2rg2UV+DH9OjYzbftBwSmG2EHPA2aiW15MEqVSuzTfRX9HPT0S8pRY63a6mT0KlqPQNZWdag==",
    "Host": "hbrbapi.hubeidaily.net",
    "Content-Type": "application/x-www-form-urlencoded"
}
cookies = {
    "$Version": "\"1\"",
    "acw_tc": "\"0881142f17900011325423239ece75eb3081814857045120e272bdf65f59fd\"",
    "$Path": "\"/\"",
    "$Domain": "\"hbrbapi.hubeidaily.net\""
}
url = 'https://hbrbapi.hubeidaily.net/amc/client/listContentByColumn'
params = {
    "column": "1476",
    "publishFlag": "1",
    "focusNo": "5",
    "cqDate": "1790001749618",
    "versionCode": "931",
    "pageNo": "0",
    "pageSize": "20"
}
data = ''.encode('utf-8', 'surrogateescape')
response = requests.post(url, headers=headers, cookies=cookies, params=params, data=data)

print(response.text)
print(response)