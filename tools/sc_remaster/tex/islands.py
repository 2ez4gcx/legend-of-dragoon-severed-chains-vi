"""islands.py — đảo UV theo CLUT cho đường texture HD (gói P3 của mô hình HD route B).

Một "đảo" (island) = các mặt có texture nối nhau qua cạnh UV chung (hoặc dùng chung texel) và dùng CÙNG một CLUT.
Texel được nhiều CLUT dùng thì mỗi CLUT có bản riêng (đảo riêng, giải mã bằng CLUT của nó). Mỗi đảo được cắt theo hộp
bao + lề 8 texel; mọi texel ngoài đảo (và texel trong suốt trong đảo) được tô bằng pull-push để mô hình AI không thấy
nội dung lạ ở mép đảo (đó là nguồn của viền sáng ở cổ áo / cẳng tay trong bản thử upscale_atlas.py: AI vẽ viền đỏ ở chỗ
đảo giáp texel không dùng). Các đảo đã đệm được xếp kệ (shelf) vào MỘT ảnh làm việc cho mỗi mô hình, cách nhau 2 x lề.

Module này là phần nền dùng chung của tools/sc_remaster/tex và qa/check_tex.py:
  - PNG: ghi xác định (zlib mức 9, lọc 0 mọi hàng), đọc PNG 8 bit không xen kẽ (xám, RGB, bảng màu, xám+alpha, RGBA;
    mọi bộ lọc 0-4), không dùng PIL. Đọc nhanh bằng OpenImageIO (Python của Blender) nếu có, đặt
    oiio:UnassociatedAlpha=1; kết quả trùng từng byte với bộ đọc thuần Python.
  - TIM + VRAM ảo: đặt ảnh / CLUT đúng rect mà export_tmd.py ghi trong JSON (source.texture_vram / clut_vram):
    trận = rect gốc của TIM, trường = ô sobj 0 (576,256) / (576,368). Lớp phủ sc-vi: <game>/../vi/files thắng files/.
  - Đọc JSON lược đồ export_tmd.py (tools/sc_remodel/export_tmd.py, cũng là lược đồ lib/export.py của P1):
    mặt có texture theo thứ tự "textured face index" g (phần theo thứ tự, rồi gói theo thứ tự đã làm phẳng — SPEC §0),
    uv atlas -> toạ độ texel tương đối TIM (tu, tv): tu = u_json, tv = v_json - khối*H (khối phụ của export xếp dưới).
  - Raster bảo thủ: texel (x, y) phủ [x, x+1) x [y, y+1) (shader: texelFetch(floor(uv)), tmd.fsh:73-89); tập texel của
    một tam giác = mọi texel mà hình tam giác ĐÓNG chạm (SAT), nên mặt suy biến (uv thẳng hàng, có thật trong dữ liệu)
    vẫn có texel. Raster tâm (tâm texel nằm trong tam giác đóng) dùng cho số liệu QA.
  - Đảo, pull-push, xếp kệ / xếp skyline (atlas cuối), ảnh làm việc 1x.

Cách gọi (từ gốc repo, PYTHONIOENCODING=utf-8; chạy được bằng python hệ thống và bằng python.exe -I của Blender):
  python tools/sc_remaster/tex/islands.py info <export.json | thư mục export> [--game game/files]
      in thống kê đảo (số đảo, kích thước ảnh làm việc), không ghi file.
  python tools/sc_remaster/tex/islands.py work <export> --out <thư mục> [--game G] [--margin 8]
      ghi work_1x.png (ảnh làm việc RGB) + islands.json để xem.
  python tools/sc_remaster/tex/islands.py selftest
      tự kiểm không cần dữ liệu game: PNG (mọi bộ lọc, mọi kiểu màu), raster SAT, pull-push, xếp kệ, đảo tổng hợp.
Exit 0 = đạt, 1 = lỗi. Chỉ đọc game/files; dữ liệu suy ra từ đĩa chỉ ghi vào nơi được chỉ định (work/upscale/sc_remaster*).
"""
import argparse
import hashlib
import json
import math
import os
import struct
import sys
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
DEFAULT_GAME = os.path.join(ROOT, 'game', 'files')

MARGIN = 8          # lề texel quanh hộp bao đảo trong ảnh làm việc 1x
EPS_BOX = 1e-6      # ô texel nửa mở [x, x+1): thu về [x, x+1-EPS_BOX] khi kiểm giao


class TexError(Exception):
    pass


def rel(p):
    """Đường dẫn để in: tương đối theo gốc repo; khác ổ đĩa thì giữ tuyệt đối."""
    try:
        return os.path.relpath(p, ROOT).replace('\\', '/')
    except ValueError:
        return os.path.abspath(p).replace('\\', '/')


def sha1_bytes(b):
    return hashlib.sha1(b).hexdigest()


def write_atomic(path, data):
    """Ghi file qua <path>.tmp rồi đổi tên (không để file dở khi bị huỷ giữa chừng)."""
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)


# ---------------------------------------------------------------- PNG (không PIL)
def _chunk(kind, payload):
    return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & 0xFFFFFFFF)


def png_write(arr, level=9):
    """PNG 8 bit không xen kẽ, lọc 0 mọi hàng, một IDAT, zlib mức 9 -> byte xác định với cùng bản zlib.
    arr: uint8 [H, W] (xám), [H, W, 3] (RGB) hoặc [H, W, 4] (RGBA)."""
    a = np.ascontiguousarray(arr, np.uint8)
    if a.ndim == 2:
        a = a[..., None]
    h, w, c = a.shape
    ctype = {1: 0, 3: 2, 4: 6}[c]
    rows = np.zeros((h, w * c + 1), np.uint8)
    rows[:, 1:] = a.reshape(h, w * c)
    return (b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, ctype, 0, 0, 0))
            + _chunk(b'IDAT', zlib.compress(rows.tobytes(), level)) + _chunk(b'IEND', b''))


def _unfilter_row(ft, line, prev, bpp):
    """Bỏ lọc một hàng PNG. line, prev: np.uint8 (cùng độ dài). Bộ lọc 0-2 bằng numpy, 3-4 vòng Python."""
    if ft == 0:
        return line
    if ft == 1:
        return np.cumsum(line.reshape(-1, bpp), axis=0, dtype=np.uint8).reshape(-1)
    if ft == 2:
        return (line + prev).astype(np.uint8)
    n = len(line)
    out = bytearray(line.tobytes())
    pv = prev.tobytes()
    if ft == 3:
        for i in range(bpp):
            out[i] = (out[i] + (pv[i] >> 1)) & 0xFF
        for i in range(bpp, n):
            out[i] = (out[i] + ((out[i - bpp] + pv[i]) >> 1)) & 0xFF
    elif ft == 4:
        for i in range(bpp):
            out[i] = (out[i] + pv[i]) & 0xFF
        for i in range(bpp, n):
            a = out[i - bpp]
            b = pv[i]
            c = pv[i - bpp]
            p = a + b - c
            pa = p - a if p > a else a - p
            pb = p - b if p > b else b - p
            pc = p - c if p > c else c - p
            out[i] = (out[i] + (a if (pa <= pb and pa <= pc) else (b if pb <= pc else c))) & 0xFF
    else:
        raise TexError('PNG bo loc %d' % ft)
    return np.frombuffer(bytes(out), np.uint8)


