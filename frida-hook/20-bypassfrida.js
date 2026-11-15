
 const badKeywords = [
      'frida',
      'gum-js-loop',
      'gmain',
      'linjector',
      're.frida.server',
      'frida-agent',
      'frida-gadget',
      'frida-server',
      'magisk',
      'xposed',
      'substrate'
  ];

  const fakeMapsLine = '';
  const fakeReadlink = '/system/lib/libc.so';

  function containsBad(s) {
      if (!s) return false;
      const lower = s.toLowerCase();
      return badKeywords.some(k => lower.indexOf(k.toLowerCase()) !== -1);
  }

  function readCStringSafe(ptr) {
      try {
          if (ptr.isNull()) return '';
          return ptr.readCString();
      } catch (_) {
          return '';
      }
  }

  function writeFakeString(buf, str) {
      try {
          Memory.writeUtf8String(buf, str);
      } catch (_) {}
  }

  function hookOpenFamily() {
      const funcs = ['open', 'open64', 'openat', 'openat64', 'fopen', 'fopen64'];

      funcs.forEach(name => {
          const addr = Module.findExportByName(null, name);
          if (!addr) return;

          Interceptor.attach(addr, {
              onEnter(args) {
                  this.name = name;

                  if (name.indexOf('openat') === 0) {
                      this.pathPtr = args[1];
                  } else {
                      this.pathPtr = args[0];
                  }

                  this.path = readCStringSafe(this.pathPtr);

                  if (
                      this.path.indexOf('/proc/self/maps') !== -1 ||
                      this.path.indexOf('/proc/self/status') !== -1 ||
                      this.path.indexOf('/proc/self/task') !== -1 ||
                      this.path.indexOf('/proc/self/fd') !== -1 ||
                      this.path.indexOf('/proc/') !== -1 && (
                          this.path.indexOf('/maps') !== -1 ||
                          this.path.indexOf('/status') !== -1 ||
                          this.path.indexOf('/cmdline') !== -1 ||
                          this.path.indexOf('/comm') !== -1
                      )
                  ) {
                      const fake = '/dev/null';
                      const p = Memory.allocUtf8String(fake);

                      if (name.indexOf('openat') === 0) {
                          args[1] = p;
                      } else {
                          args[0] = p;
                      }
                  }
              }
          });

          console.log('[+] hook', name);
      });
  }

  function hookReadlink() {
      const funcs = ['readlink', 'readlinkat'];

      funcs.forEach(name => {
          const addr = Module.findExportByName(null, name);
          if (!addr) return;

          Interceptor.attach(addr, {
              onEnter(args) {
                  this.name = name;

                  if (name === 'readlink') {
                      this.path = readCStringSafe(args[0]);
                      this.buf = args[1];
                      this.size = args[2].toInt32();
                  } else {
                      this.path = readCStringSafe(args[1]);
                      this.buf = args[2];
                      this.size = args[3].toInt32();
                  }

                  this.shouldFake =
                      this.path.indexOf('/proc/self/fd') !== -1 ||
                      this.path.indexOf('/proc/') !== -1 && this.path.indexOf('/fd') !== -1;
              },
              onLeave(retval) {
                  if (this.shouldFake) {
                      const s = fakeReadlink;
                      writeFakeString(this.buf, s);
                      retval.replace(s.length);
                  }
              }
          });

          console.log('[+] hook', name);
      });
  }

  function hookRead() {
      const readAddr = Module.findExportByName(null, 'read');
      if (!readAddr) return;

      Interceptor.attach(readAddr, {
          onEnter(args) {
              this.buf = args[1];
          },
          onLeave(retval) {
              const len = retval.toInt32();
              if (len <= 0) return;

              try {
                  let data = this.buf.readUtf8String(len);
                  if (!data) return;

                  let changed = false;

                  badKeywords.forEach(k => {
                      const re = new RegExp(k, 'ig');
                      if (re.test(data)) {
                          data = data.replace(re, 'hide');
                          changed = true;
                      }
                  });

                  // hide TracerPid
                  if (data.indexOf('TracerPid:') !== -1) {
                      data = data.replace(/TracerPid:\s*\d+/g, 'TracerPid:\t0');
                      changed = true;
                  }

                  // hide maps line
                  if (data.indexOf('frida') !== -1 || data.indexOf('gum-js') !== -1) {
                      data = data
                          .split('\n')
                          .filter(line => !containsBad(line))
                          .join('\n');
                      changed = true;
                  }

                  if (changed) {
                      Memory.writeUtf8String(this.buf, data);
                      retval.replace(data.length);
                  }
              } catch (_) {}
          }
      });

      console.log('[+] hook read');
  }

  function hookPread() {
      const funcs = ['pread', 'pread64'];

      funcs.forEach(name => {
          const addr = Module.findExportByName(null, name);
          if (!addr) return;

          Interceptor.attach(addr, {
              onEnter(args) {
                  this.buf = args[1];
              },
              onLeave(retval) {
                  const len = retval.toInt32();
                  if (len <= 0) return;

                  try {
                      let data = this.buf.readUtf8String(len);
                      if (!data) return;

                      if (containsBad(data)) {
                          badKeywords.forEach(k => {
                              data = data.replace(new RegExp(k, 'ig'), 'hide');
                          });
                          Memory.writeUtf8String(this.buf, data);
                          retval.replace(data.length);
                      }
                  } catch (_) {}
              }
          });

          console.log('[+] hook', name);
      });
  }

  function hookConnect() {
      const connectAddr = Module.findExportByName(null, 'connect');
      if (!connectAddr) return;

      Interceptor.attach(connectAddr, {
          onEnter(args) {
              const sockaddr = args[1];
              const family = sockaddr.readU16();

              // AF_INET = 2
              if (family === 2) {
                  const port = sockaddr.add(2).readU16();
                  const realPort = ((port & 0xff) << 8) | (port >> 8);

                  // Frida 默认端口
                  if (realPort === 27042 || realPort === 27043) {
                      console.log('[hide] block connect port:', realPort);
                      this.block = true;
                  }
              }
          },
          onLeave(retval) {
              if (this.block) {
                  retval.replace(-1);
              }
          }
      });

      console.log('[+] hook connect');
  }

  function hookSendRecv() {
      ['send', 'recv', 'sendto', 'recvfrom'].forEach(name => {
          const addr = Module.findExportByName(null, name);
          if (!addr) return;

          Interceptor.attach(addr, {
              onEnter(args) {
                  this.buf = args[1];
                  this.len = args[2].toInt32();
              },
              onLeave(retval) {
                  if (retval.toInt32() <= 0) return;

                  try {
                      const data = this.buf.readUtf8String(Math.min(this.len, 512));
                      if (containsBad(data)) {
                          console.log('[hide]', name, data);
                          Memory.writeUtf8String(this.buf, data.replace(/frida/ig, 'hide'));
                      }
                  } catch (_) {}
              }
          });

          console.log('[+] hook', name);
      });
  }

  function hookStrstrMemmem() {
      const strstr = Module.findExportByName(null, 'strstr');
      if (strstr) {
          Interceptor.attach(strstr, {
              onEnter(args) {
                  this.haystack = readCStringSafe(args[0]);
                  this.needle = readCStringSafe(args[1]);
                  this.block = containsBad(this.haystack) || containsBad(this.needle);
              },
              onLeave(retval) {
                  if (this.block) {
                      retval.replace(ptr(0));
                  }
              }
          });
          console.log('[+] hook strstr');
      }

      const strcasestr = Module.findExportByName(null, 'strcasestr');
      if (strcasestr) {
          Interceptor.attach(strcasestr, {
              onEnter(args) {
                  this.haystack = readCStringSafe(args[0]);
                  this.needle = readCStringSafe(args[1]);
                  this.block = containsBad(this.haystack) || containsBad(this.needle);
              },
              onLeave(retval) {
                  if (this.block) {
                      retval.replace(ptr(0));
                  }
              }
          });
          console.log('[+] hook strcasestr');
      }

      const memmem = Module.findExportByName(null, 'memmem');
      if (memmem) {
          Interceptor.attach(memmem, {
              onEnter(args) {
                  this.needle = '';
                  try {
                      this.needle = args[2].readUtf8String(args[3].toInt32());
                  } catch (_) {}
                  this.block = containsBad(this.needle);
              },
              onLeave(retval) {
                  if (this.block) {
                      retval.replace(ptr(0));
                  }
              }
          });
          console.log('[+] hook memmem');
      }
  }

  function hookPtrace() {
      const ptrace = Module.findExportByName(null, 'ptrace');
      if (!ptrace) return;

      Interceptor.replace(ptrace, new NativeCallback(function () {
          return 0;
      }, 'long', ['int', 'int', 'pointer', 'pointer']));

      console.log('[+] replace ptrace');
  }

  function hookPrctlThreadName() {
      const prctl = Module.findExportByName(null, 'prctl');
      if (!prctl) return;

      Interceptor.attach(prctl, {
          onEnter(args) {
              const option = args[0].toInt32();

              // PR_SET_NAME = 15
              if (option === 15) {
                  const name = readCStringSafe(args[1]);
                  if (containsBad(name)) {
                      const fake = Memory.allocUtf8String('worker');
                      args[1] = fake;
                  }
              }
          }
      });

      console.log('[+] hook prctl');
  }

  function hookPthreadSetname() {
      const funcs = ['pthread_setname_np'];

      funcs.forEach(name => {
          const addr = Module.findExportByName(null, name);
          if (!addr) return;

          Interceptor.attach(addr, {
              onEnter(args) {
                  const threadName = readCStringSafe(args[1]);
                  if (containsBad(threadName)) {
                      args[1] = Memory.allocUtf8String('worker');
                  }
              }
          });

          console.log('[+] hook', name);
      });
  }

  function patchCmdline() {
      const addr = Module.findExportByName(null, 'getprogname');
      if (!addr) return;

      Interceptor.attach(addr, {
          onLeave(retval) {
              const name = readCStringSafe(retval);
              if (containsBad(name)) {
                  retval.replace(Memory.allocUtf8String('app_process'));
              }
          }
      });

      console.log('[+] hook getprogname');
  }

  function hideJavaSide() {
      Java.perform(function () {
          const File = Java.use('java.io.File');

          File.exists.implementation = function () {
              const path = this.getAbsolutePath();
              if (
                  path.indexOf('frida') !== -1 ||
                  path.indexOf('re.frida') !== -1 ||
                  path.indexOf('/proc/self/maps') !== -1 ||
                  path.indexOf('/proc/self/status') !== -1
              ) {
                  return false;
              }
              return this.exists();
          };

          const Runtime = Java.use('java.lang.Runtime');

          Runtime.exec.overload('java.lang.String').implementation = function (cmd) {
              if (cmd.indexOf('getprop') !== -1 ||
                  cmd.indexOf('ps') !== -1 ||
                  cmd.indexOf('netstat') !== -1 ||
                  cmd.indexOf('lsof') !== -1) {
                  cmd = 'echo';
              }
              return this.exec(cmd);
          };

          Runtime.exec.overload('[Ljava.lang.String;').implementation = function (cmdArray) {
              const joined = cmdArray.join(' ');
              if (
                  joined.indexOf('ps') !== -1 ||
                  joined.indexOf('netstat') !== -1 ||
                  joined.indexOf('lsof') !== -1 ||
                  joined.indexOf('frida') !== -1
              ) {
                  const arr = Java.array('java.lang.String', ['echo']);
                  return this.exec(arr);
              }
              return this.exec(cmdArray);
          };

          console.log('[+] Java hide installed');
      });
  }

  function main() {
      hookOpenFamily();
      hookReadlink();
      hookRead();
      hookPread();
      hookConnect();
      hookSendRecv();
      hookStrstrMemmem();
      hookPtrace();
      hookPrctlThreadName();
      hookPthreadSetname();
      patchCmdline();

      if (Java.available) {
          hideJavaSide();
      }
  }

  setImmediate(main);


