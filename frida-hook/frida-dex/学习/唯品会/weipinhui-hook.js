

function showStacks() {
    Java.perform(function () {
        console.log(Java.use("android.util.Log").getStackTraceString(Java.use("java.lang.Exception").$new()));
    });
}
function hook1(){
    var hash = Java.use("java.util.HashMap") // 没有走这个结构
    hash.put.implementation = function (aa,bb){
        console.log("key->",aa)
        console.log("val->",bb)
        // if ()
        // 跟栈调试
        // if(aa.toString() === "sign"){
        //     console.log("查看堆栈")
        //     showStacks()
        // }
        var res = this.put(aa,bb)
        return res
    }
}

// hook1()

function hook2(){
    var b = Java.use("com.achievo.vipshop.commons.h.b");
b["b"].implementation = function (context, treeMap, str, str2) {
    console.log(`b.b is called: context=${context}, treeMap=${treeMap}, str=${str}, str2=${str2}`);
    let result = this["b"](context, treeMap, str, str2);
    console.log(`b.b result=${result}`);
    return result;
};
}

function hook3(){
    var b = Java.use("com.achievo.vipshop.commons.h.b");
b["a"].implementation = function (context, treeMap, str) {
    console.log(`b.a is called: context=${context}, treeMap=${treeMap}, str=${str}`);
    let result = this["a"](context, treeMap, str);
    console.log(`b.a result=${result}`);
    return result;
};
}

function hook4(){
    var VCSPSecurityConfig = Java.use("com.vip.vcsp.security.sign.VCSPSecurityConfig");
VCSPSecurityConfig["gs"].implementation = function (context, map, str, z) {
    console.log(`VCSPSecurityConfig.gs is called: context=${context}, map=${map}, str=${str}, z=${z}`);
    let result = this["gs"](context, map, str, z);
    console.log(`VCSPSecurityConfig.gs result=${result}`);
    return result;
};
}


// 监听C代码
function hook5(){

    var funaddr = Module.findExportByName("libkeyinfo.so","getByteHash")
    console.log(funaddr)
    Interceptor.attach(funaddr,{
        onEnter:function (args) {
            console.log("arg->",args[2].readCString())
        },
        onLeave:function (res) {
            console.log("res->",res.readCString() )
        }

    })

}


function hook6(){
    Java.perform(function () {

        var KeyInfo = Java.use("com.vip.vcsp.KeyInfo");
        KeyInfo["gsNav"].implementation = function (context, map, str, z) {
        map = Java.cast(map,Java.use("java.util.TreeMap"))
        console.log(`KeyInfo.gsNav is called: context=${context}, map=${map}, str=${str}, z=${z}`);
        let result = this["gsNav"](context, map, str, z);
        console.log(`KeyInfo.gsNav result=${result}`);
        return result;
};


})

}

hook6()





// nmp i @type/frida-gum

