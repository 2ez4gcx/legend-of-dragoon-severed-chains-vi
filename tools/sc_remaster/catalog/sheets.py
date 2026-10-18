"""sheets.py — tờ ảnh xem trước (contact sheet) cho danh mục v1: mỗi mục một ô, 3 góc nhìn (trước / sau / cạnh) của
mô hình nguồn đầu tiên, dựng ở khung hoạt cảnh 0, có texture từ TIM đặt trong VRAM ảo như SPEC §3.3.7.

Chỉ để NHẬN DIỆN / DUYỆT danh mục (không phải bản xem trước remaster). Dữ liệu suy ra từ đĩa => chỉ ghi vào
work/upscale/sc_remaster_c1/ (git bỏ qua; không bao giờ commit). Không dùng PIL: bộ dựng hình phần mềm bằng numpy,
font điểm ảnh 3x5 tự vẽ (chữ ASCII; nhãn tiếng Việt nằm trong sheets_index.json), PNG ghi bằng zlib.

Cách gọi (từ gốc repo; python hệ thống hoặc python.exe -I của Blender):
  python tools/sc_remaster/catalog/sheets.py [--game game/files] [--catalog tools/sc_remaster/catalog/catalog_v1.json]
                                             [--out work/upscale/sc_remaster_c1] [--only field|battle|verify|excluded]
                                             [--cell 80x112] [--cols 6]
Ghi: sheet_field_core.png, sheet_field_optional.png, sheet_battle.png (trận + cốt truyện + ô quái),
     sheet_verify.png (28 mục medium/low, mọi nguồn), sheet_excluded.png (mô hình loại trừ), sheets_index.json
     (số ô -> id, nhãn tiếng Việt, mô hình, TIM, hoạt cảnh). --only chỉ dựng lại tờ đó; số ô và sheets_index.json
     luôn tính cho mọi tờ (giống lần chạy đầy đủ). Exit 0 = mọi ô của các tờ đã dựng đều dựng được, 1 = có ô lỗi.
     Cùng trình thông dịch + numpy: chạy lại ra đúng từng byte. Giữa hai môi trường (python hệ thống numpy 2.5 / zlib-ng
     và python của Blender numpy 2.3 / zlib) byte PNG khác (zlib, SPEC B.2.10) và ~0,01% điểm ảnh ở cạnh tam giác / chỗ
     trùng độ sâu lệch do làm tròn float — tờ ảnh chỉ để nhận diện, không phải mục nghiệm thu.

Dựng: ref_spec.parse_ccontainer + decode_faces (uv/clut/tpage sau UvAdjust ô 0 với nguồn field), đỉnh xoay theo khung 0
của hoạt cảnh (rx, ry, rz, tx, ty, tz s16 tại 0x10 + 12*phần; JOML rotationZYX như tools/sc_remodel/export_tmd.py).
Hoạt cảnh: field = tài nguyên[obj*33+1..+32] đầu tiên cùng số phần; battle = models/<form>/0; story = DRGN0/N+2..;
quái = DRGN0/<thư mục>/0..1. Không tìm được thì dựng tư thế gốc (ô ghi 'NO ANIM').
"""
import argparse
import json
import math
import os
import struct
import sys
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import inventory as inv  # noqa: E402

ref_spec = inv.ref_spec
ROOT = inv.ROOT
CATALOG_PATH = os.path.join(HERE, 'catalog_v1.json')
VERIFY_PATH = os.path.join(HERE, 'verify_scenes.json')

