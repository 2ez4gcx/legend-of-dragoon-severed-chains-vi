"""export.py — xuất một mô hình nhân vật theo lược đồ của tools/sc_remodel/export_tmd.py (bản thử nghiệm, đã đóng băng).

Cùng thuật toán, chỉ numpy (không PIL): JSON (<name>.json), atlas RGBA (<name>_atlas.png), atlas tô viền trong suốt
(<name>_atlas_pad.png), glTF (<name>.gltf + .bin), OBJ (<name>.mtl, <name>_posed.obj, parts/partNN.obj). Với cùng đầu vào,
JSON / .bin / .mtl / .gltf / .obj trùng từng byte với export_tmd.py; PNG trùng từng điểm ảnh (byte PNG khác vì bộ ghi
khác: imgio, zlib 9, lọc 0). Đầu vào của P2 (Blender) và P3 (texture HD).

Nguồn (kind, theo catalog §3.8; mô hình đọc qua gamefiles — mrg đã giải, lớp phủ sc-vi):
  battle  model 'characters/<c>/models/<form>/32', tim 'characters/<c>/textures/<form>'      đặt TIM 'native'
  story   model 'SECT/DRGN0.BIN/<N>', tim 'SECT/DRGN0.BIN/<N+1>'                              'native'
  monster model 'SECT/DRGN0.BIN/<3137+id>/32', tim 'monsters/<id>/textures/combat'           'native'
  field   model 'SECT/DRGN2x.BIN/<cảnh>/<obj*33>', tim 'SECT/DRGN2x.BIN/<cảnh>/textures/<obj>' 'field_slot0' + UvAdjust
Hoạt cảnh (chỉ dùng khung khoá 0 cho tư thế xem nhanh): anim_rel nếu cho, ngược lại hoạt cảnh đầu tiên của anims.find_anims.
Khác export_tmd.py ở chỗ không ảnh hưởng dữ liệu US: gói đọc theo run như SC (TmdObjTable1c), UvAdjust chỉ áp cho gói
gouraud có texture (Models.adjustPartUvs, SPEC §3.3.7); các file liên kết ảo trong mrg được giải (export_tmd.py chỉ đọc file thật).

Cách dùng:
  from lib import gamefiles, export
  gf = gamefiles.GameFiles('game/files')
  summary, errors = export.export_source(gf, 'battle', 'characters/dart/models/combat/32',
                                         'characters/dart/textures/combat', name='dart_battle', out_dir='work/upscale/...')
  summary, errors = export.export_battle(gf, 'dart', 'combat', anim='0', out_dir=...)
  summary, errors = export.export_field(gf, 'DRGN21.BIN/26', 0, name='dart_field', out_dir=...)
  write=False: chỉ kiểm (như --check), không ghi file. errors rỗng = đạt (giống exit 0 của export_tmd.py).
Chỉ đọc game/files; ghi duy nhất vào out_dir (dữ liệu suy ra từ đĩa: chỉ dưới work/upscale/sc_remaster*, không commit).
"""
import json
import math
import os

import numpy as np

from . import SpecError, anims as _anims, imgio, rel_to_root, tim as _tim, tmd as _tmd

SCALE_GLTF = 0.001
PILOT_GLTF_GENERATOR = 'LOD-SC tools/sc_remodel/export_tmd.py'
GLTF_GENERATOR = 'LOD-SC tools/sc_remaster/lib/export.py'
FIELD_UV_ADJUST_NOTE = 'UvAdjustmentMetrics14(slot 0: 576,256)'


class ExportError(Exception):
    """Lỗi nặng (export_tmd.py: SystemExit) — không xuất được."""


# ---------------------------------------------------------------- tải mô hình -> cấu trúc 'objs' của export_tmd.py
def _prim_dict(f):
    """tmd.Face -> dict gói như export_tmd.py parse_obj."""
    p = dict(index=f.index, header=f.header, quad=f.quad, textured=f.textured, translucent=f.translucent, lit=f.lit,
             uv=list(f.uv), clut=f.clut, tpage=f.tpage, colours=None, vidx=list(f.vidx), nidx=list(f.nidx))
    p['coloured'] = f.coloured
    if f.colours is not None:
        p['colours'] = [(c & 0xff, c >> 8 & 0xff, c >> 16 & 0xff) for c in f.colours]
    return p