def png_read(data):
    """PNG 8 bit không xen kẽ -> uint8 [H, W, 4] (RGBA; ảnh không alpha có A = 255)."""
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise TexError('khong phai PNG')
    o = 8
    ihdr = None
    idat = []
    plte = trns = None
    while o + 8 <= len(data):
        ln = struct.unpack_from('>I', data, o)[0]
        kind = data[o + 4:o + 8]
        payload = data[o + 8:o + 8 + ln]
        if len(payload) != ln or o + 12 + ln > len(data):
            raise TexError('PNG bi cat o chunk %r' % kind)
        crc = struct.unpack_from('>I', data, o + 8 + ln)[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != crc:
            raise TexError('PNG CRC sai o chunk %r' % kind)
        o += 12 + ln
        if kind == b'IHDR':
            ihdr = struct.unpack('>IIBBBBB', payload)
        elif kind == b'PLTE':
            plte = payload
        elif kind == b'tRNS':
            trns = payload
        elif kind == b'IDAT':
            idat.append(payload)
        elif kind == b'IEND':
            break
    if ihdr is None:
        raise TexError('PNG thieu IHDR')
    w, h, depth, ctype, _comp, _filt, inter = ihdr
    if depth != 8 or inter != 0 or ctype not in (0, 2, 3, 4, 6):
        raise TexError('PNG khong ho tro (depth %d, kieu %d, xen ke %d)' % (depth, ctype, inter))
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    raw = np.frombuffer(zlib.decompress(b''.join(idat)), np.uint8)
    stride = w * bpp
    if raw.size != h * (stride + 1):
        raise TexError('PNG IDAT sai do dai')
    rows = raw.reshape(h, stride + 1)
    img = np.empty((h, stride), np.uint8)
    prev = np.zeros(stride, np.uint8)
    for y in range(h):
        line = _unfilter_row(int(rows[y, 0]), rows[y, 1:], prev, bpp)
        img[y] = line
        prev = img[y]
    a = img.reshape(h, w, bpp)
    out = np.zeros((h, w, 4), np.uint8)
    if ctype == 6:
        out[:] = a
    elif ctype == 2:
        out[..., :3] = a
        out[..., 3] = 255
    elif ctype == 0:
        out[..., :3] = a[..., :1]
        out[..., 3] = 255
    elif ctype == 4:
        out[..., :3] = a[..., :1]
        out[..., 3] = a[..., 1]
    else:
        if plte is None:
            raise TexError('PNG bang mau thieu PLTE')
        pal = np.frombuffer(plte, np.uint8).reshape(-1, 3)
        alpha = np.full(len(pal), 255, np.uint8)
        if trns:
            t = np.frombuffer(trns, np.uint8)[:len(pal)]
            alpha[:len(t)] = t
        idx = a[..., 0]
        if idx.max(initial=0) >= len(pal):
            raise TexError('PNG chi so bang mau ngoai pham vi')
        out[..., :3] = pal[idx]
        out[..., 3] = alpha[idx]
    return out


def _oiio_read(path):
    """Đọc PNG bằng OpenImageIO (chỉ khi import được). Trả None nếu không dùng được."""
    try:
        import OpenImageIO as oiio  # noqa: N813 (chỉ có trong Python của Blender)
    except Exception:
        return None
    try:
        spec = oiio.ImageSpec()
        spec.attribute('oiio:UnassociatedAlpha', 1)
        inp = oiio.ImageInput.open(path, spec)
        if inp is None:
            return None
        s = inp.spec()
        if s.format != oiio.UINT8 or s.nchannels not in (1, 2, 3, 4):
            inp.close()
            return None
        px = inp.read_image(0, 0, 0, s.nchannels, oiio.UINT8)
        inp.close()
        if px is None:
            return None
        a = np.asarray(px, np.uint8).reshape(s.height, s.width, s.nchannels)
        out = np.zeros((s.height, s.width, 4), np.uint8)
        if s.nchannels == 4:
            out[:] = a
        elif s.nchannels == 3:
            out[..., :3] = a
            out[..., 3] = 255
        elif s.nchannels == 2:
            out[..., :3] = a[..., :1]
            out[..., 3] = a[..., 1]
        else:
            out[..., :3] = a
            out[..., 3] = 255
        return out
    except Exception:
        return None


def png_read_file(path, allow_oiio=True):
    """Đọc PNG từ đĩa -> RGBA uint8. Ảnh lớn dùng OpenImageIO nếu có (nhanh hơn), cho ra cùng giá trị."""
    with open(path, 'rb') as f:
        data = f.read()
    if allow_oiio and len(data) > 1 << 20:
        # chỉ dùng OIIO cho PNG không bảng màu (OIIO đổi bảng màu sang RGB cũng đúng, nhưng giữ một đường duy nhất)
        if len(data) > 25 and data[25] in (0, 2, 4, 6):
            r = _oiio_read(path)
            if r is not None:
                return r
    return png_read(data)


def png_write_file(path, arr):
    data = png_write(arr)
    write_atomic(path, data)
    return data


# ---------------------------------------------------------------- màu 15 bit
def c15_to_rgb8(px):
    """Màu 15 bit PS1 -> RGB 8 bit làm tròn gần nhất (round(c5 * 255 / 31)); shader dùng c5 / 31 (tmd.fsh:79-82)."""
    px = np.asarray(px, np.int64)
    r = ((px & 31) * 255 + 15) // 31
    g = ((px >> 5 & 31) * 255 + 15) // 31
    b = ((px >> 10 & 31) * 255 + 15) // 31
    return np.stack([r, g, b], -1).astype(np.uint8)


def rgb8_to_c5(c8):
    """Ngược của cả hai cách đổi 5->8 bit (làm tròn của module này, cắt của export_tmd.py): round(c8 * 31 / 255)."""
    c8 = np.asarray(c8, np.int64)
    return (c8 * 31 + 127) // 255


# ---------------------------------------------------------------- TIM + VRAM ảo
def parse_tim(b):
    if len(b) < 20:
        raise TexError('TIM qua ngan')
    magic, flags = struct.unpack_from('<II', b, 0)
    if magic != 0x10:
        raise TexError('khong phai TIM (magic %x)' % magic)
    o = 8
    clut = clut_rect = None
    if flags & 8:
        ln, cx, cy, cw, ch = struct.unpack_from('<IHHHH', b, o)
        clut = np.frombuffer(b, '<u2', cw * ch, o + 12).reshape(ch, cw)
        clut_rect = (cx, cy, cw, ch)
        o += ln
    ln, ix, iy, iw, ih = struct.unpack_from('<IHHHH', b, o)
    img = np.frombuffer(b, '<u2', iw * ih, o + 12).reshape(ih, iw)
    return dict(bpp=flags & 3, clut=clut, clut_rect=clut_rect, img=img, img_rect=(ix, iy, iw, ih))


def game_file_path(game, relpath):
    """Lớp phủ sc-vi (sc-vi Loader.java:32-50): <game>/../vi/files/<rel> thắng <game>/<rel>."""
    parts = relpath.replace('\\', '/').split('/')
    over = os.path.join(os.path.dirname(os.path.abspath(game)), 'vi', 'files', *parts)
    if os.path.isfile(over):
        return over
    return os.path.join(game, *parts)


def resolve_game(game):
    """--game có thể là thư mục files/ hoặc thư mục game/ chứa files/."""
    if game is None:
        game = DEFAULT_GAME
    if os.path.isdir(os.path.join(game, 'files')) and not os.path.isdir(os.path.join(game, 'SECT')) \
            and not os.path.isdir(os.path.join(game, 'characters')):
        return os.path.join(game, 'files')
    return game


# ---------------------------------------------------------------- JSON lược đồ export_tmd.py
class Face:
    """Một mặt có texture: g = textured face index; tuv = góc TMD theo toạ độ texel tương đối TIM (số nguyên)."""
    __slots__ = ('g', 'part', 'prim', 'quad', 'translucent', 'layer', 'tpage', 'clut', 'uvj', 'blk', 'tuv',
                 'valid', 'reason', 'island')

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def tris(self):
        """Tam giác TmdObjLoader: (2,1,0) và (1,2,3) cho tứ giác."""
        return [(2, 1, 0)] + ([(1, 2, 3)] if self.quad else [])

    def tri_points(self):
        return [[self.tuv[c] for c in t] for t in self.tris()]


class Export:
    pass


def find_export_json(path):
    """Nhận file .json hoặc thư mục export (<dir>/<tên thư mục>.json, hoặc .json duy nhất trong thư mục)."""
    if os.path.isfile(path):
        return path
    if os.path.isdir(path):
        name = os.path.basename(os.path.normpath(path))
        cand = os.path.join(path, name + '.json')
        if os.path.isfile(cand):
            return cand
        js = sorted(f for f in os.listdir(path) if f.endswith('.json') and not f.endswith('_x4.json'))
        if len(js) == 1:
            return os.path.join(path, js[0])
    raise TexError('khong thay JSON export o %s' % path)


def load_export(path, game=None, need_tim=True):
    """Đọc JSON export_tmd.py + TIM nguồn -> Export.

    Trường dùng: name, source{texture, texture_vram, clut_vram}, atlas{W, H, bpp, extra_blocks}, atlas_size,
    parts[].faces[] {textured, quad, translucent, layer, prim, uv, tpage, clut}. _atlas.png (nếu có) chỉ để đối chiếu."""
    jpath = find_export_json(path)
    with open(jpath, 'rb') as f:
        jbytes = f.read()
    doc = json.loads(jbytes.decode('utf-8'))
    ex = Export()
    ex.json_path = jpath
    ex.json_sha1 = sha1_bytes(jbytes)
    ex.dir = os.path.dirname(jpath)
    ex.name = doc.get('name') or os.path.splitext(os.path.basename(jpath))[0]
    ex.source = doc.get('source') or {}
    at = doc.get('atlas')
    if not at:
        raise TexError('%s: mo hinh khong co texture (atlas = null)' % ex.name)
    ex.W, ex.H = int(at['W']), int(at['H'])
    ex.bpp = int(at.get('bpp', 0))
    ex.extra_blocks = [int(c, 16) for c in at.get('extra_blocks', [])]
    ex.Htot = int(doc.get('atlas_size', [ex.W, ex.H])[1])
    ex.parts = len(doc['parts'])
    faces = []
    g = 0
    for pi, part in enumerate(doc['parts']):
        for f in part['faces']:
            if not f.get('textured'):
                continue
            uvj = [(int(u), int(v)) for u, v in f['uv']]
            clut = int(f['clut'], 16)
            tpage = int(f['tpage'], 16)
            blk = 0
            if clut in ex.extra_blocks:
                b = 1 + ex.extra_blocks.index(clut)
                if min(v for _, v in uvj) >= b * ex.H:
                    blk = b
            tuv = [(u, v - blk * ex.H) for u, v in uvj]
            faces.append(Face(g=g, part=pi, prim=int(f.get('prim', -1)), quad=bool(f.get('quad', len(uvj) == 4)),
                              translucent=bool(f.get('translucent')), layer=f.get('layer', 'base'), tpage=tpage,
                              clut=clut, uvj=uvj, blk=blk, tuv=tuv, valid=True, reason='', island=-1))
            g += 1
    ex.faces = faces
    ex.n_tex = len(faces)
    ex.game = resolve_game(game)
    ex.tim = None
    ex.vram = None
    if need_tim:
        _load_tim(ex)
    _validate_faces(ex)
    ex.atlas_png = None
    ap = os.path.join(ex.dir, ex.name + '_atlas.png')
    if os.path.isfile(ap):
        ex.atlas_png = png_read_file(ap)
    return ex


def _load_tim(ex):
    src = ex.source
    if 'texture' not in src:
        raise TexError('%s: JSON thieu source.texture' % ex.name)
    tpath = game_file_path(ex.game, src['texture'])
    if not os.path.isfile(tpath):
        raise TexError('%s: khong thay TIM %s (--game?)' % (ex.name, tpath))
    with open(tpath, 'rb') as f:
        tb = f.read()
    ex.tim_path = tpath
    ex.tim_sha1 = sha1_bytes(tb)
    tim = parse_tim(tb)
    ex.tim = tim
    ix, iy, iw, ih = [int(v) for v in src.get('texture_vram', tim['img_rect'])]
    if (iw, ih) != (tim['img'].shape[1], tim['img'].shape[0]):
        raise TexError('%s: texture_vram %dx%d khac TIM %dx%d' % (ex.name, iw, ih, tim['img'].shape[1],
                                                                   tim['img'].shape[0]))
    vram = np.zeros((512, 1024), np.uint16)
    vram[iy:iy + ih, ix:ix + iw] = tim['img']
    crect = None
    if tim['clut'] is not None:
        cx, cy, cw, ch = [int(v) for v in src.get('clut_vram', tim['clut_rect'])]
        if (cw, ch) != (tim['clut'].shape[1], tim['clut'].shape[0]):
            raise TexError('%s: clut_vram khac TIM' % ex.name)
        vram[cy:cy + ch, cx:cx + cw] = tim['clut']
        crect = (cx, cy, cw, ch)
    ex.vram = vram
    ex.irect = (ix, iy, iw, ih)
    ex.crect = crect
    ppw = {0: 4, 1: 2, 2: 1}.get(tim['bpp'] & 3, 1)
    if (iw * ppw, ih) != (ex.W, ex.H):
        raise TexError('%s: atlas %dx%d khac TIM %dx%d texel' % (ex.name, ex.W, ex.H, iw * ppw, ih))
    if (tim['bpp'] & 3) != ex.bpp:
        raise TexError('%s: bpp atlas %d khac TIM %d' % (ex.name, ex.bpp, tim['bpp'] & 3))


def _validate_faces(ex):
    """Mặt không dựng được trong atlas -> valid = False (đảo bỏ qua, atlasUv = 0; lúc chạy chúng LIVE / faceHash 0)."""
    for f in ex.faces:
        bpp = f.tpage >> 7 & 3
        if bpp != ex.bpp:
            f.valid, f.reason = False, 'bpp %d khac TIM %d' % (bpp, ex.bpp)
            continue
        if any(not (0 <= u <= ex.W and 0 <= v <= ex.H) for u, v in f.tuv):
            f.valid, f.reason = False, 'uv ngoai TIM'
            continue
        if ex.vram is not None and bpp in (0, 1) and ex.crect is not None:
            cx, cy = (f.clut & 0x3F) * 16, f.clut >> 6
            n = 16 if bpp == 0 else 256
            rx, ry, rw, rh = ex.crect
            if cx < rx or cx + n > rx + rw or cy < ry or cy >= ry + rh:
                f.valid, f.reason = False, 'CLUT ngoai TIM'
                continue


def decode(ex, clut, tu, tv):
    """Texel 16 bit (gồm STP) tại toạ độ tương đối TIM (tu, tv) giải mã bằng clut (như tmd.fsh / FaceHash §3.3.3).
    Texel ngoài TIM -> 0. tu, tv: mảng int cùng hình."""
    tu = np.asarray(tu, np.int64)
    tv = np.asarray(tv, np.int64)
    out = np.zeros(tu.shape, np.uint16)
    ok = (tu >= 0) & (tu < ex.W) & (tv >= 0) & (tv < ex.H)
    if not ok.any():
        return out
    ix, iy, _, _ = ex.irect
    u = tu[ok]
    v = tv[ok]
    vram = ex.vram
    if ex.bpp == 0:
        w = vram[iy + v, ix + (u >> 2)].astype(np.int64)
        idx = (w >> ((u & 3) * 4)) & 0xF
        out[ok] = vram[(clut >> 6) & 511, ((clut & 0x3F) * 16 + idx) & 1023]
    elif ex.bpp == 1:
        w = vram[iy + v, ix + (u >> 1)].astype(np.int64)
        idx = (w >> ((u & 1) * 8)) & 0xFF
        out[ok] = vram[(clut >> 6) & 511, ((clut & 0x3F) * 16 + idx) & 1023]
    else:
        out[ok] = vram[iy + v, ix + u]
    return out


def _same_as_atlas(px, raw):
    """Điểm ảnh _atlas.png (RGBA 8 bit) có đúng là texel 15 bit raw (cùng trong suốt, cùng màu 5 bit) không."""
    transp = px[:, 3] == 0
    c5 = rgb8_to_c5(px[:, :3])
    c15 = c5[:, 0] | c5[:, 1] << 5 | c5[:, 2] << 10
    return (transp == (raw == 0)) & (transp | (c15 == (raw.astype(np.int64) & 0x7FFF)))


def check_against_atlas(ex):
    """Đối chiếu giải mã của module này với _atlas.png của export: texel phủ tâm của mỗi mặt (khối của mặt) phải có
    cùng màu 15 bit và cùng trạng thái trong suốt. -> (số texel so, số khác). Bỏ qua khi không có _atlas.png.

    Khối 0 của export chỉ giữ MỘT CLUT cho mỗi texel (CLUT "sở hữu" theo độ phủ 4/16 mẫu, export_tmd.build_atlas);
    texel tâm của một mặt mảnh có thể thuộc CLUT khác ở đó. Texel khối 0 khớp với giải mã bằng một CLUT khác của mô hình
    vì vậy không phải lỗi (đếm vào ex.atlas_other_clut); TIM / vị trí sai thì không CLUT nào khớp -> vẫn tính là khác."""
    ex.atlas_other_clut = 0
    if ex.atlas_png is None:
        return 0, 0
    a = ex.atlas_png
    cluts = sorted({f.clut for f in ex.faces if f.valid})
    tot = bad = 0
    for f in ex.faces:
        if not f.valid:
            continue
        for tri in f.tri_points():
            x0, y0, m = raster_centres(tri, ex.W, ex.H)
            if m.size == 0 or not m.any():
                continue
            yy, xx = np.nonzero(m)
            tu = xx + x0
            tv = yy + y0
            raw = decode(ex, f.clut, tu, tv)
            ay = tv + f.blk * ex.H
            if ay.max() >= a.shape[0]:
                bad += len(tu)
                continue
            px = a[ay, tu]
            same = _same_as_atlas(px, raw)
            tot += len(tu)
            if f.blk == 0 and not same.all():
                miss = np.nonzero(~same)[0]
                alt = np.zeros(len(miss), bool)
                for c in cluts:
                    if c != f.clut:
                        alt |= _same_as_atlas(px[miss], decode(ex, c, tu[miss], tv[miss]))
                ex.atlas_other_clut += int(alt.sum())
                same[miss[alt]] = True
            bad += int((~same).sum())
    return tot, bad


# ---------------------------------------------------------------- raster
def raster_conservative(tri, W, H):
    """Texel (x, y) trong [0,W) x [0,H) có ô nửa mở [x,x+1) x [y,y+1) giao tam giác ĐÓNG tri (3 điểm, toạ độ texel).
    -> (x0, y0, mask bool [h, w]). Kiểm giao bằng trục tách (SAT): trục x, y và pháp tuyến 3 cạnh; tam giác suy biến
    (đoạn thẳng / điểm) vẫn đúng."""
    P = np.asarray(tri, np.float64).reshape(3, 2)
    x0 = max(int(math.floor(P[:, 0].min())), 0)
    x1 = min(int(math.floor(P[:, 0].max())), W - 1)
    y0 = max(int(math.floor(P[:, 1].min())), 0)
    y1 = min(int(math.floor(P[:, 1].max())), H - 1)
    if x1 < x0 or y1 < y0:
        return max(x0, 0), max(y0, 0), np.zeros((0, 0), bool)
    X, Y = np.meshgrid(np.arange(x0, x1 + 1, dtype=np.float64), np.arange(y0, y1 + 1, dtype=np.float64))
    half = (1.0 - EPS_BOX) / 2.0
    CX = X + half
    CY = Y + half
    m = np.ones(X.shape, bool)
    for i in range(3):
        a = P[i]
        b = P[(i + 1) % 3]
        nx, ny = -(b[1] - a[1]), b[0] - a[0]
        if nx == 0 and ny == 0:
            continue
        proj = P[:, 0] * nx + P[:, 1] * ny
        tmin, tmax = proj.min(), proj.max()
        c = CX * nx + CY * ny
        r = half * (abs(nx) + abs(ny))
        tol = 1e-9 * (abs(nx) + abs(ny))
        m &= (c - r <= tmax + tol) & (c + r >= tmin - tol)
    return x0, y0, m


def raster_centres(tri, W, H):
    """Texel có TÂM (x+0.5, y+0.5) nằm trong tam giác đóng (tam giác suy biến: không texel nào)."""
    P = np.asarray(tri, np.float64).reshape(3, 2)
    x0 = max(int(math.floor(P[:, 0].min())), 0)
    x1 = min(int(math.ceil(P[:, 0].max())), W)
    y0 = max(int(math.floor(P[:, 1].min())), 0)
    y1 = min(int(math.ceil(P[:, 1].max())), H)
    if x1 <= x0 or y1 <= y0:
        return x0, y0, np.zeros((0, 0), bool)
    X, Y = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
    (ax, ay), (bx, by), (cx, cy) = P
    den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if den == 0:
        return x0, y0, np.zeros(X.shape, bool)
    w0 = ((by - cy) * (X - cx) + (cx - bx) * (Y - cy)) / den
    w1 = ((cy - ay) * (X - cx) + (ax - cx) * (Y - cy)) / den
    w2 = 1.0 - w0 - w1
    e = 1e-9
    return x0, y0, (w0 >= -e) & (w1 >= -e) & (w2 >= -e)


def face_texels(f, W, H, centres=False):
    """Tập texel (mảng tu, tv) của mặt: hợp các tam giác (bảo thủ hoặc theo tâm)."""
    us, vs = [], []
    fn = raster_centres if centres else raster_conservative
    for tri in f.tri_points():
        x0, y0, m = fn(tri, W, H)
        if m.size and m.any():
            yy, xx = np.nonzero(m)
            us.append(xx + x0)
            vs.append(yy + y0)
    if not us:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    k = np.unique(np.concatenate(vs).astype(np.int64) * (W + 1) + np.concatenate(us))
    return k % (W + 1), k // (W + 1)


# ---------------------------------------------------------------- đảo
class Island:
    """Đảo: id, clut, faces (danh sách g), bbox [x0, y0, x1, y1) theo toạ độ TIM, mask (texel dùng) trong bbox."""
    pass


class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            if b < a:
                a, b = b, a
            self.p[b] = a


def build_islands(ex):
    """Gom mặt hợp lệ thành đảo: cùng CLUT và (cạnh UV chung hoặc dùng chung texel). Thứ tự xác định:
    đảo xếp theo mặt nhỏ nhất (g) của nó."""
    faces = [f for f in ex.faces if f.valid]
    n = len(faces)
    uf = _UF(n)
    texels = []
    for f in faces:
        texels.append(face_texels(f, ex.W, ex.H))
    # cạnh UV chung (cùng CLUT)
    edges = {}
    for i, f in enumerate(faces):
        for t in f.tris():
            for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                pa, pb = f.tuv[a], f.tuv[b]
                if pa == pb:
                    continue
                k = (f.clut,) + (pa + pb if pa < pb else pb + pa)
                if k in edges:
                    uf.union(edges[k], i)
                else:
                    edges[k] = i
    # texel chung (cùng CLUT): sơn chỉ số mặt lên lưới theo CLUT
    grids = {}
    for i, f in enumerate(faces):
        tu, tv = texels[i]
        if len(tu) == 0:
            continue
        gr = grids.get(f.clut)
        if gr is None:
            gr = grids[f.clut] = np.full((ex.H, ex.W), -1, np.int64)
        old = gr[tv, tu]
        for j in np.unique(old[old >= 0]):
            uf.union(int(j), i)
        gr[tv, tu] = i
    groups = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)
    islands = []
    for root in sorted(groups, key=lambda r: min(faces[i].g for i in groups[r])):
        idx = groups[root]
        tu = np.concatenate([texels[i][0] for i in idx])
        tv = np.concatenate([texels[i][1] for i in idx])
        isl = Island()
        isl.id = len(islands)
        isl.clut = faces[idx[0]].clut
        isl.faces = sorted(faces[i].g for i in idx)
        if len(tu) == 0:
            # chỉ có mặt mọi góc ngoài phạm vi raster (không xảy ra với mặt hợp lệ) -> đảo 1 texel ở góc đầu
            u, v = faces[idx[0]].tuv[0]
            tu = np.array([min(u, ex.W - 1)])
            tv = np.array([min(v, ex.H - 1)])
        x0, x1 = int(tu.min()), int(tu.max()) + 1
        y0, y1 = int(tv.min()), int(tv.max()) + 1
        # bbox phải chứa mọi góc uv của mặt (góc = W/H ở mép TIM vẫn nằm trong bbox đóng)
        for i in idx:
            for u, v in faces[i].tuv:
                x0, y0 = min(x0, u), min(y0, v)
                x1, y1 = max(x1, u), max(y1, v)
        isl.bbox = (x0, y0, x1, y1)
        m = np.zeros((y1 - y0, x1 - x0), bool)
        m[tv - y0, tu - x0] = True
        isl.mask = m
        for i in idx:
            faces[i].island = isl.id
        islands.append(isl)
    return islands


