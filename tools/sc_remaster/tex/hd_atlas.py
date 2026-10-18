"""hd_atlas.py — dựng atlas HD (4x + 2x) cho MỘT biến thể texture (gói P3 của mô hình HD route B, SPEC §3.6, §3.8).

Một biến thể = khoá hình học x véc-tơ face-hash riêng; đầu vào = JSON lược đồ export_tmd.py (+ _atlas.png để đối chiếu)
và TIM nguồn trong game/files (source.texture của JSON; lớp phủ vi/files thắng). TIM là "nguồn 1x": màu 15 bit, bit STP
và độ phủ (texel 0x0000 = trong suốt) đều lấy từ đây, KHÔNG lấy từ ảnh AI.

Các bước:
  1. islands.py: đảo UV theo CLUT, cắt bbox + lề 8, pull-push ngoài đảo, xếp kệ thành ảnh làm việc 1x (khe 2 x lề).
  2. Phóng 4x ảnh làm việc: Real-ESRGAN (esrgan.py: staging ASCII, tự kiểm một lần mỗi tiến trình, 600 s + diệt cây,
     thử lại -t 64; treo cả hai lần thì tắt ESRGAN cho các biến thể sau trong cùng tiến trình) hoặc
     scale4x.py (--no-ai / không có Vulkan / ESRGAN hỏng). Kết quả ESRGAN được lưu đệm theo SHA-1 ảnh vào
     -> chạy lại cho cùng byte (đầu ra xác định khi ảnh ESRGAN cố định).
  3. Mỗi đảo:
     - chống viền sáng (chỉ ảnh ESRGAN, tắt bằng --no-antiring): kẹp từng kênh điểm ảnh 4x vào [min, max] của 2x2
       texel 1x quanh tâm điểm ảnh (ảnh làm việc mà AI đã thấy). Mô hình anime vẽ nét viền sáng ở chỗ hai vùng màu gặp
       nhau (viền đỏ cổ áo / cẳng tay Dart trận) — màu đó không có trong texel gốc lân cận nên bị kẹp. Trên 101 đảo của
       5 mô hình thử: PSNR tăng trung bình 2.0 dB (-0.2 .. +8.4), số đảo ESRGAN đạt 28 dB từ 41 lên 65;
     - giữ màu gốc: hd += up4(G(orig - down4_area(hd))), G = Gauss sigma 1.5 texel CHUẨN HOÁ theo mặt nạ texel đục của
       đảo (chỉ texel thật mới có tiếng nói), up4 song tuyến;
     - PSNR(down4_area(hd), orig) >= 28 dB, không thì đảo đó dùng scale4x, rồi nearest 4x; đo trên texel đục có tâm
       nằm trong một mặt của đảo, mỗi texel = trung bình các điểm ảnh 4x đục của khối (đúng số đo của check_tex.py);
     - độ phủ: khoảng cách có dấu của mặt nạ đục 1x (ngoài đảo: lan độ đục của texel đảo gần nhất, để mép mặt không bị
       khuyết), phóng song tuyến 4x, cắt ngưỡng 0 -> nhị phân. Điểm ảnh 4x chứa tâm texel 1x luôn cùng lớp với texel
       đó: SDF tại texel |v| >= 0.5 với trọng số song tuyến 0.766, láng giềng khác lớp |v| <= sqrt(2) - 0.5 = 0.914
       với tổng trọng số 0.234 -> dấu giữ nguyên (check_tex.py đo lại);
     - STP: bit STP 1x của texel đục (texel trong suốt / ngoài đảo: STP của texel đục gần nhất), lấy mẫu gần nhất 4x;
     - texel trong suốt: đúng (0, 0, 0, 0).
  4. Xếp lại các đảo ở 4x (bbox + lề cuối 2 texel = 8 px, khe 8 px, vị trí bội 4) vào atlas luỹ thừa 2 <= 2048 nhỏ nhất
     (thiếu chỗ thì lề cuối 1 rồi 0). Khe và ngoài đảo = (0,0,0,0) theo SPEC §3.6.1 (bộ ghi chỉ dùng A = 0 / 255 / 128,
     A = 0 thì RGB = 0; runtime + quy tắc mip §3.6.3 bỏ RGB của texel trong suốt nên tô RGB khe cũng không có tác dụng).
  5. atlas_4x.png, atlas_2x.png (= một mức mip §3.6.3 của 4x: khối 2x2, >= 2 trong suốt -> trong suốt, RGB trung bình
     làm tròn, STP đa số, hoà -> 1), atlas.json {w, h, faceUv[g][4][2], ...}: uv chuẩn hoá của 4 góc TMD (tam giác: góc
     4 = (0, 0)), suy từ uv tương đối TIM qua phép đặt đảo: X = ox + 4 (tu - tx0), u = X / w (cùng uv cho bản 2x).
     Mặt không dựng được (uv ngoài TIM, bpp khác TIM, CLUT ngoài TIM) -> uv 0, liệt kê trong skippedFaces.
     Hợp đồng với bộ đóng gói (P4): mọi g trong skippedFaces PHẢI có faceHash[g] = 0 trong biến thể (LIVE §3.4 d),
     nếu không runtime lấy mẫu atlasUv (0, 0) = khe trong suốt -> lỗ. Uv / CLUT ngoài TIM trùng quy tắc ghi 0 của
     SPEC §3.3.5; "bpp khác TIM" chỉ trùng khi dải CLUT 256 màu nằm ngoài rect CLUT của TIM (đúng cho mọi mặt bỏ qua
     của 114 mô hình v1 — đã đối chiếu với lib/facehash.stored_hashes), nên P4 ép 0 theo skippedFaces cho chắc.

Cách gọi (từ gốc repo, PYTHONIOENCODING=utf-8; chạy được bằng python hệ thống và python.exe -I của Blender):
  python tools/sc_remaster/tex/hd_atlas.py <export.json | thư mục export> --out <thư mục biến thể>
      [--game game/files] [--no-ai] [--model realesrgan-x4plus-anime] [--esrgan <staging ASCII>]
      [--esrgan-tool <thư mục Real-ESRGAN>] [--timeout 600] [--selftest-timeout 120] [--cache <thư mục>]
      [--psnr-min 28] [--save-candidates] [--no-antiring]
  Ra: <out>/atlas_4x.png, atlas_2x.png, atlas.json (chỉ dữ liệu xác định), work/work_1x.png,
      work/esrgan_<mô hình>_<sha1>.png (đệm kết quả AI), work/run_log.json (thời gian, staging, các lần thử).
      --save-candidates: thêm work/cand_esrgan.png, work/cand_esrgan_raw.png (chưa kẹp viền), work/cand_scale4x.png
      (cùng bố cục atlas_4x) + work/candidates.json (PSNR từng cách) cho tờ so sánh.
  Kiểm: python tools/sc_remaster/qa/check_tex.py <out> --export <export> [--game G]
Exit 0 = xong, 1 = lỗi. Không dùng PIL. Dữ liệu suy ra từ đĩa: chỉ ghi vào --out (remaster_work/tex/<biến thể> hoặc
work/upscale/sc_remaster*).
"""
import argparse
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import islands as isl  # noqa: E402
import scale4x as s4  # noqa: E402
import esrgan as esr  # noqa: E402

