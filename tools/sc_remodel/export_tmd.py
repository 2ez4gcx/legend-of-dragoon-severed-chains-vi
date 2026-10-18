"""export_tmd.py — xuất mô hình nhân vật TMD (LoD, đọc như Severed Chains affcef0) ra glTF / OBJ từng phần + JSON + atlas PNG.

Dùng cho thử nghiệm "remaster bằng Blender" (hướng B): mỗi đối tượng TMD (= một khớp cứng được hoạt cảnh) thành MỘT đối tượng,
giữ nguyên thứ tự phần và gốc toạ độ (pivot) để sau này một bộ nạp thay thế có thể ghép phần mới về đúng khớp.

Cách gọi (từ thư mục gốc repo; chỉ đọc file đã giải nén của người dùng trong game/files, không ghi gì cạnh dữ liệu game):
  python tools/sc_remodel/export_tmd.py battle dart [--form combat] [--anim 0] [--name dart_battle]
  python tools/sc_remodel/export_tmd.py field DRGN21.BIN/26 0 [--name dart_field]
      field <thư mục cảnh trong game/files/SECT> <chỉ số đối tượng sobj>  (mô hình = <obj*33>, texture = textures/<obj>,
      hoạt cảnh = file đầu tiên trong obj*33+1..obj*33+32 có cùng số phần)
  python tools/sc_remodel/export_tmd.py ... --check      chỉ kiểm tra (exit 0 = đạt, 1 = lỗi), không ghi file
  [--game <thư mục game/files>] [--out <thư mục ra>]  mặc định game/files và work/upscale/remodel/<name>

Đầu ra (mặc định work/upscale/remodel/<name>/ — dữ liệu suy ra từ đĩa Sony: .gitignore, KHÔNG commit, KHÔNG phát hành):
  <name>.json        dữ liệu chính xác cho remaster.py: toạ độ PS1 thô (x phải, y xuống, z vào trong), mỗi phần: đỉnh cục bộ,
                     mặt (thứ tự đỉnh TMD, vòng đa giác hướng ra ngoài, uv theo texel atlas, pháp tuyến TMD từng góc, màu từng góc,
                     cờ textured/translucent/lit/quad, tpage/clut gốc, transp_frac = tỉ lệ texel trong suốt), phép biến đổi
                     khung hình 0 (quay psx 4096=360°, tịnh tiến).
  <name>_atlas.png   atlas RGBA gộp: mỗi texel giải mã bằng CLUT của mặt dùng nó (giống tmd.fsh: màu 15-bit = 0 -> alpha 0);
                     texel không mặt nào dùng lấy CLUT của texel gần nhất; texel trùng hai CLUT khác nhau -> khối riêng xếp bên dưới.
  <name>_atlas_pad.png   như trên nhưng texel trong suốt được tô màu texel đục gần nhất (alpha giữ 0) — đầu vào cho upscale.
  <name>.gltf/.bin   glTF 2.0: nút gốc (tỉ lệ 0.001, Y lên: PS1 (x,y,z) -> (x,-y,-z)) + một nút con mỗi phần (TRS = khung 0),
                     lưới cục bộ đơn vị PS1, vật liệu 'tex' (atlas, lọc nearest, alpha MASK) và 'vcol' (màu đỉnh COLOR_0).
                     Mặt đề can (cùng tập đỉnh, cùng chiều với mặt nền: mắt/miệng) -> nút con partNN_decal; mặt sau của tấm
                     hai mặt (cùng tập đỉnh, ngược chiều) -> nút con partNN_back (bộ nhập glTF của Blender gộp mặt trùng tập
                     đỉnh nếu để chung lưới). JSON: trường 'layer' của mặt = base / decal / back.
  parts/partNN.obj   OBJ từng phần trong toạ độ cục bộ (Y lên; nhóm o partNN, o partNN_decal, o partNN_back), <name>.mtl;
                     <name>_posed.obj = mọi phần ở khung 0 (xem nhanh).
Kiểm tra tự động mỗi lần chạy: chỉ số đỉnh/pháp tuyến trong phạm vi, gói lệnh không lấn sang bảng khác, uv nằm trong TIM,
mọi texel mặt dùng trong atlas trùng từng bit màu với giải mã VRAM trực tiếp, đọc lại .bin glTF khớp số đỉnh/mặt.

Đặc tả (Severed Chains affcef0): CContainer (u32 tmd), TmdWithId (id 0x41 rồi TMD), TmdHeader (flags, nobj, bảng 0x1c),
CtmdTransformer.primitivePacketSize, TmdObjLoader.fromObjTable (thứ tự trường; tam giác (2,1,0) + (1,2,3) cho quad; backface
culling bật cho mặt đục), TmdAnimationFile (u16 số phần @0xc, khung @0x10, 12 byte/phần: svec3 quay, svec3 dời),
JOML rotationZYX = Rz*Ry*Rx, UvAdjustmentMetrics14 + RetailSubmap.calculateTextureLocations (sobj ô 0: ảnh 576,256 / clut 576,368).
"""
import argparse
import base64
import json
import math
import os
import struct
import sys

import numpy as np
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
SCALE_GLTF = 0.001


def rel(p):
    """Đường dẫn tương đối theo gốc repo để in; khác ổ đĩa (vd. --out C:\\...) thì giữ tuyệt đối thay vì ValueError."""
    try:
        return os.path.relpath(p, ROOT).replace('\\', '/')
    except ValueError:
        return os.path.abspath(p).replace('\\', '/')


def u16(b, o): return struct.unpack_from('<H', b, o)[0]
def s16(b, o): return struct.unpack_from('<h', b, o)[0]
def u32(b, o): return struct.unpack_from('<I', b, o)[0]


