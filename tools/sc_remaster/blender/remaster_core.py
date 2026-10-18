"""remaster_core.py — pipeline hình học v2 (gói P2, route B "Mô hình HD"): dựng lưới remaster L0 / L1 / L2 cho từng
phần TMD của một mô hình nhân vật, theo đặc tả LRM 1 (tools/sc_remaster/SPEC.md §3.2, §3.5.2, §3.8, §4.3).

Không có argparse, biến toàn cục hay render ở cấp module; hàm phụ thuộc Blender (bpy) chỉ import bpy bên trong hàm, nên
phần numpy (đọc JSON, hàn đỉnh, phân lớp đề can / mặt sau, crease, kế hoạch khớp, phát lưới, ghi npz) chạy được cả với
Python hệ thống. geom_job.py gọi `process_model` bên trong `blender -b`.

Đầu vào: JSON theo lược đồ tools/sc_remodel/export_tmd.py (toạ độ PS1 thô, TMD-local: x phải, y xuống, z vào; mỗi phần:
'verts', 'faces' với 'prim' = chỉ số gói đã làm phẳng (srcFace), 'vidx' (thứ tự góc TMD), 'loop' (vòng đa giác theo chiều
SC: tam giác (2,1,0), tứ giác [0,2,3,1]), 'normals' (pháp tuyến TMD từng góc, đã làm tròn 6 số lẻ), 'uv' (texel atlas từng
góc TMD), 'translucent', 'textured', 'lit', 'tpage', 'transp_frac', 'geo_normal', 'kf0_matrix', 'kf0_trans').
Hoạt cảnh (mọi khung của mọi file hoạt cảnh của mô hình) đọc thẳng từ game/files (chỉ đọc) — xem `find_anims`.

Pipeline mỗi phần (đơn vị TMD-local thô: không M, không SCALE, không tư thế):
  1. Hàn đỉnh trùng (<= weld_dist), giữ bản đồ TMD -> đỉnh hàn (`wid`) và đỉnh hàn -> TMD đại diện (`rep`).
     Tứ giác có đỉnh lặp -> tam giác; mặt còn < 3 đỉnh phân biệt, hoặc không có tam giác SC nào không suy biến (tứ giác
     hàn hai góc chéo 1-2: retail không vẽ gì), bị bỏ khỏi lồng (chỉ còn ở L0).
  2. Lớp: các mặt cùng TẬP đỉnh hàn thành nhóm; mặt nền 'base' = ít texel trong suốt nhất (mặt không texture trước);
     cùng chiều -> 'decal' (mắt/miệng), ngược chiều -> 'back' (mặt sau tấm hai mặt). Chỉ mặt nền vào lồng Subdivision.
  3. Định hướng lồng nhất quán (BFS qua cạnh 2 mặt), lật cả mảnh theo đa số pháp tuyến TMD; nhớ mặt nào bị đảo so với
     chiều SC để khi phát tam giác con trả lại đúng chiều gốc của từng gói.
  4. Crease 'boxy' v2 (như exp_quality.py của báo cáo chất lượng) + hồ sơ (profile, `detect_profiles`, ghi đè được trong
     rules.json): mặt mắt / viền trong mờ-đục / cạnh không đa tạp / đế giày / cạnh vũ khí / cạnh giáp (armour) -> crease 1
     + sharp; tay (hands) -> crease tối thiểu 0.5 ở cạnh >= 30°; crease đỉnh 1 ở mũi nhọn (tổng góc < 200°), 0.5 cho da
     mặt (< 280°).
  5. Bơm thể tích từng đỉnh: lồng P1 có mặt giới hạn đi qua đỉnh gốc (giải K_lim·P1 = P0 bằng ma trận stencil lấy từ
     Blender), lồng = P0 + f_v·(P1 − P0); f_v = 1 ở biên, đỉnh đặc trưng (thiếu góc > 60°), vùng khớp (gần biên phần khác
     ở mọi khung đã lấy mẫu), đỉnh mặt mắt; f toàn cục chia đôi để thể tích lưới subdivision = thể tích TMD.
  6. Sửa khớp ("min-offset 0"): điểm biên của phần khác nằm trong phần này (lưới gốc, mọi khung) phải vẫn nằm trong
     mặt remaster (đẩy lồng ra theo stencil, lặp).
  7. Váy (skirt) ở vòng biên hở là khớp: dải mặt nối tiếp bề mặt, nghiêng vào trong, crease 1 ở vòng gốc, srcFace và (s,t)
     kẹp từ mặt kề; dài max(2 cạnh, 8% đường chéo), rút ngắn tới khi đầu váy bị phần khác che ở mọi khung lấy mẫu.
  8. Subdivision Surface của Blender: use_limit_surface, quality 3, uv_smooth NONE, boundary PRESERVE_CORNERS. Không Bevel,
     không Shrinkwrap. Lớp UV 'st' mang tham số góc TMD (§3.2: tam giác (0,0),(1,0),(0,1); tứ giác thứ tự Z).
  9. Pháp tuyến hình học (sharp ở crease 1); phần có p90 góc(pháp tuyến TMD, pháp tuyến mặt) > 60° trộn 50/50 với pháp
     tuyến TMD nội suy. Mặt đề can dùng lại đúng tam giác con của mặt nền (vị trí trùng bit, cùng pháp tuyến); mặt sau đảo
     chiều, pháp tuyến đối, srcFace riêng.
  10. Phần có >= 80% gói trong mờ: L0 (bản sao hình gốc, mode 1 identity). Hồ sơ vũ khí: tối đa L1.

Ma trận stencil: Subdivision của Blender tuyến tính theo toạ độ lồng (báo cáo chất lượng: S(P+Q) = S(P) + S(Q)), nên
K (m x n) lấy bằng cách đánh giá n/3 lần với véc-tơ cơ sở; mọi phép bơm / chia đôi / sửa khớp làm bằng numpy trên K, rồi
Blender đánh giá lại một lần ở lồng cuối để lấy vị trí và pháp tuyến góc thật. Mọi phần của cùng một mức được đánh giá
chung (`subdivide_parts` / `evaluate_many`: một lần cập nhật depsgraph cho mọi đối tượng lồng — mỗi đối tượng có modifier
riêng nên kết quả không đổi, nhanh hơn 2-3 lần).

Tự kiểm: `python tools/sc_remaster/blender/remaster_core.py` (numpy, mô hình tổng hợp `synth_model`, không cần Blender /
dữ liệu game; mã thoát 0 = đạt); bản đầy đủ trong Blender: `geom_job.py -- --selftest`.

Đầu ra của `process_model`: {'parts': [{level: partmesh}], 'info': [...], 'stats': {...}}; partmesh = dict mảng đúng lược
đồ SPEC §3.8 (pos f32[P,3], corner_pos u32[C], corner_n f32[C,3], corner_face u32[C], corner_st u16[C,2],
corner_near u16[C], corner_role u8[C], tri u32[T,3], mode) + tri_flag u8[T] (bit 0 = tam giác váy) + level.
`write_npz` ghi npz xác định (zip STORED, ngày giờ cố định): khoá 'format', 'level', 'partCount', 'srcFaceCount[n]',
'mode[n]', 'partLevel[n]', và mỗi phần 'p%03d_<trường>' (pos, corner_pos, corner_n, corner_face, corner_st, corner_near,
corner_role, tri, tri_flag, mode).

Dữ liệu suy ra từ đĩa (npz, qa.json, ảnh) chỉ ghi dưới work/upscale/sc_remaster* hoặc <game>/remaster_work (git bỏ qua).
"""
import hashlib
import io
import json
import math
import os
import struct
import time
import zipfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
RULES_PATH = os.path.join(HERE, 'rules.json')
DEFAULT_GAME = os.path.join(ROOT, 'game', 'files')
GENERATOR = 'lodsc-remaster p2 1'

ST = {3: ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)), 4: ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))}
ROLE_BASE, ROLE_DECAL, ROLE_BACK = 0, 1, 2
FLAG_SKIRT = 1
EPS = 1e-12


