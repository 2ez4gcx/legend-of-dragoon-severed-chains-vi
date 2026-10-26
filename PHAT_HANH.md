# Phát hành bản tiếng Việt cho Severed Chains

Người dùng chốt (16/10/2026): **tự phát hành** bản sửa kèm (jar + lang + font + launcher), mã nguồn công khai theo AGPL-3.0,
**ghim theo commit SC**. Repo public + Releases: xem mục Phát hành cuối tệp (v0.1 phát hành 17/10/2026).

## Vì sao gói phải kèm nguyên bản build SC

- GitHub của SC chỉ có bản `devbuild` cuốn chiếu (luôn là commit mới nhất) và `recommended-build-2.1` (cũ, 2025). Không có bản
  build theo từng commit → muốn ghim `affcef0` thì phải kèm bản build đó. Bản đã lưu: `dl/Severed_Chains_Windows.zip`,
  SHA-256 `88abbfb28492400168070fdc03ddfdff4b4e4781277d2de0195d17445bbf0800` (tải 16/10/2026, Last-Modified 14/10/2026,
  chứa `lod-game-affcef0cba71819515fdf05521c1fedb1d7a92f0.jar`).
- AGPL-3.0 cho phép phát hành lại bản build SC kèm mã nguồn: gói có sẵn `lod-game-<commit>-sources.jar` của SC, phần sửa của
  ta ở `vi/NGUON/` (lớp Java, diff so với SC, tự kiểm, công cụ sinh dữ liệu), bản giấy phép ở `vi/LICENSE`.

## Trình cập nhật của SC (đã đọc mã `UpdaterApplication.java`)

- Nút "Update Available" tải bản mới, chép đè, **xoá mọi `.jar` ở thư mục gốc không có trong bản mới** và jar lạ trong `libs/`.
  Giữ nguyên: `saves`, `mods`, `isos`, `files`, `jdk25`, `config.dcnf`, `launch.conf`, `updater.jar`.
- Vì vậy jar Việt hoá đặt ở `vi/sc-vi.jar` (không bị xoá), `launch-vi.bat` không có trong bản SC nên không bị đè;
  sau khi lỡ cập nhật, `launch-vi.bat` không thấy `lod-game-affcef0….jar` → báo tiếng Việt, không chạy lớp sửa trên mã SC khác.
- v0.1: hướng dẫn dặn "đừng bấm Update". Từ v0.2: ghi đè `legend.core.Updater` (`sc-vi/src/legend/core/Updater.java`,
  `check()` trả "không có bản mới" ngay) → nút "Update Available" không bao giờ hiện. Đã kiểm mã nguồn `Updater` gốc biên
  dịch ra trùng lớp trong jar affcef0 trước khi sửa.

## Nội dung gói `release/LoD-SC-VN-v<ver>-sc-affcef0-windows.zip`

```
Severed Chains (VN)/
  (nguyên bản build SC affcef0: launch.bat, lod-game-*.jar, -sources.jar, libs/, gfx/, lang/, patches/, updater.jar…)
  launch-vi.bat            sinh từ launch.bat: chcp 65001, kiểm jar đúng commit + vi\sc-vi.jar, tải JDK 25 y như bản gốc,
                           classpath "vi/sc-vi.jar;<classpath gốc>"
  config.dcnf              2 mục: lod_core:language = vi, lod_core:retail_font = vietnamese.json (mục khác SC tự đặt)
  HUONG_DAN_VIET_HOA.txt   hướng dẫn tiếng Việt (UTF-8 BOM)
  lang/lod.vi.lang, lang/scvi.vi.lang, lang/core.vi.lang, lang/unpacker.vi.lang, lang/turnorder.vi.lang,
  lang/scvi_ui.vi.lang (v0.3: mục Tốc độ game, Tự bỏ khung hình; KHÔNG kèm .en.lang vì bộ nạp SC gộp en sau vi),
  lang/dialogue.vi.tsv
  gfx/fonts/vietnamese.json, vietnamese.png
  gfx/ui/title_menu.vi.png, title_menu.vi.widths   menu màn tựa tiếng Việt (v0.2; tên riêng, không đè ảnh gốc của SC)
  vi/files/SECT/DRGN0.BIN/…   lớp phủ đồ hoạ (v0.2): ảnh đã duyệt của bản PS1 + dòng ghi công màn tựa ở hàng 209
                              (phương án B đã duyệt), Loader đọc thay files/ (52 file; từ v0.3: 54 file, thêm 4113/0 +
                              6666 = nhãn "Vàng"/"Vật phẩm" màn kết quả trận)
  vi/sc-vi.jar, vi/VERSION.txt, vi/LICENSE, vi/NGUON/…
```

