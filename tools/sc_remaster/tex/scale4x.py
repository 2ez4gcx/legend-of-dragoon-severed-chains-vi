"""scale4x.py — phóng 4x không cần AI cho đường texture HD (dự phòng của Real-ESRGAN, gói P3).

Cách làm (numpy, xác định từng byte): EPX / Scale2x hai lần (mỗi điểm ảnh tách thành 2x2, góc lấy màu láng giềng khi
hai láng giềng kề bằng nhau và khác hai láng giềng còn lại — giữ nguyên màu gốc, chỉ làm tròn bậc thang chéo), rồi một
lớp lọc giữ cạnh (bilateral 5x5, sigma không gian 1.2 px, sigma màu 24 / 255) để làm mềm bậc thang mà không nhoè biên
giữa hai vùng màu khác hẳn nhau. Đầu vào là ảnh làm việc RGB của islands.py (texel ngoài đảo đã pull-push).

Dùng khi: --no-ai, không có Vulkan / Real-ESRGAN tự kiểm hỏng, Real-ESRGAN treo hoặc lỗi hai lần, hoặc một đảo có
PSNR(thu nhỏ 4x của ảnh HD, ảnh gốc) < 28 dB (hd_atlas.py).

Cách gọi:
  python tools/sc_remaster/tex/scale4x.py <vào.png> <ra.png>
  python tools/sc_remaster/tex/scale4x.py selftest
Exit 0 = đạt, 1 = lỗi. Không dùng PIL.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import islands as isl  # noqa: E402

SIGMA_S = 1.2
SIGMA_R = 24.0
RADIUS = 2


def _shift(img, dy, dx):
    """Ảnh dịch (dy, dx) với biên lặp: out[y, x] = img[clamp(y+dy), clamp(x+dx)]."""
    h, w = img.shape[:2]
    ys = np.clip(np.arange(h) + dy, 0, h - 1)
    xs = np.clip(np.arange(w) + dx, 0, w - 1)
    return img[ys][:, xs]


def _eq(a, b):
    return np.all(a == b, axis=-1)


def epx2(img):
    """Scale2x (EPX) trên ảnh uint8 [h, w, C]: so sánh màu chính xác mọi kênh."""
    P = np.asarray(img)
    A = _shift(P, -1, 0)
    B = _shift(P, 0, 1)
    C = _shift(P, 0, -1)
    D = _shift(P, 1, 0)
    ca, cd, ab, bd, db = _eq(C, A), _eq(C, D), _eq(A, B), _eq(B, D), _eq(D, B)
    e0 = np.where((ca & ~cd & ~ab)[..., None], A, P)
    e1 = np.where((ab & ~ca & ~bd)[..., None], B, P)
    e2 = np.where((cd & ~db & ~ca)[..., None], C, P)
    e3 = np.where((bd & ~ab & ~cd)[..., None], D, P)
    h, w = P.shape[:2]
    out = np.empty((h * 2, w * 2) + P.shape[2:], P.dtype)
    out[0::2, 0::2] = e0
    out[0::2, 1::2] = e1
    out[1::2, 0::2] = e2
    out[1::2, 1::2] = e3
    return out


_RANGE_LUT = {}


def _range_lut(sigma_r):
    """Bảng trọng số màu theo bình phương khoảng cách nguyên (0 .. 3*255^2), tính bằng math.exp (không phụ thuộc
    cài đặt SIMD của np.exp) để kết quả lặp lại được giữa các bản numpy."""
    lut = _RANGE_LUT.get(sigma_r)
    if lut is None:
        import math
        k = -0.5 / (sigma_r * sigma_r)
        lut = np.array([math.exp(i * k) for i in range(3 * 255 * 255 + 1)], np.float64)
        _RANGE_LUT[sigma_r] = lut
    return lut


def bilateral(img, radius=RADIUS, sigma_s=SIGMA_S, sigma_r=SIGMA_R):
    """Lọc song phương (bilateral) bằng các phép cộng từng phần tử theo thứ tự cố định (kết quả không phụ thuộc thứ tự
    rút gọn của numpy). img: uint8 [h, w, 3] -> uint8."""
    import math
    xi = np.asarray(img, np.int32)
    h, w = xi.shape[:2]
    pad = np.pad(xi, ((radius, radius), (radius, radius), (0, 0)), mode='edge')
    num = np.zeros(xi.shape, np.float64)
    den = np.zeros((h, w), np.float64)
    lut = _range_lut(sigma_r)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            ws = math.exp(-(dx * dx + dy * dy) / (2.0 * sigma_s * sigma_s))
            si = pad[radius + dy:radius + dy + h, radius + dx:radius + dx + w]
            d = si - xi
            d2 = (d[..., 0] * d[..., 0] + d[..., 1] * d[..., 1]) + d[..., 2] * d[..., 2]
            wt = ws * lut[d2]
            num += wt[..., None] * si
            den += wt
    return np.clip(np.floor(num / den[..., None] + 0.5), 0, 255).astype(np.uint8)


def scale4x(rgb):
    """RGB uint8 [h, w, 3] -> [4h, 4w, 3]: EPX hai lần + lọc giữ cạnh."""
    rgb = np.ascontiguousarray(rgb, np.uint8)[..., :3]
    return bilateral(epx2(epx2(rgb)))


def nearest4x(rgb):
    return np.repeat(np.repeat(np.asarray(rgb), 4, axis=0), 4, axis=1)


def selftest():
    errs = []
    flat = np.full((5, 7, 3), 77, np.uint8)
    if not np.array_equal(scale4x(flat), np.full((20, 28, 3), 77, np.uint8)):
        errs.append('anh mot mau phai giu nguyen')
    # đường chéo: EPX phải làm tròn bậc thang (góc trong nhận màu láng giềng)
    d = np.zeros((4, 4, 3), np.uint8)
    for i in range(4):
        d[i, i] = 255
    e = epx2(d)
    if e.shape != (8, 8, 3) or not (e[1, 2] == 255).all() or not (e[0, 0] == 255).all():
        errs.append('EPX sai tren duong cheo')
    if e[0, 7].any():
        errs.append('EPX lan mau sai cho')
    rng = np.random.default_rng(3)
    img = rng.integers(0, 256, (16, 12, 3)).astype(np.uint8)
    a = scale4x(img)
    b = scale4x(img.copy())
    if a.shape != (64, 48, 3) or not np.array_equal(a, b):
        errs.append('scale4x khong xac dinh / sai kich thuoc')
    # thu nhỏ 4x (trung bình khối) phải gần ảnh gốc trên ảnh khối lớn
    blk = np.repeat(np.repeat(rng.integers(0, 256, (6, 6, 3)), 3, 0), 3, 1).astype(np.uint8)
    s = scale4x(blk).astype(np.float64)
    down = s.reshape(18, 4, 18, 4, 3).mean((1, 3))
    mse = ((down - blk) ** 2).mean()
    psnr = 10 * np.log10(255 * 255 / max(mse, 1e-9))
    if psnr < 24:
        errs.append('scale4x PSNR qua thap %.1f' % psnr)
    if 'PIL' in sys.modules:
        errs.append('PIL da bi import')
    for e in errs:
        print('LOI:', e)
    print('scale4x selftest: %s (PSNR khoi %.1f dB)' % ('DAT' if not errs else 'KHONG DAT', psnr))
    return not errs


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ['selftest']:
        return 0 if selftest() else 1
    if len(argv) != 2:
        print(__doc__)
        return 1
    src = isl.png_read_file(argv[0])
    out = scale4x(src[..., :3])
    isl.png_write_file(argv[1], out)
    print('scale4x: %dx%d -> %dx%d' % (src.shape[1], src.shape[0], out.shape[1], out.shape[0]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