# ---------------------------------------------------------------- font 3x5 (ASCII hoa; chữ thường -> hoa)
_FONT_SRC = {
    '0': '### #.# #.# #.# ###', '1': '.#. ##. .#. .#. ###', '2': '### ..# ### #.. ###', '3': '### ..# .## ..# ###',
    '4': '#.# #.# ### ..# ..#', '5': '### #.. ### ..# ###', '6': '### #.. ### #.# ###', '7': '### ..# .#. .#. .#.',
    '8': '### #.# ### #.# ###', '9': '### #.# ### ..# ###', 'A': '.#. #.# ### #.# #.#', 'B': '##. #.# ##. #.# ##.',
    'C': '.## #.. #.. #.. .##', 'D': '##. #.# #.# #.# ##.', 'E': '### #.. ##. #.. ###', 'F': '### #.. ##. #.. #..',
    'G': '.## #.. #.# #.# .##', 'H': '#.# #.# ### #.# #.#', 'I': '### .#. .#. .#. ###', 'J': '..# ..# ..# #.# .#.',
    'K': '#.# #.# ##. #.# #.#', 'L': '#.. #.. #.. #.. ###', 'M': '#.# ### ### #.# #.#', 'N': '##. #.# #.# #.# #.#',
    'O': '.#. #.# #.# #.# .#.', 'P': '##. #.# ##. #.. #..', 'Q': '.#. #.# #.# ##. .##', 'R': '##. #.# ##. #.# #.#',
    'S': '.## #.. .#. ..# ##.', 'T': '### .#. .#. .#. .#.', 'U': '#.# #.# #.# #.# ###', 'V': '#.# #.# #.# #.# .#.',
    'W': '#.# #.# ### ### #.#', 'X': '#.# #.# .#. #.# #.#', 'Y': '#.# #.# .#. .#. .#.', 'Z': '### ..# .#. #.. ###',
    ' ': '... ... ... ... ...', '.': '... ... ... ... .#.', ',': '... ... ... .#. #..', ':': '... .#. ... .#. ...',
    '-': '... ... ### ... ...', '_': '... ... ... ... ###', '/': '..# ..# .#. #.. #..', '|': '.#. .#. .#. .#. .#.',
    '(': '..# .#. .#. .#. ..#', ')': '#.. .#. .#. .#. #..', '+': '... .#. ### .#. ...', '#': '#.# ### #.# ### #.#',
    '=': '... ### ... ### ...', '?': '### ..# .#. ... .#.', '!': '.#. .#. .#. ... .#.', '*': '#.# .#. #.# ... ...',
    '%': '#.# ..# .#. #.. #.#', '[': '.## .#. .#. .#. .##', ']': '##. .#. .#. .#. ##.', '<': '..# .#. #.. .#. ..#',
    '>': '#.. .#. ..# .#. #..',
}
FONT = {c: np.array([[ch == '#' for ch in row] for row in s.split()], bool) for c, s in _FONT_SRC.items()}


def draw_text(img, x, y, text, colour, scale=2, maxw=None):
    """Vẽ chữ ASCII (hoa) lên img (H, W, 3) uint8; trả x cuối. Ký tự lạ -> '?'."""
    adv = 4 * scale
    for ch in str(text).upper():
        if maxw is not None and x + 3 * scale > maxw:
            break
        g = FONT.get(ch, FONT['?'])
        big = np.kron(g, np.ones((scale, scale), bool))
        h, w = big.shape
        sub = img[y:y + h, x:x + w]
        sub[big[:sub.shape[0], :sub.shape[1]]] = colour
        x += adv
    return x


def wrap(text, n):
    out = []
    s = str(text)
    while len(s) > n:
        cut = max(s.rfind('.', 0, n), s.rfind('/', 0, n), s.rfind(' ', 0, n))
        cut = n if cut <= 0 else cut + 1
        out.append(s[:cut])
        s = s[cut:]
    out.append(s)
    return out


# ---------------------------------------------------------------- PNG (zlib, xác định)
def png_rgb(img):
    h, w, _ = img.shape
    raw = b''.join(b'\x00' + img[y].tobytes() for y in range(h))

    def chunk(kind, data):
        c = kind + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


# ---------------------------------------------------------------- hoạt cảnh khung 0
def anim_kf0(b, nobj):
    if inv.anim_parts(b) != nobj or 0x10 + nobj * 12 > len(b):
        return None
    return [struct.unpack_from('<hhhhhh', b, 0x10 + p * 12) for p in range(nobj)]


