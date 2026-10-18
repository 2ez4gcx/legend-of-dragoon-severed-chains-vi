"""lrm.py — file LRM1 (SPEC §3.5): ghi xác định, đọc + kiểm bắt buộc §3.5.4; index.tsv (§3.7); lưới 16 float (§3.2, §4.3).

Bố cục (little-endian):
  header 0x40: 'LRM1', u16 version 1, u16 flags (bit 0 = thân zlib), u8[20] modelKey, u16 partCount (1..64),
               u16 variantCount (0..4), u32 bodySize (<= 256 MiB, sau giải nén), u8 level (0..2), u8[3] 0,
               char[24] generator (ASCII 0x20..0x7E, đệm 0)
  thân: part[partCount] rồi variant[variantCount]
    part: u8[20] partKey, u32 srcFaceCount, u8 mode (0 giữ gốc / 1 thay), u8[3] 0,
          mode 1: u32 P, u32 C, u32 T (P >= 1, C >= 3, T >= 1, mỗi số <= 200000), f32 pos[P][3], corner[C] (32 byte),
                  u32 tri[T][3]
      corner: u32 pos, f32 nx, ny, nz, u32 srcFace, u16 s, u16 t, u16 nearestTmdVertex, u8 role (0 base, 1 decal,
              2 back), u8 0, u8[4] reserved 0
    variant: u8[20] pngSha1, u16 w, u16 h (luỹ thừa 2, <= 2048), u32 texturedFaceCount (n), u32 faceHash[n],
             f32 atlasUv[n][4][2] (chuẩn hoá [0,1], góc thứ 4 của tam giác = (0,0))
Bộ ghi xác định: cùng dữ liệu -> cùng byte khi không nén; thân nén (deflate=True, zlib mức 9) phụ thuộc bản zlib, so
phần thân đã giải (§3.5.5).

Cách dùng:
  data = write_lrm(Lrm(model_key, parts, variants, level=2, generator='lodsc-remaster 1'))
  lrm = read_lrm(data, expect_key=key, runtime=runtime_info(model))    # LrmError nếu sai bất kỳ điều nào của §3.5.4
  part = part_from_arrays(part_key, src_face_count, pos, corner_pos, corner_n, corner_face, corner_st, corner_near,
                          corner_role, tri)              # mảng theo lược đồ geom_L*.npz (§3.8)
  write_index([(key_hex, nhãn)]) / read_index(data)       # index.tsv
  meshes = remaster_part_meshes(faces, backface, lrm_part, atlas=None | atlasUv, live=set(), tex_base=g0)
"""
import hashlib
import re
import struct
import zlib

import numpy as np

from . import GENERATOR, LrmError, SpecError, tmd as _tmd

LRM_MAGIC = b'LRM1'
LRM_VERSION = 1
HEADER_SIZE = 0x40
MAX_PARTS = 64
MAX_VARIANTS = 4
MAX_PCT = 200000
MAX_BODY = 0x10000000
MAX_TEX = 2048
MAX_LEVEL = 2
ROLE_BASE, ROLE_DECAL, ROLE_BACK = 0, 1, 2
CORNER_DT = np.dtype([('pos', '<u4'), ('n', '<f4', (3,)), ('src', '<u4'), ('s', '<u2'), ('t', '<u2'),
                      ('near', '<u2'), ('role', 'u1'), ('zero', 'u1'), ('reserved', '<u4')])
assert CORNER_DT.itemsize == 32


class LrmPart:
    def __init__(self, key, src_face_count, mode, pos=None, corners=None, tri=None):
        self.key = bytes(key)
        self.src_face_count = int(src_face_count)
        self.mode = int(mode)
        self.pos = np.zeros((0, 3), '<f4') if pos is None else np.asarray(pos, '<f4').reshape(-1, 3)
        self.corners = np.zeros(0, CORNER_DT) if corners is None else np.asarray(corners, CORNER_DT)
        self.tri = np.zeros((0, 3), '<u4') if tri is None else np.asarray(tri, '<u4').reshape(-1, 3)


class LrmVariant:
    def __init__(self, png_sha1, w, h, face_hash, atlas_uv):
        self.png_sha1 = bytes(png_sha1)
        self.w, self.h = int(w), int(h)
        self.face_hash = np.asarray(face_hash, '<u4').reshape(-1)
        self.atlas_uv = np.asarray(atlas_uv, '<f4').reshape(-1, 4, 2)


