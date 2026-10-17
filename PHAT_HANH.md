# Phát hành bản tiếng Việt cho Severed Chains

Người dùng chốt (16/10/2026): **tự phát hành** bản sửa kèm (jar + lang + font + launcher), mã nguồn công khai theo AGPL-3.0,
**ghim theo commit SC**. Repo private + Releases: xem mục Phát hành cuối tệp (v0.1 phát hành 17/10/2026).

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
  lang/dialogue.vi.tsv
  gfx/fonts/vietnamese.json, vietnamese.png
  gfx/ui/title_menu.vi.png, title_menu.vi.widths   menu màn tựa tiếng Việt (v0.2; tên riêng, không đè ảnh gốc của SC)
  vi/files/SECT/DRGN0.BIN/…   lớp phủ đồ hoạ (v0.2): ảnh đã duyệt của bản PS1 + dòng ghi công màn tựa ở hàng 209
                              (phương án B đã duyệt), Loader đọc thay files/ (52 file)
  vi/sc-vi.jar, vi/VERSION.txt, vi/LICENSE, vi/NGUON/…
```

Lớp sửa trong `vi/sc-vi.jar` (v0.2, 8 lớp, diff `sc-vi/patches/sc-core-affcef0.diff`): `LodString`, `Text`, `SMap`,
`ConfigStorage`, `Loader` (lớp phủ `vi/files`), `Updater` (tắt cập nhật) + lớp mới `ScriptTextTranslations`,
`HardcodedTranslations` (bảng viết cứng, câu viết thẳng, địa danh trên thẻ lưu cũ, ảnh menu màn tựa theo ngôn ngữ).

Không chứa: ảnh đĩa, BIOS, JDK, `files/`.

## Dựng gói

```bash
python tools/make_release.py --version 0.2
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

## Đã kiểm (v0.2 — bản dựng thử từ 375e2cd, chờ duyệt menu màn tựa / vị trí dòng ghi công)

| Kiểm | Kết quả |
|---|---|
| Tự kiểm khi dựng (`TagRoundTrip`) | 13.276 câu, 530 câu B0xx có bản nối dòng, 10 ca riêng, 0 lỗi |
| Dựng 2 lần | cùng SHA-256 `7a4bd19f…` |
| Nội dung gói | 51 file `vi/files`, `gfx/ui/title_menu.vi.png/.widths`, `gfx/ui/title_menu.png` giữ nguyên bản SC, 8 lớp sửa |
| Cài sạch `test_cai.ps1 -Choi` | lên màn tựa 107 s (gồm giải nén), classpath đúng, không lỗi trong log; menu tựa tiếng Việt, Tùy chọn, thoại mở đầu, menu "Chương 1: Chiến Sự Serdio", Vàng/Bụi Sao, vật phẩm (`docs/anh/31`) |
| Trong game (thư mục `game`) | menu tựa Việt → English → Việt, vào/ra Giới thiệu (`docs/anh/28`); thẻ lưu cũ "Chương 4: Trăng & Số Mệnh" (`29`); trận + màn kết quả (`30`) |

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

- Repo mã nguồn **private**: https://github.com/2ez4gcx/legend-of-dragoon-severed-chains-vi (tạo 16/10/2026 theo lời người
  dùng; người dùng tự bật public khi muốn). Gói zip (132 MB, quá 100 MB/file của git) đưa lên mục **Releases**, tag
  `v<ver>-sc-<commit7>`, đánh dấu pre-release khi còn thử nghiệm, kèm `SHA256SUMS.txt`. Sau khi tải lên: tải lại từ GitHub và so
  SHA-256 với bản đã kiểm.
- Chỉ có gói Windows (bản build SC Windows). Linux/Mac: cần zip SC tương ứng + launcher `.sh` — chưa làm.