# ---------------------------------------------------------------- TMD
def packet_size(header):
    """CtmdTransformer.primitivePacketSize (không gồm 4 byte header)."""
    pid = header >> 24 & 0xff
    gradated = (header & 0x40000) != 0
    normals = (header & 0x10000) == 0
    shaded = (pid & 0x10) != 0
    quad = (pid & 0x8) != 0
    textured = (pid & 0x4) != 0
    lit = (pid & 0x1) == 0
    vc = 4 if quad else 3
    n = vc * 2
    if normals:
        n += (vc if shaded else 1) * 2
    if gradated or not lit:
        n += vc * 4
    elif not textured:
        n += 4
    if textured:
        n += vc * 4
    return (n + 3) & ~3


def parse_obj(b, objbase, rec, errors, tag):
    vtop, nv, ntop, nn, ptop, npr, scale = struct.unpack_from('<IIIIIIi', b, rec)
    verts = np.array([struct.unpack_from('<hhh', b, objbase + vtop + i * 8) for i in range(nv)], np.float64).reshape(-1, 3)
    norms = (np.array([struct.unpack_from('<hhh', b, objbase + ntop + i * 8) for i in range(nn)], np.float64) / 4096.0).reshape(-1, 3)
    prims = []
    off = objbase + ptop
    for pi in range(npr):
        header = u32(b, off)
        size = packet_size(header)
        d = b[off + 4: off + 4 + size]
        off += 4 + size
        pid = header >> 24
        if (pid >> 5 & 3) != 1:
            errors.append('%s prim %d: kieu goi %08x khong ho tro' % (tag, pi, header))
        shaded = (header & 0x40000) != 0
        gour = (pid & 0x10) != 0
        p = dict(index=pi, header=header, quad=bool(pid & 0x8), textured=bool(pid & 0x4), translucent=bool(pid & 0x2),
                 lit=(pid & 0x1) == 0, uv=[], clut=0, tpage=0, colours=None, vidx=[], nidx=[])
        vc = 4 if p['quad'] else 3
        o = 0
        if p['textured']:
            for i in range(vc):
                p['uv'].append((d[o], d[o + 1])); o += 2
                if i == 0:
                    p['clut'] = u16(d, o)
                elif i == 1:
                    p['tpage'] = u16(d, o)
                o += 2
        p['coloured'] = shaded or not p['lit'] or not p['textured']
        if shaded or not p['lit']:
            p['colours'] = [tuple(d[o + 4 * i: o + 4 * i + 3]) for i in range(vc)]; o += 4 * vc
        elif not p['textured']:
            p['colours'] = [tuple(d[o:o + 3])] * vc; o += 4
        for i in range(vc):
            if p['lit']:
                if gour or i == 0:
                    p['nidx'].append(u16(d, o)); o += 2
                else:
                    p['nidx'].append(p['nidx'][0])
            p['vidx'].append(u16(d, o)); o += 2
        if o > size:
            errors.append('%s prim %d: doc %d byte > kich thuoc goi %d' % (tag, pi, o, size))
        for v in p['vidx']:
            if v >= nv:
                errors.append('%s prim %d: chi so dinh %d >= %d' % (tag, pi, v, nv))
        prims.append(p)
    return dict(verts=verts, norms=norms, prims=prims, scale=scale, prim_end=off - objbase,
                sections=(vtop, vtop + nv * 8, ntop, ntop + nn * 8, ptop))


def parse_ccontainer(b, errors):
    tmd_with_id = u32(b, 0)
    if u32(b, tmd_with_id) != 0x41:
        errors.append('TmdWithId id = %x (mong doi 0x41)' % u32(b, tmd_with_id))
    base = tmd_with_id + 4
    flags, nobj = struct.unpack_from('<II', b, base)
    if flags & 3:
        raise SystemExit('LOI: TMD flags=%x (fixp/CTMD chua ho tro)' % flags)
    objbase = base + 8
    objs = [parse_obj(b, objbase, objbase + i * 0x1c, errors, 'obj%02d' % i) for i in range(nobj)]
    # gói lệnh của mỗi đối tượng không được lấn sang vùng đỉnh/pháp tuyến/gói của đối tượng khác
    starts = sorted({s for o in objs for s in (o['sections'][0], o['sections'][2], o['sections'][4])})
    for i, o in enumerate(objs):
        ptop = o['sections'][4]
        nxt = [s for s in starts if s > ptop]
        if nxt and o['prim_end'] > min(nxt):
            errors.append('obj%02d: goi lenh ket thuc %x lan sang vung %x' % (i, o['prim_end'], min(nxt)))
    return objs


def parse_anim_kf0(b):
    parts = u16(b, 0xc)
    if 0x10 + parts * 12 > len(b):
        return parts, None
    row = []
    for p in range(parts):
        rx, ry, rz, tx, ty, tz = struct.unpack_from('<hhhhhh', b, 0x10 + p * 12)
        row.append(((rx, ry, rz), (tx, ty, tz)))
    return parts, row


def rot_zyx(rx, ry, rz):
    """JOML Quaternionf.rotationZYX(z, y, x) == Rz * Ry * Rx (psx: 4096 = 360°)."""
    a = [v / 4096.0 * 2 * math.pi for v in (rx, ry, rz)]
    cx, sx = math.cos(a[0]), math.sin(a[0])
    cy, sy = math.cos(a[1]), math.sin(a[1])
    cz, sz = math.cos(a[2]), math.sin(a[2])
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


# ---------------------------------------------------------------- TIM / VRAM
def parse_tim(b):
    magic, flags = struct.unpack_from('<II', b, 0)
    if magic != 0x10:
        raise SystemExit('LOI: khong phai TIM')
    o = 8
    clut = clut_rect = None
    if flags & 8:
        ln, cx, cy, cw, ch = struct.unpack_from('<IHHHH', b, o)
        clut = np.frombuffer(b, '<u2', cw * ch, o + 12).reshape(ch, cw)
        clut_rect = [cx, cy, cw, ch]
        o += ln
    ln, ix, iy, iw, ih = struct.unpack_from('<IHHHH', b, o)
    img = np.frombuffer(b, '<u2', iw * ih, o + 12).reshape(ih, iw)
    return dict(bpp=flags & 3, clut=clut, clut_rect=clut_rect, img=img, img_rect=[ix, iy, iw, ih])