Lớp sửa trong `vi/sc-vi.jar` (v0.2, 8 lớp, diff `sc-vi/patches/sc-core-affcef0.diff`): `LodString`, `Text`, `SMap`,
`ConfigStorage`, `Loader` (lớp phủ `vi/files`), `Updater` (tắt cập nhật) + lớp mới `ScriptTextTranslations`,
`HardcodedTranslations` (bảng viết cứng, câu viết thẳng, địa danh trên thẻ lưu cũ, ảnh menu màn tựa theo ngôn ngữ).
Từ v0.3 thêm `RenderEngine` (tự bỏ khung hình khi máy chậm), `CoreMod` (đăng ký 2 mục tùy chọn) + lớp mới
`GameSpeedConfigEntry`, `AutoFrameSkipConfigEntry`; `ConfigStorage` áp tốc độ sau khi nạp và (Android) hạ 720p một lần.
Sau v0.3 (chưa phát hành, 26/10): `RenderEngine` thêm mục "Tiết kiệm pin (30 khung/giây)" (lớp mới `BatterySaverConfigEntry`,
khoá `lod_core.config.battery_saver.*` trong `lang/scvi_ui.vi.lang`) và cho cửa sổ bỏ swap ở khung không vẽ; lớp sửa mới
`Gpu` (chỉ tải VRAM lên GPU ở khung có vẽ); lớp sửa mới `SdlWindow` (PC: chỉ swap khung có vẽ, không vẽ khi cửa sổ thu nhỏ,
biểu tượng cửa sổ `gfx/textures/icon.vi.png` = tranh chú rồng). Gói thêm `gfx/textures/icon.vi.png` (sinh bằng
`android/gen_icon.py --windows` trong `build_sc_vi.ps1`; `make_release.py` xuất thêm `android/gen_icon.py` + `icon_rong.webp`).
Đợt 2: `Gpu` chỉ tải phần VRAM đã đổi và chỉ duyệt ô có lệnh của bảng thứ tự; lớp sửa mới `ConfigCollection` (giá trị mặc định
chỉ tính khi thiếu — trước đây mỗi lần vẽ chữ duyệt thư mục `lang`) và `Spu` (chip âm thanh hiệu ứng nghỉ khi im lặng).

Không chứa: ảnh đĩa, BIOS, JDK, `files/`.

## Dựng gói

```bash
python tools/make_release.py --version 0.3
```

- Kiểm SHA-256 zip SC, kiểm clone `Severed-Chains/` đúng commit, xuất **HEAD** của repo này bằng `git archive` (không gom thay đổi
  chưa commit), chạy `tools/build_sc_vi.ps1` (sinh lang/thoại/font, biên dịch JDK 25, tự kiểm `TagRoundTrip` phải 0 lỗi),
  đóng `vi/sc-vi.jar` bằng zipfile thời gian cố định, ghi zip theo thứ tự cố định, cập nhật `release/SHA256SUMS.txt`.
- **Xác định**: dựng 2 lần liên tiếp ra cùng SHA-256.

## Đã kiểm (v0.1 — gói phát hành cuối cùng, dựng từ commit có `tools/test_cai.ps1`)

