"""facehash.py — FaceHash (SPEC §3.3), mặt LIVE (§3.4), xác minh biến thể (§4.4) trên VRAM ảo của bộ sinh.

FaceHash của một mặt có texture với bpp live b = (tpage >>> 7) & 3 ∈ {0, 1, 2}:
  tpX = (tpage & 0xF) * 64, tpY = 256 nếu tpage & 0x10 ngược lại 0; cx = (clut & 0x3F) * 16, cy = clut >>> 6;
  hộp bao uv live (bao gồm hai đầu), v ngoài, u trong; mọi lần đọc VRAM bọc (x & 1023, y & 511):
    b=0: idx = (V[tpY+v][tpX+(u>>2)] >> ((u&3)*4)) & 0xF;  px = V[cy][cx+idx]
    b=1: idx = (V[tpY+v][tpX+(u>>1)] >> ((u&1)*8)) & 0xFF; px = V[cy][cx+idx]
    b=2: px = V[tpY+v][tpX+u]
  FNV-1a 32 bit trên (px & 0xFF, px >>> 8) từng texel; kết quả 0 đổi thành 1. Mặt b = 3: không băm (0).
Hai loại véc-tơ (theo textured face index, tmd.textured_faces):
  raw_hashes    — FaceHash thô cho mọi mặt (b = 3 -> 0); = 'faceHashVectorSha1' của spec/vectors.json và véc-tơ runtime
                  mà -Dscvi.remasterLog in ra.
  stored_hashes — giá trị lưu trong biến thể LRM (§3.3.5): như trên nhưng ghi 0 cho mặt đọc ngoài TIM đã đặt
                  (dấu chân ảnh ngoài rect ảnh, hoặc dải CLUT 16 / 256 màu ngoài rect CLUT) -> LIVE d riêng biến thể đó.

Cách dùng:
  model = tmd.parse_ccontainer(data); t = tim.parse_tim(tdata)
  vram, irect, crect, adj = tim.virtual_vram(t, 'field_slot0'); adj and tmd.uv_adjust_model(model, *adj)
  faces, _ = tmd.model_faces(model)
  raw = raw_hashes(vram, faces); stored = stored_hashes(vram, faces, irect, crect); vector_sha1(raw)
  live = live_set(model, faces)                       # §3.4 a-c (chỉ số toàn cục)
"""
import hashlib
import struct

import numpy as np

from . import tmd as _tmd

FNV_OFFSET, FNV_PRIME = 0x811C9DC5, 0x01000193


def fnv1a32(data, h=FNV_OFFSET):
    """FNV-1a 32 bit trên dãy byte (bytes / bytearray / memoryview)."""
    for b in data:
        h = ((h ^ b) * FNV_PRIME) & 0xFFFFFFFF
    return h


def face_texels(vram, tpage, clut, uvs):
    """Texel 16 bit (gồm STP) của hộp bao uv theo thứ tự băm (v ngoài, u trong) -> mảng u16; None khi bpp = 3."""
    bpp = tpage >> 7 & 3
    if bpp == 3:
        return None
    tpx = (tpage & 0xF) * 64
    tpy = 256 if tpage & 0x10 else 0
    cx = (clut & 0x3F) * 16
    cy = clut >> 6
    us = [u for u, _ in uvs]
    vs = [v for _, v in uvs]
    u = np.arange(min(us), max(us) + 1, dtype=np.int64)
    v = np.arange(min(vs), max(vs) + 1, dtype=np.int64)
    U = np.tile(u, len(v))
    V = np.repeat(v, len(u))
    if bpp == 0:
        idx = (vram[(tpy + V) & 511, (tpx + (U >> 2)) & 1023].astype(np.int64) >> ((U & 3) * 4)) & 0xF
        px = vram[cy & 511, (cx + idx) & 1023]
    elif bpp == 1:
        idx = (vram[(tpy + V) & 511, (tpx + (U >> 1)) & 1023].astype(np.int64) >> ((U & 1) * 8)) & 0xFF
        px = vram[cy & 511, (cx + idx) & 1023]
    else:
        px = vram[(tpy + V) & 511, (tpx + U) & 1023]
    return np.asarray(px, np.uint16)


def face_hash(vram, f):
    """FaceHash §3.3.4 của một Face (tmd.Face); 0 khi bpp = 3 (không băm)."""
    px = face_texels(vram, f.tpage, f.clut, f.uv)
    if px is None:
        return 0
    h = fnv1a32(px.astype('<u2').tobytes())
    return h if h != 0 else 1


def footprint(f):
    """Dấu chân word VRAM của mặt (§3.4 b / §3.3.5): (x0, x1, y0, y1) bao gồm hai đầu, không bọc; None khi bpp = 3."""
    bpp = f.tpage >> 7 & 3
    if bpp == 3:
        return None
    sh = (2, 1, 0)[bpp]
    tpx = (f.tpage & 0xF) * 64
    tpy = 256 if f.tpage & 0x10 else 0
    us = [u for u, _ in f.uv]
    vs = [v for _, v in f.uv]
    return tpx + (min(us) >> sh), tpx + (max(us) >> sh), tpy + min(vs), tpy + max(vs)


