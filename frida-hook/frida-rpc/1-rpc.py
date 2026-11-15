import time

import frida

def message(message, data):
    if message['type'] == 'send':
        print(f"[*] {message['payload']}")
    else:
        print(message)

session = frida.get_usb_device().attach(17368)
with open("./1-rpc.js") as f:
    jsCode = f.read()

# print("加载代码", jsCode)
script = session.create_script(jsCode)
# script.on("message", message)
script.load()

# result = script.exports_sync.invokemethod01("1111")
_ts = str(round(time.time()*1000))
res = script.exports_sync.xhnmethod("C50GIK6GDhQNjtMRVRoQbwxVovXCX8DUv5androidEF6949802546884406443E9C92347F46158DA1C8"+_ts)

print(res)


def spider():
    import requests
    headers = {
        "Host": "xhnapi2.voc.com.cn",
        "os": "android",
        "user-agent": "xhn/11.0.3 (REDMI/25102RKBEC; android/28; okhttp/4.12.0)",
        "appversion": "11.0.3",
        "rmt-device-id": "EF6949802546884406443E9C92347F46158DA1C8",
        "rmt-hash": res,
        "rmt-request-time": _ts,
        "rmt-device-type": "android",
        "rmt-build": "1100302",
        "rmt-app-version": "11.0.3",
        "rmt-app-id": "9"
    }
    url = "https://xhnapi2.voc.com.cn/v5/news/getlist"
    params = {
        "list_version": "202604232048",
        "classid": "5159_xhn",
        "appid": "9",
        "page": "1"
    }
    response = requests.get(url, headers=headers, params=params)

    print(response.text)
    print(response)

spider()

# from flask import Flask, request
#
# # pip install flask
#
# app = Flask(__name__) # 初始化
#
# @app.route('/api', methods=['GET'])  # data解密
# def decrypt_class():
#     data = request.args.get('arg')
#     res = script.exports_sync.xhnmethod(data)
#     return res
#
# @app.route('/')
# def index():
#     return  "hello"
#
# if __name__ == "__main__":
#     app.run()