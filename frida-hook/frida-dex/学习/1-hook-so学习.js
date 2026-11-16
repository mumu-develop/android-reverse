


// hook1()
/**
 * 打印 所有的 so 文件
 */
function hookSo1(){
    var modules = Process.enumerateModules();
    for (var i in modules) {
        var module = modules[i];
        // console.log(module.name)
        if (module.name==="libnative-lib.so"){
            console.log(module.name)
            console.log(module.base)
            console.log(JSON.stringify(module))
        }
    }
}

// hookSo1()
/**
 * 打印指定 so 文件中的所有方法
 */
function hook2(){
    var exports = Module.enumerateExports("libnative-lib.so");
for (var i = 0; i < exports.length; i++) {
    if (exports[i].name.includes("Java")) {
        console.log(JSON.stringify(exports[i]));
    }
    // console.log(JSON.stringify(exports[i]))
}
}
// hook2()

// 中场休息10分钟

// hook C 方法
function hook3(){
    var addr = Module.findExportByName("libnative-lib.so", "Java_com_luoge_com_MainActivity_nativeMessage")
    console.log(addr)
    Interceptor.attach(addr, {
          onEnter: function (args) {
            // 在函数执行前执行的代码
            //   console.log(args)
          },
          onLeave: function (retval) {
            // 在函数执行后执行的代码
              console.log(retval)
              // var res = Java.cast(retval,Java.use("java.lang.String"))
              // console.log(res)
              var env = Java.vm.getEnv();
              console.log(env.getStringUtfChars(retval).readUtf8String());

              // 修改返回值
               var res1 = env.newStringUtf("xxxxxx")
                retval.replace(res1)

          }
});
}

// hook3()
function hook4(){
    var addr = Module.findExportByName("libnative-lib.so", "Java_com_luoge_com_MainActivity_nativeSum")
    console.log(addr)
    Interceptor.attach(addr, {
          onEnter: function (args) {
            // 在函数执行前执行的代码
            //   console.log(args[2].readUtf8String());
            //   var arg2 = Java.cast(args[2],Java.use("java.lang.String"))
            //   var arg3 = Java.cast(args[3],Java.use("java.lang.String"))
            //   console.log(arg2)
            //   console.log(arg3)
              var env = Java.vm.getEnv(); // jstring
              console.log(env.getStringUtfChars(args[2]).readUtf8String());
              console.log(env.getStringUtfChars(args[3]).readUtf8String());

          },
          onLeave: function (retval) {
            // 在函数执行后执行的代码
              var env = Java.vm.getEnv();
              console.log(env.getStringUtfChars(retval).readUtf8String());

          }
});


}

// hook4()

function hook5(){
        var addr = Module.findExportByName("libnative-lib.so", "Java_com_luoge_com_MainActivity_getSign")
    console.log(addr)
    Interceptor.attach(addr, {
          onEnter: function (args) {
            // 在函数执行前执行的代码
            //   console.log(args[2].readUtf8String());
            //   var arg2 = Java.cast(args[2],Java.use("java.lang.String"))
            //   var arg3 = Java.cast(args[3],Java.use("java.lang.String"))
            //   console.log(arg2)
            //   console.log(arg3)
              var env = Java.vm.getEnv(); // jstring
              console.log(env.getStringUtfChars(args[2]).readUtf8String());
              console.log(env.getStringUtfChars(args[3]).readUtf8String());

          },
          onLeave: function (retval) {
            // 在函数执行后执行的代码
              var env = Java.vm.getEnv();
              console.log(env.getStringUtfChars(retval).readUtf8String());

          }
});
}
hook5()



function hook1(){
    var addr = Module.findExportByName("libwtf.so", "Java_cn_thecover_lib_common_manager_SignManager_getSign")
    console.log(addr)
     Interceptor.attach(addr, {
          onEnter: function (args) {
            // 在函数执行前执行的代码
            //   console.log(args[2].readUtf8String());
            //   var arg2 = Java.cast(args[2],Java.use("java.lang.String"))
            //   var arg3 = Java.cast(args[3],Java.use("java.lang.String"))
            //   console.log(arg2)
            //   console.log(arg3)
              var env = Java.vm.getEnv(); // jstring
              console.log(env.getStringUtfChars(args[2]).readUtf8String());
              console.log(env.getStringUtfChars(args[3]).readUtf8String()); // null
              console.log(env.getStringUtfChars(args[4]).readUtf8String());

          },
          onLeave: function (retval) {
            // 在函数执行后执行的代码
              var env = Java.vm.getEnv();
              console.log(env.getStringUtfChars(retval).readUtf8String());

          }
});

}

// hook1()

