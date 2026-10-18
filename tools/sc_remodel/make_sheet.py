"""make_sheet.py — ghép tờ so sánh "gốc | remaster" (nhãn tiếng Việt) từ ảnh dựng của remaster.py.

Cách gọi (từ thư mục gốc repo):
  python tools/sc_remodel/make_sheet.py [--out work/upscale/remodel/dart_remaster_sosanh.png] [--h 720]
      [--rows dart_battle:full34,dart_battle:closeup,dart_battle:back34,dart_battle:face,dart_field:full34,dart_field:closeup]
Đầu vào: work/upscale/remodel/<mô hình>/remaster/<view>_goc.png, <view>_remaster.png (RGBA nền trong suốt),
         .../remaster/report.json (số tam giác, thời gian, texture), <mô hình>/<mô hình>.json (nguồn, kích thước atlas).
Ra: một PNG nền xám trung tính (128), mỗi hàng = một góc nhìn: ảnh gốc | ảnh remaster cùng máy quay, cao --h px.
Kiểm: thiếu ảnh -> báo lỗi, exit 1. Ảnh suy ra từ dữ liệu Sony: chỉ xem trên máy, không commit, không phát hành.
"""
import argparse
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
REMODEL = os.path.join(ROOT, 'work', 'upscale', 'remodel')
FONTS = os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts')
VIEW_VI = {'full34': 'toàn thân, 3/4 trước', 'closeup': 'nửa người trên', 'back34': 'toàn thân, 3/4 sau', 'face': 'mặt',
           'front': 'chính diện'}
KIND_VI = {'battle': 'Chiến đấu', 'field': 'Bản đồ'}
BG = (128, 128, 128)


def rel(p):
    """Đường dẫn để in: tương đối theo gốc repo, khác ổ đĩa thì tuyệt đối (os.path.relpath ném ValueError)."""
    try:
        return os.path.relpath(p, ROOT)
    except ValueError:
        return os.path.abspath(p)


def tex_info(d, model, W_at, H_at):
    """Texture remaster thật sự đã dùng: tên mô hình upscale (upscale_atlas.py ghi 'picked') + kích thước file x4."""
    picked = None
    try:
        picked = json.load(open(os.path.join(d, model + '_atlas_x4.json'), encoding='utf-8')).get('picked')
    except (OSError, ValueError):
        pass
    p = os.path.join(d, model + '_atlas_x4.png')
    if not os.path.isfile(p):
        return 'texture gốc %d×%d (chưa upscale)' % (W_at, H_at)
    with Image.open(p) as im:
        w, h = im.size
    return 'texture %d×%d (%s)' % (w, h, picked or 'upscale không rõ mô hình')


