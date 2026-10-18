"""tim.py — TIM của PS1 và VRAM ảo 1024x512 (u16, gồm bit STP) cho bộ sinh.

Đặt TIM đúng như tools/sc_remodel/export_tmd.py (SPEC §3.3.7):
  'native'      : ảnh và CLUT tại rect gốc ghi trong TIM (load_battle) — trận (characters/<c>/textures/<form>),
                  story DRGN0 (TIM = file N+1), quái (monsters/<id>/textures/combat); không UvAdjust.
  'field_slot0' : ô sobj 0 của RetailSubmap — ảnh tại (576, 256), CLUT tại (576, 368) với kích thước của TIM
                  (load_field); mô hình phải áp UvAdjustmentMetrics14(0, 576, 256) (tmd.uv_adjust_model).
Giải mã texel đúng công thức tmd.fsh:71-89 (sample_vram) và màu 15 bit -> RGBA như export_tmd.py (c15_to_rgba).

Cách dùng:
  t = parse_tim(gf.read('characters/dart/textures/combat'))
  vram, irect, crect, adjust = virtual_vram(t, 'native')   # adjust = (576, 256) với 'field_slot0', None nếu không
"""
import struct

import numpy as np

from . import SpecError

VRAM_W, VRAM_H = 1024, 512
FIELD_SLOT0 = (576, 256)
PLACEMENTS = ('native', 'field_slot0')


class Tim:
    __slots__ = ('bpp', 'img', 'img_rect', 'clut', 'clut_rect')

    def __init__(self, bpp, img, img_rect, clut, clut_rect):
        self.bpp = bpp                  # flags & 3 (0 = 4bpp, 1 = 8bpp, 2 = 15bpp, 3 = 24bpp)
        self.img = img                  # u16 [h, w] (word VRAM)
        self.img_rect = img_rect        # (x, y, w, h) word VRAM
        self.clut = clut                # u16 [ch, cw] hoặc None
        self.clut_rect = clut_rect      # (x, y, w, h) hoặc None

    # tương thích với dict của export_tmd.py / ref_spec.py
    def __getitem__(self, k):
        return getattr(self, k)


def is_tim(data):
    return len(data) >= 8 and struct.unpack_from('<I', data, 0)[0] == 0x10


def parse_tim(data):
    """TIM: magic 0x10, flags (bpp = flags & 3, có CLUT khi flags & 8), [khối CLUT], khối ảnh. SpecError khi hỏng."""
    if len(data) < 8:
        raise SpecError('TIM qua ngan')
    magic, flags = struct.unpack_from('<II', data, 0)
    if magic != 0x10:
        raise SpecError('khong phai TIM (magic %x)' % magic)
    o = 8
    clut = clut_rect = None
    if flags & 8:
        if o + 12 > len(data):
            raise SpecError('TIM: khoi CLUT bi cat')
        ln, cx, cy, cw, ch = struct.unpack_from('<IHHHH', data, o)
        if o + 12 + cw * ch * 2 > len(data):
            raise SpecError('TIM: du lieu CLUT bi cat')
        clut = np.frombuffer(data, '<u2', cw * ch, o + 12).reshape(ch, cw).astype(np.uint16)
        clut_rect = (cx, cy, cw, ch)
        o += ln
    if o + 12 > len(data):
        raise SpecError('TIM: khoi anh bi cat')
    ln, ix, iy, iw, ih = struct.unpack_from('<IHHHH', data, o)
    if o + 12 + iw * ih * 2 > len(data):
        raise SpecError('TIM: du lieu anh bi cat')
    img = np.frombuffer(data, '<u2', iw * ih, o + 12).reshape(ih, iw).astype(np.uint16)
    return Tim(flags & 3, img, (ix, iy, iw, ih), clut, clut_rect)


def new_vram():
    return np.zeros((VRAM_H, VRAM_W), np.uint16)


