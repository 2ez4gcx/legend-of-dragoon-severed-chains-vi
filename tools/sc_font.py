"""Xuất font tiếng Việt cho Severed Chains (định dạng gfx/fonts/<tên>.json + .png) từ font vẽ tay của D:\\LOD.

Cách gọi:
    python tools/sc_font.py            -> out/fonts/vietnamese.json + vietnamese.png + out/font_preview.png

Định dạng font SC (legend/core/font/FontManager.java):
    {"name": ..., "glyphs": {"<ký tự>" hoặc "0xXXXX": {texU, texV, texW, texH, x, y, w, h, colour}}}
    texU/V/W/H = vùng trên ảnh PNG (RGBA), x/y/w/h = vị trí/cỡ quad khi vẽ; w còn là BƯỚC chữ
    (renderer cộng thêm 1 px: nudgeX += w + 1). colour=true -> ảnh trắng được nhuộm màu chữ.
Bố cục: ô 16x16, 16 ô/hàng. Glyph 12 hàng của D:\\LOD (font/base.py + compose.py) đặt ở hàng 1..12 của ô
    (hộp thoại SC cắt hàng 0 của glyph và hiện hàng 1..12; đường chân chữ hoa hàng 10 = như font Original).
Ký tự D:\\LOD không có (# $ % & * + < = > @ \\ ^ ` { | } ~ ...) và biểu tượng nút (0xE000..) lấy nguyên từ
    gfx/fonts/default.json (font Original của SC).
"""
import json
import os
import sys
import unicodedata

import numpy as np
from PIL import Image

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SC = os.path.join(ROOT, 'Severed-Chains')
LOD = os.environ.get('LOD_ROOT', os.path.join(ROOT, '..', 'LOD'))
OUT = os.path.join(ROOT, 'out')
sys.path.insert(0, os.path.join(LOD, 'font'))

from base import G  # noqa: E402
from compose import VN_LOWER, VN_UPPER, glyph  # noqa: E402

CELL = 16
COLS = 16
ROW_SHIFT = 1          # hàng 0 của glyph D:\LOD -> hàng 1 của ô SC
SPACE_W = 3            # bước dấu cách (+1 renderer = 4 px như bản PS1)


def ours():
    """{ký tự: bitmap bool 12x8} cho mọi ký tự D:\\LOD vẽ được."""
    out = {}
    for ch in list(G.keys()) + list(VN_LOWER + VN_UPPER):
        if ch == ' ':
            continue
        out[ch] = glyph(ch)
    return out


