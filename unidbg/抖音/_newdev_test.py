import json, os, subprocess, time, urllib.parse, urllib.request
PROJ = r"D:\idea\IdeaProjects\douyin-sign-server"
JAVA = r"D:\Java\jdk-21\bin\java.exe"
UA = ("com.ss.android.ugc.aweme/400200 (Linux; U; Android 13; zh_CN_#Hans; Pixel 6; "
      "Build/TQ3A.230901.001.C2; Cronet/TTNetVersion:0a471c49 2026-10-28)")
# 从设备池取一台
recs = [json.loads(l) for l in open(r"D:\PythonProject\安卓-逆向\unidbg\抖音\devices.jsonl", encoding="utf-8") if l.strip()]
d = recs[-1]
print("用设备:", d["device_id"], d["brand"], d["model"], d.get("os_version"))
DEV, IID, CDID = d["device_id"], d["install_id"], d["cdid"]

def sign_once(url):
    cp = open(os.path.join(PROJ, "cp.txt")).read().strip()
    cmd = [JAVA, "-Dinit=true", "-Dchannel=810", "-Dsignurl=" + url, "-Dreporturl=" + url,
           "-Ddeviceid=" + DEV, "-Dinstallid=" + IID, "-Dop2=0",
           "-cp", "target\\classes;" + cp, "com.dy.sign.DouyinMetasecSign"]
    p = subprocess.run(cmd, cwd=PROJ, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=300)
    out = p.stdout or ""
    if "===HEADERS_START===" not in out: return None
    block = out.split("===HEADERS_START===")[1].split("===HEADERS_END===")[0]
    h = {}
    for line in block.strip().splitlines():
        if "=" in line:
            k, v = line.split("=", 1); h[k.strip()] = v.strip()
    return h

ts = int(time.time()*1000)
params = [("aweme_id","7688378193157898395"),("cursor","0"),("count","20"),
  ("aid","1128"),("app_name","aweme"),("version_code","400200"),("version_name","40.2.0"),
  ("manifest_version_code","400201"),("update_version_code","40209900"),
  ("device_platform","android"),("device_type",d["model"]),("device_brand",d["brand"]),
  ("os","android"),("os_api",str(d["os_api"])),("os_version",d["os_version"]),
  ("channel",d["channel"]),("device_id",DEV),("iid",IID),("cdid",CDID),
  ("resolution",d["resolution"]),("dpi",str(d["dpi"])),("host_abi","arm64-v8a"),
  ("cpu_support64","true"),("language","zh"),("ac","wifi"),
  ("_rticket",str(ts)),("ts",str(ts//1000))]
url = "https://aweme.snssdk.com/aweme/v2/comment/list/?" + urllib.parse.urlencode(params)
h = None
for i in range(10):
    h = sign_once(url)
    if h: break
    time.sleep(0.3)
if not h:
    print("签名失败"); raise SystemExit(1)
hh = {"User-Agent": UA}; hh.update(h)
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with op.open(urllib.request.Request(url, headers=hh), timeout=30) as r:
    body = r.read().decode("utf-8", "ignore")
if body.strip().startswith("<"):
    print("❌ 仍被拒:", body[:80])
else:
    j = json.loads(body.split("\n")[0])
    print("✅ 成功 status=%s 评论=%d total=%s" % (j.get("status_code"), len(j.get("comments") or []), j.get("total")))