def c15_to_rgba(px):
    px = np.asarray(px, np.uint32)
    r = (px & 31) * 255 // 31
    g = (px >> 5 & 31) * 255 // 31
    bb = (px >> 10 & 31) * 255 // 31
    a = np.where(px == 0, 0, 255)  # tmd.fsh: bỏ texel khi cả 16 bit = 0
    return np.stack([r, g, bb, a], -1).astype(np.uint8)


class UvAdjust:
    """UvAdjustmentMetrics14(index, x, y): clut = (x, y+112), tpage = (x, y); apply() như Java."""

    def __init__(self, x, y):
        clut = x // 16 | (y + 112) << 6
        tpage = x // 64 | y // 256 << 4
        self.clut_or = clut << 16
        self.tpage_or = tpage << 16
        self.uv_off = (x % 64 * 4) | (y % 256) << 8

    def apply(self, p):
        uv = p['uv']
        w0 = (uv[0][0] | uv[0][1] << 8 | p['clut'] << 16)
        w1 = (uv[1][0] | uv[1][1] << 8 | p['tpage'] << 16)
        w0 = ((w0 & 0x3c3ffff | self.clut_or) + self.uv_off) & 0xffffffff
        w1 = ((w1 & 0xffe0ffff | self.tpage_or) + self.uv_off) & 0xffffffff
        new_uv = [(w0 & 0xff, w0 >> 8 & 0xff), (w1 & 0xff, w1 >> 8 & 0xff)]
        for k in range(2, len(uv)):
            # các góc sau chỉ có u,v + 2 byte đệm: Java cộng uvOffset vào cả int (đệm = 0 trong TMD sobj)
            w = (uv[k][0] | uv[k][1] << 8) + self.uv_off
            new_uv.append((w & 0xff, w >> 8 & 0xff))
        p['uv'] = new_uv
        p['clut'] = w0 >> 16
        p['tpage'] = w1 >> 16


def page_info(tpage):
    return (tpage & 0xf) * 64, (256 if tpage & 0x10 else 0), tpage >> 7 & 3


def sample_vram(vram, tpage, clut, u, v):
    """Giải mã texel (u, v) trong trang tpage với clut — đúng công thức tmd.fsh. u, v: mảng int."""
    tx, ty, bpp = page_info(tpage)
    cx, cy = (clut & 0x3f) * 16, clut >> 6
    if bpp == 0:
        idx = (vram[ty + v, tx + (u >> 2)] >> ((u & 3) * 4)) & 0xf
    elif bpp == 1:
        idx = (vram[ty + v, tx + (u >> 1)] >> ((u & 1) * 8)) & 0xff
    else:
        return vram[ty + v, tx + u]
    return vram[cy, cx + idx]


# ---------------------------------------------------------------- tải mô hình
def load_battle(game, ch, form, anim, errors):
    base = os.path.join(game, 'characters', ch)
    mpath = os.path.join(base, 'models', form, '32')
    objs = parse_ccontainer(open(mpath, 'rb').read(), errors)
    tim = parse_tim(open(os.path.join(base, 'textures', form), 'rb').read())
    apath = os.path.join(base, 'models', form, str(anim))
    n, kf0 = parse_anim_kf0(open(apath, 'rb').read())
    if n != len(objs) or kf0 is None:
        raise SystemExit('LOI: hoat canh %s co %d phan, mo hinh %d phan' % (apath, n, len(objs)))
    vram = np.zeros((512, 1024), np.uint16)
    ix, iy, iw, ih = tim['img_rect']
    vram[iy:iy + ih, ix:ix + iw] = tim['img']
    cx, cy, cw, chh = tim['clut_rect']
    vram[cy:cy + chh, cx:cx + cw] = tim['clut']
    src = dict(model=os.path.relpath(mpath, game).replace('\\', '/'), anim=os.path.relpath(apath, game).replace('\\', '/'),
               texture=os.path.relpath(os.path.join(base, 'textures', form), game).replace('\\', '/'),
               texture_vram=[ix, iy, iw, ih], clut_vram=[cx, cy, cw, chh], uv_adjust=None)
    return objs, kf0, tim, vram, (ix, iy), src


def load_field(game, drgn_dir, obj, errors):
    base = os.path.join(game, 'SECT', *drgn_dir.replace('\\', '/').split('/'))
    mpath = os.path.join(base, str(obj * 33))
    objs = parse_ccontainer(open(mpath, 'rb').read(), errors)
    tpath = os.path.join(base, 'textures', str(obj))
    tim = parse_tim(open(tpath, 'rb').read())
    kf0 = apath = None
    for k in range(obj * 33 + 1, obj * 33 + 33):
        f = os.path.join(base, str(k))
        if os.path.isfile(f) and os.path.getsize(f) >= 0x10:
            b = open(f, 'rb').read()
            if u32(b, 0) == 0x11:
                continue
            n, row = parse_anim_kf0(b)
            if n == len(objs) and row is not None:
                kf0, apath = row, f
                break
    if kf0 is None:
        raise SystemExit('LOI: khong thay hoat canh cung so phan cho %s' % mpath)
    # RetailSubmap: sobj đầu tiên ở ô 0 -> ảnh (576,256), clut (576,368); masks của UvAdjustmentMetrics14 giữ phần tương đối
    sx, sy = 576, 256
    vram = np.zeros((512, 1024), np.uint16)
    ih, iw = tim['img'].shape
    vram[sy:sy + ih, sx:sx + iw] = tim['img']
    ch, cw = tim['clut'].shape
    vram[sy + 112:sy + 112 + ch, sx:sx + cw] = tim['clut']
    adj = UvAdjust(sx, sy)
    for o in objs:
        for p in o['prims']:
            if p['textured']:
                adj.apply(p)
    src = dict(model=os.path.relpath(mpath, game).replace('\\', '/'), anim=os.path.relpath(apath, game).replace('\\', '/'),
               texture=os.path.relpath(tpath, game).replace('\\', '/'), texture_vram=[sx, sy, iw, ih],
               clut_vram=[sx, sy + 112, cw, ch], uv_adjust='UvAdjustmentMetrics14(slot 0: 576,256)')
    return objs, kf0, tim, vram, (sx, sy), src


