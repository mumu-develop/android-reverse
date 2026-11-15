/*
 * ============================================================================
 *  抖音六神签名 · 最小可运行模板（无探测/基准代码）
 * ============================================================================
 *  换版本时改 6 处「VERSION-SPECIFIC」常量：
 *    1. LICENSE / 2. s4 / 3. VER+VERCODE / 4. channel / 5. op 码 / 6. 请求参数集
 *
 *  运行：
 *    java -Dinit=true -Dsignurl=<URL> -Ddeviceid=.. -Dinstallid=.. \
 *         -cp "target/classes;target/deps/*" com.dy.sign.DouyinMetasecSign
 * ============================================================================
 */

package com.dy.sign;

import com.github.unidbg.AndroidEmulator;
import com.github.unidbg.Emulator;
import com.github.unidbg.Module;
import com.github.unidbg.file.FileResult;
import com.github.unidbg.file.IOResolver;
import com.github.unidbg.file.linux.AndroidFileIO;
import com.github.unidbg.linux.android.AndroidEmulatorBuilder;
import com.github.unidbg.linux.android.AndroidResolver;
import com.github.unidbg.linux.android.dvm.*;
import com.github.unidbg.linux.android.dvm.array.ByteArray;
import com.github.unidbg.linux.android.dvm.wrapper.DvmBoolean;
import com.github.unidbg.linux.file.SimpleFileIO;
import com.github.unidbg.memory.Memory;
import com.github.unidbg.pointer.UnidbgPointer;
import com.github.unidbg.virtualmodule.android.AndroidModule;
import com.github.unidbg.virtualmodule.android.JniGraphics;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

/**
 * Douyin (com.ss.android.ugc.aweme) metasec offline-sign harness.
 * Adapted from the hongguo/fqnovel-unidbg MetasecSign template — same metasec_ml SDK
 * (class chain ms/bd/c/m <- a4$a <- MS, MS.b(op) callback protocol).
 *
 * Milestone 1: load libmetasec_ml.so + call JNI_OnLoad under unidbg, log FindClass /
 * first blocker. Sign offset + license are filled in once the loading path is clear.
 */
public class DouyinMetasecSign extends AbstractJni implements IOResolver<AndroidFileIO> {

    static final String PKG = "com.ss.android.ugc.aweme";
    static final String VER = "40.2.0";
    static final int    VERCODE = 400200;                 // TODO confirm from APK manifest
    static final String FILES = "/data/user/0/" + PKG + "/files";

    /** 可固定的时间源（-Dfixtime=<ms>），用于消除非确定性 */
    static long now() {
        String ft = System.getProperty("fixtime");
        return ft == null ? System.currentTimeMillis() : Long.parseLong(ft);
    }
    static final java.util.UUID FIXED_UUID = java.util.UUID.fromString("12345678-1234-1234-1234-123456789abc");

    private final AndroidEmulator emulator;
    private final VM vm;
    private final Module module;
    private final Memory memory;
    private final File soMeta;
    private File certFile;
    private long sessionHandle = -1L;