def font(bold, size):
    return ImageFont.truetype(os.path.join(FONTS, 'segoeuib.ttf' if bold else 'segoeui.ttf'), size)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(REMODEL, 'dart_remaster_sosanh.png'))
    ap.add_argument('--h', type=int, default=720)
    ap.add_argument('--rows', default='dart_battle:full34,dart_battle:closeup,dart_battle:back34,dart_battle:face,'
                                      'dart_field:full34,dart_field:closeup')
    a = ap.parse_args()
    rows, errors = [], []
    info = {}
    for item in a.rows.split(','):
        model, view = item.split(':')
        d = os.path.join(REMODEL, model)
        if model not in info:
            try:
                rep = json.load(open(os.path.join(d, 'remaster', 'report.json'), encoding='utf-8'))
                doc = json.load(open(os.path.join(d, model + '.json'), encoding='utf-8'))
                info[model] = (rep, doc)
            except OSError as e:
                errors.append('thieu report/json cua %s: %s' % (model, e))
                continue
        pics = []
        for tag in ('goc', 'remaster'):
            p = os.path.join(d, 'remaster', '%s_%s.png' % (view, tag))
            if not os.path.isfile(p):
                errors.append('thieu ' + rel(p))
                break
            im = Image.open(p).convert('RGBA')
            bg = Image.new('RGBA', im.size, BG + (255,))
            bg.alpha_composite(im)
            s = a.h / bg.height
            pics.append(bg.convert('RGB').resize((round(bg.width * s), a.h), Image.LANCZOS))
        if len(pics) == 2:
            rows.append((model, view, pics))
    if errors:
        for e in errors:
            print('LOI:', e)
        sys.exit(1)
    f_title, f_head, f_row, f_small = font(True, 30), font(True, 21), font(True, 22), font(False, 19)
    gap, label_h = 10, 40
    colw = max(max(p[0].width, p[1].width) for _, _, p in rows)
    W = 2 * colw + 3 * gap
    probe = ImageDraw.Draw(Image.new('RGB', (8, 8)))
    head = []
    for model, (rep, doc) in info.items():
        W_at, H_at = doc['atlas_size']
        sec = rep.get('seconds', {})
        rend = rep.get('render_seconds', {})
        nrem = [v for k, v in rend.items() if k.endswith('_remaster')]
        engine = 'Cycles' if rep.get('args', {}).get('engine') == 'cycles' else 'Eevee'
        head.append('%s (%s, %d phần): gốc %d tam giác, texture %d×%d — remaster %d tam giác, %s; dựng lưới %.1f s, ảnh %s %.1f s/góc.'
                    % (KIND_VI.get(doc['kind'], doc['kind']), doc['source']['model'], len(doc['parts']), rep['tris_goc'], W_at, H_at,
                       rep['tris_remaster'], tex_info(os.path.join(REMODEL, model), model, W_at, H_at),
                       sec.get('remaster_build_total', 0), engine, sum(nrem) / max(1, len(nrem))))
    args = next(iter(info.values()))[0].get('args', {}) if info else {}
    hard = 'bevel' if args.get('hardmode') == 'bevel' else 'crease'
    vol = 'tắt giữ thể tích' if args.get('inflate', -1) == 0 else 'giữ thể tích từng phần'
    head.append('Cùng máy quay, cùng 3 đèn. Gốc = lưới TMD như SC (pháp tuyến Gouraud, texture nearest). Remaster = Catmull-Clark '
                '%d cấp + %s theo cạnh cứng của TMD + %s + texture x4 lọc tuyến tính; pivot/thứ tự phần giữ nguyên.'
                % (args.get('levels', 2), hard, vol))
    lines = []
    for para in head:
        cur = ''
        for word in para.split(' '):
            t = (cur + ' ' + word).strip()
            if probe.textlength(t, font=f_small) > W - 2 * gap and cur:
                lines.append(cur); cur = word
            else:
                cur = t
        lines.append(cur)
    head_h = 56 + 25 * len(lines) + 14
    H = head_h + sum(label_h + a.h + gap for _ in rows) + gap
    sheet = Image.new('RGB', (W, H), (40, 40, 40))
    dr = ImageDraw.Draw(sheet)
    dr.text((gap, 10), 'Dart — thử "remaster tự động" bằng Blender 5.2 (hướng B, chỉ xem trên máy)', font=f_title, fill=(255, 235, 150))
    for k, ln in enumerate(lines):
        dr.text((gap, 56 + 25 * k), ln, font=f_small, fill=(220, 220, 220))
    y = head_h
    for model, view, (g, r) in rows:
        rep, doc = info[model]
        dr.text((gap, y + 6), '%s — %s' % (KIND_VI.get(doc['kind'], doc['kind']), VIEW_VI.get(view, view)), font=f_row,
                fill=(255, 235, 150))
        y += label_h
        for k, (im, lab) in enumerate(((g, 'GỐC (PS1/SC)'), (r, 'REMASTER (Blender)'))):
            x0 = gap + k * (colw + gap)
            sheet.paste(Image.new('RGB', (colw, a.h), BG), (x0, y))
            sheet.paste(im, (x0 + (colw - im.width) // 2, y))
            tw = dr.textlength(lab, font=f_head)
            dr.rectangle((x0 + 8, y + 8, x0 + 20 + tw, y + 40), fill=(30, 30, 30))
            dr.text((x0 + 14, y + 10), lab, font=f_head, fill=(255, 255, 255))
        y += a.h + gap
    sheet.save(a.out)
    print('to so sanh: %s (%dx%d, %d hang)' % (rel(a.out), W, H, len(rows)))


if __name__ == '__main__':
    main()