| Kiểm | Kết quả |
|---|---|
| Tự kiểm khi dựng (`TagRoundTrip`) | 13.276 câu (13.264 + 12 bí danh SC), 0 lỗi |
| Dựng 2 lần | cùng SHA-256 (giá trị trong `release/SHA256SUMS.txt` và trang Releases) |
| `config.dcnf` tự tạo | 2 bản ghi trùng từng byte với bản ghi SC tự lưu khi chọn tiếng Việt + font Việt |
| `launch-vi.bat` khi thiếu jar đúng commit | in thông báo tiếng Việt đúng dấu, thoát mã 1 |
| Cài sạch từ zip: `powershell -File tools/test_cai.ps1 -Zip <zip> -Choi` | giải nén vào thư mục trống, hard link 4 đĩa gốc, chạy đúng `launch-vi.bat` của gói: giải nén tài nguyên ~35 s, vá script không lỗi, classpath `vi/sc-vi.jar` đứng đầu; Tùy chọn hiện sẵn "Ngôn ngữ = Vietnamese", "Phông chữ = Tiếng Việt (pixel)" ngay lần chạy đầu; lời thoại mở đầu, menu trong game ("Dùng đồ", "Trạng thái"…), danh sách vật phẩm tiếng Việt (ảnh `docs/anh/22–24`) |

Lỗi tìm ra nhờ thử cài sạch và đã sửa trước khi phát hành:
- SC gốc nạp file ngôn ngữ trước khi đọc `config.dcnf` → menu màn tựa/Tùy chọn vẫn tiếng Anh tới khi bắt đầu chiến dịch.
  Sửa trong `sc-vi/src/legend/game/saves/ConfigStorage.java` (nạp lại ngôn ngữ sau khi đọc cấu hình chung).
- "Dùng vật phẩm" tràn ô menu trong game → "Dùng đồ".
- Công cụ: menu SC chọn mục theo vị trí chuột (con trỏ nằm trên "Quit" + Enter làm game thoát) → `sc_ui.ps1` dời chuột ra
  ngoài cửa sổ trước khi bấm phím; phim intro chỉ chạy khi cửa sổ ở trên cùng → `test_cai.ps1` tự đưa cửa sổ lên.

## Đã kiểm (v0.2 — gói phát hành, dựng từ adb4e65; người dùng duyệt menu màn tựa + dòng ghi công phương án B ngày 17/10)

| Kiểm | Kết quả |
|---|---|
| Tự kiểm khi dựng (`TagRoundTrip`) | 13.276 câu, 530 câu B0xx có bản nối dòng, 10 ca riêng, 0 lỗi |
| Dựng 2 lần | cùng SHA-256 `834384aa1f4f7bad4cea9dc85b47d8005b22a9932af73788394a1f1574a2c9d9` |
| Nội dung gói | 52 file `vi/files` (gồm nền màn tựa có dòng ghi công, trùng từng byte ảnh đã duyệt), `gfx/ui/title_menu.vi.png/.widths`, `gfx/ui/title_menu.png` giữ nguyên bản SC, 8 lớp sửa |
| Cài sạch `test_cai.ps1 -Choi` | lên màn tựa 114 s (gồm giải nén), classpath đúng, không lỗi trong log; menu tựa tiếng Việt + dòng ghi công, Tùy chọn, thoại mở đầu, menu "Chương 1: Chiến Sự Serdio", Vàng/Bụi Sao, vật phẩm (`docs/anh/31`) |
| Trong game (thư mục `game`) | menu tựa Việt → English → Việt, vào/ra Giới thiệu (`docs/anh/28`); thẻ lưu cũ "Chương 4: Trăng & Số Mệnh" (`29`); trận + màn kết quả (`30`) |

## Đã kiểm (v0.3 — gói phát hành 19/10/2026, dựng từ 2e8a8bc + D:\LOD main 40e91b8 = PS1 v1.12)

Gói thử ngày 17/10 (từ 60bc3ff, SHA `135fbb47…`) không phát hành; bản phát hành thêm tùy chọn Tốc độ game, Tự bỏ khung hình
(sửa chứng quay chậm), hướng dẫn trong gói có mục TỐC ĐỘ VÀ HIỆU NĂNG. Dữ liệu dịch như gói thử.