    public DouyinMetasecSign(File soMeta, File soCpp, File cert) {
        this.soMeta = soMeta;
        this.certFile = cert;
        emulator = AndroidEmulatorBuilder.for64Bit().setProcessName(PKG).build();
        emulator.getSyscallHandler().setVerbose(false);
        emulator.getSyscallHandler().addIOResolver(this);
        java.util.Map<String, Integer> inode = new java.util.HashMap<>();
        inode.put("/data/user/0/" + PKG, 700001);
        inode.put(FILES, 700002);
        emulator.set("inode", inode);
        emulator.set("uid", 10234);

        memory = emulator.getMemory();
        memory.setLibraryResolver(new AndroidResolver(23));

        vm = emulator.createDalvikVM();
        vm.setJni(this);
        vm.setVerbose(System.getProperty("jniVerbose") != null); // 默认关闭，避免服务端日志爆炸
        new AndroidModule(emulator, vm).register(memory);
        new JniGraphics(emulator, vm).register(memory);

        if (soCpp != null && soCpp.exists()) {
            vm.loadLibrary(soCpp, false);
            System.out.println("[*] loaded " + soCpp.getName());
        }

        DvmClass m = vm.resolveClass("ms/bd/c/m");
        DvmClass a4a = vm.resolveClass("ms/bd/c/a4$a", m);
        vm.resolveClass("com/bytedance/mobsec/metasec/ml/MS", a4a);

        System.out.println("[*] loading libmetasec_ml.so ...");
        DalvikModule dm = vm.loadLibrary(soMeta, true);
        module = dm.getModule();
        System.out.println("[*] mapped base=0x" + Long.toHexString(module.base) + ", calling JNI_OnLoad...");
        dm.callJNI_OnLoad(emulator);
        System.out.println("[+] JNI_OnLoad OK. base=0x" + Long.toHexString(module.base));

        if (System.getProperty("init") != null) driveInit();
    }

    // REDACTED for public release. Douyin's hardcoded 244-byte metasec license is a static constant in the
    // app: com.ss.android.ugc.aweme.sec.SecApiImpl (classes14.dex), bound to appID 1128.
    // Extract it from your own copy of the APK and paste it here to run the harness.
    static final String LICENSE =
        "bo95dJizD1WFcV03zOuLzN5Pn1sFtVa3szqiVQmflMJTNW0p0Kpqfw8D4i0zUlfrou4kuYt/i0521YRygM83dwv/wn3DD+TMJF+QFzW9wb8Qq2/1B4jPMbObrDNdyMMukpAYqy1fLWtbLGVIPxsFsZegwQy5lsRX9h49PH/Qx8MwgYvWvH7ZTFLV28LwTWZiljQyBPaBE+TsyumEu0Y+JRkeidHFEYcVs0yRoa+xC004hugQhdPupIt6dBiWA4phsB3fNJZjFTAKGE1lPB4gzt6Qf+FmlgZBbRvT8zekxTV2HZ5dUvSutB2/0QpbHKAvWL4DRA==";

