
Java.perform(function () {
      // 获取当前应用的上下文
      var currentApplication = Java.use('android.app.ActivityThread').currentApplication();
      var context = currentApplication.getApplicationContext();
      // 获取包名
      var packageName = context.getPackageName();
      // 输出包名
      console.log("当前应用的包名是: " + packageName);
});

// Java.perform 入口  main
// Java.use  找类

// 不是Node JS的脚本  需要使用frida执行


