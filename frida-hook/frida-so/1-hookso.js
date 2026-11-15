
// var addr = Module.findExportByName("libwtf.so","Java_cn_thecover_lib_common_manager_SignManager_getSign")
// console.log(addr)

function hookSo1(){
    var modules = Process.enumerateModules();
    for (var i in modules) {
        var module = modules[i];
        // console.log(module.name)
        // 查so文件里面的方法
            if(module.name==="libnative-lib.so"){
                console.log(module.base)
                console.log(JSON.stringify(module))
            }
    }
}

// hookSo1()

function hookexpore(){
    var exports = Module.enumerateExports("libnative-lib.so");
for (var i = 0; i < exports.length; i++) {
    if (exports[i].name.includes("Java")) {
         console.log(JSON.stringify(exports[i]));
    }
}
}
// hookexpore()
function hookfun1(){
    var addr = Module.findExportByName("libnative-lib.so","Java_com_luoge_com_MainActivity_nativeMessage")
    console.log(addr)
    Interceptor.attach(addr, {
          onEnter: function (args) {
            // 在函数执行前执行的代码
              console.log("进入了函数")
          },
          onLeave: function (retval) {
            // 在函数执行后执行的代码
            var env  = Java.vm.getEnv();
            var res = env.getStringUtfChars(retval).readUtf8String()
              console.log(res)
              // console.log(retval.toString())
          }
});
}

hookfun1()