def _blit(vram, x, y, arr):
    h, w = arr.shape
    if x < 0 or y < 0 or x + w > VRAM_W or y + h > VRAM_H:
        raise SpecError('rect (%d,%d %dx%d) ngoai VRAM 1024x512' % (x, y, w, h))
    vram[y:y + h, x:x + w] = arr


def place_native(vram, tim):
    """export_tmd.py load_battle: ảnh và CLUT tại rect gốc của TIM -> (rect ảnh, rect CLUT hoặc None)."""
    ix, iy, iw, ih = tim.img_rect
    _blit(vram, ix, iy, tim.img)
    crect = None
    if tim.clut is not None:
        cx, cy, cw, ch = tim.clut_rect
        _blit(vram, cx, cy, tim.clut)
        crect = (cx, cy, cw, ch)
    return (ix, iy, iw, ih), crect


def place_field_slot0(vram, tim, slot=FIELD_SLOT0):
    """export_tmd.py load_field: ô sobj 0 -> ảnh (576,256), CLUT (576,368) bất kể rect trong TIM."""
    sx, sy = slot
    ih, iw = tim.img.shape
    _blit(vram, sx, sy, tim.img)
    crect = None
    if tim.clut is not None:
        ch, cw = tim.clut.shape
        _blit(vram, sx, sy + 112, tim.clut)
        crect = (sx, sy + 112, cw, ch)
    return (sx, sy, iw, ih), crect


def virtual_vram(tim, placement):
    """VRAM ảo của bộ sinh (SPEC §3.3.7) -> (vram, rect ảnh, rect CLUT, (x, y) UvAdjust cần áp cho mô hình hoặc None)."""
    vram = new_vram()
    if placement == 'native':
        irect, crect = place_native(vram, tim)
        return vram, irect, crect, None
    if placement == 'field_slot0':
        irect, crect = place_field_slot0(vram, tim)
        return vram, irect, crect, FIELD_SLOT0
    raise ValueError('placement %r' % placement)


def placement_for(kind):
    """kind của nguồn (catalog §3.8: battle | field | story | monster) -> cách đặt TIM."""
    if kind == 'field':
        return 'field_slot0'
    if kind in ('battle', 'story', 'monster'):
        return 'native'
    raise ValueError('kind %r' % kind)


# ---------------------------------------------------------------- giải mã như tmd.fsh
def page_info(tpage):
    """-> (x trang, y trang, bpp) của tpage."""
    return (tpage & 0xf) * 64, (256 if tpage & 0x10 else 0), tpage >> 7 & 3


def sample_vram(vram, tpage, clut, u, v):
    """Giải mã texel (u, v) (mảng int) trong trang tpage với clut — đúng công thức tmd.fsh (export_tmd.py). Toạ độ VRAM
    được bọc (x & 1023, y & 511) như SPEC §3.3.2: trong VRAM thì y hệt export_tmd.py, ngoài VRAM (trang 15 + u lớn, CLUT
    8bpp sát mép phải) không ném IndexError."""
    tx, ty, bpp = page_info(tpage)
    cx, cy = (clut & 0x3f) * 16, clut >> 6
    if bpp == 0:
        idx = (vram[(ty + v) & 511, (tx + (u >> 2)) & 1023] >> ((u & 3) * 4)) & 0xf
    elif bpp == 1:
        idx = (vram[(ty + v) & 511, (tx + (u >> 1)) & 1023] >> ((u & 1) * 8)) & 0xff
    else:
        return vram[(ty + v) & 511, (tx + u) & 1023]
    return vram[cy & 511, (cx + idx) & 1023]


def c15_to_rgba(px):
    """Màu 15 bit -> RGBA8 như export_tmd.py: kênh * 255 // 31, alpha 0 khi cả 16 bit = 0 (tmd.fsh bỏ texel)."""
    px = np.asarray(px, np.uint32)
    r = (px & 31) * 255 // 31
    g = (px >> 5 & 31) * 255 // 31
    bb = (px >> 10 & 31) * 255 // 31
    a = np.where(px == 0, 0, 255)
    return np.stack([r, g, bb, a], -1).astype(np.uint8)
