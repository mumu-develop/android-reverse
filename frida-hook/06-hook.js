function hook(){
    var BufferMap = Java.use("com.luoge.com.BufferMap");
    BufferMap["show"].implementation = function (map) {
        // object
          var key = map.keySet(); // 这一行获取了Map对象的键集合，这个键集合是一个迭代器
            var it = key.iterator();
            var result = "";
            while(it.hasNext()){
                var keystr = it.next();
                var valuestr = map.get(keystr);
                result += valuestr;
            }
            console.log(result);

        // console.log(`BufferMap.show is called: map=${map}`);
          // 添加数据返回
        map.put("name", "xialuo");
        map.put("age", "18");

        var results = this["show"](map);
        // console.log(`BufferMap.show result=${results}`);
        return results;
    };
}
function showStacks() {
    Java.perform(function () {
        console.log(Java.use("android.util.Log").getStackTraceString(Java.use("java.lang.Exception").$new()));
    });
}
function hook1(){
    var hash = Java.use("java.util.HashMap") // 没有走这个结构
    hash.put.implementation = function (aa,bb){
        console.log("key->",aa)
        // console.log("val->",bb)
        // if ()
        // 跟栈调试

        if(aa.toString() === "Authorization"){
            console.log("查看堆栈")
            showStacks()
        }
        var res = this.put(aa,bb)
        return res
    }
}

// hook请求地址
function hookOkhttpURl() {
    var Builder = Java.use('okhttp3.Request$Builder');
    Builder.url.overload('okhttp3.HttpUrl').implementation = function (a) {
        console.log('url: ' + a)
        var res = this.url(a);
        return res;
    }
}

// 野路子
function hookHeader(){
    var Builder = Java.use("okhttp3.Request$Builder");
    Builder["addHeader"].implementation = function (str, str2) {
        console.log("key: " + str)
        if(str.toString() === "Authorization"){
            console.log("查看堆栈")
            showStacks()
        }

        console.log("val: " + str2)
        var result = this["addHeader"](str, str2);
        return result;
    };
}

function hookrequest(){
    var OkHttpClient = Java.use("okhttp3.OkHttpClient");
    OkHttpClient.newCall.overload("okhttp3.Request").implementation = function (request) {
        console.log("HTTP Request -> " + request.url().toString());
        var call = this.newCall(request); // 获取新的 Call 对象
        var response = call.execute(); // 调用新的 Call 对象的 execute 方法
        console.log("HTTP Response -> " + response.body().string());
        return call
    }
}

// 的用spwn模式、加载时机会比较早
function hookInter(){
    var Builder = Java.use('okhttp3.OkHttpClient$Builder');
    Builder.addInterceptor.implementation = function (a) {
        console.log('a: ' + JSON.stringify(a))
        return this.addInterceptor(a);
}
}

function hookint(){
    var YouthNetworkInterceptor = Java.use("cn.youth.news.network.api.YouthNetworkInterceptor");
YouthNetworkInterceptor["intercept"].implementation = function (chain) {
    console.log(`YouthNetworkInterceptor.intercept is called: chain=${chain}`);
    let result = this["intercept"](chain);
    console.log(`YouthNetworkInterceptor.intercept result=${result}`);
    return result;
};
}
// a: "<instance: okhttp3.Interceptor, $className: cn.youth.news.network.api.YouthNetworkInterceptor>"

function hook2(){
    let ZQNetUtils = Java.use("cn.youth.news.network.ZQNetUtils");
    ZQNetUtils["getParamsByRequestUrl"].implementation = function (list) {
    console.log(`ZQNetUtils.getParamsByRequestUrl is called: list=${list}`);
    let result = this["getParamsByRequestUrl"](list);
    console.log(`ZQNetUtils.getParamsByRequestUrl result=${result}`);
    return result;
};

}

// 入口
function main(){
    Java.perform(function (){
        // hook1()
        // hookOkhttpURl()
        // hookInter()
        // hookrequest()
        // hookHeader()
        // hookint()
        hook2()
    })
}

main()
