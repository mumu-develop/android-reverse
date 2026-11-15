# -*- coding:utf-8 -*- 
# Author: luoge

import frida, sys

jsCode = """
Java.perform(function () {
    // 获取当前应用的上下文
    var currentApplication = Java.use('android.app.ActivityThread').currentApplication();
    var context = currentApplication.getApplicationContext();
    // 获取包名
    var packageName = context.getPackageName();
    // 输出包名
    console.log("当前应用的包名是: " + packageName);
});
"""

def message(message, data):
    if message['type'] == 'send':
        print(f"[*] {message['payload']}")
    else:
        print(message)

device = frida.get_device_manager().add_remote_device('127.0.0.1:8881')
print(device)
# 附着到已运行的应用
# pid = device.get_process("新快报").pid
# print(pid)
# # 附加到目标进程
# session = device.attach(pid)

session = device.attach("新快报")


script = session.create_script(jsCode)
script.on("message",message)
script.load()