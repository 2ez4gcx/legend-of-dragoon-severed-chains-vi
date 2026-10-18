"""check_tex.py — kiểm tra atlas HD của một biến thể texture (gói P3, SPEC §3.6, §3.8) + tờ so sánh gốc | 4x.

Đọc <biến thể>/atlas.json, atlas_4x.png, atlas_2x.png (đầu ra tex/hd_atlas.py), JSON export (lược đồ export_tmd.py) và
TIM nguồn (game/files, lớp phủ vi/files thắng). Giải mã texel 1x LẠI TỪ ĐẦU từ ảnh + CLUT của TIM (không qua VRAM ảo của
islands.py) và tự raster theo tâm texel, nên đây là phép kiểm độc lập với bộ sinh. Kiểm:
  1. PNG: SHA-1 trùng atlas.json; RGBA 8 bit; w, h luỹ thừa 2 <= 2048, bằng atlas.json; 2x = (w/2, h/2).
  2. Quy ước alpha SPEC §3.6.1: A chỉ thuộc {0, 128, 255}; A = 0 thì RGB = 0; mọi điểm ảnh ngoài các hình đảo = 0.
  3. atlas_2x = một mức mip SPEC §3.6.3 của atlas_4x (cài lại độc lập).
  4. faceUv: đủ texturedFaceCount mặt, hữu hạn, trong [0, 1]; góc 4 của tam giác = (0, 0); mặt bỏ qua = 0.
     skippedFaces ĐÚNG bằng tập tính lại độc lập (bpp khác TIM, góc uv ngoài TIM, dải CLUT ngoài rect CLUT): bỏ nhầm
     một mặt hợp lệ thì lúc chạy mặt đó lấy mẫu atlasUv (0, 0) = khe trong suốt -> lỗ.
  5. Mỗi mặt: thuộc đúng một đảo, cùng CLUT với đảo; đa giác uv (theo điểm ảnh 4x) nằm trong hình của đảo và trong
     4 x bbox đảo; phép đặt đảo khớp uv gốc ((X - ox) / 4 + gốc_x == tu ĐÚNG từng góc). Hai hình đảo cách nhau >= 8 px.
  6. Mỗi đảo, trên texel có tâm nằm trong một mặt của đảo, đo ở điểm ảnh 4x chứa tâm texel (4x+2, 4y+2):
     - độ phủ khớp 1x >= 99.5 %;
     - STP đúng 100 % (texel đục: A = 128 khi STP = 1, 255 khi STP = 0);
     - trong suốt đúng 100 % (texel 0x0000 -> điểm ảnh (0, 0, 0, 0));
     - PSNR(trung bình khối 4x4 các điểm ảnh đục, màu gốc) >= psnr_min (28 dB); đảo 'nearest' (bộ sinh đã hạ dần
       esrgan -> scale4x -> nearest) phải >= 45 dB vì nearest giữ đúng màu.
  7. Như 6 (độ phủ >= 99.5 %, STP + trong suốt đúng 100 %) trên MỌI texel mặt của đảo có thể lấy mẫu lúc chạy (raster
     bảo thủ: tam giác uv đóng chạm ô texel; cài lại độc lập) — gồm cả đảo chỉ có mặt suy biến, không có texel tâm.
  Ghi <biến thể>/<tên thư mục biến thể>_tex.json (số liệu từng đảo). Exit 0 = đạt, 1 = lỗi.

Tờ so sánh (--sheet DIR; ảnh suy ra từ đĩa: chỉ ghi vào work/upscale/sc_remaster*, không commit):
  <tên>_dao_<n>.png    mỗi đảo một ô: gốc 1x phóng 4x | [esrgan thô | esrgan kẹp viền | scale4x khi bộ sinh chạy
                       --save-candidates] | atlas 4x đã chọn (texel ngoài mặt nạ đảo tối đi, trong suốt = ô cờ; nhãn
                       ghi PSNR từng cách, lấy từ work/candidates.json).
  <tên>_tongquan.png   theo bố cục TIM: gốc | [bản thử cũ --pilot] | mới 4x (ghép lại), viền uv mặt màu xanh;
                       kèm vùng phóng to (--zoom x0,y0,x1,y1 theo texel TIM, lặp lại được) — dùng để xem viền cổ áo /
                       cẳng tay của bản thử upscale_atlas.py (atlas_uv_top.png).

Cách gọi (từ gốc repo, PYTHONIOENCODING=utf-8):
  python tools/sc_remaster/qa/check_tex.py <thư mục biến thể> --export <export.json | thư mục> [--game game/files]
      [--psnr-min 28] [--sheet DIR] [--pilot <ảnh x4 cũ theo bố cục TIM>] [--zoom x0,y0,x1,y1 ...] [--label TEXT]
  python tools/sc_remaster/qa/check_tex.py selftest [--work DIR]
      mô hình + TIM tổng hợp (không phải dữ liệu Sony): dựng bằng hd_atlas.py --no-ai, phải đạt; 12 lỗi gieo phải bị bắt;
      hai lần dựng ra cùng byte; không import PIL.
"""
import argparse
import hashlib
import json
import math
import os
import shutil
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TEX = os.path.normpath(os.path.join(HERE, '..', 'tex'))
sys.path.insert(0, TEX)
import islands as isl  # noqa: E402  (chỉ dùng đọc JSON / TIM / PNG; số liệu tính lại ở đây)

ROOT = isl.ROOT
PSNR_MIN = 28.0
COVER_MIN = 0.995
NEAREST_PSNR = 45.0   # nearest 4x giữ đúng màu gốc: trung bình khối = màu 1x
GUTTER_MIN = 8        # khe tối thiểu giữa hai hình đảo ở 4x (gói P3: khe 8 px)


