# LoD tiếng Việt cho Severed Chains (nghiên cứu + bản thử)

Thử đưa bản dịch tiếng Việt The Legend of Dragoon (dự án `D:\LOD`, bản vá PS1 v1.9) vào
[Severed Chains](https://github.com/Legend-of-Dragoon-Modding/Severed-Chains) — bản port Java của LoD.

Đọc **[NGHIEN_CUU.md](NGHIEN_CUU.md)**: kiến trúc chữ/font/mod của SC, đánh giá các hướng, bản thử, kế hoạch, câu hỏi cần chốt.

Phát hành (tự phát hành, ghim SC commit `affcef0`): **[PHAT_HANH.md](PHAT_HANH.md)** — `python tools/make_release.py --version 0.1`.

Dựng bản thử (cần thư mục `game` = bản build SC devbuild commit `affcef0` + JDK 25, và `D:\LOD` cạnh thư mục này):

```bash
powershell -ExecutionPolicy Bypass -File tools/build_sc_vi.ps1
```

Phần sửa mã SC (`sc-vi/`) phát sinh từ mã SC nên theo giấy phép AGPL-3.0 của SC.
