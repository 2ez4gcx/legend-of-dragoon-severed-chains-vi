"""check_geom.py — QA hình học remaster (gói P2): kiểm geom_L1.npz / geom_L2.npz của một mô hình so với JSON xuất
(lược đồ tools/sc_remodel/export_tmd.py) và mọi khung của mọi hoạt cảnh. Chỉ dùng numpy (chạy được với Python hệ thống
và python.exe -I của Blender); viết độc lập với blender/remaster_core.py (không import nó).

Cách gọi (từ gốc repo, PYTHONIOENCODING=utf-8):
  python tools/sc_remaster/qa/check_geom.py <model.json> <thư mục geom> [--game game/files] [--rules R] [--levels 1,2]
                                            [--out qa_check.json]
      kiểm geom_L<n>.npz trong <thư mục geom>; exit 0 = mọi phần đạt (phần đã hạ mức được liệt kê), 1 = lỗi.
  python tools/sc_remaster/qa/check_geom.py --batch <batch.json>
      như trên cho mọi job của batch geom_job.py (json, out; đường dẫn tương đối theo thư mục batch.json; 'game', 'rules',
      'params' của lô và 'params' từng job được dùng như geom_job.py).
  python tools/sc_remaster/qa/check_geom.py --selftest
      tự kiểm không cần dữ liệu game: điểm gần nhất trên tam giác, raster, công thức f32 §3.2.2, lưới tham số, gói thấy /
      không thấy, và lỗi gieo trên một tứ giác L1 (lỗ, tam giác trùng, gai, pháp tuyến lật / ngắn) phải bị bắt đúng tiêu chí.
  Mức kiểm mặc định (--batch): 'levels' của job / lô / params / rules như geom_job.py; --levels ghi đè.

Tiêu chí (mỗi phần, ở mức đang lưu; ngưỡng trong blender/rules.json mục 'qa'):
  hausdorff   khoảng cách từ đỉnh TMD (mặt không suy biến) tới mặt remaster (tam giác nền, không váy) <= 3% đường chéo phần;
  drift       đỉnh biên gốc: |pos - đỉnh TMD| ở góc có (s,t) đúng góc TMD <= 0.5 đơn vị PS1;
  uv          sai số uv (texel) giữa công thức runtime f32 §3.2.2 từ (S,T) và uv đúng tại tham số lưới con (bội
              1/(3·2^(2L-1)): chứa lưới tứ giác 1/2^L và lưới tam giác; tứ giác có hai góc hàn trùng là tam giác trong lồng)
              <= 1e-3, hoặc <= giới hạn lượng tử u16 của SPEC (|d uv/ds| + |d uv/dt|) * 0.5/65535 khi giới hạn đó lớn hơn
              (mặt rộng ~200 texel); số góc chỉ đạt nhờ giới hạn lượng tử ghi ở 'uv_quant_limited'; (S,T) lệch lưới -> lỗi
              'st_lattice';
  winding     mọi tam giác nền / đề can / mặt sau (không váy) có diện tích có dấu âm trong không gian (s,t) của srcFace =
              cùng chiều với tam giác SC (2,1,0)/(1,2,3);
  classes     số srcFace có tam giác trong từng lớp lưới (opaque / untextured translucent / Translucency abr) = TmdObjLoader
              (L >= 1 bỏ gói không thấy: không tam giác SC nào có 3 đỉnh hàn phân biệt, kể cả tứ giác hàn hai góc chéo 1-2);
  decal       mỗi tam giác đề can trùng bit vị trí một tam giác con của mặt nền (cùng chiều); mặt sau: chiều ngược;
  schema      kiểu / dải chỉ số / hữu hạn / thứ tự tam giác theo srcFace / corner cùng srcFace trong tam giác;
  bulge       Hausdorff chiều ngược: đỉnh remaster (tam giác nền, không váy) -> lưới gốc <= hausdorff_out_rel = 6% đường chéo
              phần (bắt bề mặt phồng / gai mà chiều đỉnh TMD -> remaster không thấy);
  coverage    (L >= 1) tam giác nền không váy của mỗi gói lát kín đúng miền (s,t) của lồng (đa giác góc phân biệt; tổng
              |diện tích| = diện tích miền ± coverage_tol): bắt lỗ thủng và tam giác chồng; gói không thấy không có tam giác;
              đề can / mặt sau có đúng số tam giác như phần không váy của mặt nền;
  normals     (L >= 1) pháp tuyến góc của gói LIT dài 1 (± normal_len_tol); số gói LIT có pháp tuyến trung bình ngược tổng
              pháp tuyến TMD <= normal_flip_frac = 25% (bắt pháp tuyến bị lật cả phần; vài gói lệch là bình thường).
Mô hình: lộ khớp (đỉnh biên gốc của phần i nằm trong phần j ở lưới gốc — sâu hơn exposure_tol = 0.25 đơn vị PS1 — nhưng
không còn nằm trong lưới remaster, ở MỌI khung của mọi hoạt cảnh) = 0; IoU bóng 16 hướng ở khung 0 của cả mô hình >= 0.97
(IoU từng phần 'iou_part' chỉ để báo cáo: phần nhỏ chiếm vài điểm ảnh nên không dùng làm ngưỡng); ngân sách tam giác
L2 <= 20000, L1 <= 5500. Hàm `select_levels` (geom_job.py dùng) hạ phần lỗi L2 -> L1 -> L0 và ghi lý do.
"Nằm trong" = điểm gần nhất trên lưới (tam giác chiều SC, hướng ra ngoài), dấu theo pháp tuyến giả (trung bình pháp tuyến
các tam giác cùng khoảng cách nhỏ nhất), khoảng cách < 0.5 đường chéo phần che.
"""
import argparse
import hashlib
import json
import math
import os
import struct
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
RULES = os.path.join(ROOT, 'tools', 'sc_remaster', 'blender', 'rules.json')
GAME = os.path.join(ROOT, 'game', 'files')
F32 = np.float32
EPS = 1e-12
FIELDS = ('pos', 'corner_pos', 'corner_n', 'corner_face', 'corner_st', 'corner_near', 'corner_role', 'tri', 'tri_flag')


# ---------------------------------------------------------------- hình học
def _unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), EPS)