# ---------------------------------------------------------------- atlas
def prim_tris(p):
    return [(2, 1, 0)] + ([(1, 2, 3)] if p['quad'] else [])


def coverage(tri_uv, W, H, ss=4):
    """Số mẫu (trên ss*ss mẫu/texel) nằm trong tam giác uv (toạ độ texel) cho mỗi texel trong bbox -> (x0, y0, counts)."""
    tri = np.asarray(tri_uv, float)
    x0 = max(int(math.floor(tri[:, 0].min())), 0); x1 = min(int(math.ceil(tri[:, 0].max())), W)
    y0 = max(int(math.floor(tri[:, 1].min())), 0); y1 = min(int(math.ceil(tri[:, 1].max())), H)
    if x1 <= x0 or y1 <= y0:
        return x0, y0, np.zeros((0, 0), int)
    off = (np.arange(ss) + 0.5) / ss
    xs = (np.arange(x0, x1)[:, None] + off[None, :]).reshape(-1)
    ys = (np.arange(y0, y1)[:, None] + off[None, :]).reshape(-1)
    X, Y = np.meshgrid(xs, ys)
    (ax, ay), (bx, by), (cx, cy) = tri
    den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(den) < 1e-9:
        return x0, y0, np.zeros((y1 - y0, x1 - x0), int)
    w0 = ((by - cy) * (X - cx) + (cx - bx) * (Y - cy)) / den
    w1 = ((cy - ay) * (X - cx) + (ax - cx) * (Y - cy)) / den
    w2 = 1 - w0 - w1
    inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
    cnt = inside.reshape(y1 - y0, ss, x1 - x0, ss).sum((1, 3))
    return x0, y0, cnt


def nearest_fill(owner, valid):
    """Lan toả giá trị owner (chỗ valid) sang các ô chưa có theo lân cận 4 hướng (gần đúng khoảng cách Manhattan)."""
    owner = owner.copy(); valid = valid.copy()
    H, W = owner.shape
    for _ in range(H + W):
        if valid.all():
            break
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            src_v = np.zeros_like(valid); src_o = np.zeros_like(owner)
            ys = slice(max(dy, 0), H + min(dy, 0)); yd = slice(max(-dy, 0), H + min(-dy, 0))
            xs = slice(max(dx, 0), W + min(dx, 0)); xd = slice(max(-dx, 0), W + min(-dx, 0))
            src_v[yd, xd] = valid[ys, xs]; src_o[yd, xd] = owner[ys, xs]
            take = ~valid & src_v
            owner[take] = src_o[take]; valid |= take
    return owner, valid