# ---------------------------------------------------------------- giải mã độc lập từ TIM
def tim_decode(ex, clut, tu, tv):
    """Texel 16 bit từ ảnh + CLUT của TIM (không qua VRAM ảo). Ngoài TIM -> 0."""
    tim = ex.tim
    img = tim['img'].astype(np.int64)
    bpp = tim['bpp'] & 3
    tu = np.asarray(tu, np.int64)
    tv = np.asarray(tv, np.int64)
    out = np.zeros(tu.shape, np.int64)
    ok = (tu >= 0) & (tv >= 0) & (tu < ex.W) & (tv < ex.H)
    u, v = tu[ok], tv[ok]
    if bpp == 2:
        out[ok] = img[v, u]
        return out
    if bpp == 0:
        idx = (img[v, u // 4] >> (4 * (u % 4))) & 15
    else:
        idx = (img[v, u // 2] >> (8 * (u % 2))) & 255
    cx, cy = (clut & 0x3F) * 16, clut >> 6
    rx, ry, _, _ = ex.crect
    out[ok] = tim['clut'].astype(np.int64)[cy - ry, cx - rx + idx]
    return out


def c5to8(c):
    return (np.asarray(c, np.int64) * 255 + 15) // 31


def centre_texels(tuv, quad, W, H):
    """Texel có tâm trong một tam giác (2,1,0) / (1,2,3) đóng của mặt -> tập (tu, tv)."""
    out = set()
    tris = [(2, 1, 0)] + ([(1, 2, 3)] if quad else [])
    for t in tris:
        (ax, ay), (bx, by), (cx, cy) = [tuv[k] for k in t]
        area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if area == 0:
            continue
        for y in range(max(0, min(ay, by, cy)), min(H, max(ay, by, cy) + 1)):
            for x in range(max(0, min(ax, bx, cx)), min(W, max(ax, bx, cx) + 1)):
                px, py = x + 0.5, y + 0.5
                e0 = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
                e1 = (cx - bx) * (py - by) - (cy - by) * (px - bx)
                e2 = (ax - cx) * (py - cy) - (ay - cy) * (px - cx)
                if (e0 >= 0 and e1 >= 0 and e2 >= 0) if area > 0 else (e0 <= 0 and e1 <= 0 and e2 <= 0):
                    out.add((x, y))
    return out


def cons_texels(tuv, quad, W, H):
    """Texel mà tam giác ĐÓNG (2,1,0) / (1,2,3) của mặt chạm vào (ô nửa mở [x, x+1) x [y, y+1)) -> tập (tu, tv).
    Đây là mọi texel lúc chạy có thể lấy mẫu (texelFetch(floor(uv)), uv nội suy nằm trong tam giác uv); mặt suy biến
    (uv thẳng hàng) vẫn có texel. Cài lại bằng vòng Python + trục tách (SAT), độc lập với islands.raster_conservative."""
    out = set()
    tris = [(2, 1, 0)] + ([(1, 2, 3)] if quad else [])
    e = 1e-6
    for t in tris:
        P = [tuv[k] for k in t]
        xs = [p[0] for p in P]
        ys = [p[1] for p in P]
        axes = []
        for i in range(3):
            (ax, ay), (bx, by) = P[i], P[(i + 1) % 3]
            if (ax, ay) != (bx, by):
                axes.append((-(by - ay), bx - ax))
        for y in range(max(0, int(math.floor(min(ys)))), min(H - 1, int(math.floor(max(ys)))) + 1):
            for x in range(max(0, int(math.floor(min(xs)))), min(W - 1, int(math.floor(max(xs)))) + 1):
                sq = [(x, y), (x + 1 - e, y), (x, y + 1 - e), (x + 1 - e, y + 1 - e)]
                hit = True
                for nx, ny in axes:
                    tp = [px * nx + py * ny for px, py in P]
                    sp = [px * nx + py * ny for px, py in sq]
                    tol = 1e-9 * (abs(nx) + abs(ny))
                    if max(sp) < min(tp) - tol or min(sp) > max(tp) + tol:
                        hit = False
                        break
                if hit:
                    out.add((x, y))
    return out


def mip_ref(level):
    """SPEC §3.6.3 cho ảnh cạnh chẵn (cài lại bằng reshape, độc lập với hd_atlas.mip_down)."""
    h, w = level.shape[:2]
    blk = level.reshape(h // 2, 2, w // 2, 2, 4).transpose(0, 2, 1, 3, 4).reshape(h // 2, w // 2, 4, 4).astype(np.int64)
    a = blk[..., 3]
    transp = a < 64
    stp1 = (a >= 64) & (a < 192)
    t = transp.sum(-1)
    o = 4 - t
    s1 = stp1.sum(-1)
    rgb = np.where(~transp[..., None], blk[..., :3], 0).sum(2)
    keep = 2 * t < 4
    osafe = np.maximum(o, 1)
    out = np.zeros((h // 2, w // 2, 4), np.int64)
    out[..., :3] = np.where(keep[..., None], (rgb + (o // 2)[..., None]) // osafe[..., None], 0)
    out[..., 3] = np.where(keep, np.where(s1 >= o - s1, 128, 255), 0)
    return out.astype(np.uint8)


def pow2(v):
    return v >= 1 and (v & (v - 1)) == 0


# ---------------------------------------------------------------- kiểm
def check(variant_dir, export, game=None, psnr_min=PSNR_MIN, write=True):
    """-> (đạt?, báo cáo dict)."""
    errs = []
    with open(os.path.join(variant_dir, 'atlas.json'), 'rb') as f:
        doc = json.loads(f.read().decode('utf-8'))
    raw4 = open(os.path.join(variant_dir, 'atlas_4x.png'), 'rb').read()
    raw2 = open(os.path.join(variant_dir, 'atlas_2x.png'), 'rb').read()
    if hashlib.sha1(raw4).hexdigest() != doc['png']['atlas_4x']:
        errs.append('SHA-1 atlas_4x.png khac atlas.json')
    if hashlib.sha1(raw2).hexdigest() != doc['png']['atlas_2x']:
        errs.append('SHA-1 atlas_2x.png khac atlas.json')
    if raw4[25] != 6 or raw2[25] != 6 or raw4[24] != 8 or raw2[24] != 8:
        errs.append('PNG khong phai RGBA 8 bit')
    a4 = isl.png_read(raw4)
    a2 = isl.png_read(raw2)
    H4, W4 = a4.shape[:2]
    if (W4, H4) != (doc['w'], doc['h']) or not pow2(W4) or not pow2(H4) or W4 > 2048 or H4 > 2048:
        errs.append('kich thuoc 4x %dx%d sai (json %dx%d)' % (W4, H4, doc['w'], doc['h']))
    if a2.shape[:2] != (max(1, H4 // 2), max(1, W4 // 2)) or (doc['w2'], doc['h2']) != (a2.shape[1], a2.shape[0]):
        errs.append('kich thuoc 2x sai')
    # quy ước alpha
    A = a4[..., 3]
    bad_a = ~np.isin(A, (0, 128, 255))
    if bad_a.any():
        errs.append('alpha ngoai {0,128,255}: %d diem' % int(bad_a.sum()))
    if (a4[A == 0][:, :3] != 0).any():
        errs.append('diem trong suot co RGB != 0: %d' % int((a4[A == 0][:, :3] != 0).any(-1).sum()))
    if not np.isin(a2[..., 3], (0, 128, 255)).all() or (a2[a2[..., 3] == 0][:, :3] != 0).any():
        errs.append('2x sai quy uoc alpha')
    if W4 % 2 == 0 and H4 % 2 == 0 and not np.array_equal(mip_ref(a4), a2):
        errs.append('atlas_2x khac mip(4x): %d diem' % int((mip_ref(a4) != a2).any(-1).sum()))
    ex = isl.load_export(export, game)
    if doc['texturedFaceCount'] != ex.n_tex or len(doc['faceUv']) != ex.n_tex:
        errs.append('so mat co texture %d / %d != export %d' % (doc['texturedFaceCount'], len(doc['faceUv']), ex.n_tex))
    skipped = {s['g'] for s in doc.get('skippedFaces', [])}
    # mặt được phép bỏ qua (tính lại độc lập): bpp khác TIM, góc uv ngoài TIM, dải CLUT ngoài rect CLUT. Bỏ nhầm một
    # mặt hợp lệ = lỗ lúc chạy (faceHash != 0 nên runtime vẽ atlasUv (0,0) = khe trong suốt) -> phải bắt.
    want_skip = set()
    tim_bpp = ex.tim['bpp'] & 3
    crect = ex.crect
    for f in ex.faces:
        fb = f.tpage >> 7 & 3
        bad = fb != tim_bpp or any(not (0 <= u <= ex.W and 0 <= v <= ex.H) for u, v in f.tuv)
        if not bad and fb in (0, 1):
            cx, cy, n = (f.clut & 0x3F) * 16, f.clut >> 6, (16 if fb == 0 else 256)
            bad = crect is None or not (crect[0] <= cx and cx + n <= crect[0] + crect[2]
                                        and crect[1] <= cy < crect[1] + crect[3])
        if bad:
            want_skip.add(f.g)
    if skipped != want_skip:
        errs.append('mat bo qua sai: thua %s, thieu %s' % (sorted(skipped - want_skip)[:10], sorted(want_skip - skipped)[:10]))
    owner = {}
    covered = np.zeros((H4, W4), bool)
    face_by_g = {f.g: f for f in ex.faces}
    rects = []
    for e in doc['islands']:
        x, y, w, h = e['rect4x']
        if x < 0 or y < 0 or x + w > W4 or y + h > H4 or x % 4 or y % 4:
            errs.append('dao %d: hinh %s ngoai atlas / khong can 4' % (e['id'], e['rect4x']))
            continue
        if covered[y:y + h, x:x + w].any():
            errs.append('dao %d chong dao khac' % e['id'])
        covered[y:y + h, x:x + w] = True
        rects.append((e['id'], x, y, w, h))
        for g in e['faces']:
            if g in owner:
                errs.append('mat %d thuoc hai dao %d, %d' % (g, owner[g]['id'], e['id']))
            owner[g] = e
            f = face_by_g.get(g)
            # số liệu đảo giải mã bằng CLUT của đảo: mặt CLUT khác trong đảo sẽ bị đo sai màu -> phải bắt riêng
            if f is not None and f.clut != int(e['clut'], 16):
                errs.append('mat %d (CLUT %04x) nam trong dao %d CLUT %s' % (g, f.clut, e['id'], e['clut']))
    # khe giữa các đảo >= GUTTER_MIN điểm ảnh (mip §3.6.3 không trộn hai đảo)
    for i in range(len(rects)):
        ia, ax, ay, aw, ah = rects[i]
        for j in range(i):
            ib, bx, by, bw, bh = rects[j]
            if not (ax >= bx + bw + GUTTER_MIN or bx >= ax + aw + GUTTER_MIN or ay >= by + bh + GUTTER_MIN
                    or by >= ay + ah + GUTTER_MIN):
                errs.append('dao %d va %d cach nhau < %d diem anh' % (ib, ia, GUTTER_MIN))
    outside = a4[~covered]
    if outside.size and outside.any():
        errs.append('%d diem anh ngoai cac dao khac 0' % int(outside.any(-1).sum()))
    # faceUv
    fuv = doc['faceUv']
    report_islands = {}
    report_cons = {}
    for f in ex.faces:
        if f.g >= len(fuv):
            break
        c = np.array(fuv[f.g], np.float64)
        if c.shape != (4, 2) or not np.isfinite(c).all() or (c < 0).any() or (c > 1).any():
            errs.append('mat %d: faceUv sai %s' % (f.g, fuv[f.g]))
            continue
        if not f.quad and (c[3] != 0).any():
            errs.append('mat %d: goc 4 cua tam giac != 0' % f.g)
        if f.g in skipped:
            if (c != 0).any():
                errs.append('mat %d bo qua nhung faceUv != 0' % f.g)
            continue
        e = owner.get(f.g)
        if e is None:
            errs.append('mat %d khong thuoc dao nao va khong bi bo qua (%s)' % (f.g, f.reason))
            continue
        x, y, w, h = e['rect4x']
        ox0, oy0 = e['origin']
        bx0, by0, bx1, by1 = e['bbox']
        for k in range(len(f.tuv)):
            X, Y = c[k, 0] * W4, c[k, 1] * H4
            tu, tv = f.tuv[k]
            if (X - x) / 4 + ox0 != tu or (Y - y) / 4 + oy0 != tv:
                errs.append('mat %d goc %d: uv atlas (%.3f,%.3f) khong ve dung uv goc (%d,%d)' % (f.g, k, X, Y, tu, tv))
                break
            if not (x <= X <= x + w and y <= Y <= y + h):
                errs.append('mat %d goc %d: ngoai hinh dao %d' % (f.g, k, e['id']))
                break
            if not (x + 4 * (bx0 - ox0) <= X <= x + 4 * (bx1 - ox0) and y + 4 * (by0 - oy0) <= Y <= y + 4 * (by1 - oy0)):
                errs.append('mat %d goc %d: ngoai bbox dao %d' % (f.g, k, e['id']))
                break
        report_islands.setdefault(e['id'], set()).update(centre_texels(f.tuv, f.quad, ex.W, ex.H))
        report_cons.setdefault(e['id'], set()).update(cons_texels(f.tuv, f.quad, ex.W, ex.H))
    # số liệu từng đảo
    rows = []
    worst = dict(cover=1.0, stp=1.0, transp=1.0, psnr=99.0, consCover=1.0, consStp=1.0, consTransp=1.0)

    def at_centres(e, tex):
        """Texel 1x (tu, tv) -> (raw16, điểm ảnh 4x chứa tâm texel, độ phủ / STP / trong suốt đúng)."""
        x, y = e['rect4x'][:2]
        ox0, oy0 = e['origin']
        tu = np.array([t[0] for t in tex])
        tv = np.array([t[1] for t in tex])
        raw = tim_decode(ex, int(e['clut'], 16), tu, tv)
        X = x + 4 * (tu - ox0)
        Y = y + 4 * (tv - oy0)
        pc = a4[Y + 2, X + 2]
        opq = raw != 0
        cov_ok = (pc[:, 3] != 0) == opq
        both = opq & (pc[:, 3] != 0)
        stp_ok = (pc[both, 3] == 128) == (((raw[both] >> 15) & 1) == 1)
        tr_ok = (pc[~opq] == 0).all(-1)
        frac = (lambda v: float(v.mean()) if v.size else 1.0)
        return raw, X, Y, opq, frac(cov_ok), frac(stp_ok), frac(tr_ok)

    for e in doc['islands']:
        tex = sorted(report_islands.get(e['id'], ()))
        row = dict(id=e['id'], clut=e['clut'], texels=len(tex), method=e['method'], psnr_gen=e['psnr'])
        # mọi texel mặt của đảo có thể lấy mẫu (raster bảo thủ): độ phủ >= 99.5 %, STP + trong suốt đúng tuyệt đối —
        # cũng phủ đảo chỉ có mặt suy biến (không có texel tâm nào)
        cons = sorted(report_cons.get(e['id'], ()))
        row['consTexels'] = len(cons)
        if cons:
            _, _, _, _, cc, cs, ct = at_centres(e, cons)
            row['consCover'], row['consStp'], row['consTransp'] = cc, cs, ct
            worst['consCover'] = min(worst['consCover'], cc)
            worst['consStp'] = min(worst['consStp'], cs)
            worst['consTransp'] = min(worst['consTransp'], ct)
            if cc < COVER_MIN:
                errs.append('dao %d: do phu khop (texel bao thu) %.4f < %.3f' % (e['id'], cc, COVER_MIN))
            if cs < 1.0:
                errs.append('dao %d: STP dung (texel bao thu) %.4f < 1' % (e['id'], cs))
            if ct < 1.0:
                errs.append('dao %d: trong suot dung (texel bao thu) %.4f < 1' % (e['id'], ct))
        if not tex:
            rows.append(row)
            continue
        raw, X, Y, opq, row['cover'], row['stp'], row['transp'] = at_centres(e, tex)
        # PSNR: trung bình các điểm ảnh đục của khối 4x4
        blocks = np.stack([a4[Y + j, X + i] for j in range(4) for i in range(4)], 1).astype(np.int64)
        op4 = blocks[..., 3] != 0
        n = op4.sum(1)
        sel = opq & (n > 0)
        if sel.any():
            mean = (blocks[..., :3] * op4[..., None]).sum(1)[sel] / n[sel][:, None]
            orig = np.stack([c5to8(raw[sel] & 31), c5to8(raw[sel] >> 5 & 31), c5to8(raw[sel] >> 10 & 31)], -1)
            mse = float(((mean - orig) ** 2).mean())
            row['psnr'] = 99.0 if mse <= 1e-12 else round(min(99.0, 10 * math.log10(255 * 255 / mse)), 2)
        else:
            row['psnr'] = 99.0
        rows.append(row)
        worst['cover'] = min(worst['cover'], row['cover'])
        worst['stp'] = min(worst['stp'], row['stp'])
        worst['transp'] = min(worst['transp'], row['transp'])
        worst['psnr'] = min(worst['psnr'], row['psnr'])
        if row['cover'] < COVER_MIN:
            errs.append('dao %d: do phu khop %.4f < %.3f' % (e['id'], row['cover'], COVER_MIN))
        if row['stp'] < 1.0:
            errs.append('dao %d: STP dung %.4f < 1' % (e['id'], row['stp']))
        if row['transp'] < 1.0:
            errs.append('dao %d: trong suot dung %.4f < 1' % (e['id'], row['transp']))
        need = NEAREST_PSNR if e['method'] == 'nearest' else psnr_min
        if row['psnr'] < need:
            errs.append('dao %d (%s): PSNR %.2f < %.1f' % (e['id'], e['method'], row['psnr'], need))
    rep = dict(variant=os.path.basename(os.path.normpath(variant_dir)), name=doc.get('name'), ok=not errs,
               errors=errs[:200], size4x=[W4, H4], size2x=[a2.shape[1], a2.shape[0]], islands=len(doc['islands']),
               methods=doc.get('methods'), worst=worst, texturedFaceCount=ex.n_tex, skipped=len(skipped),
               psnrMin=psnr_min, perIsland=rows)
    if write:
        out = os.path.join(variant_dir, rep['variant'] + '_tex.json')
        isl.write_atomic(out, json.dumps(rep, ensure_ascii=False, indent=1).encode('utf-8'))
    return not errs, rep


# ---------------------------------------------------------------- tờ so sánh (numpy, không PIL)
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
    ' ': '00000 00000 00000 00000 00000 00000 00000', '.': '00000 00000 00000 00000 00000 01100 01100',
    ':': '00000 01100 01100 00000 01100 01100 00000', '-': '00000 00000 00000 11111 00000 00000 00000',
    '(': '00010 00100 01000 01000 01000 00100 00010', ')': '01000 00100 00010 00010 00010 00100 01000',
    '/': '00001 00010 00010 00100 01000 01000 10000', '|': '00100 00100 00100 00100 00100 00100 00100',
    '%': '11001 11010 00010 00100 01000 01011 10011', ',': '00000 00000 00000 00000 01100 00100 01000',
    '_': '00000 00000 00000 00000 00000 00000 11111', '#': '01010 11111 01010 01010 01010 11111 01010',
    '+': '00000 00100 00100 11111 00100 00100 00000', '=': '00000 00000 11111 00000 11111 00000 00000',
    '<': '00010 00100 01000 10000 01000 00100 00010', '>': '01000 00100 00010 00001 00010 00100 01000',
}


def draw_text(img, x, y, text, colour=(255, 230, 120), scale=2):
    """Chữ bitmap 5x7 (chữ hoa ASCII; ký tự lạ -> '?' bỏ qua) lên img RGB uint8."""
    for ch in text.upper():
        pat = FONT.get(ch)
        if pat is None:
            x += 6 * scale
            continue
        rows = pat.split()
        for j, r in enumerate(rows):
            for i, b in enumerate(r):
                if b == '1':
                    y0, x0 = y + j * scale, x + i * scale
                    if 0 <= y0 and y0 + scale <= img.shape[0] and 0 <= x0 and x0 + scale <= img.shape[1]:
                        img[y0:y0 + scale, x0:x0 + scale] = colour
        x += 6 * scale


def checker(h, w, s=8):
    y, x = np.mgrid[0:h, 0:w]
    v = np.where(((x // s) + (y // s)) % 2 == 0, 96, 64).astype(np.uint8)
    return np.repeat(v[..., None], 3, 2)


def over_checker(rgba):
    """RGBA (A chỉ là có/không) lên nền ô cờ -> RGB."""
    bg = checker(rgba.shape[0], rgba.shape[1])
    return np.where((rgba[..., 3] > 0)[..., None], rgba[..., :3], bg)


def draw_poly(img, pts, colour=(40, 255, 60)):
    """Viền đa giác 1 px (lấy mẫu dày theo cạnh)."""
    h, w = img.shape[:2]
    n = len(pts)
    for k in range(n):
        (x0, y0), (x1, y1) = pts[k], pts[(k + 1) % n]
        m = int(max(abs(x1 - x0), abs(y1 - y0)) * 2) + 2
        t = np.linspace(0, 1, m)
        xs = np.clip(np.round(x0 + (x1 - x0) * t).astype(int), 0, w - 1)
        ys = np.clip(np.round(y0 + (y1 - y0) * t).astype(int), 0, h - 1)
        img[ys, xs] = colour


def save_png(path, rgb):
    isl.png_write_file(path, rgb)
    print('to:', isl.rel(path))


def island_orig_rgba(ex, e, tw, th, dim=True):
    """Gốc 1x của vùng hình đảo (theo origin / kích thước 1x): giải mã bằng CLUT của đảo; texel ngoài mặt nạ đảo tối đi."""
    ox0, oy0 = e['origin']
    U, V = np.meshgrid(np.arange(ox0, ox0 + tw), np.arange(oy0, oy0 + th))
    raw = tim_decode(ex, int(e['clut'], 16), U, V)
    rgba = np.zeros((th, tw, 4), np.uint8)
    rgba[..., 0] = c5to8(raw & 31)
    rgba[..., 1] = c5to8(raw >> 5 & 31)
    rgba[..., 2] = c5to8(raw >> 10 & 31)
    rgba[..., 3] = np.where(raw != 0, 255, 0)
    return rgba


def island_mask_1x(ex, e, tw, th):
    """Mặt nạ texel của đảo (raster bảo thủ như bộ sinh) trên vùng hình đảo."""
    ox0, oy0 = e['origin']
    m = np.zeros((th, tw), bool)
    gs = set(e['faces'])
    for f in ex.faces:
        if f.g in gs:
            tu, tv = isl.face_texels(f, ex.W, ex.H)
            ok = (tu - ox0 >= 0) & (tu - ox0 < tw) & (tv - oy0 >= 0) & (tv - oy0 < th)
            m[tv[ok] - oy0, tu[ok] - ox0] = True
    return m


def _dim(rgb, m4):
    return np.where(m4[..., None], rgb, (rgb.astype(np.int64) * 35 // 100).astype(np.uint8))


def sheet_islands(variant_dir, ex, doc, rep, out_dir, label, page_w=2400, page_h=3200):
    """Mỗi đảo một ô: GỐC 1x (phóng 4x) | [ESRGAN | SCALE4X nếu có work/cand_*.png] | CHỌN (atlas_4x).
    Texel ngoài mặt nạ đảo (lề, chỉ để mip) tối đi ở mọi cột."""
    a4 = isl.png_read_file(os.path.join(variant_dir, 'atlas_4x.png'))
    cands = []
    heads_of = dict(esrgan_raw='ESRGAN THO', esrgan='ESRGAN KEP VIEN', scale4x='SCALE4X')
    for name in ('esrgan_raw', 'esrgan', 'scale4x'):
        p = os.path.join(variant_dir, 'work', 'cand_%s.png' % name)
        if os.path.isfile(p):
            cands.append((name, isl.png_read_file(p)))
    cpsnr = {}
    cj = os.path.join(variant_dir, 'work', 'candidates.json')
    if os.path.isfile(cj):
        cdoc = json.load(open(cj, encoding='utf-8'))
        cpsnr = {e['id']: e['psnr'] for e in cdoc['islands']}
        if not cdoc.get('antiring'):
            heads_of['esrgan'] = 'ESRGAN'
    per = {r['id']: r for r in rep['perIsland']}
    tiles = []
    for e in doc['islands']:
        x, y, w, h = e['rect4x']
        tw, th = w // 4, h // 4
        orig = island_orig_rgba(ex, e, tw, th)
        m4 = np.repeat(np.repeat(island_mask_1x(ex, e, tw, th), 4, 0), 4, 1)
        cols = [_dim(over_checker(np.repeat(np.repeat(orig, 4, 0), 4, 1)), m4)]
        tried = {t[0]: t[1] for t in e.get('tried', [])}
        tried.update(cpsnr.get(e['id'], {}))
        heads = ['GOC']
        for name, ca in cands:
            cols.append(_dim(over_checker(ca[y:y + h, x:x + w]), m4))
            heads.append('%s %s' % (heads_of[name], tried.get(name, '')))
        cols.append(_dim(over_checker(a4[y:y + h, x:x + w]), m4))
        heads.append('CHON')
        r = per.get(e['id'], {})
        txt = 'DAO %d CLUT %s CHON %s PSNR %s' % (e['id'], e['clut'], e['method'], r.get('psnr', '-'))
        sub = ' | '.join(heads)
        tw_px = max(len(cols) * (w + 12), len(txt) * 12 + 8, len(sub) * 6 + 8)
        tile = np.full((h + 36, tw_px, 3), 24, np.uint8)
        draw_text(tile, 4, 4, txt)
        draw_text(tile, 4, 22, sub, colour=(170, 200, 255), scale=1)
        for i, c in enumerate(cols):
            tile[36:36 + h, i * (w + 12):i * (w + 12) + w] = c
        tiles.append(tile)
    pos = isl.shelf_pack([(t.shape[1], t.shape[0]) for t in tiles], page_w, 16)[0]
    by_page = {}
    for i, (px, py) in enumerate(pos):
        by_page.setdefault(py // page_h, []).append(i)
    paths = []
    head = 40
    title = 'GOC 1X (PHONG 4X)' + ''.join(' | %s' % heads_of[n] for n, _ in cands) + ' | CHON (ATLAS_4X)'
    for pg in sorted(by_page):
        idx = by_page[pg]
        y0 = min(pos[i][1] for i in idx)
        hh = max(pos[i][1] + tiles[i].shape[0] for i in idx) - y0
        ww = max(pos[i][0] + tiles[i].shape[1] for i in idx)
        img = np.full((hh + head + 8, max(ww, 1400), 3), 16, np.uint8)
        draw_text(img, 8, 10, '%s  %s  NGOAI DAO TOI DI  TRANG %d/%d' % (label, title, len(paths) + 1, len(by_page)),
                  scale=3)
        for i in idx:
            px, py = pos[i]
            t = tiles[i]
            img[head + py - y0:head + py - y0 + t.shape[0], px:px + t.shape[1]] = t
        p = os.path.join(out_dir, '%s_dao_%d.png' % (label, len(paths) + 1))
        save_png(p, img)
        paths.append(p)
    return paths


def tim_space_new(ex, doc, a4):
    """Ghép atlas 4x mới về bố cục TIM (khối 0): mỗi texel lấy đảo có màu giải mã trùng _atlas.png của export (đúng CLUT
    mà ảnh gốc hiển thị), ưu tiên đảo trước. -> RGBA [4H, 4W]."""
    W, H = ex.W, ex.H
    out = np.zeros((H * 4, W * 4, 4), np.uint8)
    done = np.zeros((H, W), bool)
    ref = ex.atlas_png
    for e in doc['islands']:
        x, y, w, h = e['rect4x']
        tw, th = w // 4, h // 4
        ox0, oy0 = e['origin']
        m = island_mask_1x(ex, e, tw, th)
        yy, xx = np.nonzero(m)
        tu, tv = xx + ox0, yy + oy0
        ok = (tu >= 0) & (tu < W) & (tv >= 0) & (tv < H)
        tu, tv, xx, yy = tu[ok], tv[ok], xx[ok], yy[ok]
        if ref is not None:
            raw = tim_decode(ex, int(e['clut'], 16), tu, tv)
            px = ref[tv, tu]
            same = np.where(raw == 0, px[:, 3] == 0,
                            (px[:, 3] != 0) & (isl.rgb8_to_c5(px[:, 0]) == (raw & 31))
                            & (isl.rgb8_to_c5(px[:, 1]) == (raw >> 5 & 31)) & (isl.rgb8_to_c5(px[:, 2]) == (raw >> 10 & 31)))
            sel = same & ~done[tv, tu]
        else:
            sel = ~done[tv, tu]
        for a, b, c, d in zip(tu[sel], tv[sel], xx[sel], yy[sel]):
            out[b * 4:b * 4 + 4, a * 4:a * 4 + 4] = a4[y + d * 4:y + d * 4 + 4, x + c * 4:x + c * 4 + 4]
        done[tv[sel], tu[sel]] = True
    return out, done


def sheet_overview(variant_dir, ex, doc, out_dir, label, pilot=None, zooms=()):
    a4 = isl.png_read_file(os.path.join(variant_dir, 'atlas_4x.png'))
    W, H = ex.W, ex.H
    new, used = tim_space_new(ex, doc, a4)
    u4 = np.repeat(np.repeat(used, 4, 0), 4, 1)
    panels = []
    if ex.atlas_png is not None:
        o = ex.atlas_png[:H]
        o4 = np.repeat(np.repeat(o, 4, 0), 4, 1)
        rgb = over_checker(o4)
        rgb = np.where(u4[..., None], rgb, (rgb.astype(np.int64) * 35 // 100).astype(np.uint8))
        panels.append(('GOC 1X (PHONG 4X)', rgb))
    if pilot is not None:
        p = isl.png_read_file(pilot)[:H * 4, :W * 4]
        rgb = over_checker(p)
        rgb = np.where(u4[..., None], rgb, (rgb.astype(np.int64) * 35 // 100).astype(np.uint8))
        panels.append(('BAN THU CU (UPSCALE_ATLAS.PY)', rgb))
    panels.append(('MOI 4X (DAO + STP + DO PHU)', over_checker(new)))
    # viền uv
    for _, img in panels:
        for f in ex.faces:
            if f.valid and f.blk == 0:
                for t in f.tris():
                    draw_poly(img, [(f.tuv[c][0] * 4, f.tuv[c][1] * 4) for c in t])
    gap = 16
    head = 44
    pw = W * 4
    total_w = len(panels) * pw + (len(panels) - 1) * gap
    rows_h = head + H * 4 + 8
    zoom_imgs = []
    for z in zooms:
        x0, y0, x1, y1 = z
        crops = []
        for name, img in panels:
            c = img[y0 * 4:y1 * 4, x0 * 4:x1 * 4]
            c = np.repeat(np.repeat(c, 2, 0), 2, 1)
            crops.append((name, c))
        zoom_imgs.append((z, crops))
    zh = sum(28 + c[0][1].shape[0] + 8 for _, c in zoom_imgs)
    img = np.full((rows_h + zh + 8, max(total_w, 600), 3), 16, np.uint8)
    for k, (name, p) in enumerate(panels):
        x = k * (pw + gap)
        draw_text(img, x + 4, 8, name, scale=3 if len(name) * 18 + 8 <= pw else 2)
        img[head:head + H * 4, x:x + pw] = p
    y = rows_h
    for z, crops in zoom_imgs:
        draw_text(img, 4, y + 4, 'PHONG TO 8X VUNG TEXEL %d,%d - %d,%d' % z, colour=(200, 200, 255))
        y += 28
        for k, (name, c) in enumerate(crops):
            x = k * (c.shape[1] + gap)
            if x + c.shape[1] <= img.shape[1]:
                img[y:y + c.shape[0], x:x + c.shape[1]] = c
        y += crops[0][1].shape[0] + 8
    p = os.path.join(out_dir, '%s_tongquan.png' % label)
    save_png(p, img)
    return p


# ---------------------------------------------------------------- tự kiểm tổng hợp
def _synth(work):
    """Tạo 'game' tổng hợp (TIM 4bpp 64x32, 3 hàng CLUT) + JSON export lược đồ export_tmd.py. -> (game, export dir)."""
    game = os.path.join(work, 'game', 'files')
    os.makedirs(os.path.join(game, 'synth'), exist_ok=True)
    rng = np.random.default_rng(11)
    iw, ih = 16, 32                   # 16 word = 64 texel 4bpp
    idx = rng.integers(1, 16, (ih, 64))
    idx[2:6, 2:9] = 0                 # lỗ trong suốt trong đảo A
    idx[20:24, 40:50] = 0
    idx[10, 10] = 15                  # texel STP
    words = np.zeros((ih, iw), np.uint16)
    for k in range(4):
        words |= (idx[:, k::4].astype(np.uint16) << (4 * k))
    clut = np.zeros((3, 16), np.uint16)
    for r in range(3):
        for i in range(1, 16):
            col = (i * 2 + r * 5) & 31 | ((i * 3 + r) & 31) << 5 | ((31 - i - r * 3) & 31) << 10
            clut[r, i] = col
        clut[r, 0] = 0
    clut[0, 15] |= 0x8000             # STP = 1
    clut[1, 7] = 0x8000               # đen đục có STP
    clut[2, 3] |= 0x8000
    ix, iy, cx, cy = 640, 0, 640, 480
    tim = struct.pack('<II', 0x10, 0x8) + struct.pack('<IHHHH', 12 + clut.size * 2, cx, cy, 16, 3) + clut.tobytes() \
        + struct.pack('<IHHHH', 12 + words.size * 2, ix, iy, iw, ih) + words.tobytes()
    with open(os.path.join(game, 'synth', 'tim'), 'wb') as f:
        f.write(tim)
    tpage = ix // 64                 # 10, 4bpp
    cl = [(cx // 16) | ((cy + r) << 6) for r in range(3)]

    def face(uv, c, quad, transl=False, textured=True):
        return dict(prim=0, quad=quad, textured=textured, translucent=transl, lit=True, layer='base', uv=uv,
                    tpage='%04x' % (tpage | (0x20 if transl else 0)), clut='%04x' % c)
    faces = [
        face([[0, 0], [16, 0], [0, 16], [16, 16]], cl[0], True),              # A
        face([[16, 0], [16, 16], [28, 6]], cl[0], False),                     # B: chung cạnh với A
        face([[8, 4], [24, 4], [8, 20], [24, 20]], cl[1], True, True),        # C: chồng texel A, CLUT khác
        face([[40, 2], [60, 2], [40, 2]], cl[2], False),                      # D: suy biến (đoạn thẳng)
        face([[36, 16], [63, 16], [36, 31], [63, 31]], cl[2], True, True),    # E: có lỗ trong suốt
        face([[30, 28], [34, 28], [30, 31]], cl[0], False),                   # F: đảo nhỏ
        dict(prim=0, quad=False, textured=False, translucent=False, lit=True, layer='base'),   # không texture
        face([[60, 10], [70, 10], [60, 20]], cl[0], False),                   # G: uv ngoài TIM -> bỏ qua
    ]
    doc = dict(name='synth', kind='field', source=dict(model='synth/model', texture='synth/tim',
                                                         texture_vram=[ix, iy, iw, ih], clut_vram=[cx, cy, 16, 3]),
               atlas=dict(W=64, H=32, bpp=0, cluts=['%04x' % c for c in cl], extra_blocks=[]), atlas_size=[64, 32],
               parts=[dict(index=0, faces=faces[:4]), dict(index=1, faces=faces[4:])])
    exd = os.path.join(work, 'export', 'synth')
    os.makedirs(exd, exist_ok=True)
    with open(os.path.join(exd, 'synth.json'), 'w', encoding='utf-8') as f:
        json.dump(doc, f)
    return game, exd


def selftest(work=None):
    import hd_atlas as hd
    errs = []
    work = os.path.abspath(work or os.path.join(ROOT, 'work', 'upscale', 'sc_remaster_p3', 'check_selftest'))
    shutil.rmtree(work, ignore_errors=True)
    game, exd = _synth(work)
    quiet = (lambda *a: None)
    v1 = os.path.join(work, 'tex', 'v1')
    v2 = os.path.join(work, 'tex', 'v2')
    hd.build_variant(exd, v1, game, ai=False, log=quiet, save_candidates=True)
    hd.build_variant(exd, v2, game, ai=False, log=quiet, save_candidates=True)
    for fn in ('atlas_4x.png', 'atlas_2x.png', 'atlas.json'):
        if open(os.path.join(v1, fn), 'rb').read() != open(os.path.join(v2, fn), 'rb').read():
            errs.append('hai lan dung khac byte: %s' % fn)
    ok, rep = check(v1, exd, game)
    if not ok:
        errs.append('ban dung tong hop khong dat: %s' % rep['errors'][:5])
    doc = json.load(open(os.path.join(v1, 'atlas.json'), encoding='utf-8'))
    if [s['g'] for s in doc['skippedFaces']] != [6] or len(doc['faceUv']) != 7:
        errs.append('mat bo qua / so mat sai: %s' % doc['skippedFaces'])
    if len(doc['islands']) != 5:
        errs.append('so dao tong hop %d != 5 (A+B, C, D, E, F)' % len(doc['islands']))
    stp_seen = rep['perIsland'] and any(r.get('stp') == 1.0 for r in rep['perIsland'])
    if not stp_seen:
        errs.append('khong do duoc STP')
    a4 = isl.png_read_file(os.path.join(v1, 'atlas_4x.png'))
    a4p = os.path.join(v1, 'atlas_4x.png')
    orig_bytes = {fn: open(os.path.join(v1, fn), 'rb').read() for fn in ('atlas_4x.png', 'atlas_2x.png', 'atlas.json')}

    def restore():
        for fn, b in orig_bytes.items():
            with open(os.path.join(v1, fn), 'wb') as f:
                f.write(b)

    def put4(img):
        b = isl.png_write(img)
        with open(a4p, 'wb') as f:
            f.write(b)
        d = json.loads(orig_bytes['atlas.json'].decode('utf-8'))
        d['png']['atlas_4x'] = hashlib.sha1(b).hexdigest()
        a2 = hd.mip_down(img)
        b2 = isl.png_write(a2)
        with open(os.path.join(v1, 'atlas_2x.png'), 'wb') as f:
            f.write(b2)
        d['png']['atlas_2x'] = hashlib.sha1(b2).hexdigest()
        with open(os.path.join(v1, 'atlas.json'), 'w', encoding='utf-8') as f:
            json.dump(d, f)

    e0 = doc['islands'][0]
    x, y = e0['rect4x'][:2]
    ox0, oy0 = e0['origin']
    # tìm một texel đục và một texel trong suốt của đảo A theo TIM
    exs = isl.load_export(exd, game)
    tu_o, tv_o = 10, 10           # STP = 1 (clut 0 chỉ số 15)
    tu_t, tv_t = 3, 3             # trong suốt
    P_o = (y + 4 * (tv_o - oy0) + 2, x + 4 * (tu_o - ox0) + 2)
    P_t = (y + 4 * (tv_t - oy0) + 2, x + 4 * (tu_t - ox0) + 2)
    if not (tim_decode(exs, int(e0['clut'], 16), tu_o, tv_o) >> 15) & 1:
        errs.append('texel thu STP khong co STP')
    faults = []
    m = a4.copy(); m[P_o][3] = 255 if m[P_o][3] == 128 else 128; faults.append(('lat STP', m, None))       # noqa: E702
    m = a4.copy(); m[P_t] = [9, 0, 0, 0]; faults.append(('RGB khac 0 o diem trong suot', m, None))           # noqa: E702
    m = a4.copy()
    m[P_o[0] - 2:P_o[0] + 18, P_o[1] - 2:P_o[1] + 18] = 0     # 5x5 texel mất độ phủ (> 0.5 % texel của đảo)
    faults.append(('mat do phu 5x5 texel', m, None))
    m = a4.copy(); m[P_t] = [50, 50, 50, 255]; faults.append(('texel trong suot thanh duc', m, None))       # noqa: E702
    m = a4.copy()
    cov = np.zeros(m.shape[:2], bool)
    for e in doc['islands']:
        rx, ry, rw, rh = e['rect4x']
        cov[ry:ry + rh, rx:rx + rw] = True
    yy, xx = np.nonzero(~cov)
    if len(yy):
        m[yy[-1], xx[-1]] = [1, 2, 3, 255]
        faults.append(('diem anh trong khe', m, None))
    else:
        errs.append('atlas tong hop khong co khe de gieo loi')
    # đảo D (chỉ có mặt suy biến uv (40,2)-(60,2): không texel tâm) — chỉ phép kiểm texel bảo thủ thấy được
    eD = [e for e in doc['islands'] if e['faces'] == [3]]
    if len(eD) != 1:
        errs.append('khong thay dao suy bien D')
    else:
        eD = eD[0]
        PD = (eD['rect4x'][1] + 4 * (2 - eD['origin'][1]) + 2, eD['rect4x'][0] + 4 * (50 - eD['origin'][0]) + 2)
        m = a4.copy()
        if m[PD][3] == 0:
            errs.append('texel (50,2) cua dao D trong suot')
        m[PD][3] = 255 if m[PD][3] == 128 else 128
        faults.append(('lat STP dao suy bien', m, None))
    m = a4.copy(); r = e0['rect4x']; blk = m[r[1]:r[1] + r[3], r[0]:r[0] + r[2]]                            # noqa: E702
    blk[..., :3] = np.where(blk[..., 3:] > 0, 255 - blk[..., :3], 0); faults.append(('dao mau (PSNR)', m, None))  # noqa: E702

    def json_fault(d):
        d['faceUv'][0][1][0] += 4.0 / d['w']
    faults.append(('faceUv lech 1 texel', None, json_fault))

    def two_fault(_):
        a2 = isl.png_read_file(os.path.join(v1, 'atlas_2x.png'))
        a2[0, 0] = [7, 7, 7, 255] if a2[0, 0, 3] == 0 else [0, 0, 0, 0]
        b2 = isl.png_write(a2)
        with open(os.path.join(v1, 'atlas_2x.png'), 'wb') as f:
            f.write(b2)
        return b2
    faults.append(('2x khac mip', None, two_fault))
    # bộ sinh bỏ nhầm một mặt hợp lệ (uv 0, khỏi đảo, vào skippedFaces): lúc chạy thành lỗ -> phải bắt
    def skip_fault(d):
        g = d['islands'][0]['faces'][0]
        d['islands'][0]['faces'] = d['islands'][0]['faces'][1:]
        d['faceUv'][g] = [[0.0, 0.0]] * 4
        d['skippedFaces'].append(dict(g=g, reason='gia'))
    faults.append(('bo nham mat hop le', None, skip_fault))
    # đảo khai CLUT khác CLUT của mặt (số liệu sẽ giải mã sai CLUT)
    def clut_fault(d):
        e = [e for e in d['islands'] if e['clut'] != d['islands'][0]['clut']][0]
        e['clut'] = d['islands'][0]['clut']
    faults.append(('dao sai CLUT', None, clut_fault))
    # hai hình đảo sát nhau hơn khe 8 px (nới rộng một hình về phía láng giềng; uv / điểm ảnh không đổi)
    def gutter_fault(d):
        R = [e['rect4x'] for e in d['islands']]
        for a in R:
            for b in R:
                if a is not b and b[0] - (a[0] + a[2]) == 8 and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]:
                    a[2] += 4
                    return
                if a is not b and b[1] - (a[1] + a[3]) == 8 and a[0] < b[0] + b[2] and b[0] < a[0] + a[2]:
                    a[3] += 4
                    return
        raise RuntimeError('khong co cap dao cach dung 8 px')
    faults.append(('khe dao < 8 px', None, gutter_fault))
    expect = {'bo nham mat hop le': 'mat bo qua sai', 'dao sai CLUT': 'nam trong dao', 'khe dao < 8 px': 'cach nhau <'}
    for name, img, jf in faults:
        restore()
        if img is not None:
            put4(img)
        elif name.startswith('2x'):
            b2 = jf(None)
            d = json.loads(orig_bytes['atlas.json'].decode('utf-8'))
            d['png']['atlas_2x'] = hashlib.sha1(b2).hexdigest()
            with open(os.path.join(v1, 'atlas.json'), 'w', encoding='utf-8') as f:
                json.dump(d, f)
        else:
            d = json.loads(orig_bytes['atlas.json'].decode('utf-8'))
            try:
                jf(d)
            except RuntimeError as e:
                errs.append('khong gieo duoc loi %s: %s' % (name, e))
                continue
            with open(os.path.join(v1, 'atlas.json'), 'w', encoding='utf-8') as f:
                json.dump(d, f)
        ok, rep = check(v1, exd, game, write=False)
        hit = [m for m in rep['errors'] if expect.get(name, '') in m]
        print('  loi gieo %-32s -> %s %s' % (name, 'BAT DUOC' if not ok else 'KHONG BAT DUOC',
                                              (hit or rep['errors'] or [''])[0]))
        if ok:
            errs.append('khong bat duoc loi gieo: %s' % name)
        elif not hit:
            errs.append('loi gieo %s bi bat nhung khong boi phep kiem rieng (%s)' % (name, expect[name]))
    restore()
    ok, _ = check(v1, exd, game, write=False)
    if not ok:
        errs.append('khoi phuc xong van khong dat')
    # chống viền sáng (hd_atlas.antiring_clamp): nét sáng ở ranh hai vùng màu bị kẹp, ảnh trong khoảng giữ nguyên
    ref = np.zeros((4, 6, 3), np.uint8)
    ref[:, :3] = [100, 10, 10]
    ref[:, 3:] = [60, 60, 60]
    base4 = np.repeat(np.repeat(ref, 4, 0), 4, 1)
    if not np.array_equal(hd.antiring_clamp(base4, ref), base4):
        errs.append('antiring doi anh khong co vien')
    ring = base4.copy()
    ring[:, 11] = [230, 30, 30]                 # nét đỏ sáng ở cột điểm ảnh cuối của texel 2, sát ranh đỏ / xám
    ring[:, 1] = [0, 0, 0]                      # nét tối trong vùng một màu
    got = hd.antiring_clamp(ring, ref)
    if got[0, 11].tolist() != [100, 30, 30] or got[0, 1].tolist() != [100, 10, 10]:
        errs.append('antiring khong kep vien: %s %s' % (got[0, 11].tolist(), got[0, 1].tolist()))
    # tờ so sánh chạy được
    exs = isl.load_export(exd, game)
    _, rep = check(v1, exd, game, write=False)
    sheet_islands(v1, exs, doc, rep, work, 'synth')
    sheet_overview(v1, exs, doc, work, 'synth', zooms=[(0, 0, 32, 32)])
    if 'PIL' in sys.modules:
        errs.append('PIL da bi import')
    for e in errs:
        print('LOI:', e)
    print('check_tex selftest: %s (%d loi)' % ('DAT' if not errs else 'KHONG DAT', len(errs)))
    return not errs


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ['selftest']:
        ap = argparse.ArgumentParser()
        ap.add_argument('cmd')
        ap.add_argument('--work')
        a = ap.parse_args(argv)
        return 0 if selftest(a.work) else 1
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('variant')
    ap.add_argument('--export', required=True)
    ap.add_argument('--game')
    ap.add_argument('--psnr-min', type=float, default=PSNR_MIN)
    ap.add_argument('--sheet')
    ap.add_argument('--pilot')
    ap.add_argument('--zoom', action='append', default=[])
    ap.add_argument('--label')
    a = ap.parse_args(argv)
    ok, rep = check(a.variant, a.export, a.game, a.psnr_min)
    w = rep['worst']
    print('%s: %s  4x %dx%d, %d dao %s, do phu min %.4f, STP min %.4f, trong suot min %.4f, PSNR min %.2f dB'
          % (rep['variant'], 'DAT' if ok else 'KHONG DAT', rep['size4x'][0], rep['size4x'][1], rep['islands'],
             rep['methods'], w['cover'], w['stp'], w['transp'], w['psnr']))
    for e in rep['errors'][:30]:
        print('  LOI:', e)
    if a.sheet:
        os.makedirs(a.sheet, exist_ok=True)
        ex = isl.load_export(a.export, a.game)
        doc = json.load(open(os.path.join(a.variant, 'atlas.json'), encoding='utf-8'))
        label = a.label or rep['variant']
        zooms = [tuple(int(v) for v in z.split(',')) for z in a.zoom]
        sheet_overview(a.variant, ex, doc, a.sheet, label, a.pilot, zooms)
        sheet_islands(a.variant, ex, doc, rep, a.sheet, label)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
