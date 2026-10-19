"""Đọc/sửa tệp cấu hình config.dcnf của Severed Chains (dùng khi thử tự động: bật/tắt tùy chọn mà không phải bấm menu).

Cách gọi:
    python tools/sc_config.py [game/config.dcnf]                      in mọi mục
    python tools/sc_config.py game/config.dcnf --set lod_core:resolution=enum:NATIVE --set lod_core:show_fps=bool:1
    python tools/sc_config.py game/config.dcnf --del lod_core:game_speed
Chỉ sửa khi game đã tắt (game ghi đè tệp khi lưu tùy chọn).
Định dạng (legend.game.saves.ConfigStorage): u32 LE số mục; mỗi mục: mã (độ dài u24 LE + ASCII, FileData.writeRegistryId),
u32 LE độ dài giá trị, giá trị. Giá trị: bool = 1 byte (BoolConfigEntry), enum = độ dài u8 + tên (IoHelper.enumToBytes),
int = u32 LE (IntConfigEntry); kiểu khác in dạng hex.
"""
import argparse
import os
import struct
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')


def load(path):
    d = open(path, 'rb').read()
    n = struct.unpack_from('<I', d, 0)[0]
    off = 4
    out = []
    for _ in range(n):
        ln = int.from_bytes(d[off:off + 3], 'little')
        key = d[off + 3:off + 3 + ln].decode('ascii')
        off += 3 + ln
        vl = struct.unpack_from('<I', d, off)[0]
        off += 4
        out.append((key, d[off:off + vl]))
        off += vl
    if off != len(d):
        sys.exit('LOI: %s doc het %d/%d byte' % (path, off, len(d)))
    return out


def save(path, items):
    b = bytearray(struct.pack('<I', len(items)))
    for key, val in items:
        b += len(key).to_bytes(3, 'little') + key.encode('ascii') + struct.pack('<I', len(val)) + val
    open(path, 'wb').write(bytes(b))


def show(val):
    if len(val) >= 1 and val[0] == len(val) - 1 and all(32 <= c < 127 for c in val[1:]) and len(val) > 1:
        return 'enum:' + val[1:].decode('ascii')
    if len(val) == 1:
        return 'bool:%d' % val[0]
    if len(val) == 4:
        return 'int:%d' % struct.unpack('<i', val)[0]
    return 'hex:' + val.hex()


def parse(spec):
    kind, _, v = spec.partition(':')
    if kind == 'enum':
        return bytes([len(v)]) + v.encode('ascii')
    if kind == 'bool':
        return bytes([1 if v in ('1', 'true') else 0])
    if kind == 'int':
        return struct.pack('<i', int(v))
    if kind == 'hex':
        return bytes.fromhex(v)
    sys.exit('LOI: kieu %s (enum/bool/int/hex)' % kind)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file', nargs='?', default=os.path.join(ROOT, 'game', 'config.dcnf'))
    ap.add_argument('--set', action='append', default=[], help='ma=kieu:gia_tri')
    ap.add_argument('--del', dest='delete', action='append', default=[])
    a = ap.parse_args()
    items = load(a.file)
    if a.set or a.delete:
        d = dict(items)
        order = [k for k, _ in items]
        for s in a.set:
            key, _, spec = s.partition('=')
            if key not in d:
                order.append(key)
            d[key] = parse(spec)
        for key in a.delete:
            d.pop(key, None)
        items = [(k, d[k]) for k in order if k in d]
        save(a.file, items)
        if load(a.file) != items:
            sys.exit('LOI: doc lai khong khop')
    for key, val in items:
        print('%s = %s' % (key, show(val)))


if __name__ == '__main__':
    main()
