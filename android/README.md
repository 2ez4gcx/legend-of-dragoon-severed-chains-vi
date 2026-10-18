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
| `legend.core.platform.SdlWindow` | Android không có OpenGL desktop: vào thẳng ES 3.2; **không** xin ngữ cảnh debug (driver điện thoại báo cảnh báo vô hại mức HIGH, ví dụ "unable to generate a triangle primitive because there are less than 3 vertices", `GlesApi` hiện lên màn hình thành "GL ERROR …" và ghi log kèm stack trace mỗi lần — chậm); bật lại bằng `-Dscvi.gldebug=true` |
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

## Mô hình HD trên Android (tuỳ chọn, route B)

Mô hình nhân vật làm lại (định dạng LRM spec 1, `tools/sc_remaster/SPEC.md`) **không** được tạo trên điện thoại và **không**
nằm trong APK: người chơi tạo trên máy tính Windows bằng công cụ "Tạo mô hình HD" (`TAO_MO_HINH_HD.bat`, từ đĩa của chính
mình), bấm "Xuất gói Android" (bộ "mobile": L1 + atlas 2x), chép tệp `.zip` vào điện thoại rồi nhập trong app.

```
SetupActivity  nút "Nhập mô hình HD (.zip)": trình chọn tệp Android (ACTION_OPEN_DOCUMENT, application/zip, đọc một lần)
               nút "Mô hình HD: Bật/Tắt": ghi game/remaster.properties (enabled=true|false; giữ textures, log theo
               đúng nghĩa runtime: textures thiếu/hd -> hd, khác -> retail; log true -> true, khác -> false)
               đã có 4 đĩa: đếm ngược 3 giây rồi mới tự vào game, để kịp bấm các nút trên (bấm nút nào cũng huỷ
               đếm ngược; Chơi = vào ngay; rời màn hình cũng huỷ). Mở bằng "--ez setup true" thì không tự vào game.
RemasterImport giải nén luồng vào game/remaster.import/, kiểm, rồi đổi chỗ nguyên tử:
               remaster -> remaster.old, remaster.import/remaster -> remaster, xoá remaster.old; bật Mô hình HD
               lỗi bất kỳ: xoá remaster.import, game/remaster giữ nguyên, báo tiếng Việt
               mở app: dọn remaster.import còn sót, khôi phục remaster.old nếu app bị tắt giữa hai lần đổi tên
SC (sc-vi.jar) đọc game/remaster.properties + game/remaster/{index.tsv, models/*.lrm, textures/*.png} như bản PC
```

Gói hợp lệ chỉ gồm `remaster/index.tsv`, `remaster/manifest.json` (tuỳ chọn), `remaster/models/<40 hex>.lrm`,
`remaster/textures/<40 hex>.png`, các mục thư mục `remaster/`, `remaster/models/`, `remaster/textures/`, và ghi chú
`DOC_TRUOC.txt` ở gốc zip (bỏ qua, không giải nén). Bị từ chối: mục khác (kể cả lồng thêm một thư mục ngoài), đường dẫn
tuyệt đối / `..` / `.` / `\` / `:` / thành phần rỗng, tên mục không phải UTF-8, mục trùng tên, mục > 64 MB (`index.tsv`,
`manifest.json` > 4 MB), tổng > 1 GB, > 4096 mục, zip hỏng/cụt, zip không trọn vẹn (đọc hết tới cuối tệp: bản ghi
kết thúc EOCD phải ở đúng cuối, mục lục đếm đúng số mục đã đọc — bắt được zip cắt đúng ranh giới giữa hai mục, thiếu mục
lục, thừa byte sau EOCD); `index.tsv` không đúng §3.7 (dòng 1 `LRMINDEX<TAB>1`, UTF-8 không BOM, LF, `<khoá><TAB>models/<khoá>.lrm<TAB><nhãn>`,
khoá không trùng); `.lrm` được chỉ mục mà thiếu; `.lrm` sai magic `LRM1` / version 1 / modelKey ≠ tên tệp; PNG có SHA-1 ≠ tên tệp,
sai chữ ký, cỡ không phải luỹ thừa 2 trong 1..2048; `manifest.json` không phải JSON hoặc `format` ≠ 1. Cần bộ nhớ trống
≥ cỡ zip × 1,1 + 200 MB. Phần còn lại của tệp `.lrm` do runtime kiểm (§3.5.4; lỗi → mô hình gốc).

`game/remaster/` và `game/remaster.properties` nằm ngoài `Payload.PROGRAM` nên còn nguyên khi cài lại / cập nhật APK.
`make_apk.py` bỏ công cụ PC khỏi payload (`TAO_MO_HINH_HD.bat`, `HUONG_DAN_MO_HINH_HD.txt`, `vi/remaster/**` trừ
`THIRD_PARTY.txt`) và dừng dựng nếu payload chở dữ liệu mô hình HD (`game/remaster*`, `remaster.properties`, `.lrm`, atlas PNG,
Real-ESRGAN/Blender; không phân biệt hoa thường) hoặc `Payload.PROGRAM` chứa "remaster" hay mục trỏ tới cả `game/` (`""`, `.`,
`..`); tự kiểm: `python android/make_apk.py --selftest-guards`.

Thử trên giả lập (bản x86_64 debuggable; dữ liệu tổng hợp `sample_cube`, không phải dữ liệu Sony; không mở game):

```bash
powershell -ExecutionPolicy Bypass -File android/test/remaster_import.ps1 [-Build] [-Determinism] [-Saf] [-NoUpdate] [-RealUpdate]
```

Gồm 64 gói (7 hợp lệ, kể cả zip STORED, zip ghi luồng có data descriptor, tên tệp zip tiếng Việt, zip có chú thích;
57 gieo lỗi), công tắc qua nút (kể cả giá trị lạ trong `remaster.properties`), khôi phục sau khi bị tắt giữa lúc đổi chỗ, cài lại và cập nhật APK
(giải nén lại payload) giữ dữ liệu, chốt chặn `make_apk.py`, (`-Determinism`) dựng APK hai lần cùng SHA-256, (`-Saf`) nhập thật
qua nút + trình chọn tệp, (`-RealUpdate`) cập nhật thật lên APK x86_64 dựng từ gói v0.3 (versionCode cao hơn, payload
khác) rồi hạ lại. Bản debuggable nhận `--es hd_test_zip <tệp trong filesDir>` (+ `--el hd_test_total_cap / hd_test_entry_cap
/ hd_test_reserve`) để nhập không qua trình chọn tệp; bản phát hành arm64 bỏ qua các tham số này. Thử trên điện thoại thật
(hiển thị, fps, bộ nhớ) thuộc bước kiểm tích hợp I1.

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