# ---------------------------------------------------------------- pull-push, lan gần nhất
def _down2(c, w):
    """Một bước 'pull': khối 2x2 -> trung bình có trọng số (c đã nhân w), w = min(1, tổng w)."""
    h, wd = w.shape
    H2, W2 = (h + 1) // 2, (wd + 1) // 2
    cp = np.zeros((H2 * 2, W2 * 2) + c.shape[2:], np.float64)
    wp = np.zeros((H2 * 2, W2 * 2), np.float64)
    cp[:h, :wd] = c * w[..., None]
    wp[:h, :wd] = w
    cs = ((cp[0::2, 0::2] + cp[0::2, 1::2]) + cp[1::2, 0::2]) + cp[1::2, 1::2]
    ws = ((wp[0::2, 0::2] + wp[0::2, 1::2]) + wp[1::2, 0::2]) + wp[1::2, 1::2]
    cn = np.where(ws[..., None] > 0, cs / np.where(ws > 0, ws, 1.0)[..., None], 0.0)
    return cn, np.minimum(ws, 1.0)


def resize_bilinear(img, out_h, out_w):
    """Phóng / thu song tuyến căn theo tâm điểm ảnh (biên kẹp). img: [h, w, ...] float."""
    h, w = img.shape[:2]
    ys = (np.arange(out_h) + 0.5) * (h / out_h) - 0.5
    xs = (np.arange(out_w) + 0.5) * (w / out_w) - 0.5
    ys = np.clip(ys, 0, h - 1)
    xs = np.clip(xs, 0, w - 1)
    y0 = np.floor(ys).astype(np.int64)
    x0 = np.floor(xs).astype(np.int64)
    y1 = np.minimum(y0 + 1, h - 1)
    x1 = np.minimum(x0 + 1, w - 1)
    fy = (ys - y0)
    fx = (xs - x0)
    if img.ndim == 3:
        fy = fy[:, None, None]
        fx = fx[None, :, None]
    else:
        fy = fy[:, None]
        fx = fx[None, :]
    a = img[y0][:, x0]
    b = img[y0][:, x1]
    c = img[y1][:, x0]
    d = img[y1][:, x1]
    top = a + (b - a) * fx
    bot = c + (d - c) * fx
    return top + (bot - top) * fy


