"""synth_cube.py — mô hình tổng hợp (KHÔNG phải dữ liệu Sony) cho 'LRM spec 1': CContainer 2 phần + TIM 4bpp + 2 atlas,
sinh sample_cube.lrm và sample_cube.json (giá trị mong đợi) để R1 / R2 / P1 / A1 kiểm độc lập.

Cách gọi (từ gốc repo; PYTHONIOENCODING=utf-8):
  python tools/sc_remaster/spec/synth_cube.py            ghi lại tools/sc_remaster/spec/sample_cube.{lrm,json}
  python tools/sc_remaster/spec/synth_cube.py --check    dựng lại trong bộ nhớ, so từng byte với file đã có (exit 0/1)
  python tools/sc_remaster/spec/synth_cube.py --out DIR  ghi thêm bộ file đầy đủ vào DIR:
        DIR/synth/cube.ccontainer, tim_A..tim_E.tim, atlas_0.png, atlas_1.png
        DIR/remaster/index.tsv, models/<modelKey>.lrm, textures/<sha1>.png   (cây thư mục như trong <game>/)
        DIR/remaster.properties                                              (enabled=true, textures=hd, log=true)

Mô hình (ngữ cảnh runtime: 'SobjModel (index 0)', tw = th = 0, UvAdjustmentMetrics14(0, 576, 256) như ô sobj 0;
TIM đặt như export_tmd.py load_field: ảnh (576,256) 8x32 word = 32x32 texel 4bpp, CLUT (576,368) 16x2):
  phần 0 'cube' (L0 identity trong LRM): GT4 có texture (CLUT hàng 0 / 1), GT3 x2 (cùng run), GT4 trong mờ abr 1,
     G4 không texture có gradation (4 màu), G3 không texture có đèn x2, GT3 không đèn có texture (màu x2),
     GT3 trên vùng hoạt cảnh texture (LIVE quy tắc b), GT3 đọc ngoài TIM (faceHash 0, LIVE quy tắc d).
  phần 1 'plate' (chia một lần trong LRM): GT4 nền + GT4 đề can (cùng tập đỉnh, cùng chiều) + GT4 mặt sau (cùng tập đỉnh,
     ngược chiều, thứ tự góc 1,0,3,2), GT3 trong mờ abr 1, G4 không texture, G3 không texture trong mờ (lớp
     'untextured translucent', backfaceCulling = false).
  CContainer +8: subfile2 7 mục; mục 0 = rect hoạt cảnh texture x+2, y+16, w 8/4 = 2 word, h 8 (đè đúng một mặt).
Biến thể LRM: 0 = TIM A, 1 = TIM B (đổi màu CLUT hàng 0; atlas 128x256 xếp hai khối CLUT theo thứ tự ngược với biến thể 0
nên atlasUv hai biến thể khác nhau). TIM kiểm thêm: C (CLUT khác) và D (ảnh lệch 1 texel) không
khớp biến thể nào; E = A với texel trong rect hoạt cảnh bị đổi -> vẫn khớp biến thể 0 (mặt đó LIVE).
Mọi giá trị mong đợi tính bằng ref_spec.py (cùng thư mục); file ghi ra xác định (PNG dùng khối deflate 'stored').
"""
import argparse
import hashlib
import json
import math
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ref_spec as R  # noqa: E402  (tham chiếu cùng thư mục)

ROOT = R.ROOT
LRM_PATH = os.path.join(HERE, 'sample_cube.lrm')
JSON_PATH = os.path.join(HERE, 'sample_cube.json')
GENERATOR = 'synth_cube 1'
SLOT_X, SLOT_Y = R.FIELD_SLOT0
ANIM = dict(x=2, y=16, w=8, h=8)            # animationMetrics_d0[0][1..4] (w theo texel 4bpp: w/4 = 2 word)
ATLAS_W, ATLAS_H = 128, 256                 # 4x của 32x32, hai khối CLUT hàng 0 / 1 xếp dọc


# ---------------------------------------------------------------- TIM tổng hợp
def c15(r, g, b, stp=0):
    return (r & 31) | (g & 31) << 5 | (b & 31) << 10 | (0x8000 if stp else 0)


def clut_rows():
    """Hai hàng CLUT 16 màu: 0 = trong suốt (0x0000), 1..12 đục, 13..15 có bit STP (13 = đen STP)."""
    rows = []
    for row in range(2):
        cl = [0]
        for i in range(1, 13):
            cl.append(c15((i * 5 + row * 11) % 30 + 1, (i * 9 + 7 + row * 3) % 30 + 1, (i * 13 + 3 + row * 17) % 30 + 1))
        cl.append(c15(0, 0, 0, 1))
        cl.append(c15(20 + row, 4, 9, 1))
        cl.append(c15(6, 18 + row, 27, 1))
        rows.append(cl)
    return rows