def outside_tim(f, irect, crect):
    """§3.3.5: dấu chân ảnh không nằm trọn rect ảnh đã đặt, hoặc (4/8bpp) dải CLUT không nằm trọn rect CLUT."""
    fp = footprint(f)
    if fp is None:
        return False
    x0, x1, y0, y1 = fp
    ix, iy, iw, ih = irect
    if x0 < ix or x1 >= ix + iw or y0 < iy or y1 >= iy + ih:
        return True
    bpp = f.tpage >> 7 & 3
    if bpp in (0, 1):
        if crect is None:
            return True
        cx, cy = (f.clut & 0x3F) * 16, f.clut >> 6
        n = 16 if bpp == 0 else 256
        rx, ry, rw, rh = crect
        if cx < rx or cx + n > rx + rw or cy < ry or cy >= ry + rh:
            return True
    return False


def _box_key(f):
    us = [u for u, _ in f.uv]
    vs = [v for _, v in f.uv]
    return f.tpage, f.clut, min(us), max(us), min(vs), max(vs)


def raw_hashes(vram, all_faces):
    """FaceHash thô mọi mặt có texture (b = 3 -> 0), theo textured face index. Mặt cùng (tpage, clut, hộp uv) dùng lại kết
    quả (FaceHash chỉ phụ thuộc các giá trị đó và VRAM)."""
    memo = {}
    out = []
    for f in _tmd.textured_faces(all_faces):
        k = _box_key(f)
        h = memo.get(k)
        if h is None:
            h = memo[k] = face_hash(vram, f)
        out.append(h)
    return out


def stored_hashes(vram, all_faces, irect, crect):
    """Giá trị lưu trong biến thể (§3.3.5): FaceHash, trừ mặt b = 3 hoặc đọc ngoài TIM -> 0."""
    out = []
    for f in _tmd.textured_faces(all_faces):
        if (f.tpage >> 7 & 3) == 3 or outside_tim(f, irect, crect):
            out.append(0)
        else:
            out.append(face_hash(vram, f))
    return out


def stored_from_raw(raw, all_faces, irect, crect):
    """Áp quy tắc ghi 0 của §3.3.5 lên véc-tơ thô đã tính (tránh băm lại)."""
    tex = _tmd.textured_faces(all_faces)
    return [0 if (f.tpage >> 7 & 3) == 3 or outside_tim(f, irect, crect) else h for f, h in zip(tex, raw)]


def vector_bytes(hashes):
    return b''.join(struct.pack('<I', h & 0xFFFFFFFF) for h in hashes)


def vector_sha1(hashes):
    """faceHashVectorSha1 (§3.3.6): SHA-1 hex của u32 LE nối theo textured face index."""
    return hashlib.sha1(vector_bytes(hashes)).hexdigest()


def anim_rects(model):
    """Rect đích của mọi animationMetrics_d0[i] (i < 7) có >= 5 short: x = m1 + tpageX, y = m2 + tpageY,
    w = m3 / 4 (chia nguyên Java, cắt về 0), h = m4. Rỗng khi uvAdjustments = NONE hoặc không có subfile2."""
    if model.tex_anims is None or model.uv_adjust is None:
        return []
    tx, ty = model.uv_adjust
    rects = []
    for m in model.tex_anims[:7]:
        if m is None or len(m) < 5:
            continue
        w = int(m[3] / 4)
        rects.append((m[1] + tx, m[2] + ty, w, m[4]))
    return rects


def live_set(model, all_faces):
    """Tập textured face index LIVE theo §3.4 a (CLUT anim), b (giao rect hoạt cảnh texture), c (bpp 3)."""
    tex = _tmd.textured_faces(all_faces)
    if model.clut_anim:
        return set(range(len(tex)))
    rects = [r for r in anim_rects(model) if r[2] > 0 and r[3] > 0]
    live = set()
    for g, f in enumerate(tex):
        fp = footprint(f)
        if fp is None:
            live.add(g)
            continue
        x0, x1, y0, y1 = fp
        for rx, ry, rw, rh in rects:
            if x0 < rx + rw and rx <= x1 and y0 < ry + rh and ry <= y1:
                live.add(g)
                break
    return live


def effective_live(model_live, variant_hashes):
    """LIVE của bộ ATLAS một biến thể: LIVE(a-c) ∪ {g : faceHash lưu = 0} (§3.4 d)."""
    return set(model_live) | {g for g, h in enumerate(variant_hashes) if h == 0}


def verify_variants(runtime_hashes, variants_hashes, live):
    """§4.4: chỉ số biến thể đầu tiên mà mọi mặt không LIVE (a-c) có hash lưu != 0 đều trùng hash runtime; None nếu không."""
    for vi, vh in enumerate(variants_hashes):
        ok = True
        for g, h in enumerate(vh):
            if g in live or h == 0:
                continue
            if runtime_hashes[g] != h:
                ok = False
                break
        if ok:
            return vi
    return None
