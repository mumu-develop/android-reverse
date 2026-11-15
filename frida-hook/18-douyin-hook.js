function hook_dlopen(module_name, fun) {
    var android_dlopen_ext = Module.findExportByName(null, "android_dlopen_ext");
    if (android_dlopen_ext) {
        Interceptor.attach(android_dlopen_ext, {
            onEnter: function (args) {
                var pathptr = args[0];
                if (pathptr) {
                    this.path = (pathptr).readCString();
                    if (this.path.indexOf(module_name) >= 0) {
                        this.canhook = true;
                    }
                }
            },
            onLeave: function (retval) {
                if (this.canhook) {
                    let verifyadd = Module.getExportByName("libsscronet.so","SSL_CTX_set_custom_verify");
                    Interceptor.attach(verifyadd,{
                        onEnter(args){
                            Interceptor.attach(args[2],{
                                onLeave(retval){
                                    retval.replace(0x0);
                                }
                            })
                        }
                    })
                }
            }
        });
    }
}

hook_dlopen("libsscronet.so","SSL_CTX_set_custom_verify")