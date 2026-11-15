# -*- coding:utf-8 -*-
# Author: luoge
import sys
import frida

device = frida.get_usb_device()
print(device)

# 获取目标应用程序的PID
pid = device.get_process("新快报").pid
print(pid)

# 附加到目标进程
session = device.attach(pid)
# 读取Frida脚本
js_cpde = '''
Java.perform(function () {
    // 获取当前应用的上下文
    var currentApplication = Java.use('android.app.ActivityThread').currentApplication();
    var context = currentApplication.getApplicationContext();
    // 获取包名
    var packageName = context.getPackageName();
    // 输出包名
    console.log("当前应用的包名是: " + packageName);
});
'''

# 创建Frida脚本并加载
script = session.create_script(js_cpde)
 # 加载脚本到目标进程
script.load()
# 阻塞主线程，以保持脚本运行
sys.stdin.read()