def pull_push(img, known):
    """Tô mọi điểm ảnh known = False bằng pull-push (Gortler 96): kim tự tháp trung bình có trọng số rồi đẩy xuống,
    nội suy song tuyến. img [h, w, C] float; điểm known giữ nguyên. Không có điểm known nào -> trả 0."""
    img = np.asarray(img, np.float64)
    w = known.astype(np.float64)
    if not known.any():
        return np.zeros_like(img)
    levels = [(img, w)]
    c, ww = img, w
    while c.shape[0] > 1 or c.shape[1] > 1:
        c, ww = _down2(c, ww)
        levels.append((c, ww))
    cur = levels[-1][0]
    for c, ww in reversed(levels[:-1]):
        up = resize_bilinear(cur, c.shape[0], c.shape[1])
        cur = ww[..., None] * c + (1.0 - ww[..., None]) * up
    out = cur.copy()
    out[known] = img[known]
    return out


def propagate_nearest(values, valid):
    """Lan giá trị ở ô valid sang ô chưa có theo lân cận 4 hướng (thứ tự cố định: phải, trái, xuống, lên) cho tới khi phủ
    kín. values [h, w] (hoặc [h, w, C]); -> (giá trị, valid mới). Không có ô valid nào -> giữ nguyên."""
    v = values.copy()
    ok = valid.copy()
    if not ok.any():
        return v, ok
    H, W = ok.shape
    for _ in range(H + W + 2):
        if ok.all():
            break
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            sv = np.zeros_like(ok)
            so = np.zeros_like(v)
            ys = slice(max(dy, 0), H + min(dy, 0))
            yd = slice(max(-dy, 0), H + min(-dy, 0))
            xs = slice(max(dx, 0), W + min(dx, 0))
            xd = slice(max(-dx, 0), W + min(-dx, 0))
            sv[yd, xd] = ok[ys, xs]
            so[yd, xd] = v[ys, xs]
            take = ~ok & sv
            v[take] = so[take]
            ok |= take
    return v, ok