| Kiểm (19/10) | Kết quả |
|---|---|
| Dựng 2 lần (`LOD_ROOT` = bản sao nối tới D:\LOD, `LOD_COMMIT` = 40e91b8) | cùng SHA-256 `2e278f7951cfbbeee13332782c005aab612999a892877b4dea39501dbeb75d49` (132.904.722 byte); `vi/VERSION.txt` lod_sc_commit 2e8a8bc, lod_commit 40e91b8 |
| Cài sạch `test_cai.ps1 -Dia <game/isos> -Choi` | lên game 128 s, classpath `vi/sc-vi.jar` đầu, log không lỗi; kịch bản `-Choi` lệch nhịp (phím rơi vào màn tùy chọn lượt chơi mới) nên điều khiển tay tiếp: Lượt chơi mới → Bắt đầu → phim → "Rồng Nanh Xanh, Feyrbrand." |
| Tốc độ game (thư mục `game`) | Nhanh gấp 2: màn tựa 60/60 (30 Hz × 2), cảnh 120/120; giữ sau khi mở lại game; trợ giúp vừa khung (`docs/anh/38`) |
| Tự bỏ khung hình | PC giả lập `-Dscvi.fakeDrawMs=25`: tắt 35,6/60 FPS, bật 59,3/60 (log 130/300 khung không vẽ mỗi 5 s, `docs/anh/35`); máy thường chỉ bỏ 1–3 khung/5 s lúc nạp cảnh |
| APK x86_64 (giả lập Android 15) | log "Android: render resolution NATIVE -> 720p" một lần; ▶▶ đổi phim 15 → 30 FPS và trở lại; hộp ⚙ (độ đậm, cỡ phím, Mặc định) (`docs/anh/36–37`) |

Kiểm của gói thử 17/10 (dữ liệu dịch giống hệt):

