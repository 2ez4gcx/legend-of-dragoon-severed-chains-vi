"""Vẽ biểu tượng ứng dụng (không dùng logo/thương hiệu của Sony): nền nâu đỏ bo góc, chữ "LoD" vàng, dải "VN".

Cách gọi:  python android/gen_icon.py   -> android/app/res/mipmap-*/ic_launcher.png + out/android/icon_preview.png
"""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SIZES = {'mdpi': 48, 'hdpi': 72, 'xhdpi': 96, 'xxhdpi': 144, 'xxxhdpi': 192}
SERIF = 'C:/Windows/Fonts/cambriab.ttf'
SANS = 'C:/Windows/Fonts/arialbd.ttf'


def draw(n=1024):
    im = Image.new('RGBA', (n, n), (0, 0, 0, 0))
    bg = Image.new('RGBA', (n, n))
    d = ImageDraw.Draw(bg)
    for y in range(n):
        t = y / n
        d.line([(0, y), (n, y)], fill=(int(120 - 70 * t), int(28 - 14 * t), int(18 - 8 * t), 255))
    mask = Image.new('L', (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, n - 1, n - 1], radius=n // 5, fill=255)
    im.paste(bg, (0, 0), mask)
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(SERIF, int(n * 0.40))
    w = d.textlength('LoD', font=f)
    glow = Image.new('RGBA', (n, n), (0, 0, 0, 0))
    ImageDraw.Draw(glow).text(((n - w) / 2, n * 0.18), 'LoD', font=f, fill=(255, 150, 40, 255))
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(n * 0.02)))
    d.text(((n - w) / 2, n * 0.18), 'LoD', font=f, fill=(255, 222, 140, 255))
    band = [n * 0.12, n * 0.70, n * 0.88, n * 0.86]
    d.rounded_rectangle(band, radius=n * 0.05, fill=(250, 214, 120, 255))
    g = ImageFont.truetype(SANS, int(n * 0.12))
    t = 'TIẾNG VIỆT'
    tw = d.textlength(t, font=g)
    d.text(((n - tw) / 2, n * 0.715), t, font=g, fill=(90, 20, 12, 255))
    return im


def main():
    big = draw()
    for k, s in SIZES.items():
        d = os.path.join(ROOT, 'android', 'app', 'res', 'mipmap-' + k)
        os.makedirs(d, exist_ok=True)
        big.resize((s, s), Image.LANCZOS).save(os.path.join(d, 'ic_launcher.png'))
    os.makedirs(os.path.join(ROOT, 'out', 'android'), exist_ok=True)
    big.resize((256, 256), Image.LANCZOS).save(os.path.join(ROOT, 'out', 'android', 'icon_preview.png'))
    print('icon -> android/app/res/mipmap-*')


if __name__ == '__main__':
    main()
