"""preview_sc.py — ảnh xem trước kiểu Severed Chains cho mô hình remaster (gói P2): gốc | L1 | L2 cạnh nhau.

Cách gọi (từ gốc repo; chỉ numpy, không PIL; chạy được với Python hệ thống hoặc python.exe -I của Blender):
  python tools/sc_remaster/qa/preview_sc.py <model.json> <thư mục geom> <ảnh ra.png> [--views full34,back34,head]
                                            [--res 420] [--title "..."] [--atlas <atlas.png>]
  python tools/sc_remaster/qa/preview_sc.py --sheet <ảnh ra.png> <ảnh 1.png> <ảnh 2.png> ...   (ghép dọc nhiều tờ)
  python tools/sc_remaster/qa/preview_sc.py --selftest
Đầu vào: JSON lược đồ tools/sc_remodel/export_tmd.py + <tên>_atlas.png cạnh JSON (texel atlas, alpha 0 = trong suốt như
tmd.fsh), <thư mục geom>/geom_L1.npz, geom_L2.npz (lược đồ SPEC §3.8, xem blender/remaster_core.py).
Dựng hình (giống SC ở mức đủ để duyệt hình học, không phải bản sao shader):
  - tư thế khung 0 (kf0_matrix / kf0_trans của JSON), chiếu trực giao, z-buffer;
  - Gouraud theo đỉnh: màu đỉnh (x2 cho mặt có texture như TmdObjLoader) x ánh sáng (môi trường 0.45 + đèn chính 0.7 +
    đèn phụ 0.2) cho mặt có đèn (LIT); mặt không đèn chỉ màu đỉnh;
  - texture lấy mẫu gần nhất (nearest) trên atlas, bỏ texel alpha 0 (không ghi độ sâu, như discard của tmd.fsh);
  - culling mặt sau bật cho phần không có gói trong mờ không texture (quy tắc backfaceCulling của TmdObjLoader);
  - gói trong mờ vẽ sau, một lớp gần nhất, trộn theo abr (0: 50/50, 1: cộng, 2: trừ, 3: cộng 1/4);
  - đỉnh remaster: uv / màu nội suy từ gói gốc theo (srcFace, s, t) đúng công thức SPEC §3.2 (độ chính xác double);
    pháp tuyến = corner_n đã lưu.
Hàng: full34 (3/4 trước), front (chính diện), back34 (3/4 sau), head (cận đầu); cột: GOC | L1 | L2 (số tam giác, mức từng
phần ở dưới). Độ sâu lượng tử 1e-3; gói đục hoà độ sâu thì tam giác vẽ trước thắng (GL_LESS của SC), gói trong mờ thì
vẽ sau thắng (GL_LEQUAL) — mặt đề can (trùng vị trí mặt nền, srcFace nhỏ hơn) hiện đúng như trong game.
Ảnh suy ra từ đĩa: chỉ ghi dưới work/upscale/sc_remaster* (git bỏ qua), không commit, không phát hành.
"""
import argparse
import json
import math
import os
import struct
import sys
import zlib

import numpy as np

EPS = 1e-12
BG = np.array([0.42, 0.44, 0.47])


# ---------------------------------------------------------------- PNG (không PIL)
def png_write(path, rgb):
    """RGB8 hoặc RGBA8, lọc 0, zlib mức 6."""
    a = np.ascontiguousarray(np.clip(rgb, 0, 255).astype(np.uint8))
    h, w, c = a.shape
    raw = b''.join(b'\x00' + a[y].tobytes() for y in range(h))

    def chunk(k, d):
        return struct.pack('>I', len(d)) + k + d + struct.pack('>I', zlib.crc32(k + d) & 0xFFFFFFFF)
    data = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6 if c == 4 else 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)