Thay đổi so với v0.2 chỉ ở dữ liệu: `sc_dialogue.py` đã theo quy tắc `build.py` v1.11 từ 34abba5 (trước v0.2: `speaker_line`,
`clause_like`, `APPOS`, `vi_speakers`, bản nối dòng cho câu `{B0xx}` ≈ `reflow(force=True)`), nên dựng lại từ D:\LOD main mới chỉ
đổi **10 câu** trong `dialogue.vi.tsv` — đúng 10 câu sửa dịch của v1.11 (S02241 "Lối tắt", Gorgaga S03659–61 + S03664–66 "Chiến sĩ
cuồng nộ", S04523, S13479, S13651); `lod.vi.lang`/`scvi.vi.lang` trùng từng byte bản v0.2. Lớp phủ đồ hoạ thêm 4113/0 + 6666
(màn kết quả trận, b4d2f6c). Khác biệt cố ý còn lại với `vtext.reflow`: SC chỉ giữ dòng tên ở trang đầu (`not pages`), PS1 giữ dòng 1
của mọi trang khi câu có tên. S04096 (", q Greham…", tiền tố rác do lệnh trỏ lệch trong dump PS1) không bao giờ là khoá trong SC:
script SC đọc đúng "Greham{n}…" = khoá S04080 (vốn kiểu N).

| Kiểm | Kết quả |
|---|---|
| `build_sc_vi.ps1` + `TagRoundTrip` | 13.264 câu (N 7.166, J 2.399, L 3.317 [530 có bản nối dòng], C 382) + 12 bí danh SC = 13.276 câu, 10 ca riêng, 0 lỗi |
| Dựng 2 lần | cùng SHA-256 `135fbb473aff4c0c1b12b1f696302b278e51ba4395e61c4ceb53632c59273466` (132.837.512 byte) |
| Nội dung gói | `vi/VERSION.txt`: lod_commit 40e91b8, lod_sc_commit 60bc3ff; 54 file `vi/files` (gồm `4113/0`, `6666`); `lang/dialogue.vi.tsv` SHA `e03ae079…` (trùng bản dựng thường) |
| Trong game (thư mục `game`, save chương 4 LV31 + Debugger F12) | Donau cảnh 201: S12610 (NPC sobj 5, giai đoạn 2 = flags2 62, 66 bật / 6d tắt, flags1 c9 = 1) "Ước mơ của tôi là phủ xanh cả / Tiberoa giống như Donau. Người / ta có nói gì đi nữa, tôi cũng / sẽ làm được!" — hết chữ lẻ; S12641 (sobj 5, giai đoạn 6 = 62…8d bật / b5 tắt, c9 = 0) "Nghe nói nàng Công chúa Emille ngỗ ngược kia là / đồ giả mạo." — không còn bị coi là dòng tên; biển cảnh 133 (điểm 180,10,29 bán kính 30): S02241 "Trái: Lối tắt tới vùng Bale!"; trận 0 → màn kết quả "Vàng / EXP. / Vật phẩm" (`docs/anh/33`) |
| Chưa kiểm | Cài sạch `test_cai.ps1 -Choi` từ zip v0.3; trong game: Gorgaga (cảnh 638, chuỗi sự kiện Đại hội Lohan — warp vào chỉ thấy đấu trường trống), S04523 (trận), S13479/S13651 (cảnh cắt đĩa 3–4) |

Bẫy khi chạy từ xa: lúc người dùng nối Chrome Remote Desktop, cửa sổ ẩn của `remoting_desktop.exe` giữ quyền trên cùng, SC không lên
được (cả bấm chuột giả lập) → `sc_ui.ps1` huỷ đúng như thiết kế. SC bỏ phím khi không có keyboard focus (`SdlPlatformManager`:
sự kiện phím không có cửa sổ thì bỏ qua) nên `PostMessage` cũng không dùng được; chuột thì SC vẫn nhận. Chờ phiên từ xa ngắt là chạy lại được.

## Đổi sang commit SC mới (khi cần)

1. `git -C Severed-Chains fetch && git checkout <commit>`; tải `Severed_Chains_Windows.zip` của devbuild **cùng commit** (tên jar
   trong zip phải là `lod-game-<commit>.jar`).
2. Áp lại `sc-vi/patches/sc-core-affcef0.diff` lên `Text.java`, `SMap.java`, `LodString.java`, `ConfigStorage.java`,
   `Loader.java`, `Updater.java` mới (chép sang `sc-vi/src`), sửa xung đột nếu có, tạo diff mới `sc-core-<commit7>.diff`.
   Kiểm lại tên trường dùng qua reflection trong `HardcodedTranslations` (`Ttle.menuTextTex/menuTextWidth`,
   `BattleHud.targeting_800fb36c`, `Texture.deleted`) và các bảng viết cứng (`tools/sc_hardcoded.py`).
3. Cập nhật `SC_COMMIT`, `SC_ZIP_SHA` trong `tools/make_release.py` và tên jar trong `tools/build_sc_vi.ps1`.
4. Dựng, chạy tự kiểm, chơi thử lại các cảnh mẫu, tăng phiên bản Việt hoá.

## Phát hành

- Repo mã nguồn **public** từ 19/10/2026 theo lời người dùng: https://github.com/2ez4gcx/legend-of-dragoon-severed-chains-vi
  (tạo private 16/10/2026). Gói zip (132 MB, quá 100 MB/file của git) đưa lên mục **Releases**, tag
  `v<ver>-sc-<commit7>`, đánh dấu pre-release khi còn thử nghiệm, kèm `SHA256SUMS.txt`. Sau khi tải lên: tải lại từ GitHub và so
  SHA-256 với bản đã kiểm.
- Đã phát hành (pre-release): v0.1-sc-affcef0 (tag → 243d150, zip SHA `3eccc6c3…`), v0.2-sc-affcef0 (17/10/2026, tag → adb4e65,
  zip 132.807.079 byte, SHA `834384aa…`; tải lại từ GitHub khớp), v0.2-android-sc-affcef0 (19/10/2026, tag → 47bef50,
  APK arm64 200.075.870 byte, SHA `2f5e6f13…`, kèm `SHA256SUMS-android.txt`, ghi chú `release_notes/v0.2-android-sc-affcef0.md`;
  tải lại từ GitHub khớp; tải được khi không đăng nhập).
- v0.3-sc-affcef0 (19/10/2026, theo lời người dùng "Hãy phát hành v0.3"; tag → 2e8a8bc, zip 132.904.722 byte, SHA `2e278f79…`)
  và v0.3-android-sc-affcef0 (tag → 2e8a8bc, APK arm64 200.178.270 byte, SHA `d979c602…`, versionCode 3001, dựng từ zip v0.3;
  ghi chú `release_notes/v0.3-android-sc-affcef0.md`); cả hai tải lại từ GitHub khớp SHA-256, tải được khi không đăng nhập.
  Gắn tag vào commit đã dựng gói (dựng lại từ commit khác thì
  `lod_sc_commit` trong `vi/VERSION.txt` đổi → SHA đổi).
- Chỉ có gói Windows (bản build SC Windows). Linux/Mac: cần zip SC tương ứng + launcher `.sh` — chưa làm.