def build_atlas(objs, tim, vram, tim_origin, errors):
    """-> atlas RGBA, raw15 (u16), W, H, per-prim (block, tim_u0, tim_v0). Toạ độ atlas texel = (u - u0, v - v0 + block*H)."""
    ix, iy = tim_origin
    ih, iw = tim['img'].shape
    prims = [p for o in objs for p in o['prims'] if p['textured']]
    if not prims:
        return None
    bpps = {page_info(p['tpage'])[2] for p in prims}
    if len(bpps) != 1:
        errors.append('nhieu do sau mau trong mot mo hinh: %s' % bpps)
    bpp = bpps.pop()
    ppw = {0: 4, 1: 2, 2: 1}[bpp]
    W, H = iw * ppw, ih
    for p in prims:
        tx, ty, _ = page_info(p['tpage'])
        p['_u0'] = (ix - tx) * ppw
        p['_v0'] = iy - ty
        for (u, v) in p['uv']:
            if not (0 <= u - p['_u0'] <= W and 0 <= v - p['_v0'] <= H):
                errors.append('prim %d: uv (%d,%d) ngoai TIM' % (p['index'], u, v))
    # cluts theo tổng diện tích phủ
    cov = {}
    for p in prims:
        acc = []
        for t in prim_tris(p):
            tuv = [(p['uv'][c][0] - p['_u0'], p['uv'][c][1] - p['_v0']) for c in t]
            acc.append(coverage(tuv, W, H))
        p['_cov'] = acc
        cov[p['clut']] = cov.get(p['clut'], 0) + sum(int(c.sum()) for _, _, c in acc)
    order = sorted(cov, key=lambda k: -cov[k])
    rank = {k: i for i, k in enumerate(order)}
    owner = np.full((H, W), -1, int)       # chỉ số clut (theo order) sở hữu texel (phủ mạnh >= 4/16 mẫu)
    weak = np.full((H, W), -1, int)
    extra_blocks = []                       # [clut] khối phụ
    for p in sorted(prims, key=lambda q: rank[q['clut']]):
        r = rank[p['clut']]
        conflict = False
        for x0, y0, c in p['_cov']:
            if c.size == 0:
                continue
            o = owner[y0:y0 + c.shape[0], x0:x0 + c.shape[1]]
            if ((c >= 4) & (o >= 0) & (o != r)).any():
                conflict = True
        if conflict:
            if p['clut'] not in extra_blocks:
                extra_blocks.append(p['clut'])
            p['_block'] = 1 + extra_blocks.index(p['clut'])
            continue
        p['_block'] = 0
        for x0, y0, c in p['_cov']:
            if c.size == 0:
                continue
            o = owner[y0:y0 + c.shape[0], x0:x0 + c.shape[1]]
            o[(c >= 4) & (o < 0)] = r
            w = weak[y0:y0 + c.shape[0], x0:x0 + c.shape[1]]
            w[(c > 0) & (w < 0)] = r
    base_owner = np.where(owner >= 0, owner, weak)
    filled, ok = nearest_fill(base_owner, base_owner >= 0)
    if not ok.all():
        filled[~ok] = 0
    # giải mã: dùng tpage của prim đầu tiên (mọi prim chung trang theo kiểm tra bpp + gốc TIM)
    tp0 = prims[0]['tpage']
    _, _, _ = page_info(tp0)
    u0, v0 = prims[0]['_u0'], prims[0]['_v0']
    U, V = np.meshgrid(np.arange(W) + u0, np.arange(H) + v0)
    raw = np.zeros((H * (1 + len(extra_blocks)), W), np.uint16)
    base = np.zeros((H, W), np.uint16)
    for k, cl in enumerate(order):
        m = filled == k
        if m.any():
            base[m] = sample_vram(vram, tp0, cl, U[m], V[m])
    raw[:H] = base
    for b, cl in enumerate(extra_blocks):
        raw[H * (b + 1): H * (b + 2)] = sample_vram(vram, tp0, cl, U, V)
    # kiểm: mọi texel prim dùng (phủ mạnh) giải mã qua atlas == giải mã trực tiếp từ VRAM
    bad = 0
    for p in prims:
        for x0, y0, c in p['_cov']:
            if c.size == 0:
                continue
            yy, xx = np.nonzero(c >= 4)
            uu = xx + x0; vv = yy + y0
            direct = sample_vram(vram, p['tpage'], p['clut'], uu + p['_u0'], vv + p['_v0'])
            via = raw[vv + p['_block'] * H, uu]
            bad += int((direct != via).sum())
    if bad:
        errors.append('atlas: %d texel khac giai ma VRAM truc tiep' % bad)
    # tỉ lệ texel trong suốt (màu 15-bit = 0) trong vùng mặt dùng: mặt "đề can" (mắt, miệng) -> remaster.py dò hướng mặt
    for p in prims:
        tot = tr = 0
        for x0, y0, c in p['_cov']:
            if c.size == 0:
                continue
            yy, xx = np.nonzero(c >= 4)
            tot += len(yy)
            tr += int((raw[yy + y0 + p['_block'] * H, xx + x0] == 0).sum())
        p['_transp'] = tr / tot if tot else 0.0
    # texel chỉ phủ yếu (cạnh) có thể khác CLUT -> báo số lượng (không phải lỗi: sai khác chỉ ở mép tam giác)
    edge_diff = 0
    for p in prims:
        for x0, y0, c in p['_cov']:
            if c.size == 0:
                continue
            yy, xx = np.nonzero((c > 0) & (c < 4))
            uu = xx + x0; vv = yy + y0
            direct = sample_vram(vram, p['tpage'], p['clut'], uu + p['_u0'], vv + p['_v0'])
            edge_diff += int((direct != raw[vv + p['_block'] * H, uu]).sum())
    stats = dict(W=W, H=H, bpp=bpp, cluts=['%04x' % c for c in order], extra_blocks=['%04x' % c for c in extra_blocks],
                 owned_texels=int((owner >= 0).sum()), edge_texels_other_clut=edge_diff)
    return c15_to_rgba(raw), raw, W, H, stats


def pad_transparent(rgba):
    """Tô RGB của texel alpha=0 bằng màu texel đục gần nhất (alpha giữ nguyên) để lọc tuyến tính/upscale không ám đen."""
    a = rgba[..., 3] > 0
    if a.all() or not a.any():
        return rgba.copy()
    H, W = a.shape
    idx = np.arange(H * W).reshape(H, W)
    src, ok = nearest_fill(np.where(a, idx, -1), a)
    out = rgba.copy()
    flat = rgba.reshape(-1, 4)
    out[..., :3] = flat[src.reshape(-1), :3].reshape(H, W, 3)
    out[..., 3] = rgba[..., 3]
    return out


