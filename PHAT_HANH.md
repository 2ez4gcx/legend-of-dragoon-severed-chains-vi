# Phát hành bản tiếng Việt cho Severed Chains

Người dùng chốt (16/10/2026): **tự phát hành** bản sửa kèm (jar + lang + font + launcher), mã nguồn công khai theo AGPL-3.0,
**ghim theo commit SC**. Chưa tạo repo/chưa đưa lên mạng — chờ người dùng bảo.

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
- Không tắt được kiểm tra cập nhật mà không sửa thêm mã SC (chỉ bỏ qua khi `Version.TIMESTAMP == null`) → hướng dẫn dặn
  "đừng bấm Update".

## Nội dung gói `release/LoD-SC-VN-v<ver>-sc-affcef0-windows.zip`

```
Severed Chains (VN)/
  (nguyên bản build SC affcef0: launch.bat, lod-game-*.jar, -sources.jar, libs/, gfx/, lang/, patches/, updater.jar…)
  launch-vi.bat            sinh từ launch.bat: chcp 65001, kiểm jar đúng commit + vi\sc-vi.jar, tải JDK 25 y như bản gốc,
                           classpath "vi/sc-vi.jar;<classpath gốc>"
  config.dcnf              2 mục: lod_core:language = vi, lod_core:retail_font = vietnamese.json (mục khác SC tự đặt)
  HUONG_DAN_VIET_HOA.txt   hướng dẫn tiếng Việt (UTF-8 BOM)
  lang/lod.vi.lang, lang/core.vi.lang, lang/dialogue.vi.tsv
  gfx/fonts/vietnamese.json, vietnamese.png
  vi/sc-vi.jar, vi/VERSION.txt, vi/LICENSE, vi/NGUON/…
```

Không chứa: ảnh đĩa, BIOS, JDK, `files/`.

## Dựng gói

```bash
python tools/make_release.py --version 0.1
```

- Kiểm SHA-256 zip SC, kiểm clone `Severed-Chains/` đúng commit, xuất **HEAD** của repo này bằng `git archive` (không gom thay đổi
  chưa commit), chạy `tools/build_sc_vi.ps1` (sinh lang/thoại/font, biên dịch JDK 25, tự kiểm `TagRoundTrip` phải 0 lỗi),
  đóng `vi/sc-vi.jar` bằng zipfile thời gian cố định, ghi zip theo thứ tự cố định, cập nhật `release/SHA256SUMS.txt`.
- **Xác định**: dựng 2 lần liên tiếp ra cùng SHA-256.

## Đã kiểm (v0.1)

| Kiểm | Kết quả |
|---|---|
| Dựng 2 lần | cùng SHA-256 `fb3e16668a4aef9aa5ecface64bda845ead7902898e93be8c9c9bf3cb8c9f13f` (132,4 MB) |
| `config.dcnf` tự tạo | 2 bản ghi trùng từng byte với bản ghi SC tự lưu khi chọn tiếng Việt + font Việt |
| `launch-vi.bat` khi thiếu jar đúng commit | in thông báo tiếng Việt đúng dấu, thoát mã 1 |
| Cài sạch từ zip (giải nén, hard link 4 đĩa gốc, chạy `launch-vi.bat`) | xem mục dưới |

## Đổi sang commit SC mới (khi cần)

1. `git -C Severed-Chains fetch && git checkout <commit>`; tải `Severed_Chains_Windows.zip` của devbuild **cùng commit** (tên jar
   trong zip phải là `lod-game-<commit>.jar`).
2. Áp lại `sc-vi/patches/sc-core-affcef0.diff` lên `Text.java`, `SMap.java`, `LodString.java` mới (chép sang `sc-vi/src`), sửa
   xung đột nếu có, tạo diff mới `sc-core-<commit7>.diff`.
3. Cập nhật `SC_COMMIT`, `SC_ZIP_SHA` trong `tools/make_release.py` và tên jar trong `tools/build_sc_vi.ps1`.
4. Dựng, chạy tự kiểm, chơi thử lại các cảnh mẫu, tăng phiên bản Việt hoá.

## Việc còn lại trước khi phát hành công khai

- Chạy thử bản cài sạch đến lời thoại đầu (đang chờ phiên kiểm thử kia rảnh màn hình).
- Gom các sửa lỗi của phiên kiểm thử (trận đánh, hộp chọn, cửa hàng…) rồi dựng lại.
- Hỏi người dùng: tạo repo GitHub (private, tự bật public) cho mã nguồn + đưa zip lên mục Releases (zip 132 MB vượt giới hạn
  100 MB/file của git thường → dùng Releases), tên repo, số phiên bản, có kèm bản Linux/Mac không (gói hiện chỉ Windows).
