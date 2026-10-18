"""lrmkey.py — khoá hình học LRMK1 (SPEC §3.1), tính trên mô hình 'live' (tmd.parse_ccontainer).

partKey_i = SHA-1( 'P' ‖ u32 n_vert ‖ s16 xyz mỗi đỉnh ‖ u32 n_normal ‖ s16 xyz mỗi pháp tuyến ‖ u32 nPackets ‖
                   mỗi gói đã làm phẳng: u32 (header run & 0xffff0000) ‖ [u8 abr = (tpage >>> 5) & 3 nếu có texture] ‖
                   tail (có texture: data[4*vc..size); không texture: data[0..size)) )
modelKey  = SHA-1( 'LRMK1' ‖ u16 partCount ‖ partKey_0 ‖ … ‖ partKey_{n-1} )
Little-endian. Khoá không đổi qua UvAdjust (16 byte uv/clut/tpage đầu gói bị loại, abr được giữ riêng) và qua
updateTmdPacketIlen (16 bit thấp header bị loại).

Cách dùng:
  key, part_keys = model_keys(tmd.parse_ccontainer(data))     # bytes 20 + list[bytes 20]
  key_hex(data)                                               # tiện: khoá hex của byte CContainer (None nếu không phải mô hình)
"""
import hashlib
import struct

from . import tmd as _tmd

KEY_TAG = b'LRMK1'


def part_key(part):
    h = hashlib.sha1()
    h.update(b'P')
    h.update(struct.pack('<I', len(part.verts)))
    h.update(b''.join(struct.pack('<hhh', *v) for v in part.verts))
    h.update(struct.pack('<I', len(part.normals)))
    h.update(b''.join(struct.pack('<hhh', *n) for n in part.normals))
    pk = part.packets()
    h.update(struct.pack('<I', len(pk)))
    for header, d in pk:
        h.update(struct.pack('<I', header & 0xffff0000))
        pid = header >> 24 & 0xff
        if pid & 0x4:
            vc = 4 if pid & 0x8 else 3
            tpage = struct.unpack_from('<H', d, 6)[0]
            h.update(bytes((tpage >> 5 & 3,)))
            h.update(bytes(d[4 * vc:]))
        else:
            h.update(bytes(d))
    return h.digest()


def model_key(part_keys):
    """SHA-1('LRMK1' ‖ u16 partCount ‖ partKeys) -> bytes 20."""
    return hashlib.sha1(KEY_TAG + struct.pack('<H', len(part_keys)) + b''.join(part_keys)).digest()


def model_keys(model):
    """-> (modelKey bytes, [partKey bytes])."""
    pks = [part_key(p) for p in model.parts]
    return model_key(pks), pks


def key_hex(data, scan_filter=True):
    """Khoá hex (40 ký tự thường) của byte CContainer; None nếu scan_filter loại hoặc Java sẽ ném lỗi."""
    try:
        m = _tmd.parse_ccontainer(data, scan_filter=scan_filter)
    except _tmd.SpecError:
        return None
    if m is None:
        return None
    return model_keys(m)[0].hex()
