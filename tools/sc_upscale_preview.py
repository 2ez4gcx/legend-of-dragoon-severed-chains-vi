"""sc_upscale_preview.py — ghép ảnh xem trước: ảnh nền gốc (như SC đang hiện) cạnh ảnh upscale AI.

Cách gọi:
  python tools/sc_upscale_preview.py <thư mục goc> <thư mục ai> <ảnh ra.png> DRGN21_25:200,190 DRGN21_37:250,230
    mỗi tham số = <cảnh>:<x>,<y> là tâm vùng phóng to (toạ độ ảnh gốc)
  [--models=realesrgan-x4plus:Nhãn,seedvr2:Nhãn,...]   mô hình ở hàng 2 (mặc định 3 mô hình Real-ESRGAN), tên = <ai>/<cảnh>_<tên>.png
  [--full=seedvr2]                                     mô hình hiện cả cảnh ở hàng 1 (mặc định mô hình đầu)
Đầu vào: <goc>/<cảnh>_rgb.png (tools/sc_bgdump), <ai>/<cảnh>_<mô hình>.png (Real-ESRGAN ncnn-vulkan, x4).
Hàng 1: cả cảnh, SC hiện nay (phóng to kiểu nearest, giữ ô điểm ảnh) | Real-ESRGAN x4plus. Hàng 2: vùng phóng to 4x của gốc
và 3 mô hình. (SC affcef0 dựng texture nền bằng Texture.create không bật minFilter/magFilter = GL_NEAREST; đã đối chiếu ảnh
chụp trong game 18/10.)
Ảnh suy ra từ đĩa gốc: chỉ để xem trên máy, không commit, không phát hành.
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFont

MODELS = [('realesrgan-x4plus', 'AI: Real-ESRGAN x4plus'),
          ('realesrgan-x4plus-anime', 'AI: x4plus-anime'),
          ('realesr-animevideov3-x4', 'AI: animevideov3')]
FONT = ImageFont.truetype(os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts', 'segoeui.ttf'), 22)
FONT_B = ImageFont.truetype(os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts', 'segoeuib.ttf'), 26)
PAD, LABEL, CROP = 12, 34, 400  # CROP: cạnh vùng phóng to ở tỉ lệ 4x (= 100 px ảnh gốc)


def panel(img, text):
    p = Image.new('RGB', (img.width, img.height + LABEL), (24, 24, 24))
    p.paste(img, (0, LABEL))
    ImageDraw.Draw(p).text((6, 4), text, font=FONT, fill=(255, 230, 120))
    return p


def scene(goc_dir, ai_dir, name, cx, cy, models=MODELS, full=None):
    orig = Image.open(os.path.join(goc_dir, name + '_rgb.png')).convert('RGB')
    w, h = orig.size
    smooth = orig.resize((w * 4, h * 4), Image.NEAREST)   # SC: texture nền GL_NEAREST (ô điểm ảnh to)
    ai = {m: Image.open(os.path.join(ai_dir, '%s_%s.png' % (name, m))).convert('RGB') for m, _ in models}
    full = full or models[0][0]
    labels = dict(models)

    full_w = 760
    full_h = round(h * 4 * full_w / (w * 4))
    row1 = [panel(smooth.resize((full_w, full_h), Image.LANCZOS), 'Hiện nay (ảnh gốc, ô điểm ảnh)'),
            panel(ai[full].resize((full_w, full_h), Image.LANCZOS), labels[full])]

    x0 = max(0, min(w * 4 - CROP, cx * 4 - CROP // 2))
    y0 = max(0, min(h * 4 - CROP, cy * 4 - CROP // 2))
    box = (x0, y0, x0 + CROP, y0 + CROP)
    row2 = [panel(smooth.crop(box), 'Phóng to 4x: hiện nay')] + [panel(ai[m].crop(box), t) for m, t in models]

    width = max(sum(p.width for p in row1) + PAD * (len(row1) - 1), sum(p.width for p in row2) + PAD * (len(row2) - 1))
    title_h = 40
    out = Image.new('RGB', (width + PAD * 2, title_h + row1[0].height + row2[0].height + PAD * 3), (40, 40, 40))
    d = ImageDraw.Draw(out)
    d.text((PAD, 6), 'Cảnh %s — ảnh gốc %dx%d, AI x4 = %dx%d' % (name.replace('_', '/'), w, h, w * 4, h * 4), font=FONT_B, fill=(255, 255, 255))
    x = PAD
    for p in row1:
        out.paste(p, (x, title_h))
        x += p.width + PAD
    # khung vùng phóng to trên ảnh cả cảnh
    s = full_w / (w * 4)
    for i in range(2):
        bx = PAD + i * (full_w + PAD)
        d.rectangle((bx + x0 * s, title_h + LABEL + y0 * s, bx + (x0 + CROP) * s, title_h + LABEL + (y0 + CROP) * s), outline=(255, 80, 80), width=2)
    x = PAD
    y = title_h + row1[0].height + PAD
    for p in row2:
        out.paste(p, (x, y))
        x += p.width + PAD
    return out


def main():
    opts = {a.split('=', 1)[0]: a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--')}
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    goc_dir, ai_dir, out_path = args[:3]
    models = MODELS
    if '--models' in opts:
        models = [tuple(m.split(':', 1)) if ':' in m else (m, 'AI: ' + m) for m in opts['--models'].split(',')]
    sheets = []
    for arg in args[3:]:
        name, xy = arg.split(':')
        cx, cy = (int(v) for v in xy.split(','))
        sheets.append(scene(goc_dir, ai_dir, name, cx, cy, models, opts.get('--full')))
    width = max(s.width for s in sheets)
    out = Image.new('RGB', (width, sum(s.height for s in sheets)), (40, 40, 40))
    y = 0
    for s in sheets:
        out.paste(s, (0, y))
        y += s.height
    out.save(out_path)
    print(out_path, out.size)


if __name__ == '__main__':
    main()
