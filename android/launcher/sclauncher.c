/*
 * libsclauncher.so — điểm vào SDL_main của bản Android: chạy Severed Chains (Java 25) trên JRE HotSpot đi kèm APK.
 *
 * SDLActivity (lớp Java của SDL3) nạp libSDL3.so rồi thư viện này và gọi SDL_main(argc, argv) trên luồng "SDLThread".
 * argv (VnGameActivity.getArguments()): khoá=giá trị — game=<thư mục game>, jre=<thư mục JRE>, lib=<nativeLibraryDir>,
 * tmp=<cacheDir>, xmx=<MB>, rồi các "-D..."/"-X..." bổ sung cho JVM.
 * Máy ảo chạy trên một pthread riêng có ngăn xếp 16 MB (luồng Java của ART chỉ có ~1 MB); luồng này là luồng chính của
 * SC (gọi SDL, OpenGL ES) cho tới khi Main.main trả về. Mọi lệnh SDL của SC chạy trên cùng một luồng như yêu cầu của SDL.
 * stdout/stderr của JVM được chuyển vào logcat (thẻ "SC").
 *
 * Tay cầm ảo: lớp phủ cảm ứng gọi nativeSetButton/nativeSetAxis (JNI, lớp vn.lodsc.TouchPad) → SDL_SetJoystickVirtual*.
 * Tay cầm ảo được gắn khi SC đã khởi tạo hệ con gamepad của SDL (lần chạm đầu tiên sau đó).
 */
#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>
#include <android/log.h>
#include <dirent.h>
#include <dlfcn.h>
#include <errno.h>
#include <jni.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define TAG "SC"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)

typedef jint (*CreateJavaVM_t)(JavaVM **, void **, void *);

/* jni.h của NDK chỉ tới JNI_VERSION_1_6; HotSpot 25 nhận 1.8 */
#ifndef JNI_VERSION_1_8
#define JNI_VERSION_1_8 0x00010008
#endif

#define MAX_OPTS 64

static int g_argc;
static char **g_argv;
static int g_exit_code = 1;

static const char *arg_value(const char *key) {
  const size_t n = strlen(key);
  for(int i = 1; i < g_argc; i++) {
    if(strncmp(g_argv[i], key, n) == 0 && g_argv[i][n] == '=') {
      return g_argv[i] + n + 1;
    }
  }
  return NULL;
}

/* stdout/stderr → logcat */
static int g_pipe[2];

static void *log_thread(void *unused) {
  (void)unused;
  char buf[1024];
  FILE *in = fdopen(g_pipe[0], "r");
  if(in == NULL) {
    return NULL;
  }
  while(fgets(buf, sizeof buf, in) != NULL) {
    __android_log_write(ANDROID_LOG_INFO, TAG, buf);
  }
  return NULL;
}

static void redirect_stdio(void) {
  setvbuf(stdout, NULL, _IOLBF, 0);
  setvbuf(stderr, NULL, _IONBF, 0);
  if(pipe(g_pipe) != 0) {
    return;
  }
  dup2(g_pipe[1], STDOUT_FILENO);
  dup2(g_pipe[1], STDERR_FILENO);
  pthread_t t;
  pthread_create(&t, NULL, log_thread, NULL);
  pthread_detach(t);
}

/*
 * Móc "exit" của JVM (System.exit, Thoát trong game): kết thúc tiến trình bằng _exit. exit() thường chạy atexit/huỷ
 * mutex tĩnh khi các luồng giao diện của Android (hwui) còn chạy -> "FORTIFY: pthread_mutex_lock called on a destroyed
 * mutex" và hộp thoại "ứng dụng bị dừng".
 */
static void jvm_exit_hook(jint code) {
  LOGI("JVM exit(%d)", code);
  _exit(code);
}

static char *fmt(const char *format, const char *a) {
  const size_t n = strlen(format) + (a ? strlen(a) : 0) + 1;
  char *s = malloc(n);
  snprintf(s, n, format, a ? a : "");
  return s;
}

/*
 * Không gian tên linker của app không tìm được thư viện phụ thuộc trong jre/lib (vd libnio.so cần libnet.so) ->
 * nạp trước mọi .so của JRE (dlopen đường dẫn đầy đủ, nhiều lượt cho tới khi không nạp thêm được); về sau HotSpot nạp
 * lại theo đường dẫn sẽ nhận đúng thư viện đã nạp (khớp soname). Thư viện cần X11 (libawt_xawt) hỏng là bình thường.
 */
