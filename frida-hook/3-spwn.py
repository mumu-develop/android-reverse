# -*- coding:utf-8 -*- 
# Author: luoge

import frida
import sys

def on_message(message, data):
    print("message", message)
    print("data", data)


# 通过Spawn模式启动一个新的应用程序进程，并在该进程中加载Frida脚本
device = frida.get_usb_device()
pid = device.spawn(["com.trs.xkb.newsclient"])
print(pid)
# 恢复应用程序的执行
device.resume(pid)
session = device.attach(pid)

js_cpde = '''
Java.perform(function () {
    // 获取当前应用的上下文
    var currentApplication = Java.use('android.app.ActivityThread').currentApplication();
    var context = currentApplication.getApplicationContext();
    // 获取包名
    var packageName = context.getPackageName();
    // 输出包名
    console.log("当前应用的包名是: " + packageName);
    send(packageName) // 发送消息到外部  看日志 
});
'''

script = session.create_script(js_cpde)

script.on("message", on_message)
script.load()
# 阻塞主线程，以保持脚本运行
sys.stdin.read()