GENERATOR = 'lodsc-remaster tex 1'
PSNR_MIN = 28.0
SIGMA = 1.5
FINAL_MARGINS = (2, 1, 0)
GUTTER = 8
MAX_SIZE = 2048
SDF_RADIUS = 3


# ---------------------------------------------------------------- phép lọc xác định (cộng từng phần tử, thứ tự cố định)
def gauss_taps(sigma):
    r = int(math.ceil(3 * sigma))
    k = [math.exp(-(i * i) / (2.0 * sigma * sigma)) for i in range(-r, r + 1)]
    s = math.fsum(k)
    return [v / s for v in k]


def blur_sep(img, taps):
    """Lọc tách được, biên = 0 (ngoài ảnh không có khối lượng). img [h, w] hoặc [h, w, C] float64."""
    r = len(taps) // 2
    out = img
    for axis in (0, 1):
        n = out.shape[axis]
        pad = [(0, 0)] * out.ndim
        pad[axis] = (r, r)
        p = np.pad(out, pad)
        acc = np.zeros_like(out)
        for i, t in enumerate(taps):
            sl = [slice(None)] * out.ndim
            sl[axis] = slice(i, i + n)
            acc = acc + t * p[tuple(sl)]
        out = acc
    return out


def masked_blur(d, m, sigma=SIGMA):
    """Gauss chuẩn hoá theo mặt nạ: G(d*m) / G(m); chỗ G(m) ~ 0 -> 0."""
    taps = gauss_taps(sigma)
    mf = m.astype(np.float64)
    num = blur_sep(d * mf[..., None], taps)
    den = blur_sep(mf, taps)
    ok = den > 1e-12
    out = np.zeros_like(d)
    out[ok] = num[ok] / den[ok][..., None]
    return out