def closest_pairs(p, a, b, c):
    """Điểm gần nhất trên tam giác cho từng cặp (p[k], tam giác k) — Ericson 5.1.5 vector hoá. -> q (M,3)."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = np.sum(ab * ap, 1), np.sum(ac * ap, 1)
    bp = p - b
    d3, d4 = np.sum(ab * bp, 1), np.sum(ac * bp, 1)
    cp = p - c
    d5, d6 = np.sum(ab * cp, 1), np.sum(ac * cp, 1)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    den = va + vb + vc
    den = np.where(np.abs(den) < EPS, EPS, den)
    v, w = vb / den, vc / den
    q = a + ab * v[:, None] + ac * w[:, None]

    def sel(m, val):
        nonlocal q
        q = np.where(m[:, None], val, q)

    e = (d4 - d3) + (d5 - d6)
    t = (d4 - d3) / np.where(np.abs(e) < EPS, EPS, e)
    sel((va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0), b + (c - b) * t[:, None])
    e = d2 - d6
    t = d2 / np.where(np.abs(e) < EPS, EPS, e)
    sel((vb <= 0) & (d2 >= 0) & (d6 <= 0), a + ac * t[:, None])
    sel((d6 >= 0) & (d5 <= d6), c)
    e = d1 - d3
    t = d1 / np.where(np.abs(e) < EPS, EPS, e)
    sel((vc <= 0) & (d1 >= 0) & (d3 <= 0), a + ab * t[:, None])
    sel((d3 >= 0) & (d4 <= d3), b)
    sel((d1 <= 0) & (d2 <= 0), a)
    return q


class TriSet:
    """Tập tam giác (chiều SC = hướng ra ngoài) cho truy vấn điểm gần nhất có lọc hộp bao."""

    def __init__(self, P, tris):
        tris = np.asarray(tris, np.int64).reshape(-1, 3)
        P = np.asarray(P, float)
        A, B, C = P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]]
        cr = np.cross(B - A, C - A)
        keep = np.linalg.norm(cr, axis=1) > 1e-9
        self.A, self.B, self.C = A[keep], B[keep], C[keep]
        self.N = _unit(cr[keep])
        self.lo = np.minimum(np.minimum(self.A, self.B), self.C)
        self.hi = np.maximum(np.maximum(self.A, self.B), self.C)
        self.V = np.unique(np.concatenate([self.A, self.B, self.C]), axis=0) if len(self.A) else np.zeros((0, 3))
        self.n = len(self.A)
        if self.n:
            self.blo, self.bhi = self.lo.min(0), self.hi.max(0)
            self.diag = float(np.linalg.norm(self.bhi - self.blo))
        else:
            self.blo = self.bhi = np.zeros(3)
            self.diag = 0.0
        self.cen = (self.lo + self.hi) * 0.5
        self.rad = np.linalg.norm(self.hi - self.lo, axis=1) * 0.5
        self.cn = np.einsum('ij,ij->i', self.cen, self.cen)
        self.vn = np.einsum('ij,ij->i', self.V, self.V)

    def _pairs(self, p, dv):
        """Cặp (điểm, tam giác) có thể gần nhất: cầu bao (matmul, có lề) rồi hộp bao <= khoảng cách tới đỉnh gần nhất."""
        pn = np.einsum('ij,ij->i', p, p)
        d2 = np.maximum(pn[:, None] + self.cn[None] - 2.0 * (p @ self.cen.T), 0.0)
        lim = np.sqrt(dv)[:, None] * (1 + 1e-6) + self.rad[None] + 1e-6 * (1.0 + np.sqrt(pn)[:, None])
        pi, ti = np.nonzero(d2 <= lim * lim)
        pp = p[pi]
        dd = np.maximum(self.lo[ti] - pp, 0) + np.maximum(pp - self.hi[ti], 0)
        keep = np.einsum('ij,ij->i', dd, dd) <= dv[pi] * (1 + 1e-9) + 1e-9
        return pi[keep], ti[keep]

    def query(self, pts, chunk=4_000_000):
        """-> (dist (N,), side (N,): âm = phía trong theo pháp tuyến giả)."""
        pts = np.asarray(pts, float)
        n = len(pts)
        dist = np.full(n, np.inf)
        side = np.zeros(n)
        if n == 0 or self.n == 0:
            return dist, side
        # chặn trên: bình phương khoảng cách thật tới một đỉnh (đỉnh gần nhất chọn bằng matmul)
        step = max(1, chunk // max(1, len(self.V)))
        dv = np.empty(n)
        for s in range(0, n, step):
            p = pts[s:s + step]
            j = np.argmin(np.einsum('ij,ij->i', p, p)[:, None] + self.vn[None] - 2.0 * (p @ self.V.T), 1)
            dv[s:s + step] = np.sum((p - self.V[j]) ** 2, 1)
        step = max(1, chunk // max(1, self.n))
        for s in range(0, n, step):
            p = pts[s:s + step]
            pi, ti = self._pairs(p, dv[s:s + step])
            q = closest_pairs(p[pi], self.A[ti], self.B[ti], self.C[ti])
            d2 = np.sum((p[pi] - q) ** 2, 1)
            order = np.lexsort((ti, d2, pi))
            first = order[np.r_[True, pi[order][1:] != pi[order][:-1]]]
            mn = np.full(len(p), np.inf)
            qb = np.zeros((len(p), 3))
            mn[pi[first]] = d2[first]
            qb[pi[first]] = q[first]
            # pháp tuyến giả: mọi tam giác có cùng điểm gần nhất (cạnh / đỉnh chung) với cặp tốt nhất
            tie = (d2 <= mn[pi] + 1e-6 * np.maximum(mn[pi], 1.0)) & \
                  (np.sum((q - qb[pi]) ** 2, 1) <= 1e-8 * np.maximum(mn[pi], 1.0))
            nsum = np.zeros((len(p), 3))
            np.add.at(nsum, pi[tie], self.N[ti[tie]])
            dist[s:s + step] = np.sqrt(mn)
            side[s:s + step] = np.sum((p - qb) * nsum, 1) / np.maximum(np.linalg.norm(nsum, axis=1), EPS)
        return dist, side

    def inside(self, pts, max_dist, tol=0.0):
        """Nằm trong: dấu theo pháp tuyến giả < -tol và khoảng cách < max_dist."""
        d, s = self.query(pts)
        return (s < -tol) & (d < max_dist)


def raster_mask(xy, H, W, tile=None, ntiles=1, chunk=500_000):
    """Phủ pixel (tâm pixel trong tam giác, kể cả cạnh, dung sai 1e-9) cho tam giác 2D xy (T,3,2) toạ độ pixel -> bool
    (ntiles*H, W). tile (T,): ô (ảnh con H x W xếp dọc) của từng tam giác.
    Quét dòng: mỗi (tam giác, dòng tâm pixel) lấy đoạn x = giao ba nửa mặt phẳng cạnh e_k(x, y) >= -1e-9 rồi tô thẳng các
    pixel của đoạn (np.repeat) — không có vòng lặp theo pixel hay theo tam giác."""
    mask = np.zeros(ntiles * H * W, bool)
    if not len(xy):
        return mask.reshape(ntiles * H, W)
    xs, ys = xy[:, :, 0].astype(float), xy[:, :, 1].astype(float)
    toff = (np.zeros(len(xy), np.int64) if tile is None else np.asarray(tile, np.int64)) * H
    area = (xs[:, 1] - xs[:, 0]) * (ys[:, 2] - ys[:, 0]) - (xs[:, 2] - xs[:, 0]) * (ys[:, 1] - ys[:, 0])
    y0 = np.maximum(np.ceil(ys.min(1) - 0.5), 0)
    y1 = np.minimum(np.floor(ys.max(1) - 0.5), H - 1)
    vis = (np.abs(area) > 1e-12) & (xs.max(1) >= 0) & (xs.min(1) < W) & (y1 >= y0)
    sel = np.nonzero(vis)[0]
    if not len(sel):
        return mask.reshape(ntiles * H, W)
    xs, ys, area, toff = xs[sel], ys[sel], area[sel], toff[sel]
    y0 = y0[sel].astype(np.int64)
    nrow = y1[sel].astype(np.int64) - y0 + 1
    sg = np.sign(area)
    # e_k(x,y) = EA x + EB y + EC (dương = trong), đổi dấu theo chiều tam giác
    EA, EB, EC = [], [], []
    for k in range(3):
        ax, ay = xs[:, k], ys[:, k]
        bx, by = xs[:, (k + 1) % 3], ys[:, (k + 1) % 3]
        EA.append(-(by - ay) * sg)
        EB.append((bx - ax) * sg)
        EC.append(((by - ay) * ax - (bx - ax) * ay) * sg)
    EA, EB, EC = np.stack(EA, 1), np.stack(EB, 1), np.stack(EC, 1)
    cum = np.cumsum(nrow)
    start = 0
    while start < len(sel):
        stop = int(np.searchsorted(cum, cum[start - 1] + chunk if start else chunk, 'right'))
        stop = max(stop, start + 1)
        rr = np.arange(start, stop)
        nr = nrow[rr]
        ti = np.repeat(rr, nr)
        first = np.repeat(np.cumsum(nr) - nr, nr)
        row = y0[ti] + (np.arange(len(ti)) - first)
        yc = row + 0.5
        a = EA[ti]
        r = EB[ti] * yc[:, None] + EC[ti] + 1e-9          # cần a·x >= -r
        with np.errstate(divide='ignore', invalid='ignore'):
            q = -r / a
        lo = np.max(np.where(a > 0, q, -np.inf), 1)
        hi = np.min(np.where(a < 0, q, np.inf), 1)
        ok = np.all((a != 0) | (r >= 0), 1)
        xa = np.maximum(np.ceil(lo - 0.5), 0)
        xb = np.minimum(np.floor(hi - 0.5), W - 1)
        ok &= xb >= xa
        first_px = (row[ok] + toff[ti[ok]]) * W + xa[ok].astype(np.int64)
        ln = (xb[ok] - xa[ok]).astype(np.int64) + 1
        tot = int(ln.sum())
        if tot:
            mask[np.repeat(first_px - (np.cumsum(ln) - ln), ln) + np.arange(tot)] = True
        start = stop
    return mask.reshape(ntiles * H, W)


def view_dirs(n=16):
    """16 hướng: 8 góc phương vị x 2 góc ngẩng (+25°, -25°) -> ma trận quay (n,3,3) (hàng 0,1 = trục ảnh)."""
    out = []
    for el in (25.0, -25.0):
        for k in range(n // 2):
            az = math.radians(k * 360.0 / (n // 2))
            e = math.radians(el)
            d = np.array([math.sin(az) * math.cos(e), math.sin(e), math.cos(az) * math.cos(e)])
            up = np.array([0.0, -1.0, 0.0])
            x = _unit(np.cross(up, d))
            y = np.cross(d, x)
            out.append(np.stack([x, y, d]))
    return np.array(out)


def view_frames(P, views):
    """Khung 2D (tâm, cạnh) mỗi hướng nhìn bao toàn bộ điểm P (thêm lề 8%)."""
    q = np.einsum('vij,nj->vni', views[:, :2, :], P)
    lo, hi = q.min(1), q.max(1)
    span = np.maximum((hi - lo).max(1), 1e-6) * 1.08
    return (lo + hi) / 2, span


def raster_views(P, tris, views, frames, res):
    """Bóng của lưới (P, tris) ở mọi hướng nhìn, một lần raster (các hướng xếp dọc) -> bool (V, res, res)."""
    V = len(views)
    tris = np.asarray(tris, np.int64).reshape(-1, 3)
    if not len(tris) or not len(P):
        return np.zeros((V, res, res), bool)
    c, span = frames
    q = np.einsum('vij,nj->vni', views[:, :2, :], np.asarray(P, float))
    q = (q - c[:, None, :]) / span[:, None, None] * res + res / 2
    xy = q[:, tris].reshape(-1, 3, 2)
    tile = np.repeat(np.arange(V), len(tris))
    return raster_mask(xy, res, res, tile, V).reshape(V, res, res)


def iou(ma, mb):
    """IoU từng hướng nhìn của hai chồng mặt nạ (V, H, W)."""
    u = np.logical_or(ma, mb).sum((1, 2))
    i = np.logical_and(ma, mb).sum((1, 2))
    return np.where(u == 0, 1.0, i / np.maximum(u, 1)).tolist()


# ---------------------------------------------------------------- công thức runtime (SPEC §3.2.2, f32 từng phép)
def runtime_weights(S, T, quad):
    one = F32(1.0)
    s = S.astype(F32) / F32(65535.0)
    t = T.astype(F32) / F32(65535.0)
    if quad:
        return [(one - s) * (one - t), s * (one - t), (one - s) * t, s * t]
    t = np.where(s + t > one, one - s, t).astype(F32)
    return [(one - s) - t, s, t]


def runtime_interp(w, xs):
    acc = w[0] * xs[0]
    for k in range(1, len(w)):
        acc = (acc + w[k] * xs[k]).astype(F32)
    return acc


def exact_weights(s, t, quad):
    if quad:
        return np.stack([(1 - s) * (1 - t), s * (1 - t), (1 - s) * t, s * t], -1)
    return np.stack([1 - s - t, s, t], -1)


def lattice(level, quad):
    if level <= 0:
        return 1.0
    return float(2 ** level) if quad else float(3 * 2 ** (2 * level - 1))


# ---------------------------------------------------------------- hoạt cảnh (đọc độc lập)
def _rot(rx, ry, rz):
    a = [np.asarray(v, float) / 4096.0 * 2 * math.pi for v in (rx, ry, rz)]
    cx, sx, cy, sy, cz, sz = np.cos(a[0]), np.sin(a[0]), np.cos(a[1]), np.sin(a[1]), np.cos(a[2]), np.sin(a[2])
    z, o = np.zeros_like(cx), np.ones_like(cx)
    Rx = np.stack([np.stack([o, z, z], -1), np.stack([z, cx, -sx], -1), np.stack([z, sx, cx], -1)], -2)
    Ry = np.stack([np.stack([cy, z, sy], -1), np.stack([z, o, z], -1), np.stack([-sy, z, cy], -1)], -2)
    Rz = np.stack([np.stack([cz, -sz, z], -1), np.stack([sz, cz, z], -1), np.stack([z, z, o], -1)], -2)
    return Rz @ Ry @ Rx


def load_anims(doc, game):
    """Mọi khung khoá: khung 0 trong JSON + mọi file hoạt cảnh (trận: thư mục mô hình; trường: obj*33+1..+32 qua mrg)."""
    npart = len(doc['parts'])
    src = doc.get('source', {})
    model = src.get('model', '')
    d = os.path.join(game, *os.path.dirname(model).split('/')) if model else ''
    paths = []
    if model.startswith('characters/') and os.path.isdir(d):
        paths = [os.path.join(d, f) for f in sorted(os.listdir(d), key=lambda s: (len(s), s))
                 if f.isdigit() and f != os.path.basename(model)]
    elif model.startswith('SECT/') and os.path.isdir(d):
        obj = int(os.path.basename(model)) // 33
        mrg = {}
        mp = os.path.join(d, 'mrg')
        if os.path.isfile(mp):
            for line in open(mp, encoding='ascii'):
                if '=' in line:
                    v, r = line.strip().split('=', 1)
                    r = r.split(';')[0]
                    if v.isdigit() and r.strip().lstrip('-').isdigit():
                        mrg[int(v)] = int(r)
        for k in range(obj * 33 + 1, obj * 33 + 33):
            p = os.path.join(d, str(k))
            seen = set()
            r = k
            while not os.path.isfile(p) and r in mrg and r not in seen:
                seen.add(r)
                r = mrg[r]
                p = os.path.join(d, str(r))
            if os.path.isfile(p):
                paths.append(p)
    if src.get('anim'):
        paths.append(os.path.join(game, *src['anim'].split('/')))
    Rs = [np.array([p['kf0_matrix'] for p in doc['parts']], float)[None]]
    Ts = [np.array([p['kf0_trans'] for p in doc['parts']], float)[None]]
    used, seen = [], set()
    for p in paths:
        if not os.path.isfile(p):
            continue
        b = open(p, 'rb').read()
        h = hashlib.sha1(b).hexdigest()
        if h in seen or len(b) < 0x10 or struct.unpack_from('<I', b, 0)[0] == 0x11:
            continue
        n, total = struct.unpack_from('<Hh', b, 0xc)
        kf = total // 2
        if n != npart or kf <= 0 or 0x10 + kf * n * 12 > len(b):
            continue
        seen.add(h)
        a = np.frombuffer(b, '<i2', kf * n * 6, 0x10).reshape(kf, n, 6).astype(float)
        Rs.append(_rot(a[..., 0], a[..., 1], a[..., 2]))
        Ts.append(a[..., 3:6])
        used.append(os.path.relpath(p, game).replace('\\', '/'))
    return np.concatenate(Rs), np.concatenate(Ts), used


# ---------------------------------------------------------------- mô hình gốc
def sc_visible(ws):
    """Gói có ít nhất một tam giác SC ((2,1,0), tứ giác thêm (1,2,3)) gồm 3 đỉnh hàn phân biệt — gói mà retail vẽ ra diện
    tích. Tứ giác hàn hai góc chéo 1 và 2 có cả hai tam giác suy biến dù còn 3 đỉnh phân biệt -> không thấy."""
    if len(ws) == 3:
        return len(set(ws)) == 3
    return len({ws[2], ws[1], ws[0]}) == 3 or len({ws[1], ws[2], ws[3]}) == 3


class OrigPart:
    def __init__(self, part, weld=1e-3):
        V = np.array(part['verts'], float).reshape(-1, 3)
        self.V = V
        self.nv = len(V)
        keys = {}
        wid = np.zeros(self.nv, int)
        for i, k in enumerate(map(tuple, np.round(V / max(weld, 1e-9)).astype(np.int64) if len(V) else [])):
            wid[i] = keys.setdefault(k, len(keys))
        self.wid = wid
        self.faces = part['faces']
        self.cls, self.vc, self.visible, self.layer, self.base = [], [], [], [], []
        self.dom = []                      # diện tích miền tham số (s,t) mà lưới con L >= 1 phải phủ (0 = mặt bị bỏ)
        groups = {}
        for k, f in enumerate(self.faces):
            vc = 4 if f['quad'] else 3
            ws = [int(wid[v]) for v in f['vidx']]
            self.vc.append(vc)
            vis = sc_visible(ws)
            self.visible.append(vis)
            # đa giác các góc phân biệt theo vòng SC (lồng của pipeline), diện tích trong không gian (s,t)
            stc = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))
            seq, seen = [], []
            for c in f['loop']:
                if ws[c] not in seen:
                    seen.append(ws[c])
                    seq.append(stc[c])
            Pd = np.array(seq, float)
            self.dom.append(0.5 * abs(float(np.sum(Pd[:, 0] * np.roll(Pd[:, 1], -1) - np.roll(Pd[:, 0], -1) * Pd[:, 1])))
                            if vis else 0.0)
            if f['translucent'] and f['textured']:
                self.cls.append(2 + ((int(f['tpage'], 16) >> 5) & 3))
            elif f['translucent']:
                self.cls.append(1)
            else:
                self.cls.append(0)
            self.layer.append('skip')
            self.base.append(-1)
            if vis:
                groups.setdefault(tuple(sorted(set(ws))), []).append(k)
        for key in sorted(groups, key=lambda g: groups[g][0]):
            g = sorted(groups[key], key=lambda k: (self.faces[k].get('transp_frac', 0.0) if self.faces[k]['textured']
                                                   else -1.0, k))
            self.layer[g[0]] = 'base'
            g0 = np.array(self.faces[g[0]]['geo_normal'], float)
            for k in g[1:]:
                self.layer[k] = 'back' if float(np.dot(g0, self.faces[k]['geo_normal'])) < 0 else 'decal'
                self.base[k] = g[0]
        # lưới gốc (mặt nền, chiều SC) để thử che / bóng / Hausdorff
        tris = []
        for k, f in enumerate(self.faces):
            if self.layer[k] != 'base':
                continue
            v = f['vidx']
            tris.append((v[2], v[1], v[0]))
            if f['quad']:
                tris.append((v[1], v[2], v[3]))
        self.tris = np.array(tris, np.int64).reshape(-1, 3)
        self.tset = TriSet(V, self.tris)
        # cạnh biên (mặt nền, đỉnh hàn)
        cnt = {}
        for k, f in enumerate(self.faces):
            if self.layer[k] != 'base':
                continue
            ws = []
            for c in f['loop']:
                w = int(wid[f['vidx'][c]])
                if w not in ws:
                    ws.append(w)
            for a, b in zip(ws, ws[1:] + ws[:1]):
                key = (min(a, b), max(a, b))
                cnt[key] = cnt.get(key, 0) + 1
        bw = sorted({w for e, c in cnt.items() if c == 1 for w in e})
        rep = {}
        for i in range(self.nv):
            rep.setdefault(int(wid[i]), i)
        self.bnd_w = np.array(bw, int)
        self.bnd_pts = V[[rep[w] for w in bw]] if bw else np.zeros((0, 3))
        used = sorted({int(wid[v]) for k, f in enumerate(self.faces) if self.visible[k] for v in f['vidx']})
        self.used_pts = V[[rep[w] for w in used]] if used else np.zeros((0, 3))
        self.diag = float(np.linalg.norm(self.used_pts.max(0) - self.used_pts.min(0))) if len(used) else 0.0
        self._table = None

    def table(self):
        """Bảng mảng theo srcFace: quad, textured, uv (nf,4,2), vidx (nf,4), geo (nf,3), layer (0 nền/bỏ, 1 đề can,
        2 mặt sau), base (mặt nền của đề can / mặt sau, -1 nếu không)."""
        if self._table is None:
            nf = len(self.faces)
            uv = np.zeros((nf, 4, 2))
            vidx = np.zeros((nf, 4), np.int64)
            for k, f in enumerate(self.faces):
                vc = self.vc[k]
                if f['textured']:
                    uv[k, :vc] = np.array(f['uv'], float)
                vidx[k, :vc] = f['vidx']
            code = {'base': 0, 'skip': 0, 'decal': 1, 'back': 2}
            ntmd = np.zeros((nf, 3))
            lit = np.zeros(nf, bool)
            for k, f in enumerate(self.faces):
                if f['lit'] and f.get('normals') is not None:
                    lit[k] = True
                    ntmd[k] = np.sum(np.array(f['normals'], float).reshape(-1, 3), 0)
            self._table = dict(quad=np.array([bool(f['quad']) for f in self.faces], bool).reshape(nf),
                               lit=lit, ntmd=ntmd,
                               textured=np.array([bool(f['textured']) for f in self.faces], bool).reshape(nf),
                               uv=uv, vidx=vidx,
                               geo=np.array([f['geo_normal'] for f in self.faces], float).reshape(nf, 3),
                               layer=np.array([code[x] for x in self.layer], np.int64).reshape(nf),
                               base=np.array(self.base, np.int64).reshape(nf))
        return self._table


class Model:
    """Dữ liệu gốc + mọi khung + truy vấn khớp (đỉnh biên của i, khung k) -> phần che ở lưới gốc."""

    def __init__(self, doc, rules, game=GAME, R=None, T=None):
        self.doc = doc
        self.rules = rules
        self.qa = rules['qa']
        self.parts = [OrigPart(p, float(rules.get('weld_dist', 1e-3))) for p in doc['parts']]
        if R is None:
            R, T, self.anims = load_anims(doc, game)
        else:
            self.anims = []
        self.R, self.T = R, T
        self.atlas = doc.get('atlas_size', [1, 1])
        self._joint_queries()
        self.cache_part = {}
        self.cache_cover = {}
        self.cache_iou = {}
        self.cache_miou = {}

    def _joint_queries(self):
        """Mọi (i, đỉnh biên b, khung k): vị trí mô hình; với mỗi j: có nằm trong lưới gốc j."""
        R, T = self.R, self.T
        qp, qi = [], []
        for i, op in enumerate(self.parts):
            if not len(op.bnd_pts):
                continue
            P = np.einsum('kij,nj->kni', R[:, i], op.bnd_pts) + T[:, i][:, None, :]
            qp.append(P.reshape(-1, 3))
            qi.append(np.full(P.shape[0] * P.shape[1], i))
        self.qpos = np.concatenate(qp) if qp else np.zeros((0, 3))
        self.qpart = np.concatenate(qi) if qi else np.zeros(0, int)
        self.qkf = np.concatenate([np.repeat(np.arange(len(R)), len(op.bnd_pts)) for op in self.parts
                                   if len(op.bnd_pts)]) if qp else np.zeros(0, int)
        n = len(self.parts)
        self.orig_cov = np.zeros((n, len(self.qpos)), bool)
        for j, op in enumerate(self.parts):
            ts = op.tset
            if ts.n == 0:
                continue
            idx, loc = self._local_candidates(j, ts.blo, ts.bhi, 0.02 * ts.diag)
            if len(idx):
                self.orig_cov[j, idx] = ts.inside(loc, self.qa['inside_max_rel'] * op.diag, self.qa['exposure_tol'])
        self.orig_any = self.orig_cov.any(0)

    def _local_candidates(self, j, lo, hi, margin):
        m = self.qpart != j
        idx = np.nonzero(m)[0]
        if not len(idx):
            return idx, np.zeros((0, 3))
        Rk = self.R[self.qkf[idx], j]
        Tk = self.T[self.qkf[idx], j]
        loc = np.einsum('nji,nj->ni', Rk, self.qpos[idx] - Tk)
        box = np.all((loc >= lo - margin) & (loc <= hi + margin), axis=1)
        return idx[box], loc[box]

    # ---------------- kiểm từng phần
    def check_part(self, i, pm):
        key = (i, int(pm['level']), id(pm))
        if key in self.cache_part:
            return self.cache_part[key]
        r = part_metrics(self, i, pm)
        self.cache_part[key] = r
        return r

    def cover(self, j, pm):
        """Mảng bool (Q,) cho truy vấn khớp: điểm nằm trong lưới remaster của j (tam giác nền, không váy)."""
        key = (j, id(pm))
        if key in self.cache_cover:
            return self.cache_cover[key]
        out = np.zeros(len(self.qpos), bool)
        sel = (pm['corner_role'][pm['tri'][:, 0]] == 0) & ((pm['tri_flag'] & 1) == 0) if len(pm['tri']) else \
            np.zeros(0, bool)
        ts = TriSet(pm['pos'][pm['corner_pos']].astype(float), pm['tri'][sel])
        if ts.n:
            need = np.nonzero(self.orig_any)[0]
            idx, loc = self._local_candidates(j, ts.blo, ts.bhi, 0.02 * max(ts.diag, EPS))
            keep = np.isin(idx, need)
            idx, loc = idx[keep], loc[keep]
            if len(idx):
                out[idx] = ts.inside(loc, self.qa['inside_max_rel'] * max(self.parts[j].diag, EPS))
        self.cache_cover[key] = out
        return out

    def joint_exposure(self, pms):
        rem_any = np.zeros(len(self.qpos), bool)
        covs = []
        for j, pm in enumerate(pms):
            c = self.cover(j, pm) if pm['mode'] == 1 else self.orig_cov[j]
            covs.append(c)
            rem_any |= c
        newly = self.orig_any & ~rem_any
        blame = {}
        for j, c in enumerate(covs):
            b = int((newly & self.orig_cov[j] & ~c).sum())
            if b:
                blame[j] = b
        per_part = {}
        for i in np.unique(self.qpart[newly]):
            per_part[int(i)] = int((self.qpart[newly] == i).sum())
        return dict(newly_exposed=int(newly.sum()), covered_orig=int(self.orig_any.sum()), blame=blame,
                    exposed_parts=per_part, keyframes=int(len(self.R)))

    # ---------------- bóng 16 hướng ở khung 0 (khung ảnh cố định theo mô hình gốc)
    def _setup_views(self):
        if hasattr(self, 'views'):
            return
        self.views = view_dirs(int(self.qa['iou_views']))
        self.res = int(self.qa['iou_res'])
        R0, T0 = self.R[0], self.T[0]
        self.posed0 = [op.V @ R0[i].T + T0[i] for i, op in enumerate(self.parts)]
        allp = [p for p, op in zip(self.posed0, self.parts) if op.tset.n]
        self.frames = view_frames(np.concatenate(allp) if allp else np.zeros((1, 3)), self.views)
        self.orig_masks = [raster_views(P, op.tris, self.views, self.frames, self.res)
                           for P, op in zip(self.posed0, self.parts)]
        self.orig_model = np.zeros((len(self.views), self.res, self.res), bool)
        for m in self.orig_masks:
            self.orig_model |= m

    def masks(self, i, pm):
        """(mặt nạ phần không váy, mặt nạ váy) của ứng viên ở khung 0, khung ảnh mô hình; mode 0 -> bóng gốc."""
        self._setup_views()
        key = (i, id(pm))
        if key in self.cache_iou:
            return self.cache_iou[key]
        if pm['mode'] != 1 or not len(pm['tri']):
            r = (self.orig_masks[i], None)
        else:
            P = pm['pos'][pm['corner_pos']].astype(float) @ self.R[0, i].T + self.T[0, i]
            base = pm['corner_role'][pm['tri'][:, 0]] == 0
            sk = (pm['tri_flag'] & 1) == 1
            r = (raster_views(P, pm['tri'][base & ~sk], self.views, self.frames, self.res),
                 raster_views(P, pm['tri'][base & sk], self.views, self.frames, self.res) if (base & sk).any() else None)
        self.cache_iou[key] = r
        return r

    def part_iou(self, i, pm):
        """IoU nhỏ nhất (16 hướng) của bóng phần (không váy) so với bóng gốc của phần, trong khung ảnh mô hình."""
        m, _ = self.masks(i, pm)
        return float(min(iou(m, self.orig_masks[i])))

    def part_diff(self, i, pm):
        """Số pixel khác (XOR) giữa bóng phần remaster và bóng gốc — chọn phần gây giảm IoU mô hình."""
        m, _ = self.masks(i, pm)
        return int(np.logical_xor(m, self.orig_masks[i]).sum())

    def model_iou(self, pms):
        key = tuple(id(p) for p in pms)
        if key in self.cache_miou:
            return self.cache_miou[key]
        self._setup_views()
        rem = np.zeros_like(self.orig_model)
        for i, pm in enumerate(pms):
            m, sk = self.masks(i, pm)
            rem |= m
            if sk is not None:
                rem |= sk
        v = iou(rem, self.orig_model)
        r = dict(min=round(float(min(v)), 4), mean=round(float(np.mean(v)), 4))
        self.cache_miou[key] = r
        return r


def part_metrics(model, i, pm):
    """Các tiêu chí của một phần ở mức pm['level'] -> dict(metrics, fail=[...])."""
    qa = model.qa
    op = model.parts[i]
    faces = op.faces
    level = int(pm['level'])
    out = dict(level=level, mode=int(pm['mode']), tris=int(len(pm['tri'])), fail=[])
    if pm['mode'] == 0:
        return out
    fail = out['fail']
    pos, cpos, cface, cst = pm['pos'], pm['corner_pos'], pm['corner_face'], pm['corner_st']
    tri, flag, role = pm['tri'], pm['tri_flag'], pm['corner_role']
    nf = len(faces)
    # schema
    bad = []
    if not np.all(np.isfinite(pos)) or not np.all(np.isfinite(pm['corner_n'])):
        bad.append('nan')
    if len(cpos) and cpos.max() >= len(pos):
        bad.append('corner_pos')
    if len(cface) and cface.max() >= nf:
        bad.append('corner_face')
    if len(tri) and tri.max() >= len(cpos):
        bad.append('tri')
    if len(pm['corner_near']) and pm['corner_near'].max() >= op.nv:
        bad.append('near')
    if len(role) and role.max() > 2:
        bad.append('role')
    if len(tri):
        tf = cface[tri]
        if not np.all(tf == tf[:, :1]):
            bad.append('tri_mixed_srcface')
        if np.any(np.diff(tf[:, 0].astype(np.int64)) < 0):
            bad.append('tri_order')
    if bad:
        fail.append('schema:' + ','.join(bad))
        out['schema'] = bad
        return out
    P = pos[cpos].astype(float)
    S = cst[:, 0].astype(np.int64)
    T = cst[:, 1].astype(np.int64)
    ft = op.table()
    cf = cface.astype(np.int64)
    quad = ft['quad'][cf]
    # uv + lưới tham số. Lưới chung (bội 1/(3·2^(2L-1)) chứa cả lưới tứ giác 1/2^L): tứ giác có hai góc trùng vị trí thành
    # tam giác trong lồng nên tham số con nằm trên lưới tam giác.
    Ls = lattice(level, False) if level else 1.0
    s = S / 65535.0
    t = T / 65535.0
    sl = np.round(s * Ls) / Ls
    tl = np.round(t * Ls) / Ls
    off = (np.abs(s - sl) > 0.6 / 65535) | (np.abs(t - tl) > 0.6 / 65535) | (~quad & (sl + tl > 1 + 1e-9))
    off_lattice = int(off.sum())
    tex = ft['textured'][cf]
    uv_err = 0.0
    uv_quant = 0
    uv_bad = False
    if tex.any():
        c = np.nonzero(tex)[0]
        uv = ft['uv'][cf[c]]                                   # (n, 4, 2) float64 (tam giác: hàng 3 = 0)
        qd = quad[c]
        wq = runtime_weights(S[c], T[c], True)
        wt = runtime_weights(S[c], T[c], False) + [np.zeros(len(c), F32)]
        w = [np.where(qd, a, b).astype(F32) for a, b in zip(wq, wt)]
        uv32 = uv.astype(F32)
        # cùng thứ tự phép f32 như runtime; tam giác cộng thêm 0·0 = không đổi giá trị
        ur = runtime_interp(w, [uv32[:, k, 0] for k in range(4)]).astype(float)
        vr = runtime_interp(w, [uv32[:, k, 1] for k in range(4)]).astype(float)
        slc, tlc = sl[c], tl[c]
        we = np.where(qd[:, None], exact_weights(slc, tlc, True),
                      np.concatenate([exact_weights(slc, tlc, False), np.zeros((len(c), 1))], 1))
        ue = np.einsum('nk,nk->n', we, uv[:, :, 0])
        ve = np.einsum('nk,nk->n', we, uv[:, :, 1])
        e = np.maximum(np.abs(ur - ue), np.abs(vr - ve))
        # giới hạn lượng tử u16 của SPEC (|S/65535 - s| <= 0.5/65535): (|d/ds| + |d/dt|) * 0.5/65535 + sai số f32
        dsq = (1 - tlc)[:, None] * (uv[:, 1] - uv[:, 0]) + tlc[:, None] * (uv[:, 3] - uv[:, 2])
        dtq = (1 - slc)[:, None] * (uv[:, 2] - uv[:, 0]) + slc[:, None] * (uv[:, 3] - uv[:, 1])
        ds = np.where(qd[:, None], dsq, uv[:, 1] - uv[:, 0])
        dt = np.where(qd[:, None], dtq, uv[:, 2] - uv[:, 0])
        qb = (np.abs(ds) + np.abs(dt)).max(1) * (0.5 / 65535) + 2e-5
        lim = np.maximum(qa['uv_err_texel'], qb)
        oc = off[c]
        bad = (e > lim) & ~oc
        uv_quant = int(((e > qa['uv_err_texel']) & ~bad & ~oc).sum())
        if (~oc).any():
            uv_err = float(e[~oc].max())
        uv_bad = bool(bad.any())
    out['uv_err_texel'] = uv_err
    out['uv_quant_limited'] = uv_quant
    out['st_off_lattice'] = off_lattice
    if off_lattice:
        fail.append('st_lattice')
    if uv_bad:
        fail.append('uv')
    # winding trong không gian (s,t)
    nonskirt = (flag & 1) == 0
    tt = tri[nonskirt]
    s3 = (S[tt] / 65535.0)
    t3 = (T[tt] / 65535.0)
    area = (s3[:, 1] - s3[:, 0]) * (t3[:, 2] - t3[:, 0]) - (s3[:, 2] - s3[:, 0]) * (t3[:, 1] - t3[:, 0])
    wrong = int((area > 1e-12).sum())
    zero = int((np.abs(area) <= 1e-12).sum())
    out['winding_wrong'] = wrong
    out['winding_zero_area'] = zero
    if wrong:
        fail.append('winding')
    # chiều hình học so với mặt gốc (chỉ báo cáo)
    if len(tt):
        A, B, C = P[tt[:, 0]], P[tt[:, 1]], P[tt[:, 2]]
        nrm = np.cross(B - A, C - A)
        g = ft['geo'][cf[tt[:, 0]]]
        out['geom_facing_opposite'] = int((np.sum(nrm * g, 1) < 0).sum())
    # lớp lưới
    exp_cls, got_cls = {}, {}
    for k, f in enumerate(faces):
        if level >= 1 and not op.visible[k]:
            continue
        exp_cls[op.cls[k]] = exp_cls.get(op.cls[k], 0) + 1
    for k in np.unique(cface[tri[:, 0]]) if len(tri) else []:
        got_cls[op.cls[int(k)]] = got_cls.get(op.cls[int(k)], 0) + 1
    out['classes'] = dict(expected={str(k): v for k, v in sorted(exp_cls.items())},
                          got={str(k): v for k, v in sorted(got_cls.items())})
    if exp_cls != got_cls:
        fail.append('classes')
    # đề can / mặt sau dùng lại tam giác con của mặt nền (trùng bit vị trí): đỉnh = bộ 3 u32 bit f32 của vị trí, tam giác =
    # bộ 3 mã đỉnh xoay về cách viết nhỏ nhất (mặt sau: đảo chiều trước), thuộc tập tam giác nền của mặt nền.
    tf = cface[tri[:, 0]].astype(np.int64) if len(tri) else np.zeros(0, np.int64)
    layer = ft['layer'][tf]
    dec = layer >= 1
    dec_n = int(dec.sum())
    dec_bad = 0
    if dec_n:
        Pi = np.ascontiguousarray(P.astype(np.float32)).view(np.uint32).reshape(-1, 3)
        _, vid = np.unique(Pi, axis=0, return_inverse=True)
        vid = vid.reshape(-1).astype(np.int64)
        nvid = int(vid.max()) + 1
        tv = vid[tri.astype(np.int64)]
        isb = (role[tri[:, 0]] == 0) & (layer == 0)
        td = tv[dec]
        back = layer[dec] == 2
        td[back] = td[back][:, [0, 2, 1]]

        def canon(x):
            r = [x[:, (0 + k) % 3] * nvid * nvid + x[:, (1 + k) % 3] * nvid + x[:, (2 + k) % 3] for k in range(3)]
            return np.minimum(np.minimum(r[0], r[1]), r[2])
        if nvid ** 3 * (len(faces) + 1) < (1 << 62):
            kb = tf[isb] * nvid ** 3 + canon(tv[isb])
            kd = ft['base'][tf[dec]] * nvid ** 3 + canon(td)
            dec_bad = int((~np.isin(kd, kb)).sum())
        else:
            sb = set(zip(tf[isb].tolist(), canon(tv[isb]).tolist()))
            dec_bad = sum(1 for k in zip(ft['base'][tf[dec]].tolist(), canon(td).tolist()) if k not in sb)
    out['decal_tris'] = dec_n
    out['decal_mismatch'] = dec_bad
    if dec_bad:
        fail.append('decal')
    # Hausdorff một phía: đỉnh TMD -> mặt remaster (tam giác nền, không váy)
    selb = nonskirt & (role[tri[:, 0]] == 0)
    ts = TriSet(P, tri[selb])
    if len(op.used_pts) and ts.n:
        d, _ = ts.query(op.used_pts)
        h = float(d.max() / max(op.diag, EPS))
    else:
        h = 0.0
    out['hausdorff_rel'] = round(h, 5)
    if h > qa['hausdorff_rel']:
        fail.append('hausdorff')
    # trôi biên: góc đúng góc TMD tại đỉnh biên
    drift = 0.0
    if len(op.bnd_w):
        main_c = np.zeros(len(cpos), bool)
        main_c[tri[nonskirt].reshape(-1)] = True
        kc = np.full(len(cpos), -1, np.int64)
        kc[(S == 0) & (T == 0)] = 0
        kc[(S == 65535) & (T == 0)] = 1
        kc[(S == 0) & (T == 65535)] = 2
        kc[(S == 65535) & (T == 65535) & quad] = 3
        c = np.nonzero(main_c & (kc >= 0))[0]
        if len(c):
            v = ft['vidx'][cf[c], kc[c]]
            isbnd = np.isin(op.wid[v], op.bnd_w)
            if isbnd.any():
                drift = float(np.linalg.norm(P[c[isbnd]] - op.V[v[isbnd]], axis=1).max())
    out['boundary_drift'] = round(drift, 4)
    if drift > qa['boundary_drift']:
        fail.append('drift')
    # Hausdorff chiều ngược (phồng / gai): đỉnh remaster (tam giác nền, không váy) -> lưới gốc của phần. Hausdorff một phía
    # ở trên không thấy bề mặt bị đẩy ra ngoài (vd. sửa khớp dời lồng 2 đơn vị trên phần đường chéo 16).
    bulge = 0.0
    if op.tset.n and selb.any():
        vs = np.unique(cpos[tri[selb].reshape(-1)])
        d, _ = op.tset.query(pos[vs].astype(float))
        bulge = float(d.max() / max(op.diag, EPS))
    out['hausdorff_out_rel'] = round(bulge, 5)
    if bulge > qa.get('hausdorff_out_rel', 0.06):
        fail.append('bulge')
    if level >= 1:
        # phủ miền tham số: tam giác nền không váy của mỗi gói phải lát kín đúng miền (s,t) của lồng (đa giác các góc phân
        # biệt) — không lỗ, không chồng; gói không thấy (tam giác SC suy biến) không có tam giác; đề can / mặt sau có đúng
        # số tam giác như phần không váy của mặt nền.
        fk = cf[tt[:, 0]] if len(tt) else np.zeros(0, np.int64)
        ntri = np.bincount(fk, minlength=nf)
        cov = np.bincount(fk, weights=0.5 * np.abs(area), minlength=nf)
        dom = np.array(op.dom, float)
        lay = ft['layer']
        isbase = (lay == 0) & np.array(op.visible, bool) & (np.array(op.layer) == 'base')
        bad_cov = isbase & (np.abs(cov - dom) > qa.get('coverage_tol', 1e-4))
        invis = ~np.array(op.visible, bool) & (ntri > 0)
        dl = np.nonzero(lay >= 1)[0]
        bad_dec = dl[ntri[dl] != ntri[ft['base'][dl]]] if len(dl) else dl
        out['coverage_bad'] = int(bad_cov.sum()) + int(invis.sum()) + int(len(bad_dec))
        out['coverage_err'] = round(float(np.abs(cov - dom)[isbase].max()), 6) if isbase.any() else 0.0
        if out['coverage_bad']:
            fail.append('coverage')
        # pháp tuyến (hình học, L >= 1): mặt LIT dùng pháp tuyến -> độ dài 1; chiều trung bình mỗi gói LIT so với tổng
        # pháp tuyến TMD — ngược ở quá normal_flip_frac số gói = pháp tuyến bị lật.
        litf = ft['lit']
        usedc = np.zeros(len(cpos), bool)
        if len(tri):
            usedc[tri.reshape(-1)] = True
        cl = usedc & litf[cf]
        nrm = pm['corner_n'].astype(float)
        nlen = np.linalg.norm(nrm[cl], axis=1) if cl.any() else np.zeros(0)
        out['normal_len_err'] = round(float(np.abs(nlen - 1.0).max()), 6) if len(nlen) else 0.0
        acc = np.zeros((nf, 3))
        np.add.at(acc, cf[cl], nrm[cl])
        hasf = np.bincount(cf[cl], minlength=nf) > 0
        opp = hasf & (np.sum(acc * ft['ntmd'], 1) < 0)
        frac = float(opp.sum() / max(int(hasf.sum()), 1))
        out['normal_flip_frac'] = round(frac, 4)
        if out['normal_len_err'] > qa.get('normal_len_tol', 1e-3) or frac > qa.get('normal_flip_frac', 0.25):
            fail.append('normals')
    return out


# ---------------------------------------------------------------- chọn mức + hạ mức
def select_levels(model, cands, target):
    """cands: [{level: partmesh}] -> (chọn [partmesh], nhật ký). Hạ L2 -> L1 -> L0 cho phần lỗi tiêu chí riêng, phần làm
    lộ khớp (phần che), phần IoU thấp nhất khi IoU mô hình < ngưỡng, phần nhiều tam giác nhất khi vượt ngân sách."""
    qa = model.qa
    n = len(cands)
    lv = [max(l for l in c if l <= target) for c in cands]
    log = []

    def down(i, why):
        lower = [l for l in cands[i] if l < lv[i]]
        if not lower:
            return False
        nl = max(lower)
        log.append(dict(part=i, frm=lv[i], to=nl, reason=why))
        lv[i] = nl
        return True

    budget = int(qa['tri_budget'].get(str(target), 1 << 30))
    for _ in range(4 * n + 8):
        pms = [cands[i][lv[i]] for i in range(n)]
        changed = False
        for i in range(n):
            r = model.check_part(i, pms[i])
            if r['fail'] and lv[i] > 0:
                changed |= down(i, ','.join(r['fail']))
        if changed:
            continue
        je = model.joint_exposure(pms)
        if je['newly_exposed']:
            for j in sorted(je['blame'], key=lambda j: -je['blame'][j]):
                if lv[j] > 0 and down(j, 'lo_khop:%d' % je['blame'][j]):
                    changed = True
                    break
            if changed:
                continue
        tris = sum(len(p['tri']) for p in pms)
        if tris > budget:
            order = sorted([i for i in range(n) if lv[i] > 0], key=lambda i: -len(pms[i]['tri']))
            if order and down(order[0], 'ngan_sach:%d>%d' % (tris, budget)):
                continue
        mi = model.model_iou(pms)
        if mi['min'] < qa['iou_min']:
            worst = sorted([i for i in range(n) if lv[i] > 0], key=lambda i: -model.part_diff(i, pms[i]))
            if worst and down(worst[0], 'iou_mo_hinh:%.4f' % mi['min']):
                continue
        break
    pms = [cands[i][lv[i]] for i in range(n)]
    return pms, log


def model_report(model, pms, target):
    qa = model.qa
    parts = [dict(model.check_part(i, pm), iou_part=round(model.part_iou(i, pm), 4)) for i, pm in enumerate(pms)]
    je = model.joint_exposure(pms)
    mi = model.model_iou(pms)
    tris = sum(len(p['tri']) for p in pms)
    budget = int(qa['tri_budget'].get(str(target), 1 << 30))
    fails = []
    for i, r in enumerate(parts):
        for f in r['fail']:
            fails.append('phan %d: %s' % (i, f))
    if je['newly_exposed']:
        fails.append('lo khop: %d (phan che %s)' % (je['newly_exposed'], je['blame']))
    if mi['min'] < qa['iou_min']:
        fails.append('iou mo hinh %.4f < %.2f' % (mi['min'], qa['iou_min']))
    if tris > budget:
        fails.append('ngan sach tam giac %d > %d' % (tris, budget))
    return dict(level=target, tris=tris, budget=budget, joint=je, iou=mi, parts=parts, fail=fails,
                part_levels=[int(p['level']) for p in pms])


# ---------------------------------------------------------------- đọc npz + CLI
def load_npz(path):
    z = np.load(path, allow_pickle=False)
    n = int(z['partCount'][0])
    pms = []
    for i in range(n):
        pm = {k: z['p%03d_%s' % (i, k)] for k in FIELDS}
        pm['mode'] = int(z['p%03d_mode' % i][0])
        pm['level'] = int(z['partLevel'][i])
        pms.append(pm)
    return dict(level=int(z['level'][0]), parts=pms, srcFaceCount=z['srcFaceCount'], mode=z['mode'])


def check_files(doc, geom_dir, rules, game, levels):
    model = Model(doc, rules, game)
    res = dict(model=doc.get('name'), anims=model.anims, keyframes=int(len(model.R)), levels={}, fail=[])
    for L in levels:
        p = os.path.join(geom_dir, 'geom_L%d.npz' % L)
        if not os.path.isfile(p):
            res['fail'].append('thieu %s' % os.path.basename(p))
            continue
        d = load_npz(p)
        if len(d['parts']) != len(doc['parts']):
            res['fail'].append('L%d: so phan %d != %d' % (L, len(d['parts']), len(doc['parts'])))
            continue
        sfc = [len(p['faces']) for p in doc['parts']]
        if list(d['srcFaceCount']) != sfc:
            res['fail'].append('L%d: srcFaceCount sai' % L)
        r = model_report(model, d['parts'], L)
        if any(pl > L for pl in r['part_levels']):
            r['fail'].append('muc phan > muc file')
        res['levels'][L] = r
        res['fail'] += ['L%d %s' % (L, f) for f in r['fail']]
    return res


def _rules(path):
    with open(path or RULES, encoding='utf-8') as f:
        return json.load(f)


def _with_params(rules, *params):
    """rules + ghi đè 'params' của lô / job (dict lồng nhau, gộp như geom_job.py) — bản sao, không sửa rules."""
    out = json.loads(json.dumps(rules))

    def merge(dst, src):
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                merge(dst[k], v)
            else:
                dst[k] = v
    for p in params:
        if p:
            merge(out, json.loads(json.dumps(p)))
    return out


def selftest():
    errs = []
    # điểm gần nhất
    rng = np.random.default_rng(3)
    a, b, c = rng.normal(size=(3, 50, 3))
    p = rng.normal(size=(50, 3)) * 2
    q = closest_pairs(p, a, b, c)
    for k in range(50):
        best = np.inf
        for u in np.linspace(0, 1, 81):
            for v in np.linspace(0, 1 - u, max(2, int(81 * (1 - u)))):
                x = a[k] + u * (b[k] - a[k]) + v * (c[k] - a[k])
                best = min(best, float(np.linalg.norm(p[k] - x)))
        if np.linalg.norm(p[k] - q[k]) > best + 1e-9:
            errs.append('closest %d' % k)
    # trong / ngoài hộp lập phương
    Pc = np.array([[x, y, z] for x in (0, 1) for y in (0, 1) for z in (0, 1)], float)
    cube = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    tris = []
    for f in cube:
        tris += [(f[0], f[1], f[2]), (f[0], f[2], f[3])]
    tris = np.array(tris)
    cen = Pc.mean(0)
    nrm = np.cross(Pc[tris[:, 1]] - Pc[tris[:, 0]], Pc[tris[:, 2]] - Pc[tris[:, 0]])
    if np.any(np.sum(nrm * (Pc[tris[:, 0]] - cen), 1) < 0):
        tris = tris[:, ::-1]
    ts = TriSet(Pc, tris)
    ins = ts.inside(np.array([[0.5, 0.5, 0.5], [1.5, 0.5, 0.5], [0.99, 0.99, 0.99], [1.01, 1.01, 0.5]]), 10)
    if list(ins) != [True, False, True, False]:
        errs.append('inside %s' % ins)
    # raster: hình vuông 10x10 px
    sq = np.array([[[2, 2], [12, 2], [12, 12]], [[2, 2], [12, 12], [2, 12]]], float)
    m = raster_mask(sq, 16, 16)
    if int(m.sum()) != 100:
        errs.append('raster %d' % m.sum())
    # công thức f32: góc đúng góc TMD
    for quad in (False, True):
        S = np.array([0, 65535, 0, 65535][:4 if quad else 3])
        T = np.array([0, 0, 65535, 65535][:4 if quad else 3])
        w = runtime_weights(S, T, quad)
        Wm = np.stack(w, -1)
        if not np.array_equal(Wm, np.eye(len(S), dtype=F32)):
            errs.append('weights %s' % quad)
    if lattice(2, False) != 24.0 or lattice(1, True) != 2.0:
        errs.append('lattice')
    # gói thấy / không thấy: tứ giác hàn góc chéo 1-2 -> hai tam giác SC suy biến
    if [sc_visible(w) for w in ([0, 1, 2], [0, 1, 1, 2], [0, 1, 2, 0], [0, 1, 2, 1], [0, 0, 1, 1])] != \
            [True, False, True, True, False]:
        errs.append('sc_visible')
    # tiêu chí phần trên một tứ giác phẳng chia L1 (lưới 3x3 tham số), rồi các lỗi gieo: lỗ, tam giác trùng, gai, pháp
    # tuyến lật / ngắn -> phải bị bắt đúng tiêu chí
    Vq = [[0, 0, 0], [10, 0, 0], [0, 10, 0], [10, 10, 0]]
    fq = dict(prim=0, vidx=[0, 1, 2, 3], loop=[0, 2, 3, 1], quad=True, textured=False, translucent=False, lit=True,
              normals=[[0, 0, -1]] * 4, geo_normal=[0, 0, -100], colours=[[9, 9, 9]] * 4)
    grid = [(s, t) for t in (0.0, 0.5, 1.0) for s in (0.0, 0.5, 1.0)]
    trs = []
    for j in range(2):
        for i in range(2):
            c0, c1, c2, c3 = j * 3 + i, j * 3 + i + 1, (j + 1) * 3 + i, (j + 1) * 3 + i + 1
            trs += [(c2, c1, c0), (c1, c2, c3)]
    pm0 = dict(level=1, mode=1, pos=np.array([[10 * s, 10 * t, 0] for s, t in grid], np.float32),
               corner_pos=np.arange(9, dtype=np.uint32), corner_n=np.tile(np.float32([0, 0, -1]), (9, 1)),
               corner_face=np.zeros(9, np.uint32),
               corner_st=np.array([[round(s * 65535), round(t * 65535)] for s, t in grid], np.uint16),
               corner_near=np.zeros(9, np.uint16), corner_role=np.zeros(9, np.uint8),
               tri=np.array(trs, np.uint32), tri_flag=np.zeros(len(trs), np.uint8))

    class _M:
        pass
    mq = _M()
    mq.qa = json.load(open(RULES, encoding='utf-8'))['qa'] if os.path.isfile(RULES) else \
        dict(hausdorff_rel=0.03, boundary_drift=0.5, uv_err_texel=1e-3)
    mq.parts = [OrigPart(dict(verts=Vq, faces=[fq]))]

    def crit(**kw):
        pm = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in pm0.items()}
        if 'drop' in kw:
            pm['tri'] = np.delete(pm['tri'], kw['drop'], 0)
            pm['tri_flag'] = np.delete(pm['tri_flag'], kw['drop'], 0)
        if 'dup' in kw:
            pm['tri'] = np.concatenate([pm['tri'], pm['tri'][:1]])
            pm['tri_flag'] = np.concatenate([pm['tri_flag'], pm['tri_flag'][:1]])
        if 'lift' in kw:
            pm['pos'][4, 2] = kw['lift']
        if 'nscale' in kw:
            pm['corner_n'] = (pm['corner_n'] * kw['nscale']).astype(np.float32)
        return part_metrics(mq, 0, pm)['fail']
    for kw, want in ((dict(), []), (dict(drop=[3]), ['coverage']), (dict(dup=1), ['coverage']),
                     (dict(lift=-3.0), ['bulge']), (dict(nscale=-1.0), ['normals']), (dict(nscale=0.5), ['normals'])):
        got = crit(**kw)
        if got != want:
            errs.append('tieu chi %s: %s != %s' % (kw, got, want))
    if 'PIL' in sys.modules:
        errs.append('PIL da duoc import')
    print('selftest:', 'DAT' if not errs else 'LOI %s' % errs)
    return 0 if not errs else 1


def main():
    ap = argparse.ArgumentParser(description='QA hinh hoc remaster (P2)')
    ap.add_argument('json', nargs='?')
    ap.add_argument('geom', nargs='?')
    ap.add_argument('--game', default=GAME)
    ap.add_argument('--rules')
    ap.add_argument('--levels', help='vd. 1,2; mac dinh: levels cua job / lo / params / rules nhu geom_job.py, roi 1,2')
    ap.add_argument('--out')
    ap.add_argument('--batch')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    jobs = []
    game = a.game
    rules_path = a.rules
    bparams = {}
    blevels = None
    if a.batch:
        # như geom_job.py: đường dẫn tương đối tính theo thư mục chứa batch.json; 'game' / 'rules' của lô nếu không ghi đè
        base = os.path.dirname(os.path.abspath(a.batch))

        def ab(p):
            return p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))
        b = json.load(open(a.batch, encoding='utf-8'))
        for j in b['jobs']:
            jobs.append((ab(j['json']), ab(j['out']), j.get('name'), j.get('params') or {}, j.get('levels')))
        if b.get('game') and a.game == GAME:
            game = ab(b['game'])
        if b.get('rules') and not a.rules:
            rules_path = ab(b['rules'])
        bparams = b.get('params') or {}
        blevels = b.get('levels')
    elif a.json and a.geom:
        jobs.append((a.json, a.geom, None, {}, None))
    else:
        ap.error('can <model.json> <geom_dir> hoac --batch')
    rules = _rules(rules_path)
    allres = []
    nfail = 0
    for js, gd, nm, jp, jl in jobs:
        t = time.perf_counter()
        doc = json.load(open(js, encoding='utf-8'))
        doc.setdefault('name', nm or os.path.splitext(os.path.basename(js))[0])
        jr = _with_params(rules, bparams, jp)
        # mức cần kiểm: --levels, nếu không thì như geom_job.py (job -> lô -> params/rules -> [1, 2])
        if a.levels:
            levels = [int(x) for x in a.levels.split(',') if x]
        else:
            levels = [int(x) for x in (jl or blevels or jr.get('levels') or [1, 2]) if int(x) > 0]
        r = check_files(doc, gd, jr, game, levels)
        r['seconds'] = round(time.perf_counter() - t, 2)
        allres.append(r)
        fb = {}
        for L, lr in r['levels'].items():
            fb[L] = sum(1 for x in lr['part_levels'] if x < L)
        status = 'DAT' if not r['fail'] else 'LOI'
        print('%s %s: L1 %s tam giac, L2 %s tam giac, phan ha muc %s, lo khop %s, IoU %s (%.1fs)' % (
            status, r['model'], r['levels'].get(1, {}).get('tris'), r['levels'].get(2, {}).get('tris'), fb,
            {L: lr['joint']['newly_exposed'] for L, lr in r['levels'].items()},
            {L: lr['iou']['min'] for L, lr in r['levels'].items()}, r['seconds']))
        for f in r['fail'][:20]:
            print('   ', f)
        nfail += bool(r['fail'])
    if a.out:
        with open(a.out, 'w', encoding='utf-8') as f:
            json.dump(allres, f, ensure_ascii=False, indent=1, default=lambda o: o.tolist() if hasattr(o, 'tolist') else str(o))
    print('TONG: %d mo hinh, %d loi' % (len(jobs), nfail))
    return 1 if nfail else 0


if __name__ == '__main__':
    sys.exit(main())