# ---------------------------------------------------------------- xếp kệ
def shelf_pack(sizes, width, gap, align=1):
    """Xếp kệ xác định. sizes: [(w, h)] theo chỉ số; sắp theo cao giảm, rộng giảm, chỉ số tăng. Vị trí bội của align;
    khoảng cách giữa hai hình = gap (gap là bội của align thì giữ đúng). -> (vị trí [(x, y)], rộng dùng, cao dùng)
    hoặc None nếu một hình rộng hơn width."""
    order = sorted(range(len(sizes)), key=lambda i: (-sizes[i][1], -sizes[i][0], i))
    pos = [None] * len(sizes)
    x = y = shelf_h = used_w = 0

    def up(v):
        return (v + align - 1) // align * align

    for i in order:
        w, h = sizes[i]
        if w > width:
            return None
        if x > 0 and x + w > width:
            y = up(y + shelf_h + gap)
            x = 0
            shelf_h = 0
        pos[i] = (x, y)
        used_w = max(used_w, x + w)
        shelf_h = max(shelf_h, h)
        x = up(x + w + gap)
    return pos, used_w, (y + shelf_h if sizes else 0)


def skyline_pack(sizes, width, gap):
    """Xếp kiểu đường chân trời (skyline, bottom-left) xác định: sắp như shelf_pack (cao giảm, rộng giảm, chỉ số tăng);
    mỗi hình đặt ở chỗ có đáy thấp nhất (hoà -> x nhỏ nhất). Hình được nới thêm gap ở phải / dưới, khung rộng width + gap
    -> hai hình bất kỳ cách nhau >= gap, hình nằm trong [0, width). Kích thước + gap là bội của 4 thì vị trí là bội của 4.
    Thường chặt hơn xếp kệ (vd. Shana Dragoon trận: 1024x1024 thay vì 1024x2048).
    -> (vị trí [(x, y)], rộng dùng, cao dùng) hoặc None nếu một hình rộng hơn width."""
    W = width + gap
    order = sorted(range(len(sizes)), key=lambda i: (-sizes[i][1], -sizes[i][0], i))
    sky = [(0, 0, W)]                     # đoạn (x, y đáy trống, rộng), liền nhau, sắp theo x
    pos = [None] * len(sizes)
    for i in order:
        w, h = sizes[i][0] + gap, sizes[i][1] + gap
        if w > W:
            return None
        best = None
        for s in range(len(sky)):
            x = sky[s][0]
            if x + w > W:
                break
            y = 0
            rem = w
            k = s
            while rem > 0:
                y = max(y, sky[k][1])
                rem -= sky[k][2]
                k += 1
            if best is None or (y + h, x) < best[0]:
                best = ((y + h, x), x, y)
        _, x, y = best
        pos[i] = (x, y)
        new = []
        for sx, sy, sw in sky:
            e = sx + sw
            if e <= x or sx >= x + w:
                new.append((sx, sy, sw))
                continue
            if sx < x:
                new.append((sx, sy, x - sx))
            if e > x + w:
                new.append((x + w, sy, e - x - w))
        new.append((x, y + h, w))
        new.sort()
        sky = []
        for seg in new:
            if sky and sky[-1][1] == seg[1] and sky[-1][0] + sky[-1][2] == seg[0]:
                sky[-1] = (sky[-1][0], seg[1], sky[-1][2] + seg[2])
            else:
                sky.append(seg)
    used_w = max([pos[i][0] + sizes[i][0] for i in range(len(sizes))] + [0])
    used_h = max([pos[i][1] + sizes[i][1] for i in range(len(sizes))] + [0])
    return pos, used_w, used_h


