"""Vẽ lại ảnh menu màn tựa riêng của Severed Chains (gfx/ui/title_menu.png) bằng tiếng Việt.

Cách gọi:
    python tools/sc_title_menu.py   -> out/gfx/ui/title_menu.png + out/title_menu_preview.png (gốc | Việt, nền tối)
Ảnh gốc 1024x512 RGBA: hàng i (cao 64) = mục i; cột trái (x 0..511) chữ trắng sắc, cột phải (512..1023) bản làm mờ (phát sáng
khi được chọn); hàng 7 = biểu tượng (giữ nguyên).
Mục 0..4 (Ttle.java): quad đặt tại x = 184 - menuTextWidth[i]*scale/2 với menuTextWidth = {407, 257, 227, 189, 141} (bề rộng
chữ Anh, ghi cứng; = mép phải chữ + 17). Chữ Việt căn trái ở x = 16 như gốc, bề rộng mới ghi ra out/gfx/ui/title_menu.widths;
lớp HardcodedTranslations ghi bảng này vào Ttle.menuTextWidth (reflection) khi màn tựa hiện -> căn giữa đúng.
Mục 5, 6 (Convert Memcard / Update Available) căn trái ở x = 16 như gốc.
Chữ: Cambria (có đủ dấu tiếng Việt), chữ hoa cao bằng chữ gốc (29 px), vẽ ở 4x rồi thu nhỏ, viền mảnh cho nét đậm như gốc,
kéo giãn ngang theo hệ số đo từ "New Campaign" (chữ gốc là kiểu serif mặt rộng). Lớp phát sáng = làm mờ Gaussian chữ sắc với
bán kính và hệ số đo từ ảnh gốc (khớp bình phương nhỏ nhất).
"""
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SC = os.environ.get('SC_ROOT', os.path.join(ROOT, 'Severed-Chains'))
FONT = 'C:/Windows/Fonts/cambria.ttc'
WORDS = ['Lượt chơi mới', 'Chơi tiếp', 'Tùy chọn', 'Giới thiệu', 'Thoát', 'Chuyển thẻ nhớ', 'Có bản cập nhật']
MENU_TEXT_WIDTH = [407, 257, 227, 189, 141]   # Ttle.menuTextWidth (SC affcef0)
CAP = 29          # chiều cao chữ hoa gốc (px)
TOP = 16          # hàng đỉnh chữ hoa trong ô gốc
TRACK = 1         # giãn chữ (px, trước khi kéo ngang); 2 làm "Tùy chọn" rộng hơn ô "Options"
SS = 4            # vẽ ở 4x
STROKE = 2        # viền ở 4x (~0,5 px) cho nét đậm như gốc


def font_for_cap():
    for size in range(20, 120):
        f = ImageFont.truetype(FONT, size * SS)
        b = f.getbbox('N')
        if (b[3] - b[1]) >= CAP * SS:
            return f
    raise SystemExit('khong tim duoc co chu')


