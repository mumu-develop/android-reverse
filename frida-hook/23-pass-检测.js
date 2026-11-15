function hook_patch() {
    var patch = Module.findExportByName("libc.so", "pthread_create");
    console.log("[pth_create]", patch);
    Interceptor.attach(patch, {
        onEnter: function (args) {
            var module = Process.findModuleByAddress(args[2]);
            if (module != null) {
                console.log("开启线程-->", module.name, args[2].sub(module.base));
            }
        },
        onLeave: function (retval) {}
    });
}

function hook_dlopen(){
    //Android8.0之后加载so通过android_dlopen_ext函数
    var android_dlopen_ext = Module.findExportByName(null,"android_dlopen_ext");
    console.log("addr_android_dlopen_ext",android_dlopen_ext);
    Interceptor.attach(android_dlopen_ext,{
        onEnter:function(args){
            var pathptr = args[0];
            if(pathptr!=null && pathptr != undefined){
                var path = ptr(pathptr).readCString();
                 console.log("android_dlopen_ext:",path);
                if(path.indexOf("libmsaoaidsec.so")!=-1){
                    console.log("android_dlopen_ext:",path);
                    hook_call_constructors()
                }
            }
        },
        onLeave:function(retvel){
            //console.log("leave!");
        }
    })
}
function hook_call_constructors() {
    let linker = null;
    if (Process.pointerSize === 4) {
        linker = Process.findModuleByName("linker");
    } else {
        linker = Process.findModuleByName("linker64"); // 连接器
    }
    let call_constructors_addr, get_soname
    let symbols = linker.enumerateSymbols();
    for (let index = 0; index < symbols.length; index++) {
        let symbol = symbols[index];
        if (symbol.name === "__dl__ZN6soinfo17call_constructorsEv") {
            call_constructors_addr = symbol.address; // 同一台手机 这个地址是死的
        } else if (symbol.name === "__dl__ZNK6soinfo10get_sonameEv") {
            get_soname = new NativeFunction(symbol.address, "pointer", ["pointer"]);
        }
    }
    console.log(call_constructors_addr)
    var listener = Interceptor.attach(call_constructors_addr, {
        onEnter: function (args) {
            console.log("hooked call_constructors")
            var module = Process.findModuleByName("libmsaoaidsec.so")
            if (module != null) {
                // nop_addr(module.base.add(0x127f1))
                // console.log("0x1c544:替换成功")
                // nop_addr(module.base.add(0x11e1d))
                // console.log("0x1b8d4:替换成功")
                Interceptor.replace(module.base.add(0x1B924), new NativeCallback(function () {
                    console.log("替换成功")
                }, "void", []))
                listener.detach()
            }
        },
    })
}

hook_patch()







