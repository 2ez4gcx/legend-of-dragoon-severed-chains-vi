"""upscale_atlas.py — phóng to 4x atlas texture của mô hình (đầu ra export_tmd.py) cho bản remaster, GIỮ NGUYÊN bố cục UV.

Cách gọi (từ thư mục gốc repo):
  python tools/sc_remodel/upscale_atlas.py work/upscale/remodel/dart_battle [--models realesrgan-x4plus,realesrgan-x4plus-anime,seedvr2]
      [--pick realesrgan-x4plus]   chép bản đã chọn thành <name>_atlas_x4.png (remaster.py dùng file này) và ghi
                                   <name>_atlas_x4_sc.png = cùng ảnh nhưng texel trong suốt -> RGBA (0,0,0,0): tmd.fsh của SC
                                   (đường PNG 24-bit, SubmapObjectTextureEvent) chỉ bỏ texel khi cả 4 kênh = 0, còn
                                   <name>_atlas_x4.png giữ RGB đã tô ở texel alpha 0 (cho lọc tuyến tính trong Blender).
                                   Chỉ chọn lại, không chạy mô hình: --models none --pick <mô hình>
                                   (không dùng --models "": PowerShell 5.1 bỏ đối số rỗng khi gọi chương trình ngoài)
      [--sheet [--crop x,y]]       ghép tờ so sánh <name>_atlas_x4_sosanh.png (gốc nearest | từng mô hình, có vùng phóng to)
Đầu vào: <dir>/<name>_atlas_pad.png (RGB đã tô texel trong suốt bằng màu đục gần nhất; alpha = texel trong suốt của TIM).
Cách làm: RGB đi qua mô hình (Real-ESRGAN ncnn-vulkan ở deps/upscale/realesrgan, hoặc SeedVR2 3B qua ComfyUI 127.0.0.1:8188 —
đồ thị lấy từ tools/sc_comfy_run.py); alpha = mặt nạ gốc phóng lanczos rồi cắt ngưỡng 0.5 (viền mượt hơn nearest, không mờ).
Kích thước ra đúng 4x (UV chuẩn hoá giữ nguyên). Ra: <dir>/<name>_atlas_x4_<model>.png, <name>_atlas_x4.json (thời gian từng mô hình).
Ảnh suy ra từ đĩa gốc: chỉ để thử trên máy (work/upscale bị .gitignore), không commit, không phát hành.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
ESRGAN = os.path.join(ROOT, 'deps', 'upscale', 'realesrgan', 'realesrgan-ncnn-vulkan.exe')
FONT = os.path.join(os.environ.get('WINDIR', 'C:/Windows'), 'Fonts', 'segoeui.ttf')


def rel(p):
    """Đường dẫn để in: tương đối theo gốc repo, khác ổ đĩa thì tuyệt đối (os.path.relpath ném ValueError)."""
    try:
        return os.path.relpath(p, ROOT)
    except ValueError:
        return os.path.abspath(p)


def esrgan(src_png, dst_png, model):
    t0 = time.time()
    r = subprocess.run([ESRGAN, '-i', src_png, '-o', dst_png, '-n', model, '-s', '4', '-f', 'png'],
                       capture_output=True, text=True, cwd=os.path.dirname(ESRGAN))
    if r.returncode != 0 or not os.path.isfile(dst_png):
        sys.exit('LOI realesrgan %s: %s' % (model, (r.stderr or r.stdout)[-800:]))
    return time.time() - t0


def seedvr2(src_png, dst_png):
    sys.path.insert(0, os.path.join(ROOT, 'tools'))
    import sc_comfy_run as cr
    t0 = time.time()
    name = cr.upload(src_png)
    graph = cr.graph_seedvr2(name, 4.0, 42, 'lab')
    meta = {'scene': os.path.basename(src_png), 'mode': 'seedvr2', 'color': 'lab'}
    cr.run(graph, dst_png, meta)
    return time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dir')
    ap.add_argument('--models', default='realesrgan-x4plus,realesrgan-x4plus-anime,seedvr2')
    ap.add_argument('--pick')
    ap.add_argument('--sheet', action='store_true')
    ap.add_argument('--crop', help='x,y (texel goc) vung phong to tren to so sanh; mac dinh tu chon')
    a = ap.parse_args()
    d = os.path.abspath(a.dir)
    name = os.path.basename(d.rstrip('\\/'))
    pad = os.path.join(d, name + '_atlas_pad.png')
    if not os.path.isfile(pad):
        sys.exit('LOI: khong thay ' + pad)
    src = Image.open(pad).convert('RGBA')
    W, H = src.size
    alpha = src.getchannel('A')
    a4 = np.array(alpha.resize((W * 4, H * 4), Image.LANCZOS)) >= 128
    meta_path = os.path.join(d, name + '_atlas_x4.json')
    meta = json.load(open(meta_path, encoding='utf-8')) if os.path.isfile(meta_path) else {}
    tmp = tempfile.mkdtemp(prefix='lodsc_up_')
    try:
        rgb_in = os.path.join(tmp, name + '_rgb.png')
        src.convert('RGB').save(rgb_in)
        for m in [x for x in a.models.split(',') if x and x != 'none']:
            out_raw = os.path.join(tmp, '%s_%s.png' % (name, m))
            secs = seedvr2(rgb_in, out_raw) if m == 'seedvr2' else esrgan(rgb_in, out_raw, m)
            up = Image.open(out_raw).convert('RGB')
            if up.size != (W * 4, H * 4):
                print('  %s: kich thuoc %s -> chinh ve %dx%d' % (m, up.size, W * 4, H * 4))
                up = up.resize((W * 4, H * 4), Image.LANCZOS)
            rgba = np.dstack([np.array(up), np.where(a4, 255, 0).astype(np.uint8)])
            dst = os.path.join(d, '%s_atlas_x4_%s.png' % (name, m))
            Image.fromarray(rgba, 'RGBA').save(dst)
            meta[m] = dict(seconds=round(secs, 1), size=[W * 4, H * 4])
            print('%s: %.1f s -> %s' % (m, secs, rel(dst)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if a.pick:
        p = os.path.join(d, '%s_atlas_x4_%s.png' % (name, a.pick))
        if not os.path.isfile(p):
            sys.exit('LOI: chua co %s (chay mo hinh %s truoc)' % (rel(p), a.pick))
        shutil.copyfile(p, os.path.join(d, name + '_atlas_x4.png'))
        # bản cho SC (đường PNG 24-bit của tmd.fsh chỉ bỏ texel khi cả RGBA = 0): texel trong suốt -> (0,0,0,0)
        sc = np.array(Image.open(p).convert('RGBA'))
        sc[sc[..., 3] == 0] = 0
        Image.fromarray(sc, 'RGBA').save(os.path.join(d, name + '_atlas_x4_sc.png'))
        meta['picked'] = a.pick
        print('chon:', a.pick)
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=1)
    if a.sheet:
        make_sheet(d, name, src, tuple(int(v) for v in a.crop.split(',')) if a.crop else None)


def make_sheet(d, name, src, crop_xy=None):
    files = sorted(f for f in glob.glob(os.path.join(d, name + '_atlas_x4_*.png'))
                   if not f.endswith(('_sosanh.png', '_x4_sc.png')))
    items = [('Gốc (nearest x4)', src.resize((src.width * 4, src.height * 4), Image.NEAREST))]
    for f in files:
        m = os.path.basename(f)[len(name + '_atlas_x4_'):-4]
        items.append((m, Image.open(f).convert('RGBA')))
    font = ImageFont.truetype(FONT, 22)
    W4, H4 = items[0][1].size
    # vùng phóng to: chọn góc ô 48x48 texel nhiều chi tiết nhỏ nhất (năng lượng Laplace cao) -> hiện 2x của bản x4
    g = np.array(src.convert('L'), float)
    lap = np.abs(4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:])
    best, bxy = -1, (0, 0)
    for y in range(0, max(src.height - 50, 1), 4):
        for x in range(0, max(src.width - 50, 1), 4):
            v = lap[y:y + 48, x:x + 48].mean()
            if v > best:
                best, bxy = v, (x, y)
    cx, cy = crop_xy or bxy
    cols = len(items)
    tile = max(W4, 384)
    cp = min(tile // 2, W4, H4)  # vùng cp x cp px của bản x4, hiện phóng to; kẹp trong ảnh (ngoài ảnh crop ra màu đen)
    x0 = min(max(cx * 4, 0), W4 - cp); y0 = min(max(cy * 4, 0), H4 - cp)
    cx, cy = x0 // 4, y0 // 4
    crop = (x0, y0, x0 + cp, y0 + cp)
    sheet = Image.new('RGB', (cols * (tile + 8), 34 + H4 + 34 + tile), (32, 32, 32))
    dr = ImageDraw.Draw(sheet)
    for i, (label, im) in enumerate(items):
        x = i * (tile + 8)
        bg = Image.new('RGBA', im.size, (255, 0, 255, 255)); bg.alpha_composite(im)
        dr.text((x + 6, 4), label, font=font, fill=(255, 230, 120))
        sheet.paste(bg.convert('RGB'), (x, 34))
        dr.text((x + 6, 34 + H4 + 4), 'phóng to %.3gx vùng %d,%d' % (tile / cp, cx, cy), font=font, fill=(200, 200, 200))
        sheet.paste(bg.crop(crop).resize((tile, tile), Image.NEAREST).convert('RGB'), (x, 34 + H4 + 34))
    out = os.path.join(d, name + '_atlas_x4_sosanh.png')
    sheet.save(out)
    print('to so sanh:', rel(out))


if __name__ == '__main__':
    main()
