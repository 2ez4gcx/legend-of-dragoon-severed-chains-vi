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
               trong thư mục game/; móc exit -> _exit; tay cầm ảo SDL (SDL_AttachVirtualJoystick) cho lớp phủ cảm ứng;
               cầu tua nhanh: TouchPad.nativeSetSpeed ghi biến C, RegisterNatives AndroidBridge.fastForward() cho HotSpot
TouchPad       lớp phủ phím (D-pad, ✕○△□, L1/L2/R1/R2, SELECT/START); hàng giữa trên: ⚙ (TouchSettings: độ đậm 10–100%,
               cỡ phím 70–120%, rung khi bấm, tốc độ tua nhanh ×2/×3/×4; lưu SharedPreferences "touchpad"),
               ẩn/hiện, ▶▶ tua nhanh (bật/tắt; tắt thì về tốc độ chọn trong Tùy chọn → Lối chơi → Tốc độ game)
SC             SDL3 + OpenGL ES 3.2 (GlesApi) + OpenAL Soft + FFmpeg (JavaCPP) như bản PC
```

Lớp đè chỉ dùng cho Android (`sc-android/`, đứng đầu classpath, mã gốc đã kiểm trùng jar affcef0):

| Lớp | Sửa |
|---|---|
| `legend.core.platform.SdlWindow` | Android không có OpenGL desktop: vào thẳng ES 3.2; **không** xin ngữ cảnh debug (driver điện thoại báo cảnh báo vô hại mức HIGH, ví dụ "unable to generate a triangle primitive because there are less than 3 vertices", `GlesApi` hiện lên màn hình thành "GL ERROR …" và ghi log kèm stack trace mỗi lần — chậm); bật lại bằng `-Dscvi.gldebug=true`. Tiết kiệm pin: không swap khung không vẽ gì mới (hỏi `RenderEngine.isFramePresented()` của sc-vi); app xuống nền thì tạm dừng thiết bị OpenAL (`SDL_AddEventWatch`, `alcDevicePauseSOFT`), lên lại thì chạy tiếp |
| `legend.core.platform.PlatformManager` | Chờ tới nhịp kế bằng `LockSupport.parkNanos` (bản gốc ngủ theo mili-giây rồi quay vòng `Thread.sleep(0)` suốt mili-giây cuối, giữ một nhân CPU thức trước mỗi khung); trên Windows (`run_sc -Gles`) giữ cách gốc |
| `legend.core.renderer.ShaderManager` | Dùng shader GLSL ES dịch sẵn `gfx/shaders_es` (sinh trên PC bằng `ShaderCacheTool`, shaderc + SPIRV-Cross) — không mang shaderc/SPIRV-Cross lên máy |
| `legend.core.renderer.opengles.GlesTexture` | Texture độ sâu dùng `GL_DEPTH_COMPONENT32F` (ES 3 không nhận `GL_DEPTH_COMPONENT` + `GL_FLOAT`: "Render buffer is not complete!") |
| `legend.game.unpacker.IsoReader` | Đọc đĩa từ fd đã mở sẵn (mở lại `/proc/self/fd/N` bị kiểm quyền chủ tệp `media_rw`) |
| `legend.core.platform.AndroidBridge` (mới) | Hàm `fastForward()` do libsclauncher đăng ký; `SdlWindow.tick()` đọc mỗi khung, đặt `Config.setGameSpeedMultiplier` (tắt → `getLoadedGameSpeedMultiplier`) |

Ngoài ra `config.conf` đặt sẵn `low_memory_unpacker=true` (heap điện thoại 1–2 GB; kiểu giải nén thường hết bộ nhớ).

Hiệu năng (dùng chung với bản PC, trong `sc-vi`): logic SC chạy đúng một lần mỗi khung vẽ, không bù giờ, nên điện thoại vẽ
không kịp thì cả game chậm như quay chậm. `RenderEngine` (sc-vi) tự bỏ vẽ khung bị trễ (Tùy chọn → Đồ họa → "Tự bỏ khung
hình khi máy chậm", mặc định bật; logcat ghi `[sc-vi] auto frame skip: X of Y frames not drawn`), và lần chạy đầu trên
Android `ConfigStorage` hạ độ phân giải "Theo cửa sổ" (máy 2400×1080 vẽ 3200×1200) xuống 720p (1920×720) một lần (dấu
`game/scvi-android-defaults-1`); người chơi đổi lại trong Tùy chọn thì giữ lựa chọn đó.

Tiết kiệm pin (26/10, sau v0.3):

- Khung không vẽ gì mới (tua nhanh ▶▶/Tốc độ game: chỉ 1/N nhịp vẽ; tự bỏ khung; tiết kiệm pin) thì không chép ảnh cũ ra màn
  và không swap (`RenderEngine.enableIdlePresentSkip`, chỉ bật khi cửa sổ là `SdlWindow` của sc-android), không tải VRAM
  (`Gpu.startFrame`, sc-vi). Ở ×4: 60 lần chép/swap và tải VRAM mỗi giây thay vì 240.
- Tùy chọn → Đồ họa → "Tiết kiệm pin (30 khung/giây)" (mặc định tắt): vẽ tối đa 30 khung/giây, logic vẫn đủ nhịp. Có tác dụng ở
  cảnh vẽ 60 Hz (đi lại, bản đồ thế giới, menu); trận đánh 20–30 Hz không đổi.
- App xuống nền (Home, tắt màn): SDL chặn luồng chính nhưng OpenAL không phải âm thanh của SDL nên nhạc vẫn phát và luồng âm
  thanh vẫn trộn; nay `SdlWindow` tạm dừng thiết bị OpenAL (logcat `[sc-android] app in the background: audio paused`).
- Màn 90/120 Hz: `VnGameActivity` xin chế độ màn 60 Hz cùng độ phân giải (`preferredDisplayModeId`).
- Bản PC dùng chung phần `RenderEngine`/`Gpu`; `SdlWindow` của sc-vi (PC) cũng chỉ swap khung có vẽ và không vẽ khi cửa sổ thu
  nhỏ (game và nhạc vẫn chạy). Khung không vẽ vẫn dọn hàng đợi, đối tượng chờ xoá và scissor stack như khung vẽ (cảnh bản đồ đẩy
  scissor mỗi nhịp, tối đa 100: không dọn thì thu nhỏ ~1,7 s là crash).
- Đo trên PC, đường ES (`run_sc -Gles`, RTX 3060 Laptop, cảnh hội thoại đầu chương 4, công suất GPU theo `nvidia-smi`, nền
  18,5 W khi không chạy game): v0.3 ×1 20,0 W / CPU 30% một nhân, ×4 26,7 W / 94%; bản mới ×1 20,4 W / 34%, ×4 21,2 W / 49%;
  bật tiết kiệm pin ×1 19,3 W / 15%, ×4 19,3 W / 31%. PC (OpenGL) thu nhỏ cửa sổ ở cảnh trên 20 s: 18,5 W (bằng nền) / CPU
  10%, mở lại chơi tiếp bình thường. Giả lập Android 15: dừng/chạy lại âm thanh khi xuống nền/lên lại, ▶▶ vẽ đúng.

Biểu tượng ứng dụng: `python android/gen_icon.py` sinh từ tranh `android/icon_rong.webp` (biểu tượng thường bo góc + biểu tượng
thích ứng Android 8+ `mipmap-anydpi-v26/ic_launcher.xml`: tranh 72dp ở lớp trước, chính tranh làm mờ ở lớp sau) và biểu tượng
cửa sổ game trên máy tính `out/gfx/textures/icon.vi.png` (64×64; `--windows` chỉ sinh tệp này).

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

Sửa `launcher/sclauncher.c` thì phải dựng lại launcher **cho cả hai ABI** (`-Abi arm64-v8a -Only launcher` và
`-Abi x86_64 -Only launcher`): `build_natives.ps1` ghi dấu SHA-256 của mã nguồn vào `out/<abi>/libsclauncher.src.sha256`,
`make_apk.py` từ chối đóng gói khi dấu không khớp. (APK arm64 đầu tiên ngày 17/10, SHA `1400a698…`, chở launcher arm64 cũ thiếu
`--add-opens java.base/java.io` → `IsoReader` không dùng được fd → SC báo "Please place US ISOs/BINs in "isos" directory"
dù đã chọn đủ 4 đĩa; `retest.ps1` chỉ dựng lại x86_64.)

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