class Lrm:
    def __init__(self, model_key, parts, variants, level=0, generator=GENERATOR, deflate=False):
        self.model_key = bytes(model_key)
        self.parts = parts
        self.variants = variants
        self.level = level
        self.generator = generator
        self.deflate = deflate


def make_corners(corner_pos, corner_n, corner_face, corner_st, corner_near, corner_role):
    """Mảng corner có cấu trúc (32 byte/corner) từ các mảng của geom_L*.npz (§3.8)."""
    n = len(corner_pos)
    c = np.zeros(n, CORNER_DT)
    c['pos'] = np.asarray(corner_pos, np.uint32).reshape(n)
    c['n'] = np.asarray(corner_n, np.float32).reshape(n, 3)
    c['src'] = np.asarray(corner_face, np.uint32).reshape(n)
    st = np.asarray(corner_st, np.uint16).reshape(n, 2)
    c['s'] = st[:, 0]
    c['t'] = st[:, 1]
    c['near'] = np.asarray(corner_near, np.uint16).reshape(n)
    c['role'] = np.asarray(corner_role, np.uint8).reshape(n)
    return c


def part_from_arrays(key, src_face_count, pos, corner_pos, corner_n, corner_face, corner_st, corner_near, corner_role,
                     tri, mode=1):
    """LrmPart mode 1 (hoặc mode 0 nếu mode=0, bỏ qua mảng)."""
    if mode == 0:
        return LrmPart(key, src_face_count, 0)
    return LrmPart(key, src_face_count, 1, pos,
                   make_corners(corner_pos, corner_n, corner_face, corner_st, corner_near, corner_role), tri)


def model_key_of(part_keys):
    return hashlib.sha1(b'LRMK1' + struct.pack('<H', len(part_keys)) + b''.join(part_keys)).digest()


# ---------------------------------------------------------------- ghi
def lrm_body(lrm):
    out = bytearray()
    for p in lrm.parts:
        if len(p.key) != 20:
            raise LrmError('partKey phai 20 byte')
        out += p.key + struct.pack('<IB3x', p.src_face_count, p.mode)
        if p.mode == 1:
            out += struct.pack('<III', len(p.pos), len(p.corners), len(p.tri))
            out += np.ascontiguousarray(p.pos, '<f4').tobytes()
            out += np.ascontiguousarray(p.corners, CORNER_DT).tobytes()
            out += np.ascontiguousarray(p.tri, '<u4').tobytes()
    for v in lrm.variants:
        if len(v.png_sha1) != 20:
            raise LrmError('pngSha1 phai 20 byte')
        out += v.png_sha1 + struct.pack('<HHI', v.w, v.h, len(v.face_hash))
        out += np.ascontiguousarray(v.face_hash, '<u4').tobytes()
        out += np.ascontiguousarray(v.atlas_uv, '<f4').tobytes()
    return bytes(out)


def write_lrm(lrm, validate=True):
    """-> byte file LRM1. validate=True: đọc lại bằng read_lrm (mọi kiểm §3.5.4 không cần runtime) trước khi trả."""
    body = lrm_body(lrm)
    gen = lrm.generator.encode('ascii')
    if len(gen) > 24 or b'\0' in gen or any(c < 0x20 or c > 0x7e for c in gen):
        raise LrmError('generator phai ASCII 0x20..0x7E, <= 24 byte')
    if len(lrm.model_key) != 20:
        raise LrmError('modelKey phai 20 byte')
    head = LRM_MAGIC + struct.pack('<HH', LRM_VERSION, 1 if lrm.deflate else 0) + lrm.model_key
    head += struct.pack('<HHIB3x', len(lrm.parts), len(lrm.variants), len(body), lrm.level) + gen.ljust(24, b'\0')
    assert len(head) == HEADER_SIZE
    data = head + (zlib.compress(body, 9) if lrm.deflate else body)
    if validate:
        read_lrm(data)
    return data


# ---------------------------------------------------------------- đọc + kiểm (§3.5.4)
def _finite(a):
    # không ép sang float64: NaN báo hiệu (sNaN) trong f32 sẽ bật cờ 'invalid' -> RuntimeWarning vô ích
    return bool(np.all(np.isfinite(np.asarray(a))))


