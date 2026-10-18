"""anims.py — hoạt cảnh TMD (TmdAnimationFile của SC) và cách tìm file hoạt cảnh của một nguồn mô hình (QA hình học).

TmdAnimationFile (game/types/TmdAnimationFile.java): u16 @0xc = số phần, s16 @0xe = totalFrames, số khung khoá =
totalFrames / 2 (chia nguyên Java), khung khoá k phần i ở 0x10 + (k * số phần + i) * 0xc: svec3 quay (4096 = 360°) rồi
svec3 dời (Keyframe0c: quat.rotationZYX(z, y, x) = Rz * Ry * Rx). File bắt đầu bằng u32 0x11 là PXL (lỗi bán lẻ DRGN24.938,
SC bỏ qua — RetailSubmap.prepareSobjs).

Tìm hoạt cảnh (find_anims, theo chỗ SC nạp):
  battle  'characters/<c>/models/<form>/32': mọi mục khác 32 của thư mục models/<form> (mrg đã giải) — mục 0 trước;
  field   'SECT/DRGN2x.BIN/<cảnh>/<obj*33>': mục obj*33+1 .. obj*33+32 (mrg đã giải), bỏ PXL;
  story   'SECT/DRGN0.BIN/<N>': các file N+2 .. N+40 (N+1 là TIM) — dừng ở file đầu tiên không phải hoạt cảnh sau khi
          đã gặp hoạt cảnh;
  monster 'SECT/DRGN0.BIN/<3137+id>/32': mục 0..31 của thư mục.
Chỉ giữ file có số phần = số phần mô hình (như export_tmd.py); trùng file thật thì giữ một.

Cách dùng:
  a = parse_anim(data)                 # Anim: rot int16 [K, P, 3], trans int16 [K, P, 3]
  found = find_anims(gf, 'battle', 'characters/dart/models/combat/32', nparts=17)   # [(rel, Anim)]
  R = rot_zyx(*a.rot[0, i])            # ma trận 3x3 (float64) như export_tmd.py
"""
import math
import struct

import numpy as np

from . import GameFileError, SpecError

PXL_MAGIC = 0x11


class Anim:
    __slots__ = ('part_count', 'total_frames', 'rot', 'trans', 'path')

    def __init__(self, part_count, total_frames, rot, trans, path=None):
        self.part_count = part_count
        self.total_frames = total_frames
        self.rot = rot          # int16 [K, P, 3] (rx, ry, rz) 4096 = 360°
        self.trans = trans      # int16 [K, P, 3]
        self.path = path

    @property
    def keyframes(self):
        return self.rot.shape[0]


def anim_part_count(data):
    """Số phần của file hoạt cảnh; None nếu file quá ngắn hoặc là PXL (u32 @0 = 0x11)."""
    if len(data) < 0x10 or struct.unpack_from('<I', data, 0)[0] == PXL_MAGIC:
        return None
    return struct.unpack_from('<H', data, 0xc)[0]


def parse_anim(data, path=None):
    """TmdAnimationFile(data) -> Anim. SpecError khi Java sẽ ném lỗi (khung khoá ngoài file, totalFrames âm)."""
    if len(data) < 0x10:
        raise SpecError('hoat canh qua ngan')
    parts = struct.unpack_from('<H', data, 0xc)[0]
    total = struct.unpack_from('<h', data, 0xe)[0]
    k = int(total / 2)                       # chia nguyên Java (cắt về 0)
    if k < 0:
        raise SpecError('totalFrames am (%d)' % total)
    need = 0x10 + k * parts * 12
    if need > len(data):
        raise SpecError('hoat canh: %d khung khoa x %d phan vuot file (%d > %d)' % (k, parts, need, len(data)))
    a = np.frombuffer(data, '<i2', k * parts * 6, 0x10).reshape(k, parts, 6).astype(np.int16)
    return Anim(parts, total, a[..., :3].copy(), a[..., 3:].copy(), path)


def kf0(data):
    """Khung khoá 0 như export_tmd.py parse_anim_kf0 -> (số phần, [((rx,ry,rz), (tx,ty,tz))] hoặc None)."""
    parts = struct.unpack_from('<H', data, 0xc)[0]
    if 0x10 + parts * 12 > len(data):
        return parts, None
    row = []
    for p in range(parts):
        rx, ry, rz, tx, ty, tz = struct.unpack_from('<hhhhhh', data, 0x10 + p * 12)
        row.append(((rx, ry, rz), (tx, ty, tz)))
    return parts, row


def rot_zyx(rx, ry, rz):
    """JOML Quaternionf.rotationZYX(z, y, x) == Rz * Ry * Rx (psx: 4096 = 360°), float64 — giống export_tmd.py."""
    a = [v / 4096.0 * 2 * math.pi for v in (rx, ry, rz)]
    cx, sx = math.cos(a[0]), math.sin(a[0])
    cy, sy = math.cos(a[1]), math.sin(a[1])
    cz, sz = math.cos(a[2]), math.sin(a[2])
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def part_transforms(anim, k):
    """-> (R float64 [P, 3, 3], T float64 [P, 3]) của khung khoá k: điểm đặt tư thế = R @ v + T (cục bộ phần)."""
    R = np.stack([rot_zyx(*[int(c) for c in anim.rot[k, i]]) for i in range(anim.part_count)]) \
        if anim.part_count else np.zeros((0, 3, 3))
    return R, anim.trans[k].astype(np.float64)


def all_keyframes(anims):
    """[(rel, chỉ số khung khoá, R [P,3,3], T [P,3])] cho mọi khung khoá của mọi hoạt cảnh (QA khớp nối)."""
    out = []
    for rel, a in anims:
        for k in range(a.keyframes):
            R, T = part_transforms(a, k)
            out.append((rel, k, R, T))
    return out


# ---------------------------------------------------------------- tìm file hoạt cảnh của một nguồn
def _try(gf, rel, nparts, seen, out):
    if rel is None or rel in seen:
        return False
    try:
        data = gf.read(rel)
    except GameFileError:
        return False
    if anim_part_count(data) != nparts:
        return False
    try:
        a = parse_anim(data, rel)
    except SpecError:
        return False
    seen.add(rel)
    out.append((rel, a))
    return True


def _dir_entries(gf, d, indices, nparts):
    out, seen = [], set()
    for i in indices:
        try:
            e = gf.entry(d, i)
        except GameFileError:
            e = None
        if e is None or e.is_dir:
            continue
        _try(gf, e.path, nparts, seen, out)
    return out


def find_anims(gf, kind, model_rel, nparts):
    """Mọi hoạt cảnh khớp số phần của một nguồn (xem docstring mô-đun) -> [(rel file thật, Anim)] theo thứ tự tìm."""
    model_rel = gf.norm(model_rel)
    d, _, name = model_rel.rpartition('/')
    if kind == 'battle':
        files = gf.load_dir(d)
        idx = [0] + [i for i in range(1, len(files)) if i != 32]
        return _dir_entries(gf, d, idx, nparts)
    if kind == 'monster':
        return _dir_entries(gf, d, range(0, 32), nparts)
    if kind == 'field':
        base = int(name) // 33 * 33
        return _dir_entries(gf, d, range(base + 1, base + 33), nparts)
    if kind == 'story':
        n = int(name)
        out, seen = [], set()
        for k in range(n + 2, n + 41):
            rel = '%s/%d' % (d, k)
            if not gf.exists(rel):
                break
            ok = _try(gf, rel, nparts, seen, out)
            if not ok and out:
                break
        return out
    raise ValueError('kind %r' % kind)
