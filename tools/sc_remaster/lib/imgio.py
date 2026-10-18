"""imgio.py — PNG không cần PIL (Blender python -I không có PIL) + quy ước alpha / mip của atlas (SPEC §3.6).

Ghi (xác định): encode_png / write_png — PNG 8 bit không xen kẽ, lọc 0 mọi hàng, một IDAT, không chunk phụ.
  level = 9 (mặc định, theo đặc tả gói P1): zlib mức 9 — cùng byte với cùng bản zlib (CPython 3.14 Windows dùng
          zlib-ng, Python của Blender dùng zlib 1.3.1: byte nén KHÁC nhau giữa hai trình thông dịch, ảnh giải ra giống).
  level = None: khối deflate 'stored' — byte cố định với mọi bản zlib (dùng khi cần tên file SHA-1 tái lập được ở mọi máy).
Đọc: decode_png / read_png — thuần Python + numpy, PNG 8 bit không xen kẽ: xám, RGB, bảng màu (PLTE + tRNS), xám + alpha,
  RGBA; mọi bộ lọc 0-4 (Sub/Up theo hàng bằng numpy, Average/Paeth theo đường chéo sóng — vectơ hoá). Luôn trả uint8
  [H, W, 4] (RGBA, alpha không nhân trước). CRC từng chunk được kiểm.
  read_png(path, use_oiio=True): dùng OpenImageIO nếu có (nhanh hơn), BẮT BUỘC đặt 'oiio:UnassociatedAlpha' = 1 để OIIO
  không nhân trước alpha; không có OIIO thì về bộ đọc thuần Python.
Atlas (§3.6): file_classes, normalize_file, to_runtime (§3.6.2), mip_down / mip_chain / runtime_mips (§3.6.3), vectơ hoá.

Cách dùng:
  write_png('a.png', rgba)            # rgba uint8 [H, W, 4]
  img = read_png('a.png')             # uint8 [H, W, 4]
  mips = runtime_mips(img)            # danh sách mức đã đổi sang dạng shader cần
"""
import hashlib
import os
import struct
import zlib

import numpy as np

from . import PngError

PNG_SIG = b'\x89PNG\r\n\x1a\n'
_CTYPE_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


# ---------------------------------------------------------------- ghi
def _zlib_stored(raw):
    """Luồng zlib (RFC 1950) chỉ gồm khối 'stored' — byte cố định với mọi bản cài zlib / zlib-ng."""
    out = bytearray(b'\x78\x01')
    n = len(raw)
    pos = 0
    while True:
        chunk = raw[pos:pos + 65535]
        pos += len(chunk)
        final = pos >= n
        out += bytes((1 if final else 0,)) + struct.pack('<HH', len(chunk), len(chunk) ^ 0xFFFF) + chunk
        if final:
            break
    out += struct.pack('>I', zlib.adler32(raw) & 0xFFFFFFFF)
    return bytes(out)


def _chunk(kind, payload):
    return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & 0xFFFFFFFF)


def encode_png(img, level=9):
    """Ảnh uint8 [H, W] / [H, W, 1] xám, [H, W, 2] xám + alpha, [H, W, 3] RGB, [H, W, 4] RGBA -> byte PNG xác định."""
    a = np.asarray(img)
    if a.dtype != np.uint8:
        if a.size and (a.min() < 0 or a.max() > 255):
            raise PngError('anh khong phai uint8')
        a = a.astype(np.uint8)
    if a.ndim == 2:
        a = a[:, :, None]
    if a.ndim != 3 or a.shape[2] not in (1, 2, 3, 4):
        raise PngError('hinh dang anh %s khong ho tro' % (a.shape,))
    h, w, c = a.shape
    if h < 1 or w < 1:
        raise PngError('anh rong')
    ctype = {1: 0, 2: 4, 3: 2, 4: 6}[c]
    rows = np.ascontiguousarray(a).reshape(h, w * c)
    raw = np.zeros((h, w * c + 1), np.uint8)
    raw[:, 1:] = rows
    raw = raw.tobytes()
    data = _zlib_stored(raw) if level is None else zlib.compress(raw, level)
    return (PNG_SIG + _chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, ctype, 0, 0, 0))
            + _chunk(b'IDAT', data) + _chunk(b'IEND', b''))