    private String jstr(String s) { return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"") + "\""; }

    private String decryptStr(String key, byte[] seed) {
        try {
            DvmObject<?> r = vm.resolveClass("ms/bd/c/m").callStaticJniMethodObject(emulator,
                    "a(IIJLjava/lang/String;Ljava/lang/Object;)Ljava/lang/Object;",
                    0x1000001, 0, 0L, new StringObject(vm, key), new ByteArray(vm, seed));
            return r == null ? "" : String.valueOf(r.getValue());
        } catch (Throwable t) { return ""; }
    }

    private void driveInit() {
        try {
            String appID = System.getProperty("appID", "1128");
            int channel = Integer.getInteger("channel", 0);
            vm.setVerbose(false);
            String s4 = decryptStr("bebb7f", new byte[]{101,55,69,88,89,33,47,20,103});  // config idx4 (SDK ver)
            System.out.println("[*] s4.LIZ (SDK ver) = \"" + s4 + "\"");
            // config = u2.LIZ() positional JSONArray
            String cfg = "[" + jstr(appID) + ",\"\",\"\"," + jstr(LICENSE) + "," + jstr(s4)
                    + ",\"\",\"\",\"\",\"\",\"\",\"0\",\"-1\",\"" + channel + "\",\"\",\"0\",[],"
                    + "[\"tk_key\",\"douyin\"]]";
            // sub-init i3.LIZIZ: native context init (op 0x1000003) sets the "SDK init" flag
            DvmClass mm0 = vm.resolveClass("ms/bd/c/m");
            DvmObject<?> ctx = vm.resolveClass("android/app/Application").newObject(null);
            try {
                mm0.callStaticJniMethodObject(emulator, "a(IIJLjava/lang/String;Ljava/lang/Object;)Ljava/lang/Object;",
                        16777219, 0, 0L, null, ctx);   // op 0x1000003 native init(context)
                mm0.callStaticJniMethodObject(emulator, "a(IIJLjava/lang/String;Ljava/lang/Object;)Ljava/lang/Object;",
                        16777228, 0, 0L, null, ctx);   // op 0x100000c switch init (via a)
            } catch (Throwable t) { System.out.println("[i] sub-init: " + t); }
            System.out.println("[*] driving init op 0x4000001 (appID=" + appID + ", channel=" + channel
                    + ", cfg len=" + cfg.length() + ")...");
            DvmObject<?> ret = mm0.callStaticJniMethodObject(emulator,
                    "a(IIJLjava/lang/String;Ljava/lang/Object;)Ljava/lang/Object;",
                    0x4000001, 0, 0L, new StringObject(vm, cfg), null);
            System.out.println("[*] init returned = " + (ret == null ? "null" : ret.getValue()));
            if (ret != null && Boolean.TRUE.equals(ret.getValue())) {
                DvmObject<?> h = vm.resolveClass("ms/bd/c/m").callStaticJniMethodObject(emulator,
                        "a(IIJLjava/lang/String;Ljava/lang/Object;)Ljava/lang/Object;",
                        0x4000002, 0, 0L, null, null);
                long handle = (h != null && h.getValue() instanceof Long) ? (Long) h.getValue() : -1;
System.out.println("[+] INIT OK — session handle = " + handle);
                this.sessionHandle = handle;
                if (handle != -1) {
                    // set device/install id (op 0x2000002/3)
                    DvmClass mm = vm.resolveClass("ms/bd/c/m");
                    String devId = System.getProperty("deviceid", "1325332544628567");
                    String iid = System.getProperty("installid", "1325332544632663");
                    System.out.println("DEVICE_ID=" + devId + "  INSTALL_ID=" + iid);
                    mm.callStaticJniMethodObject(emulator, "a(IIJLjava/lang/String;Ljava/lang/Object;)Ljava/lang/Object;",
                            33554434, 0, handle, devId, null);
                    mm.callStaticJniMethodObject(emulator, "a(IIJLjava/lang/String;Ljava/lang/Object;)Ljava/lang/Object;",
                            33554435, 0, handle, iid, null);
                    // report the request (feeds url + x-ss-stub) op 0x2000001
                    String url = System.getProperty("reporturl", "https://aweme.snssdk.com/aweme/v1/feed/?aid=1128&version_code=290100&count=6");
                    long ticket = now();
                    String stub = System.getProperty("stub", "00000000000000000000000000000000");
                    String trace = System.getProperty("trace", "");
                    StringBuilder rb = new StringBuilder();
                    rb.append("x-ss-req-ticket\r\n").append(ticket).append("\r\n");
                    rb.append("x-ss-stub\r\n").append(stub).append("\r\n");
                    if (!trace.isEmpty()) rb.append("x-tt-trace-id\r\n").append(trace).append("\r\n");
                    String rep = rb.append(url).toString();
                    System.out.println("SS_REQ_TICKET=" + ticket);
                    System.out.println("SS_STUB=" + stub);
                    System.out.println("SS_TRACE=" + trace);
                    if (System.getProperty("noreport") == null) {
                        mm.callStaticJniMethodObject(emulator, "a(IIJLjava/lang/String;Ljava/lang/Object;)Ljava/lang/Object;",
                                33554433, 0, handle, rep, "");
                    } else {
                        System.out.println("[*] 跳过 report (noreport)");
                    }
                    // frameSign op 0x200000a -> String[]
                    DvmObject<?> sig = mm.callStaticJniMethodObject(emulator,
                            "a(IIJLjava/lang/String;Ljava/lang/Object;)Ljava/lang/Object;",
                            33554442, 2, handle, url, null);
                    System.out.println("===SIGN_START===");
                    if (sig instanceof com.github.unidbg.linux.android.dvm.array.ArrayObject) {
                        for (Object o : ((com.github.unidbg.linux.android.dvm.array.ArrayObject) sig).getValue())
                            System.out.println("  " + (o == null ? "null" : ((DvmObject<?>) o).getValue()));
                    } else {
                        System.out.println("  frameSign returned: " + (sig == null ? "null" : sig.getValue()));
                    }
System.out.println("===SIGN_END===");
                }
            }
        } catch (Throwable t) {
            System.out.println("[!] init exception: " + t); t.printStackTrace(System.out);
        }
    }

    /** Crack the string obfuscation: native op 0x1000001 = decrypt("keyhex", seed[]) -> plaintext.
     *  Reads capture/decrypt_pairs.tsv (harvested from the decompiled SDK) and dumps all. */
    public void decryptDemo() {
        DvmClass m = vm.resolveClass("ms/bd/c/m");
        vm.setVerbose(false);
        java.util.List<String[]> pairs = new java.util.ArrayList<>();
        File pf = new File("capture/decrypt_pairs.tsv");
        try {
            if (pf.exists())
                for (String line : Files.readAllLines(pf.toPath())) {
                    String[] c = line.split("\t");
                    if (c.length >= 2) pairs.add(new String[]{c[0], c[1]});
                }
        } catch (Exception e) {}
        if (pairs.isEmpty()) pairs.add(new String[]{"6dd7f7", "104,118,5,76,90,111,112,65,122,100,42,98,27,74,87,37"});
        System.out.println("=== string-decrypt (op 0x1000001), " + pairs.size() + " pairs ===");
        StringBuilder out = new StringBuilder();
        int ok = 0;
        for (String[] p : pairs) {
            try {
                String[] bs = p[1].split(",");
                byte[] seed = new byte[bs.length];
                for (int i = 0; i < bs.length; i++) seed[i] = (byte) (Integer.parseInt(bs[i].trim()) & 0xff);
                DvmObject<?> r = m.callStaticJniMethodObject(emulator,
                        "a(IIJLjava/lang/String;Ljava/lang/Object;)Ljava/lang/Object;",
                        0x1000001, 0, 0L, new StringObject(vm, p[0]), new ByteArray(vm, seed));
                String v = r == null ? "" : String.valueOf(r.getValue());
                if (!v.isEmpty()) ok++;
                out.append(p[0]).append('\t').append(v.replace("\n", "\\n")).append('\n');
            } catch (Throwable t) {
                out.append(p[0]).append("\tERR\n");
            }
        }
        try { Files.write(new File("capture/decrypted.txt").toPath(), out.toString().getBytes(StandardCharsets.UTF_8)); } catch (Exception e) {}
        System.out.println("decrypted " + ok + "/" + pairs.size() + " -> capture/decrypted.txt");
    }

    private long tick = 0x2d641eee02cfL;
    private int counter = 0x3a75b16;


    private DvmObject<?> handleMS(BaseVM vm, int op) {
        System.out.println("  [MS.b op=" + op + " 0x" + Integer.toHexString(op) + "]");
        switch (op) {
            case 65539:    return new StringObject(vm, FILES + "/.msdata");
            case 33554433:
            case 33554434: return DvmBoolean.valueOf(vm, true);
            case 16777232: return vm.resolveClass("java/lang/Integer").newObject(VERCODE);
            case 16777233: return new StringObject(vm, VER);
            case 16777218:
                try {
                    if (certFile != null && certFile.exists())
                        return new ByteArray(vm, Files.readAllBytes(certFile.toPath()));
                } catch (Exception e) {}
                System.out.println("    [MS.b op=16777218 cert] none, null");
                return null;
            case 268435470: return vm.resolveClass("java/lang/Long").newObject(now());
            default:
                System.out.println("    [MS.b unhandled op=" + op + " 0x" + Integer.toHexString(op) + "]");
                return null;
        }
    }

    @Override
    public DvmObject<?> callStaticObjectMethodV(BaseVM vm, DvmClass c, String sig, VaList va) {
        if (sig.equals("com/bytedance/mobsec/metasec/ml/MS->b(IIJLjava/lang/String;Ljava/lang/Object;)Ljava/lang/Object;"))
            return handleMS(vm, va.getIntArg(0));
        if (sig.equals("java/util/UUID->randomUUID()Ljava/util/UUID;")) {
            return vm.resolveClass("java/util/UUID").newObject(FIXED_UUID);
        }
        if (sig.equals("java/lang/System->currentTimeMillis()J")) {
            return vm.resolveClass("java/lang/Long").newObject(now());
        }
        if (sig.equals("java/lang/Thread->currentThread()Ljava/lang/Thread;"))
            return vm.resolveClass("java/lang/Thread").newObject(Thread.currentThread());
        if (sig.equals("java/lang/Boolean->valueOf(Z)Ljava/lang/Boolean;"))
            return DvmBoolean.valueOf(vm, va.getIntArg(0) != 0);
        if (sig.equals("java/lang/Integer->valueOf(I)Ljava/lang/Integer;"))
            return vm.resolveClass("java/lang/Integer").newObject(va.getIntArg(0));
        if (sig.equals("java/lang/Long->valueOf(J)Ljava/lang/Long;"))
            return vm.resolveClass("java/lang/Long").newObject(va.getLongArg(0));
        return super.callStaticObjectMethodV(vm, c, sig, va);
    }

    @Override
    public DvmObject<?> callObjectMethodV(BaseVM vm, DvmObject<?> o, String sig, VaList va) {
        switch (sig) {
            case "android/app/Application->getPackageName()Ljava/lang/String;":
            case "android/content/Context->getPackageName()Ljava/lang/String;":
                return new StringObject(vm, PKG);
            case "android/app/Application->getApplicationContext()Landroid/content/Context;":
            case "android/content/Context->getApplicationContext()Landroid/content/Context;":
                return o;
            case "android/app/Application->getContentResolver()Landroid/content/ContentResolver;":
                return vm.resolveClass("android/content/ContentResolver").newObject(null);
            case "android/app/Application->getFilesDir()Ljava/io/File;":
            case "android/content/Context->getFilesDir()Ljava/io/File;":
                return vm.resolveClass("java/io/File").newObject(new File(FILES));
            case "java/io/File->getAbsolutePath()Ljava/lang/String;":
            case "java/io/File->getCanonicalPath()Ljava/lang/String;":
                return new StringObject(vm, String.valueOf(((File) o.getValue()).getPath()).replace("\\", "/"));
        }
        return super.callObjectMethodV(vm, o, sig, va);
    }

    @Override
    public int callIntMethodV(BaseVM vm, DvmObject<?> o, String sig, VaList va) {
        if ("java/lang/Integer->intValue()I".equals(sig) && o.getValue() instanceof Integer) return (Integer) o.getValue();
        return super.callIntMethodV(vm, o, sig, va);
    }

    @Override
    public long callLongMethodV(BaseVM vm, DvmObject<?> o, String sig, VaList va) {
        if ("java/lang/Long->longValue()J".equals(sig) && o.getValue() instanceof Long) return (Long) o.getValue();
        return super.callLongMethodV(vm, o, sig, va);
    }

    @Override
    public boolean callBooleanMethodV(BaseVM vm, DvmObject<?> o, String sig, VaList va) {
        if ("java/lang/Boolean->booleanValue()Z".equals(sig) && o.getValue() instanceof Boolean) return (Boolean) o.getValue();
        return super.callBooleanMethodV(vm, o, sig, va);
    }

    @Override
    public FileResult resolve(Emulator emu, String pathname, int oflags) {
        if (pathname.contains("libmetasec_ml.so"))
            return FileResult.success(new SimpleFileIO(oflags, soMeta, pathname));
        // 用真机导出的 .msdata 状态文件
        if (pathname.contains(".msdata/")) {
            String rel = pathname.substring(pathname.indexOf(".msdata/") + ".msdata/".length());
            File f = new File("msdata", rel);
            if (f.exists() && f.isFile()) {
                System.out.println("  [msdata] serve " + rel + " (" + f.length() + "B)");
                return FileResult.success(new SimpleFileIO(oflags, f, pathname));
            }
        }
        if (pathname.startsWith(FILES) || pathname.contains(".ms") || pathname.contains("msdata"))
            System.out.println("  [resolve] " + pathname + " oflags=0x" + Integer.toHexString(oflags));
        return null;
    }

    public static void main(String[] args) {
        File meta = new File("so/libmetasec_ml.so");
        File cpp = new File("so/libc++_shared.so");
        File cert = new File("capture/ms_16777218.bin");
        if (!meta.exists()) { System.err.println("missing so/libmetasec_ml.so"); return; }
        try {
            DouyinMetasecSign s = new DouyinMetasecSign(meta, cpp.exists() ? cpp : null, cert.exists() ? cert : null);
            System.out.println("[*] milestone: metasec loaded under unidbg on Douyin.");
if (System.getProperty("decrypt") != null) s.decryptDemo();
            String url = System.getProperty("signurl");
            if (url == null) {
                System.err.println("用法: -Dinit=true -Dsignurl=<URL> -Ddeviceid=<id> -Dinstallid=<id>");
                return;
            }
            s.initIfNeeded();
            java.util.Map<String, String> headers =
                    s.signHeaders(url, Integer.getInteger("op2", 0), 12);
            if (headers == null) {
                System.err.println("[!] 签名失败（初始化随机失败，重跑一次即可）");
                return;
            }
            System.out.println("===HEADERS_START===");
            for (java.util.Map.Entry<String, String> e : headers.entrySet()) {
                System.out.println(e.getKey() + "=" + e.getValue());
            }
            System.out.println("===HEADERS_END===");
        } catch (Throwable t) { System.out.println("[!] blocker:"); t.printStackTrace(System.out); }
    }

    /** 对指定 URL 生成全部请求头，输出 KEY=VALUE 行 */
    /** 单独调用某个 op，打印返回类型和内容 */

    /** 初始化（幂等），供常驻服务调用 */
    public synchronized void initIfNeeded() {
        if (sessionHandle == -1L) driveInit();
    }

    /** 常驻服务入口：返回 header 键值对；内部自动重试，失败返回 null */
    public synchronized java.util.Map<String, String> signHeaders(String url, int op2, int tries) {
        if (sessionHandle == -1L) initIfNeeded();
        DvmClass mm = vm.resolveClass("ms/bd/c/m");
        for (int attempt = 0; attempt < tries; attempt++) {
            try {
                DvmObject<?> r = mm.callStaticJniMethodObject(emulator,
                        "a(IIJLjava/lang/String;Ljava/lang/Object;)Ljava/lang/Object;",
                        0x2000006, op2, sessionHandle, url, null);
                if (r instanceof com.github.unidbg.linux.android.dvm.array.ArrayObject) {
                    Object[] arr = ((com.github.unidbg.linux.android.dvm.array.ArrayObject) r).getValue();
                    java.util.Map<String, String> h = new java.util.LinkedHashMap<>();
                    for (int i = 0; i + 1 < arr.length; i += 2) {
                        Object k = arr[i], v = arr[i + 1];
                        if (k == null || v == null) continue;
                        h.put(String.valueOf(((DvmObject<?>) k).getValue()),
                              String.valueOf(((DvmObject<?>) v).getValue()));
                    }
                    if (!h.isEmpty()) return h;
                }
            } catch (Throwable t) {
                // 单次失败可重试
            }
        }
        return null;
    }

    /** 直接按偏移调用 (url, cookie) -> char* 的签名函数 */
    /** 广域探测：找所有返回 [name, value] 的 op */
}