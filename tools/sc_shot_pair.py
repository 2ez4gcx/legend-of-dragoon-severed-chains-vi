"""sc_shot_pair.py — ghép ảnh chụp trong game "gốc | HD" cạnh nhau, kèm vùng cắt 1:1 để xem độ nét thật.

Cách gọi:
  python tools/sc_shot_pair.py <ảnh ra.png> "<tiêu đề>|<gốc.png>|<hd.png>|x,y,w,h" ["<tiêu đề 2>|..."]
    x,y,w,h = vùng cắt (toạ độ ảnh chụp), hiện ở tỉ lệ 1:1 (không co giãn) bên dưới hai ảnh toàn màn hình (thu 50%).
  Nhiều bản: "<tiêu đề>|<nhãn 1>=<ảnh 1>|<nhãn 2>=<ảnh 2>|...|x,y,w,h" (ảnh đầu là gốc).
Ảnh chụp từ tools/sc_ui.ps1 -Shot (cửa sổ 1280x960). Ảnh có nền suy ra từ đĩa gốc: chỉ xem trên máy, không commit.
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFont

FONTS = os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts')
FONT = ImageFont.truetype(os.path.join(FONTS, 'segoeui.ttf'), 22)
FONT_B = ImageFont.truetype(os.path.join(FONTS, 'segoeuib.ttf'), 26)
PAD, LABEL, TITLE = 12, 34, 40
BG, FG, ACCENT, BOX = (40, 40, 40), (255, 255, 255), (255, 230, 120), (255, 80, 80)


def labelled(img, text):
    p = Image.new('RGB', (img.width, img.height + LABEL), (24, 24, 24))
    p.paste(img, (0, LABEL))
    ImageDraw.Draw(p).text((6, 4), text, font=FONT, fill=ACCENT)
    return p


def block(title, shots, box):
    """shots = [(nhãn, đường dẫn), ...] — ảnh đầu là gốc."""
    imgs = [(label, Image.open(path).convert('RGB')) for label, path in shots]
    x, y, w, h = box
    half = (imgs[0][1].width // 2, imgs[0][1].height // 2)
    row1 = [labelled(img.resize(half, Image.LANCZOS), label) for label, img in imgs]
    crop = (x, y, x + w, y + h)
    row2 = [labelled(img.crop(crop), label + ' — khung đỏ, 1:1') for label, img in imgs]
    width = max(sum(p.width for p in row1), sum(p.width for p in row2)) + PAD
    out = Image.new('RGB', (width + PAD * 2, TITLE + row1[0].height + row2[0].height + PAD * 3), BG)
    d = ImageDraw.Draw(out)
    d.text((PAD, 6), title, font=FONT_B, fill=FG)
    for i, p in enumerate(row1):
        px = PAD + i * (row1[0].width + PAD)
        out.paste(p, (px, TITLE))
        d.rectangle((px + x // 2, TITLE + LABEL + y // 2, px + (x + w) // 2, TITLE + LABEL + (y + h) // 2), outline=BOX, width=2)
    y2 = TITLE + row1[0].height + PAD
    for i, p in enumerate(row2):
        out.paste(p, (PAD + i * (row2[0].width + PAD), y2))
    return out


def main():
    out_path = sys.argv[1]
    blocks = []
    for spec in sys.argv[2:]:
        parts = spec.split('|')
        title, box = parts[0], tuple(int(v) for v in parts[-1].split(','))
        if len(parts) == 4 and '=' not in parts[1]:   # dạng cũ: tiêu đề|gốc|hd|khung
            shots = [('Gốc (SC hiện nay)', parts[1]), ('Nền HD (AI x4plus)', parts[2])]
        else:                                          # dạng mới: tiêu đề|nhãn=ảnh|nhãn=ảnh|...|khung
            shots = [tuple(p.split('=', 1)) for p in parts[1:-1]]
        blocks.append(block(title, shots, box))
    width = max(b.width for b in blocks)
    out = Image.new('RGB', (width, sum(b.height for b in blocks)), BG)
    y = 0
    for b in blocks:
        out.paste(b, (0, y))
        y += b.height
    out.save(out_path)
    print(out_path, out.size)


if __name__ == '__main__':
    main()