def runtime_info(model):
    """Số đếm runtime của một tmd.Model cho read_lrm(runtime=...): srcFaceCount và n_vert từng phần, số mặt có texture."""
    sfc, nv, tex = [], [], 0
    for p in model.parts:
        pk = p.packets()
        sfc.append(len(pk))
        nv.append(len(p.verts))
        tex += sum(1 for h, _ in pk if h >> 24 & 0x4)
    return dict(src_face_counts=sfc, n_verts=nv, textured=tex)


def read_lrm(data, expect_key=None, runtime=None):
    """Đọc + kiểm theo §3.5.4 (mục 1-7). runtime (tuỳ chọn): runtime_info(model) của mô hình đang nạp. Sai => LrmError."""
    data = bytes(data)
    if len(data) < HEADER_SIZE:
        raise LrmError('file ngan hon header (%d byte)' % len(data))
    if data[:4] != LRM_MAGIC:
        raise LrmError('magic sai')
    version, flags = struct.unpack_from('<HH', data, 4)
    if version != LRM_VERSION:
        raise LrmError('version %d != 1' % version)
    if flags & ~1:
        raise LrmError('flags 0x%x co bit la' % flags)
    mkey = data[8:28]
    pcount, vcount, body_size, level = struct.unpack_from('<HHIB', data, 0x1c)
    if data[0x25:0x28] != b'\0\0\0':
        raise LrmError('byte zero header != 0')
    gname = data[0x28:0x40].rstrip(b'\0')
    if b'\0' in gname or any(c < 0x20 or c > 0x7e for c in gname):
        raise LrmError('generator khong phai ASCII dem 0')
    if not 1 <= pcount <= MAX_PARTS:
        raise LrmError('partCount %d ngoai 1..64' % pcount)
    if vcount > MAX_VARIANTS:
        raise LrmError('variantCount %d > 4' % vcount)
    if level > MAX_LEVEL:
        raise LrmError('level %d > 2' % level)
    if body_size > MAX_BODY:
        raise LrmError('bodySize %d > 256 MiB' % body_size)
    if expect_key is not None and mkey != bytes(expect_key):
        raise LrmError('modelKey khac khoa runtime / ten file')
    if runtime is not None:
        if pcount != len(runtime['src_face_counts']) or pcount != len(runtime['n_verts']):
            raise LrmError('partCount %d != so phan runtime %d' % (pcount, len(runtime['src_face_counts'])))
    raw = data[HEADER_SIZE:]
    if flags & 1:
        d = zlib.decompressobj()
        try:
            body = d.decompress(raw, body_size + 1)
        except zlib.error as e:
            raise LrmError('than deflate loi: %s' % e)
        if len(body) != body_size or not d.eof or d.unused_data or d.unconsumed_tail:
            raise LrmError('than deflate khong dung bodySize / khong ket thuc / thua byte')
    else:
        body = raw
        if len(body) != body_size:
            raise LrmError('bodySize %d != %d byte con lai' % (body_size, len(body)))
    o = 0

    def take(n):
        nonlocal o
        if n < 0 or o + n > len(body):
            raise LrmError('than bi cat (can %d byte tai %d / %d)' % (n, o, len(body)))
        b = body[o:o + n]
        o += n
        return b

    parts = []
    for pi in range(pcount):
        key = take(20)
        sfc, mode = struct.unpack('<IB', take(5))
        if take(3) != b'\0\0\0':
            raise LrmError('phan %d: byte zero != 0' % pi)
        if mode not in (0, 1):
            raise LrmError('phan %d: mode %d' % (pi, mode))
        if runtime is not None and sfc != runtime['src_face_counts'][pi]:
            raise LrmError('phan %d: srcFaceCount %d != runtime %d' % (pi, sfc, runtime['src_face_counts'][pi]))
        if mode == 0:
            parts.append(LrmPart(key, sfc, 0))
            continue
        P, C, T = struct.unpack('<III', take(12))
        if P > MAX_PCT or C > MAX_PCT or T > MAX_PCT:
            raise LrmError('phan %d: P/C/T vuot 200000' % pi)
        if P < 1 or C < 3 or T < 1:
            raise LrmError('phan %d: mode 1 nhung P/C/T rong' % pi)
        if 12 * P + 32 * C + 12 * T > len(body) - o:     # mục 3 trước khi cấp phát
            raise LrmError('phan %d: than bi cat' % pi)
        pos = np.frombuffer(take(12 * P), '<f4').reshape(P, 3).copy()
        corners = np.frombuffer(take(32 * C), CORNER_DT).copy()
        tri = np.frombuffer(take(12 * T), '<u4').reshape(T, 3).copy()
        if not _finite(pos) or not _finite(corners['n']):
            raise LrmError('phan %d: float NaN/Inf' % pi)
        if np.any(corners['pos'] >= P):
            raise LrmError('phan %d: corner.pos >= P' % pi)
        if np.any(corners['src'] >= sfc):
            raise LrmError('phan %d: corner.srcFace >= srcFaceCount' % pi)
        if np.any(corners['role'] > 2):
            raise LrmError('phan %d: role > 2' % pi)
        if np.any(corners['zero'] != 0) or np.any(corners['reserved'] != 0):
            raise LrmError('phan %d: byte zero/reserved cua corner != 0' % pi)
        if runtime is not None and np.any(corners['near'] >= runtime['n_verts'][pi]):
            raise LrmError('phan %d: nearestTmdVertex >= n_vert' % pi)
        if np.any(tri >= C):
            raise LrmError('phan %d: chi so tri >= C' % pi)
        src = corners['src'][tri.astype(np.int64)]
        if np.any(src[:, 0] != src[:, 1]) or np.any(src[:, 0] != src[:, 2]):
            raise LrmError('phan %d: tam giac co corner khac srcFace' % pi)
        if T > 1 and np.any(np.diff(src[:, 0].astype(np.int64)) < 0):
            raise LrmError('phan %d: tam giac khong xep theo srcFace tang dan' % pi)
        parts.append(LrmPart(key, sfc, 1, pos, corners, tri))
    if model_key_of([p.key for p in parts]) != mkey:
        raise LrmError('modelKey != SHA-1(LRMK1 + partCount + partKeys)')
    variants = []
    tcount = None
    for vi in range(vcount):
        sha = take(20)
        w, h, n = struct.unpack('<HHI', take(8))
        if w < 1 or h < 1 or w > MAX_TEX or h > MAX_TEX or w & (w - 1) or h & (h - 1):
            raise LrmError('bien the %d: kich thuoc %dx%d khong phai luy thua 2 <= 2048' % (vi, w, h))
        if 36 * n > len(body) - o:
            raise LrmError('bien the %d: than bi cat (texturedFaceCount %d)' % (vi, n))
        if tcount is not None and n != tcount:
            raise LrmError('bien the %d: texturedFaceCount khac bien the 0' % vi)
        tcount = n
        if runtime is not None and n != runtime['textured']:
            raise LrmError('bien the %d: texturedFaceCount %d != runtime %d' % (vi, n, runtime['textured']))
        fh = np.frombuffer(take(4 * n), '<u4').copy()
        uv = np.frombuffer(take(32 * n), '<f4').reshape(n, 4, 2).copy()
        if not _finite(uv) or np.any(uv < 0) or np.any(uv > 1):
            raise LrmError('bien the %d: atlasUv NaN/Inf hoac ngoai [0,1]' % vi)
        variants.append(LrmVariant(sha, w, h, fh, uv))
    if o != len(body):
        raise LrmError('thua %d byte sau bien the cuoi' % (len(body) - o))
    return Lrm(mkey, parts, variants, level, gname.decode('ascii'), bool(flags & 1))