def rects_separated(rects, gap):
    """Mọi cặp hình (x, y, w, h) cách nhau >= gap (theo trục x hoặc y). -> danh sách cặp (i, j) vi phạm."""
    bad = []
    for i in range(len(rects)):
        ax, ay, aw, ah = rects[i]
        for j in range(i):
            bx, by, bw, bh = rects[j]
            if not (ax >= bx + bw + gap or bx >= ax + aw + gap or ay >= by + bh + gap or by >= ay + ah + gap):
                bad.append((j, i))
    return bad


# ---------------------------------------------------------------- ảnh làm việc 1x
def island_crop(ex, isl, margin):
    """Dữ liệu 1x của đảo trên vùng cắt = bbox + lề: raw16 (giải mã bằng CLUT của đảo), mask (texel đảo), known
    (texel đảo đục), rgb8 (màu gốc), fill (pull-push RGB float), origin (x, y) của vùng cắt trong toạ độ TIM."""
    x0, y0, x1, y1 = isl.bbox
    cx0, cy0 = x0 - margin, y0 - margin
    w, h = x1 - x0 + 2 * margin, y1 - y0 + 2 * margin
    U, V = np.meshgrid(np.arange(cx0, cx0 + w), np.arange(cy0, cy0 + h))
    raw = decode(ex, isl.clut, U, V)
    mask = np.zeros((h, w), bool)
    mask[margin:margin + (y1 - y0), margin:margin + (x1 - x0)] = isl.mask
    opaque = raw != 0
    known = mask & opaque
    rgb8 = c15_to_rgb8(raw)
    fill = pull_push(rgb8.astype(np.float64), known)
    return dict(raw=raw, mask=mask, known=known, opaque=opaque, rgb8=rgb8, fill=fill, origin=(cx0, cy0), size=(w, h))