def rot_zyx(rx, ry, rz):
    """JOML Quaternionf.rotationZYX(z, y, x) == Rz * Ry * Rx (4096 = 360 độ) — như export_tmd.py."""
    a = [v / 4096.0 * 2 * math.pi for v in (rx, ry, rz)]
    cx, sx = math.cos(a[0]), math.sin(a[0])
    cy, sy = math.cos(a[1]), math.sin(a[1])
    cz, sz = math.cos(a[2]), math.sin(a[2])
    rxm = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    rym = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rzm = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rzm @ rym @ rxm


def find_anim(game, kind, model, nobj, field_recs):
    """-> đường dẫn hoạt cảnh cùng số phần hoặc None (xem docstring đầu file)."""
    cands = []
    if kind == 'field':
        r = field_recs.get(model)
        if r is None:
            return None
        return inv.find_anim(game, inv.FIELD_DRGN[r['disc'] - 1], r['scene_dir'], r['obj'], nobj)
    if kind == 'battle':
        d = model.rsplit('/', 1)[0]
        cands = ['%s/%d' % (d, k) for k in (0, 1, 5, 10, 11, 14, 29)]
    elif kind == 'story':
        n = int(model.rsplit('/', 1)[1])
        cands = ['SECT/DRGN0.BIN/%d' % k for k in range(n + 2, n + 12)]
    elif kind == 'monster':
        d = model.rsplit('/', 1)[0]
        cands = ['%s/%d' % (d, k) for k in range(0, 32)]
    for c in cands:
        if inv.exists(game, c):
            b = inv.read_file(game, c)
            if anim_kf0(b, nobj) is not None:
                return c
    return None


# ---------------------------------------------------------------- dựng hình phần mềm
def load_tris(game, kind, model, tim, anim):
    """-> danh sách (P[3x3] đã xoay, uv[3x2] | None, tpage, clut, rgb, trong mờ), vram."""
    m = ref_spec.parse_ccontainer(inv.read_file(game, model))
    t = ref_spec.parse_tim(inv.read_file(game, tim))
    vram = ref_spec.new_vram()
    if kind == 'field':
        ref_spec.place_field_slot0(vram, t)
        ref_spec.uv_adjust_model(m, *ref_spec.FIELD_SLOT0)
    else:
        ref_spec.place_native(vram, t)
    kf0 = anim_kf0(inv.read_file(game, anim), len(m.parts)) if anim else None
    out = []
    for i, part in enumerate(m.parts):
        faces, _bf = ref_spec.decode_faces(part)
        verts = np.array(part.verts, float).reshape(-1, 3)
        if kf0 is not None:
            rx, ry, rz, tx, ty, tz = kf0[i]
            verts = verts @ rot_zyx(rx, ry, rz).T + np.array([tx, ty, tz], float)
        for f in faces:
            c = f.colours[0] if f.colours else 0xA0A0A0
            rgb = (c & 0xFF, c >> 8 & 0xFF, c >> 16 & 0xFF)
            for tri in ((2, 1, 0), (1, 2, 3)) if f.quad else ((2, 1, 0),):
                p = verts[[f.vidx[k] for k in tri]]
                uv = np.array([f.uv[k] for k in tri], float) if f.textured else None
                out.append((p, uv, f.tpage, f.clut, rgb, f.translucent))
    return out, vram


def sample(vram, tpage, clut, u, v):
    """Texel 15 bit (u, v mảng int) theo công thức tmd.fsh; toạ độ VRAM bọc & 1023 / & 511."""
    tx, ty, bpp = (tpage & 0xF) * 64, (256 if tpage & 0x10 else 0), tpage >> 7 & 3
    cx, cy = (clut & 0x3F) * 16, clut >> 6
    yy = (ty + v) & 511
    if bpp == 0:
        idx = (vram[yy, (tx + (u >> 2)) & 1023] >> ((u & 3) * 4)) & 0xF
    elif bpp == 1:
        idx = (vram[yy, (tx + (u >> 1)) & 1023] >> ((u & 1) * 8)) & 0xFF
    else:
        return vram[yy, (tx + u) & 1023]
    return vram[cy & 511, (cx + idx) & 1023]