def down4(hd):
    """Trung bình khối 4x4 (cộng 16 lát theo thứ tự cố định)."""
    x = np.asarray(hd, np.float64)
    acc = np.zeros((x.shape[0] // 4, x.shape[1] // 4) + x.shape[2:], np.float64)
    for j in range(4):
        for i in range(4):
            acc = acc + x[j::4, i::4]
    return acc / 16.0


def psnr_shown(hd_u8, a4, orig8, sel):
    """PSNR giữa màu hiển thị và màu gốc trên texel sel (đục): mỗi texel lấy trung bình các điểm ảnh 4x ĐỤC (a4) của
    khối 4x4 của nó (cùng số đo với qa/check_tex.py). Texel không có điểm ảnh đục nào bị bỏ (độ phủ đo riêng)."""
    x = np.asarray(hd_u8, np.float64)
    m = a4.astype(np.float64)
    acc = np.zeros(orig8.shape, np.float64)
    cnt = np.zeros(orig8.shape[:2], np.float64)
    for j in range(4):
        for i in range(4):
            mm = m[j::4, i::4]
            acc = acc + x[j::4, i::4] * mm[..., None]
            cnt = cnt + mm
    use = sel & (cnt > 0)
    if not use.any():
        return 99.0
    d = acc[use] / cnt[use][:, None] - orig8[use].astype(np.float64)
    mse = float((d * d).sum()) / d.size
    return 99.0 if mse <= 1e-12 else min(99.0, 10.0 * math.log10(255.0 * 255.0 / mse))


def centre_mask(ex, isd, crop):
    """Texel có tâm nằm trong một mặt của đảo (toạ độ vùng cắt); đảo chỉ có mặt suy biến -> mặt nạ bảo thủ."""
    cx0, cy0 = crop['origin']
    w, h = crop['size']
    m = np.zeros((h, w), bool)
    for g in isd.faces:
        for tri in ex.faces[g].tri_points():
            x0, y0, mm = isl.raster_centres(tri, ex.W, ex.H)
            if mm.size and mm.any():
                yy, xx = np.nonzero(mm)
                m[yy + y0 - cy0, xx + x0 - cx0] = True
    return m if m.any() else crop['mask']


def antiring_clamp(hd, ref):
    """Chống viền sáng (anti-ringing) cho ảnh AI: kẹp từng kênh của điểm ảnh 4x vào [min, max] của 2x2 texel 1x quanh
    tâm điểm ảnh (vết lấy mẫu song tuyến; biên kẹp). ref = vùng cắt ảnh làm việc 1x mà mô hình AI đã thấy (texel đảo
    chính xác, ngoài đảo là pull-push). Real-ESRGAN anime vẽ thêm nét viền sáng ở chỗ hai vùng màu gặp nhau (viền đỏ
    ở cổ áo / cẳng tay Dart trận, atlas_uv_top.png); màu vượt khoảng của texel gốc lân cận là màu không có trong ảnh gốc
    -> bị kẹp, còn chuyển màu mượt và nét trong khoảng thì giữ. Số nguyên, xác định."""
    r = np.asarray(ref, np.int16)
    h, w = r.shape[:2]
    ys = np.clip(np.floor((np.arange(4 * h) + 0.5) / 4 - 0.5).astype(np.int64), 0, h - 1)
    xs = np.clip(np.floor((np.arange(4 * w) + 0.5) / 4 - 0.5).astype(np.int64), 0, w - 1)
    y1 = np.minimum(ys + 1, h - 1)
    x1 = np.minimum(xs + 1, w - 1)
    c = [r[a][:, b] for a in (ys, y1) for b in (xs, x1)]
    lo = np.minimum(np.minimum(c[0], c[1]), np.minimum(c[2], c[3]))
    hi = np.maximum(np.maximum(c[0], c[1]), np.maximum(c[2], c[3]))
    return np.clip(np.asarray(hd, np.int16), lo, hi).astype(np.uint8)


def colour_correct(hd, orig8, known, sigma=SIGMA):
    """hd (4x, uint8/float) += up4(G_M(orig - down4(hd))) -> uint8."""
    x = np.asarray(hd, np.float64)
    d = orig8.astype(np.float64) - down4(x)
    c = masked_blur(d, known, sigma)
    up = isl.resize_bilinear(c, x.shape[0], x.shape[1])
    return np.clip(np.floor(x + up + 0.5), 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- độ phủ + STP
def signed_distance(o, radius=SDF_RADIUS):
    """Khoảng cách có dấu (theo tâm texel) tới texel khác lớp gần nhất, cắt ở radius: đục -> +(d - 0.5),
    trong suốt -> -(d - 0.5). Biên ảnh: lặp lại texel biên."""
    h, w = o.shape
    p = np.pad(o, radius, mode='edge')
    d = np.full((h, w), float(radius), np.float64)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            dist = math.sqrt(dy * dy + dx * dx)
            if dist == 0 or dist >= radius:
                continue
            nb = p[radius + dy:radius + dy + h, radius + dx:radius + dx + w]
            diff = nb != o
            d = np.where(diff & (dist < d), dist, d)
    return np.where(o, d - 0.5, -(d - 0.5))


def coverage_stp(crop):
    """-> (alpha4 bool [4h, 4w], stp4 uint8 [4h, 4w]) của vùng cắt (xem docstring module)."""
    mask, opaque, raw = crop['mask'], crop['opaque'], crop['raw']
    h, w = mask.shape
    o_ext, _ = isl.propagate_nearest(mask & opaque, mask)
    known = mask & opaque
    stp = ((raw.astype(np.int64) >> 15) & 1).astype(np.uint8)
    s_ext, ok = isl.propagate_nearest(np.where(known, stp, 0).astype(np.uint8), known)
    if not ok.all():
        s_ext = np.zeros((h, w), np.uint8)
    sdf = signed_distance(o_ext)
    a4 = isl.resize_bilinear(sdf, 4 * h, 4 * w) > 0
    stp4 = np.repeat(np.repeat(s_ext, 4, 0), 4, 1)
    return a4, stp4


# ---------------------------------------------------------------- mip §3.6.3 (vectorized)
def file_classes(rgba):
    a = rgba[..., 3]
    return np.where(a < 64, 0, np.where(a < 192, 2, 1)).astype(np.uint8)


def mip_down(level):
    """SPEC §3.6.3 một mức (quy ước file): khối 2x2 (cắt theo cạnh khi một chiều lẻ / bằng 1)."""
    level = np.asarray(level, np.uint8)
    h, w = level.shape[:2]
    h2, w2 = max(1, h // 2), max(1, w // 2)
    cls = file_classes(level)
    n = np.zeros((h2, w2), np.int64)
    t = np.zeros((h2, w2), np.int64)
    o = np.zeros((h2, w2), np.int64)
    s1 = np.zeros((h2, w2), np.int64)
    acc = np.zeros((h2, w2, 3), np.int64)
    for j in (0, 1):
        for i in (0, 1):
            ys = 2 * np.arange(h2) + j
            xs = 2 * np.arange(w2) + i
            valid = (ys < h)[:, None] & (xs < w)[None, :]
            yy = np.minimum(ys, h - 1)
            xx = np.minimum(xs, w - 1)
            c = cls[yy][:, xx]
            px = level[yy][:, xx].astype(np.int64)
            n += valid
            t += valid & (c == 0)
            op = valid & (c != 0)
            o += op
            s1 += valid & (c == 2)
            acc += np.where(op[..., None], px[..., :3], 0)
    keep = 2 * t < n
    osafe = np.maximum(o, 1)
    rgb = (acc + (o // 2)[..., None]) // osafe[..., None]
    out = np.zeros((h2, w2, 4), np.uint8)
    out[..., :3] = np.where(keep[..., None], rgb, 0).astype(np.uint8)
    out[..., 3] = np.where(keep, np.where(s1 >= o - s1, 128, 255), 0).astype(np.uint8)
    return out


# ---------------------------------------------------------------- xếp atlas cuối
def choose_atlas(sizes, gutter=GUTTER, max_size=MAX_SIZE):
    """Atlas luỹ thừa 2 nhỏ nhất (diện tích, rồi cạnh dài, rồi rộng, rồi xếp kệ trước skyline) chứa mọi hình, thử cả
    xếp kệ và xếp skyline cho mỗi bề rộng (xác định). Hình cách nhau >= gutter, vị trí bội 4. -> (W, H, pos) | None."""
    best = None
    W = 4
    while W <= max_size:
        for k, r in enumerate((isl.shelf_pack(sizes, W, gutter, align=4), isl.skyline_pack(sizes, W, gutter))):
            if r is None:
                continue
            pos, _, uh = r
            H = 4
            while H < uh:
                H *= 2
            if H <= max_size:
                key = (W * H, max(W, H), W, k)
                if best is None or key < best[0]:
                    best = (key, W, H, pos)
        W *= 2
    return None if best is None else best[1:]


# ---------------------------------------------------------------- dựng biến thể
# Trạng thái Real-ESRGAN trong MỘT tiến trình (worker chạy nhiều biến thể liền nhau): tự kiểm chỉ chạy một lần cho mỗi
# (staging, mô hình); ESRGAN treo / hỏng cả hai lần ở một biến thể thì tắt cho các biến thể sau (cầu dao), để một máy
# treo GPU không tốn 2 x 600 s cho từng biến thể. reset_esrgan_state() để bắt đầu lại.
_ESRGAN_STATE = dict(selftest={}, disabled=None)


def reset_esrgan_state():
    _ESRGAN_STATE['selftest'].clear()
    _ESRGAN_STATE['disabled'] = None


def _esrgan_stage(work_rgb, model, esrgan_dir, tool_dir, timeout, selftest_timeout, cache_dir, log):
    """-> (ảnh 4x hoặc None, thông tin)."""
    info = dict(model=model)
    # khoá đệm theo điểm ảnh thô (không theo byte PNG: zlib của Blender và zlib-ng của CPython 3.14 nén khác nhau)
    wr = np.ascontiguousarray(work_rgb, np.uint8)
    key = isl.sha1_bytes(('%dx%dx%d:' % wr.shape).encode() + wr.tobytes() + model.encode())
    cpath = os.path.join(cache_dir, 'esrgan_%s_%s.png' % (model, key[:16])) if cache_dir else None
    if cpath and os.path.isfile(cpath):
        try:
            img = isl.png_read_file(cpath)
        except Exception as e:   # đệm hỏng (CRC, zlib, cắt cụt...) -> chạy lại ESRGAN, không dừng cả biến thể
            log('esrgan: bo qua ket qua dem hong %s (%s)' % (os.path.basename(cpath), e))
            img = np.zeros((0, 0, 3), np.uint8)
        if img.shape[:2] == (work_rgb.shape[0] * 4, work_rgb.shape[1] * 4):
            info['cache'] = os.path.basename(cpath)
            log('esrgan: dung ket qua dem %s' % os.path.basename(cpath))
            return np.ascontiguousarray(img[..., :3]), info
    if _ESRGAN_STATE['disabled']:
        info['reason'] = 'Real-ESRGAN da tat trong lan chay nay (%s)' % _ESRGAN_STATE['disabled']
        return None, info
    try:
        st = esr.prepare_staging(esrgan_dir, tool_dir, model)
    except esr.EsrganError as e:
        info['reason'] = str(e)
        return None, info
    info['staging'] = st.info()
    skey = (os.path.normcase(st.dir), model)
    if skey not in _ESRGAN_STATE['selftest']:
        _ESRGAN_STATE['selftest'][skey] = esr.selftest_tool(st, model, selftest_timeout)
    ok, sti = _ESRGAN_STATE['selftest'][skey]
    info['selftest'] = sti
    if not ok:
        info['reason'] = 'tu kiem Real-ESRGAN hong: %s' % sti.get('reason')
        log('esrgan: ' + info['reason'])
        return None, info
    out, attempts = esr.upscale(st, work_rgb, model, timeout, 'atlas', log)
    info['attempts'] = attempts
    if out is None:
        info['reason'] = 'Real-ESRGAN hong ca hai lan'
        if all(a.get('timeout') for a in attempts):
            _ESRGAN_STATE['disabled'] = 'treo ca hai lan, qua %d s' % timeout
        return None, info
    if cpath:
        os.makedirs(cache_dir, exist_ok=True)
        isl.png_write_file(cpath, out)
        info['cache'] = os.path.basename(cpath)
    return out, info


def _esrgan_summary(einfo, up):
    """Phần xác định của thông tin ESRGAN cho atlas.json (không có thời gian / đường dẫn staging)."""
    if einfo is None:
        return None
    out = dict(model=einfo.get('model'), used=up is not None)
    if up is not None:
        out['out_sha1'] = isl.sha1_bytes(np.ascontiguousarray(up, np.uint8).tobytes())   # SHA-1 điểm ảnh thô
    else:
        out['reason'] = einfo.get('reason')
    return out


def build_variant(export, out_dir, game=None, ai=True, model=esr.DEFAULT_MODEL, esrgan_dir=None, tool_dir=None,
                  timeout=esr.TIMEOUT, selftest_timeout=esr.SELFTEST_TIMEOUT, margin=isl.MARGIN, psnr_min=PSNR_MIN,
                  cache_dir=None, final_margins=FINAL_MARGINS, gutter=GUTTER, max_size=MAX_SIZE, log=print,
                  save_candidates=False, antiring=True):
    """Dựng atlas HD cho một biến thể. -> dict tóm tắt (cũng là phần đầu atlas.json). Lỗi -> isl.TexError.
    antiring: kẹp ảnh ESRGAN vào khoảng màu texel gốc lân cận trước khi giữ màu (antiring_clamp).
    save_candidates: ghi thêm work/cand_esrgan.png, work/cand_scale4x.png (+ work/cand_esrgan_raw.png = ESRGAN chưa kẹp
    khi antiring) cùng bố cục atlas_4x, mọi đảo dùng một phương pháp, đã giữ màu + độ phủ + STP, và
    work/candidates.json (PSNR từng cách cho mỗi đảo) để tờ so sánh cho người dùng thấy ngưỡng PSNR đã chọn gì."""
    t0 = time.time()
    if 'PIL' in sys.modules:
        raise isl.TexError('PIL da bi import (cam trong tools/sc_remaster)')
    ex = isl.load_export(export, game)
    tot, bad = isl.check_against_atlas(ex)
    if bad:
        raise isl.TexError('%s: giai ma TIM khac _atlas.png o %d/%d texel (sai TIM / vi tri?)' % (ex.name, bad, tot))
    islands = isl.build_islands(ex)
    if not islands:
        raise isl.TexError('%s: khong co dao nao (moi mat bi bo qua)' % ex.name)
    work = isl.make_work(ex, islands, margin)
    wrgb = work['rgb']
    os.makedirs(out_dir, exist_ok=True)
    wdir = os.path.join(out_dir, 'work')
    os.makedirs(wdir, exist_ok=True)
    isl.png_write_file(os.path.join(wdir, 'work_1x.png'), wrgb)
    log('%s: %d mat co texture, %d dao, anh lam viec %dx%d' % (ex.name, ex.n_tex, len(islands), wrgb.shape[1],
                                                               wrgb.shape[0]))
    up = None
    einfo = None
    if ai:
        up, einfo = _esrgan_stage(wrgb, model, esrgan_dir, tool_dir or esr.DEFAULT_TOOL, timeout, selftest_timeout,
                                  cache_dir or wdir, log)
        if up is None:
            log('esrgan khong dung duoc -> scale4x (%s)' % einfo.get('reason'))
    sc4 = None
    results = []
    for k, (isd, crop) in enumerate(zip(islands, work['crops'])):
        px, py = work['pos'][k]
        w, h = crop['size']
        orig8 = crop['rgb8']
        known = crop['known']
        cands = []
        extra_cands = []
        if up is not None:
            def esr_crop(px=px, py=py, w=w, h=h, c=crop, clamp=antiring):
                e = up[py * 4:(py + h) * 4, px * 4:(px + w) * 4]
                return antiring_clamp(e, c['work']) if clamp else e
            cands.append(('esrgan', esr_crop))
            if antiring:
                extra_cands.append(('esrgan_raw', lambda f=esr_crop: f(clamp=False)))

        def sc4_crop(px=px, py=py, w=w, h=h):
            nonlocal sc4
            if sc4 is None:
                sc4 = s4.scale4x(wrgb)
            return sc4[py * 4:(py + h) * 4, px * 4:(px + w) * 4]
        cands.append(('scale4x', sc4_crop))
        cands.append(('nearest', lambda c=crop: s4.nearest4x(c['work'])))
        a4, stp4 = coverage_stp(crop)
        sel = centre_mask(ex, isd, crop) & crop['opaque']

        def finish(hd, a4=a4, stp4=stp4, w=w, h=h):
            rgba = np.zeros((h * 4, w * 4, 4), np.uint8)
            rgba[..., :3] = np.where(a4[..., None], hd, 0)
            rgba[..., 3] = np.where(a4, np.where(stp4 == 1, 128, 255), 0)
            return rgba
        tried = []
        extra = {}
        cpsnr = {}
        for name, get in cands:
            hd = colour_correct(get(), orig8, known)
            p = psnr_shown(hd, a4, orig8, sel)
            tried.append((name, round(p, 2)))
            if save_candidates and name != 'nearest':
                extra[name] = finish(hd)
                cpsnr[name] = round(p, 2)
            if p >= psnr_min or name == 'nearest':
                break
        if save_candidates:
            for nm, gt in cands + extra_cands:
                if nm not in extra and nm != 'nearest':
                    c = colour_correct(gt(), orig8, known)
                    cpsnr[nm] = round(psnr_shown(c, a4, orig8, sel), 2)
                    extra[nm] = finish(c)
        results.append(dict(rgba=finish(hd), method=name, psnr=round(p, 2), tried=tried, extra=extra, cpsnr=cpsnr))
    # xếp cuối
    chosen = None
    for fm in final_margins:
        sizes = []
        for isd in islands:
            x0, y0, x1, y1 = isd.bbox
            sizes.append(((x1 - x0 + 2 * fm) * 4, (y1 - y0 + 2 * fm) * 4))
        r = choose_atlas(sizes, gutter, max_size)
        if r is not None:
            chosen = (fm, sizes) + tuple(r)
            break
    if chosen is None:
        raise isl.TexError('%s: dao khong vua atlas %dx%d' % (ex.name, max_size, max_size))
    fm, sizes, W4, H4, pos = chosen
    atlas = np.zeros((H4, W4, 4), np.uint8)
    cand_atlas = {}
    out_islands = []
    for k, isd in enumerate(islands):
        x0, y0, x1, y1 = isd.bbox
        ox, oy = pos[k]
        sw, sh = sizes[k]
        s = (margin - fm) * 4
        atlas[oy:oy + sh, ox:ox + sw] = results[k]['rgba'][s:s + sh, s:s + sw]
        for name, rg in results[k]['extra'].items():
            ca = cand_atlas.setdefault(name, np.zeros((H4, W4, 4), np.uint8))
            ca[oy:oy + sh, ox:ox + sw] = rg[s:s + sh, s:s + sw]
        out_islands.append(dict(id=isd.id, clut='%04x' % isd.clut, faces=isd.faces, bbox=[x0, y0, x1, y1],
                                texels=int(isd.mask.sum()), rect4x=[ox, oy, sw, sh], origin=[x0 - fm, y0 - fm],
                                method=results[k]['method'], psnr=results[k]['psnr'],
                                tried=[list(t) for t in results[k]['tried']]))
    face_uv = []
    for f in ex.faces:
        if not f.valid:
            face_uv.append([[0.0, 0.0]] * 4)
            continue
        e = out_islands[f.island]
        ox, oy = e['rect4x'][:2]
        tx0, ty0 = e['origin']
        corners = [[(ox + 4 * (u - tx0)) / W4, (oy + 4 * (v - ty0)) / H4] for u, v in f.tuv]
        if len(corners) == 3:
            corners.append([0.0, 0.0])
        face_uv.append(corners)
    a2 = mip_down(atlas)
    b4 = isl.png_write(atlas)
    b2 = isl.png_write(a2)
    methods = {}
    for r in results:
        methods[r['method']] = methods.get(r['method'], 0) + 1
    doc = dict(format=1, generator=GENERATOR, name=ex.name, w=W4, h=H4, w2=a2.shape[1], h2=a2.shape[0],
               texturedFaceCount=ex.n_tex, faceUv=face_uv,
               skippedFaces=[dict(g=f.g, reason=f.reason) for f in ex.faces if not f.valid],
               islands=out_islands, methods=methods, finalMargin=fm, gutter=gutter, margin=margin,
               psnrMin=psnr_min, png=dict(atlas_4x=isl.sha1_bytes(b4), atlas_2x=isl.sha1_bytes(b2)),
               source=dict(export=os.path.basename(ex.json_path), json_sha1=ex.json_sha1,
                           tim=ex.source.get('texture'), tim_sha1=ex.tim_sha1, atlas_check=[tot, bad],
                           atlas_check_other_clut=ex.atlas_other_clut),
               esrgan=_esrgan_summary(einfo, up) if ai else None, ai=bool(ai),
               antiring=bool(antiring and up is not None),
               work=dict(size=[int(wrgb.shape[1]), int(wrgb.shape[0])], sha1=isl.sha1_bytes(wrgb.tobytes())))
    # nhật ký chạy (thời gian, staging, các lần thử) để riêng: atlas.json chỉ chứa dữ liệu xác định
    isl.write_atomic(os.path.join(wdir, 'run_log.json'), json.dumps(
        dict(esrgan=einfo, seconds=round(time.time() - t0, 2)), ensure_ascii=False, indent=1).encode('utf-8'))
    for name in ('esrgan', 'esrgan_raw', 'scale4x'):
        p = os.path.join(wdir, 'cand_%s.png' % name)
        if name not in cand_atlas and os.path.isfile(p):
            os.remove(p)                          # ứng viên cũ của lần chạy trước không còn đúng bố cục
    for name, ca in sorted(cand_atlas.items()):
        isl.png_write_file(os.path.join(wdir, 'cand_%s.png' % name), ca)
    cj = os.path.join(wdir, 'candidates.json')
    if save_candidates:
        isl.write_atomic(cj, json.dumps(dict(antiring=bool(antiring), islands=[
            dict(id=isd.id, psnr=results[k]['cpsnr']) for k, isd in enumerate(islands)]), indent=1).encode('utf-8'))
    elif os.path.isfile(cj):
        os.remove(cj)
    isl.write_atomic(os.path.join(out_dir, 'atlas_4x.png'), b4)
    isl.write_atomic(os.path.join(out_dir, 'atlas_2x.png'), b2)
    isl.write_atomic(os.path.join(out_dir, 'atlas.json'), json.dumps(doc, ensure_ascii=False, indent=1).encode('utf-8'))
    log('%s: atlas %dx%d (2x %dx%d), le cuoi %d, phuong phap %s, PSNR min %.1f dB, %.1f s'
        % (ex.name, W4, H4, a2.shape[1], a2.shape[0], fm, methods, min(r['psnr'] for r in results),
           time.time() - t0))
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('export')
    ap.add_argument('--out', required=True)
    ap.add_argument('--game')
    ap.add_argument('--no-ai', action='store_true')
    ap.add_argument('--model', default=esr.DEFAULT_MODEL)
    ap.add_argument('--esrgan', help='thu muc staging ASCII da co Real-ESRGAN (cong cu PC chon)')
    ap.add_argument('--esrgan-tool', help='thu muc cai Real-ESRGAN (mac dinh deps/upscale/realesrgan)')
    ap.add_argument('--timeout', type=float, default=esr.TIMEOUT)
    ap.add_argument('--selftest-timeout', type=float, default=esr.SELFTEST_TIMEOUT)
    ap.add_argument('--cache')
    ap.add_argument('--psnr-min', type=float, default=PSNR_MIN)
    ap.add_argument('--save-candidates', action='store_true',
                    help='ghi work/cand_*.png + work/candidates.json cho to so sanh')
    ap.add_argument('--no-antiring', action='store_true', help='khong kep anh ESRGAN (chi de so sanh)')
    a = ap.parse_args(argv)
    try:
        build_variant(a.export, a.out, a.game, not a.no_ai, a.model, a.esrgan, a.esrgan_tool, a.timeout,
                      a.selftest_timeout, psnr_min=a.psnr_min, cache_dir=a.cache, save_candidates=a.save_candidates,
                      antiring=not a.no_antiring)
    except (isl.TexError, OSError) as e:
        print('LOI:', e)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
