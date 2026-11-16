# -*- coding:utf-8 -*- 
# Author: luoge

import hashlib

def getSha(aaa):
    sha = hashlib.sha1()
    sha.update(aaa.encode())
    return sha.hexdigest()


import requests

def getsign(data):
    dataenc = "&".join([f"{i}={data[i]}" for i in sorted(data.keys())])
    salt = "a84c5883206309ad076deea939e850dc"
    sign1 = getSha(salt + dataenc)
    print(sign1)
    sign2 = getSha(salt + sign1)
    print(sign2)
    return  sign2

def spider():
    headers = {
        "Host": "mapi.appvipshop.com",
        "authorization": "OAuth api_sign=0343ad0408c25c04d0c511dab4050358edf14969",
        "x-vip-host": "mapi.appvipshop.com",
        "content-type": "application/x-www-form-urlencoded",
        "user-agent": "okhttp/3.12.13"
    }
    url = "https://mapi.appvipshop.com/vips-mobile/rest/layout/channel/data"
    data = {
        "age_group": "",
        "androidTenSlotTabSupport": "1",
        "api_key": "23e7f28019e8407b98b84cd05b5aef2c",
        "app_name": "shop_android",
        "app_version": "7.45.6",
        "changeResolution": "2",
        "channel_flag": "0_1",
        "channel_name": "母婴",
        "city_id": "104103101",
        "client": "android",
        "client_type": "android",
        "darkmode": "0",
        "deeplink_cps": "",
        "device_model": "Pixel 4",
        "device_vendor": "google",
        "did": "0.0.f81256ac564e49764335a4919db82438.dd16b7",
        "fdc_area_id": "104103101104",
        "function": "collect_msg",
        "height": "2236",
        "load_more_token": "",
        "mars_cid": "73282cb2-beb4-377e-b817-e8fe6dfb9cec",
        "menu_code": "daohangmuying",
        "mobile_channel": "8rdlo74r:::",
        "mobile_platform": "3",
        "net": "WIFI",
        "os_type": "android",
        "os_version": "10",
        "otddid": "",
        "other_cps": "",
        "oxo_area_id": "104103101",
        "oxo_city": "104103101",
        "oxo_district": "104103101104",
        "oxo_province": "104103",
        "pageSessionId": "73282cb2-beb4-377e-b817-e8fe6dfb9cec_1778159864688",
        "page_id": "page_channel_1778159864637",
        "phone_model": "Pixel 4",
        "province_id": "104103",
        "referer": "com.achievo.vipshop.homepage.activity.MainActivity",
        "rom": "Dalvik/2.1.0 (Linux; U; Android 10; Pixel 4 Build/QQ2A.200405.005)",
        "sd_tuijian": "0",
        "service_provider": "",
        "session_id": "73282cb2-beb4-377e-b817-e8fe6dfb9cec_shop_android_1778157766537",
        "sex_type": "",
        "skey": "2d30297ff20ec9b7442dc4f3c335abdc",
        "source_app": "android",
        "standby_id": "8rdlo74r:::",
        "sys_version": "29",
        "timestamp": "1778159864",
        "warehouse": "VIP_HZ",
        "width": "1080"
    }
    sign = getsign(data)
    headers['authorization'] = f"OAuth api_sign={sign}"
    response = requests.post(url, headers=headers, data=data,verify=False)
    print(response.text)

if __name__ == '__main__':
    spider()





