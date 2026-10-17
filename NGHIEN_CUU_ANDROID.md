# Nghiên cứu: đồ hoạ upscale và bản Android cho Severed Chains (17/10/2026)

> **Cập nhật cùng ngày**: người dùng đồng ý làm theo hướng mục 2. Bản Android đã dựng được (APK arm64, chạy JRE 25 trong
> app, SDL3 + OpenGL ES 3.2), thử trên giả lập Android 15 và đường ES trên PC — chi tiết, cách dựng, kết quả và phần còn
> thiếu (thử máy thật) trong **[android/README.md](android/README.md)**. JRE: dùng bản dựng sẵn `download_jre25` của nhóm
> Amethyst (AngelAuraMC) thay vì tự dựng OpenJDK (máy không có WSL).

## 1. Bản SC hiện tại đã "upscale" đồ hoạ chưa?

**Chưa có ảnh upscale (AI/HD).** Bản SC commit `affcef0` mà gói Việt hoá ghim theo:

| Phần đồ hoạ | Trong SC `affcef0` |
|---|---|
| Mô hình 3D (nhân vật, quái, phép, bản đồ thế giới) | **Vẽ lại ở độ phân giải màn hình**: mục Đồ họa → Độ phân giải = Gốc (240p) / 480p / 720p / 1080p / 1440p / 4K / 8K / Theo màn hình (mặc định). Không rung điểm như PS1, có màn rộng (widescreen), 60 khung hình/giây. |
| Ảnh nền vẽ sẵn của cảnh (submap), ảnh menu, chân dung, chữ trong ảnh | **Ảnh gốc PS1** (368×240…), chỉ phóng to + lọc mịn. |
| Texture trên mô hình 3D | Ảnh gốc PS1. |
| Phim (FMV) | Phim gốc (STR), phóng to. |
| Hiệu ứng | Shader tuỳ chọn: CRT, bloom, viền tối, `Pixelate` (làm mờ ngược về 240/480/720p). |

Mã SC có sẵn chỗ cho mod thay ảnh nền / texture cảnh (`SubmapEnvironmentTextureEvent`, `SubmapObjectTextureEvent` trong
`legend.game.modding.events.submap`), nhưng **không kèm gói ảnh nào**.

Cộng đồng có dự án **The Legend of Dragoon Upscale Project** (theflyingzamboni, Zychronix, Mr. Scentless — AI upscale ảnh nền,
giao diện, lượt nhẹ texture 3D), nay **chỉ nhắm Severed Chains**, nhưng **chưa phát hành, chưa có ngày hoàn thành**, đang tạm dừng
để làm SC 3.0 / Dragoon Modifier (trang dự án; cập nhật gần nhất của Zychronix ngày 16/3/2025). Nguồn:
<https://legendofdragoon.org/projects/image-upscaling/>, <https://legendofdragoon.org/news/upscale-project-debut/>.

Tự upscale bằng AI: kỹ thuật làm được (máy này RTX 3060 Laptop 6 GB), nhưng ảnh upscale là **dữ liệu suy ra từ đĩa của Sony**:
không được chở sẵn trong bản phát hành (người dùng không chia sẻ đĩa gốc) → chỉ có thể là công cụ người chơi tự chạy trên máy
mình sau khi có đĩa; chất lượng AI chung chung kém xa dự án cộng đồng đã tách lớp/sửa tay. Không khuyến nghị lúc này.

**Kết luận**: "bản SC đã upscale" hiện chỉ có nghĩa là **3D vẽ ở độ phân giải cao** (đã có sẵn trong gói v0.2). Ảnh nền/texture HD
phải chờ gói của Upscale Project (khi ra, gói Việt hoá cài kèm được vì SC nạp qua sự kiện mod).

## 2. Làm bản Android được không?

SC đã có sẵn nhiều thứ thuận lợi:
- Cửa sổ/nhập liệu qua **SDL3** (`lwjgl-sdl 3.4.3`, `legend.core.platform.SdlWindow`) — SDL3 chạy được trên Android (có sẵn
  `SDLActivity`).
