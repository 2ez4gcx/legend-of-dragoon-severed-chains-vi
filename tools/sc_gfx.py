"""Sinh lớp phủ đồ hoạ tiếng Việt cho Severed Chains: out/vi_files/SECT/DRGN0.BIN/... (gói vào vi/files/ của bản phát hành).

Cách gọi:
    python tools/sc_gfx.py [--game game]
Ảnh lấy đúng từ hàm gfx.patch của dự án D:\\LOD (ảnh đã được người dùng duyệt cho bản PS1):
    DRGN0/5718  sub 0: nền màn tựa + dòng ghi công (sub 3 chữ menu tựa PS1: SC không dùng, nhưng vẫn phủ nếu đổi)
    DRGN0/6665  nhãn menu trong game (BPE)          DRGN0/6670..6673  thẻ tiêu đề chương 1..4
    DRGN0/5695  tên vùng bản đồ thế giới
Cách làm: đọc mục gốc từ đĩa 1 bản Mỹ (D:\\LOD\\paths.json), chạy gfx.patch -> mục Việt; tách cả hai như trình giải nén SC
(BPE -> giải nén; MRG -> từng mục con, mục con BPE cũng giải nén). Kiểm: dạng tách từ đĩa gốc phải TRÙNG TỪNG BYTE với file
SC đã giải nén trong <game>/files (nếu khác -> lỗi, không phủ). Ghi ra những file con khác bản gốc; file "ảo" trong
<game>/files/.../mrg (trỏ tới file thật khác) mà bản Việt lại khác file thật -> lỗi.
Lớp sửa Loader (sc-vi/src/legend/game/unpacker/Loader.java) đọc vi/files/<đường dẫn> thay cho files/<đường dẫn> nếu có.
Exit 0 = đạt.
"""
import argparse
import json
import os
import shutil
import struct
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
LOD = os.path.abspath(os.environ.get('LOD_ROOT', os.path.join(ROOT, '..', 'LOD')))
sys.path.insert(0, os.path.join(LOD, 'tools'))
sys.path.insert(0, os.path.join(LOD, 'font'))

from cdimage import Disc  # noqa: E402
import bpe  # noqa: E402
import gfx  # noqa: E402
import mrg  # noqa: E402

ENTRIES = [5718, 6665, 6670, 6671, 6672, 6673, 5695]
ARCHIVE = 'SECT/DRGN0.BIN'


def read_entry(disc, index):
    e = disc.find_record(ARCHIVE)
    hdr = disc.data(e['lba'], 1)
    n = struct.unpack_from('<I', hdr, 4)[0]
    hdr = disc.data(e['lba'], (8 + 8 * n + 2047) // 2048)
    o, s = struct.unpack_from('<II', hdr, 8 + 8 * index)
    return disc.data(e['lba'] + o, (s + 2047) // 2048)[:s]


def leaf(b):
    return bpe.decompress(b)[0] if mrg.is_bpe(b) else b


def unpack_like_sc(ent):
    """('file', bytes) hoặc ('dir', [bytes con theo chỉ số])"""
    if mrg.is_bpe(ent):
        return 'file', bpe.decompress(ent)[0]
    if mrg.is_mrg(ent):
        return 'dir', [leaf(ent[o:o + s]) if s else b'' for o, s in mrg.parse(ent)]
    return 'file', ent


def sc_dir(path):
    """{ảo: (thật, kích thước)} từ file mrg của SC"""
    m = {}
    for line in open(os.path.join(path, 'mrg'), encoding='ascii'):
        line = line.strip()
        if not line:
            continue
        v, rest = line.split('=')
        real, size = rest.split(';')
        m[int(v)] = (int(real) if real else -1, int(size))
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--game', default=os.path.join(ROOT, 'game'))
    a = ap.parse_args()
    paths = json.load(open(os.path.join(LOD, 'paths.json'), encoding='utf-8'))
    disc = Disc(os.path.join(LOD, paths['disc1']))
    files = os.path.join(a.game, 'files', 'SECT', 'DRGN0.BIN')
    out = os.path.join(ROOT, 'out', 'vi_files', 'SECT', 'DRGN0.BIN')
    shutil.rmtree(os.path.join(ROOT, 'out', 'vi_files'), ignore_errors=True)
    errors, written = [], []

    # Dòng ghi công của bản PS1 nằm ở hàng 191 của nền màn tựa: menu tựa của SC (ảnh riêng, đặt thấp hơn) đè lên
    # "About/Quit" -> không vẽ vào nền cho SC (vị trí riêng cho SC phải gửi ảnh xem trước để người dùng duyệt).
    # SCVI_CREDIT_TOP=<hàng>: vẽ dòng ghi công ở hàng đó của nền (chỉ dùng khi người dùng đã duyệt vị trí cho SC)
    if os.environ.get('SCVI_CREDIT_TOP'):
        os.environ['LOD_CREDIT_TOP'] = os.environ['SCVI_CREDIT_TOP']
        os.environ.pop('LOD_NOCREDIT', None)
    else:
        os.environ['LOD_NOCREDIT'] = '1'
    for idx in ENTRIES:
        orig = read_entry(disc, idx)
        vn = gfx.patch(ARCHIVE, idx, orig)
        if vn is None:
            errors.append('%d: gfx.patch khong doi gi (LOD_NOGFX?)' % idx)
            continue
        ko, do = unpack_like_sc(orig)
        kv, dv = unpack_like_sc(vn)
        if ko != kv:
            errors.append('%d: dang khac nhau sau khi va (%s/%s)' % (idx, ko, kv))
            continue
        sc_path = os.path.join(files, str(idx))
        if ko == 'file':
            if not os.path.isfile(sc_path) or open(sc_path, 'rb').read() != do:
                errors.append('%d: file SC khac ban tach tu dia goc' % idx)
                continue
            if dv != do:
                os.makedirs(out, exist_ok=True)
                open(os.path.join(out, str(idx)), 'wb').write(dv)
                written.append('%d (%d byte)' % (idx, len(dv)))
            continue
        m = sc_dir(sc_path)
        if len(m) != len(do) or len(dv) != len(do):
            errors.append('%d: so muc con khac (SC %d, goc %d, Viet %d)' % (idx, len(m), len(do), len(dv)))
            continue
        for v, (real, size) in m.items():
            if real == v:
                if open(os.path.join(sc_path, str(v)), 'rb').read() != do[v]:
                    errors.append('%d/%d: file SC khac ban tach tu dia goc' % (idx, v))
            elif real >= 0 and dv[v][:size] != dv[real][:size]:
                errors.append('%d/%d: muc ao (-> %d) bi doi khac file that' % (idx, v, real))
        for v, (real, size) in m.items():
            if real == v and dv[v] != do[v]:
                os.makedirs(os.path.join(out, str(idx)), exist_ok=True)
                open(os.path.join(out, str(idx), str(v)), 'wb').write(dv[v])
                written.append('%d/%d (%d byte)' % (idx, v, len(dv[v])))

    for e in errors:
        print('LOI ' + e)
    print('lop phu: %d file -> out/vi_files/SECT/DRGN0.BIN: %s' % (len(written), ', '.join(written)))
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