# ---------------------------------------------------------------- dựng dữ liệu phần
def build_parts(objs, kf0, atlas_info, errors):
    W, H = (atlas_info[2], atlas_info[3]) if atlas_info else (1, 1)
    parts = []
    winding = [0, 0]
    for i, o in enumerate(objs):
        V = o['verts']
        faces = []
        for p in o['prims']:
            vc = len(p['vidx'])
            P = V[p['vidx']]
            if p['lit']:
                N = []
                for n in p['nidx']:
                    if n < len(o['norms']):
                        N.append(o['norms'][n])
                    else:
                        N.append(np.zeros(3))
                        errors.append('obj%02d prim %d: chi so phap tuyen %d ngoai pham vi (SC dung 0)' % (i, p['index'], n))
                N = np.array(N)
            else:
                N = None
            # vòng đa giác theo tam giác TMD (2,1,0): tri -> [2,1,0]; quad -> [0,2,3,1] (ghép (2,1,0)+(1,2,3))
            loop = [2, 1, 0] if vc == 3 else [0, 2, 3, 1]
            # pháp tuyến hình học của vòng (Newell) so với pháp tuyến TMD để biết chiều nào là mặt trước
            g = np.zeros(3)
            for k in range(len(loop)):
                a, b = P[loop[k]], P[loop[(k + 1) % len(loop)]]
                g += np.array([(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])])
            if N is not None:
                d = float(np.dot(g, N.sum(0)))
                if abs(d) > 1e-9:
                    winding[0 if d > 0 else 1] += 1
            f = dict(prim=p['index'], vidx=[int(x) for x in p['vidx']], loop=loop, quad=p['quad'], textured=p['textured'],
                     translucent=p['translucent'], lit=p['lit'], coloured=bool(p['coloured']),
                     normals=None if N is None else [[round(float(c), 6) for c in n] for n in N],
                     colours=None if p['colours'] is None else [list(c) for c in p['colours']],
                     geo_normal=[float(c) for c in g])
            if p['textured']:
                blk = p.get('_block', 0)
                f['uv'] = [[int(u - p['_u0']), int(v - p['_v0'] + blk * H)] for (u, v) in p['uv']]
                f['tpage'] = '%04x' % p['tpage']; f['clut'] = '%04x' % p['clut']
                f['transp_frac'] = round(p.get('_transp', 0.0), 4)
            faces.append(f)
        # lớp đề can: mặt cùng tập đỉnh và CÙNG chiều với mặt khác (mắt/miệng vẽ chồng; PS1 dựa thứ tự vẽ). Mặt ít texel trong
        # suốt nhất trong nhóm là nền ('base'), mặt cùng chiều còn lại 'decal' -> nút/đối tượng con partNN_decal; mặt cùng tập
        # đỉnh nhưng NGƯỢC chiều = mặt sau của tấm hai mặt ('back', không phải đề can) -> nút con partNN_back.
        # (Blender không cho hai mặt cùng tập đỉnh trong một lưới: bộ nhập glTF gộp mất nếu để chung.)
        groups = {}
        for f in faces:
            groups.setdefault(tuple(sorted(f['vidx'])), []).append(f)
        for g in groups.values():
            g.sort(key=lambda f: f.get('transp_frac', 0.0) if f['textured'] else -1.0)
            g0 = np.array(g[0]['geo_normal'])
            for k, f in enumerate(g):
                if k == 0:
                    f['layer'] = 'base'
                else:
                    f['layer'] = 'back' if float(np.dot(g0, f['geo_normal'])) < 0 else 'decal'
        R = rot_zyx(*kf0[i][0])
        parts.append(dict(index=i, name='part%02d' % i, verts=[[int(c) for c in v] for v in V],
                          normals_tmd=len(o['norms']), faces=faces, kf0_rot_psx=list(kf0[i][0]), kf0_trans=list(kf0[i][1]),
                          kf0_matrix=[[round(float(c), 9) for c in r] for r in R]))
    return parts, winding


# ---------------------------------------------------------------- glTF / OBJ
C = np.diag([1.0, -1.0, -1.0])   # PS1 (y xuống, z vào) -> glTF (Y lên, Z ra phía trước): quay 180° quanh X


def mat_to_quat(M):
    t = np.trace(M)
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        w = 0.25 * s; x = (M[2, 1] - M[1, 2]) / s; y = (M[0, 2] - M[2, 0]) / s; z = (M[1, 0] - M[0, 1]) / s
    elif M[0, 0] > M[1, 1] and M[0, 0] > M[2, 2]:
        s = math.sqrt(1.0 + M[0, 0] - M[1, 1] - M[2, 2]) * 2
        w = (M[2, 1] - M[1, 2]) / s; x = 0.25 * s; y = (M[0, 1] + M[1, 0]) / s; z = (M[0, 2] + M[2, 0]) / s
    elif M[1, 1] > M[2, 2]:
        s = math.sqrt(1.0 + M[1, 1] - M[0, 0] - M[2, 2]) * 2
        w = (M[0, 2] - M[2, 0]) / s; x = (M[0, 1] + M[1, 0]) / s; y = 0.25 * s; z = (M[1, 2] + M[2, 1]) / s
    else:
        s = math.sqrt(1.0 + M[2, 2] - M[0, 0] - M[1, 1]) * 2
        w = (M[1, 0] - M[0, 1]) / s; x = (M[0, 2] + M[2, 0]) / s; y = (M[1, 2] + M[2, 1]) / s; z = 0.25 * s
    q = np.array([x, y, z, w]); return (q / np.linalg.norm(q)).tolist()