def write_png(path, img, level=9, atomic=False):
    """Ghi PNG; atomic=True: ghi '<path>.tmp' rồi os.replace. -> byte đã ghi."""
    data = encode_png(img, level)
    tmp = path + '.tmp' if atomic else path
    with open(tmp, 'wb') as f:
        f.write(data)
    if atomic:
        os.replace(tmp, path)
    return data


def sha1_hex(data):
    return hashlib.sha1(data).hexdigest()


# ---------------------------------------------------------------- đọc
def png_info(data):
    """-> dict(w, h, depth, ctype, interlace) từ IHDR (không giải nén)."""
    if data[:8] != PNG_SIG:
        raise PngError('khong phai PNG')
    if len(data) < 33 or data[12:16] != b'IHDR':
        raise PngError('PNG thieu IHDR')
    w, h, depth, ctype, _c, _f, inter = struct.unpack('>IIBBBBB', data[16:29])
    return dict(w=w, h=h, depth=depth, ctype=ctype, interlace=inter)


def _paeth(a, b, c):
    p = a + b - c
    pa = np.abs(p - a)
    pb = np.abs(p - b)
    pc = np.abs(p - c)
    return np.where((pa <= pb) & (pa <= pc), a, np.where(pb <= pc, b, c))


def _unfilter(raw, h, w, bpp):
    """Giải bộ lọc PNG -> uint8 [h, w, bpp]. Lọc 0/1/2: theo hàng; có lọc 3/4: theo đường chéo (x + y = d), vì mỗi byte
    chỉ phụ thuộc trái, trên, trên-trái — mọi điểm cùng đường chéo tính được song song."""
    stride = w * bpp
    a = np.frombuffer(raw, np.uint8)
    if a.size != h * (stride + 1):
        raise PngError('PNG IDAT sai do dai (%d != %d)' % (a.size, h * (stride + 1)))
    a = a.reshape(h, stride + 1)
    ft = a[:, 0].astype(np.int64)
    data = a[:, 1:].reshape(h, w, bpp)
    if ft.size and ft.max() > 4:
        raise PngError('PNG bo loc %d' % int(ft.max()))
    if not ft.any():
        return data.copy()
    if ft.max() <= 2:
        out = np.empty((h, w, bpp), np.uint8)
        prev = np.zeros((w, bpp), np.uint8)
        for y in range(h):
            f = ft[y]
            r = data[y]
            if f == 0:
                out[y] = r
            elif f == 1:
                out[y] = np.cumsum(r, axis=0, dtype=np.uint8)
            else:
                out[y] = r + prev
            prev = out[y]
        return out
    pad = np.zeros((h + 1, w + 1, bpp), np.int32)       # pad[y + 1, x + 1] = điểm (x, y); hàng/cột 0 = 0
    for d in range(h + w - 1):
        y0 = max(0, d - w + 1)
        y1 = min(h - 1, d)
        ys = np.arange(y0, y1 + 1)
        xs = d - ys
        left = pad[ys + 1, xs]
        up = pad[ys, xs + 1]
        ul = pad[ys, xs]
        f = ft[ys][:, None]
        pred = np.select([f == 1, f == 2, f == 3, f == 4],
                         [left, up, (left + up) >> 1, _paeth(left, up, ul)], 0)
        pad[ys + 1, xs + 1] = (data[ys, xs].astype(np.int32) + pred) & 255
    return pad[1:, 1:].astype(np.uint8)