def make_work(ex, islands, margin=MARGIN):
    """Ảnh làm việc 1x: các vùng cắt (đã pull-push trong từng đảo) xếp kệ cách nhau 2*lề; khe giữa các vùng cắt tô
    pull-push lần nữa (biết = mọi điểm của vùng cắt). -> dict(rgb uint8 [H, W, 3], crops, pos)."""
    crops = [island_crop(ex, isl, margin) for isl in islands]
    sizes = [c['size'] for c in crops]
    gap = 2 * margin
    area = sum((w + gap) * (h + gap) for w, h in sizes)
    width = max([w for w, _ in sizes] + [int(math.ceil(math.sqrt(max(area, 1)) * 1.05))])
    width = (width + 3) // 4 * 4
    packed = shelf_pack(sizes, width, gap, align=1)
    pos, used_w, used_h = packed
    WW, HH = max(used_w, 1), max(used_h, 1)
    img = np.zeros((HH, WW, 3), np.float64)
    known = np.zeros((HH, WW), bool)
    for c, (px, py) in zip(crops, pos):
        w, h = c['size']
        img[py:py + h, px:px + w] = c['fill']
        known[py:py + h, px:px + w] = True
    if not known.all():
        img = pull_push(img, known)
    rgb = np.clip(np.floor(img + 0.5), 0, 255).astype(np.uint8)
    for c, (px, py) in zip(crops, pos):
        w, h = c['size']
        # vùng cắt: texel gốc chính xác ở chỗ biết, chỗ còn lại là pull-push đã làm tròn
        c['work'] = rgb[py:py + h, px:px + w]
    return dict(rgb=rgb, crops=crops, pos=pos, margin=margin)


def islands_summary(ex, islands, work=None):
    out = dict(name=ex.name, W=ex.W, H=ex.H, bpp=ex.bpp, texturedFaces=ex.n_tex,
               skipped=[dict(g=f.g, reason=f.reason) for f in ex.faces if not f.valid], islands=[])
    for i, isl in enumerate(islands):
        d = dict(id=isl.id, clut='%04x' % isl.clut, faces=isl.faces, bbox=list(isl.bbox),
                 texels=int(isl.mask.sum()))
        if work is not None:
            d['work_pos'] = list(work['pos'][i])
            d['work_size'] = list(work['crops'][i]['size'])
        out['islands'].append(d)
    if work is not None:
        out['work_size'] = [int(work['rgb'].shape[1]), int(work['rgb'].shape[0])]
    return out


# ---------------------------------------------------------------- tự kiểm
def _png_encode_filtered(img, ft):
    """Bộ mã hoá thử nghiệm áp bộ lọc ft cho mọi hàng (chỉ dùng trong selftest để kiểm bộ đọc)."""
    h, w, c = img.shape
    stride = w * c
    rows = []
    prev = np.zeros(stride, np.int64)
    for y in range(h):
        line = img[y].reshape(-1).astype(np.int64)
        left = np.concatenate([np.zeros(c, np.int64), line[:-c]])
        upleft = np.concatenate([np.zeros(c, np.int64), prev[:-c]])
        if ft == 0:
            f = line
        elif ft == 1:
            f = line - left
        elif ft == 2:
            f = line - prev
        elif ft == 3:
            f = line - ((left + prev) >> 1)
        else:
            p = left + prev - upleft
            pa, pb, pc = abs(p - left), abs(p - prev), abs(p - upleft)
            pr = np.where((pa <= pb) & (pa <= pc), left, np.where(pb <= pc, prev, upleft))
            f = line - pr
        rows.append(bytes([ft]) + (f & 0xFF).astype(np.uint8).tobytes())
        prev = line
    ctype = {1: 0, 3: 2, 4: 6}[c]
    return (b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, ctype, 0, 0, 0))
            + _chunk(b'IDAT', zlib.compress(b''.join(rows), 6)) + _chunk(b'IEND', b''))