def png_read(path):
    """PNG 8 bit không xen kẽ (xám, RGB, bảng màu, xám+alpha, RGBA) -> uint8 (H, W, 4)."""
    data = open(path, 'rb').read()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('khong phai PNG: %s' % path)
    o, idat, ihdr, plte, trns = 8, bytearray(), None, None, None
    while o < len(data):
        ln = struct.unpack_from('>I', data, o)[0]
        k = data[o + 4:o + 8]
        d = data[o + 8:o + 8 + ln]
        o += 12 + ln
        if k == b'IHDR':
            ihdr = struct.unpack('>IIBBBBB', d)
        elif k == b'PLTE':
            plte = d
        elif k == b'tRNS':
            trns = d
        elif k == b'IDAT':
            idat += d
        elif k == b'IEND':
            break
    w, h, depth, ct, _, _, inter = ihdr
    if depth != 8 or inter != 0:
        raise ValueError('PNG khong ho tro (depth %d, interlace %d)' % (depth, inter))
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]
    raw = np.frombuffer(zlib.decompress(bytes(idat)), np.uint8)
    stride = w * bpp
    raw = raw.reshape(h, stride + 1)
    out = np.zeros((h, stride), np.uint8)
    prev = np.zeros(stride, np.int32)
    for y in range(h):
        ft = raw[y, 0]
        line = raw[y, 1:].astype(np.int32)
        if ft == 0:
            cur = line
        elif ft == 1:
            cur = line.copy()
            for i in range(bpp, stride, bpp):
                cur[i:i + bpp] = (cur[i:i + bpp] + cur[i - bpp:i]) & 255
        elif ft == 2:
            cur = (line + prev) & 255
        elif ft == 3:
            cur = line.copy()
            for i in range(stride):
                a = cur[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + ((a + prev[i]) >> 1)) & 255
        elif ft == 4:
            cur = line.copy()
            for i in range(stride):
                a = cur[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                cur[i] = (cur[i] + (a if pa <= pb and pa <= pc else (b if pb <= pc else c))) & 255
        else:
            raise ValueError('PNG bo loc %d' % ft)
        out[y] = cur
        prev = cur
    a = out.reshape(h, w, bpp)
    rgba = np.zeros((h, w, 4), np.uint8)
    if ct == 6:
        rgba[:] = a
    elif ct == 2:
        rgba[..., :3] = a
        rgba[..., 3] = 255
    elif ct == 0:
        rgba[..., :3] = a[..., :1]
        rgba[..., 3] = 255
    elif ct == 4:
        rgba[..., :3] = a[..., :1]
        rgba[..., 3] = a[..., 1]
    else:
        pal = np.frombuffer(plte, np.uint8).reshape(-1, 3)
        al = np.full(len(pal), 255, np.uint8)
        if trns:
            al[:len(trns)] = np.frombuffer(trns, np.uint8)[:len(pal)]
        rgba[..., :3] = pal[a[..., 0]]
        rgba[..., 3] = al[a[..., 0]]
    return rgba


# ---------------------------------------------------------------- chữ 5x7 (nhãn ASCII)
FONT = {
    'A': '01110 10001 10001 11111 10001 10001 10001', 'B': '11110 10001 10001 11110 10001 10001 11110',
    'C': '01111 10000 10000 10000 10000 10000 01111', 'D': '11110 10001 10001 10001 10001 10001 11110',
    'E': '11111 10000 10000 11110 10000 10000 11111', 'F': '11111 10000 10000 11110 10000 10000 10000',
    'G': '01111 10000 10000 10011 10001 10001 01111', 'H': '10001 10001 10001 11111 10001 10001 10001',
    'I': '01110 00100 00100 00100 00100 00100 01110', 'J': '00111 00010 00010 00010 00010 10010 01100',
    'K': '10001 10010 10100 11000 10100 10010 10001', 'L': '10000 10000 10000 10000 10000 10000 11111',
    'M': '10001 11011 10101 10101 10001 10001 10001', 'N': '10001 11001 10101 10011 10001 10001 10001',
    'O': '01110 10001 10001 10001 10001 10001 01110', 'P': '11110 10001 10001 11110 10000 10000 10000',
    'Q': '01110 10001 10001 10001 10101 10010 01101', 'R': '11110 10001 10001 11110 10100 10010 10001',
    'S': '01111 10000 10000 01110 00001 00001 11110', 'T': '11111 00100 00100 00100 00100 00100 00100',
    'U': '10001 10001 10001 10001 10001 10001 01110', 'V': '10001 10001 10001 10001 10001 01010 00100',
    'W': '10001 10001 10001 10101 10101 10101 01010', 'X': '10001 10001 01010 00100 01010 10001 10001',
    'Y': '10001 10001 01010 00100 00100 00100 00100', 'Z': '11111 00001 00010 00100 01000 10000 11111',
    '0': '01110 10001 10011 10101 11001 10001 01110', '1': '00100 01100 00100 00100 00100 00100 01110',
    '2': '01110 10001 00001 00010 00100 01000 11111', '3': '11110 00001 00001 01110 00001 00001 11110',
    '4': '00010 00110 01010 10010 11111 00010 00010', '5': '11111 10000 11110 00001 00001 10001 01110',
    '6': '00110 01000 10000 11110 10001 10001 01110', '7': '11111 00001 00010 00100 01000 01000 01000',
    '8': '01110 10001 10001 01110 10001 10001 01110', '9': '01110 10001 10001 01111 00001 00010 01100',
    ' ': '00000 00000 00000 00000 00000 00000 00000', '-': '00000 00000 00000 11111 00000 00000 00000',
    '.': '00000 00000 00000 00000 00000 01100 01100', ':': '00000 01100 01100 00000 01100 01100 00000',
    '/': '00001 00010 00010 00100 01000 01000 10000', '|': '00100 00100 00100 00100 00100 00100 00100',
    '(': '00010 00100 01000 01000 01000 00100 00010', ')': '01000 00100 00010 00010 00010 00100 01000',
    '%': '11001 11010 00010 00100 01000 01011 10011', '_': '00000 00000 00000 00000 00000 00000 11111',
    '+': '00000 00100 00100 11111 00100 00100 00000', '=': '00000 00000 11111 00000 11111 00000 00000',
    ',': '00000 00000 00000 00000 01100 00100 01000', '>': '01000 00100 00010 00001 00010 00100 01000',
}


def draw_text(img, x, y, text, scale=2, color=(255, 255, 255)):
    for ch in text.upper():
        g = FONT.get(ch, FONT[' '])
        rows = g.split()
        for r, row in enumerate(rows):
            for c, bit in enumerate(row):
                if bit == '1':
                    y0, x0 = y + r * scale, x + c * scale
                    img[max(0, y0):max(0, y0 + scale), max(0, x0):max(0, x0 + scale)] = color
        x += 6 * scale
    return x


# ---------------------------------------------------------------- dữ liệu vẽ
def face_tables(doc):
    """Bảng theo (phần, srcFace): uv (4,2), màu (4,3) 0..1 (x2 nếu có texture), cờ."""
    out = []
    for part in doc['parts']:
        rows = []
        for f in part['faces']:
            vc = 4 if f['quad'] else 3
            uv = np.zeros((4, 2))
            if f['textured']:
                uv[:vc] = np.array(f['uv'], float)
            col = np.ones((4, 3))
            if f.get('colours') is not None:
                col[:vc] = np.array(f['colours'], float) / 255.0 * (2.0 if f['textured'] else 1.0)
            abr = (int(f['tpage'], 16) >> 5) & 3 if f['textured'] else 0
            rows.append(dict(vc=vc, uv=uv, col=col, textured=bool(f['textured']), lit=bool(f['lit']),
                             transl=bool(f['translucent']), abr=abr))
        out.append(rows)
    return out


def part_backface(part):
    return not any(f['translucent'] and not f['textured'] for f in part['faces'])


def orig_mesh(doc, tables):
    """Lưới gốc giống TmdObjLoader: mỗi gói tam giác (2,1,0) (+ (1,2,3)), pháp tuyến TMD từng góc."""
    out = []
    for pi, part in enumerate(doc['parts']):
        V = np.array(part['verts'], float).reshape(-1, 3)
        P, N, UV, COL, TF = [], [], [], [], []
        for k, f in enumerate(part['faces']):
            t = tables[pi][k]
            vc = t['vc']
            g = np.array(f['geo_normal'], float)
            g = g / max(np.linalg.norm(g), EPS)
            nrm = np.array(f['normals'], float) if f.get('normals') is not None else np.tile(g, (vc, 1))
            for tri in [(2, 1, 0)] + ([(1, 2, 3)] if vc == 4 else []):
                P.append(V[[f['vidx'][c] for c in tri]])
                N.append(nrm[list(tri)])
                UV.append(t['uv'][list(tri)])
                COL.append(t['col'][list(tri)])
                TF.append(k)
        out.append(dict(P=np.array(P).reshape(-1, 3, 3), N=np.array(N).reshape(-1, 3, 3),
                        UV=np.array(UV).reshape(-1, 3, 2), COL=np.array(COL).reshape(-1, 3, 3),
                        face=np.array(TF, int), back=part_backface(part)))
    return out


def load_npz(path):
    z = np.load(path, allow_pickle=False)
    n = int(z['partCount'][0])
    parts = []
    for i in range(n):
        parts.append(dict(mode=int(z['p%03d_mode' % i][0]), level=int(z['partLevel'][i]),
                          **{k: z['p%03d_%s' % (i, k)] for k in ('pos', 'corner_pos', 'corner_n', 'corner_face',
                                                                   'corner_st', 'tri')}))
    return parts


def rem_mesh(doc, tables, parts, orig):
    """Lưới remaster: uv / màu nội suy theo (srcFace, s, t) (SPEC §3.2), pháp tuyến corner_n."""
    out = []
    for pi, pm in enumerate(parts):
        if pm['mode'] != 1 or not len(pm['tri']):
            out.append(orig[pi])
            continue
        tab = tables[pi]
        cf = pm['corner_face'].astype(int)
        s = pm['corner_st'][:, 0] / 65535.0
        t = pm['corner_st'][:, 1] / 65535.0
        vc = np.array([tab[k]['vc'] for k in cf])
        tt = np.where(s + t > 1, 1 - s, t)
        w = np.where((vc == 3)[:, None], np.stack([1 - s - tt, s, tt, 0 * s], 1),
                     np.stack([(1 - s) * (1 - t), s * (1 - t), (1 - s) * t, s * t], 1))
        uvt = np.array([tab[k]['uv'] for k in range(len(tab))])
        colt = np.array([tab[k]['col'] for k in range(len(tab))])
        uv = np.einsum('ck,ckj->cj', w, uvt[cf])
        col = np.einsum('ck,ckj->cj', w, colt[cf])
        P = pm['pos'][pm['corner_pos']].astype(float)
        tri = pm['tri'].astype(int)
        out.append(dict(P=P[tri], N=pm['corner_n'].astype(float)[tri], UV=uv[tri], COL=col[tri],
                        face=cf[tri[:, 0]], back=part_backface(doc['parts'][pi])))
    return out


# ---------------------------------------------------------------- dựng hình
def view_matrix(yaw, el):
    """Quay quanh trục y (PS1, y xuống) rồi nghiêng quanh x. Kết quả: x phải, y xuống, z vào màn hình."""
    cy, sy = math.cos(yaw), math.sin(yaw)
    ce, se = math.cos(el), math.sin(el)
    Ry = np.array([[cy, 0, -sy], [0, 1, 0], [sy, 0, cy]])
    Rx = np.array([[1, 0, 0], [0, ce, se], [0, -se, ce]])
    return Rx @ Ry


def face_yaw(doc):
    """Hướng mặt: trung bình pháp tuyến (khung 0) của mặt có texel trong suốt >= 20% (mắt / miệng, đề can); không có ->
    trung bình pháp tuyến phần cao nhất. Trả góc yaw để mặt nhìn về phía máy quay (-z)."""
    acc = np.zeros(3)
    for part in doc['parts']:
        R = np.array(part['kf0_matrix'], float)
        for f in part['faces']:
            if f.get('transp_frac', 0.0) >= 0.2 and f.get('normals') is not None:
                acc += R @ np.array(f['normals'], float).sum(0)
    if np.hypot(acc[0], acc[2]) < 1e-9:
        return 0.0
    # tìm yaw sao cho (Ry @ acc) có x = 0, z < 0
    for cand in np.linspace(-math.pi, math.pi, 721):
        v = view_matrix(cand, 0.0) @ acc
        if v[2] < 0 and abs(v[0]) <= np.hypot(acc[0], acc[2]) * math.sin(math.radians(0.6)):
            return float(cand)
    return 0.0


LIGHTS = [(np.array([-0.45, -0.6, -0.65]), 0.7), (np.array([0.6, -0.1, -0.4]), 0.2)]
AMBIENT = 0.45


def render(meshes, doc, tables, atlas, M, center, span, W, H):
    """Một khung hình: lưới các phần (toạ độ cục bộ) -> ảnh RGB float (H, W, 3)."""
    frags = []          # (pix, depth, order, tri_global)
    tris_all = []
    order0 = 0
    for pi, (m, part) in enumerate(zip(meshes, doc['parts'])):
        if not len(m['P']):
            continue
        R = np.array(part['kf0_matrix'], float)
        T = np.array(part['kf0_trans'], float)
        Pw = m['P'] @ R.T + T
        Nw = m['N'] @ R.T
        Pv = (Pw - center) @ M.T
        Nv = Nw @ M.T
        scr = np.empty_like(Pv)
        scr[..., 0] = Pv[..., 0] / span * H + W / 2
        scr[..., 1] = Pv[..., 1] / span * H + H / 2
        scr[..., 2] = Pv[..., 2]
        # culling: pháp tuyến tay phải của tam giác (chiều SC) hướng ra ngoài -> mặt trước khi n·z < 0
        nrm = np.cross(Pv[:, 1] - Pv[:, 0], Pv[:, 2] - Pv[:, 0])
        keep = np.ones(len(Pv), bool)
        if m['back']:
            keep = nrm[:, 2] < 0
        # ánh sáng từng góc
        tf = m['face']
        lit = np.array([tables[pi][k]['lit'] for k in tf])
        textured = np.array([tables[pi][k]['textured'] for k in tf])
        transl = np.array([tables[pi][k]['transl'] for k in tf])
        abr = np.array([tables[pi][k]['abr'] for k in tf])
        nv = Nv / np.maximum(np.linalg.norm(Nv, axis=-1, keepdims=True), EPS)
        light = np.full(nv.shape[:2], AMBIENT)
        for d, k in LIGHTS:
            dv = d / np.linalg.norm(d)
            light += k * np.maximum(0.0, -(nv @ dv))
        light = np.where(lit[:, None], light, 1.0)
        shade = m['COL'] * light[..., None]
        tris_all.append(dict(scr=scr[keep], shade=shade[keep], uv=m['UV'][keep], textured=textured[keep],
                             transl=transl[keep], abr=abr[keep], order=order0 + np.nonzero(keep)[0]))
        order0 += len(Pv)
    if not tris_all:
        return np.tile(BG, (H, W, 1))
    scr = np.concatenate([t['scr'] for t in tris_all])
    shade = np.concatenate([t['shade'] for t in tris_all])
    uv = np.concatenate([t['uv'] for t in tris_all])
    textured = np.concatenate([t['textured'] for t in tris_all])
    transl = np.concatenate([t['transl'] for t in tris_all])
    abr = np.concatenate([t['abr'] for t in tris_all])
    order = np.concatenate([t['order'] for t in tris_all])
    AH, AW = atlas.shape[:2] if atlas is not None else (1, 1)
    # raster theo cỡ hộp bao
    xs, ys = scr[:, :, 0], scr[:, :, 1]
    x0 = np.clip(np.floor(xs.min(1) - 0.5), 0, W - 1).astype(np.int64)
    y0 = np.clip(np.floor(ys.min(1) - 0.5), 0, H - 1).astype(np.int64)
    x1 = np.clip(np.ceil(xs.max(1) - 0.5), 0, W - 1).astype(np.int64)
    y1 = np.clip(np.ceil(ys.max(1) - 0.5), 0, H - 1).astype(np.int64)
    area = (xs[:, 1] - xs[:, 0]) * (ys[:, 2] - ys[:, 0]) - (xs[:, 2] - xs[:, 0]) * (ys[:, 1] - ys[:, 0])
    vis = (np.abs(area) > 1e-9) & (xs.max(1) >= 0) & (ys.max(1) >= 0) & (xs.min(1) < W) & (ys.min(1) < H)
    size = np.maximum(x1 - x0, y1 - y0) + 1
    F_pix, F_z, F_ord, F_t, F_b = [], [], [], [], []
    prev = 0
    for sz in (2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048):
        sel = np.nonzero(vis & (size <= sz) & (size > prev))[0]
        prev = sz
        if not len(sel):
            continue
        g = np.arange(sz)
        cs = max(1, 3_000_000 // (sz * sz))
        for c0 in range(0, len(sel), cs):
            idx = sel[c0:c0 + cs]
            px = (x0[idx, None] + g[None, :])[:, None, :] + 0.5
            py = (y0[idx, None] + g[None, :])[:, :, None] + 0.5
            ax, ay = xs[idx, 0][:, None, None], ys[idx, 0][:, None, None]
            bx, by = xs[idx, 1][:, None, None], ys[idx, 1][:, None, None]
            cx, cy = xs[idx, 2][:, None, None], ys[idx, 2][:, None, None]
            ar = area[idx][:, None, None]
            w1 = ((px - ax) * (cy - ay) - (py - ay) * (cx - ax)) / ar
            w2 = ((bx - ax) * (py - ay) - (by - ay) * (px - ax)) / ar
            w0 = 1.0 - w1 - w2
            ins = (w0 >= -1e-7) & (w1 >= -1e-7) & (w2 >= -1e-7)
            ins &= ((px - 0.5) <= x1[idx, None, None]) & ((py - 0.5) <= y1[idx, None, None])
            ti, yy, xx = np.nonzero(ins)
            if not len(ti):
                continue
            b = np.stack([w0[ti, yy, xx], w1[ti, yy, xx], w2[ti, yy, xx]], 1)
            tg = idx[ti]
            pix = (y0[tg] + yy) * W + (x0[tg] + xx)
            z = np.sum(b * scr[tg, :, 2], 1)
            F_pix.append(pix)
            F_z.append(z)
            F_t.append(tg)
            F_b.append(b)
    if not F_pix:
        return np.tile(BG, (H, W, 1))
    pix = np.concatenate(F_pix)
    # độ sâu lượng tử 1e-3 đơn vị: mặt đề can trùng vị trí với mặt nền thì hoà độ sâu
    z = np.round(np.concatenate(F_z) * 1000.0) / 1000.0
    tg = np.concatenate(F_t)
    b = np.concatenate(F_b)
    # texel + discard alpha 0
    texrgb = np.ones((len(tg), 3))
    alive = np.ones(len(tg), bool)
    if atlas is not None:
        tx = textured[tg]
        uvp = np.einsum('fk,fkj->fj', b, uv[tg])
        u = np.clip(np.floor(uvp[:, 0]).astype(np.int64), 0, AW - 1)
        v = np.clip(np.floor(uvp[:, 1]).astype(np.int64), 0, AH - 1)
        texel = atlas[v, u]
        alive &= ~tx | (texel[:, 3] > 0)
        texrgb = np.where(tx[:, None], texel[:, :3] / 255.0, 1.0)
    col = np.clip(np.einsum('fk,fkj->fj', b, shade[tg]), 0, 2.0) * texrgb
    col = np.clip(col, 0, 1)
    img = np.tile(BG, (H * W, 1))
    zbuf = np.full(H * W, np.inf)
    op = alive & ~transl[tg]
    if op.any():
        o = np.nonzero(op)[0]
        # gói đục: GL_LESS của SC (QueuedModel.opaqueDepthComparator) -> hoà độ sâu thì tam giác vẽ trước thắng
        srt = np.lexsort((order[tg[o]], z[o], pix[o]))
        o = o[srt]
        first = np.r_[True, pix[o][1:] != pix[o][:-1]]
        w = o[first]
        img[pix[w]] = col[w]
        zbuf[pix[w]] = z[w]
    tr = alive & transl[tg]
    if tr.any():
        o = np.nonzero(tr)[0]
        o = o[z[o] < zbuf[pix[o]]]
        if len(o):
            srt = np.lexsort((-order[tg[o]], z[o], pix[o]))
            o = o[srt]
            first = np.r_[True, pix[o][1:] != pix[o][:-1]]
            w = o[first]
            a = abr[tg[w]]
            B = img[pix[w]]
            Fc = col[w]
            mix = np.where((a == 0)[:, None], 0.5 * B + 0.5 * Fc,
                           np.where((a == 1)[:, None], B + Fc, np.where((a == 2)[:, None], B - Fc, B + 0.25 * Fc)))
            img[pix[w]] = np.clip(mix, 0, 1)
    return img.reshape(H, W, 3)


def posed_points(doc):
    pts = []
    for part in doc['parts']:
        V = np.array(part['verts'], float).reshape(-1, 3)
        if len(V):
            pts.append(V @ np.array(part['kf0_matrix'], float).T + np.array(part['kf0_trans'], float))
    return np.concatenate(pts) if pts else np.zeros((1, 3))


def head_box(doc):
    """Phần 'đầu': trong các phần có cạnh hộp < 40% chiều cao mô hình và không dài như vũ khí (trục chính < 3 lần trục
    thứ hai), phần có đỉnh cao nhất (y nhỏ nhất)."""
    allp = posed_points(doc)
    Hm = allp[:, 1].max() - allp[:, 1].min()
    best = None
    for part in doc['parts']:
        V = np.array(part['verts'], float).reshape(-1, 3)
        if not len(V):
            continue
        P = V @ np.array(part['kf0_matrix'], float).T + np.array(part['kf0_trans'], float)
        ext = P.max(0) - P.min(0)
        if len(P) >= 3:
            sv = np.linalg.svd(P - P.mean(0), compute_uv=False)
            if sv[0] > 3.0 * max(sv[1], 1e-6):
                continue
        if ext.max() < 0.4 * Hm and (best is None or P[:, 1].min() < best[0]):
            best = (P[:, 1].min(), P.min(0), P.max(0))
    return best


def views_for(doc, names):
    yaw = face_yaw(doc)
    allp = posed_points(doc)
    out = []
    for v in names:
        if v == 'head':
            # cận đầu: phần nhỏ cao nhất (không phải vũ khí), khung bao mọi đỉnh trong bán kính 0.18 x chiều cao mô hình
            # quanh nó (đầu + tóc + trang sức), tối thiểu 0.25 x chiều cao
            hb = head_box(doc)
            if hb is None:
                continue
            _, lo, hi = hb
            Hm = max(float(allp[:, 1].max() - allp[:, 1].min()), EPS)
            near = allp[np.linalg.norm(allp - (lo + hi) / 2, axis=1) <= 0.18 * Hm]
            lo2, hi2 = (near.min(0), near.max(0)) if len(near) else (lo, hi)
            out.append(('head', yaw + math.radians(20), math.radians(-8), (lo2 + hi2) / 2,
                        max(1.3 * float((hi2 - lo2).max()), 0.25 * Hm)))
            continue
        az = {'full34': 35.0, 'back34': 180.0 + 35.0, 'front': 0.0, 'side': 90.0}.get(v, 35.0)
        M = view_matrix(yaw + math.radians(az), math.radians(-10))
        q = (allp - allp.mean(0)) @ M.T
        c = allp.mean(0) + M.T @ ((q.max(0) + q.min(0)) / 2)
        span = float((q.max(0) - q.min(0))[1]) * 1.08
        span = max(span, float((q.max(0) - q.min(0))[0]) * 1.08 / 0.75)
        out.append((v, yaw + math.radians(az), math.radians(-10), c, span))
    return out


def make_sheet(json_path, geom_dir, out_path, views=('full34', 'front', 'back34', 'head'), res=420, title=None, atlas=None):
    doc = json.load(open(json_path, encoding='utf-8'))
    name = doc.get('name') or os.path.splitext(os.path.basename(json_path))[0]
    ap = atlas or os.path.join(os.path.dirname(json_path), name + '_atlas.png')
    if not os.path.isfile(ap):
        alt = os.path.splitext(json_path)[0] + '_atlas.png'
        ap = alt if os.path.isfile(alt) else None
    tex = png_read(ap) if ap else None
    tables = face_tables(doc)
    orig = orig_mesh(doc, tables)
    cols = [('GOC', orig, '%d TAM GIAC' % sum(len(m['P']) for m in orig))]
    for L in (1, 2):
        p = os.path.join(geom_dir, 'geom_L%d.npz' % L)
        if os.path.isfile(p):
            parts = load_npz(p)
            mesh = rem_mesh(doc, tables, parts, orig)
            lv = ''.join(str(x['level']) for x in parts)
            cols.append(('L%d' % L, mesh, '%d TAM GIAC  MUC %s' % (sum(len(m['P']) for m in mesh), lv)))
    vlist = views_for(doc, views)
    W = int(res * 0.75)
    H = res
    head_h = 34
    foot_h = 26
    sheet = np.zeros((head_h + len(vlist) * H + foot_h, len(cols) * W + (len(cols) - 1) * 4, 3), np.uint8)
    sheet[:] = (30, 30, 34)
    draw_text(sheet, 8, 8, (title or name)[:80], 2)
    for r, (vn, yaw, el, c, span) in enumerate(vlist):
        M = view_matrix(yaw, el)
        for ci, (lab, mesh, info) in enumerate(cols):
            img = render(mesh, doc, tables, tex, M, c, span, W, H)
            x = ci * (W + 4)
            y = head_h + r * H
            sheet[y:y + H, x:x + W] = (img * 255 + 0.5).astype(np.uint8)
            if r == 0:
                draw_text(sheet, x + 6, y + 6, lab, 2, (255, 230, 120))
            draw_text(sheet, x + W - 6 - 12 * len(vn), y + H - 20, vn, 2, (200, 200, 200))
    for ci, (lab, mesh, info) in enumerate(cols):
        draw_text(sheet, ci * (W + 4) + 6, head_h + len(vlist) * H + 6, info[:W // 7], 1, (220, 220, 220))
    png_write(out_path, sheet)
    return out_path


def stack_sheets(out, paths):
    imgs = [png_read(p)[..., :3] for p in paths]
    w = max(i.shape[1] for i in imgs)
    rows = []
    for i in imgs:
        pad = np.zeros((i.shape[0], w, 3), np.uint8)
        pad[:] = (30, 30, 34)
        pad[:, :i.shape[1]] = i
        rows.append(pad)
        rows.append(np.full((6, w, 3), 80, np.uint8))
    png_write(out, np.concatenate(rows[:-1]))


def selftest():
    errs = []
    img = (np.arange(4 * 5 * 4) % 251).astype(np.uint8).reshape(4, 5, 4)
    p = os.path.join(os.environ.get('TEMP', '.'), 'preview_sc_selftest.png')
    png_write(p, img)
    back = png_read(p)
    if not np.array_equal(back, img):
        errs.append('png roundtrip')
    os.remove(p)
    # tam giác phủ nửa ảnh, culling theo chiều
    doc = dict(parts=[dict(verts=[[0, 0, 0], [10, 0, 0], [0, 10, 0]], kf0_matrix=np.eye(3).tolist(), kf0_trans=[0, 0, 0],
                           faces=[dict(quad=False, textured=False, translucent=False, lit=False, vidx=[0, 1, 2],
                                       colours=[[255, 0, 0]] * 3, geo_normal=[0, 0, 1], normals=None)])])
    tables = face_tables(doc)
    mesh = orig_mesh(doc, tables)
    a = render(mesh, doc, tables, None, view_matrix(0.0, 0.0), np.array([5.0, 5.0, 0]), 10.0, 20, 20)
    b = render(mesh, doc, tables, None, view_matrix(math.pi, 0.0), np.array([5.0, 5.0, 0]), 10.0, 20, 20)
    red_a = int((a[..., 0] > 0.9).sum())
    red_b = int((b[..., 0] > 0.9).sum())
    if not (red_a > 0) ^ (red_b > 0):
        errs.append('culling %d %d' % (red_a, red_b))
    if 'PIL' in sys.modules:
        errs.append('PIL da duoc import')
    print('selftest:', 'DAT' if not errs else 'LOI %s' % errs)
    return 0 if not errs else 1


def main():
    ap = argparse.ArgumentParser(description='Anh xem truoc kieu SC: goc | L1 | L2')
    ap.add_argument('json', nargs='?')
    ap.add_argument('geom', nargs='?')
    ap.add_argument('out', nargs='?')
    ap.add_argument('--views', default='full34,front,back34,head')
    ap.add_argument('--res', type=int, default=420)
    ap.add_argument('--title')
    ap.add_argument('--atlas')
    ap.add_argument('--sheet', nargs='+')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.sheet:
        stack_sheets(a.sheet[0], a.sheet[1:])
        print('DAT:', a.sheet[0])
        return 0
    if not (a.json and a.geom and a.out):
        ap.error('can <model.json> <geom_dir> <out.png>')
    make_sheet(a.json, a.geom, a.out, a.views.split(','), a.res, a.title, a.atlas)
    print('DAT:', a.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
