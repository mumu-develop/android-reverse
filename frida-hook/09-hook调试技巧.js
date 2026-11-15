function showStacks() {
    Java.perform(function () {
        console.log(Java.use("android.util.Log").getStackTraceString(Java.use("java.lang.Exception").$new()));
    });
}

function hook() {
    var keys = "x-sign"
    var hashMap = Java.use("java.util.HashMap");
    hashMap.put.implementation = function (k,v) {
        console.log("key->"+ k +"--||val-->" + v)
        if(k.toString() === keys){
            // 看堆栈
            showStacks()
        }
        var result = this.put(k,v)
        return result
    }
}

function hookText(){
    var TextUtils = Java.use("android.text.TextUtils");
    TextUtils.isEmpty.implementation = function(aa){
        console.log("TextUtils ->",aa);
        if ( null != aa && '1758003781' in aa){
            showStacks()
        }
        return this.isEmpty(aa)
    }

}


// 封装公共的方法
function show(kk,vv){
    if (kk === vv){
        showStacks()
    }
}

function hookjson() {
    var JSONObject = Java.use('org.json.JSONObject');
// Hook JSONObject.put() 方法
    // 针对put推送 进行Hook 日志
    JSONObject.put.overload('java.lang.String', 'java.lang.Object').implementation = function (key, value) {
        console.log('Hooked JSONObject.put()');
        console.log('Key: ' + key.toString());
        console.log('Value: ' + value.toString());
        // 可在此处对参数进行修改或记录
        // 调用原始的put()方法
        show(key.toString(), "Encrypt")

        return this.put(key, value);
    };
}


function hooksort(){
    Java.perform(function() {
  var Collections = Java.use('java.util.Collections');
  // Hook sort() 方法
  Collections.sort.overload("java.util.List").implementation = function(list) {
    console.log('Hooked Collections.sort()');
    console.log('List: ' + list.toString());
    // 可在此处对参数进行修改或记录
   // 使用 Java.cast 进行类型转换 将list转换成ArrayList类型
        var res = Java.cast(list,Java.use("java.util.ArrayList"))
        console.log('List list-->',res)
      // 调用原始的 sort() 方法
      return this.sort(list);
  };

  Collections.sort.overload("java.util.List","java.util.Comparator").implementation = function(a,b) {
    console.log('Hooked Collections.sort()');
    var res = Java.cast(a,Java.use("java.util.ArrayList"))
    console.log('Comparator list-->',res)
      return    this.sort(a,b);
  };

});
}

function hookString() {
    var StringClass = Java.use('java.lang.String');

    // Hook String 类的构造函数
    StringClass.getBytes.overload().implementation = function () {
        console.log('Original Value');
        // 可在此处修改传入的字符串参数
        var res = this.getBytes();
        var newString = StringClass.$new(res)
        // 输出修改后的值
        console.log('Modified Value: ' + newString);
        return res;
    };

    // Hook String 类的静态方法
    StringClass.getBytes.overload('java.lang.String').implementation = function (obj) {
        console.log('Hooked String.valueOf()');
        var res = this.getBytes(obj);
        var newString = StringClass.$new(res, obj)
        // 输出修改后的结果
        console.log('getBytes: ' + newString)
        return res
    }

}


function hooktoString() {
    // 获取 StringBuilder 类并定义需要 Hook 的方法名
    var stringBuilderClass = Java.use("java.lang.StringBuilder");
    stringBuilderClass.toString.implementation = function () {
        var res = this.toString.apply(this, arguments)
        console.log("tostring --> " + res)

        if(res.toString().includes("username=1234")){
            showStacks()
        }

        return res
    }
}

// 入口
function main() {
    // 调用入口
    Java.perform(function () {
        hooktoString()
    })
}

setImmediate(main)