def raster(tris, vram, view, w, h, bbox):
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = (40, 40, 48)
    zb = np.full((h, w), np.inf)
    if not tris:
        return img

    def proj(p):
        if view == 'front':
            return p[:, 0], p[:, 1], p[:, 2]
        if view == 'back':
            return -p[:, 0], p[:, 1], -p[:, 2]
        return p[:, 2], p[:, 1], -p[:, 0]
    x0, x1, y0, y1 = bbox[view]
    s = min((w - 4) / max(x1 - x0, 1e-6), (h - 4) / max(y1 - y0, 1e-6))
    cxm, cym = (x0 + x1) / 2, (y0 + y1) / 2
    light = np.array([0.3, -0.6, -0.75])
    light /= np.linalg.norm(light)
    order = sorted(range(len(tris)), key=lambda i: tris[i][5])   # đục trước, trong mờ sau
    for i in order:
        p, uv, tpage, clut, col, transl = tris[i]
        a, b, z = proj(p)
        sx = (a - cxm) * s + w / 2
        sy = (b - cym) * s + h / 2
        n = np.cross(p[1] - p[0], p[2] - p[0])
        nn = np.linalg.norm(n)
        shade = 0.55 + 0.45 * abs(float(np.dot(n / nn, light))) if nn > 0 else 1.0
        bx0, bx1 = max(int(np.floor(sx.min())), 0), min(int(np.ceil(sx.max())) + 1, w)
        by0, by1 = max(int(np.floor(sy.min())), 0), min(int(np.ceil(sy.max())) + 1, h)
        if bx1 <= bx0 or by1 <= by0:
            continue
        xg, yg = np.meshgrid(np.arange(bx0, bx1) + 0.5, np.arange(by0, by1) + 0.5)
        den = (sy[1] - sy[2]) * (sx[0] - sx[2]) + (sx[2] - sx[1]) * (sy[0] - sy[2])
        if abs(den) < 1e-9:
            continue
        w0 = ((sy[1] - sy[2]) * (xg - sx[2]) + (sx[2] - sx[1]) * (yg - sy[2])) / den
        w1 = ((sy[2] - sy[0]) * (xg - sx[2]) + (sx[0] - sx[2]) * (yg - sy[2])) / den
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not inside.any():
            continue
        zz = w0 * z[0] + w1 * z[1] + w2 * z[2]
        sub = zb[by0:by1, bx0:bx1]
        msk = inside & (zz < sub)
        if not msk.any():
            continue
        if uv is not None:
            uu = np.clip((w0 * uv[0, 0] + w1 * uv[1, 0] + w2 * uv[2, 0]).astype(int), 0, 255)[msk]
            vv = np.clip((w0 * uv[0, 1] + w1 * uv[1, 1] + w2 * uv[2, 1]).astype(int), 0, 255)[msk]
            px = sample(vram, tpage, clut, uu, vv).astype(np.uint32)
            ok = px != 0                                      # tmd.fsh: bỏ texel = 0
            rgb = np.stack([(px & 31) * 255 // 31, (px >> 5 & 31) * 255 // 31, (px >> 10 & 31) * 255 // 31],
                           -1).astype(float)[ok] * shade
            mm = np.zeros_like(msk)
            mm[msk] = ok
        else:
            mm = msk
            rgb = np.tile(np.array(col, float) * shade, (int(msk.sum()), 1))
        if not mm.any():
            continue
        tile = img[by0:by1, bx0:bx1]
        if transl:
            tile[mm] = np.clip(tile[mm].astype(float) * 0.5 + rgb * 0.5, 0, 255).astype(np.uint8)
        else:
            sub[mm] = zz[mm]
            tile[mm] = np.clip(rgb, 0, 255).astype(np.uint8)
    return img


def render(game, kind, model, tim, anim, w, h):
    tris, vram = load_tris(game, kind, model, tim, anim)
    allp = np.concatenate([t[0] for t in tris]) if tris else np.zeros((1, 3))
    bbox = {'front': (allp[:, 0].min(), allp[:, 0].max(), allp[:, 1].min(), allp[:, 1].max()),
            'back': (-allp[:, 0].max(), -allp[:, 0].min(), allp[:, 1].min(), allp[:, 1].max()),
            'side': (allp[:, 2].min(), allp[:, 2].max(), allp[:, 1].min(), allp[:, 1].max())}
    return np.concatenate([raster(tris, vram, v, w, h, bbox) for v in ('front', 'back', 'side')], axis=1)


# ---------------------------------------------------------------- tờ ảnh
def make_sheet(game, title, cells, field_recs, w, h, cols):
    """cells: [{n, kind, model, tim, lines[]}] -> (ảnh, lỗi[])."""
    cw, chh = 3 * w + 8, h + 8 + 3 * 12
    rows = max(1, (len(cells) + cols - 1) // cols)
    img = np.zeros((28 + rows * chh, cols * cw, 3), np.uint8)
    img[:] = (24, 24, 28)
    draw_text(img, 6, 8, title, (255, 255, 255), 3)
    errs = []
    for i, c in enumerate(cells):
        x, y = (i % cols) * cw + 4, 28 + (i // cols) * chh + 4
        try:
            if c.get('err'):
                raise ValueError(c['err'])
            anim = c['anim']
            tile = render(game, c['kind'], c['model'], c['tim'], anim, w, h)
            img[y:y + h, x:x + 3 * w] = tile
            if anim is None:
                draw_text(img, x + 2, y + 2, 'NO ANIM', (255, 120, 120), 1)
        except Exception as e:  # noqa: BLE001  (một ô lỗi không được làm hỏng cả tờ)
            errs.append('%s: %s' % (c['model'], e))
            draw_text(img, x + 2, y + 2, 'LOI ' + str(e)[:40], (255, 80, 80), 1)
        ty = y + h + 3
        for k, line in enumerate(c['lines'][:3]):
            draw_text(img, x, ty + 12 * k, line, (255, 255, 160) if k == 0 else (170, 220, 255), 2, x + 3 * w)
    return img, errs


def cell_anim(game, c, field_recs):
    """Đặt c['anim'] (hoạt cảnh cùng số phần hoặc None) và c['err'] nếu mô hình không đọc được."""
    c['anim'] = None
    try:
        nobj = inv.model_key(game, c['model'])['nobj']
        c['anim'] = find_anim(game, c['kind'], c['model'], nobj, field_recs)
    except Exception as e:  # noqa: BLE001  (một ô lỗi không được làm hỏng cả tờ)
        c['err'] = str(e)


def cell_lines(n, e, src, nsrc=1):
    conf = {'high': 'H', 'medium': 'M', 'low': 'L'}[e['confidence']]
    head = '#%d %s %s %dP %dT' % (n, conf, 'C' if e['tier'] == 'core' else 'OPT', e['expect']['nobj'],
                                  e['expect']['tris'])
    model = src['model'].replace('SECT/', '').replace('.BIN', '').replace('characters/', '').replace('/models/', '/')
    tail = model + ('  +%d' % (nsrc - 1) if nsrc > 1 else '')
    return [head, e['id'][:30], tail[:30]]


def main(argv=None):
    inv.utf8_stdout()
    ap = argparse.ArgumentParser(description='To anh nhan dien danh muc v1 (chi doc game/files).')
    ap.add_argument('--game', default=None)
    ap.add_argument('--catalog', default=CATALOG_PATH)
    ap.add_argument('--out', default=inv.OUT_DIR)
    ap.add_argument('--only', choices=['field', 'battle', 'verify', 'excluded'], default=None)
    ap.add_argument('--cell', default='80x112')
    ap.add_argument('--cols', type=int, default=6)
    a = ap.parse_args(argv)
    game = inv.resolve_game(a.game)
    inv.guard_out(os.path.join(a.out, 'x.png'))
    w, h = (int(x) for x in a.cell.lower().split('x'))
    with open(a.catalog, encoding='utf-8') as f:
        cat = json.load(f)
    with open(VERIFY_PATH, encoding='utf-8') as f:
        ver = json.load(f)
    recs, _ = inv.scan_field(game)
    field_recs = {}
    for r in recs:
        field_recs.setdefault(r['model'], r)
    by_id = {e['id']: e for e in cat}
    sheets = []
    n = 0

    def cells_for(entries, all_sources=False):
        nonlocal n
        out = []
        for e in entries:
            srcs = e['sources'] if all_sources else e['sources'][:1]
            for s in srcs:
                n += 1
                out.append(dict(n=n, id=e['id'], label_vi=e['label_vi'], kind=s['kind'], model=s['model'],
                                tim=s['tim'], lines=cell_lines(n, e, s, 1 if all_sources else len(e['sources']))))
        return out
    # Mọi tờ luôn được liệt kê (số ô ổn định, sheets_index.json luôn đầy đủ); --only chỉ giới hạn tờ được DỰNG lại.
    sheets.append(('field', 'sheet_field_core.png', 'FIELD CORE', cells_for(
        [e for e in cat if e['form'].startswith('field') and e['tier'] == 'core'])))
    sheets.append(('field', 'sheet_field_optional.png', 'FIELD OPTIONAL', cells_for(
        [e for e in cat if e['form'].startswith('field') and e['tier'] == 'optional'])))
    sheets.append(('battle', 'sheet_battle.png', 'BATTLE + STORY + MONSTER', cells_for(
        [e for e in cat if e['form'].startswith('battle')])))
    sheets.append(('verify', 'sheet_verify.png', 'VERIFY (MEDIUM/LOW) - ALL SOURCES', cells_for(
        [by_id[v['id']] for v in ver['entries']], all_sources=True)))
    cells = []
    for x in ver['excluded']:
        n += 1
        model = x['model'].replace('SECT/', '').replace('.BIN', '')
        cells.append(dict(n=n, id='excluded', label_vi=x['reason_vi'], kind=x['kind'], model=x['model'],
                          tim=x['tim'], lines=['#%d EXCLUDED %dP %dT' % (n, x['expect']['nobj'], x['expect']['tris']),
                                               'KEY ' + x['key_us'][:12], model[:30]]))
    sheets.append(('excluded', 'sheet_excluded.png', 'EXCLUDED LOOK-ALIKES', cells))
    os.makedirs(a.out, exist_ok=True)
    index = []
    all_errs = []
    for grp, fname, title, cells in sheets:
        for c in cells:
            cell_anim(game, c, field_recs)
        if a.only in (None, grp):
            img, errs = make_sheet(game, title, cells, field_recs, w, h, a.cols)
            all_errs += errs
            p = os.path.join(a.out, fname)
            inv.guard_out(p)
            with open(p, 'wb') as f:
                f.write(png_rgb(img))
            print('ghi %s (%d o, %dx%d)' % (os.path.relpath(p, ROOT), len(cells), img.shape[1], img.shape[0]))
        for c in cells:
            index.append(dict(sheet=fname, cell=c['n'], id=c['id'], label_vi=c['label_vi'], kind=c['kind'],
                              model=c['model'], tim=c['tim'], anim=c.get('anim')))
    p = os.path.join(a.out, 'sheets_index.json')
    inv.guard_out(p)
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
        f.write('\n')
    print('ghi', os.path.relpath(p, ROOT))
    noanim = [c for c in index if c['anim'] is None]
    print('o: %d, khong co hoat canh: %d, loi: %d' % (len(index), len(noanim), len(all_errs)))
    for c in noanim:
        print('  khong hoat canh: #%d %s' % (c['cell'], c['model']))
    for e in all_errs:
        print('LOI:', e)
    return 0 if not all_errs else 1


if __name__ == '__main__':
    sys.exit(main())