def decode_png(data):
    """PNG 8 bit không xen kẽ (xám, RGB, bảng màu, xám + alpha, RGBA) -> uint8 [H, W, 4]. PngError khi hỏng/không hỗ trợ."""
    data = bytes(data)
    if data[:8] != PNG_SIG:
        raise PngError('khong phai PNG')
    o = 8
    ihdr = None
    idat = []
    plte = trns = None
    seen_end = False
    while o + 12 <= len(data):
        ln = struct.unpack_from('>I', data, o)[0]
        kind = data[o + 4:o + 8]
        if o + 12 + ln > len(data):
            raise PngError('PNG chunk %r bi cat' % kind)
        payload = data[o + 8:o + 8 + ln]
        crc = struct.unpack_from('>I', data, o + 8 + ln)[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != crc:
            raise PngError('PNG CRC sai o chunk %r' % kind)
        o += 12 + ln
        if ihdr is None and kind != b'IHDR':
            raise PngError('PNG: chunk dau khong phai IHDR')
        if kind == b'IHDR':
            if len(payload) != 13:
                raise PngError('IHDR sai do dai')
            ihdr = struct.unpack('>IIBBBBB', payload)
        elif kind == b'PLTE':
            plte = payload
        elif kind == b'tRNS':
            trns = payload
        elif kind == b'IDAT':
            idat.append(payload)
        elif kind == b'IEND':
            seen_end = True
            break
    if ihdr is None:
        raise PngError('PNG thieu IHDR')
    if not seen_end:
        raise PngError('PNG thieu IEND')
    w, h, depth, ctype, comp, filt, inter = ihdr
    if depth != 8 or inter != 0 or ctype not in _CTYPE_CHANNELS or comp != 0 or filt != 0:
        raise PngError('PNG khong ho tro (depth %d, kieu %d, xen ke %d)' % (depth, ctype, inter))
    if w < 1 or h < 1:
        raise PngError('PNG rong')
    bpp = _CTYPE_CHANNELS[ctype]
    try:
        d = zlib.decompressobj()
        raw = d.decompress(b''.join(idat))
        raw += d.flush()
    except zlib.error as e:
        raise PngError('PNG IDAT hong: %s' % e)
    a = _unfilter(raw, h, w, bpp)
    out = np.empty((h, w, 4), np.uint8)
    if ctype == 6:
        out[:] = a
    elif ctype == 2:
        out[..., :3] = a
        out[..., 3] = 255
        if trns is not None and len(trns) >= 6:
            key = [struct.unpack_from('>H', trns, 2 * i)[0] for i in range(3)]
            out[(a[..., 0] == key[0]) & (a[..., 1] == key[1]) & (a[..., 2] == key[2]), 3] = 0
    elif ctype == 0:
        out[..., :3] = a[..., :1]
        out[..., 3] = 255
        if trns is not None and len(trns) >= 2:
            out[a[..., 0] == struct.unpack_from('>H', trns, 0)[0], 3] = 0
    elif ctype == 4:
        out[..., :3] = a[..., :1]
        out[..., 3] = a[..., 1]
    else:
        if plte is None or len(plte) % 3 or not plte:
            raise PngError('PNG bang mau thieu PLTE')
        pal = np.frombuffer(plte, np.uint8).reshape(-1, 3)
        alpha = np.full(len(pal), 255, np.uint8)
        if trns:
            t = np.frombuffer(trns, np.uint8)[:len(pal)]
            alpha[:len(t)] = t
        idx = a[..., 0]
        if idx.size and int(idx.max()) >= len(pal):
            raise PngError('PNG chi so bang mau ngoai PLTE')
        out[..., :3] = pal[idx]
        out[..., 3] = alpha[idx]
    return out


def have_oiio():
    try:
        import OpenImageIO  # noqa: F401
        return True
    except ImportError:
        return False


def read_png_oiio(path):
    """Đọc bằng OpenImageIO với 'oiio:UnassociatedAlpha' = 1 (không nhân trước alpha) -> uint8 [H, W, 4]."""
    import OpenImageIO as oiio
    cfg = oiio.ImageSpec()
    cfg.attribute('oiio:UnassociatedAlpha', 1)
    inp = oiio.ImageInput.open(path, cfg)
    if inp is None:
        raise PngError('OIIO khong mo duoc %s: %s' % (path, oiio.geterror()))
    try:
        spec = inp.spec()
        px = inp.read_image(0, 0, 0, spec.nchannels, 'uint8')
    finally:
        inp.close()
    if px is None:
        raise PngError('OIIO khong doc duoc %s' % path)
    a = np.asarray(px, np.uint8).reshape(spec.height, spec.width, spec.nchannels)
    out = np.empty((spec.height, spec.width, 4), np.uint8)
    c = spec.nchannels
    if c == 4:
        out[:] = a
    elif c == 3:
        out[..., :3] = a
        out[..., 3] = 255
    elif c == 2:
        out[..., :3] = a[..., :1]
        out[..., 3] = a[..., 1]
    elif c == 1:
        out[..., :3] = a
        out[..., 3] = 255
    else:
        raise PngError('OIIO: %d kenh' % c)
    return out


def read_png(path, use_oiio=False):
    """Đọc PNG -> uint8 [H, W, 4]. use_oiio=True: dùng OpenImageIO nếu cài được (không thì thuần Python)."""
    if use_oiio and have_oiio():
        return read_png_oiio(path)
    with open(path, 'rb') as f:
        return decode_png(f.read())


# ---------------------------------------------------------------- quy ước alpha + mip (SPEC §3.6)
def file_classes(rgba):
    """§3.6.1 bộ đọc chịu sai lệch: 0 trong suốt (A < 64), 2 STP=1 (64 <= A < 192), 1 STP=0 (A >= 192)."""
    a = np.asarray(rgba)[..., 3]
    return np.where(a < 64, 0, np.where(a < 192, 2, 1)).astype(np.uint8)


def normalize_file(rgba):
    """Đưa ảnh về đúng quy ước file: trong suốt (0,0,0,0), STP=0 A=255, STP=1 A=128."""
    rgba = np.asarray(rgba, np.uint8)
    cls = file_classes(rgba)
    out = rgba.copy()
    out[cls == 0] = 0
    out[..., 3] = np.where(cls == 1, 255, np.where(cls == 2, 128, 0))
    return out


def to_runtime(rgba):
    """§3.6.2: trong suốt -> (0,0,0,0); STP=0 -> (R,G,B,0) và (0,0,0) -> (1,1,1); STP=1 -> (R,G,B,255)."""
    rgba = np.asarray(rgba, np.uint8)
    cls = file_classes(rgba)
    out = np.zeros_like(rgba)
    rgb = rgba[..., :3]
    stp0 = cls == 1
    out[stp0, :3] = rgb[stp0]
    black0 = stp0 & (rgb.astype(np.int32).sum(-1) == 0)
    out[black0, :3] = 1
    out[stp0, 3] = 0
    stp1 = cls == 2
    out[stp1, :3] = rgb[stp1]
    out[stp1, 3] = 255
    return out


def mip_down(level):
    """§3.6.3 một bước (quy ước file, đã normalize): khối 2x2 (1x2 / 2x1 khi một chiều = 1).
    n = số texel khối, t = số trong suốt: 2t >= n -> trong suốt; ngược lại RGB = floor((Σ + floor(o/2)) / o) trên o texel
    đục, STP = 1 nếu số STP=1 >= số STP=0."""
    level = np.asarray(level, np.uint8)
    h, w = level.shape[:2]
    h2, w2 = max(1, h // 2), max(1, w // 2)
    bh = 2 if h > 1 else 1
    bw = 2 if w > 1 else 1
    lv = level[:h2 * bh, :w2 * bw]
    cls = file_classes(lv)
    n = bh * bw

    def blk(x):
        return x.reshape((h2, bh, w2, bw) + x.shape[2:]).sum(axis=(1, 3))

    opaque = cls != 0
    o = blk(opaque.astype(np.int64))
    stp1 = blk((cls == 2).astype(np.int64))
    rgb = blk(lv[..., :3].astype(np.int64) * opaque[..., None])
    keep = 2 * (n - o) < n
    os_ = np.maximum(o, 1)
    mean = (rgb + (os_ // 2)[..., None]) // os_[..., None]
    out = np.zeros((h2, w2, 4), np.uint8)
    out[keep, :3] = mean[keep].astype(np.uint8)
    out[keep, 3] = np.where(stp1 >= o - stp1, 128, 255)[keep]
    return out


def mip_chain(rgba_file):
    """Mức 0 = ảnh file đã normalize, các mức sau theo mip_down tới 1x1 (quy ước file)."""
    lv = normalize_file(rgba_file)
    chain = [lv]
    while lv.shape[0] > 1 or lv.shape[1] > 1:
        lv = mip_down(lv)
        chain.append(lv)
    return chain


def runtime_mips(rgba_file):
    """Chuỗi mip đã đổi sang dạng shader (§3.6.2) — đúng dữ liệu runtime tải lên GPU."""
    return [to_runtime(lv) for lv in mip_chain(rgba_file)]
