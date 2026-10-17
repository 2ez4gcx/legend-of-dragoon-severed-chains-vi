# LoD tiếng Việt cho Severed Chains

Bản dịch tiếng Việt The Legend of Dragoon (dự án `D:\LOD`, bản vá PS1) chạy trên
[Severed Chains](https://github.com/Legend-of-Dragoon-Modding/Severed-Chains) — bản port Java của LoD.
Gói cài cho người chơi: mục **Releases** của repo này (v0.1, v0.2 — ghim SC commit `affcef0`).

- **[NGHIEN_CUU.md](NGHIEN_CUU.md)**: kiến trúc chữ/font/mod của SC, đánh giá các hướng, bản thử, kế hoạch.
- **[PHAT_HANH.md](PHAT_HANH.md)**: nội dung gói, cách dựng (`python tools/make_release.py --version <ver>`), thử cài sạch
  (`tools/test_cai.ps1`), đổi sang commit SC mới.
- `release_notes/`: ghi chú từng bản phát hành. `docs/anh/`: ảnh chụp trong game.

Dựng bản thử (cần thư mục `game` = bản build SC devbuild commit `affcef0` + JDK 25, và `D:\LOD` cạnh thư mục này):

```bash
powershell -ExecutionPolicy Bypass -File tools/build_sc_vi.ps1
powershell -ExecutionPolicy Bypass -File tools/run_sc.ps1 -Install
```

Phần sửa mã SC (`sc-vi/`) phát sinh từ mã SC nên theo giấy phép AGPL-3.0 của SC.
