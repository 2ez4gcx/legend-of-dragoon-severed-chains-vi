"""sc_hd_lock.py — "khoá" ảnh nền HD do mô hình khuếch tán (SeedVR2, SDXL + ControlNet Tile...) vẽ thêm chi tiết vào đúng
màu và đúng lưới điểm ảnh của nền PS1 gốc, rồi kiểm tra chất lượng (QA).

Cách gọi:
  python tools/sc_hd_lock.py <cảnh> --in <ảnh khuếch tán> --model <tên> [--ref realesrgan-x4plus|lanczos]
         [--goc work/upscale/goc] [--ai work/upscale/ai] [--iters 4] [--step 0.5] [--no-wavelet] [--no-backproj]
         [--crop auto|center|topleft] [--up bicubic|lanczos]
         [--min-psnr 30] [--min-edge 0.90] [--max-block 12] [--min-edge-raw 0.80] [--max-offset 1.0]
  ví dụ: python tools/sc_hd_lock.py DRGN21_25 --in D:/ComfyUI/output/rung_00001_.png --model seedvr2
Đầu vào:
  goc/<cảnh>_rgb.png                ảnh ghép gốc O (W x H, RGB; tools/sc_bgdump)
  ai/<cảnh>_<ref>.png               ảnh tham chiếu R lấy màu tần số thấp (mặc định Real-ESRGAN x4plus, 4W x 4H);
                                    --ref lanczos: R = O phóng 4x bằng LANCZOS (không cần file)
  --in                              ảnh khuếch tán D (RGB/RGBA, cỡ bất kỳ gần 4W x 4H)
Ra:
  ai/<cảnh>_<tên>.png               ảnh HD đã khoá, RGB, đúng 4W x 4H -> dùng tiếp: python tools/sc_hd_layers.py <cảnh> --model <tên>
  ai/<cảnh>_<tên>.qa.json           số đo QA (ảnh đã khoá và ảnh thô D), ngưỡng, các lỗi
  một dòng tóm tắt QA; exit 0 = QA đạt, 1 = QA không đạt hoặc lỗi (ảnh vẫn được ghi để xem, in rõ "QA FAIL").
  Không ghi đè ai/<cảnh>_<tên>.png đã có mà thiếu .qa.json (ảnh không do công cụ này ghi, vd. Real-ESRGAN thô).
  Cần --iters >= 0 và 0 < --step < 2 (xem bước 2).

Các bước (float32, chỉ numpy + Pillow, xác định: chạy 2 lần ra cùng byte):
 0. Cỡ ảnh, xét TỪNG TRỤC: trục dài hơn đích 0..MAXPAD px (mô hình đệm lên bội 8/16/32) thì cắt, trục khác thì đổi cỡ
    LANCZOS riêng trục đó (vd. 1540x1532: cắt ngang, giãn dọc; 1024x1024 hay 3072x3072: đổi cỡ cả hai).
    Cắt: --crop center = cắt giữa; topleft = từ góc trên trái; auto (mặc định) = bắt đầu từ cắt giữa rồi dời khung cắt
    theo độ lệch đo bằng tương quan pha với R (làm tròn, kẹp trong [0, phần dư]) -> đúng cả khi mô hình đệm một phía.
    Đọc ảnh: RGBA/P/L -> RGB (bỏ alpha); PNG xám 16 bit chia 257. In ra đã làm gì.
 1. Sửa màu kiểu wavelet (StableSR "wavelet_reconstruction"): B_r = lọc tách được [1/4, 1/2, 1/4] x [1/4, 1/2, 1/4]
    (3x3) giãn cách r, biên lặp điểm ảnh; X_0 = X, X_{i+1} = B_{2^i}(X_i), i = 0..4 (r = 1, 2, 4, 8, 16);
    cao tần H(X) = sum_i (X_i - X_{i+1}) = X - X_5, thấp tần L(X) = X_5.  Kết quả = H(D) + L(R) = D - L(D) + L(R):
    chi tiết nhỏ của D, màu/độ sáng mảng lớn (thang > ~15 px gốc) của R.
 2. Chiếu ngược lặp (iterative back-projection) về lưới điểm ảnh PS1: A = trung bình ô 4x4 (thu nhỏ theo diện tích),
    U = phóng 4x bicubic (Pillow, ảnh float 'F'); lặp n lần: HD <- clip(HD + s * U(O - A(HD)), 0, 255).
    Phần dư r = O - A(HD) giảm theo (1 - s*lambda)^n với lambda = trị riêng của A.U (đo được: 1 ở tần 0, ~0.65 gần
    Nyquist, bicubic và lanczos) -> hội tụ khi 0 < s < 2 (s = 0.5, n = 4: RMS phần dư 9.8 -> 1.6; s = 1: -> 0.25);
    s >= 2 hoặc s < 0 phân kỳ. A(HD) ~ O: mỗi ô 4x4 HD trung bình ra đúng điểm ảnh gốc; chi tiết dưới 1 điểm ảnh gốc
    của D được giữ.
 3. QA trên ảnh float ở tỉ lệ 1x (A của ảnh đã lượng tử uint8), so với O; cùng các số đo cho D thô (sau bước 0):
    PSNR      = 10 log10(255^2 / MSE), MSE trên R, G, B mọi điểm ảnh.
    SSIM      = trung bình bản đồ SSIM cửa sổ trượt 8x8 đều trên độ sáng Y (BT.601), C1 = (0.01*255)^2, C2 = (0.03*255)^2.
    cạnh      = hệ số tương quan Pearson giữa độ lớn Sobel |G| của Y hai ảnh (bỏ 1 px viền).
    lệch màu  = max trên các ô 16x16 (1x) của max_kênh |trung bình(A(X) - O)| (đơn vị mức 0..255).
    lệch hình (chỉ D thô) = độ dời toàn cục (dx, dy) px HD của D so với R, tương quan pha có cửa sổ Hann, phổ chéo
                chuẩn hoá biên độ nhân Gauss exp(-(f/0.15)^2) (bỏ chi tiết mô hình tự vẽ), đỉnh tinh chỉnh dưới px
                bằng khớp Gauss/parabol 3 điểm.  Dương = nội dung D dời sang phải/xuống.  Ảnh phẳng (không đo
                được) = trượt.
    Ngưỡng mặc định: ảnh khoá PSNR >= 30 dB, cạnh >= 0.90, lệch màu <= 12; ảnh thô cạnh >= 0.80, |lệch hình| <= 1 px HD
    (= 1/4 px gốc; các mô hình Real-ESRGAN đo được <= 0.3 px). Đo thử (DRGN21_25 / _37): x4plus khoá PSNR 44.1 / 47.2 dB,
    lệch màu 1.2 / 1.0 (x4plus thô tự làm tối mảng hoa văn: lệch màu 19.3 / 15.4); trôi màu +18 sáng + xoay sắc độ: khoá
    còn 1.2 / 1.0.  Chiếu ngược ép A(HD) ~ O nên che được lỗi dời hình của D (dời 12 px HD: ảnh khoá vẫn PSNR 36 / 40 dB,
    cạnh 0.99, nhưng có viền kép ở tỉ lệ HD): hai ngưỡng trên ảnh thô bắt lỗi đó (cạnh thô 0.40 / 0.54, lệch hình 12.00 px);
    dời 2 px HD: lệch hình 2.00 -> trượt.
Ảnh suy ra từ đĩa gốc: chỉ để thử trên máy (work/upscale bị .gitignore), không commit, không phát hành.
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
MAXPAD = 64          # px HD: phần dư tối đa mỗi chiều coi là đệm của mô hình (cắt), lớn hơn thì đổi cỡ
LEVELS = 5           # số mức wavelet (r = 1, 2, 4, 8, 16)
BLOCK = 16           # cạnh ô đo lệch màu, px gốc
PC_F0 = 0.15         # tần số (chu kỳ / px HD) của trọng số Gauss trong tương quan pha


# ---------- tiện ích ảnh ----------

def load_rgb(path):
    im = Image.open(path)
    if im.mode.startswith('I;16') or (im.mode == 'I' and im.getextrema()[1] > 255):
        g = np.asarray(im, dtype=np.float32) / np.float32(257)     # PNG xám 16 bit (0..65535): convert('RGB') kẹp -> trắng
        return np.repeat(np.clip(g, 0, 255)[..., None], 3, axis=2)
    return np.asarray(im.convert('RGB'), dtype=np.float32)


def luma(x):
    return x[..., 0] * np.float32(0.299) + x[..., 1] * np.float32(0.587) + x[..., 2] * np.float32(0.114)


def down4(x):
    """A: trung bình ô 4x4 (thu nhỏ theo diện tích)."""
    h, w = x.shape[0] // 4, x.shape[1] // 4
    return x.reshape(h, 4, w, 4, -1).mean(axis=(1, 3), dtype=np.float32)


def up4(x, flt):
    """U: phóng 4x từng kênh bằng Pillow trên ảnh float 'F'."""
    h, w = x.shape[:2]
    return np.stack([np.asarray(Image.fromarray(np.ascontiguousarray(x[..., c], dtype=np.float32))
                                .resize((w * 4, h * 4), flt), dtype=np.float32) for c in range(x.shape[2])], axis=-1)


def to_u8(x):
    return np.clip(np.rint(x), 0, 255).astype(np.uint8)


# ---------- bước 1: wavelet ----------

def blur(x, r):
    """B_r: lọc [1/4, 1/2, 1/4] tách được theo 2 trục, giãn cách r, biên lặp điểm ảnh."""
    p = np.pad(x, ((r, r), (0, 0), (0, 0)), mode='edge')
    x = 0.25 * p[:-2 * r] + 0.5 * p[r:-r] + 0.25 * p[2 * r:]
    p = np.pad(x, ((0, 0), (r, r), (0, 0)), mode='edge')
    return (0.25 * p[:, :-2 * r] + 0.5 * p[:, r:-r] + 0.25 * p[:, 2 * r:]).astype(np.float32)


def low_freq(x):
    for i in range(LEVELS):
        x = blur(x, 2 ** i)
    return x


def wavelet_fix(d, r):
    return (d - low_freq(d) + low_freq(r)).astype(np.float32)


# ---------- bước 2: chiếu ngược ----------

def back_project(hd, o, iters, step, flt):
    hd = np.clip(hd, 0, 255).astype(np.float32)
    for _ in range(iters):
        hd = np.clip(hd + np.float32(step) * up4(o - down4(hd), flt), 0, 255).astype(np.float32)
    return hd


# ---------- QA ----------

def box_mean(x, k):
    c = np.pad(np.cumsum(np.cumsum(x.astype(np.float64), 0), 1), ((1, 0), (1, 0)))
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def ssim(a, b, k=8):
    ya, yb = luma(a).astype(np.float64), luma(b).astype(np.float64)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    ma, mb = box_mean(ya, k), box_mean(yb, k)
    va = box_mean(ya * ya, k) - ma * ma
    vb = box_mean(yb * yb, k) - mb * mb
    cov = box_mean(ya * yb, k) - ma * mb
    m = ((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma * ma + mb * mb + c1) * (va + vb + c2))
    return float(m.mean())


def sobel_mag(y):
    p = np.pad(y.astype(np.float64), 1, mode='edge')
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    return np.hypot(gx, gy)[1:-1, 1:-1]


def edge_corr(a, b):
    ga, gb = sobel_mag(luma(a)).ravel(), sobel_mag(luma(b)).ravel()
    ga, gb = ga - ga.mean(), gb - gb.mean()
    den = np.sqrt((ga * ga).sum() * (gb * gb).sum())
    return float((ga * gb).sum() / den) if den > 0 else 0.0


def worst_block(a, o):
    """max trên ô BLOCK x BLOCK của max_kênh |trung bình(a - o)|; trả (giá trị, (x, y) góc ô ở 1x, độ lệch từng kênh)."""
    d = (a - o).astype(np.float64)
    ys, xs = np.arange(0, d.shape[0], BLOCK), np.arange(0, d.shape[1], BLOCK)
    s = np.add.reduceat(np.add.reduceat(d, ys, axis=0), xs, axis=1)
    n = np.outer(np.diff(np.append(ys, d.shape[0])), np.diff(np.append(xs, d.shape[1])))[..., None]
    m = s / n
    worst = np.abs(m).max(axis=2)
    iy, ix = np.unravel_index(int(np.argmax(worst)), worst.shape)
    return float(worst[iy, ix]), (int(xs[ix]), int(ys[iy])), [round(float(v), 2) for v in m[iy, ix]]


def psnr(a, b):
    mse = float(np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2))
    return 99.0 if mse <= 1e-10 else 10 * np.log10(255.0 ** 2 / mse)


def phase_offset(a, b):
    """Độ dời (dx, dy) px của a so với b (a(x) ~ b(x - d)) bằng tương quan pha; trả (dx, dy, độ cao đỉnh)."""
    h, w = a.shape
    win = np.outer(np.hanning(h), np.hanning(w))
    fa = np.fft.rfft2((a - a.mean()) * win)
    fb = np.fft.rfft2((b - b.mean()) * win)
    x = fa * np.conj(fb)
    amax = np.abs(x).max()
    if not amax > 0:                                  # một ảnh phẳng (đen/xám đều): không đo được -> NaN
        return float('nan'), float('nan'), 0.0
    x /= np.abs(x) + 1e-9 * amax
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.rfftfreq(w)[None, :]
    x *= np.exp(-(fx * fx + fy * fy) / (PC_F0 * PC_F0))
    r = np.fft.irfft2(x, s=(h, w))
    iy, ix = np.unravel_index(int(np.argmax(r)), r.shape)

    def sub(m1, c, p1):
        if m1 > 0 and c > 0 and p1 > 0:          # khớp Gauss (log-parabol)
            m1, c, p1 = np.log(m1), np.log(c), np.log(p1)
        den = m1 - 2 * c + p1
        return 0.0 if den == 0 else float(np.clip(0.5 * (m1 - p1) / den, -0.5, 0.5))

    dy = iy + sub(r[(iy - 1) % h, ix], r[iy, ix], r[(iy + 1) % h, ix])
    dx = ix + sub(r[iy, (ix - 1) % w], r[iy, ix], r[iy, (ix + 1) % w])
    if dy > h / 2:
        dy -= h
    if dx > w / 2:
        dx -= w
    return float(dx), float(dy), float(r[iy, ix] / r.std()) if r.std() > 0 else 0.0


def metrics(img_hd, o):
    s = down4(img_hd)
    blk, at, ch = worst_block(s, o)
    return {'psnr': round(float(psnr(s, o)), 3), 'ssim': round(ssim(s, o), 5), 'edge': round(edge_corr(s, o), 5),
            'block': round(blk, 3), 'block_at_1x': at, 'block_mean_diff_rgb': ch}


# ---------- bước 0: cỡ ảnh ----------

def fit_size(d, w4, h4, r, mode):
    """Từng trục riêng: dư 0..MAXPAD px -> cắt; khác -> đổi cỡ LANCZOS trục đó (vd. 1540x1532: cắt ngang, giãn dọc)."""
    h, w = d.shape[:2]
    if (w, h) == (w4, h4):
        return d, 'giu nguyen %dx%d' % (w, h)
    notes = []
    nw = w if 0 <= w - w4 <= MAXPAD else w4
    nh = h if 0 <= h - h4 <= MAXPAD else h4
    if (nw, nh) != (w, h):
        d = np.asarray(Image.fromarray(to_u8(d)).resize((nw, nh), Image.LANCZOS), dtype=np.float32)
        notes.append('doi co LANCZOS %dx%d -> %dx%d' % (w, h, nw, nh))
    ex, ey = nw - w4, nh - h4
    if ex or ey:
        x0, y0 = ex // 2, ey // 2
        if mode == 'topleft':
            x0, y0 = 0, 0
        elif mode == 'auto':
            dx, dy, _ = phase_offset(luma(d[y0:y0 + h4, x0:x0 + w4]), luma(r))
            if np.isfinite(dx) and np.isfinite(dy):
                x0 = int(np.clip(x0 + int(round(dx)), 0, ex))
                y0 = int(np.clip(y0 + int(round(dy)), 0, ey))
        d = d[y0:y0 + h4, x0:x0 + w4]
        notes.append('cat %dx%d -> %dx%d tai (%d,%d) [%s; cat giua = (%d,%d)]' % (nw, nh, w4, h4, x0, y0, mode, ex // 2, ey // 2))
    return d, '; '.join(notes)


# ---------- chính ----------

def main():
    ap = argparse.ArgumentParser(description='Khoa anh HD khuech tan vao mau/luoi diem anh PS1 goc + QA')
    ap.add_argument('scene')
    ap.add_argument('--in', dest='inp', required=True, help='anh khuech tan D')
    ap.add_argument('--model', required=True, help='ten dau ra: ai/<canh>_<ten>.png')
    ap.add_argument('--ref', default='realesrgan-x4plus', help='realesrgan-x4plus (ai/<canh>_<ref>.png) hoac lanczos')
    ap.add_argument('--goc', default=os.path.join(ROOT, 'work', 'upscale', 'goc'))
    ap.add_argument('--ai', default=os.path.join(ROOT, 'work', 'upscale', 'ai'))
    ap.add_argument('--iters', type=int, default=4)
    ap.add_argument('--step', type=float, default=0.5)
    ap.add_argument('--no-wavelet', action='store_true')
    ap.add_argument('--no-backproj', action='store_true')
    ap.add_argument('--crop', choices=['auto', 'center', 'topleft'], default='auto')
    ap.add_argument('--up', choices=['bicubic', 'lanczos'], default='bicubic')
    ap.add_argument('--min-psnr', type=float, default=30.0)
    ap.add_argument('--min-edge', type=float, default=0.90)
    ap.add_argument('--max-block', type=float, default=12.0)
    ap.add_argument('--min-edge-raw', type=float, default=0.80)
    ap.add_argument('--max-offset', type=float, default=1.0)
    a = ap.parse_args()

    tag = '%s %s' % (a.scene, a.model)
    if not a.model or a.model != os.path.basename(a.model) or a.model in ('.', '..'):
        print('LOI %s: --model phai la mot ten (khong co / hoac \\)' % tag)
        sys.exit(1)
    if a.iters < 0 or not 0 < a.step < 2:
        print('LOI %s: can --iters >= 0 va 0 < --step < 2 (tri rieng cua A.U nam trong (0.65, 1] -> buoc >= 2 phan ky)' % tag)
        sys.exit(1)
    o_path = os.path.normpath(os.path.join(a.goc, a.scene + '_rgb.png'))
    out_path = os.path.normpath(os.path.join(a.ai, '%s_%s.png' % (a.scene, a.model)))
    qa_path = os.path.normpath(os.path.join(a.ai, '%s_%s.qa.json' % (a.scene, a.model)))
    ref_path = None if a.ref == 'lanczos' else os.path.normpath(os.path.join(a.ai, '%s_%s.png' % (a.scene, a.ref)))
    for p, what in [(o_path, 'anh goc'), (a.inp, 'anh khuech tan --in'), (ref_path, 'anh tham chieu --ref')]:
        if p is not None and not os.path.isfile(p):
            print('LOI %s: khong thay %s: %s%s' % (tag, what, p, ' (thu --ref lanczos)' if what.endswith('--ref') else ''))
            sys.exit(1)
    for p in [ref_path, os.path.abspath(a.inp)]:
        if p is not None and os.path.normcase(os.path.abspath(p)) == os.path.normcase(os.path.abspath(out_path)):
            print('LOI %s: dau ra %s trung %s -> doi --model' % (tag, out_path, 'anh tham chieu' if p == ref_path else 'anh vao'))
            sys.exit(1)
    if os.path.exists(out_path) and not os.path.exists(qa_path):
        # ảnh không do công cụ này ghi (không có .qa.json): ví dụ ảnh Real-ESRGAN thô dùng làm tham chiếu / cho sc_hd_layers
        print('LOI %s: %s da co va khong co %s (khong phai do sc_hd_lock ghi) -> khong ghi de, doi --model' % (
            tag, out_path, os.path.basename(qa_path)))
        sys.exit(1)

    try:
        o = load_rgb(o_path)
        d0 = load_rgb(a.inp)
        r = None if ref_path is None else load_rgb(ref_path)
    except (OSError, ValueError) as e:
        print('LOI %s: khong doc duoc anh: %s' % (tag, e))
        sys.exit(1)
    h, w = o.shape[:2]
    flt = Image.BICUBIC if a.up == 'bicubic' else Image.LANCZOS
    if r is None:
        r = np.asarray(Image.fromarray(to_u8(o)).resize((w * 4, h * 4), Image.LANCZOS), dtype=np.float32)
    elif r.shape[:2] != (h * 4, w * 4):
        print('LOI %s: anh tham chieu %s co %s, can %dx%d' % (tag, ref_path, r.shape[1::-1], w * 4, h * 4))
        sys.exit(1)

    d, size_note = fit_size(d0, w * 4, h * 4, r, a.crop)
    print('%s: anh vao %s' % (tag, size_note))

    hd = d
    if not a.no_wavelet:
        hd = wavelet_fix(hd, r)
    if not a.no_backproj:
        hd = back_project(hd, o, a.iters, a.step, flt)
    hd8 = to_u8(hd)
    assert hd8.shape == (h * 4, w * 4, 3)

    m_lock = metrics(hd8.astype(np.float32), o)
    m_raw = metrics(to_u8(d).astype(np.float32), o)
    dx, dy, peak = phase_offset(luma(d), luma(r))
    off_ok = bool(np.isfinite(dx) and np.isfinite(dy))
    m_raw['offset_hd'] = [round(dx, 3), round(dy, 3)] if off_ok else None
    m_raw['offset_peak'] = round(peak, 1)

    fails = []
    if m_lock['psnr'] < a.min_psnr:
        fails.append('anh khoa: PSNR %.2f dB < %.2f' % (m_lock['psnr'], a.min_psnr))
    if m_lock['edge'] < a.min_edge:
        fails.append('anh khoa: tuong quan canh %.4f < %.2f' % (m_lock['edge'], a.min_edge))
    if m_lock['block'] > a.max_block:
        fails.append('anh khoa: lech mau o %dx%d tai %s = %.2f > %.1f (RGB %s)' % (
            BLOCK, BLOCK, m_lock['block_at_1x'], m_lock['block'], a.max_block, m_lock['block_mean_diff_rgb']))
    if m_raw['edge'] < a.min_edge_raw:
        fails.append('anh tho: tuong quan canh %.4f < %.2f (hinh bi doi/meo?)' % (m_raw['edge'], a.min_edge_raw))
    if not off_ok:
        fails.append('anh tho: khong do duoc lech hinh (anh phang?)')
    elif np.hypot(dx, dy) > a.max_offset:
        fails.append('anh tho: lech hinh toan cuc (%.2f, %.2f) px HD > %.1f (thu --crop topleft/center?)' % (dx, dy, a.max_offset))

    os.makedirs(a.ai, exist_ok=True)
    Image.fromarray(hd8).save(out_path)
    qa = {'scene': a.scene, 'model': a.model, 'input': os.path.abspath(a.inp), 'output': os.path.abspath(out_path),
          'ref': a.ref, 'size': size_note,
          'settings': {'wavelet': not a.no_wavelet, 'levels': LEVELS, 'backproj': not a.no_backproj, 'iters': a.iters,
                       'step': a.step, 'up': a.up, 'crop': a.crop, 'block': BLOCK},
          'gates': {'min_psnr': a.min_psnr, 'min_edge': a.min_edge, 'max_block': a.max_block,
                    'min_edge_raw': a.min_edge_raw, 'max_offset_hd': a.max_offset},
          'locked': m_lock, 'raw': m_raw, 'fails': fails, 'pass': not fails}
    with open(qa_path, 'w', encoding='utf-8') as f:
        json.dump(qa, f, ensure_ascii=False, indent=1)

    for name, m in [('khoa', m_lock), ('tho ', m_raw)]:
        extra = '' if 'offset_hd' not in m else '  lech hinh %s px HD' % (
            '(%.2f, %.2f)' % tuple(m['offset_hd']) if m['offset_hd'] else '?')
        print('  %s: PSNR %6.2f dB  SSIM %.4f  canh %.4f  lech mau %5.2f @%s%s' % (
            name, m['psnr'], m['ssim'], m['edge'], m['block'], m['block_at_1x'], extra))
    for e in fails:
        print('LOI %s: %s' % (tag, e))
    print('%s: QA %s | khoa PSNR %.2f canh %.3f mau %.2f | tho PSNR %.2f canh %.3f mau %.2f lech (%.1f,%.1f) | %s' % (
        tag, 'PASS' if not fails else 'FAIL', m_lock['psnr'], m_lock['edge'], m_lock['block'],
        m_raw['psnr'], m_raw['edge'], m_raw['block'], dx, dy, out_path))
    if fails:
        print('QA FAIL: anh van duoc ghi de xem: %s' % out_path)
    sys.exit(0 if not fails else 1)


if __name__ == '__main__':
    main()