- Khi không có OpenGL 3.3, SC tự dùng **OpenGL ES 3.2** (`GlesApi`) — đa số điện thoại Adreno 6xx+/Mali-G7x+/Xclipse có.
- Phim dùng FFmpeg qua JavaCPP (bytedeco `ffmpeg 8.0.1-1.5.13`) — bytedeco có bản `android-arm64`.
- Đĩa chỉ cần lúc giải nén lần đầu (`Unpacker` đọc thư mục `isos`), sau đó SC chạy từ `files/` (1,39 GB).

Phần phải tự làm:

| Việc | Ghi chú |
|---|---|
| Máy ảo Java trên Android | SC là Java 25. ART của Android không chạy thẳng được (thiếu `java.net.http`, một phần NIO/thread…). Hướng chắc ăn: **chở OpenJDK dựng cho Android arm64** trong APK và khởi chạy bằng JNI (cách PojavLauncher/Amethyst chạy Minecraft Java). |
| LWJGL cho Android | LWJGL không phát hành bản Android: tự dựng `liblwjgl`, `lwjgl_opengles`, `lwjgl_stb`, `lwjgl_sdl` (+ SDL3), OpenAL Soft, Opus bằng NDK (arm64-v8a). Bỏ JavaFX (chỉ dùng cho debugger), Discord SDK, assimp/shaderc/spvc nếu SC không gọi trên đường GLES. |
| Chọn đĩa lần đầu | Màn hình Android riêng: người chơi chọn 4 file `.bin` gốc bằng trình chọn tệp của Android (SAF, không cần quyền bộ nhớ), app đọc trực tiếp qua `/proc/self/fd/<fd>` hoặc chép tạm vào bộ nhớ riêng của app → SC giải nén → xoá bản chép. Không chở dữ liệu Sony nào trong APK. |
| Điều khiển cảm ứng | SC hỗ trợ tay cầm và bàn phím; điện thoại cần **lớp phím ảo** (D-pad, ○ × △ □, L1/R1, Start/Select) phát sự kiện tay cầm SDL. Tay cầm Bluetooth dùng được sẵn. |
| Dung lượng | APK ~250–350 MB (JRE ~120 MB + SC + thư viện + bản Việt), sau giải nén thêm 1,4 GB; lúc giải nén cần thêm chỗ nếu phải chép đĩa (~2,8 GB). |
| Hiệu năng | `launch.bat` không đặt `-Xmx` (Java tự lấy tối đa 1/4 RAM); cần đo mức dùng thật. Tạm nhắm máy ≥ 6 GB RAM, Android 10+, arm64, GLES 3.2. |
| Bản Việt | Gói chung `sc-vi.jar` + lang + font + `vi/files` như bản Windows; ghim cùng commit SC `affcef0`. |
| Giấy phép | SC là AGPL-3.0 → APK phải kèm/công bố mã nguồn phần sửa (đã có repo). Không kèm đĩa/BIOS. |

Khối lượng: lớn (nhiều phiên làm việc): dựng LWJGL+SDL3+OpenAL cho Android, JRE Android, app khởi chạy, màn chọn đĩa, phím ảo,
thử trên máy thật.

## 3. Cần có trước khi bắt đầu

- **Tải về** (cần bạn đồng ý, ~3–4 GB sau cài): Android NDK (~2 GB), CMake/Ninja của SDK, bản OpenJDK cho Android arm64,
  mã nguồn LWJGL 3.4.3, SDL3, OpenAL Soft; Gradle. Máy đã có Android SDK (platform 36, build-tools 36.1, adb) — chưa có NDK.
- **Dung lượng trống**: C: 19 GB, D: 13 GB — đủ nhưng sát; giả lập Android (thêm ~5 GB) chỉ nên dùng nếu không có máy thật.
- **Máy Android để thử** (khuyến nghị): bật Tuỳ chọn nhà phát triển → Gỡ lỗi USB, cắm vào máy này (`adb devices` hiện chưa thấy
  máy nào). Giả lập x86_64 trên Windows chạy GLES qua GPU máy tính được nhưng khác máy thật (phải dựng thêm thư viện x86_64).
