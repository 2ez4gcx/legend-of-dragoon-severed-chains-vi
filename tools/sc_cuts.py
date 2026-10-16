"""Tra số cảnh (submap cut) của Severed Chains từ vị trí script trong tr/en/strings.tsv của D:\\LOD — để nhảy tới cảnh
bằng trình debug F12 của SC (ô "Map ID" + nút "Warp to map") khi kiểm hộp thoại.

Cách gọi:
    python tools/sc_cuts.py S01012 S01089 ...      # cảnh chứa các câu (uid)
    python tools/sc_cuts.py DRGN21/0219             # cảnh dùng thư mục script này
Đầu vào: game/files/SUBMAP/NEWROOT.RDT (SC giải nén từ đĩa), D:\\LOD tr/en/strings.tsv (biến môi trường LOD_ROOT để đổi).
NEWROOT.RDT: 0x400 mục 8 byte (u16 file đầu game, u16 file cuối game, ...). Như NewRootStruct.getDrgnFile của SC:
    đĩa = (file >> 13) + 1 (DRGN21..24), thư mục cảnh = (file & 0x1fff) * 3 + 4 (đĩa 1-4), script ở thư mục + 2.
"""
import os
import struct
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
LOD = os.environ.get('LOD_ROOT', os.path.join(ROOT, '..', 'LOD'))


def cut_table():
    data = open(os.path.join(ROOT, 'game', 'files', 'SUBMAP', 'NEWROOT.RDT'), 'rb').read()
    table = {}
    for cut in range(791):   # 791..0x3ff: mục rỗng
        early, late = struct.unpack_from('<HH', data, cut * 8)
        for kind, f in (('dau', early), ('cuoi', late)):
            if f == 0xffff or (kind == 'cuoi' and f >> 13 == 1 and f & 0x1fff == early):
                continue   # không có / bản "cuối game" mặc định (đĩa 2, cùng số) mà mọi cảnh đĩa 1 đều có
            key = 'DRGN2%d/%04d' % ((f >> 13) + 1, (f & 0x1fff) * 3 + 4 + 2)
            table.setdefault(key, []).append((cut, kind))
    return table


def main():
    table = cut_table()
    pos = {}
    for line in open(os.path.join(LOD, 'tr', 'en', 'strings.tsv'), encoding='utf-8'):
        uid, _, where, text = line.rstrip('\n').split('\t')
        pos[uid] = (where, text)
    for arg in sys.argv[1:]:
        if arg in pos:
            where, text = pos[arg]
            key = where.split('/', 1)[1]
            print('%s %s cut %s  %s' % (arg, where, table.get(key, '?'), text[:70]))
        else:
            print('%s cut %s' % (arg, table.get(arg, '?')))


if __name__ == '__main__':
    main()
