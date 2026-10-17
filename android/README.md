# Bản Android (thử nghiệm) — The Legend of Dragoon tiếng Việt trên Severed Chains

APK `release/LoD-SC-VN-v<ver>-android-arm64.apk`: Severed Chains (SC, Java 25) commit `affcef0` + bản Việt hoá v0.2, chạy
trên điện thoại Android 10+ arm64 có OpenGL ES 3.2. **Không chứa dữ liệu game**: lần đầu người chơi chọn 4 file `.bin`
đĩa gốc bản Mỹ của mình.

## Cách hoạt động

```
SetupActivity  (lần đầu / sau cập nhật) giải nén assets/payload.zip -> filesDir/jre (JRE 25), filesDir/game (SC + bản Việt)
               chọn 4 đĩa .bin bằng trình chọn tệp Android (SAF, giữ quyền đọc lâu dài, không chép đĩa)
               mỗi lần chơi: mở 4 tệp, nối game/isos/discN.bin -> /proc/self/fd/N
VnGameActivity (SDLActivity của SDL3) nạp libSDL3.so + libsclauncher.so, gọi SDL_main
libsclauncher  nạp trước thư viện của JRE, dlopen libjvm.so, JNI_CreateJavaVM (luồng 16 MB), chạy legend.game.Main
               trong thư mục game/; móc exit -> _exit; tay cầm ảo SDL (SDL_AttachVirtualJoystick) cho lớp phủ cảm ứng
SC             SDL3 + OpenGL ES 3.2 (GlesApi) + OpenAL Soft + FFmpeg (JavaCPP) như bản PC
```

Lớp đè chỉ dùng cho Android (`sc-android/`, đứng đầu classpath, mã gốc đã kiểm trùng jar affcef0):

| Lớp | Sửa |
|---|---|
| `legend.core.platform.SdlWindow` | Android không có OpenGL desktop: vào thẳng ES 3.2; driver từ chối ngữ cảnh debug thì thử lại không có cờ debug |
| `legend.core.renderer.ShaderManager` | Dùng shader GLSL ES dịch sẵn `gfx/shaders_es` (sinh trên PC bằng `ShaderCacheTool`, shaderc + SPIRV-Cross) — không mang shaderc/SPIRV-Cross lên máy |
| `legend.core.renderer.opengles.GlesTexture` | Texture độ sâu dùng `GL_DEPTH_COMPONENT32F` (ES 3 không nhận `GL_DEPTH_COMPONENT` + `GL_FLOAT`: "Render buffer is not complete!") |
| `legend.game.unpacker.IsoReader` | Đọc đĩa từ fd đã mở sẵn (mở lại `/proc/self/fd/N` bị kiểm quyền chủ tệp `media_rw`) |

Ngoài ra `config.conf` đặt sẵn `low_memory_unpacker=true` (heap điện thoại 1–2 GB; kiểu giải nén thường hết bộ nhớ).

## Dựng

Cần: Android SDK (`cmdline-tools`, `build-tools;36.1.0`, `platforms;android-36`, `ndk;28.2.13676358`, `cmake;3.31.6`),
JDK 17, thư mục `game/` (bản build SC affcef0) và gói Windows v0.2 trong `release/`. Mã nguồn chính thức giải nén vào
`deps/android/src`: SDL3 3.4.14, LWJGL 3.4.3, libffi 3.8.0, Opus 1.6.1, OpenAL Soft 1.25.2. JRE 25 Android
(`deps/android/jre/jre25-android-arm64.tar.xz`, bản phát hành `download_jre25` của AngelAuraMC/angelauramc-openjdk-build,
SHA-256 kiểm trong `make_apk.py`), `ffmpeg-8.0.1-1.5.13-android-arm64.jar` + `javacpp-1.5.13-android-arm64.jar` (Maven
Central) trong `deps/android/maven`. Python dạng gói (MSIX) không đọc được `%LOCALAPPDATA%`: chép `build-tools/36.1.0`
và `platforms/android-36/android.jar` vào `deps/android/sdk-tools`.

```bash
powershell -ExecutionPolicy Bypass -File android/build_natives.ps1
powershell -ExecutionPolicy Bypass -File android/build_sc_android.ps1 -CheckOriginal
python android/make_apk.py --version 0.2
```

Khoá ký: `deps/android/keys/lodsc-release.jks` + `keystore.pass` (tạo lần đầu, **sao lưu** — bản cập nhật phải cùng khoá).
Dựng 2 lần ra cùng SHA-256.

## Thử

- Trên máy tính, đường ES của bản Android: `powershell -File tools/run_sc.ps1 -Gles` (ES 3.2 qua WGL của driver NVIDIA).
- Giả lập: `python android/make_apk.py --version 0.2 --abi x86_64` (bản debuggable), AVD Android 15 x86_64 chạy
  `emulator -avd lodsc -gpu host -feature GuestAngle,Vulkan,GLESDynamicVersion` (không có GuestAngle chỉ có ES 3.1);
  `android/test/retest.ps1` dựng + cài + mở + in log, `android/test/adbui.ps1` bấm/chụp qua uiautomator.
- `game/android-jvm.txt` (mỗi dòng một tuỳ chọn JVM) để gỡ lỗi, chỉ đặt được trên bản debuggable (`adb shell run-as`).

## Kết quả thử (17/10/2026)

| Bước | Giả lập Android 15 (GuestAngle) | PC, đường ES (NVIDIA ES 3.2) |
|---|---|---|
| Cài, giải nén payload, chọn 4 đĩa (kiểm định dạng, báo khi chọn sai số lượng) | đạt | — |
| JVM HotSpot trong app, nạp LWJGL/SDL3/OpenAL/FFmpeg, mod, cấu hình, phông Việt | đạt | đạt |
| Giải nén tài nguyên từ đĩa (kiểu ít bộ nhớ) + vá script | đạt (147 s) | đạt |
| Phim mở đầu (FFmpeg) + âm thanh | đạt | đạt |
| Màn tựa tiếng Việt, dòng ghi công, tay cầm ảo (▲▼, ×), màn tạo lượt chơi | đạt | đạt |
| Cảnh trong game: nền | đạt | đạt |
| Cảnh trong game: mô hình 3D | **không hiện** (lỗi tầng ANGLE/gfxstream của giả lập) | **đạt** |
| ANR khi popup "Viewing full screen" lấy focus lúc đang tạo cửa sổ | xảy ra 1 lần (hwui kẹt fence Vulkan của giả lập) | — |

Chưa thử trên điện thoại thật (Adreno/Mali): cần thử hiển thị mô hình 3D, hiệu năng, nhiệt, bộ nhớ.