def roundtrip(data):
    """Đọc rồi ghi lại -> (trùng_byte, trùng_thân_đã_giải). File nén: so header + thân đã giải (§3.5.5)."""
    lrm = read_lrm(data)
    out = write_lrm(lrm, validate=False)
    if out == bytes(data):
        return True, True
    if lrm.deflate:
        same_body = out[:HEADER_SIZE] == bytes(data[:HEADER_SIZE]) and \
            zlib.decompress(bytes(data[HEADER_SIZE:])) == lrm_body(lrm)
        return False, same_body
    return False, False


# ---------------------------------------------------------------- index.tsv (§3.7)
KEY_RE = re.compile(r'[0-9a-f]{40}')        # chỉ dùng với fullmatch ('$' của re.match nhận cả '\n' ở cuối)
INDEX_HEADER = 'LRMINDEX\t1'


def write_index(entries):
    """[(khoá hex, nhãn)] -> byte UTF-8 (không BOM, LF). Nhãn không được chứa TAB/CR/LF."""
    lines = [INDEX_HEADER]
    for key, label in entries:
        if not KEY_RE.fullmatch(key) or '\t' in label or '\n' in label or '\r' in label:
            raise LrmError('muc index sai: %r %r' % (key, label))
        lines.append('%s\tmodels/%s.lrm\t%s' % (key, key, label))
    return ('\n'.join(lines) + '\n').encode('utf-8')