def render(text, f, k):
    """-> mảng alpha (float 0..1) [64+, w] với đỉnh chữ hoa ở hàng TOP"""
    w = int(sum(f.getlength(c) + TRACK * SS for c in text)) + 40 * SS
    im = Image.new('L', (w, 96 * SS), 0)
    d = ImageDraw.Draw(im)
    capb = f.getbbox('N')
    y0 = TOP * SS - capb[1] + 16 * SS
    x = 8 * SS
    for c in text:
        d.text((x, y0), c, font=f, fill=255, stroke_width=STROKE, stroke_fill=255)
        x += f.getlength(c) + TRACK * SS
    a = np.array(im)
    xs = np.where(a.max(0) > 0)[0]
    a = a[:, xs.min():xs.max() + 1]
    small = Image.fromarray(a).resize((max(1, round(a.shape[1] / SS * k)), a.shape[0] // SS), Image.LANCZOS)
    return np.array(small).astype(float)[16:16 + 64] / 255.0


def fit_glow(orig):
    """bán kính Gaussian và hệ số: glow ~ s * blur(crisp)"""
    best = None
    for r in [x / 2 for x in range(4, 25)]:
        num = den = 0.0
        for row in range(7):
            crisp = Image.fromarray((orig[row * 64:(row + 1) * 64, 0:512, 3]).astype(np.uint8))
            glow = orig[row * 64:(row + 1) * 64, 512:1024, 3].astype(float)
            b = np.array(crisp.filter(ImageFilter.GaussianBlur(r))).astype(float)
            num += (b * glow).sum()
            den += (b * b).sum()
        s = num / den
        err = 0.0
        for row in range(7):
            crisp = Image.fromarray((orig[row * 64:(row + 1) * 64, 0:512, 3]).astype(np.uint8))
            glow = orig[row * 64:(row + 1) * 64, 512:1024, 3].astype(float)
            b = np.array(crisp.filter(ImageFilter.GaussianBlur(r))).astype(float)
            err += ((s * b - glow) ** 2).sum()
        if best is None or err < best[0]:
            best = (err, r, s)
    return best[1], best[2]


def main():
    src = Image.open(os.path.join(SC, 'gfx', 'ui', 'title_menu.png')).convert('RGBA')
    orig = np.array(src)
    f = font_for_cap()
    ref = render('New Campaign', f, 1.0)
    ow = np.where(orig[0:64, 0:512, 3].max(0) > 40)[0]
    k = (ow.max() - ow.min() + 1) / ref.shape[1]
    r, s = fit_glow(orig)
    out = orig.copy()
    widths = []
    for row, text in enumerate(WORDS):
        a = render(text, f, k)
        w = a.shape[1]
        x0 = 16
        if x0 + w > 495:
            raise SystemExit('LOI: "%s" khong vua o (x %d, rong %d)' % (text, x0, w))
        cell = np.zeros((64, 512), float)
        cell[:, x0:x0 + w] = a[:64, :]
        crisp = np.clip(cell * 255, 0, 255).astype(np.uint8)
        glow = np.array(Image.fromarray(crisp).filter(ImageFilter.GaussianBlur(r))).astype(float) * s
        rows = slice(row * 64, (row + 1) * 64)
        out[rows, 0:512, 0:3] = 239
        out[rows, 0:512, 3] = crisp
        out[rows, 512:1024, 0:3] = 255
        out[rows, 512:1024, 3] = np.clip(glow, 0, 255).astype(np.uint8)
        if row < 5:
            widths.append(x0 + w + 17)   # như gốc: menuTextWidth = mép phải chữ + 17 (407 = 390 + 17 ...)
        print('%-16s rong %3d px' % (text, w))
    os.makedirs(os.path.join(ROOT, 'out', 'gfx', 'ui'), exist_ok=True)
    Image.fromarray(out).save(os.path.join(ROOT, 'out', 'gfx', 'ui', 'title_menu.png'))
    with open(os.path.join(ROOT, 'out', 'gfx', 'ui', 'title_menu.widths'), 'w', encoding='ascii', newline='\n') as fw:
        fw.write(','.join(str(x) for x in widths) + '\n')
    print('menuTextWidth tieng Viet: %s (goc %s)' % (widths, MENU_TEXT_WIDTH))
    print('he so keo ngang %.3f, phat sang: Gaussian r=%.1f x%.2f' % (k, r, s))

    def on_dark(a):
        im = Image.new('RGBA', (a.shape[1], a.shape[0]), (24, 20, 16, 255))
        im.alpha_composite(Image.fromarray(a))
        return im
    pa, pb = on_dark(orig[0:448]), on_dark(out[0:448])
    prev = Image.new('RGB', (pa.width, pa.height * 2 + 8), (80, 80, 80))
    prev.paste(pa.convert('RGB'), (0, 0))
    prev.paste(pb.convert('RGB'), (0, pa.height + 8))
    prev.save(os.path.join(ROOT, 'out', 'title_menu_preview.png'))
    print('xem truoc: out/title_menu_preview.png (tren: goc, duoi: tieng Viet)')


if __name__ == '__main__':
    main()
