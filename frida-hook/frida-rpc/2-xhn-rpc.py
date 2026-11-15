import time

import requests

import frida

def on_message(message, data):
    print("[MSG]", message)

device = frida.get_usb_device()

# spawn 主动启动 App，主进程一定存在
pid = device.spawn(["com.zc.hubei_news"])
session = device.attach(pid)
with open("./2-xhn-rpc.js", encoding="utf-8") as f:
    jsCode = f.read()

# print("加载代码", jsCode)
script = session.create_script(jsCode)
script.on("message", on_message)
script.load()

# 脚本加载完再恢复进程
device.resume(pid)
time.sleep(3)

_ts = str(round(time.time()*1000))
hbrb_app_amc_md5 = script.exports_sync.md5method("hbrb-app-amc$"+_ts)
print("hbrb_app_amc_md5",hbrb_app_amc_md5)
token = script.exports_sync.md5method("d37867cf3b31460eba14173f0572a783"+"$" + hbrb_app_amc_md5 + "$" + _ts)
print("token",token)

reqsign = script.exports_sync.reqsignmethod()
print("reqsign",reqsign)

reqdeviceid = script.exports_sync.reqdeviceidmethod()
print("reqdeviceid",reqdeviceid)


headers = {
    "requestTime": _ts,
    "deviceId": "d37867cf3b31460eba14173f0572a783",
    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; 25102RKBEC Build/PQ3A.190605.07291804)",
    "token": token,
    "reqdeviceid": reqdeviceid,
    "reqsign": reqsign,
    "If-Modified-Since": "Sat, 10 Oct 2026 14:57:06 GMT",
    "Host": "hbrbapi.hubeidaily.net",
    "Content-Type": "application/x-www-form-urlencoded"
}
cookies = {
    "$Version": "\"1\"",
    "acw_tc": "\"0881142f17916434822333634e5257e2d2b4e819da8735687612a2d24f72a1\"",
    "$Path": "\"/\"",
    "$Domain": "\"hbrbapi.hubeidaily.net\""
}
url = 'https://hbrbapi.hubeidaily.net/amc/client/listContentByColumn'
params = {
    "column": "22",
    "publishFlag": "1",
    "focusNo": "5",
    "pageNo": "0",
    "pageSize": "20"
}
data = ''.encode('utf-8', 'surrogateescape')
response = requests.post(url, headers=headers, cookies=cookies, params=params, data=data)

print(response.text)
print(response)