def srgb_to_linear(c):
    c = np.asarray(c, float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def corner_lists(part, flip, W, Htot, layer='base'):
    """-> dict mat -> (positions, normals, uvs, colours, indices) đã quy về đỉnh duy nhất (glTF, toạ độ Y lên); chỉ lớp layer."""
    out = {}
    V = np.array(part['verts'], float) @ C.T
    for f in part['faces']:
        if f.get('layer', 'base') != layer:
            continue
        mat = 'tex' if f['textured'] else 'vcol'
        d = out.setdefault(mat, dict(key={}, P=[], N=[], T=[], Col=[], I=[]))
        loop = f['loop'][::-1] if flip else f['loop']
        tris = [(loop[0], loop[1], loop[2])] + ([(loop[0], loop[2], loop[3])] if len(loop) == 4 else [])
        gn = np.array(f['geo_normal']) @ C.T
        gn = -gn if flip else gn
        gn = gn / (np.linalg.norm(gn) + 1e-12)
        for t in tris:
            for c in t:
                n = (np.array(f['normals'][c]) @ C.T) if f['normals'] is not None else gn
                if np.linalg.norm(n) < 1e-9:
                    n = gn
                n = n / np.linalg.norm(n)
                uv = (f['uv'][c][0] / W, f['uv'][c][1] / Htot) if f['textured'] else (0.0, 0.0)
                if f['colours'] is not None:
                    col = tuple(srgb_to_linear(np.array(f['colours'][c]) / 255.0).tolist())
                else:
                    col = (1.0, 1.0, 1.0)
                k = (f['vidx'][c], tuple(np.round(n, 5)), uv, col)
                if k not in d['key']:
                    d['key'][k] = len(d['P'])
                    d['P'].append(V[f['vidx'][c]]); d['N'].append(n); d['T'].append(uv); d['Col'].append(col + (1.0,))
                d['I'].append(d['key'][k])
    return out


def write_gltf(path_base, name, parts, flip, W, Htot, has_atlas):
    blob = bytearray()
    views, accessors = [], []

    def add(arr, ctype, comp, target=None, minmax=False):
        arr = np.ascontiguousarray(arr)
        while len(blob) % 4:
            blob.append(0)
        off = len(blob)
        blob.extend(arr.tobytes())
        v = dict(buffer=0, byteOffset=off, byteLength=arr.nbytes)
        if target:
            v['target'] = target
        views.append(v)
        a = dict(bufferView=len(views) - 1, componentType=comp, count=int(arr.shape[0]), type=ctype)
        if minmax:
            a['min'] = arr.min(0).astype(float).tolist(); a['max'] = arr.max(0).astype(float).tolist()
        accessors.append(a)
        return len(accessors) - 1

    mats = []
    mat_index = {}
    if has_atlas:
        mat_index['tex'] = len(mats)
        mats.append(dict(name='tex', pbrMetallicRoughness=dict(baseColorTexture=dict(index=0), metallicFactor=0.0, roughnessFactor=1.0),
                         alphaMode='MASK', alphaCutoff=0.5, doubleSided=False))
    mat_index['vcol'] = len(mats)
    mats.append(dict(name='vcol', pbrMetallicRoughness=dict(metallicFactor=0.0, roughnessFactor=1.0), doubleSided=False))
    meshes, nodes = [], [dict(name=name + '_root', scale=[SCALE_GLTF] * 3, children=[])]
    def prims_of(cl):
        prims = []
        for mat, d in cl.items():
            P = np.array(d['P'], np.float32); N = np.array(d['N'], np.float32)
            attrs = dict(POSITION=add(P, 'VEC3', 5126, 34962, True), NORMAL=add(N, 'VEC3', 5126, 34962))
            if mat == 'tex':
                attrs['TEXCOORD_0'] = add(np.array(d['T'], np.float32), 'VEC2', 5126, 34962)
            else:
                attrs['COLOR_0'] = add(np.array(d['Col'], np.float32), 'VEC4', 5126, 34962)
            idx = add(np.array(d['I'], np.uint32), 'SCALAR', 5125, 34963)
            prims.append(dict(attributes=attrs, indices=idx, material=mat_index[mat], mode=4))
        return prims

    for part in parts:
        prims = prims_of(corner_lists(part, flip, W, Htot, 'base'))
        R = np.array(part['kf0_matrix'])
        node = dict(name=part['name'], rotation=mat_to_quat(C @ R @ C),
                    translation=(C @ np.array(part['kf0_trans'], float)).tolist(),
                    extras=dict(tmd_object=part['index'], kf0_rot_psx=part['kf0_rot_psx'], kf0_trans=part['kf0_trans']))
        if prims:
            node['mesh'] = len(meshes)
            meshes.append(dict(name=part['name'], primitives=prims))
        nodes[0]['children'].append(len(nodes))
        nodes.append(node)
        for layer in ('decal', 'back'):
            dprims = prims_of(corner_lists(part, flip, W, Htot, layer))
            if dprims:
                node.setdefault('children', []).append(len(nodes))
                nodes.append(dict(name=part['name'] + '_' + layer, mesh=len(meshes), extras=dict(tmd_object=part['index'], layer=layer)))
                meshes.append(dict(name=part['name'] + '_' + layer, primitives=dprims))
    g = dict(asset=dict(version='2.0', generator='LOD-SC tools/sc_remodel/export_tmd.py'), scene=0,
             scenes=[dict(nodes=[0])], nodes=nodes, meshes=meshes, materials=mats,
             buffers=[dict(uri=os.path.basename(path_base) + '.bin', byteLength=len(blob))], bufferViews=views, accessors=accessors)
    if has_atlas:
        g['images'] = [dict(uri=os.path.basename(path_base) + '_atlas.png')]
        g['samplers'] = [dict(magFilter=9728, minFilter=9728, wrapS=33071, wrapT=33071)]
        g['textures'] = [dict(source=0, sampler=0)]
    with open(path_base + '.bin', 'wb') as f:
        f.write(blob)
    with open(path_base + '.gltf', 'w', encoding='utf-8') as f:
        json.dump(g, f, indent=1)
    return g, bytes(blob)


def check_gltf(g, blob, parts, errors):
    """Đọc lại .bin: tổng số tam giác khớp TMD, chỉ số trong phạm vi, min/max POSITION đúng."""
    ntri = 0
    for m in g['meshes']:
        for p in m['primitives']:
            ia = g['accessors'][p['indices']]; iv = g['bufferViews'][ia['bufferView']]
            idx = np.frombuffer(blob, np.uint32, ia['count'], iv['byteOffset'])
            pa = g['accessors'][p['attributes']['POSITION']]; pv = g['bufferViews'][pa['bufferView']]
            pos = np.frombuffer(blob, np.float32, pa['count'] * 3, pv['byteOffset']).reshape(-1, 3)
            if idx.max() >= pa['count']:
                errors.append('gltf %s: chi so %d >= %d' % (m['name'], idx.max(), pa['count']))
            if not np.allclose(pos.min(0), pa['min']) or not np.allclose(pos.max(0), pa['max']):
                errors.append('gltf %s: min/max POSITION sai' % m['name'])
            ntri += ia['count'] // 3
    want = sum(2 if f['quad'] else 1 for p in parts for f in p['faces'])
    if ntri != want:
        errors.append('gltf: %d tam giac, TMD %d' % (ntri, want))
    return ntri


def write_obj(outdir, name, parts, flip, W, Htot, has_atlas):
    os.makedirs(os.path.join(outdir, 'parts'), exist_ok=True)
    with open(os.path.join(outdir, name + '.mtl'), 'w') as f:
        if has_atlas:
            f.write('newmtl tex\nKd 1 1 1\nmap_Kd %s_atlas.png\n' % name)
        f.write('newmtl vcol\nKd 1 1 1\n')
    posed = ['mtllib %s.mtl' % name]
    pbase = [1, 1, 1]
    for part in parts:
        R = np.array(part['kf0_matrix']); T = np.array(part['kf0_trans'], float)
        Rg = C @ R @ C; Tg = C @ T
        local = ['mtllib ../%s.mtl' % name]
        lb = [1, 1, 1]
        groups = []
        for layer in ('base', 'decal', 'back'):
            cl = corner_lists(part, flip, W, Htot, layer)
            if layer == 'base' or cl:
                groups.append((part['name'] + ('' if layer == 'base' else '_' + layer), cl))
        for gname, cl in groups:
            local.append('o %s' % gname)
            posed.append('o %s' % gname)
            for mat, d in cl.items():
                P = np.array(d['P']); N = np.array(d['N'])
                for out, base, PP, NN in ((local, lb, P, N), (posed, pbase, P @ Rg.T + Tg, N @ Rg.T)):
                    for k, p in enumerate(PP):
                        if mat == 'vcol':
                            c = d['Col'][k]
                            out.append('v %.3f %.3f %.3f %.4f %.4f %.4f' % (p[0], p[1], p[2], c[0], c[1], c[2]))
                        else:
                            out.append('v %.3f %.3f %.3f' % tuple(p))
                    for n in NN:
                        out.append('vn %.5f %.5f %.5f' % tuple(n))
                    for t in d['T']:
                        out.append('vt %.6f %.6f' % (t[0], 1.0 - t[1]))
                    out.append('usemtl %s' % mat)
                    I = d['I']
                    for k in range(0, len(I), 3):
                        out.append('f ' + ' '.join('%d/%d/%d' % (base[0] + I[k + j], base[1] + I[k + j], base[2] + I[k + j]) for j in range(3)))
                    base[0] += len(PP); base[1] += len(d['T']); base[2] += len(NN)
        with open(os.path.join(outdir, 'parts', part['name'] + '.obj'), 'w') as f:
            f.write('\n'.join(local) + '\n')
    with open(os.path.join(outdir, name + '_posed.obj'), 'w') as f:
        f.write('\n'.join(posed) + '\n')


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('kind', choices=['battle', 'field'])
    ap.add_argument('what', help='battle: ten nhan vat (dart); field: thu muc canh (DRGN21.BIN/26)')
    ap.add_argument('obj', nargs='?', type=int, default=0, help='field: chi so sobj')
    ap.add_argument('--form', default='combat')
    ap.add_argument('--anim', default='0')
    ap.add_argument('--name')
    ap.add_argument('--game', default=os.path.join(ROOT, 'game', 'files'))
    ap.add_argument('--out')
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    errors = []
    if a.kind == 'battle':
        objs, kf0, tim, vram, origin, src = load_battle(a.game, a.what, a.form, a.anim, errors)
        name = a.name or '%s_battle' % a.what
    else:
        objs, kf0, tim, vram, origin, src = load_field(a.game, a.what, a.obj, errors)
        name = a.name or 'field_%s_%d' % (a.what.replace('/', '_').replace('.BIN', ''), a.obj)
    atlas = build_atlas(objs, tim, vram, origin, errors)
    parts, winding = build_parts(objs, kf0, atlas, errors)
    # chiều vòng: geo_normal của vòng [2,1,0] cùng chiều pháp tuyến TMD -> giữ; ngược -> lật khi xuất
    flip = winding[1] > winding[0]
    ntri = sum(2 if f['quad'] else 1 for p in parts for f in p['faces'])
    nquad = sum(1 for p in parts for f in p['faces'] if f['quad'])
    W, Htot = (atlas[2], atlas[0].shape[0]) if atlas else (1, 1)
    summary = dict(name=name, kind=a.kind, source=src, parts=len(parts), verts=sum(len(p['verts']) for p in parts),
                   prims=sum(len(p['faces']) for p in parts), quads=nquad, tris=ntri,
                   untextured=sum(1 for p in parts for f in p['faces'] if not f['textured']),
                   winding_tmd_vs_loop=dict(same=winding[0], opposite=winding[1]), loop_reversed_for_outward=flip,
                   atlas=atlas[4] if atlas else None)
    if not a.check:
        out = a.out or os.path.join(ROOT, 'work', 'upscale', 'remodel', name)
        os.makedirs(out, exist_ok=True)
        if atlas:
            Image.fromarray(atlas[0], 'RGBA').save(os.path.join(out, name + '_atlas.png'))
            Image.fromarray(pad_transparent(atlas[0]), 'RGBA').save(os.path.join(out, name + '_atlas_pad.png'))
        doc = dict(summary, coord='PS1 raw: x right, y down, z forward-in; part posed = kf0_matrix @ v + kf0_trans',
                   atlas_size=[W, Htot], parts=parts)
        with open(os.path.join(out, name + '.json'), 'w', encoding='utf-8') as f:
            json.dump(doc, f)
        g, blob = write_gltf(os.path.join(out, name), name, parts, flip, W, Htot, atlas is not None)
        check_gltf(g, blob, parts, errors)
        write_obj(out, name, parts, flip, W, Htot, atlas is not None)
        summary['out'] = rel(out)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if errors:
        print('LOI (%d):' % len(errors))
        for e in errors[:50]:
            print('  ' + e)
        sys.exit(1)
    print('DAT: %s %d phan, %d tam giac (%d quad), atlas %s' % (name, len(parts), ntri, nquad, '%dx%d' % (W, Htot) if atlas else '-'))


if __name__ == '__main__':
    main()
