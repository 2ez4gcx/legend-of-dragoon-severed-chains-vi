"""Biểu tượng ứng dụng từ tranh chú rồng (android/icon_rong.webp, 1024x1024: tranh trong khung bo góc, viền sáng bên ngoài).

Cách gọi:  python android/gen_icon.py [--windows]
  -> out/gfx/textures/icon.vi.png                          biểu tượng cửa sổ game trên máy tính (64x64, bo góc); SdlWindow (sc-vi)
                                                           dùng thay gfx/textures/icon.png của SC; --windows: chỉ sinh tệp này
                                                           (build_sc_vi.ps1 gọi, make_release.py đưa vào gói)
     android/app/res/mipmap-*/ic_launcher.png             biểu tượng thường: tranh vuông bo góc, ngoài khung trong suốt
     android/app/res/mipmap-*/ic_launcher_foreground.png  biểu tượng thích ứng (Android 8+), lớp trước: tranh 72dp giữa lớp 108dp
     android/app/res/mipmap-*/ic_launcher_background.png  lớp sau: chính tranh đó phóng to, làm mờ (lộ ra khi launcher xê dịch lớp trước)
     android/app/res/mipmap-anydpi-v26/ic_launcher.xml    ghép hai lớp
     out/android/icon_preview.png                          xem thử: biểu tượng thường, mặt nạ tròn, mặt nạ bo góc
Launcher chỉ hiện vùng 72dp giữa lớp 108dp và cắt theo hình riêng của nó (tròn, bo góc...), nên tranh chiếm đúng vùng 72dp.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SRC = os.path.join(ROOT, 'android', 'icon_rong.webp')
# Phần trời bên trong khung (bỏ viền sáng và quầng ngoài); khung trong ảnh gốc là 91..933 x 91..949, hơi cao hơn rộng
ART = (99, 107, 924, 932)
CORNER = 0.2   # bán kính bo góc của khung trong ảnh gốc, tính theo cạnh
LEGACY = {'mdpi': 48, 'hdpi': 72, 'xhdpi': 96, 'xxhdpi': 144, 'xxxhdpi': 192}
WINDOW = 64   # Windows thu nhỏ cho thanh tiêu đề (16) và thanh tác vụ (24–48 tuỳ DPI)
ADAPTIVE_XML = '''<?xml version="1.0" encoding="utf-8"?>
<!-- Sinh bởi android/gen_icon.py -->
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@mipmap/ic_launcher_background" />
    <foreground android:drawable="@mipmap/ic_launcher_foreground" />
</adaptive-icon>
'''


def rounded(im, radius):
    mask = Image.new('L', im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius=radius, fill=255)
    out = im.convert('RGBA')
    out.putalpha(mask)
    return out


def layers(art, n):
    """Hai lớp n x n (n = 108dp): tranh 72dp ở giữa lớp trước, tranh phóng to làm mờ phủ kín lớp sau"""
    inner = round(n * 72 / 108)
    fg = Image.new('RGBA', (n, n), (0, 0, 0, 0))
    fg.paste(art.resize((inner, inner), Image.LANCZOS), ((n - inner) // 2, (n - inner) // 2))
    bg = art.resize((n, n), Image.LANCZOS).filter(ImageFilter.GaussianBlur(n / 24))
    return fg, bg


def masked(fg, bg, shape):
    n = fg.width
    inner = round(n * 72 / 108)
    off = (n - inner) // 2
    im = bg.convert('RGBA')
    im.alpha_composite(fg)
    im = im.crop((off, off, off + inner, off + inner))
    mask = Image.new('L', im.size, 0)
    d = ImageDraw.Draw(mask)
    if shape == 'circle':
        d.ellipse([0, 0, inner - 1, inner - 1], fill=255)
    else:
        d.rounded_rectangle([0, 0, inner - 1, inner - 1], radius=inner // 4, fill=255)
    im.putalpha(mask)
    return im


def main():
    art = Image.open(SRC).convert('RGB').crop(ART)
    legacy = rounded(art, round(art.width * CORNER))
    d = os.path.join(ROOT, 'out', 'gfx', 'textures')
    os.makedirs(d, exist_ok=True)
    legacy.resize((WINDOW, WINDOW), Image.LANCZOS).save(os.path.join(d, 'icon.vi.png'))
    if '--windows' in sys.argv[1:]:
        print('icon -> out/gfx/textures/icon.vi.png')
        return

    res = os.path.join(ROOT, 'android', 'app', 'res')
    for k, s in LEGACY.items():
        d = os.path.join(res, 'mipmap-' + k)
        os.makedirs(d, exist_ok=True)
        legacy.resize((s, s), Image.LANCZOS).save(os.path.join(d, 'ic_launcher.png'))
        fg, bg = layers(art, s * 108 // 48)
        fg.save(os.path.join(d, 'ic_launcher_foreground.png'))
        bg.save(os.path.join(d, 'ic_launcher_background.png'))
    d = os.path.join(res, 'mipmap-anydpi-v26')
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'ic_launcher.xml'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(ADAPTIVE_XML)

    fg, bg = layers(art, 432)
    tiles = [legacy.resize((288, 288), Image.LANCZOS), masked(fg, bg, 'circle'), masked(fg, bg, 'squircle')]
    preview = Image.new('RGBA', (3 * 320, 320), (40, 40, 48, 255))
    for i, t in enumerate(tiles):
        preview.alpha_composite(t.resize((288, 288), Image.LANCZOS), (i * 320 + 16, 16))
    os.makedirs(os.path.join(ROOT, 'out', 'android'), exist_ok=True)
    preview.save(os.path.join(ROOT, 'out', 'android', 'icon_preview.png'))
    print('icon -> out/gfx/textures/icon.vi.png, android/app/res/mipmap-* (thuong + thich ung), xem thu: out/android/icon_preview.png')


if __name__ == '__main__':
    main()
