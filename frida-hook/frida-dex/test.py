import requests


headers = {
    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; 25102RKBEC Build/PQ3A.190605.07291804)",
    "Host": "statics.zhuishushenqi.com"
}
cookies = {
    "_clck": "1bpmbsk%5E2%5Ega7%5E0%5E2475",
    "_clsk": "1975b7o%5E1791731820098%5E1%5E1%5Ek.clarity.ms%2Fcollect"
}
url = 'http://statics.zhuishushenqi.com/avatar/98/f2/98f22b2bc5882d024efc4c1e9006a50c'
response = requests.get(url, headers=headers, cookies=cookies)

print(response.text)
print(response)