def read_index(data):
    """-> {khoá hex: nhãn}. Sai định dạng (kể cả byte không phải UTF-8) -> LrmError (runtime coi như không có chỉ mục)."""
    if data[:3] == b'\xef\xbb\xbf':
        raise LrmError('index.tsv co BOM')
    try:
        text = bytes(data).decode('utf-8')
    except UnicodeDecodeError as e:
        raise LrmError('index.tsv khong phai UTF-8: %s' % e)
    lines = text.split('\n')
    if lines[0] != INDEX_HEADER:
        raise LrmError('dong 1 index.tsv phai la LRMINDEX<TAB>1')
    out = {}
    for ln in lines[1:]:
        if ln == '':
            continue
        cols = ln.split('\t')
        if len(cols) != 3 or not KEY_RE.fullmatch(cols[0]) or cols[1] != 'models/%s.lrm' % cols[0] or '\r' in cols[2]:
            raise LrmError('dong index sai: %r' % ln)
        out[cols[0]] = cols[2]
    return out


# ---------------------------------------------------------------- lưới 16 float (TmdObjLoader.createMesh, §3.2.3, §4.3)
F32 = np.float32


def _colour_floats(colour, textured):
    """MathHelper.colourToFloat (+ x2 cả 4 kênh khi có texture, TmdObjLoader.java:258-268)."""
    m = colour >> 24 & 0xff
    b = colour >> 16 & 0xff
    g = colour >> 8 & 0xff
    r = colour & 0xff
    out = [F32(r) / F32(255.0), F32(g) / F32(255.0), F32(b) / F32(255.0), F32(m) / F32(255.0)]
    if textured:
        out = [x * F32(2.0) for x in out]
    return out


def _normal_f32(part, ni):
    if ni >= len(part.normals):
        return [F32(0.0)] * 3
    return [F32(c) / F32(4096.0) for c in part.normals[ni]]


def retail_part_meshes(part, faces, backface, tw=0, th=0):
    """Lưới TmdObjLoader.fromObjTable của một phần (specialFlags = 0) -> dict(meshes=[...] theo thứ tự vẽ, backfaceCulling).
    Mỗi lưới: cls, textured, translucent, translucency, vertices f32 [N*16], indices i32."""
    any_tex = any(f.textured for f in faces)
    present = {f.mclass for f in faces}
    data = {c: ([], []) for c in present}
    for f in faces:
        verts, idx = data[f.mclass]
        vi = len(verts) // 16
        a1, a2 = vi + 3, vi
        idx += [vi + 2, a1, vi + 1, a1, vi, a1]
        if f.quad:
            idx += [vi + 1, a2, vi + 2, a2, vi + 3, a2]
        for k in range(f.vc):
            x, y, z = part.verts[f.vidx[k]]
            row = [F32(x), F32(y), F32(z), F32(f.vidx[k])]
            row += _normal_f32(part, f.nidx[k]) if f.lit else [F32(0.0)] * 3
            if f.textured:
                u, v = f.uv[k]
                if (f.tpage >> 7 & 3) == 3:
                    if (tw | th) == 0:
                        raise SpecError('24bpp textures must have texture width/height specified')
                    row += [F32(u) / F32(tw), F32(v) / F32(th)]
                else:
                    row += [F32(u), F32(v)]
                row += [F32(f.tpage), F32(f.clut)]
            else:
                row += [F32(0.0)] * 4
            row += _colour_floats(f.colours[k], f.textured) if f.coloured else [F32(1.0)] * 4
            row.append(F32(f.flags))
            verts += row
    out = []
    for c in _tmd.class_order(present):
        t, tr, tl = _tmd.mesh_props(c, any_tex)
        verts, idx = data[c]
        out.append(dict(cls=_tmd.class_name(c), textured=t, translucent=tr, translucency=tl,
                        vertices=np.array(verts, np.float32), indices=np.array(idx, np.int32)))
    return dict(meshes=out, backfaceCulling=backface)