static void preload_jre(const char *jre) {
  static const char *dirs[] = {"lib/server", "lib"};
  char paths[160][512];
  int loaded[160] = {0};
  int count = 0;
  for(unsigned d = 0; d < sizeof dirs / sizeof dirs[0]; d++) {
    char dir[512];
    snprintf(dir, sizeof dir, "%s/%s", jre, dirs[d]);
    DIR *dp = opendir(dir);
    if(dp == NULL) {
      continue;
    }
    struct dirent *e;
    while((e = readdir(dp)) != NULL && count < 160) {
      const size_t len = strlen(e->d_name);
      if(len > 3 && strcmp(e->d_name + len - 3, ".so") == 0) {
        snprintf(paths[count++], sizeof paths[0], "%s/%s", dir, e->d_name);
      }
    }
    closedir(dp);
  }
  int progress = 1;
  while(progress) {
    progress = 0;
    for(int i = 0; i < count; i++) {
      if(!loaded[i] && dlopen(paths[i], RTLD_NOW | RTLD_GLOBAL) != NULL) {
        loaded[i] = 1;
        progress = 1;
      }
    }
  }
  for(int i = 0; i < count; i++) {
    if(!loaded[i]) {
      dlopen(paths[i], RTLD_NOW | RTLD_GLOBAL);
      LOGI("khong nap truoc %s: %s", paths[i], dlerror());
    }
  }
}

static void *jvm_thread(void *unused) {
  (void)unused;
  const char *game = arg_value("game");
  const char *jre = arg_value("jre");
  const char *lib = arg_value("lib");
  const char *tmp = arg_value("tmp");
  const char *xmx = arg_value("xmx");
  if(game == NULL || jre == NULL || lib == NULL || tmp == NULL) {
    LOGE("thieu tham so game/jre/lib/tmp");
    return NULL;
  }

  if(chdir(game) != 0) {
    LOGE("chdir %s: %s", game, strerror(errno));
    return NULL;
  }
  setenv("HOME", game, 1);
  setenv("JAVA_HOME", jre, 1);
  setenv("TMPDIR", tmp, 1);

  preload_jre(jre);
  char *jvm_path = fmt("%s/lib/server/libjvm.so", jre);
  void *jvm = dlopen(jvm_path, RTLD_NOW | RTLD_GLOBAL);
  if(jvm == NULL) {
    LOGE("dlopen %s: %s", jvm_path, dlerror());
    return NULL;
  }
  CreateJavaVM_t create = (CreateJavaVM_t)dlsym(jvm, "JNI_CreateJavaVM");
  if(create == NULL) {
    LOGE("khong co JNI_CreateJavaVM: %s", dlerror());
    return NULL;
  }

  JavaVMOption opts[MAX_OPTS];
  int n = 0;
  opts[n++].optionString = fmt("-Djava.home=%s", jre);
  opts[n++].optionString = fmt("-Duser.dir=%s", game);
  opts[n++].optionString = fmt("-Duser.home=%s", game);
  opts[n++].optionString = fmt("-Djava.io.tmpdir=%s", tmp);
  opts[n++].optionString = fmt("-Djava.library.path=%s", lib);
  opts[n++].optionString = fmt("-Djava.class.path=%s", arg_value("cp"));
  opts[n++].optionString = fmt("-Xmx%sm", xmx ? xmx : "1536");
  opts[n++].optionString = fmt("-Xss4m", NULL);
  /* như launch.bat của SC */
  opts[n++].optionString = fmt("-Djoml.fastmath", NULL);
  opts[n++].optionString = fmt("-Djoml.sinLookup", NULL);
  opts[n++].optionString = fmt("-Djoml.useMathFma", NULL);
  opts[n++].optionString = fmt("--add-opens=java.base/java.util=ALL-UNNAMED", NULL);
  opts[n++].optionString = fmt("--add-exports=java.base/jdk.internal.misc=ALL-UNNAMED", NULL);
  opts[n++].optionString = fmt("--enable-native-access=ALL-UNNAMED", NULL);
  /* IsoReader (sc-android) dựng FileDescriptor từ fd đĩa người chơi đã chọn */
  opts[n++].optionString = fmt("--add-opens=java.base/java.io=ALL-UNNAMED", NULL);
  /* thư viện native: tất cả nằm trong nativeLibraryDir của APK */
  opts[n++].optionString = fmt("-Dorg.lwjgl.librarypath=%s", lib);
  opts[n++].optionString = fmt("-Dorg.lwjgl.system.allocator=system", NULL);
  opts[n++].optionString = fmt("-Dorg.lwjgl.opengles.libname=libGLESv2.so", NULL);
  opts[n++].optionString = fmt("-Dorg.lwjgl.egl.libname=libEGL.so", NULL);
#if defined(__x86_64__)
  opts[n++].optionString = fmt("-Dorg.bytedeco.javacpp.platform=android-x86_64", NULL);
#else
  opts[n++].optionString = fmt("-Dorg.bytedeco.javacpp.platform=android-arm64", NULL);
#endif
  opts[n++].optionString = fmt("-Dorg.bytedeco.javacpp.pathsFirst=true", NULL);
  opts[n++].optionString = fmt("-Dorg.bytedeco.javacpp.cachedir=%s/javacpp", tmp);
  opts[n++].optionString = fmt("-Djava.awt.headless=true", NULL);
  opts[n++].optionString = fmt("-Dscvi.android=true", NULL);
  for(int i = 1; i < g_argc && n < MAX_OPTS; i++) {
    if(g_argv[i][0] == '-') {
      opts[n++].optionString = g_argv[i];
    }
  }
  for(int i = 0; i < n; i++) {
    opts[i].extraInfo = NULL;
    LOGI("JVM opt: %s", opts[i].optionString);
  }
  opts[n].optionString = "exit";
  opts[n++].extraInfo = (void *)jvm_exit_hook;

  JavaVMInitArgs args;
  args.version = JNI_VERSION_1_8;
  args.nOptions = n;
  args.options = opts;
  args.ignoreUnrecognized = JNI_FALSE;

  JavaVM *vm = NULL;
  JNIEnv *env = NULL;
  const jint rc = create(&vm, (void **)&env, &args);
  if(rc != JNI_OK) {
    LOGE("JNI_CreateJavaVM loi %d", rc);
    return NULL;
  }

  jclass main = (*env)->FindClass(env, "legend/game/Main");
  if(main == NULL) {
    (*env)->ExceptionDescribe(env);
    LOGE("khong tim thay legend.game.Main");
    (*vm)->DestroyJavaVM(vm);
    return NULL;
  }
  jmethodID mainMethod = (*env)->GetStaticMethodID(env, main, "main", "([Ljava/lang/String;)V");
  jobjectArray jargs = (*env)->NewObjectArray(env, 0, (*env)->FindClass(env, "java/lang/String"), NULL);
  LOGI("chay legend.game.Main");
  (*env)->CallStaticVoidMethod(env, main, mainMethod, jargs);
  if((*env)->ExceptionCheck(env)) {
    (*env)->ExceptionDescribe(env);
    g_exit_code = 1;
  } else {
    g_exit_code = 0;
  }
  LOGI("legend.game.Main tra ve (%d)", g_exit_code);
  (*vm)->DestroyJavaVM(vm);
  return NULL;
}