# ---------------------------------------------------------------- quy tắc
def _merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def load_rules(path=None, params=None):
    """rules.json (mặc định cạnh file này) + ghi đè `params` (dict lồng nhau, vd. {'levels': [1], 'inflate': {'enabled':
    False}}). Trả dict; 'rules_sha1' = SHA-1 của JSON chuẩn hoá (đưa vào qa.json)."""
    with open(path or RULES_PATH, encoding='utf-8') as f:
        rules = json.load(f)
    if params:
        _merge(rules, json.loads(json.dumps(params)))
    rules['rules_sha1'] = hashlib.sha1(json.dumps(rules, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
    return rules


def part_override(rules, doc, i):
    """Ghi đè theo phần từ rules['overrides']['models'][<tên job | source.model | modelKey>]['parts'][str(i)]."""
    models = rules.get('overrides', {}).get('models', {})
    keys = [doc.get('name'), doc.get('source', {}).get('model'), doc.get('modelKey')]
    out = {}
    for k in keys:
        if k and k in models:
            out.update(models[k].get('parts', {}).get(str(i), {}))
    return out


# ---------------------------------------------------------------- hình học cơ bản
def newell(P):
    """Pháp tuyến Newell (không chuẩn hoá, độ dài = 2 x diện tích) của đa giác P (k,3)."""
    a = P
    b = np.roll(P, -1, axis=0)
    return np.array([np.sum((a[:, 1] - b[:, 1]) * (a[:, 2] + b[:, 2])),
                     np.sum((a[:, 2] - b[:, 2]) * (a[:, 0] + b[:, 0])),
                     np.sum((a[:, 0] - b[:, 0]) * (a[:, 1] + b[:, 1]))])


def newell_many(W, polys):
    """Pháp tuyến Newell (không chuẩn hoá) của mọi đa giác (danh sách chỉ số đỉnh) -> (P,3). Đa giác ngắn được đệm bằng
    đỉnh cuối (cạnh rỗng đóng góp đúng 0), thứ tự cộng giống `newell`."""
    if not polys:
        return np.zeros((0, 3))
    kmax = max(len(p) for p in polys)
    idx = np.array([list(p) + [p[-1]] * (kmax - len(p)) for p in polys], np.int64)
    a = W[idx]
    b = W[np.roll(idx, -1, axis=1)]
    return np.stack([np.sum((a[..., 1] - b[..., 1]) * (a[..., 2] + b[..., 2]), 1),
                     np.sum((a[..., 2] - b[..., 2]) * (a[..., 0] + b[..., 0]), 1),
                     np.sum((a[..., 0] - b[..., 0]) * (a[..., 1] + b[..., 1]), 1)], 1)


def unit(v, axis=-1):
    n = np.linalg.norm(v, axis=axis, keepdims=True)
    return v / np.maximum(n, EPS)


def angle_deg(a, b):
    a = unit(np.asarray(a, float))
    b = unit(np.asarray(b, float))
    return np.degrees(np.arccos(np.clip(np.sum(a * b, axis=-1), -1.0, 1.0)))


def closest_pairs(p, a, b, c):
    """Điểm gần nhất trên tam giác cho từng cặp (p[k], tam giác k) — Ericson 5.1.5 vector hoá -> (q (M,3), lam (M,3))."""
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
    lam = np.stack([1 - v - w, v, w], -1)
    z = np.zeros_like(v)
    e = (d4 - d3) + (d5 - d6)
    t = (d4 - d3) / np.where(np.abs(e) < EPS, EPS, e)
    lam = np.where(((va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0))[:, None], np.stack([z, 1 - t, t], -1), lam)
    e = d2 - d6
    t = d2 / np.where(np.abs(e) < EPS, EPS, e)
    lam = np.where(((vb <= 0) & (d2 >= 0) & (d6 <= 0))[:, None], np.stack([1 - t, z, t], -1), lam)
    lam = np.where(((d6 >= 0) & (d5 <= d6))[:, None], np.array([0.0, 0.0, 1.0]), lam)
    e = d1 - d3
    t = d1 / np.where(np.abs(e) < EPS, EPS, e)
    lam = np.where(((vc <= 0) & (d1 >= 0) & (d3 <= 0))[:, None], np.stack([1 - t, t, z], -1), lam)
    lam = np.where(((d3 >= 0) & (d4 <= d3))[:, None], np.array([0.0, 1.0, 0.0]), lam)
    lam = np.where(((d1 <= 0) & (d2 <= 0))[:, None], np.array([1.0, 0.0, 0.0]), lam)
    q = lam[:, 0:1] * a + lam[:, 1:2] * b + lam[:, 2:3] * c
    return q, lam


def candidate_pairs(p, lo, hi, cen, rad, cn, dv):
    """Cặp (điểm, tam giác) có thể chứa tam giác gần nhất: lọc thô bằng cầu bao (khoảng cách tâm qua matmul, có lề) rồi
    đúng bộ lọc hộp bao 'khoảng cách tới hộp <= khoảng cách tới đỉnh gần nhất' -> (pi, ti) theo thứ tự (pi, ti)."""
    pn = np.einsum('ij,ij->i', p, p)
    d2 = np.maximum(pn[:, None] + cn[None] - 2.0 * (p @ cen.T), 0.0)
    lim = np.sqrt(dv)[:, None] * (1 + 1e-6) + rad[None] + 1e-6 * (1.0 + np.sqrt(pn)[:, None])
    pi, ti = np.nonzero(d2 <= lim * lim)
    pp = p[pi]
    dd = np.maximum(lo[ti] - pp, 0) + np.maximum(pp - hi[ti], 0)
    keep = np.einsum('ij,ij->i', dd, dd) <= dv[pi] * (1 + 1e-9) + 1e-9
    return pi[keep], ti[keep]


def nearest_vertex_d2(points, Vt, chunk=4_000_000):
    """Bình phương khoảng cách thật tới một đỉnh gần nhất (chọn bằng matmul) — chặn trên của khoảng cách tới lưới."""
    n_p = len(points)
    dv = np.empty(n_p)
    vn = np.einsum('ij,ij->i', Vt, Vt)
    step = max(1, chunk // max(1, len(Vt)))
    for s in range(0, n_p, step):
        p = points[s:s + step]
        j = np.argmin(np.einsum('ij,ij->i', p, p)[:, None] + vn[None] - 2.0 * (p @ Vt.T), 1)
        dv[s:s + step] = np.sum((p - Vt[j]) ** 2, 1)
    return dv


def nearest_signed(points, A, B, C, N, chunk=4_000_000, V=None):
    """Mỗi điểm: tam giác gần nhất (chỉ số), khoảng cách, dấu (p - q)·n_giả (âm = phía trong; n_giả = tổng pháp tuyến các
    tam giác có cùng điểm gần nhất — cạnh / đỉnh chung), toạ độ trọng tâm của điểm gần nhất. Lọc cặp bằng cầu / hộp bao so
    với khoảng cách tới đỉnh gần nhất (`candidate_pairs`)."""
    points = np.asarray(points, float)
    n_p = len(points)
    idx = np.zeros(n_p, int)
    dist = np.full(n_p, np.inf)
    side = np.zeros(n_p)
    lam_out = np.zeros((n_p, 3))
    if n_p == 0 or len(A) == 0:
        return idx, dist, side, lam_out
    lo = np.minimum(np.minimum(A, B), C)
    hi = np.maximum(np.maximum(A, B), C)
    cen = (lo + hi) * 0.5
    rad = np.linalg.norm(hi - lo, axis=1) * 0.5
    cn = np.einsum('ij,ij->i', cen, cen)
    Vt = np.unique(np.concatenate([A, B, C]), axis=0) if V is None else np.asarray(V, float)
    dv = nearest_vertex_d2(points, Vt, chunk)
    step = max(1, chunk // max(1, len(A)))
    for s in range(0, n_p, step):
        p = points[s:s + step]
        pi, ti = candidate_pairs(p, lo, hi, cen, rad, cn, dv[s:s + step])
        q, lam = closest_pairs(p[pi], A[ti], B[ti], C[ti])
        d2 = np.sum((p[pi] - q) ** 2, 1)
        order = np.lexsort((ti, d2, pi))
        first = order[np.r_[True, pi[order][1:] != pi[order][:-1]]]
        mn = np.full(len(p), np.inf)
        qb = np.zeros((len(p), 3))
        mn[pi[first]] = d2[first]
        qb[pi[first]] = q[first]
        tie = (d2 <= mn[pi] + 1e-6 * np.maximum(mn[pi], 1.0)) &               (np.sum((q - qb[pi]) ** 2, 1) <= 1e-8 * np.maximum(mn[pi], 1.0))
        nsum = np.zeros((len(p), 3))
        np.add.at(nsum, pi[tie], N[ti[tie]])
        idx[s + pi[first]] = ti[first]
        lam_out[s + pi[first]] = lam[first]
        dist[s:s + step] = np.sqrt(mn)
        side[s:s + step] = np.sum((p - qb) * nsum, 1) / np.maximum(np.linalg.norm(nsum, axis=1), EPS)
    return idx, dist, side, lam_out


def tri_volume(P, tris, centre):
    a = P[tris[:, 0]] - centre
    b = P[tris[:, 1]] - centre
    c = P[tris[:, 2]] - centre
    return float(np.einsum('ij,ij->i', a, np.cross(b, c)).sum() / 6.0)


def fan(polys):
    out = []
    for p in polys:
        for k in range(1, len(p) - 1):
            out.append((p[0], p[k], p[k + 1]))
    return np.array(out, int).reshape(-1, 3)


# ---------------------------------------------------------------- hoạt cảnh (TmdAnimationFile, chỉ đọc)
def rot_zyx(rx, ry, rz):
    """Keyframe0c: quat.rotationZYX(z, y, x) = Rz * Ry * Rx; 4096 = 360°. Vector hoá theo mảng."""
    ax, ay, az = [np.asarray(v, float) / 4096.0 * 2 * math.pi for v in (rx, ry, rz)]
    cx, sx, cy, sy, cz, sz = np.cos(ax), np.sin(ax), np.cos(ay), np.sin(ay), np.cos(az), np.sin(az)
    one, zero = np.ones_like(cx), np.zeros_like(cx)
    Rx = np.stack([np.stack([one, zero, zero], -1), np.stack([zero, cx, -sx], -1), np.stack([zero, sx, cx], -1)], -2)
    Ry = np.stack([np.stack([cy, zero, sy], -1), np.stack([zero, one, zero], -1), np.stack([-sy, zero, cy], -1)], -2)
    Rz = np.stack([np.stack([cz, -sz, zero], -1), np.stack([sz, cz, zero], -1), np.stack([zero, zero, one], -1)], -2)
    return Rz @ Ry @ Rx


def read_anim(b, nparts=None):
    """TmdAnimationFile (SC): u16 số phần @0xc, s16 tổng khung @0xe, số khung khoá = tổng/2, mỗi khung khoá nparts x 12
    byte (svec3 quay, svec3 dời) từ 0x10. Trả (R (K,P,3,3), T (K,P,3)) hoặc None nếu không hợp lệ / khác số phần."""
    if len(b) < 0x10 or struct.unpack_from('<I', b, 0)[0] == 0x11:
        return None
    n = struct.unpack_from('<H', b, 0xc)[0]
    total = struct.unpack_from('<h', b, 0xe)[0]
    kf = total // 2
    if n == 0 or (nparts is not None and n != nparts) or kf <= 0 or 0x10 + kf * n * 12 > len(b):
        return None
    a = np.frombuffer(b, '<i2', kf * n * 6, 0x10).reshape(kf, n, 6).astype(float)
    return rot_zyx(a[..., 0], a[..., 1], a[..., 2]), a[..., 3:6].copy()


def _read_mrg(d):
    p = os.path.join(d, 'mrg')
    if not os.path.isfile(p):
        return None
    m = {}
    with open(p, encoding='ascii') as f:
        for line in f:
            line = line.strip()
            if not line or '=' not in line:
                continue
            v, rest = line.split('=', 1)
            r, s = (rest.split(';', 1) + ['0'])[:2]
            try:
                m[int(v)] = (int(r) if r.strip() else -1, int(s) if s.strip() else 0)
            except ValueError:
                continue
    return m


def _resolve(m, v, d):
    """Tệp thật cho mục ảo v trong thư mục d (mrg: 'ảo=thật;cỡ', cỡ 0 = liên kết; theo chuỗi liên kết)."""
    p = os.path.join(d, str(v))
    if os.path.isfile(p):
        return p
    if m is None or v not in m:
        return None
    seen = set()
    r = m[v][0]
    while r not in seen and r >= 0:
        seen.add(r)
        p = os.path.join(d, str(r))
        if os.path.isfile(p):
            return p
        if r not in m or m[r][0] == r:
            break
        r = m[r][0]
    return None


def find_anims(doc, game=None):
    """Mọi file hoạt cảnh của mô hình (chỉ đọc game/files), lọc đúng số phần, bỏ trùng theo SHA-1:
    - trận: characters/<c>/models/<form>/<số> (mọi file số trừ file mô hình);
    - trường: SECT/DRGN2x.BIN/<cảnh>/<obj*33+1 .. obj*33+32> (theo mrg);
    - khác: chỉ source.anim. Trả [{path, sha1, R, T}] theo thứ tự đường dẫn."""
    game = game or DEFAULT_GAME
    src = doc.get('source', {})
    npart = len(doc['parts'])
    model = src.get('model', '')
    cands = []
    md = os.path.dirname(model)
    base = os.path.join(game, *md.split('/')) if md else None
    if model.startswith('characters/') and base and os.path.isdir(base):
        mname = os.path.basename(model)
        for fn in sorted(os.listdir(base), key=lambda s: (len(s), s)):
            if fn.isdigit() and fn != mname:
                cands.append(os.path.join(base, fn))
    elif model.startswith('SECT/') and base and os.path.isdir(base) and os.path.basename(model).isdigit():
        obj = int(os.path.basename(model)) // 33
        m = _read_mrg(base)
        for k in range(obj * 33 + 1, obj * 33 + 33):
            p = _resolve(m, k, base)
            if p:
                cands.append(p)
    if src.get('anim'):
        cands.append(os.path.join(game, *src['anim'].split('/')))
    out, seen = [], set()
    for p in cands:
        if not os.path.isfile(p):
            continue
        with open(p, 'rb') as f:
            b = f.read()
        h = hashlib.sha1(b).hexdigest()
        if h in seen:
            continue
        r = read_anim(b, npart)
        if r is None:
            continue
        seen.add(h)
        out.append(dict(path=os.path.relpath(p, game).replace('\\', '/'), sha1=h, R=r[0], T=r[1]))
    return out


def kf0_pose(doc):
    R = np.array([p['kf0_matrix'] for p in doc['parts']], float)
    T = np.array([p['kf0_trans'] for p in doc['parts']], float)
    return R[None], T[None]


def all_poses(doc, anims, limit=None):
    """Mọi khung khoá (khung 0 của JSON trước, rồi mọi hoạt cảnh); limit -> lấy mẫu đều, luôn giữ khung 0."""
    R0, T0 = kf0_pose(doc)
    Rs, Ts = [R0], [T0]
    for a in anims:
        Rs.append(a['R'])
        Ts.append(a['T'])
    R = np.concatenate(Rs)
    T = np.concatenate(Ts)
    if limit and len(R) > limit:
        sel = np.unique(np.round(np.linspace(0, len(R) - 1, limit)).astype(int))
        R, T = R[sel], T[sel]
    return R, T


# ---------------------------------------------------------------- phân tích phần
def face_class(f):
    """Lớp lưới TmdObjLoader: 0 opaque, 1 untextured translucent, 2+abr = Translucency (SPEC §4.3)."""
    if f['translucent'] and f['textured']:
        return 2 + ((int(f['tpage'], 16) >> 5) & 3)
    if f['translucent']:
        return 1
    return 0


def analyse_part(part, rules):
    """Hàn đỉnh, phân lớp mặt, dựng lồng (đa giác đỉnh hàn theo chiều SC) cho một phần JSON."""
    V = np.array(part['verts'], float).reshape(-1, 3)
    nv = len(V)
    wd = max(float(rules.get('weld_dist', 1e-3)), 1e-9)
    wid = np.zeros(nv, int)
    rep, seen = [], {}
    for i, k in enumerate(map(tuple, np.round(V / wd).astype(np.int64))):
        if k not in seen:
            seen[k] = len(rep)
            rep.append(i)
        wid[i] = seen[k]
    W = V[rep] if rep else np.zeros((0, 3))
    faces = []
    for k, f in enumerate(part['faces']):
        if int(f['prim']) != k:
            raise ValueError('%s: prim %s != chi so %d (JSON khong theo thu tu goi)' % (part.get('name'), f['prim'], k))
        vc = 4 if f['quad'] else 3
        vidx = [int(x) for x in f['vidx']]
        wv = [int(wid[v]) for v in vidx]
        seq = []
        for c in f['loop']:
            if wv[c] not in [s[0] for s in seq]:
                seq.append((wv[c], c))
        n_tmd = None
        if f.get('normals') is not None and f['lit']:
            n_tmd = np.round(np.array(f['normals'], float) * 4096.0) / 4096.0
        # gói "thấy" = có tam giác SC ((2,1,0), tứ giác thêm (1,2,3)) gồm 3 đỉnh hàn phân biệt; tứ giác hàn hai góc chéo 1-2
        # còn 3 đỉnh phân biệt nhưng retail không vẽ gì -> coi như suy biến (không vào lồng).
        vis = len({wv[2], wv[1], wv[0]}) == 3 or (vc == 4 and len({wv[1], wv[2], wv[3]}) == 3)
        faces.append(dict(k=k, vc=vc, vidx=vidx, wv=wv, seq=seq, distinct=len(set(wv)) if vis else min(len(set(wv)), 2),
                          loop=list(f['loop']),
                          textured=bool(f['textured']), translucent=bool(f['translucent']), lit=bool(f['lit']),
                          n_tmd=n_tmd, geo=np.array(f['geo_normal'], float), transp=float(f.get('transp_frac', 0.0)),
                          mclass=face_class(f), layer='skip', base=-1, deps=[], cage=-1))
    groups, order = {}, []
    for f in faces:
        if f['distinct'] < 3:
            continue
        key = tuple(sorted(set(f['wv'])))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(f)
    for key in order:
        g = sorted(groups[key], key=lambda f: (f['transp'] if f['textured'] else -1.0, f['k']))
        b = g[0]
        b['layer'] = 'base'
        for f in g[1:]:
            f['layer'] = 'back' if float(np.dot(b['geo'], f['geo'])) < 0 else 'decal'
            f['base'] = b['k']
            b['deps'].append(f['k'])
    polys, poly_face, poly_corner = [], [], []
    for f in faces:
        if f['layer'] == 'base':
            f['cage'] = len(polys)
            polys.append([s[0] for s in f['seq']])
            poly_face.append(f['k'])
            poly_corner.append([s[1] for s in f['seq']])
    ntr = sum(1 for f in faces if f['translucent'])
    return dict(index=int(part.get('index', 0)), name=part.get('name', ''), V=V, nv=nv, wid=wid, rep=np.array(rep, int),
                W=W, faces=faces, polys=polys, poly_face=poly_face, poly_corner=poly_corner,
                tr_frac=(ntr / len(faces)) if faces else 0.0,
                diag=float(np.linalg.norm(W.max(0) - W.min(0))) if len(W) else 0.0)


def orient_cage(cage):
    """Hướng nhất quán qua cạnh đa tạp + lật mảnh theo đa số pháp tuyến TMD. Ghi cage['flip'][p] = đa giác bị đảo so với
    chiều SC; cage['polys'] thành chiều lồng."""
    polys = cage['polys']
    n = len(polys)
    emap = {}
    for p, poly in enumerate(polys):
        for a, b in zip(poly, poly[1:] + poly[:1]):
            emap.setdefault((min(a, b), max(a, b)), []).append((p, 1 if a < b else -1))
    o = [0] * n
    comps = []
    for s in range(n):
        if o[s]:
            continue
        o[s] = 1
        comp, stack = [s], [s]
        while stack:
            p = stack.pop()
            poly = polys[p]
            for a, b in zip(poly, poly[1:] + poly[:1]):
                lst = emap[(min(a, b), max(a, b))]
                if len(lst) != 2:
                    continue
                dp = 1 if a < b else -1
                for q, dq in lst:
                    if q != p and not o[q]:
                        o[q] = -dp * o[p] * dq
                        comp.append(q)
                        stack.append(q)
        comps.append(sorted(comp))
    W = cage['W']
    faces = cage['faces']
    nn_all = newell_many(W, polys)
    for comp in comps:
        score = 0.0
        for p in comp:
            f = faces[cage['poly_face'][p]]
            if f['n_tmd'] is not None:
                score += o[p] * float(np.dot(nn_all[p], f['n_tmd'].sum(0)))
        if score < 0 or (score == 0 and sum(o[p] for p in comp) < 0):
            for p in comp:
                o[p] = -o[p]
    cage['flip'] = [o[p] < 0 for p in range(n)]
    cage['polys'] = [polys[p] if o[p] > 0 else polys[p][::-1] for p in range(n)]
    cage['poly_corner'] = [cage['poly_corner'][p] if o[p] > 0 else cage['poly_corner'][p][::-1] for p in range(n)]
    cage['n_comp'] = len(comps)
    build_topology(cage)


def build_topology(cage):
    """Bảng cạnh (sắp theo (min,max)), mặt kề, cạnh biên có hướng, pháp tuyến đa giác, tổng góc tại đỉnh."""
    W = cage['W']
    polys = cage['polys']
    emap = {}
    for p, poly in enumerate(polys):
        for a, b in zip(poly, poly[1:] + poly[:1]):
            emap.setdefault((min(a, b), max(a, b)), []).append(p)
    keys = sorted(emap)
    cage['edges'] = np.array(keys, int).reshape(-1, 2)
    cage['edge_polys'] = [emap[k] for k in keys]
    cage['edge_index'] = {k: i for i, k in enumerate(keys)}
    nn_all = newell_many(W, polys)
    pn = unit(nn_all).reshape(-1, 3)
    cage['pnorm'] = pn
    nW = len(W)
    vfaces = [[] for _ in range(nW)]
    cur, prv, nxt = [], [], []
    for p, poly in enumerate(polys):
        k = len(poly)
        for i in range(k):
            vfaces[poly[i]].append(p)
            cur.append(poly[i])
            prv.append(poly[i - 1])
            nxt.append(poly[(i + 1) % k])
    if cur:
        cur = np.array(cur)
        ang = angle_deg(W[np.array(prv)] - W[cur], W[np.array(nxt)] - W[cur])
        angsum = np.bincount(cur, weights=ang, minlength=nW)
    else:
        angsum = np.zeros(nW)
    cage['angsum'] = angsum
    cage['vfaces'] = vfaces
    bnd = np.zeros(nW, bool)
    nonman = np.zeros(nW, bool)
    bedges = []
    for (a, b), lst in zip(keys, cage['edge_polys']):
        if len(lst) == 1:
            bnd[a] = bnd[b] = True
            poly = polys[lst[0]]
            i = poly.index(a)
            if poly[(i + 1) % len(poly)] == b:
                bedges.append((a, b, lst[0]))
            else:
                bedges.append((b, a, lst[0]))
        elif len(lst) > 2:
            nonman[a] = nonman[b] = True
    cage['bnd'] = bnd
    cage['nonman_v'] = nonman
    cage['bedges'] = bedges
    vn = np.zeros((nW, 3))
    for p, poly in enumerate(polys):
        for v in poly:
            vn[v] += nn_all[p]
    cage['vnorm'] = unit(vn)
    used = np.zeros(nW, bool)
    for poly in polys:
        used[poly] = True
    cage['used'] = used


def boundary_loops(cage):
    """Chuỗi cạnh biên có hướng thành vòng (đỉnh rẽ nhánh -> cắt chuỗi). Trả [[(a, b, poly), ...]]."""
    nxt = {}
    multi = set()
    for e in cage['bedges']:
        if e[0] in nxt:
            multi.add(e[0])
        nxt.setdefault(e[0], []).append(e)
    used = set()
    loops = []
    for e in sorted(cage['bedges']):
        if (e[0], e[1]) in used:
            continue
        loop = []
        cur = e
        while cur is not None and (cur[0], cur[1]) not in used:
            used.add((cur[0], cur[1]))
            loop.append(cur)
            cand = [x for x in nxt.get(cur[1], []) if (x[0], x[1]) not in used]
            cur = cand[0] if len(cand) == 1 and cur[1] not in multi else None
        loops.append(loop)
    return loops


def detect_profiles(doc, cages, rules):
    """Hồ sơ từng phần (tập cờ), tự nhận rồi ghi đè được bằng rules['overrides']['models'][..]['parts'][i]['profile']:
    translucent (>= 80% gói trong mờ -> L0), face (mặt / mắt: có đề can hoặc mặt nhiều texel trong suốt), hair (p90 góc
    pháp tuyến TMD / hình học > 60° -> trộn pháp tuyến), boots (chạm sàn, thấp), weapon (thanh dài / bản dẹt và dài
    >= 0.45 chiều cao mô hình — tay chân mảnh không tính -> crease cứng, tối đa L1), hands (phần nhỏ ở giữa thân, lệch khỏi trục dọc, ít mặt -> giữ góc cạnh), armour (>= 40% mặt có đèn
    là mặt phẳng — pháp tuyến các góc giống nhau, bề mặt cứng -> cạnh >= 40° crease 1)."""
    pr = rules['profiles']
    R0, T0 = kf0_pose(doc)
    allp = []
    for i, c in enumerate(cages):
        if len(c['W']):
            allp.append(c['W'] @ R0[0, i].T + T0[0, i])
    allp = np.concatenate(allp) if allp else np.zeros((1, 3))
    ymax, ymin = float(allp[:, 1].max()), float(allp[:, 1].min())
    H = max(ymax - ymin, EPS)
    axis_x, axis_z = float(np.median(allp[:, 0])), float(np.median(allp[:, 2]))
    out = []
    for i, c in enumerate(cages):
        prof = set()
        faces = c['faces']
        if not c['polys']:
            out.append(prof)
            continue
        if c['tr_frac'] >= rules['translucent_l0_frac']:
            prof.add('translucent')
        if any(f['layer'] in ('decal', 'back') and f['base'] >= 0 and faces[f['base']]['textured'] for f in faces) or \
                any(f['textured'] and f['transp'] >= pr['eye_transp_frac'] and f['layer'] == 'base' for f in faces):
            prof.add('face')
        angs = []
        for f in faces:
            if f['layer'] == 'base' and f['n_tmd'] is not None and np.linalg.norm(f['geo']) > EPS:
                angs.extend(angle_deg(f['n_tmd'], f['geo'][None]).tolist())
        if angs and float(np.percentile(angs, 90)) > rules['normals']['blend_p90_angle']:
            prof.add('hair')
        P = c['W'][c['used']] @ R0[0, i].T + T0[0, i]
        if len(P) and P[:, 1].max() >= ymax - pr['boots_floor_rel'] * H and (P[:, 1].max() - P[:, 1].min()) <= \
                pr['boots_height_rel'] * H:
            prof.add('boots')
        Wu = c['W'][c['used']]
        if len(Wu) >= 4 and len(P) and \
                float(np.linalg.norm(P.max(0) - P.min(0))) >= pr['weapon_min_len_rel'] * H:
            e = np.sort(np.linalg.svd(Wu - Wu.mean(0), compute_uv=False))[::-1]
            e = np.maximum(e, 1e-6)
            if e[0] >= pr['weapon_ratio_long'] * e[1] or (e[0] >= pr['weapon_ratio_flat_long'] * e[1] and
                                                          e[0] >= pr['weapon_ratio_flat_thin'] * e[2]):
                prof.add('weapon')
        if len(P) and not prof & {'translucent', 'face', 'hair', 'boots', 'weapon'}:
            cen = P.mean(0)
            yrel = (float(cen[1]) - ymin) / H
            lat = math.hypot(float(cen[0]) - axis_x, float(cen[2]) - axis_z) / H
            nbase = sum(1 for f in faces if f['layer'] == 'base')
            if float(np.linalg.norm(P.max(0) - P.min(0))) <= pr['hands_diag_rel'] * H and \
                    pr['hands_y_min'] <= yrel <= pr['hands_y_max'] and lat >= pr['hands_lat_rel'] and \
                    nbase <= pr['hands_max_faces']:
                prof.add('hands')
        lit = [f for f in faces if f['layer'] == 'base' and f['n_tmd'] is not None]
        if 'translucent' not in prof and len(lit) >= pr['armour_min_faces']:
            flat = sum(1 for f in lit if np.allclose(f['n_tmd'], f['n_tmd'][0], atol=1e-3))
            if flat >= pr['armour_flat_frac'] * len(lit):
                prof.add('armour')
        ov = part_override(rules, doc, i)
        if 'profile' in ov:
            prof = set(ov['profile'])
        out.append(prof)
    return out


def eye_faces(cage, prof, rules):
    """Mặt 'mắt' (hồ sơ face): mặt nền có đề can, hoặc mặt có texel trong suốt >= eye_transp_frac."""
    if 'face' not in prof:
        return set()
    th = rules['profiles']['eye_transp_frac']
    return {f['k'] for f in cage['faces'] if f['layer'] == 'base' and
            (any(cage['faces'][d]['layer'] == 'decal' for d in f['deps']) or (f['textured'] and f['transp'] >= th))}


def compute_creases(cage, prof, rules, R0):
    """Crease 'boxy' v2 + hồ sơ. Ghi cage['ecrease'], cage['esharp'], cage['vcrease'], cage['eye'], cage['feature']."""
    cr = rules['crease']
    faces = cage['faces']
    eyes = eye_faces(cage, prof, rules)
    cage['eye'] = eyes
    E = len(cage['edges'])
    ec = np.zeros(E)
    es = np.zeros(E, bool)
    stats = dict(boundary=0, nonmanifold=0, sharp=0, hard=0, soft=0, boxy=0, eye=0, transl_border=0, sole=0, weapon=0,
                 armour=0, hands=0, smooth=0)
    pn = cage['pnorm']
    for ei, ((a, b), lst) in enumerate(zip(cage['edges'], cage['edge_polys'])):
        if len(lst) == 1:
            stats['boundary'] += 1
            continue
        if len(lst) > 2:
            ec[ei], es[ei] = cr['nonmanifold_crease'], True
            stats['nonmanifold'] += 1
            continue
        p, q = lst
        fp, fq = faces[cage['poly_face'][p]], faces[cage['poly_face'][q]]
        ang = math.degrees(math.acos(max(-1.0, min(1.0, float(pn[p] @ pn[q])))))
        nsplit = 0.0
        if fp['n_tmd'] is not None and fq['n_tmd'] is not None:
            for v in (a, b):
                kp = cage['poly_corner'][p][cage['polys'][p].index(v)]
                kq = cage['poly_corner'][q][cage['polys'][q].index(v)]
                na, nb = fp['n_tmd'][kp], fq['n_tmd'][kq]
                den = math.sqrt(float(na @ na) * float(nb @ nb))
                if den > 1e-12:
                    nsplit = max(nsplit, math.degrees(math.acos(max(-1.0, min(1.0, float(na @ nb) / den)))))
        if fp['k'] in eyes or fq['k'] in eyes:
            ec[ei], es[ei] = cr['eye_crease'], True
            stats['eye'] += 1
        elif fp['translucent'] != fq['translucent']:
            ec[ei], es[ei] = cr['translucent_border_crease'], True
            stats['transl_border'] += 1
        elif 'boots' in prof and cr['sole_min_angle'] <= ang <= cr['sole_max_angle'] and \
                max((R0 @ pn[p])[1], (R0 @ pn[q])[1]) >= cr['sole_down_dot']:
            ec[ei], es[ei] = 1.0, True
            stats['sole'] += 1
        elif ang >= cr['sharp_angle']:
            ec[ei], es[ei] = 1.0, True
            stats['sharp'] += 1
        elif 'armour' in prof and ang >= cr['armour_angle']:
            ec[ei], es[ei] = 1.0, True
            stats['armour'] += 1
        elif 'hands' in prof and ang >= cr['hands_angle']:
            boxy = (min(cr['boxy_hi_max'], cr['boxy_hi_base'] + cr['boxy_hi_add'] * (ang - cr['boxy_hi_angle']) /
                        cr['boxy_hi_span']) if ang >= cr['boxy_hi_angle'] else cr['boxy_lo_crease'])
            hard = cr['hard_crease'] if nsplit >= cr['split_angle'] and ang >= cr['hard_angle'] else 0.0
            ec[ei] = max(cr['hands_crease'], boxy, hard)
            es[ei] = ec[ei] >= 1.0
            stats['hands'] += 1
        elif nsplit >= cr['split_angle'] and ang >= cr['hard_angle']:
            ec[ei] = cr['hard_crease']
            es[ei] = cr['hard_crease'] >= 1.0
            stats['hard'] += 1
        elif nsplit >= cr['split_angle'] and ang >= cr['soft_angle']:
            ec[ei] = cr['soft_crease']
            stats['soft'] += 1
        elif 'weapon' in prof and ang >= cr['weapon_angle']:
            ec[ei], es[ei] = 1.0, True
            stats['weapon'] += 1
        elif ang >= cr['boxy_hi_angle']:
            ec[ei] = min(cr['boxy_hi_max'], cr['boxy_hi_base'] + cr['boxy_hi_add'] * (ang - cr['boxy_hi_angle']) /
                         cr['boxy_hi_span'])
            stats['boxy'] += 1
        elif ang >= cr['boxy_lo_angle']:
            ec[ei] = cr['boxy_lo_crease']
            stats['boxy'] += 1
        else:
            stats['smooth'] += 1
    nW = len(cage['W'])
    vc = np.zeros(nW)
    tip = rules['tip']
    interior = ~cage['bnd'] & ~cage['nonman_v'] & cage['used']
    vc[interior & (cage['angsum'] < tip['angle_sum'])] = 1.0
    if 'face' in prof:
        m = interior & (cage['angsum'] < tip['skin_angle_sum']) & (vc < tip['skin_crease'])
        vc[m] = tip['skin_crease']
    stats['tip_vertices'] = int((vc >= 1.0).sum())
    stats['skin_vertices'] = int(((vc > 0) & (vc < 1.0)).sum())
    cage['feature'] = interior & (360.0 - cage['angsum'] > rules['inflate']['feature_deficit'])
    eye_v = np.zeros(nW, bool)
    for p, k in enumerate(cage['poly_face']):
        if k in eyes:
            eye_v[cage['polys'][p]] = True
    cage['eye_v'] = eye_v
    cage['ecrease'] = ec
    cage['esharp'] = es
    cage['vcrease'] = vc
    cage['crease_stats'] = stats


# ---------------------------------------------------------------- kế hoạch khớp (vùng khớp, ràng buộc, váy)
def part_tris(cage):
    """Tam giác lồng gốc (chiều lồng, hướng ra ngoài) để thử 'nằm trong'."""
    t = fan(cage['polys'])
    W = cage['W']
    if not len(t):
        return t, np.zeros((0, 3)), np.zeros((0, 3)), np.zeros((0, 3)), np.zeros((0, 3))
    A, B, C = W[t[:, 0]], W[t[:, 1]], W[t[:, 2]]
    return t, A, B, C, unit(np.cross(B - A, C - A))


def to_local(Rj, Tj, Q):
    """Q (K,N,3) toạ độ mô hình -> toạ độ cục bộ phần j ở từng khung: R_j^T (q - T_j)."""
    return np.einsum('kji,knj->kni', Rj, Q - Tj[:, None, :])


def posed(Ri, Ti, P):
    return np.einsum('kij,nj->kni', Ri, P) + Ti[:, None, :]


def plan_joints(cages, R, T, rules, Rs=None, Ts=None):
    """Vùng khớp (đỉnh ghim), ràng buộc 'min-offset 0' và váy cho mọi phần.
    R, T: mọi khung (K,P,3,3)/(K,P,3) cho vùng khớp và ràng buộc; Rs, Ts: khung lấy mẫu cho thử che váy."""
    if Rs is None:
        Rs, Ts = R, T
    n = len(cages)
    inf = rules['inflate']
    qa = rules['qa']
    geo = [part_tris(c) for c in cages]
    bverts = [np.nonzero(c['bnd'] & c['used'])[0] if c['polys'] else np.zeros(0, int) for c in cages]
    plans = []
    for j in range(n):
        plans.append(dict(zone=np.zeros(len(cages[j]['W']), bool), constraints=np.zeros((0, 3)), skirts=[],
                          stats=dict(zone=0, constraints=0, skirt_loops=0, skirt_dropped=0)))
    lo = [c['W'][c['used']].min(0) if c['polys'] else None for c in cages]
    hi = [c['W'][c['used']].max(0) if c['polys'] else None for c in cages]
    for j in range(n):
        cj = cages[j]
        if not cj['polys']:
            continue
        diag = max(cj['diag'], EPS)
        zr = inf['joint_zone_rel'] * diag
        Wj = cj['W']
        cons = []
        for i in range(n):
            if i == j or not len(bverts[i]):
                continue
            Q = to_local(R[:, j], T[:, j], posed(R[:, i], T[:, i], cages[i]['W'][bverts[i]]))
            Qf = Q.reshape(-1, 3)
            near = np.all((Qf >= lo[j] - zr) & (Qf <= hi[j] + zr), axis=1)
            if not near.any():
                continue
            Qn = Qf[near]
            d = np.min(np.linalg.norm(Wj[None, :, :] - Qn[:, None, :], axis=-1), axis=0)
            plans[j]['zone'] |= (d < zr) & cj['used']
            # ràng buộc: điểm biên của i nằm trong lưới gốc của j
            _, A, B, C, N = geo[j]
            box = np.all((Qn >= lo[j] - 0.02 * diag) & (Qn <= hi[j] + 0.02 * diag), axis=1)
            g = float(rules['joint_fix'].get('grid', 0.5))
            Qb = np.unique(np.round(Qn[box] / g) * g, axis=0)
            if len(Qb):
                _, dist, side, _ = nearest_signed(Qb, A, B, C, N)
                ins = (side < 0) & (dist < qa['inside_max_rel'] * diag)
                if ins.any():
                    cons.append(Qb[ins])
        if cons:
            plans[j]['constraints'] = np.unique(np.concatenate(cons), axis=0)
        plans[j]['stats']['zone'] = int(plans[j]['zone'].sum())
        plans[j]['stats']['constraints'] = int(len(plans[j]['constraints']))
    return plans, geo


def covered_by_others(i, pts_local, cages, geo, R, T, rules):
    """pts_local (N,3) của phần i -> mảng bool (K,N): ở mỗi khung, điểm nằm trong lưới gốc của một phần khác."""
    K = len(R)
    Pm = posed(R[:, i], T[:, i], pts_local)
    cov = np.zeros((K, len(pts_local)), bool)
    for j, c in enumerate(cages):
        if j == i or not c['polys']:
            continue
        _, A, B, C, N = geo[j]
        if not len(A):
            continue
        Q = to_local(R[:, j], T[:, j], Pm).reshape(-1, 3)
        lo = c['W'][c['used']].min(0)
        hi = c['W'][c['used']].max(0)
        m = np.all((Q >= lo - 1e-6) & (Q <= hi + 1e-6), axis=1) & ~cov.reshape(-1)
        if not m.any():
            continue
        _, dist, side, _ = nearest_signed(Q[m], A, B, C, N)
        ins = (side < 0) & (dist < rules['qa']['inside_max_rel'] * c['diag'])
        flat = cov.reshape(-1)
        idx = np.nonzero(m)[0]
        flat[idx[ins]] = True
        cov = flat.reshape(K, -1)
    return cov


def plan_skirts(cages, geo, plans, profiles, rules, Rs, Ts, doc):
    """Váy cho vòng biên là khớp (>= joint_cover_min đỉnh bị phần khác che ở khung 0), dài theo luật, rút ngắn tới khi đầu
    váy bị che ở >= hidden_min các (đỉnh, khung) lấy mẫu; không đạt -> bỏ váy vòng đó."""
    sk = rules['skirt']
    if not sk.get('enabled', True):
        return
    for i, c in enumerate(cages):
        if not c['polys'] or 'translucent' in profiles[i]:
            continue
        if part_override(rules, doc, i).get('skirt') is False:
            continue
        loops = boundary_loops(c)
        W = c['W']
        for loop in loops:
            verts = []
            for a, b, p in loop:
                if a not in verts:
                    verts.append(a)
                if b not in verts:
                    verts.append(b)
            if len(loop) < 2:
                continue
            cov0 = covered_by_others(i, W[verts], cages, geo, Rs[:1], Ts[:1], rules)[0]
            if cov0.mean() < sk['joint_cover_min']:
                continue
            d = np.zeros((len(W), 3))
            for a, b, p in loop:
                e = W[b] - W[a]
                out = np.cross(e, c['pnorm'][p])
                out = out / max(np.linalg.norm(out), EPS)
                d[a] += out
                d[b] += out
            el = np.mean([np.linalg.norm(W[b] - W[a]) for a, b, p in loop])
            L = sk['len_edge'] * el
            L2 = sk['len_rel'] * c['diag']
            L = max(L, L2) if sk.get('combine', 'max') == 'max' else min(L, L2)
            dirs = {}
            for v in verts:
                dv = unit(unit(d[v]) - sk['tilt_in'] * c['vnorm'][v])
                dirs[v] = dv
            ok = False
            for _ in range(int(sk['shrink_steps']) + 1):
                tips = np.array([W[v] + L * dirs[v] for v in verts])
                cov = covered_by_others(i, tips, cages, geo, Rs, Ts, rules)
                if cov.mean() >= sk['hidden_min']:
                    ok = True
                    break
                L *= 0.5
            if ok:
                plans[i]['skirts'].append(dict(loop=[(int(a), int(b), int(p)) for a, b, p in loop], verts=verts,
                                               tips={int(v): (W[v] + L * dirs[v]) for v in verts}, length=float(L)))
                plans[i]['stats']['skirt_loops'] += 1
            else:
                plans[i]['stats']['skirt_dropped'] += 1


# ---------------------------------------------------------------- lồng cho Blender
def cage_arrays(cage, plan):
    """Ghép lồng + váy: verts (n,3), polys, poly_src (chỉ số mặt JSON), poly_skirt, poly_flip, poly_st (mỗi vòng),
    crease cạnh / sharp / crease đỉnh, mặt nạ đỉnh váy, đỉnh biên gốc."""
    W = cage['W']
    verts = [w for w in W]
    polys = [list(p) for p in cage['polys']]
    faces = cage['faces']
    poly_src = list(cage['poly_face'])
    poly_skirt = [False] * len(polys)
    poly_flip = list(cage['flip'])
    poly_st = []
    for p, corners in enumerate(cage['poly_corner']):
        f = faces[cage['poly_face'][p]]
        poly_st.append([ST[f['vc']][k] for k in corners])
    ecrease = {tuple(e): float(c) for e, c in zip(map(tuple, cage['edges']), cage['ecrease'])}
    esharp = {tuple(e): bool(s) for e, s in zip(map(tuple, cage['edges']), cage['esharp'])}
    vcrease = list(cage['vcrease'])
    skirt_v = [False] * len(W)
    for sk in plan['skirts']:
        newv = {}
        for v in sk['verts']:
            newv[v] = len(verts)
            verts.append(sk['tips'][v])
            vcrease.append(0.0)
            skirt_v.append(True)
            if len(cage['vfaces'][v]) == 1:
                vcrease[v] = 1.0
        for a, b, p in sk['loop']:
            polys.append([b, a, newv[a], newv[b]])
            poly_src.append(cage['poly_face'][p])
            poly_skirt.append(True)
            poly_flip.append(cage['flip'][p])
            st_p = poly_st[p]
            sa = st_p[cage['polys'][p].index(a)]
            sb = st_p[cage['polys'][p].index(b)]
            poly_st.append([sb, sa, sa, sb])
            key = (min(a, b), max(a, b))
            ecrease[key] = 1.0
            esharp[key] = True
    return dict(verts=np.array(verts, float), polys=polys, poly_src=poly_src, poly_skirt=poly_skirt, poly_flip=poly_flip,
                poly_st=poly_st, ecrease=ecrease, esharp=esharp, vcrease=np.array(vcrease, float),
                skirt_v=np.array(skirt_v, bool))


# ---------------------------------------------------------------- Blender
class BlenderCage:
    """Một đối tượng Blender cho lồng của một phần; đánh giá Subdivision ở mức L với toạ độ lồng bất kỳ."""

    def __init__(self, ca, name):
        import bpy
        self.bpy = bpy
        self.ca = ca
        n = len(ca['verts'])
        self.n = n
        me = bpy.data.meshes.new(name)
        me.from_pydata([tuple(v) for v in ca['verts']], [], ca['polys'])
        me.shade_smooth()
        me.attributes.new('cf', 'INT', 'FACE').data.foreach_set('value', np.arange(len(ca['polys']), dtype=np.int32))
        # 'prim' = chỉ số gói đã làm phẳng (srcFace), 'role' = 0 (mặt nền; đề can / mặt sau không vào lồng, váy = nền + cờ)
        me.attributes.new('prim', 'INT', 'FACE').data.foreach_set('value', np.array(ca['poly_src'], np.int32))
        me.attributes.new('role', 'INT', 'FACE').data.foreach_set('value', np.zeros(len(ca['polys']), np.int32))
        st = np.array([s for poly in ca['poly_st'] for s in poly], np.float32).reshape(-1)
        me.uv_layers.new(name='st').data.foreach_set('uv', st)
        ev = np.empty(len(me.edges) * 2, np.int32)
        me.edges.foreach_get('vertices', ev)
        ev = ev.reshape(-1, 2)
        crease = np.zeros(len(ev), np.float32)
        sharp = np.zeros(len(ev), bool)
        for i, (a, b) in enumerate(ev):
            k = (int(min(a, b)), int(max(a, b)))
            crease[i] = ca['ecrease'].get(k, 0.0)
            sharp[i] = ca['esharp'].get(k, False)
        me.attributes.new('crease_edge', 'FLOAT', 'EDGE').data.foreach_set('value', crease)
        a = me.attributes.get('sharp_edge') or me.attributes.new('sharp_edge', 'BOOLEAN', 'EDGE')
        a.data.foreach_set('value', sharp)
        me.attributes.new('crease_vert', 'FLOAT', 'POINT').data.foreach_set('value', ca['vcrease'].astype(np.float32))
        me.update()
        if me.polygons and len(me.polygons) != len(ca['polys']):
            raise RuntimeError('Blender bo mat cua long (%d != %d)' % (len(me.polygons), len(ca['polys'])))
        ob = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(ob)
        s = ob.modifiers.new('Subdivision', 'SUBSURF')
        s.quality = 3
        s.use_creases = True
        s.uv_smooth = 'NONE'
        s.boundary_smooth = 'PRESERVE_CORNERS'
        s.use_limit_surface = True
        s.use_custom_normals = False
        self.me, self.ob, self.mod = me, ob, s
        self.evals = 0

    def set_level(self, L):
        self.mod.levels = L
        self.mod.render_levels = L

    def load(self, X):
        """Đặt toạ độ lồng (chưa đánh giá; `evaluate_many` cập nhật depsgraph một lần cho mọi lồng)."""
        self.me.vertices.foreach_set('co', np.asarray(X, np.float32).reshape(-1))
        self.me.update()

    def read(self, dg, full=False):
        """Đọc mesh đã đánh giá: toạ độ (m,3) f32, hoặc (full) thêm đa giác / vòng / cf / st / pháp tuyến góc."""
        ev = self.ob.evaluated_get(dg)
        m = ev.to_mesh()
        try:
            co = np.empty(len(m.vertices) * 3, np.float32)
            m.vertices.foreach_get('co', co)
            co = co.reshape(-1, 3)
            self.evals += 1
            if not full:
                return co
            npoly = len(m.polygons)
            ls = np.empty(npoly, np.int32)
            lt = np.empty(npoly, np.int32)
            m.polygons.foreach_get('loop_start', ls)
            m.polygons.foreach_get('loop_total', lt)
            lv = np.empty(len(m.loops), np.int32)
            m.loops.foreach_get('vertex_index', lv)
            cf = np.empty(npoly, np.int32)
            m.attributes['cf'].data.foreach_get('value', cf)
            prim = np.empty(npoly, np.int32)
            m.attributes['prim'].data.foreach_get('value', prim)
            if not np.array_equal(prim, np.asarray(self.ca['poly_src'], np.int32)[cf]):
                raise RuntimeError('thuoc tinh prim cua da giac con khong khop cf')
            st = np.empty(len(m.loops) * 2, np.float32)
            m.uv_layers['st'].data.foreach_get('uv', st)
            cn = np.empty(len(m.loops) * 3, np.float32)
            m.corner_normals.foreach_get('vector', cn)
            return dict(co=co, ls=ls, lt=lt, lv=lv, cf=cf, st=st.reshape(-1, 2), cn=cn.reshape(-1, 3))
        finally:
            ev.to_mesh_clear()

    def evaluate(self, X, full=False):
        return _raise_if(evaluate_many([(self, X)], full)[0])

    def stencil(self):
        """K (m x n): toạ độ đánh giá = K @ toạ độ lồng (mỗi lần đánh giá lấy 3 cột qua 3 kênh x, y, z)."""
        return _raise_if(stencil_many([self])[0])

    def free(self):
        bpy = self.bpy
        bpy.data.objects.remove(self.ob, do_unlink=True)
        bpy.data.meshes.remove(self.me)


def _raise_if(r):
    if isinstance(r, Exception):
        raise r
    return r


def evaluate_many(pairs, full=False):
    """[(BlenderCage, toạ độ lồng)] -> kết quả `read` từng lồng; một lần cập nhật depsgraph cho mọi lồng (Blender đánh giá
    các đối tượng độc lập song song, rẻ hơn 2-3 lần so với cập nhật từng đối tượng). Mỗi đối tượng có modifier riêng nên
    kết quả không phụ thuộc lồng khác."""
    import bpy
    for bc, X in pairs:
        bc.load(X)
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    out = []
    for bc, _ in pairs:
        try:
            out.append(bc.read(dg, full))
        except Exception as e:          # lỗi một lồng không làm hỏng các lồng khác: phần tử là Exception
            out.append(e)
    return out


def stencil_many(bcs):
    """Ma trận stencil K của nhiều lồng: vòng r đặt véc-tơ cơ sở đỉnh 3r..3r+2 (kênh x, y, z) cho mọi lồng còn đỉnh.
    Lồng đọc lỗi -> phần tử là Exception."""
    Ks = [None] * len(bcs)
    nmax = max([bc.n for bc in bcs] or [0])
    for j0 in range(0, nmax, 3):
        pairs, who = [], []
        for b, bc in enumerate(bcs):
            if j0 >= bc.n or isinstance(Ks[b], Exception):
                continue
            X = np.zeros((bc.n, 3), np.float32)
            for c in range(3):
                if j0 + c < bc.n:
                    X[j0 + c, c] = 1.0
            pairs.append((bc, X))
            who.append(b)
        if not pairs:
            continue
        for b, out in zip(who, evaluate_many(pairs)):
            bc = bcs[b]
            if isinstance(out, Exception):
                Ks[b] = out
                continue
            out = out.astype(float)
            if Ks[b] is None:
                Ks[b] = np.zeros((len(out), bc.n))
            for c in range(3):
                if j0 + c < bc.n:
                    Ks[b][:, j0 + c] = out[:, c]
    return Ks


def child_topology(ev):
    """Đa giác con (m4 = vòng 4 góc) từ kết quả đánh giá: loops (Q,4) chỉ số vòng, cf (Q,)."""
    if not np.all(ev['lt'] == 4):
        raise RuntimeError('subdivision tra da giac khong phai tu giac')
    loops = ev['ls'][:, None] + np.arange(4)[None, :]
    return loops


def inflate_and_fix(K, ca, cage, plan, prof, rules, topo, stats):
    """Bơm thể tích từng đỉnh + sửa khớp, toàn bộ bằng numpy trên ma trận stencil K. Trả toạ độ lồng cuối."""
    inf = rules['inflate']
    n = len(ca['verts'])
    P0 = ca['verts'].copy()
    nW = len(cage['W'])
    if not inf.get('enabled', True):
        stats['inflate'] = dict(f=0.0, mode='off')
        return P0
    rows = np.arange(n)
    if not np.all(np.argmax(np.abs(K[:n]), axis=1) == rows):
        raise RuntimeError('hang stencil dinh long khong o vi tri 0..n-1')
    Klim = K[:n]
    try:
        P1 = np.linalg.solve(Klim, P0)
    except np.linalg.LinAlgError:
        P1 = np.linalg.lstsq(Klim, P0, rcond=None)[0]
    D = P1 - P0
    pinned = np.zeros(n, bool)
    pinned[nW:] = True                     # đỉnh váy
    pinned[:nW] |= cage['bnd'] | cage['nonman_v'] | cage['feature'] | cage['eye_v'] | plan['zone']
    # độ dài cạnh trung bình mỗi đỉnh lồng
    acc = np.zeros(n)
    cnt = np.zeros(n)
    for poly in ca['polys']:
        for a, b in zip(poly, poly[1:] + poly[:1]):
            L = np.linalg.norm(P0[a] - P0[b])
            acc[a] += L
            acc[b] += L
            cnt[a] += 1
            cnt[b] += 1
    avg = np.maximum(acc / np.maximum(cnt, 1), 1e-6)
    lim = np.where(pinned, inf['pinned_clamp_edge'], inf['free_clamp_edge']) * avg
    main = topo['tri_main']
    centre = cage['W'][cage['used']].mean(0) if cage['used'].any() else np.zeros(3)
    t_orig = fan(cage['polys'])
    v_orig = tri_volume(cage['W'], t_orig, centre) if len(t_orig) else 0.0

    def cage_at(f):
        fv = np.where(pinned, 1.0, f)
        d = fv[:, None] * D
        dl = np.linalg.norm(d, axis=1)
        over = dl > lim
        d[over] *= (lim[over] / dl[over])[:, None]
        return P0 + d

    def vol(C):
        S = K @ C
        return tri_volume(S, main, centre)

    v0 = vol(cage_at(0.0))
    fmax = inf['f_max']
    if abs(v_orig) < 1e-9 or v0 * v_orig <= 0:
        f = 0.5
        mode = 'half'
    else:
        sg = 1.0 if v_orig > 0 else -1.0
        if sg * v0 >= sg * v_orig:
            f, mode = 0.0, 'zero'
        elif sg * vol(cage_at(fmax)) <= sg * v_orig:
            f, mode = fmax, 'max'
        else:
            lo_f, hi_f = 0.0, fmax
            for _ in range(int(inf['bisect_iters'])):
                mid = 0.5 * (lo_f + hi_f)
                if sg * vol(cage_at(mid)) < sg * v_orig:
                    lo_f = mid
                else:
                    hi_f = mid
            f, mode = 0.5 * (lo_f + hi_f), 'bisect'
    f_vol = f
    # giới hạn Hausdorff: vị trí giới hạn của đỉnh lồng gốc không được xa đỉnh TMD quá haus_target_rel * đường chéo;
    # tăng f (thêm thể tích) tới khi đạt.
    used = cage['used']
    target = inf['haus_target_rel'] * max(cage['diag'], EPS)

    def vdist(C):
        S = K[:nW] @ C
        d = np.linalg.norm(S - P0[:nW], axis=1)
        return float(d[used].max()) if used.any() else 0.0

    d0 = vdist(cage_at(f))
    if d0 > target:
        best = (d0, f)
        for fc in np.linspace(f, max(1.0, f), 21)[1:]:
            dc = vdist(cage_at(fc))
            if dc < best[0]:
                best = (dc, fc)
            if dc <= target:
                break
        f = best[1]
        mode += '+haus'
    C = cage_at(f)
    v1 = vol(C)
    stats['inflate'] = dict(f=round(f, 4), f_vol=round(f_vol, 4), mode=mode, pinned=int(pinned[:nW].sum()),
                            free=int((~pinned[:nW]).sum()), vdist_rel=round(vdist(C) / max(cage['diag'], EPS), 4),
                            d_over_edge_max=round(float((np.linalg.norm(D, axis=1) / avg).max()), 3),
                            vol_ratio_plain=round(v0 / v_orig, 4) if v_orig else None,
                            vol_ratio=round(v1 / v_orig, 4) if v_orig else None)
    # sửa khớp: điểm ràng buộc (điểm biên phần khác nằm trong lưới gốc) phải nằm trong mặt remaster, cách >= margin.
    jf = rules['joint_fix']
    Q = plan['constraints']
    fixed = dict(constraints=int(len(Q)), violations_before=0, violations_after=0, iters=0, accepted=False)
    if jf.get('enabled', True) and len(Q) and len(main):
        movable = np.zeros(n, bool)
        movable[:nW] = cage['used'] & ~cage['bnd'] & ~cage['nonman_v'] & ~cage['eye_v']
        cap = np.minimum(jf['max_move_edge'] * avg, max(jf['max_move_rel'] * cage['diag'], jf['max_move_abs']))
        C0 = C.copy()
        best = None
        active = np.ones(len(Q), bool)
        main_v = np.unique(main)          # chỉ đỉnh của tam giác chính (không váy): chặn trên khoảng cách cho bộ lọc cặp
        for it in range(int(jf['iters']) + 1):
            S = K @ C
            A, B, Cc = S[main[:, 0]], S[main[:, 1]], S[main[:, 2]]
            N = unit(np.cross(B - A, Cc - A))
            Qa = Q[active]
            k, dist, side, lam = nearest_signed(Qa, A, B, Cc, N, V=S[main_v])
            need = side + jf['margin']
            bad = need > 0
            nb = int(bad.sum())
            if it == 0:
                fixed['violations_before'] = nb
                # chỉ đẩy ra ngoài: ràng buộc đã nằm sâu bên trong không thể bị vi phạm thêm -> bỏ khỏi vòng lặp
                keep = need > -4.0 * jf['margin']
                idx = np.nonzero(active)[0][keep]
                active[:] = False
                active[idx] = True
                k, side, lam, need, bad = k[keep], side[keep], lam[keep], need[keep], bad[keep]
            if best is None or nb < best[0]:
                best = (nb, C.copy(), it)
            if not bad.any() or it == int(jf['iters']):
                break
            delta = np.zeros((n, 3))
            hits = np.zeros(n)
            for qi in np.nonzero(bad)[0]:
                t = main[k[qi]]
                w = lam[qi, 0] * K[t[0]] + lam[qi, 1] * K[t[1]] + lam[qi, 2] * K[t[2]]
                w = np.where(movable, w, 0.0)
                s2 = float(np.dot(w, w))
                if s2 < 1e-12:
                    continue
                delta += np.outer(w * (need[qi] / s2), N[k[qi]])
                hits += (np.abs(w) > 1e-6)
            m = hits > 0
            if not m.any():
                break
            delta[m] /= hits[m][:, None]
            disp = C + jf['damping'] * delta - C0
            dl = np.linalg.norm(disp, axis=1)
            over = dl > cap
            disp[over] *= (cap[over] / dl[over])[:, None]
            C = C0 + disp
        fixed['violations_after'] = best[0]
        fixed['iters'] = best[2]
        fixed['accepted'] = best[0] < fixed['violations_before']
        C = best[1] if fixed['accepted'] else C0
        fixed['max_move'] = round(float(np.linalg.norm(C - C0, axis=1).max()), 3)
    stats['joint_fix'] = fixed
    return C


def subdivide_parts(items, level, rules):
    """Mọi phần của một mức trong một lượt Blender: items [(khoá, cage, plan, prof, tên)] -> {khoá: (sub, stats) hoặc
    Exception}. Ba bước dùng chung một lần cập nhật depsgraph cho mọi lồng: đánh giá lồng gốc (topology), ma trận stencil
    (véc-tơ cơ sở), đánh giá lồng cuối sau bơm / sửa khớp (numpy, từng phần). Lỗi một phần chỉ loại phần đó."""
    out = {}
    live = []
    try:
        for key, cage, plan, prof, name in items:
            try:
                ca = cage_arrays(cage, plan)
                bc = BlenderCage(ca, name)
                live.append(dict(key=key, cage=cage, plan=plan, prof=prof, ca=ca, bc=bc))
                bc.set_level(level)
            except Exception as e:
                out[key] = e
        evs = evaluate_many([(x['bc'], x['ca']['verts']) for x in live], full=True)
        ok = []
        for x, ev0 in zip(live, evs):
            try:
                _raise_if(ev0)
                x['loops'] = child_topology(ev0)
                cf = ev0['cf']
                skirt_poly = np.array(x['ca']['poly_skirt'], bool)[cf]
                lv = ev0['lv'][x['loops']]
                x['tri_main'] = np.concatenate([lv[~skirt_poly][:, [0, 1, 2]], lv[~skirt_poly][:, [0, 2, 3]]])
                x['ev0'] = ev0
                ok.append(x)
            except Exception as e:
                out[x['key']] = e
        Ks = stencil_many([x['bc'] for x in ok])
        fin = []
        for x, K in zip(ok, Ks):
            t = time.perf_counter()
            ca = x['ca']
            try:
                _raise_if(K)
                rs = np.abs(K.sum(1) - 1.0).max() if K is not None else 0.0
                stats = dict(level=level, cage_verts=len(ca['verts']), cage_polys=len(ca['polys']),
                             child_polys=len(x['ev0']['cf']), stencil_rowsum_err=float(rs),
                             skirt_polys=int(sum(ca['poly_skirt'])))
                x['C'] = inflate_and_fix(K, ca, x['cage'], x['plan'], x['prof'], rules, dict(tri_main=x['tri_main']),
                                         stats)
                stats['seconds_numpy'] = round(time.perf_counter() - t, 3)
                x['stats'] = stats
                fin.append(x)
            except Exception as e:
                out[x['key']] = e
        evs = evaluate_many([(x['bc'], x['C']) for x in fin], full=True)
        for x, ev in zip(fin, evs):
            x['stats']['blender_evals'] = x['bc'].evals
            if isinstance(ev, Exception):
                out[x['key']] = ev
                continue
            if not np.array_equal(ev['lv'], x['ev0']['lv']) or not np.array_equal(ev['cf'], x['ev0']['cf']):
                out[x['key']] = RuntimeError('topology thay doi giua hai lan danh gia')
                continue
            out[x['key']] = (dict(ev=ev, loops=x['loops'], ca=x['ca']), x['stats'])
    finally:
        for x in live:
            x['bc'].free()
    return out


def subdivide_part(cage, plan, prof, level, rules, name):
    """Một phần (dùng khi chạy lại riêng lẻ): lồng -> (mesh con mức `level`, thống kê). Gọi trong Blender."""
    r = subdivide_parts([(0, cage, plan, prof, name)], level, rules)[0]
    if isinstance(r, Exception):
        raise r
    return r


# ---------------------------------------------------------------- phát lưới (SPEC §3.2 / §3.5.2)
def weights(vc, s, t):
    s = np.asarray(s, float)
    t = np.asarray(t, float)
    if vc == 3:
        return np.stack([1.0 - s - t, s, t], -1)
    return np.stack([(1 - s) * (1 - t), s * (1 - t), (1 - s) * t, s * t], -1)


def quant_st(st, vc):
    """(s,t) f -> u16 S,T (làm tròn, kẹp; tam giác S+T <= 65535)."""
    S = np.clip(np.round(st[:, 0] * 65535.0), 0, 65535).astype(np.int64)
    T = np.clip(np.round(st[:, 1] * 65535.0), 0, 65535).astype(np.int64)
    if vc == 3:
        over = S + T > 65535
        T[over] = 65535 - S[over]
    return S, T


def remap_st(Sb, Tb, fb, fd, wid):
    """Tham số góc của mặt nền fb -> mặt đề can / mặt sau fd (cùng tập đỉnh hàn): trọng số theo đỉnh rồi
    s' = w1 (+ w3), t' = w2 (+ w3). Chính xác với mọi hoán vị đối xứng của tứ giác và mọi hoán vị tam giác."""
    wb = weights(fb['vc'], Sb / 65535.0, Tb / 65535.0)
    per_v = {}
    for k in range(fb['vc']):
        per_v[fb['wv'][k]] = per_v.get(fb['wv'][k], 0.0) + wb[:, k]
    taken = set()
    wd = []
    for j in range(fd['vc']):
        v = fd['wv'][j]
        if v in per_v and v not in taken:
            wd.append(per_v[v])
            taken.add(v)
        else:
            wd.append(np.zeros(len(Sb)))
    wd = np.stack(wd, -1)
    if fd['vc'] == 3:
        s, t = wd[:, 1], wd[:, 2]
    else:
        s, t = wd[:, 1] + wd[:, 3], wd[:, 2] + wd[:, 3]
    return quant_st(np.stack([s, t], -1), fd['vc'])


def near_vertex(f, S, T):
    w = weights(f['vc'], S / 65535.0, T / 65535.0)
    k = np.argmax(w - 1e-9 * np.arange(f['vc'])[None, :], axis=1)
    return np.array(f['vidx'], int)[k]


CORNER_DT = np.dtype([('pos', '<u4'), ('n', '<f4', (3,)), ('face', '<u4'), ('S', '<u2'), ('T', '<u2'), ('near', '<u2'),
                      ('role', 'u1')])


class Emitter:
    """Gom góc ứng viên theo lô (mỗi lần dùng một ứng viên) + tam giác; `finish` khử trùng góc theo khoá đầy đủ
    (pos, n, srcFace, S, T, near, role), sắp tam giác theo srcFace (ổn định) và đánh số góc / vị trí theo lần dùng đầu."""

    def __init__(self):
        self.recs, self.tris, self.tface, self.tflag = [], [], [], []
        self.n = 0

    def corners(self, pos, n, face, S, T, near, role):
        k = len(pos)
        r = np.zeros(k, CORNER_DT)
        r['pos'] = pos
        r['n'] = np.asarray(n, np.float32).reshape(-1, 3)
        r['face'] = face
        r['S'] = S
        r['T'] = T
        r['near'] = near
        r['role'] = role
        self.recs.append(r)
        ids = np.arange(self.n, self.n + k)
        self.n += k
        return ids

    def record(self, ids):
        allr = np.concatenate(self.recs) if len(self.recs) > 1 else self.recs[0]
        self.recs = [allr]
        return allr[ids]

    def tri(self, idx3, face, flag=0):
        idx3 = np.asarray(idx3, np.int64).reshape(-1, 3)
        self.tris.append(idx3)
        self.tface.append(np.broadcast_to(np.asarray(face, np.int64), (len(idx3),)))
        self.tflag.append(np.broadcast_to(np.asarray(flag, np.uint8), (len(idx3),)))

    def finish(self, P, level):
        if not self.n or not self.tris:
            return empty_part()
        rec = np.concatenate(self.recs)
        keyv = np.ascontiguousarray(rec).view(np.dtype((np.void, rec.dtype.itemsize)))
        _, first, inv = np.unique(keyv, return_index=True, return_inverse=True)
        inv = inv.reshape(-1)
        tface = np.concatenate(self.tface)
        order = np.argsort(tface, kind='stable')
        tris = inv[np.concatenate(self.tris)[order]]
        tflag = np.concatenate(self.tflag)[order].astype(np.uint8)
        # số góc theo lần dùng đầu tiên trong danh sách tam giác đã sắp
        flat = tris.reshape(-1)
        u, fi = np.unique(flat, return_index=True)
        cu = u[np.argsort(fi, kind='stable')]
        remap = np.full(len(first), -1, np.int64)
        remap[cu] = np.arange(len(cu))
        cr = rec[first[cu]]
        cpos = cr['pos'].astype(np.int64)
        pu, pfi = np.unique(cpos, return_index=True)
        pord = pu[np.argsort(pfi, kind='stable')]
        premap = np.full(len(P), -1, np.int64)
        premap[pord] = np.arange(len(pord))
        return dict(level=int(level), mode=1,
                    pos=np.asarray(P, np.float32)[pord].reshape(-1, 3),
                    corner_pos=premap[cpos].astype(np.uint32),
                    corner_n=np.ascontiguousarray(cr['n'], np.float32).reshape(-1, 3),
                    corner_face=cr['face'].astype(np.uint32),
                    corner_st=np.stack([cr['S'], cr['T']], 1).astype(np.uint16),
                    corner_near=cr['near'].astype(np.uint16),
                    corner_role=cr['role'].astype(np.uint8),
                    tri=remap[tris].astype(np.uint32).reshape(-1, 3),
                    tri_flag=tflag)


def emit_identity(cage):
    """L0: bản sao hình gốc (mode 1 identity): vị trí = đỉnh TMD, góc ở (s,t) ∈ {0,1}, near = chính đỉnh, tam giác (2,1,0)
    (+ (1,2,3)) như TmdObjLoader; đề can / mặt sau dùng lại đúng tam giác của mặt nền (cùng chỉ số vị trí)."""
    em = Emitter()
    faces = cage['faces']
    zero = np.zeros(3, np.float32)

    def own_n(f, k):
        return f['n_tmd'][k].astype(np.float32) if f['n_tmd'] is not None else zero

    base_tris = {}
    for f in faces:
        if f['layer'] in ('decal', 'back') and faces[f['base']]['layer'] == 'base':
            continue
        role = ROLE_BASE if f['layer'] in ('base', 'skip') else (ROLE_DECAL if f['layer'] == 'decal' else ROLE_BACK)
        vc = f['vc']
        st = np.array(ST[vc]) * 65535
        ids = em.corners(f['vidx'], [own_n(f, k) for k in range(vc)], np.full(vc, f['k']), st[:, 0], st[:, 1],
                         f['vidx'], np.full(vc, role))
        tl = [(2, 1, 0)] + ([(1, 2, 3)] if vc == 4 else [])
        base_tris[f['k']] = tl
        em.tri(ids[np.array(tl)], f['k'])
    for f in faces:
        if not (f['layer'] in ('decal', 'back') and faces[f['base']]['layer'] == 'base'):
            continue
        b = faces[f['base']]
        role = ROLE_DECAL if f['layer'] == 'decal' else ROLE_BACK
        js = [f['wv'].index(b['wv'][k]) if b['wv'][k] in f['wv'] else 0 for k in range(b['vc'])]
        st = np.array([ST[f['vc']][j] for j in js]) * 65535
        ids = em.corners([b['vidx'][k] for k in range(b['vc'])], [own_n(f, j) for j in js],
                         np.full(b['vc'], f['k']), st[:, 0], st[:, 1], [f['vidx'][j] for j in js],
                         np.full(b['vc'], role))
        tl = np.array(base_tris[b['k']])
        if role == ROLE_BACK:
            tl = tl[:, [0, 2, 1]]
        em.tri(ids[tl], f['k'])
    return em.finish(cage['V'], 0)


def emit_subdiv(cage, sub, prof, rules, level, normals_blend=None):
    """Mesh con -> mảng phần (SPEC §3.8). Tam giác con theo chiều SC của gói (đảo nếu lồng bị lật); đề can / mặt sau dùng
    lại tam giác con của mặt nền (cùng chỉ số vị trí => trùng bit)."""
    ev, loops, ca = sub['ev'], sub['loops'], sub['ca']
    faces = cage['faces']
    nf = len(faces)
    blend = 'hair' in prof
    bw = float(rules['normals']['blend_weight'] if normals_blend is None else normals_blend) if blend else 1.0
    em = Emitter()
    cf = ev['cf']
    pf = np.array(ca['poly_src'], np.int64)[cf]
    flip = np.array(ca['poly_flip'], bool)[cf]
    skirt = np.array(ca['poly_skirt'], bool)[cf]
    L = loops.copy()
    L[flip] = L[flip][:, [0, 3, 2, 1]]
    Q = len(L)
    vc = np.array([f['vc'] for f in faces], np.int64)[pf]
    st = ev['st'][L].astype(float).reshape(-1, 2)
    S = np.clip(np.round(st[:, 0] * 65535.0), 0, 65535).astype(np.int64)
    T = np.clip(np.round(st[:, 1] * 65535.0), 0, 65535).astype(np.int64)
    tri_c = np.repeat(vc == 3, 4)
    over = tri_c & (S + T > 65535)
    T[over] = 65535 - S[over]
    s, t = S / 65535.0, T / 65535.0
    w = np.where(tri_c[:, None], np.stack([1 - s - t, s, t, np.zeros_like(s)], -1),
                 np.stack([(1 - s) * (1 - t), s * (1 - t), (1 - s) * t, s * t], -1))
    fpc = np.repeat(pf, 4)
    vtab = np.zeros((nf, 4), np.int64)
    ntab = np.zeros((nf, 4, 3))
    lit = np.zeros(nf, bool)
    for f in faces:
        vtab[f['k'], :f['vc']] = f['vidx']
        if f['n_tmd'] is not None:
            ntab[f['k'], :f['vc']] = f['n_tmd']
            lit[f['k']] = True
    kmax = np.argmax(w - 1e-9 * np.arange(4)[None, :], axis=1)
    near = vtab[fpc, kmax]
    n = ev['cn'][L].astype(float).reshape(-1, 3)
    if blend:
        nt = np.einsum('ck,ckj->cj', w, ntab[fpc])
        ok = lit[fpc] & (np.linalg.norm(nt, axis=1) > 1e-6)
        nb = unit(bw * n + (1.0 - bw) * unit(nt))
        n = np.where(ok[:, None], nb, n)
    ids = em.corners(ev['lv'][L].reshape(-1), n, fpc, S, T, near, np.zeros(Q * 4, np.uint8)).reshape(Q, 4)
    tq = np.stack([ids[:, [0, 1, 2]], ids[:, [0, 2, 3]]], 1).reshape(-1, 3)
    tf = np.repeat(pf, 2)
    tsk = np.repeat(skirt, 2)
    em.tri(tq, tf, np.where(tsk, FLAG_SKIRT, 0))
    # đề can / mặt sau: dùng lại tam giác con không váy của mặt nền
    for f in faces:
        if f['layer'] not in ('decal', 'back') or f['base'] < 0:
            continue
        b = faces[f['base']]
        sel = (tf == b['k']) & ~tsk
        if not sel.any():
            continue
        tl = tq[sel]
        used = np.unique(tl)
        r = em.record(used)
        Sd, Td = remap_st(r['S'].astype(float), r['T'].astype(float), b, f, cage['wid'])
        nd = near_vertex(f, Sd.astype(float), Td.astype(float))
        role = ROLE_DECAL if f['layer'] == 'decal' else ROLE_BACK
        nn = r['n'] if role == ROLE_DECAL else -r['n']
        nid = em.corners(r['pos'], nn, np.full(len(used), f['k']), Sd, Td, nd, np.full(len(used), role))
        m = nid[np.searchsorted(used, tl)]
        if role == ROLE_BACK:
            m = m[:, [0, 2, 1]]
        em.tri(m, f['k'])
    return em.finish(ev['co'], level)


def empty_part():
    return dict(level=0, mode=0, pos=np.zeros((0, 3), np.float32), corner_pos=np.zeros(0, np.uint32),
                corner_n=np.zeros((0, 3), np.float32), corner_face=np.zeros(0, np.uint32),
                corner_st=np.zeros((0, 2), np.uint16), corner_near=np.zeros(0, np.uint16),
                corner_role=np.zeros(0, np.uint8), tri=np.zeros((0, 3), np.uint32), tri_flag=np.zeros(0, np.uint8))


# ---------------------------------------------------------------- npz xác định
FIELDS = ('pos', 'corner_pos', 'corner_n', 'corner_face', 'corner_st', 'corner_near', 'corner_role', 'tri', 'tri_flag')


def npz_arrays(parts, level, src_face_counts):
    """parts: [partmesh] -> dict tên -> mảng (thứ tự cố định)."""
    out = {}
    n = len(parts)
    out['format'] = np.array([1], np.uint8)
    out['level'] = np.array([level], np.uint8)
    out['partCount'] = np.array([n], np.uint16)
    out['srcFaceCount'] = np.array(src_face_counts, np.uint32)
    out['mode'] = np.array([p['mode'] for p in parts], np.uint8)
    out['partLevel'] = np.array([p['level'] for p in parts], np.uint8)
    for i, p in enumerate(parts):
        for k in FIELDS:
            out['p%03d_%s' % (i, k)] = np.ascontiguousarray(p[k])
        out['p%03d_mode' % i] = np.array([p['mode']], np.uint8)
    return out


def write_npz(path, arrays):
    """npz xác định: zip STORED, ngày giờ 1980-01-01, thứ tự khoá như dict; ghi .tmp rồi đổi tên."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:
        for k, a in arrays.items():
            b = io.BytesIO()
            np.lib.format.write_array(b, np.ascontiguousarray(a), allow_pickle=False)
            zi = zipfile.ZipInfo(k + '.npy', date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_STORED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, b.getvalue())
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(buf.getvalue())
    os.replace(tmp, path)
    return hashlib.sha1(buf.getvalue()).hexdigest()


# ---------------------------------------------------------------- mô hình
def prepare_model(doc, rules):
    """Phần numpy trước Blender: phân tích, định hướng lồng, hồ sơ, crease cho mọi phần -> (cages, profiles)."""
    cages = [analyse_part(p, rules) for p in doc['parts']]
    for c in cages:
        if c['polys']:
            orient_cage(c)
    profiles = detect_profiles(doc, cages, rules)
    R0, T0 = kf0_pose(doc)
    for i, c in enumerate(cages):
        if c['polys']:
            compute_creases(c, profiles[i], rules, R0[0, i])
    return cages, profiles


def process_model(doc, rules, anims, levels=None, log=None, name=None):
    """Dựng ứng viên L0 / L1 / L2 cho mọi phần (trong Blender). Trả dict(parts=[{level: partmesh}], info=[...], stats)."""
    import bpy  # noqa: F401  (bảo đảm đang chạy trong Blender)
    t0 = time.perf_counter()
    levels = list(levels or rules.get('levels', [1, 2]))
    name = name or doc.get('name', 'model')
    cages, profiles = prepare_model(doc, rules)
    R, T = all_poses(doc, anims)
    Rs, Ts = all_poses(doc, anims, rules['sampling']['plan_keyframes'])
    t1 = time.perf_counter()
    plans, geo = plan_joints(cages, R, T, rules)
    plan_skirts(cages, geo, plans, profiles, rules, Rs, Ts, doc)
    t2 = time.perf_counter()
    parts, info, lmaxs, ovs = [], [], [], []
    for i, c in enumerate(cages):
        cand = {}
        ov = part_override(rules, doc, i)
        st = dict(index=i, name=c['name'], profile=sorted(profiles[i]), tr_frac=round(c['tr_frac'], 3),
                  faces=len(c['faces']), cage_polys=len(c['polys']), welded=int(c['nv'] - len(c['W'])),
                  layers={k: sum(1 for f in c['faces'] if f['layer'] == k) for k in ('base', 'decal', 'back', 'skip')},
                  plan=plans[i]['stats'], levels={}, reason_l0=None)
        parts.append(cand)
        info.append(st)
        ovs.append(ov)
        if not c['faces'] or c['nv'] == 0:
            cand[0] = empty_part()
            st['reason_l0'] = 'khong co mat'
            lmaxs.append(0)
            continue
        cand[0] = emit_identity(c)
        if c.get('crease_stats'):
            st['creases'] = c['crease_stats']
        lmax = max(levels) if levels else 0
        if 'translucent' in profiles[i]:
            lmax = 0
            st['reason_l0'] = 'trong mo >= %.0f%%' % (100 * rules['translucent_l0_frac'])
        if 'weapon' in profiles[i]:
            lmax = min(lmax, int(rules['profiles']['weapon_level_max']))
        if 'level_max' in ov:
            lmax = min(lmax, int(ov['level_max']))
        if not c['polys']:
            lmax = 0
            st['reason_l0'] = 'khong co mat nen hop le'
        lmaxs.append(lmax)
    t3 = time.perf_counter()
    tb = {}
    for L in levels:                       # mọi phần của một mức trong một lượt Blender (xem subdivide_parts)
        if L <= 0:
            continue
        tl = time.perf_counter()
        items = [(i, cages[i], plans[i], profiles[i], '%s_p%02d_L%d' % (name, i, L))
                 for i in range(len(cages)) if 0 < L <= lmaxs[i]]
        res = subdivide_parts(items, L, rules) if items else {}
        for i, *_ in items:
            r = res.get(i, RuntimeError('khong co ket qua'))
            try:
                sub, sst = _raise_if(r)
                parts[i][L] = emit_subdiv(cages[i], sub, profiles[i], rules, L, ovs[i].get('normals_blend'))
                sst['tris'] = int(len(parts[i][L]['tri']))
                info[i]['levels'][L] = sst
            except Exception as e:  # lỗi một phần -> phần đó dùng mức thấp hơn
                info[i]['levels'][L] = dict(error='%s: %s' % (type(e).__name__, e))
        tb[str(L)] = round(time.perf_counter() - tl, 3)
    t4 = time.perf_counter()
    stats = dict(seconds=dict(analyse=round(t1 - t0, 3), plan=round(t2 - t1, 3), identity=round(t3 - t2, 3),
                              subdivide=round(t4 - t3, 3), subdivide_level=tb, total=round(t4 - t0, 3)),
                 keyframes=int(len(R)), keyframes_plan=int(len(Rs)), anims=[a['path'] for a in anims])
    return dict(parts=parts, info=info, stats=stats, profiles=[sorted(p) for p in profiles])


# ---------------------------------------------------------------- mô hình tổng hợp + tự kiểm (không cần dữ liệu game)
def _quad(c, n, a, w, h):
    """4 góc TMD (thứ tự Z: (0,0),(1,0),(0,1),(1,1)) của hình chữ nhật tâm c, pháp tuyến ngoài n, trục a; chiều SC (2,1,0)
    hướng ra ngoài <=> A x B = -n với vị trí = c + (s-½)·w·A + (t-½)·h·B (B = A x n)."""
    n = unit(np.asarray(n, float))
    A = unit(np.asarray(a, float))
    B = np.cross(A, n)
    return [c + (s - 0.5) * w * A + (t - 0.5) * h * B for s, t in ((0, 0), (1, 0), (0, 1), (1, 1))]


def synth_model():
    """Mô hình tổng hợp theo lược đồ export_tmd.py (không phải dữ liệu Sony): phần 0 = hộp kín 40x60x30 có một mặt đề can
    (cùng 4 đỉnh, tham số xoay 90°, texel trong suốt 50%) và một mặt sau (tham số lật) ở mặt trước; phần 1 = hộp hở đáy
    24x30x20 đặt chồng lên đỉnh phần 0 (vòng biên đáy nằm trong phần 0 = khớp). Pháp tuyến TMD = hướng từ tâm hộp (mịn)."""
    def box(size, open_bottom=False):
        sx, sy, sz = size
        verts, faces = [], []
        sides = [((1, 0, 0), (0, 0, 1), sz, sy, sx / 2), ((-1, 0, 0), (0, 0, -1), sz, sy, sx / 2),
                 ((0, 0, 1), (-1, 0, 0), sx, sy, sz / 2), ((0, 0, -1), (1, 0, 0), sx, sy, sz / 2),
                 ((0, -1, 0), (1, 0, 0), sx, sz, sy / 2)]
        if not open_bottom:
            sides.append(((0, 1, 0), (1, 0, 0), sx, sz, sy / 2))
        for n, a, w, h, d in sides:
            q = _quad(np.array(n, float) * d, n, a, w, h)
            vid = []
            for p in q:
                p = tuple(np.round(p, 6))
                if p not in verts:
                    verts.append(p)
                vid.append(verts.index(p))
            faces.append((vid, n))
        return np.array(verts, float), faces

    def face_rec(k, V, vid, n, uv, transp=0.0, textured=True):
        P = V[vid]
        nn = unit(P - V.mean(0))
        return dict(prim=k, vidx=list(vid), loop=[0, 2, 3, 1], quad=True, textured=textured, translucent=False, lit=True,
                    coloured=False, normals=np.round(nn, 6).tolist(), colours=None,
                    geo_normal=(np.asarray(n, float) * 100.0).tolist(), uv=uv, tpage='0019', clut='5ca4',
                    transp_frac=transp, layer='base')
    parts = []
    V0, f0 = box((40.0, 60.0, 30.0))
    faces = [face_rec(k, V0, vid, n, [[4 * k, 0], [4 * k + 3, 0], [4 * k, 3], [4 * k + 3, 3]])
             for k, (vid, n) in enumerate(f0)]
    vid, n = f0[2]                                        # mặt trước (+z)
    faces.append(face_rec(len(faces), V0, [vid[1], vid[3], vid[0], vid[2]], n, [[40, 8], [47, 8], [40, 15], [47, 15]],
                          transp=0.5))
    faces.append(face_rec(len(faces), V0, [vid[1], vid[0], vid[3], vid[2]], -np.asarray(n, float),
                          [[50, 8], [57, 8], [50, 15], [57, 15]]))
    parts.append((V0, faces, [0.0, 0.0, 0.0]))
    V1, f1 = box((24.0, 30.0, 20.0), open_bottom=True)
    faces = [face_rec(k, V1, vid, n, [[4 * k, 20], [4 * k + 3, 20], [4 * k, 23], [4 * k + 3, 23]])
             for k, (vid, n) in enumerate(f1)]
    parts.append((V1, faces, [0.0, -40.0, 0.0]))
    out = []
    for i, (V, faces, tr) in enumerate(parts):
        out.append(dict(index=i, name='synth_%d' % i, verts=V.tolist(), faces=faces,
                        kf0_matrix=np.eye(3).tolist(), kf0_trans=tr, kf0_rot_psx=[0, 0, 0]))
    return dict(name='synth', kind='synthetic', source={}, parts=out, atlas_size=[64, 32], coord='tmd_local')


def selftest():
    """Tự kiểm phần numpy (không cần Blender / dữ liệu game): hàn đỉnh + lớp + định hướng + crease trên mô hình tổng hợp,
    remap_st chính xác, điểm gần nhất, L0 identity, npz xác định. Trả 0 = đạt, 1 = lỗi."""
    errs = []
    rules = load_rules()
    doc = synth_model()
    cages, profiles = prepare_model(doc, rules)
    c0, c1 = cages
    lay = [f['layer'] for f in c0['faces']]
    if lay.count('base') != 6 or lay.count('decal') != 1 or lay.count('back') != 1:
        errs.append('lop %s' % lay)
    if c0['bnd'].any() or any(c0['flip']):
        errs.append('hop kin: bien %d, lat %d' % (int(c0['bnd'].sum()), sum(c0['flip'])))
    if len(boundary_loops(c1)) != 1 or len(boundary_loops(c1)[0]) != 4:
        errs.append('vong bien phan 1 %s' % [len(x) for x in boundary_loops(c1)])
    if 'face' not in profiles[0]:
        errs.append('ho so phan 0 %s' % sorted(profiles[0]))
    exp = min(rules['crease']['boxy_hi_max'], rules['crease']['boxy_hi_base'] + rules['crease']['boxy_hi_add'] *
              (90.0 - rules['crease']['boxy_hi_angle']) / rules['crease']['boxy_hi_span'])
    inner = np.array([len(p) == 2 for p in c1['edge_polys']])
    if not np.allclose(c1['ecrease'][inner], exp):
        errs.append('crease hop %s != %.3f' % (np.unique(c1['ecrease'][inner]), exp))
    # gói không thấy: tứ giác hàn hai góc chéo 1-2 (cả hai tam giác SC suy biến) -> 'skip'; hàn 0-3 vẫn thấy
    Vt = [[0, 0, 0], [10, 0, 0], [0, 10, 0], [10, 10, 0]]
    ft = dict(prim=0, quad=True, loop=[0, 2, 3, 1], textured=False, translucent=False, lit=False, normals=None,
              geo_normal=[0, 0, -1])
    pt = analyse_part(dict(verts=Vt, faces=[dict(ft, vidx=[0, 1, 1, 3]), dict(ft, prim=1, vidx=[0, 1, 2, 0])]), rules)
    if [f['layer'] for f in pt['faces']] != ['skip', 'base']:
        errs.append('goi khong thay %s' % [f['layer'] for f in pt['faces']])
    # remap_st: điểm (s,t) của mặt nền -> mặt đề can / mặt sau cho cùng vị trí
    rng = np.random.default_rng(5)
    fb = c0['faces'][2]
    for fd in c0['faces'][6:]:
        S = np.round(rng.uniform(0, 1, 64) * 65535)
        T = np.round(rng.uniform(0, 1, 64) * 65535)
        Sd, Td = remap_st(S, T, fb, fd, c0['wid'])
        pb = weights(4, S / 65535, T / 65535) @ c0['V'][fb['vidx']]
        pd = weights(4, Sd / 65535, Td / 65535) @ c0['V'][fd['vidx']]
        if np.abs(pb - pd).max() > 1e-3:
            errs.append('remap_st %s %.4g' % (fd['layer'], np.abs(pb - pd).max()))
    # điểm gần nhất / phía trong
    t, A, B, C, N = part_tris(c0)
    _, dist, side, _ = nearest_signed(np.array([[0.0, 0, 0], [0, 0, 40], [19.0, 29, 14]]), A, B, C, N)
    if not (side[0] < 0 and side[1] > 0 and side[2] < 0 and abs(dist[1] - 25.0) < 1e-9):
        errs.append('nearest_signed %s %s' % (dist, side))
    # L0 identity: đề can dùng lại đúng vị trí tam giác nền, mặt sau đảo chiều
    pm = emit_identity(c0)
    tf = pm['corner_face'][pm['tri'][:, 0]]
    tb = {tuple(sorted(pm['corner_pos'][x].tolist())) for x in pm['tri'][tf == 2]}
    for k in (6, 7):
        if {tuple(sorted(pm['corner_pos'][x].tolist())) for x in pm['tri'][tf == k]} != tb:
            errs.append('L0 de can %d' % k)
    # npz xác định
    sfc = [len(p['faces']) for p in doc['parts']]
    arr = npz_arrays([emit_identity(c) for c in cages], 0, sfc)
    tmp = os.path.join(os.environ.get('TEMP', '.'), 'remaster_core_selftest_%d.npz' % os.getpid())
    h1 = write_npz(tmp, arr)
    h2 = write_npz(tmp, npz_arrays([emit_identity(c) for c in prepare_model(doc, rules)[0]], 0, sfc))
    with open(tmp, 'rb') as f:
        h3 = hashlib.sha1(f.read()).hexdigest()
    os.remove(tmp)
    if not (h1 == h2 == h3):
        errs.append('npz khong xac dinh')
    import sys
    if 'PIL' in sys.modules:
        errs.append('PIL da duoc import')
    print('selftest remaster_core:', 'DAT' if not errs else 'LOI %s' % errs)
    return 0 if not errs else 1


if __name__ == '__main__':
    raise SystemExit(selftest())