def main():
    src_json = json.load(open(os.path.join(SC, 'gfx', 'fonts', 'default.json'), encoding='utf-8'))['glyphs']
    src_png = np.array(Image.open(os.path.join(SC, 'gfx', 'fonts', 'default.png')).convert('RGBA'))
    mine = ours()

    def key_char(k):
        return k if len(k) == 1 else chr(int(k[2:], 16))

    order = []          # (khoá json, nguồn)
    seen = set()
    for k in src_json:
        ch = key_char(k)
        order.append((k, 'lod' if ch in mine else 'sc'))
        seen.add(ch)
    for ch in VN_LOWER + VN_UPPER:
        if ch not in seen:
            order.append((ch, 'lod'))
            seen.add(ch)

    n = len(order)
    rows = (n + COLS - 1) // COLS
    height = 1 << (rows * CELL - 1).bit_length()
    atlas = np.zeros((height, COLS * CELL, 4), np.uint8)
    glyphs = {}
    for i, (k, srcname) in enumerate(order):
        u, v = (i % COLS) * CELL, (i // COLS) * CELL
        ch = key_char(k)
        if ch == ' ':
            glyphs[k] = dict(colour=False, texU=0, texV=0, texW=SPACE_W, texH=0, x=0, y=0, w=SPACE_W, h=16)
            continue
        if srcname == 'lod':
            bm = mine[ch]
            cols = np.where(bm.any(0))[0]
            w = int(cols.max()) + 1 if len(cols) else SPACE_W
            for r in range(12):
                for c in range(8):
                    if bm[r, c]:
                        atlas[v + r + ROW_SHIFT, u + c] = (255, 255, 255, 255)
            glyphs[k] = dict(colour=True, texU=u, texV=v, texW=w, texH=16, x=0, y=0, w=w, h=16)
        else:
            g = src_json[k]
            tw, th = max(g['texW'], 0), g['texH']
            if tw and th:
                atlas[v:v + th, u:u + tw] = src_png[g['texV']:g['texV'] + th, g['texU']:g['texU'] + tw]
            glyphs[k] = dict(g, texU=u, texV=v)

    os.makedirs(os.path.join(OUT, 'fonts'), exist_ok=True)
    Image.fromarray(atlas).save(os.path.join(OUT, 'fonts', 'vietnamese.png'))
    with open(os.path.join(OUT, 'fonts', 'vietnamese.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump({'name': 'Tiếng Việt (pixel)', 'glyphs': glyphs}, f, ensure_ascii=False, indent=2)
    print('font: %d glyph (%d tu D:\\LOD), anh %dx%d' % (n, sum(1 for _, s in order if s == 'lod'), atlas.shape[1], atlas.shape[0]))
    preview(glyphs, atlas, src_json, src_png)


def draw(text, glyphs, atlas, key=lambda ch: ch):
    """Vẽ như Font.queueChar của SC: bước = w + 1, mỗi dòng 12 px, ảnh RGBA."""
    lines = text.split('\n')
    W = max(sum(glyphs[key(c)]['w'] + 1 for c in ln if key(c) in glyphs) for ln in lines) + 4
    img = np.zeros((len(lines) * 12 + 6, W, 4), np.uint8)
    img[...] = (24, 32, 96, 255)
    for li, ln in enumerate(lines):
        x = 2
        for c in ln:
            g = glyphs.get(key(c))
            if g is None:
                x += 9
                continue
            if g['texW'] and g['texH']:
                # hộp thoại: hiện hàng 1..12 của glyph
                tile = atlas[g['texV'] + 1:g['texV'] + 13, g['texU']:g['texU'] + g['texW']]
                y0 = li * 12 + 2
                sub = img[y0:y0 + tile.shape[0], x:x + tile.shape[1]]
                m = tile[..., 3] > 0
                sub[m] = tile[m]
            x += g['w'] + 1
    return img


def preview(glyphs, atlas, src_json, src_png):
    sample = unicodedata.normalize('NFC', 'Dart\nHắn đang bày âm mưu gì chứ? Ừ, được rồi!\n'
                                   'Chúng ta sẽ không mãi như thế này, phải không?\n'
                                   'ẤN TƯỢNG Ở ĐỒNG BẰNG — Quỹ đạo, Vầng Trăng Vĩnh Hằng.\n'
                                   + VN_LOWER + '\n' + VN_UPPER)
    a = draw(sample, glyphs, atlas)
    eng = 'Dart\nLloyd.... What kind of plot is he weaving?\nWe are not going to be like this forever, right?'
    b = draw(eng, src_json, src_png)
    W = max(a.shape[1], b.shape[1])
    canvas = np.zeros((a.shape[0] + b.shape[0] + 4, W, 4), np.uint8)
    canvas[...] = (0, 0, 0, 255)
    canvas[:b.shape[0], :b.shape[1]] = b
    canvas[b.shape[0] + 4:, :a.shape[1]] = a
    im = Image.fromarray(canvas)
    im = im.resize((im.width * 3, im.height * 3), Image.NEAREST)
    im.save(os.path.join(OUT, 'font_preview.png'))
    print('xem truoc: out/font_preview.png (tren: font Original cua SC; duoi: font Viet)')


if __name__ == '__main__':
    main()