def selftest():
    errs = []
    rng = np.random.default_rng(7)
    # PNG: mọi bộ lọc x mọi số kênh
    for c in (1, 3, 4):
        img = rng.integers(0, 256, (13, 17, c)).astype(np.uint8)
        for ft in range(5):
            r = png_read(_png_encode_filtered(img, ft))
            want = np.zeros((13, 17, 4), np.uint8)
            if c == 4:
                want[:] = img
            elif c == 3:
                want[..., :3] = img
                want[..., 3] = 255
            else:
                want[..., :3] = img
                want[..., 3] = 255
            if not np.array_equal(r, want):
                errs.append('PNG doc sai: kenh %d loc %d' % (c, ft))
        b1 = png_write(img if c != 1 else img[..., 0])
        b2 = png_write(img if c != 1 else img[..., 0])
        if b1 != b2:
            errs.append('PNG ghi khong xac dinh')
    # PNG bảng màu + tRNS
    pal = bytes(range(12))
    idx = np.array([[0, 1], [2, 3]], np.uint8)
    rows = b''.join(b'\x00' + idx[y].tobytes() for y in range(2))
    pdata = (b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 3, 0, 0, 0)) + _chunk(b'PLTE', pal)
             + _chunk(b'tRNS', b'\x00\x80') + _chunk(b'IDAT', zlib.compress(rows)) + _chunk(b'IEND', b''))
    r = png_read(pdata)
    if r[0, 0].tolist() != [0, 1, 2, 0] or r[0, 1].tolist() != [3, 4, 5, 128] or r[1, 1].tolist() != [9, 10, 11, 255]:
        errs.append('PNG bang mau sai %s' % r.reshape(-1, 4).tolist())
    # màu 15 bit
    c5 = np.arange(32)
    if not np.array_equal(rgb8_to_c5(c15_to_rgb8(c5)[:, 0]), c5) or not np.array_equal(rgb8_to_c5(c5 * 255 // 31), c5):
        errs.append('doi mau 5<->8 bit khong nghich dao')
    # raster SAT
    x0, y0, m = raster_conservative([(0, 0), (4, 0), (0, 4)], 16, 16)
    got = {(int(x + x0), int(y + y0)) for y, x in zip(*np.nonzero(m))}
    want = {(x, y) for x in range(5) for y in range(5) if x + y <= 4}
    if got != want:
        errs.append('raster tam giac sai: %s' % sorted(got ^ want))
    x0, y0, m = raster_conservative([(2, 3), (6, 3), (2, 3)], 16, 16)     # đoạn thẳng suy biến
    got = {(int(x + x0), int(y + y0)) for y, x in zip(*np.nonzero(m))}
    if got != {(x, 3) for x in range(2, 7)}:
        errs.append('raster doan suy bien sai: %s' % sorted(got))
    x0, y0, m = raster_conservative([(5, 5), (5, 5), (5, 5)], 16, 16)
    if int(m.sum()) != 1 or (x0, y0) != (5, 5):
        errs.append('raster diem sai')
    x0, y0, m = raster_conservative([(0, 0), (8, 2), (1, 8)], 16, 16)
    xc0, yc0, mc = raster_centres([(0, 0), (8, 2), (1, 8)], 16, 16)
    cons = {(int(x + x0), int(y + y0)) for y, x in zip(*np.nonzero(m))}
    cent = {(int(x + xc0), int(y + yc0)) for y, x in zip(*np.nonzero(mc))}
    if not cent <= cons or len(cent) >= len(cons):
        errs.append('raster tam khong nam trong raster bao thu')
    # pull-push: điểm biết giữ nguyên, phần còn lại hữu hạn và nằm trong khoảng giá trị biết
    img = np.zeros((20, 30, 3))
    known = np.zeros((20, 30), bool)
    img[5:9, 4:10] = [200, 10, 10]
    img[12:15, 20:25] = [10, 10, 200]
    known[5:9, 4:10] = True
    known[12:15, 20:25] = True
    f = pull_push(img, known)
    if not np.array_equal(f[known], img[known]) or not np.isfinite(f).all() or f.min() < 10 - 1e-9 \
            or f.max() > 200 + 1e-9:
        errs.append('pull-push sai')
    if not (f[2, 2, 0] > f[2, 2, 2] and f[17, 28, 2] > f[17, 28, 0]):
        errs.append('pull-push khong lan mau gan nhat')
    # lan gần nhất
    v, ok = propagate_nearest(np.array([[1, 0, 0], [0, 0, 2]]), np.array([[True, False, False], [False, False, True]]))
    if not ok.all() or v[0, 1] != 1 or v[1, 1] != 2:
        errs.append('propagate_nearest sai %s' % v.tolist())
    # xếp kệ: không chồng, cách đủ gap
    sizes = [(int(a), int(b)) for a, b in rng.integers(1, 40, (40, 2))]
    pos, uw, uh = shelf_pack(sizes, 128, 8, align=4)
    for i in range(len(sizes)):
        if pos[i][0] % 4 or pos[i][1] % 4 or pos[i][0] + sizes[i][0] > 128:
            errs.append('xep ke sai can le / rong')
        for j in range(i):
            ax0, ay0 = pos[i]
            bx0, by0 = pos[j]
            sep = (ax0 >= bx0 + sizes[j][0] + 8 or bx0 >= ax0 + sizes[i][0] + 8 or
                   ay0 >= by0 + sizes[j][1] + 8 or by0 >= ay0 + sizes[i][1] + 8)
            if not sep:
                errs.append('xep ke chong / thieu khe: %d %d' % (i, j))
    # skyline: không chồng, cách >= gap, nằm trong bề rộng, căn 4 (kích thước bội 4), xác định, có khi chặt hơn kệ
    for trial in range(20):
        sz = [(int(a) * 4, int(b) * 4) for a, b in rng.integers(1, 30, (int(rng.integers(1, 40)), 2))]
        r = skyline_pack(sz, 256, 8)
        if r is None:
            errs.append('skyline: khong xep duoc')
            continue
        pos, uw, uh = r
        rects = [(pos[i][0], pos[i][1], sz[i][0], sz[i][1]) for i in range(len(sz))]
        if rects_separated(rects, 8):
            errs.append('skyline chong / thieu khe: %s' % rects_separated(rects, 8)[:3])
        if any(x % 4 or y % 4 or x + w > 256 for x, y, w, h in rects):
            errs.append('skyline sai can le / rong')
        if uh != max(y + h for x, y, w, h in rects) or skyline_pack(sz, 256, 8) != r:
            errs.append('skyline cao dung sai / khong xac dinh')
    if skyline_pack([(300, 4)], 256, 8) is not None:
        errs.append('skyline phai tu choi hinh rong hon khung')
    if rects_separated([(0, 0, 8, 8), (12, 0, 8, 8)], 8) != [(0, 1)] or rects_separated([(0, 0, 8, 8), (16, 0, 8, 8)], 8):
        errs.append('rects_separated sai')
    for e in errs:
        print('LOI:', e)
    print('islands selftest: %s (%d loi)' % ('DAT' if not errs else 'KHONG DAT', len(errs)))
    return not errs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('info')
    p.add_argument('export')
    p.add_argument('--game')
    p.add_argument('--margin', type=int, default=MARGIN)
    p = sub.add_parser('work')
    p.add_argument('export')
    p.add_argument('--out', required=True)
    p.add_argument('--game')
    p.add_argument('--margin', type=int, default=MARGIN)
    sub.add_parser('selftest')
    a = ap.parse_args(argv)
    if a.cmd == 'selftest':
        return 0 if selftest() else 1
    ex = load_export(a.export, a.game)
    tot, bad = check_against_atlas(ex)
    isl = build_islands(ex)
    work = make_work(ex, isl, a.margin)
    s = islands_summary(ex, isl, work)
    print('%s: %d mat co texture (%d bo qua), %d dao, anh lam viec %dx%d, doi chieu _atlas.png %d texel / %d khac'
          % (ex.name, ex.n_tex, len(s['skipped']), len(isl), s['work_size'][0], s['work_size'][1], tot, bad))
    if a.cmd == 'work':
        os.makedirs(a.out, exist_ok=True)
        png_write_file(os.path.join(a.out, 'work_1x.png'), work['rgb'])
        with open(os.path.join(a.out, 'islands.json'), 'w', encoding='utf-8') as f:
            json.dump(s, f, indent=1)
        print('ghi', rel(a.out))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
