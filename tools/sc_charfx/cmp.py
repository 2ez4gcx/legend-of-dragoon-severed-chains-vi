"""cmp.py — so hai ảnh chụp từng điểm ảnh (RGB), vẽ mặt nạ chỗ đổi; ghép nhiều ảnh thành một tờ có nhãn.

Cách gọi:
  python tools/sc_charfx/cmp.py A.png B.png [--mask ra.png]
      in "identical" hoặc "diff <n> px bbox (x0,y0,x1,y1) max <m>"; --mask ghi ảnh A tối còn 35% với điểm ảnh đổi tô đỏ
      (độ đỏ = chênh lệch x 8) để thấy NGAY bộ shader chạm vào vật nào (đúng ra chỉ nhân vật/mô hình TMD).
      Exit 0 = giống hệt, 2 = khác, 1 = lỗi (khác kích thước, thiếu file).
  python tools/sc_charfx/cmp.py --sheet ra.png A.png B.png [C.png ...] [--cols 3] [--scale 0.5]
      ghép các ảnh thành lưới, nhãn = tên file (bỏ .png). Exit 0.
Ảnh chụp trong game có nền suy ra từ đĩa gốc (dữ liệu Sony): chỉ để trong work/upscale/ (không commit).
"""
import os
import sys

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont


def compare(a_path, b_path, mask=None):
    a = Image.open(a_path).convert('RGB')
    b = Image.open(b_path).convert('RGB')
    if a.size != b.size:
        print('size differs', a.size, b.size)
        return 1
    d = ImageChops.difference(a, b)
    bbox = d.getbbox()
    g = d.convert('L')
    hist = g.histogram()
    if mask:
        base = a.point(lambda v: int(v * 0.35))
        red = Image.merge('RGB', (g.point(lambda v: min(255, v * 8)), Image.new('L', a.size, 0), Image.new('L', a.size, 0)))
        ImageChops.add(base, red).save(mask)
    if bbox is None:
        print('identical')
        return 0
    # a pixel differs if any channel differs (the L histogram can round a 1-level change in one channel to 0)
    n = int(np.count_nonzero(np.asarray(d).any(axis=2)))
    mx = max((i for i, c in enumerate(hist) if c), default=0)
    print('diff %d px bbox %s max %d' % (n, bbox, mx))
    return 2


def font(size):
    for name in ('segoeui.ttf', 'arial.ttf'):
        try:
            return ImageFont.truetype(os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts', name), size)
        except OSError:
            pass
    return ImageFont.load_default()


def sheet(out, paths, cols=3, scale=0.5):
    imgs = [Image.open(p).convert('RGB') for p in paths]
    w = int(imgs[0].width * scale)
    h = int(imgs[0].height * scale)
    label = 30
    cols = max(1, min(cols, len(imgs)))
    rows = (len(imgs) + cols - 1) // cols
    canvas = Image.new('RGB', (cols * (w + 8) + 8, rows * (h + label + 8) + 8), (32, 32, 32))
    d = ImageDraw.Draw(canvas)
    f = font(20)
    for i, (p, img) in enumerate(zip(paths, imgs)):
        x = 8 + (i % cols) * (w + 8)
        y = 8 + (i // cols) * (h + label + 8)
        d.text((x + 4, y + 2), os.path.splitext(os.path.basename(p))[0], font=f, fill=(255, 230, 120))
        canvas.paste(img.resize((w, h), Image.LANCZOS), (x, y + label))
    canvas.save(out)
    print('sheet', out, canvas.size)
    return 0


def main(argv):
    try:
        if argv[:1] == ['--sheet']:
            args = list(argv[1:])
            cols, scale = 3, 0.5
            if '--cols' in args:
                i = args.index('--cols')
                cols = int(args[i + 1])
                del args[i:i + 2]
            if '--scale' in args:
                i = args.index('--scale')
                scale = float(args[i + 1])
                del args[i:i + 2]
            if len(args) < 2:
                print(__doc__)
                return 1
            return sheet(args[0], args[1:], cols, scale)
        if len(argv) < 2:
            print(__doc__)
            return 1
        mask = argv[argv.index('--mask') + 1] if '--mask' in argv else None
        return compare(argv[0], argv[1], mask)
    except (OSError, ValueError, IndexError) as e:
        print('LOI:', e)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