def base_index(u, v):
    if 24 <= u <= 31 and 16 <= v <= 31:                 # vùng STP (mặt trong mờ)
        return 13 + (u + v) % 3
    if 16 <= u <= 23 and 16 <= v <= 23:                 # đề can: hình thoi đục, ngoài là trong suốt
        return 5 + (u + v) % 4 if abs(u - 19.5) + abs(v - 19.5) <= 3 else 0
    if 8 <= u <= 15 and 16 <= v <= 23:                  # vùng hoạt cảnh
        return 2 + ((u ^ v) % 9)
    return 1 + ((u * 7 + v * 3) // 2) % 12


def make_indices(kind):
    idx = np.zeros((32, 32), np.uint8)
    for v in range(32):
        for u in range(32):
            if kind == 'D':
                k = base_index((u - 1) % 32, v)
            else:
                k = base_index(u, v)
                if kind == 'E' and 8 <= u <= 15 and 16 <= v <= 23:
                    k = (k + 3) % 12 + 1
            idx[v, u] = k
    return idx


def make_clut(kind):
    rows = clut_rows()
    if kind in ('B', 'C'):
        r0 = [0]
        for c in rows[0][1:]:
            r, g, b, s = c & 31, c >> 5 & 31, c >> 10 & 31, c >> 15
            r0.append(c15(g, b, r, s) if kind == 'B' else c15(31 - r, 31 - g, (b + 9) % 32, s))
        rows = [r0, rows[1]]
    return rows


def tim_bytes(kind):
    """TIM 4bpp: CLUT rect (0,112,16,2) rồi ảnh rect (0,0,8,32) như TIM sobj trường (rect tương đối)."""
    idx = make_indices(kind)
    words = np.zeros((32, 8), np.uint16)
    for v in range(32):
        for w in range(8):
            q = idx[v, w * 4:w * 4 + 4]
            words[v, w] = int(q[0]) | int(q[1]) << 4 | int(q[2]) << 8 | int(q[3]) << 12
    clut = np.array(make_clut(kind), '<u2')
    out = struct.pack('<II', 0x10, 0x8)
    out += struct.pack('<IHHHH', 12 + clut.nbytes, 0, 112, 16, 2) + clut.tobytes()
    out += struct.pack('<IHHHH', 12 + words.nbytes, 0, 0, 8, 32) + words.astype('<u2').tobytes()
    return out


# ---------------------------------------------------------------- CContainer tổng hợp
def tpage_raw(abr=0):
    return abr << 5          # 4bpp; bit trang bị UvAdjustmentMetrics14 thay bằng ô


def clut_raw(row):
    return row << 6           # x = 0, hàng CLUT tương đối (giữ bởi mặt nạ 0x3c3ffff)


def colour(r, g, b, code=0):
    return r | g << 8 | b << 16 | code << 24


def tex_block(uvs, row, abr=0):
    """Phần uv/clut/tpage của gói có texture: (u v clut) (u v tpage) (u v 00 00) [(u v 00 00)]."""
    out = b''
    for k, (u, v) in enumerate(uvs):
        extra = clut_raw(row) if k == 0 else tpage_raw(abr) if k == 1 else 0
        out += struct.pack('<BBH', u, v, extra)
    return out


def packet(mode, flag, body):
    size = R.packet_size(mode << 24 | flag << 16)
    assert len(body) <= size, (hex(mode), len(body), size)
    body = body + b'\0' * (size - len(body))
    assert R.ilen_step(mode, flag) == 4 + size, hex(mode)
    return struct.pack('<BBBB', size // 4, size // 4, flag, mode) + body


def nv_pairs(nidx, vidx, gour=True):
    out = b''
    for k, v in enumerate(vidx):
        if nidx is not None and (gour or k == 0):
            out += struct.pack('<H', nidx[k])
        out += struct.pack('<H', v)
    return out


CUBE_VERTS = [(-64, -64, -64), (64, -64, -64), (-64, 64, -64), (64, 64, -64),
              (-64, -64, 64), (64, -64, 64), (-64, 64, 64), (64, 64, 64)]
CUBE_NORMALS = [(0, 0, -4096), (4096, 0, 0), (0, -4096, 0), (-4096, 0, 0), (0, 4096, 0), (0, 0, 4096),
                (2896, -2896, 0), (0, 2896, -2896)]


def cube_packets():
    """(mode, flag, body, mô tả) theo thứ tự gói TMD của phần 0."""
    P = []
    # 0: GT4 trước (z-), CLUT 0, vùng u0..15 v0..15
    P.append((0x3c, 0, tex_block([(0, 0), (15, 0), (0, 15), (15, 15)], 0) + nv_pairs([0, 0, 0, 0], [0, 1, 2, 3]),
              'GT4 textured, CLUT row 0'))
    # 1: GT4 phải (x+), CLUT 1, vùng u16..31 v0..15
    P.append((0x3c, 0, tex_block([(16, 0), (31, 0), (16, 15), (31, 15)], 1) + nv_pairs([1, 1, 1, 1], [1, 5, 3, 7]),
              'GT4 textured, CLUT row 1'))
    # 2, 3: GT3 trên (y-) x2, CLUT 0, vùng u0..7 v16..23
    P.append((0x34, 0, tex_block([(0, 16), (7, 16), (0, 23)], 0) + nv_pairs([2, 2, 2], [4, 5, 0]), 'GT3 textured'))
    P.append((0x34, 0, tex_block([(7, 16), (7, 23), (0, 23)], 0) + nv_pairs([2, 6, 2], [5, 1, 0]), 'GT3 textured'))
    # 4: GT4 trái (x-) trong mờ abr 1, vùng STP u24..31 v16..31
    P.append((0x3e, 0, tex_block([(24, 16), (31, 16), (24, 31), (31, 31)], 0, abr=1) + nv_pairs([3, 3, 3, 3], [4, 0, 6, 2]),
              'GT4 textured translucent abr 1'))
    # 5: G4 dưới (y+) không texture, gradation 4 màu
    P.append((0x38, 4, struct.pack('<IIII', colour(200, 40, 40, 0x38), colour(40, 200, 40, 0x38),
                                   colour(40, 40, 200, 0x38), colour(220, 220, 30, 0x38))
              + nv_pairs([4, 4, 4, 4], [2, 3, 6, 7]), 'G4 untextured gradated lit'))
    # 6, 7: G3 sau (z+) không texture có đèn, một màu
    P.append((0x30, 0, struct.pack('<I', colour(90, 120, 150, 0x30)) + nv_pairs([5, 5, 5], [5, 4, 7]),
              'G3 untextured lit'))
    P.append((0x30, 0, struct.pack('<I', colour(150, 90, 60, 0x30)) + nv_pairs([5, 7, 5], [4, 6, 7]),
              'G3 untextured lit'))
    # 8: GT3 không đèn có texture: 3 màu (x2), CLUT 1, vùng u0..7 v24..31
    P.append((0x35, 1, tex_block([(0, 24), (7, 24), (0, 31)], 1)
              + struct.pack('<III', colour(128, 64, 32, 0x35), colour(255, 128, 0, 0x35), colour(10, 128, 250, 0x35))
              + nv_pairs(None, [1, 4, 6]), 'GT3 textured unlit (colour x2)'))
    # 9: GT3 trên vùng hoạt cảnh texture -> LIVE (quy tắc b)
    P.append((0x34, 0, tex_block([(8, 16), (15, 16), (8, 23)], 0) + nv_pairs([6, 6, 6], [0, 5, 3]),
              'GT3 textured inside texture-animation rect (LIVE b)'))
    # 10: GT3 đọc ngoài TIM (v 40..47) -> faceHash 0 trong mọi biến thể (LIVE d)
    P.append((0x34, 0, tex_block([(0, 40), (7, 40), (0, 47)], 0) + nv_pairs([7, 7, 7], [2, 7, 4]),
              'GT3 textured outside the TIM (faceHash 0, LIVE d)'))
    return P


PLATE_VERTS = [(-32, -32, 0), (32, -32, 0), (-32, 32, 0), (32, 32, 0),
               (0, -32, -40), (-32, 32, -40), (32, 32, -40),
               (-32, 48, 0), (32, 48, 0), (-32, 48, -40), (32, 48, -40)]
PLATE_NORMALS = [(0, 0, -4096), (0, 0, 4096), (0, -4096, 0), (0, 4096, 0), (-2896, 0, -2896), (2896, 0, -2896)]


def plate_packets():
    P = []
    # 0: nền GT4, CLUT 0, vùng u16..31 v0..15
    P.append((0x3c, 0, tex_block([(16, 0), (31, 0), (16, 15), (31, 15)], 0) + nv_pairs([0, 0, 0, 0], [0, 1, 2, 3]),
              'GT4 base'))
    # 1: đề can: cùng thứ tự góc, vùng đề can u16..23 v16..23 (texel trong suốt)
    P.append((0x3c, 0, tex_block([(16, 16), (23, 16), (16, 23), (23, 23)], 0) + nv_pairs([0, 0, 0, 0], [0, 1, 2, 3]),
              'GT4 decal (same vertex set and winding)'))
    # 2: mặt sau: thứ tự góc (1,0,3,2), CLUT 1, vùng u0..15 v0..15
    P.append((0x3c, 0, tex_block([(15, 0), (0, 0), (15, 15), (0, 15)], 1) + nv_pairs([1, 1, 1, 1], [1, 0, 3, 2]),
              'GT4 back (same vertex set, reversed winding)'))
    # 3: GT3 trong mờ abr 1, vùng STP
    P.append((0x36, 0, tex_block([(24, 16), (31, 16), (24, 23)], 0, abr=1) + nv_pairs([4, 5, 2], [4, 6, 5]),
              'GT3 textured translucent abr 1'))
    # 4: G4 không texture có đèn (một màu)
    P.append((0x38, 0, struct.pack('<I', colour(70, 160, 90, 0x38)) + nv_pairs([3, 3, 3, 3], [7, 8, 9, 10]),
              'G4 untextured lit'))
    # 5: G3 không texture trong mờ -> lớp 'untextured translucent', backfaceCulling = false
    P.append((0x32, 0, struct.pack('<I', colour(250, 250, 250, 0x32)) + nv_pairs([2, 2, 2], [4, 7, 8]),
              'G3 untextured translucent'))
    return P


PART_SPECS = [('cube', CUBE_VERTS, CUBE_NORMALS, cube_packets), ('plate', PLATE_VERTS, PLATE_NORMALS, plate_packets)]


def ccontainer_bytes():
    """CContainer: +0 TMD, +4 0 (không có hoạt cảnh CLUT), +8 subfile2; TmdWithId id 0x41; TMD flags 0, 2 đối tượng."""
    tmd_off = 0x0c
    objtab = tmd_off + 4 + 8            # bảng đối tượng; offset trong bảng tính từ đây
    blobs = []
    rel = 2 * 0x1c
    table = b''
    for _name, verts, normals, pk in PART_SPECS:
        vb = b''.join(struct.pack('<hhhh', *v, 0) for v in verts)
        nb = b''.join(struct.pack('<hhhh', *n, 0) for n in normals)
        pb = b''.join(packet(m, f, body) for m, f, body, _ in pk())
        vtop, ntop, ptop = rel, rel + len(vb), rel + len(vb) + len(nb)
        table += struct.pack('<IIIIIIi', vtop, len(verts), ntop, len(normals), ptop, len(pk()), 0)
        blobs.append(vb + nb + pb)
        rel = ptop + len(pb)
    tmd = struct.pack('<III', 0x41, 0, 2) + table + b''.join(blobs)
    sub_off = tmd_off + len(tmd)
    entries = [[0x4001, ANIM['x'], ANIM['y'], ANIM['w'], ANIM['h'], 1, 16, -1]] + [[1, -1]] * 6
    eoff = 7 * 4
    head = b''
    body = b''
    for e in entries:
        head += struct.pack('<I', eoff + len(body))
        body += struct.pack('<%dh' % len(e), *[x - 0x10000 if x > 0x7fff else x for x in e])
    sub = head + body
    out = struct.pack('<III', tmd_off, 0, sub_off) + tmd + sub
    return out + b'\0' * (-len(out) % 4)


# ---------------------------------------------------------------- dựng LRM
def unorm(x):
    return int(math.floor(x * 65535 + 0.5))


def orient_cw(tri_st):
    """Thứ tự góc sao cho diện tích có dấu trong không gian (s,t) < 0 — cùng chiều tam giác (2,1,0) của SC."""
    (a, b, c) = tri_st
    area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (a, b, c) if area < 0 else (a, c, b)


def sub_points(quad):
    """Điểm (s,t) của một lần chia và các tam giác con (theo chỉ số điểm), chiều như SC."""
    if quad:
        pts = [(i / 2, j / 2) for j in range(3) for i in range(3)]
        g = lambda i, j: j * 3 + i  # noqa: E731
        tris = []
        for j in range(2):
            for i in range(2):
                p00, p10, p01, p11 = g(i, j), g(i + 1, j), g(i, j + 1), g(i + 1, j + 1)
                tris += [(p01, p10, p00), (p10, p01, p11)]
        return pts, tris
    pts = [(0, 0), (0.5, 0), (1, 0), (0, 0.5), (0.5, 0.5), (0, 1)]
    raw = [(0, 1, 3), (1, 2, 4), (3, 4, 5), (4, 3, 1)]
    tris = []
    for t in raw:
        st = orient_cw(tuple(pts[i] for i in t))
        tris.append(tuple(pts.index(p) for p in st))
    return pts, tris


def weights64(s, t, quad):
    if quad:
        return [(1 - s) * (1 - t), s * (1 - t), (1 - s) * t, s * t]
    return [1 - s - t, s, t]


def unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return [c / n for c in v] if n > 0 else [0.0, 0.0, 0.0]


def face_geo_normal(P):
    """Pháp tuyến hình học của tam giác TMD (2,1,0) (chiều SC)."""
    a, b, c = np.array(P[2], float), np.array(P[1], float), np.array(P[0], float)
    return unit(np.cross(b - a, c - a).tolist())


def corner_rec(pos, n, src, S, T, near, role):
    return (pos, tuple(float(x) for x in n), src, S, T, near, role)


def identity_part(part, faces, key):
    """L0 identity: góc = góc TMD (s,t trong {0,1}), vị trí = đỉnh TMD, near = chỉ số đỉnh, pháp tuyến TMD
    (mặt không đèn: lưu pháp tuyến hình học khác 0 để kiểm runtime đặt 0)."""
    pos = [list(v) for v in part.verts]
    corners, tris = [], []
    st = [(0, 0), (65535, 0), (0, 65535), (65535, 65535)]
    for f in faces:
        base = len(corners)
        P = [part.verts[v] for v in f.vidx]
        for k in range(f.vc):
            if f.lit:
                ni = f.nidx[k]
                n = [c / 4096.0 for c in part.normals[ni]] if ni < len(part.normals) else [0.0, 0.0, 0.0]
            else:
                n = face_geo_normal(P)
            corners.append(corner_rec(f.vidx[k], n, f.index, st[k][0], st[k][1], f.vidx[k], 0))
        tris.append((base + 2, base + 1, base))
        if f.quad:
            tris.append((base + 1, base + 2, base + 3))
    return lrm_part(key, len(faces), pos, corners, tris)


def subdivided_part(part, faces, key, roles):
    """Chia một lần; đề can / mặt sau dùng lại đúng vị trí của mặt nền (chỉ số pos chung), mặt sau đảo chiều, pháp tuyến
    đảo dấu, (s,t) đổi sang khung góc riêng ((1,0,3,2): s' = 65535 - S)."""
    pos = [[float(c) for c in v] for v in part.verts]
    corners, tris = [], []
    base_cache = {}
    for f in faces:
        P = [part.verts[v] for v in f.vidx]
        pts, sub = sub_points(f.quad)
        role = roles.get(f.index, ('base', None))
        if role[0] == 'base':
            gn = face_geo_normal(P)
            pidx, nrm, near, STs = [], [], [], []
            for (s, t) in pts:
                w = weights64(s, t, f.quad)
                corner_k = [k for k in range(f.vc) if abs(w[k] - 1) < 1e-12]
                if corner_k:
                    pidx.append(f.vidx[corner_k[0]])
                else:
                    p = [sum(w[k] * P[k][c] for k in range(f.vc)) + 4.0 * gn[c] for c in range(3)]
                    pidx.append(len(pos))
                    pos.append([float(np.float32(x)) for x in p])
                if f.lit:
                    nn = [sum(w[k] * part.normals[f.nidx[k]][c] for k in range(f.vc)) / 4096.0 for c in range(3)]
                    nrm.append(unit(nn))
                else:
                    nrm.append(gn)
                near.append(f.vidx[max(range(f.vc), key=lambda k: (w[k], -k))])
                STs.append((unorm(s), unorm(t)))
            base_cache[f.index] = (pidx, nrm, near, STs, sub)
            b0 = len(corners)
            for i in range(len(pts)):
                corners.append(corner_rec(pidx[i], nrm[i], f.index, STs[i][0], STs[i][1], near[i], 0))
            tris += [(b0 + a, b0 + b, b0 + c) for a, b, c in sub]
        else:
            kind, base_face = role
            pidx, nrm, near, STs, sub = base_cache[base_face]
            b0 = len(corners)
            for i in range(len(pidx)):
                if kind == 'decal':
                    corners.append(corner_rec(pidx[i], nrm[i], f.index, STs[i][0], STs[i][1], near[i], 1))
                else:
                    corners.append(corner_rec(pidx[i], [-c for c in nrm[i]], f.index, 65535 - STs[i][0], STs[i][1],
                                              near[i], 2))
            if kind == 'decal':
                tris += [(b0 + a, b0 + b, b0 + c) for a, b, c in sub]
            else:
                tris += [(b0 + a, b0 + c, b0 + b) for a, b, c in sub]
    return lrm_part(key, len(faces), pos, corners, tris)


def lrm_part(key, nfaces, pos, corners, tris):
    arr = np.zeros(len(corners), R.CORNER_DT)
    for i, (p, n, src, S, T, near, role) in enumerate(corners):
        arr[i]['pos'], arr[i]['n'], arr[i]['src'] = p, n, src
        arr[i]['s'], arr[i]['t'], arr[i]['near'], arr[i]['role'] = S, T, near, role
    tri = np.array(tris, '<u4').reshape(-1, 3)
    order = np.argsort(arr['src'][tri[:, 0].astype(np.int64)], kind='stable')
    return R.LrmPart(key, nfaces, 1, np.array(pos, '<f4'), arr, tri[order])


# ---------------------------------------------------------------- atlas
def block_y(row, swap):
    """Atlas file 128x256: khối của CLUT hàng r ở y = 128 r (biến thể 0) hoặc 128 (1 - r) (biến thể 1, bố cục đảo để
    atlasUv hai biến thể khác nhau)."""
    return 128 * ((1 - row) if swap else row)


def atlas_rgba(kind, swap):
    """Texel (u,v) của CLUT hàng r -> ô 4x4 tại (4u, 4v + block_y(r)); quy ước alpha SPEC §3.6.1."""
    idx = make_indices(kind)
    rows = make_clut(kind)
    img = np.zeros((ATLAS_H, ATLAS_W, 4), np.uint8)
    for r in range(2):
        by = block_y(r, swap)
        for v in range(32):
            for u in range(32):
                c = rows[r][idx[v, u]]
                if c == 0:
                    px = (0, 0, 0, 0)
                else:
                    ex = lambda x: (x << 3) | (x >> 2)  # noqa: E731
                    px = (ex(c & 31), ex(c >> 5 & 31), ex(c >> 10 & 31), 128 if c & 0x8000 else 255)
                img[by + 4 * v: by + 4 * v + 4, 4 * u: 4 * u + 4] = px
    return img


def atlas_uv(tex_faces, swap):
    """atlasUv chuẩn hoá theo thứ tự góc TMD; tam giác: góc thứ 4 = 0."""
    out = np.zeros((len(tex_faces), 4, 2), np.float32)
    for g, f in enumerate(tex_faces):
        row = (f.clut >> 6) - (SLOT_Y + 112)
        for k, (u, v) in enumerate(f.uv):
            out[g, k] = (4 * u / ATLAS_W, (4 * v + block_y(row, swap)) / ATLAS_H)
    return np.clip(out, 0, 1)


# ---------------------------------------------------------------- dựng toàn bộ
def mesh_json(m):
    v = m['vertices']
    i = m['indices']
    return dict(cls=m['cls'], textured=m['textured'], translucent=m['translucent'], translucency=m['translucency'],
                vertexCount=len(v) // 16, indexCount=len(i),
                verticesSha1=R.sha1_hex(v.astype('<f4').tobytes()), indicesSha1=R.sha1_hex(i.astype('<u4').tobytes()),
                vertices=[float(x) for x in v], indices=[int(x) for x in i])


def build():
    cc = ccontainer_bytes()
    tims = {k: tim_bytes(k) for k in 'ABCDE'}
    # mô hình runtime: CContainer -> UvAdjust ô 0 (Models.adjustModelUvs) -> fromModel
    model = R.parse_ccontainer(cc)
    mkey, pkeys = R.model_keys(model)
    R.uv_adjust_model(model, SLOT_X, SLOT_Y)
    assert R.model_keys(model)[0] == mkey, 'khoa doi sau UvAdjust'
    decoded = [R.decode_faces(p) for p in model.parts]
    all_faces = [d[0] for d in decoded]
    tex = R.textured_faces(all_faces)
    model_live = R.live_set(model, all_faces)

    vrams, places = {}, {}
    for k, b in tims.items():
        vram = R.new_vram()
        places[k] = R.place_field_slot0(vram, R.parse_tim(b))
        vrams[k] = vram
    raw = {k: R.hash_vector(vrams[k], all_faces) for k in tims}
    gen = {k: R.generator_hashes(vrams[k], all_faces, *places[k]) for k in ('A', 'B')}

    swap = dict(A=False, B=True)
    atlases = {k: atlas_rgba(k, swap[k]) for k in ('A', 'B')}
    pngs = {k: R.png_write_rgba(atlases[k]) for k in atlases}
    variants = [R.LrmVariant(hashlib.sha1(pngs[k]).digest(), ATLAS_W, ATLAS_H, gen[k], atlas_uv(tex, swap[k]))
                for k in ('A', 'B')]

    roles = {1: ('decal', 0), 2: ('back', 0)}
    parts = [identity_part(model.parts[0], all_faces[0], pkeys[0]),
             subdivided_part(model.parts[1], all_faces[1], pkeys[1], roles)]
    lrm = R.Lrm(mkey, parts, variants, level=1, generator=GENERATOR, deflate=False)
    lrm_bytes = R.write_lrm(lrm)
    runtime = dict(src_face_counts=[len(f) for f in all_faces], n_verts=[len(p.verts) for p in model.parts],
                   textured=len(tex))
    back = R.read_lrm(lrm_bytes, expect_key=mkey, runtime=runtime)
    assert R.write_lrm(back) == lrm_bytes

    # kỳ vọng xác minh (SPEC §4.4)
    var_hashes = [list(v.face_hash) for v in variants]
    verify = {}
    for k in tims:
        verify[k] = R.verify_variants(raw[k], var_hashes, model_live)
    expect = dict(A=0, B=1, C=None, D=None, E=0)
    assert verify == expect, verify
    g_live_b = sorted(model_live)
    assert R.verify_variants(raw['E'], [var_hashes[0]], set()) is None, 'E phai truot neu khong co LIVE'
    assert raw['A'][g_live_b[0]] != raw['E'][g_live_b[0]]

    # lưới: retail, bộ VRAM, bộ ATLAS mỗi biến thể
    sets = dict(retail=[], vram=[], atlas=[[], []])
    tex_base = 0
    for pi, (part, (faces, bf)) in enumerate(zip(model.parts, decoded)):
        retail = R.build_retail(part, faces, bf)
        sets['retail'].append(dict(backfaceCulling=retail['backfaceCulling'], meshes=[mesh_json(m) for m in retail['meshes']]))
        vr = R.build_remaster_part(faces, bf, parts[pi], tex_base=tex_base)
        sets['vram'].append(dict(backfaceCulling=vr['backfaceCulling'], meshes=[mesh_json(m) for m in vr['meshes']]))
        if pi == 0:          # L0 identity: bộ VRAM == retail trừ QUAD_FLAG (chỉ số khác: [a,a,b,a,c,a])
            assert [m['cls'] for m in vr['meshes']] == [m['cls'] for m in retail['meshes']]
            for mr, mv in zip(retail['meshes'], vr['meshes']):
                a = mr['vertices'].reshape(-1, 16).copy()
                a[:, 15] = np.float32([int(x) & ~R.QUAD_FLAG for x in a[:, 15]])
                assert np.array_equal(a.view(np.uint32), mv['vertices'].reshape(-1, 16).view(np.uint32)), mr['cls']
        for vi, v in enumerate(variants):
            live = R.effective_live(model_live, list(v.face_hash))
            at = R.build_remaster_part(faces, bf, parts[pi], atlas=v.atlas_uv, live=live, tex_base=tex_base)
            sets['atlas'][vi].append(dict(backfaceCulling=at['backfaceCulling'],
                                          meshes=[mesh_json(m) for m in at['meshes']]))
        tex_base += sum(1 for f in faces if f.textured)

    # mô tả mặt
    desc = []
    g = 0
    for pi, (faces, (_n, _v, _no, pk)) in enumerate(zip(all_faces, PART_SPECS)):
        notes = [d for _m, _f, _b, d in pk()]
        fl = []
        for f in faces:
            e = dict(srcFace=f.index, header='%08x' % f.header, note=notes[f.index], quad=f.quad, textured=f.textured,
                     translucent=f.translucent, lit=f.lit, coloured=f.coloured, flags=f.flags,
                     meshClass=R.class_name(f.mclass), vertexIndices=f.vidx)
            if f.textured:
                e.update(texturedFaceIndex=g, tpage=f.tpage, clut=f.clut, uv=[list(x) for x in f.uv],
                         footprint=list(R.footprint(f)))
                g += 1
            fl.append(e)
        desc.append(dict(name=PART_SPECS[pi][0], srcFaceCount=len(faces), partKey=pkeys[pi].hex(),
                         backfaceCulling=decoded[pi][1], faces=fl,
                         lrm=dict(mode=1, P=len(parts[pi].pos), C=len(parts[pi].corners), T=len(parts[pi].tri),
                                  kind='L0 identity' if pi == 0 else 'subdivided once')))

    hx = lambda hs: ['%08x' % h for h in hs]  # noqa: E731
    doc = dict(
        format='sample_cube 1', spec='LRM spec 1 (tools/sc_remaster/SPEC.md)', generator='tools/sc_remaster/spec/synth_cube.py',
        note='Mo hinh tong hop, khong phai du lieu Sony. Float = gia tri f32 chinh xac (JSON double); verticesSha1 = '
             'SHA-1 cua f32 LE, indicesSha1 = SHA-1 cua u32 LE.',
        runtime=dict(name='SobjModel (index 0)', textureWidth=0, textureHeight=0,
                     uvAdjust='UvAdjustmentMetrics14(0, %d, %d) via Models.adjustModelUvs' % (SLOT_X, SLOT_Y),
                     tpageX=SLOT_X, tpageY=SLOT_Y, clutAnimations=False,
                     timPlacement='image at (%d,%d), CLUT at (%d,%d) (export_tmd.py load_field)' % (
                         SLOT_X, SLOT_Y, SLOT_X, SLOT_Y + 112),
                     texAnimRects=[list(r) for r in R.anim_rects(model)]),
        files=dict(ccontainer=dict(sha1=R.sha1_hex(cc), size=len(cc), hex=cc.hex()),
                   tims={k: dict(sha1=R.sha1_hex(b), size=len(b), hex=b.hex()) for k, b in tims.items()},
                   pngs={str(i): dict(sha1=R.sha1_hex(pngs[k]), size=len(pngs[k]), w=ATLAS_W, h=ATLAS_H)
                         for i, k in enumerate(('A', 'B'))},
                   lrm=dict(path='tools/sc_remaster/spec/sample_cube.lrm', sha1=R.sha1_hex(lrm_bytes), size=len(lrm_bytes))),
        keys=dict(modelKey=mkey.hex(), partKeys=[k.hex() for k in pkeys]),
        srcFaceCount=[len(f) for f in all_faces], texturedFaceCount=len(tex), parts=desc,
        live=dict(model=sorted(model_live), byVariant=[sorted(R.effective_live(model_live, list(v.face_hash)))
                                                          for v in variants],
                  rules='model = SPEC §3.4 a-c (here: rule b); byVariant adds rule d (stored faceHash 0)'),
        faceHashes=dict(runtime={k: hx(raw[k]) for k in tims}, stored=[hx(v.face_hash) for v in variants]),
        faceHashVectorSha1={k: R.vector_sha1(raw[k]) for k in tims},
        verify=dict(expected={k: verify[k] for k in tims},
                    rule='first variant whose stored hashes match every non-LIVE textured face; null = none (VRAM set)'),
        atlas=[dict(variant=i, png=R.sha1_hex(pngs[k]), w=ATLAS_W, h=ATLAS_H,
                    runtimeMips=[dict(w=int(m.shape[1]), h=int(m.shape[0]), sha1=R.sha1_hex(m.tobytes()))
                                 for m in R.runtime_mips(atlases[k])])
               for i, k in enumerate(('A', 'B'))],
        meshes=dict(note='per part: meshes in draw order (reversed class order); retail = TmdObjLoader.fromObjTable; '
                         'vram = remaster VRAM set (GEOMETRY mode, or FULL before verification); atlas[v] = ATLAS set of '
                         'variant v', **sets),
    )
    return dict(cc=cc, tims=tims, pngs=pngs, lrm=lrm_bytes, json=json.dumps(doc, ensure_ascii=False, indent=1) + '\n',
                key=mkey.hex())


def write_out(res, out):
    syn = os.path.join(out, 'synth')
    rem = os.path.join(out, 'remaster')
    for d in (syn, os.path.join(rem, 'models'), os.path.join(rem, 'textures')):
        os.makedirs(d, exist_ok=True)
    files = {os.path.join(syn, 'cube.ccontainer'): res['cc']}
    for k, b in res['tims'].items():
        files[os.path.join(syn, 'tim_%s.tim' % k)] = b
    for i, k in enumerate(('A', 'B')):
        files[os.path.join(syn, 'atlas_%d.png' % i)] = res['pngs'][k]
        files[os.path.join(rem, 'textures', R.sha1_hex(res['pngs'][k]) + '.png')] = res['pngs'][k]
    files[os.path.join(rem, 'models', res['key'] + '.lrm')] = res['lrm']
    files[os.path.join(out, 'remaster.properties')] = b'enabled=true\ntextures=hd\nlog=true\n'
    for p, b in files.items():
        with open(p, 'wb') as f:
            f.write(b)
    tmp = os.path.join(rem, 'index.tsv.tmp')
    with open(tmp, 'wb') as f:
        f.write(R.write_index([(res['key'], 'sample_cube (tổng hợp)')]))
    os.replace(tmp, os.path.join(rem, 'index.tsv'))
    print('da ghi bo file tong hop vao %s' % out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--out')
    a = ap.parse_args()
    res = build()
    if a.check:
        ok = True
        for path, want in ((LRM_PATH, res['lrm']), (JSON_PATH, res['json'].encode('utf-8'))):
            try:
                with open(path, 'rb') as f:
                    have = f.read()
            except OSError:
                have = None
            if path == JSON_PATH and have is not None:
                have = have.replace(b'\r\n', b'\n')      # core.autocrlf=true: bản checkout có thể là CRLF
            same = have == want
            print('%s: %s' % (os.path.basename(path), 'trung' if same else 'KHAC'))
            ok &= same
        print('DAT' if ok else 'KHONG DAT')
        sys.exit(0 if ok else 1)
    with open(LRM_PATH, 'wb') as f:
        f.write(res['lrm'])
    with open(JSON_PATH, 'w', encoding='utf-8', newline='\n') as f:
        f.write(res['json'])
    print('da ghi sample_cube.lrm (%d byte, modelKey %s) va sample_cube.json' % (len(res['lrm']), res['key']))
    if a.out:
        write_out(res, a.out)


if __name__ == '__main__':
    main()