int SDL_main(int argc, char *argv[]) {
  g_argc = argc;
  g_argv = argv;
  redirect_stdio();

  /* Cửa sổ SC có thể đổi cỡ -> SDL cho xoay theo cảm biến (cả dọc); game chỉ chơi ngang */
  SDL_SetHint(SDL_HINT_ORIENTATIONS, "LandscapeLeft LandscapeRight");

  pthread_attr_t attr;
  pthread_attr_init(&attr);
  pthread_attr_setstacksize(&attr, 16 * 1024 * 1024);
  pthread_t t;
  if(pthread_create(&t, &attr, jvm_thread, NULL) != 0) {
    LOGE("pthread_create loi");
    return 1;
  }
  pthread_join(t, NULL);
  LOGI("SDL_main ket thuc (%d)", g_exit_code);
  return g_exit_code;
}

/* ---- tay cầm ảo ---- */
static SDL_JoystickID g_pad_id;
static SDL_Joystick *g_pad;

static SDL_Joystick *pad(void) {
  if(g_pad != NULL) {
    return g_pad;
  }
  if(!SDL_WasInit(SDL_INIT_GAMEPAD)) {
    return NULL; /* SC chưa khởi tạo SDL */
  }
  SDL_VirtualJoystickDesc desc;
  SDL_INIT_INTERFACE(&desc);
  desc.type = SDL_JOYSTICK_TYPE_GAMEPAD;
  desc.naxes = SDL_GAMEPAD_AXIS_COUNT;
  desc.nbuttons = SDL_GAMEPAD_BUTTON_COUNT;
  desc.vendor_id = 0x054c; /* hiện nút kiểu PlayStation */
  desc.product_id = 0x0ce6;
  desc.name = "Tay cam cam ung";
  g_pad_id = SDL_AttachVirtualJoystick(&desc);
  if(g_pad_id == 0) {
    LOGE("SDL_AttachVirtualJoystick: %s", SDL_GetError());
    return NULL;
  }
  g_pad = SDL_OpenJoystick(g_pad_id);
  LOGI("tay cam ao %u", (unsigned)g_pad_id);
  return g_pad;
}

JNIEXPORT void JNICALL Java_vn_lodsc_TouchPad_nativeSetButton(JNIEnv *env, jclass cls, jint button, jboolean down) {
  (void)env; (void)cls;
  SDL_Joystick *j = pad();
  if(j != NULL) {
    SDL_SetJoystickVirtualButton(j, button, down);
  }
}

JNIEXPORT void JNICALL Java_vn_lodsc_TouchPad_nativeSetAxis(JNIEnv *env, jclass cls, jint axis, jint value) {
  (void)env; (void)cls;
  SDL_Joystick *j = pad();
  if(j != NULL) {
    SDL_SetJoystickVirtualAxis(j, axis, (Sint16)value);
  }
}