def model_objs(model):
    """tmd.Model (đã UvAdjust nếu cần) -> danh sách obj {verts f64 [n,3], norms f64 [n,3] (/4096), prims, scale}."""
    objs = []
    for part in model.parts:
        faces, _ = _tmd.decode_faces(part)
        verts = np.array(part.verts, np.float64).reshape(-1, 3)
        norms = (np.array(part.normals, np.float64) / 4096.0).reshape(-1, 3)
        objs.append(dict(verts=verts, norms=norms, prims=[_prim_dict(f) for f in faces], scale=part.scale))
    return objs


def default_name(kind, model_rel):
    parts = model_rel.replace('\\', '/').split('/')
    if kind == 'battle' and len(parts) >= 4 and parts[0] == 'characters':
        return '%s_battle_%s' % (parts[1], parts[3])
    if kind == 'field' and len(parts) >= 4:
        return 'field_%s_%s_%d' % (parts[1].replace('.BIN', ''), parts[2], int(parts[3]) // 33)
    if kind == 'story':
        return 'story_%s_%s' % (parts[1].replace('.BIN', ''), parts[2])
    if kind == 'monster':
        return 'monster_%s' % parts[2]
    return '_'.join(p.replace('.BIN', '') for p in parts)


def load_source(gf, kind, model_rel, tim_rel, anim_rel=None, errors=None):
    """-> (objs, kf0, tim, vram, origin, src, model). ExportError khi không tải được (export_tmd.py: SystemExit)."""
    errors = [] if errors is None else errors
    placement = _tim.placement_for(kind)
    mrel = gf.resolve(model_rel)
    trel = gf.resolve(tim_rel)
    if mrel is None:
        raise ExportError('khong co file mo hinh %s' % model_rel)
    if trel is None:
        raise ExportError('khong co file TIM %s' % tim_rel)
    data = gf.read(mrel)
    try:
        model = _tmd.parse_ccontainer(data, name=mrel)
    except SpecError as e:
        raise ExportError('%s: %s' % (mrel, e))
    if model.tmd_id != _tmd.TMD_ID:
        errors.append('TmdWithId id = %x (mong doi 0x41)' % model.tmd_id)
    errors.extend(_tmd.section_overlaps(model))
    try:
        tim = _tim.parse_tim(gf.read(trel))
        vram, irect, crect, adjust = _tim.virtual_vram(tim, placement)
    except SpecError as e:
        raise ExportError('%s: %s' % (trel, e))
    if adjust is not None:
        _tmd.uv_adjust_model(model, *adjust)
    try:
        objs = model_objs(model)
    except SpecError as e:
        raise ExportError('%s: %s' % (mrel, e))
    # hoạt cảnh: khung khoá 0
    if anim_rel is not None:
        arel = gf.resolve(anim_rel)
        if arel is None:
            raise ExportError('khong co file hoat canh %s' % anim_rel)
    else:
        found = _anims.find_anims(gf, kind, model_rel, len(objs))     # theo chỉ số (ảo) của nguồn
        if not found:
            raise ExportError('LOI: khong thay hoat canh cung so phan cho %s' % mrel)
        arel = found[0][0]
    n, kf0 = _anims.kf0(gf.read(arel))
    if n != len(objs) or kf0 is None:
        raise ExportError('LOI: hoat canh %s co %d phan, mo hinh %d phan' % (arel, n, len(objs)))
    ix, iy, iw, ih = irect
    src = dict(model=mrel, anim=arel, texture=trel, texture_vram=[ix, iy, iw, ih],
               clut_vram=list(crect) if crect is not None else None,
               uv_adjust=FIELD_UV_ADJUST_NOTE if adjust is not None else None)
    return objs, kf0, tim, vram, (ix, iy), src, model


# ---------------------------------------------------------------- atlas (export_tmd.py, nguyên thuật toán)
def prim_tris(p):
    return [(2, 1, 0)] + ([(1, 2, 3)] if p['quad'] else [])


def coverage(tri_uv, W, H, ss=4):
    """Số mẫu (trên ss*ss mẫu/texel) nằm trong tam giác uv (toạ độ texel) cho mỗi texel trong bbox -> (x0, y0, counts)."""
    tri = np.asarray(tri_uv, float)
    x0 = max(int(math.floor(tri[:, 0].min())), 0)
    x1 = min(int(math.ceil(tri[:, 0].max())), W)
    y0 = max(int(math.floor(tri[:, 1].min())), 0)
    y1 = min(int(math.ceil(tri[:, 1].max())), H)
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
    owner = owner.copy()
    valid = valid.copy()
    H, W = owner.shape
    for _ in range(H + W):
        if valid.all():
            break
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            src_v = np.zeros_like(valid)
            src_o = np.zeros_like(owner)
            ys = slice(max(dy, 0), H + min(dy, 0))
            yd = slice(max(-dy, 0), H + min(-dy, 0))
            xs = slice(max(dx, 0), W + min(dx, 0))
            xd = slice(max(-dx, 0), W + min(-dx, 0))
            src_v[yd, xd] = valid[ys, xs]
            src_o[yd, xd] = owner[ys, xs]
            take = ~valid & src_v
            owner[take] = src_o[take]
            valid |= take
    return owner, valid


def build_atlas(objs, tim, vram, tim_origin, errors):
    """-> (atlas RGBA, raw15 u16, W, H, stats) hoặc None khi không có mặt có texture. Toạ độ atlas texel =
    (u - u0, v - v0 + block*H); texel trùng hai CLUT khác nhau -> khối riêng xếp bên dưới."""
    ix, iy = tim_origin
    ih, iw = tim.img.shape
    prims = [p for o in objs for p in o['prims'] if p['textured']]
    if not prims:
        return None
    bpps = {_tim.page_info(p['tpage'])[2] for p in prims}
    if len(bpps) != 1:
        errors.append('nhieu do sau mau trong mot mo hinh: %s' % bpps)
    bpp = bpps.pop()
    if bpp not in (0, 1, 2):
        raise ExportError('atlas: bpp %d khong ho tro (mat PNG 24bpp)' % bpp)
    ppw = {0: 4, 1: 2, 2: 1}[bpp]
    W, H = iw * ppw, ih
    for p in prims:
        tx, ty, _ = _tim.page_info(p['tpage'])
        p['_u0'] = (ix - tx) * ppw
        p['_v0'] = iy - ty
        for (u, v) in p['uv']:
            if not (0 <= u - p['_u0'] <= W and 0 <= v - p['_v0'] <= H):
                errors.append('prim %d: uv (%d,%d) ngoai TIM' % (p['index'], u, v))
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
    owner = np.full((H, W), -1, int)
    weak = np.full((H, W), -1, int)
    extra_blocks = []
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
    tp0 = prims[0]['tpage']
    u0, v0 = prims[0]['_u0'], prims[0]['_v0']
    U, V = np.meshgrid(np.arange(W) + u0, np.arange(H) + v0)
    raw = np.zeros((H * (1 + len(extra_blocks)), W), np.uint16)
    base = np.zeros((H, W), np.uint16)
    for k, cl in enumerate(order):
        m = filled == k
        if m.any():
            base[m] = _tim.sample_vram(vram, tp0, cl, U[m], V[m])
    raw[:H] = base
    for b, cl in enumerate(extra_blocks):
        raw[H * (b + 1): H * (b + 2)] = _tim.sample_vram(vram, tp0, cl, U, V)
    bad = 0
    for p in prims:
        for x0, y0, c in p['_cov']:
            if c.size == 0:
                continue
            yy, xx = np.nonzero(c >= 4)
            uu = xx + x0
            vv = yy + y0
            direct = _tim.sample_vram(vram, p['tpage'], p['clut'], uu + p['_u0'], vv + p['_v0'])
            via = raw[vv + p['_block'] * H, uu]
            bad += int((direct != via).sum())
    if bad:
        errors.append('atlas: %d texel khac giai ma VRAM truc tiep' % bad)
    for p in prims:
        tot = tr = 0
        for x0, y0, c in p['_cov']:
            if c.size == 0:
                continue
            yy, xx = np.nonzero(c >= 4)
            tot += len(yy)
            tr += int((raw[yy + y0 + p['_block'] * H, xx + x0] == 0).sum())
        p['_transp'] = tr / tot if tot else 0.0
    edge_diff = 0
    for p in prims:
        for x0, y0, c in p['_cov']:
            if c.size == 0:
                continue
            yy, xx = np.nonzero((c > 0) & (c < 4))
            uu = xx + x0
            vv = yy + y0
            direct = _tim.sample_vram(vram, p['tpage'], p['clut'], uu + p['_u0'], vv + p['_v0'])
            edge_diff += int((direct != raw[vv + p['_block'] * H, uu]).sum())
    stats = dict(W=W, H=H, bpp=bpp, cluts=['%04x' % c for c in order], extra_blocks=['%04x' % c for c in extra_blocks],
                 owned_texels=int((owner >= 0).sum()), edge_texels_other_clut=edge_diff)
    return _tim.c15_to_rgba(raw), raw, W, H, stats


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


# ---------------------------------------------------------------- dữ liệu phần (export_tmd.py build_parts)
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
            loop = [2, 1, 0] if vc == 3 else [0, 2, 3, 1]
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
                f['tpage'] = '%04x' % p['tpage']
                f['clut'] = '%04x' % p['clut']
                f['transp_frac'] = round(p.get('_transp', 0.0), 4)
            faces.append(f)
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
        R = _anims.rot_zyx(*kf0[i][0])
        parts.append(dict(index=i, name='part%02d' % i, verts=[[int(c) for c in v] for v in V],
                          normals_tmd=len(o['norms']), faces=faces, kf0_rot_psx=list(kf0[i][0]), kf0_trans=list(kf0[i][1]),
                          kf0_matrix=[[round(float(c), 9) for c in r] for r in R]))
    return parts, winding


# ---------------------------------------------------------------- glTF / OBJ (export_tmd.py)
C = np.diag([1.0, -1.0, -1.0])   # PS1 (y xuống, z vào) -> glTF (Y lên, Z ra phía trước): quay 180° quanh X


def mat_to_quat(M):
    t = np.trace(M)
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        w = 0.25 * s
        x = (M[2, 1] - M[1, 2]) / s
        y = (M[0, 2] - M[2, 0]) / s
        z = (M[1, 0] - M[0, 1]) / s
    elif M[0, 0] > M[1, 1] and M[0, 0] > M[2, 2]:
        s = math.sqrt(1.0 + M[0, 0] - M[1, 1] - M[2, 2]) * 2
        w = (M[2, 1] - M[1, 2]) / s
        x = 0.25 * s
        y = (M[0, 1] + M[1, 0]) / s
        z = (M[0, 2] + M[2, 0]) / s
    elif M[1, 1] > M[2, 2]:
        s = math.sqrt(1.0 + M[1, 1] - M[0, 0] - M[2, 2]) * 2
        w = (M[0, 2] - M[2, 0]) / s
        x = (M[0, 1] + M[1, 0]) / s
        y = 0.25 * s
        z = (M[1, 2] + M[2, 1]) / s
    else:
        s = math.sqrt(1.0 + M[2, 2] - M[0, 0] - M[1, 1]) * 2
        w = (M[1, 0] - M[0, 1]) / s
        x = (M[0, 2] + M[2, 0]) / s
        y = (M[1, 2] + M[2, 1]) / s
        z = 0.25 * s
    q = np.array([x, y, z, w])
    return (q / np.linalg.norm(q)).tolist()


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
                with np.errstate(invalid='ignore', divide='ignore'):
                    n = n / np.linalg.norm(n)       # mặt suy biến không pháp tuyến -> NaN (y hệt export_tmd.py)
                uv = (f['uv'][c][0] / W, f['uv'][c][1] / Htot) if f['textured'] else (0.0, 0.0)
                if f['colours'] is not None:
                    col = tuple(srgb_to_linear(np.array(f['colours'][c]) / 255.0).tolist())
                else:
                    col = (1.0, 1.0, 1.0)
                k = (f['vidx'][c], tuple(np.round(n, 5)), uv, col)
                if k not in d['key']:
                    d['key'][k] = len(d['P'])
                    d['P'].append(V[f['vidx'][c]])
                    d['N'].append(n)
                    d['T'].append(uv)
                    d['Col'].append(col + (1.0,))
                d['I'].append(d['key'][k])
    return out


def build_gltf(path_base, name, parts, flip, W, Htot, has_atlas, generator=GLTF_GENERATOR):
    """-> (dict glTF, byte .bin) — không ghi file."""
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
            a['min'] = arr.min(0).astype(float).tolist()
            a['max'] = arr.max(0).astype(float).tolist()
        accessors.append(a)
        return len(accessors) - 1

    mats = []
    mat_index = {}
    if has_atlas:
        mat_index['tex'] = len(mats)
        mats.append(dict(name='tex', pbrMetallicRoughness=dict(baseColorTexture=dict(index=0), metallicFactor=0.0,
                                                               roughnessFactor=1.0),
                         alphaMode='MASK', alphaCutoff=0.5, doubleSided=False))
    mat_index['vcol'] = len(mats)
    mats.append(dict(name='vcol', pbrMetallicRoughness=dict(metallicFactor=0.0, roughnessFactor=1.0), doubleSided=False))
    meshes, nodes = [], [dict(name=name + '_root', scale=[SCALE_GLTF] * 3, children=[])]

    def prims_of(cl):
        prims = []
        for mat, d in cl.items():
            P = np.array(d['P'], np.float32)
            N = np.array(d['N'], np.float32)
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
                nodes.append(dict(name=part['name'] + '_' + layer, mesh=len(meshes),
                                  extras=dict(tmd_object=part['index'], layer=layer)))
                meshes.append(dict(name=part['name'] + '_' + layer, primitives=dprims))
    g = dict(asset=dict(version='2.0', generator=generator), scene=0,
             scenes=[dict(nodes=[0])], nodes=nodes, meshes=meshes, materials=mats,
             buffers=[dict(uri=os.path.basename(path_base) + '.bin', byteLength=len(blob))], bufferViews=views,
             accessors=accessors)
    if has_atlas:
        g['images'] = [dict(uri=os.path.basename(path_base) + '_atlas.png')]
        g['samplers'] = [dict(magFilter=9728, minFilter=9728, wrapS=33071, wrapT=33071)]
        g['textures'] = [dict(source=0, sampler=0)]
    return g, bytes(blob)


def check_gltf(g, blob, parts, errors):
    """Đọc lại .bin: tổng số tam giác khớp TMD, chỉ số trong phạm vi, min/max POSITION đúng."""
    ntri = 0
    for m in g['meshes']:
        for p in m['primitives']:
            ia = g['accessors'][p['indices']]
            iv = g['bufferViews'][ia['bufferView']]
            idx = np.frombuffer(blob, np.uint32, ia['count'], iv['byteOffset'])
            pa = g['accessors'][p['attributes']['POSITION']]
            pv = g['bufferViews'][pa['bufferView']]
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
    """OBJ từng phần (toạ độ cục bộ) + <name>_posed.obj + <name>.mtl; file văn bản (xuống dòng theo nền tảng như
    export_tmd.py)."""
    os.makedirs(os.path.join(outdir, 'parts'), exist_ok=True)
    with open(os.path.join(outdir, name + '.mtl'), 'w') as f:
        if has_atlas:
            f.write('newmtl tex\nKd 1 1 1\nmap_Kd %s_atlas.png\n' % name)
        f.write('newmtl vcol\nKd 1 1 1\n')
    posed = ['mtllib %s.mtl' % name]
    pbase = [1, 1, 1]
    for part in parts:
        R = np.array(part['kf0_matrix'])
        T = np.array(part['kf0_trans'], float)
        Rg = C @ R @ C
        Tg = C @ T
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
                P = np.array(d['P'])
                N = np.array(d['N'])
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
                    I = d['I']  # noqa: E741
                    for k in range(0, len(I), 3):
                        out.append('f ' + ' '.join('%d/%d/%d' % (base[0] + I[k + j], base[1] + I[k + j], base[2] + I[k + j])
                                                   for j in range(3)))
                    base[0] += len(PP)
                    base[1] += len(d['T'])
                    base[2] += len(NN)
        with open(os.path.join(outdir, 'parts', part['name'] + '.obj'), 'w') as f:
            f.write('\n'.join(local) + '\n')
    with open(os.path.join(outdir, name + '_posed.obj'), 'w') as f:
        f.write('\n'.join(posed) + '\n')


# ---------------------------------------------------------------- điểm vào
def export_source(gf, kind, model_rel, tim_rel, anim_rel=None, name=None, out_dir=None, write=True,
                  gltf_generator=GLTF_GENERATOR, png_level=9):
    """Xuất một nguồn -> (summary dict, errors list). summary['out'] = thư mục ra (khi write). ExportError khi không tải được.
    Khi errors không rỗng các file vẫn được ghi (như export_tmd.py) nhưng không nên dùng tiếp."""
    errors = []
    objs, kf0, tim, vram, origin, src, _model = load_source(gf, kind, model_rel, tim_rel, anim_rel, errors)
    name = name or default_name(kind, src['model'])
    atlas = build_atlas(objs, tim, vram, origin, errors)
    parts, winding = build_parts(objs, kf0, atlas, errors)
    flip = winding[1] > winding[0]
    ntri = sum(2 if f['quad'] else 1 for p in parts for f in p['faces'])
    nquad = sum(1 for p in parts for f in p['faces'] if f['quad'])
    W, Htot = (atlas[2], atlas[0].shape[0]) if atlas else (1, 1)
    summary = dict(name=name, kind=kind, source=src, parts=len(parts), verts=sum(len(p['verts']) for p in parts),
                   prims=sum(len(p['faces']) for p in parts), quads=nquad, tris=ntri,
                   untextured=sum(1 for p in parts for f in p['faces'] if not f['textured']),
                   winding_tmd_vs_loop=dict(same=winding[0], opposite=winding[1]), loop_reversed_for_outward=flip,
                   atlas=atlas[4] if atlas else None)
    if write:
        if out_dir is None:
            raise ValueError('out_dir')
        out = out_dir
        os.makedirs(out, exist_ok=True)
        if atlas:
            imgio.write_png(os.path.join(out, name + '_atlas.png'), atlas[0], png_level)
            imgio.write_png(os.path.join(out, name + '_atlas_pad.png'), pad_transparent(atlas[0]), png_level)
        doc = dict(summary, coord='PS1 raw: x right, y down, z forward-in; part posed = kf0_matrix @ v + kf0_trans',
                   atlas_size=[W, Htot], parts=parts)
        with open(os.path.join(out, name + '.json'), 'w', encoding='utf-8') as f:
            json.dump(doc, f)
        path_base = os.path.join(out, name)
        g, blob = build_gltf(path_base, name, parts, flip, W, Htot, atlas is not None, gltf_generator)
        with open(path_base + '.bin', 'wb') as f:
            f.write(blob)
        with open(path_base + '.gltf', 'w', encoding='utf-8') as f:
            json.dump(g, f, indent=1)
        check_gltf(g, blob, parts, errors)
        write_obj(out, name, parts, flip, W, Htot, atlas is not None)
        summary['out'] = rel_to_root(out)
    return summary, errors


def export_battle(gf, ch, form='combat', anim='0', name=None, out_dir=None, write=True, **kw):
    """Như 'export_tmd.py battle <ch> --form <form> --anim <anim>' (tên mặc định '<ch>_battle')."""
    base = 'characters/%s' % ch
    return export_source(gf, 'battle', '%s/models/%s/32' % (base, form), '%s/textures/%s' % (base, form),
                         anim_rel=None if anim is None else '%s/models/%s/%s' % (base, form, anim),
                         name=name or '%s_battle' % ch, out_dir=out_dir, write=write, **kw)


def export_field(gf, scene_dir, obj, name=None, out_dir=None, write=True, **kw):
    """Như 'export_tmd.py field <DRGN2x.BIN/cảnh> <obj>' (tên mặc định 'field_DRGN2x_<cảnh>_<obj>')."""
    scene_dir = scene_dir.replace('\\', '/').strip('/')
    base = 'SECT/%s' % scene_dir
    # đường dẫn theo chỉ số ảo của đối tượng: load_source giải mrg (mô hình / TIM liên kết), hoạt cảnh tìm từ obj*33+1
    return export_source(gf, 'field', '%s/%d' % (base, obj * 33), '%s/textures/%d' % (base, obj),
                         name=name or 'field_%s_%d' % (scene_dir.replace('/', '_').replace('.BIN', ''), obj),
                         out_dir=out_dir, write=write, **kw)