def corner_weights(S, T, quad):
    """§3.2.2: s = S/65535f, t = T/65535f; tam giác kẹp s+t <= 1 bằng t = 1 - s; tứ giác song tuyến (thứ tự Z)."""
    one = F32(1.0)
    s = F32(S) / F32(65535.0)
    t = F32(T) / F32(65535.0)
    if quad:
        return [(one - s) * (one - t), s * (one - t), (one - s) * t, s * t]
    if s + t > one:
        t = one - s
    return [(one - s) - t, s, t]


def interp(w, xs):
    """((w0*x0 + w1*x1) + w2*x2) [+ w3*x3], mỗi phép làm tròn f32."""
    acc = w[0] * xs[0]
    for k in range(1, len(w)):
        acc = acc + w[k] * xs[k]
    return acc


def remaster_part_meshes(faces, backface, lpart, tw=0, th=0, atlas=None, live=frozenset(), tex_base=0):
    """Lưới của một phần mode 1 (§4.3): bộ VRAM (atlas=None) hoặc bộ ATLAS (atlas = atlasUv f32 [n,4,2] của biến thể,
    live = tập textured face index LIVE của biến thể đó). tex_base = textured face index của mặt có texture đầu phần."""
    any_tex = any(f.textured for f in faces)
    tex_index = {}
    k = tex_base
    for f in faces:
        if f.textured:
            tex_index[f.index] = k
            k += 1
    corners = lpart.corners
    srcs = corners['src']
    tri_cls = [faces[int(srcs[t[0]])].mclass for t in lpart.tri]
    present = set(tri_cls)
    out = []
    zero = F32(0.0)
    for c in _tmd.class_order(present):
        sel = [i for i in range(len(corners)) if faces[int(srcs[i])].mclass == c]
        local = {ci: j for j, ci in enumerate(sel)}
        verts = []
        for ci in sel:
            cr = corners[ci]
            f = faces[int(cr['src'])]
            p = lpart.pos[int(cr['pos'])]
            row = [F32(p[0]), F32(p[1]), F32(p[2]), F32(int(cr['near']))]
            row += [F32(x) for x in cr['n']] if f.lit else [zero] * 3
            w = corner_weights(int(cr['s']), int(cr['t']), f.quad)
            if f.textured:
                g = tex_index[f.index]
                if atlas is not None and g not in live:
                    au = interp(w, [F32(atlas[g][j][0]) for j in range(f.vc)])
                    av = interp(w, [F32(atlas[g][j][1]) for j in range(f.vc)])
                    row += [au, av, F32((f.tpage & ~0x180) | 0x180), F32(f.clut)]
                else:
                    u = interp(w, [F32(f.uv[j][0]) for j in range(f.vc)])
                    v = interp(w, [F32(f.uv[j][1]) for j in range(f.vc)])
                    if (f.tpage >> 7 & 3) == 3:
                        if (tw | th) == 0:
                            raise SpecError('24bpp textures must have texture width/height specified')
                        u = u / F32(tw)
                        v = v / F32(th)
                    row += [u, v, F32(f.tpage), F32(f.clut)]
            else:
                row += [zero] * 4
            if f.coloured:
                cols = [_colour_floats(f.colours[j], f.textured) for j in range(f.vc)]
                row += [interp(w, [cols[j][ch] for j in range(f.vc)]) for ch in range(4)]
            else:
                row += [F32(1.0)] * 4
            row.append(F32(f.flags & ~_tmd.QUAD_FLAG))
            verts += row
        idx = []
        for t, tc in zip(lpart.tri, tri_cls):
            if tc != c:
                continue
            a, b, cc = local[int(t[0])], local[int(t[1])], local[int(t[2])]
            idx += [a, a, b, a, cc, a]
        tx, tr, tl = _tmd.mesh_props(c, any_tex)
        out.append(dict(cls=_tmd.class_name(c), textured=tx, translucent=tr, translucency=tl,
                        vertices=np.array(verts, np.float32), indices=np.array(idx, np.int32)))
    return dict(meshes=out, backfaceCulling=backface)
