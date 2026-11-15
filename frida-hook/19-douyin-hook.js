
// 从网络层导出数据 做拦截  mtop

function hook() {
	Java.perform(function(){
		var SsHttpCall = Java.use("com.bytedance.retrofit2.SsHttpCall");
        var jsons = Java.use("com.google.gson.Gson")
		SsHttpCall.getResponseWithInterceptorChain.implementation=function(){
			var response = this.getResponseWithInterceptorChain();
			var request = this.originalRequest.value;
			var url = request.getUrl();
			console.log("url:",url);
            if(url.includes("comment/list")){
                console.log(jsons.$new().toJson(response.body()))
            }
			return response;
		}
	});
}

setImmediate(hook);

