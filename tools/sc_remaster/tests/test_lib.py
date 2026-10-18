"""test_lib.py — tự kiểm thư viện tools/sc_remaster/lib (gói P1) và scan.py. Exit 0 = đạt, 1 = lỗi.

Phần không cần dữ liệu game (luôn chạy):
  FNV-1a32; PNG (ghi xác định zlib 9 / 'stored', đọc mọi bộ lọc 0-4, xám / xám+alpha / RGB / RGBA / bảng màu + tRNS,
  CRC hỏng bị từ chối, so với OpenImageIO nếu có); alpha + mip (SPEC §3.6); mô hình tổng hợp spec/sample_cube
  (khoá, giải mã mặt, FaceHash 5 TIM, giá trị lưu, LIVE, xác minh, lưới retail / VRAM / ATLAS 16 float, mip atlas);
  LRM1 (round-trip sample_cube.lrm trùng byte, >= 20 lỗi gieo bị từ chối, kiểm runtime, thân deflate, part_from_arrays);
  index.tsv; gamefiles trên cây game giả (mrg ảo, 'không có file', lớp phủ sc-vi, thứ tự không mrg, mrg sai).
Phần dùng game/files (bỏ qua bằng --no-game):
  spec/vectors.json (43 mô hình: khoá, số đếm, véc-tơ FaceHash thô, LIVE, mặt ngoài TIM); khoá mọi file trường
  (6722 -> 551); export.py so với tools/sc_remodel/export_tmd.py cho Dart trận và DRGN21.BIN/26 obj 0 (JSON / .bin /
  .mtl / .gltf / .obj trùng byte, PNG trùng điểm ảnh); hoạt cảnh; mrg thật; scan.run_scan (mọi mẫu vectors có biến thể
  trùng véc-tơ thô; --quick bỏ qua); kiểm chỉ-đọc (SHA-256 file mẫu trước/sau).
Cuối cùng: 'PIL' KHÔNG có trong sys.modules.

Cách gọi (từ gốc repo; PYTHONIOENCODING=utf-8):
  python tools/sc_remaster/tests/test_lib.py [--game game] [--no-game] [--quick] [--pilot-ref DIR] [--pilot-python EXE]
  deps/blender/blender-5.2.2-windows-x64/5.2/python/bin/python.exe -I tools/sc_remaster/tests/test_lib.py
Bản tham chiếu của export_tmd.py (cần PIL) nằm ở work/upscale/sc_remaster_p1/pilot_ref/<tên>/ kèm STAMP (SHA-1 của
export_tmd.py); thiếu hoặc cũ thì test tự tạo lại bằng một Python có PIL (--pilot-python, biến LODSC_PILOT_PYTHON, hoặc
'python' / 'py' trong PATH). File tạm chỉ ghi dưới work/upscale/sc_remaster_p1/ (git bỏ qua) và thư mục tạm hệ thống.
"""
import argparse
import filecmp
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
if PKG not in sys.path:
    sys.path.insert(0, PKG)

import numpy as np  # noqa: E402

from lib import (DEFAULT_WORK, ROOT, GameFileError, LrmError, PngError, anims, export, facehash,  # noqa: E402
                 gamefiles, imgio, lrm, lrmkey, tim as timlib, tmd, utf8_stdio)

SPEC_DIR = os.path.join(PKG, 'spec')
PILOT = os.path.join(ROOT, 'tools', 'sc_remodel', 'export_tmd.py')


class Checker:
    def __init__(self):
        self.fail = 0
        self.ok = 0
        self.skipped = []

    def check(self, name, cond, detail=''):
        if cond:
            self.ok += 1
        else:
            self.fail += 1
            print('  LOI  %s %s' % (name, detail))
        return bool(cond)

    def section(self, title):
        print('== ' + title)

    def skip(self, name, why):
        self.skipped.append((name, why))
        print('  BO QUA %s: %s' % (name, why))


def sha1(b):
    return hashlib.sha1(b).hexdigest()


# ================================================================= không cần dữ liệu game
def test_fnv(T):
    T.section('FNV-1a32')
    T.check('fnv rong', facehash.fnv1a32(b'') == 0x811C9DC5)
    T.check('fnv a', facehash.fnv1a32(b'a') == 0xE40C292C)
    T.check('fnv foobar', facehash.fnv1a32(b'foobar') == 0xBF9CF968)


def _filtered_png(img, ctype, plte=None, trns=None, filters=None):
    """Bộ mã hoá PNG riêng cho test: hàng y dùng bộ lọc filters[y] (0-4), để kiểm bộ đọc."""
    a = np.asarray(img, np.uint8)
    if a.ndim == 2:
        a = a[:, :, None]
    h, w, c = a.shape
    rows = a.reshape(h, w * c).astype(np.int32)
    out = bytearray()
    for y in range(h):
        f = filters[y] if filters is not None else y % 5
        x = rows[y]
        left = np.concatenate([np.zeros(c, np.int32), x[:-c]])
        up = rows[y - 1] if y else np.zeros_like(x)
        ul = np.concatenate([np.zeros(c, np.int32), up[:-c]])
        if f == 0:
            pred = np.zeros_like(x)
        elif f == 1:
            pred = left
        elif f == 2:
            pred = up
        elif f == 3:
            pred = (left + up) >> 1
        else:
            p = left + up - ul
            pa, pb, pc = np.abs(p - left), np.abs(p - up), np.abs(p - ul)
            pred = np.where((pa <= pb) & (pa <= pc), left, np.where(pb <= pc, up, ul))
        out.append(f)
        out += ((x - pred) & 255).astype(np.uint8).tobytes()

    def chunk(k, p):
        return struct.pack('>I', len(p)) + k + p + struct.pack('>I', zlib.crc32(k + p) & 0xFFFFFFFF)
    data = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, ctype, 0, 0, 0))
    if plte is not None:
        data += chunk(b'PLTE', plte)
    if trns is not None:
        data += chunk(b'tRNS', trns)
    z = zlib.compress(bytes(out), 6)
    data += chunk(b'IDAT', z[:len(z) // 2]) + chunk(b'IDAT', z[len(z) // 2:])     # hai IDAT
    return data + chunk(b'IEND', b'')


def test_png(T, tmpdir):
    T.section('PNG (imgio)')
    rng = np.random.RandomState(1234)
    rgba = rng.randint(0, 256, (37, 29, 4)).astype(np.uint8)
    smooth = (np.add.outer(np.arange(37), np.arange(29)) * 3 % 256).astype(np.uint8)
    rgba[..., 1] = smooth
    for level in (9, None):
        b1 = imgio.encode_png(rgba, level)
        b2 = imgio.encode_png(rgba, level)
        T.check('ghi xac dinh level=%s' % level, b1 == b2)
        T.check('doc lai RGBA level=%s' % level, np.array_equal(imgio.decode_png(b1), rgba))
        info = imgio.png_info(b1)
        T.check('IHDR level=%s' % level, (info['w'], info['h'], info['depth'], info['ctype']) == (29, 37, 8, 6))
    # các kênh khác
    exp = np.zeros((37, 29, 4), np.uint8)
    exp[..., :3] = rgba[..., :1]
    exp[..., 3] = 255
    T.check('ghi/doc xam', np.array_equal(imgio.decode_png(imgio.encode_png(rgba[..., 0])), exp))
    exp2 = exp.copy()
    exp2[..., 3] = rgba[..., 3]
    T.check('ghi/doc xam+alpha', np.array_equal(imgio.decode_png(imgio.encode_png(rgba[..., [0, 3]])), exp2))
    exp3 = rgba.copy()
    exp3[..., 3] = 255
    T.check('ghi/doc RGB', np.array_equal(imgio.decode_png(imgio.encode_png(rgba[..., :3])), exp3))
    # bộ lọc 0-4 (mọi hàng xen kẽ), nhiều IDAT
    files = {}
    for big in (False, True):
        img = rgba if not big else np.tile(rgba, (3, 5, 1))
        tag = 'lon' if big else 'nho'
        d = _filtered_png(img, 6)
        files['rgba_' + tag] = (d, img)
        T.check('loc 0-4 RGBA %s' % tag, np.array_equal(imgio.decode_png(d), img))
    d = _filtered_png(rgba[..., :3], 2)
    T.check('loc 0-4 RGB', np.array_equal(imgio.decode_png(d), exp3))
    files['rgb'] = (d, exp3)
    d = _filtered_png(rgba[..., 0], 0, filters=[(y * 3) % 5 for y in range(37)])
    T.check('loc 0-4 xam', np.array_equal(imgio.decode_png(d), exp))
    d = _filtered_png(rgba[..., [0, 3]], 4)
    T.check('loc 0-4 xam+alpha', np.array_equal(imgio.decode_png(d), exp2))
    files['ga'] = (d, exp2)
    d = _filtered_png(rgba[..., :3], 2, filters=[1, 2] * 18 + [1])
    T.check('loc chi Sub/Up', np.array_equal(imgio.decode_png(d), exp3))
    # bảng màu + tRNS
    pal = rng.randint(0, 256, (40, 3)).astype(np.uint8)
    alpha = rng.randint(0, 256, 25).astype(np.uint8)
    idx = rng.randint(0, 40, (37, 29)).astype(np.uint8)
    expp = np.zeros((37, 29, 4), np.uint8)
    expp[..., :3] = pal[idx]
    full_a = np.full(40, 255, np.uint8)
    full_a[:25] = alpha
    expp[..., 3] = full_a[idx]
    d = _filtered_png(idx, 3, plte=pal.tobytes(), trns=alpha.tobytes())
    T.check('bang mau + tRNS', np.array_equal(imgio.decode_png(d), expp))
    files['pal'] = (d, expp)
    # hỏng
    good = imgio.encode_png(rgba)
    bad = bytearray(good)
    bad[60] ^= 0xFF
    for name, b in (('CRC', bytes(bad)), ('chu ky', b'x' + good[1:]), ('cat cut', good[:-20])):
        try:
            imgio.decode_png(b)
            T.check('tu choi PNG hong (%s)' % name, False)
        except PngError:
            T.check('tu choi PNG hong (%s)' % name, True)
    interlaced = bytearray(good)
    ih = bytearray(interlaced[16:29])
    ih[12] = 1
    interlaced[16:29] = ih
    interlaced[29:33] = struct.pack('>I', zlib.crc32(b'IHDR' + bytes(ih)) & 0xFFFFFFFF)
    try:
        imgio.decode_png(bytes(interlaced))
        T.check('tu choi PNG xen ke', False)
    except PngError:
        T.check('tu choi PNG xen ke', True)
    # write_png + read_png + OIIO
    p = os.path.join(tmpdir, 'a.png')
    imgio.write_png(p, rgba, atomic=True)
    T.check('write_png/read_png', np.array_equal(imgio.read_png(p), rgba) and not os.path.exists(p + '.tmp'))
    if imgio.have_oiio():
        for k, (d, want) in sorted(files.items()):
            fp = os.path.join(tmpdir, 'oiio_%s.png' % k)
            with open(fp, 'wb') as f:
                f.write(d)
            got = imgio.read_png_oiio(fp)
            T.check('OIIO (UnassociatedAlpha) == thuan Python: %s' % k, np.array_equal(got, want),
                    'khac %d texel' % int((got != want).any(-1).sum()) if got.shape == want.shape else str(got.shape))
        T.check('read_png(use_oiio)', np.array_equal(imgio.read_png(p, use_oiio=True), rgba))
    else:
        T.skip('OIIO', 'khong co OpenImageIO trong trinh thong dich nay')


def test_mip(T):
    T.section('alpha + mip (SPEC §3.6)')
    img = np.zeros((2, 4, 4), np.uint8)
    img[0, 0] = (0, 0, 0, 255)
    img[0, 1] = (10, 20, 30, 128)
    img[1, 0] = (40, 50, 60, 255)
    img[1, 1] = (0, 0, 0, 0)
    img[0, 2] = (9, 9, 9, 0)
    img[0, 3] = (0, 0, 0, 0)
    img[1, 2] = (100, 100, 100, 255)
    img[1, 3] = (0, 0, 0, 0)
    rt = imgio.to_runtime(img)
    T.check('to_runtime', tuple(rt[0, 0]) == (1, 1, 1, 0) and tuple(rt[0, 1]) == (10, 20, 30, 255)
            and tuple(rt[0, 2]) == (0, 0, 0, 0) and tuple(rt[1, 2]) == (100, 100, 100, 0), rt[0].tolist())
    ch = imgio.mip_chain(img)
    T.check('mip kich thuoc', [c.shape[:2] for c in ch] == [(2, 4), (1, 2), (1, 1)])
    T.check('mip khoi trai', tuple(ch[1][0, 0]) == (17, 23, 30, 255), ch[1][0, 0].tolist())
    T.check('mip khoi phai (3 trong suot)', tuple(ch[1][0, 1]) == (0, 0, 0, 0))
    tie = np.array([[[10, 10, 10, 255], [20, 20, 20, 128]], [[30, 30, 30, 255], [40, 40, 40, 128]]], np.uint8)
    T.check('mip hoa STP -> 1', tuple(imgio.mip_chain(tie)[1][0, 0]) == (25, 25, 25, 128))
    one_t = np.array([[[0, 0, 0, 0], [8, 8, 8, 255]]], np.uint8)
    T.check('mip 1x2 nua trong suot', tuple(imgio.mip_chain(one_t)[1][0, 0]) == (0, 0, 0, 0))
    col = np.array([[[8, 8, 8, 255]], [[3, 3, 3, 200]]], np.uint8)
    T.check('mip 2x1', tuple(imgio.mip_chain(col)[1][0, 0]) == (6, 6, 6, 255))
    # đối chiếu cách cài vòng lặp theo đúng văn bản SPEC trên ảnh ngẫu nhiên, kích thước không vuông
    rng = np.random.RandomState(7)
    r = rng.randint(0, 256, (16, 8, 4)).astype(np.uint8)
    r[..., 3] = rng.choice([0, 30, 100, 128, 200, 255], (16, 8))
    T.check('mip vecto hoa == vong lap SPEC', all(np.array_equal(a, b) for a, b in
                                                   zip(imgio.mip_chain(r), _mip_chain_loop(r))))
    T.check('mip chuoi toi 1x1', imgio.mip_chain(r)[-1].shape[:2] == (1, 1) and len(imgio.mip_chain(r)) == 5)


def _mip_chain_loop(rgba):
    """Cài đặt từng texel theo đúng câu chữ SPEC §3.6.3 (đối chứng)."""
    lv = imgio.normalize_file(rgba)
    out = [lv]
    while lv.shape[0] > 1 or lv.shape[1] > 1:
        h, w = lv.shape[:2]
        h2, w2 = max(1, h // 2), max(1, w // 2)
        cls = imgio.file_classes(lv)
        nx = np.zeros((h2, w2, 4), np.uint8)
        for y in range(h2):
            for x in range(w2):
                cells = [(yy, xx) for yy in (2 * y, 2 * y + 1) if yy < h for xx in (2 * x, 2 * x + 1) if xx < w]
                n = len(cells)
                op = [c for c in cells if cls[c] != 0]
                if 2 * (n - len(op)) >= n:
                    continue
                o = len(op)
                nx[y, x, :3] = [(sum(int(lv[c][k]) for c in op) + o // 2) // o for k in range(3)]
                s1 = sum(1 for c in op if cls[c] == 2)
                nx[y, x, 3] = 128 if s1 >= o - s1 else 255
        lv = nx
        out.append(lv)
    return out


def _mesh_sha(m):
    return (m['cls'], bool(m['textured']), bool(m['translucent']), m['translucency'], len(m['vertices']) // 16,
            len(m['indices']), sha1(np.asarray(m['vertices'], '<f4').tobytes()),
            sha1(np.asarray(m['indices']).astype('<u4').tobytes()))


def _json_mesh_sha(m):
    return (m['cls'], m['textured'], m['translucent'], m['translucency'], m['vertexCount'], m['indexCount'],
            m['verticesSha1'], m['indicesSha1'])


def test_sample_cube(T, tmpdir):
    T.section('mo hinh tong hop spec/sample_cube')
    with open(os.path.join(SPEC_DIR, 'sample_cube.json'), encoding='utf-8') as f:
        J = json.load(f)
    cc = bytes.fromhex(J['files']['ccontainer']['hex'])
    T.check('ccontainer sha1', sha1(cc) == J['files']['ccontainer']['sha1'])
    tims = {k: bytes.fromhex(v['hex']) for k, v in J['files']['tims'].items()}
    model = tmd.parse_ccontainer(cc)
    key, pks = lrmkey.model_keys(model)
    T.check('modelKey', key.hex() == J['keys']['modelKey'])
    T.check('partKeys', [k.hex() for k in pks] == J['keys']['partKeys'])
    T.check('srcFaceCount', model.src_face_counts() == J['srcFaceCount'])
    T.check('key_hex', lrmkey.key_hex(cc) == J['keys']['modelKey'])
    tmd.uv_adjust_model(model, J['runtime']['tpageX'], J['runtime']['tpageY'])
    T.check('khoa khong doi sau UvAdjust', lrmkey.model_keys(model)[0] == key)
    # gói G3 có đèn mang cờ 'không pháp tuyến' (0x10000): primitivePacketSize = 12 byte nhưng TmdObjLoader đọc 16
    # -> Java ném ArrayIndexOutOfBounds; Python phải ném SpecError (không phải struct.error / IndexError)
    hdr = 0x30010000 | 1
    sz = tmd.packet_size(hdr)
    bad_part = tmd.Part(0, [(0, 0, 0)] * 3, [], [tmd.Run(0, hdr, sz, [bytearray(sz)])], 1, 0, (0, 0, 0, 0, 0, 0))
    try:
        tmd.decode_faces(bad_part)
        T.check('goi ngan hon giai ma -> SpecError', False)
    except tmd.SpecError:
        T.check('goi ngan hon giai ma -> SpecError', sz == 12)
    except Exception as e:
        T.check('goi ngan hon giai ma -> SpecError', False, '%s: %s' % (type(e).__name__, e))
    vr = timlib.new_vram()
    vr[511, 1023] = 7
    T.check('sample_vram boc toa do (x & 1023, y & 511)',
            int(timlib.sample_vram(vr, 0x11f, 0, np.array([1087]), np.array([767]))[0]) == 7
            and int(timlib.sample_vram(vr, 0x11f, 0, np.array([63]), np.array([255]))[0]) == 7)
    T.check('texAnimRects', [list(r) for r in facehash.anim_rects(model)] == J['runtime']['texAnimRects'])
    all_faces, backs = tmd.model_faces(model)
    tex = tmd.textured_faces(all_faces)
    T.check('texturedFaceCount', len(tex) == J['texturedFaceCount'])
    bad = []
    for pi, pj in enumerate(J['parts']):
        if backs[pi] != pj['backfaceCulling']:
            bad.append('backface %d' % pi)
        for f, fj in zip(all_faces[pi], pj['faces']):
            got = dict(srcFace=f.index, header='%08x' % f.header, quad=f.quad, textured=f.textured,
                       translucent=f.translucent, lit=f.lit, coloured=f.coloured, flags=f.flags,
                       meshClass=tmd.class_name(f.mclass), vertexIndices=f.vidx)
            if f.textured:
                got.update(tpage=f.tpage, clut=f.clut, uv=[list(x) for x in f.uv], footprint=list(facehash.footprint(f)))
            for k, v in got.items():
                if fj[k] != v:
                    bad.append('phan %d mat %d %s: %r != %r' % (pi, f.index, k, v, fj[k]))
    T.check('giai ma mat (header, co, lop, uv, footprint)', not bad, '; '.join(bad[:5]))
    # FaceHash
    vrams, places, raw = {}, {}, {}
    for k, b in tims.items():
        t = timlib.parse_tim(b)
        vram, irect, crect, adj = timlib.virtual_vram(t, 'field_slot0')
        T.check('ô sobj 0 (%s)' % k, adj == (576, 256))
        vrams[k], places[k] = vram, (irect, crect)
        raw[k] = facehash.raw_hashes(vram, all_faces)
        T.check('FaceHash runtime TIM %s' % k, ['%08x' % h for h in raw[k]] == J['faceHashes']['runtime'][k])
        T.check('faceHashVectorSha1 %s' % k, facehash.vector_sha1(raw[k]) == J['faceHashVectorSha1'][k])
    stored = []
    for i, k in enumerate(('A', 'B')):
        st = facehash.stored_hashes(vrams[k], all_faces, *places[k])
        T.check('stored %s' % k, ['%08x' % h for h in st] == J['faceHashes']['stored'][i])
        T.check('stored_from_raw %s' % k, facehash.stored_from_raw(raw[k], all_faces, *places[k]) == st)
        stored.append(st)
    live = facehash.live_set(model, all_faces)
    T.check('LIVE mo hinh', sorted(live) == J['live']['model'])
    T.check('LIVE theo bien the', [sorted(facehash.effective_live(live, s)) for s in stored] == J['live']['byVariant'])
    for k in tims:
        T.check('xac minh TIM %s' % k, facehash.verify_variants(raw[k], stored, live) == J['verify']['expected'][k])
    # LRM
    with open(os.path.join(SPEC_DIR, 'sample_cube.lrm'), 'rb') as f:
        data = f.read()
    T.check('sample_cube.lrm sha1', sha1(data) == J['files']['lrm']['sha1'])
    rt = lrm.runtime_info(model)
    L = lrm.read_lrm(data, expect_key=key, runtime=rt)
    T.check('round-trip sample_cube.lrm trung byte', lrm.write_lrm(L) == data and lrm.roundtrip(data) == (True, True))
    T.check('LRM level/generator', L.level == 1 and L.generator == 'synth_cube 1' and not L.deflate)
    T.check('LRM pngSha1', [v.png_sha1.hex() for v in L.variants] == [J['files']['pngs'][str(i)]['sha1'] for i in range(2)])
    T.check('LRM faceHash = stored', [list(v.face_hash) for v in L.variants] == stored)
    # lưới 16 float
    tex_base = 0
    for pi, part in enumerate(model.parts):
        faces, bf = all_faces[pi], backs[pi]
        r = lrm.retail_part_meshes(part, faces, bf)
        T.check('luoi retail phan %d' % pi, [_mesh_sha(m) for m in r['meshes']] ==
                [_json_mesh_sha(m) for m in J['meshes']['retail'][pi]['meshes']]
                and r['backfaceCulling'] == J['meshes']['retail'][pi]['backfaceCulling'])
        v = lrm.remaster_part_meshes(faces, bf, L.parts[pi], tex_base=tex_base)
        T.check('luoi bo VRAM phan %d' % pi, [_mesh_sha(m) for m in v['meshes']] ==
                [_json_mesh_sha(m) for m in J['meshes']['vram'][pi]['meshes']])
        for vi, var in enumerate(L.variants):
            lv = facehash.effective_live(live, list(var.face_hash))
            a = lrm.remaster_part_meshes(faces, bf, L.parts[pi], atlas=var.atlas_uv, live=lv, tex_base=tex_base)
            T.check('luoi bo ATLAS bien the %d phan %d' % (vi, pi), [_mesh_sha(m) for m in a['meshes']] ==
                    [_json_mesh_sha(m) for m in J['meshes']['atlas'][vi][pi]['meshes']])
        tex_base += sum(1 for f in faces if f.textured)
    # atlas PNG (synth_cube.py --out) -> mip runtime
    out = os.path.join(tmpdir, 'synth')
    r = subprocess.run([sys.executable, '-I', os.path.join(SPEC_DIR, 'synth_cube.py'), '--out', out],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        T.check('synth_cube.py --out', False, r.stdout[-300:] + r.stderr[-300:])
        return
    for i in range(2):
        with open(os.path.join(out, 'synth', 'atlas_%d.png' % i), 'rb') as f:
            pb = f.read()
        T.check('atlas %d sha1' % i, sha1(pb) == J['atlas'][i]['png'])
        img = imgio.decode_png(pb)
        T.check('atlas %d ghi lai (stored) trung byte' % i, imgio.encode_png(img, level=None) == pb)
        mips = imgio.runtime_mips(img)
        T.check('atlas %d mip runtime' % i, [dict(w=int(m.shape[1]), h=int(m.shape[0]), sha1=sha1(m.tobytes()))
                                             for m in mips] == J['atlas'][i]['runtimeMips'])
    # cây remaster/ do synth_cube ghi: index.tsv + lrm + png đọc được
    idx = lrm.read_index(open(os.path.join(out, 'remaster', 'index.tsv'), 'rb').read())
    T.check('index.tsv synth', list(idx) == [key.hex()])


def _lrm_offsets(data):
    """Offset các trường của sample_cube.lrm (2 phần mode 1, 2 biến thể)."""
    o = lrm.HEADER_SIZE
    parts = []
    for _ in range(2):
        P, C, Tn = struct.unpack_from('<III', data, o + 28)
        pos = o + 40
        cor = pos + 12 * P
        tri = cor + 32 * C
        parts.append(dict(start=o, P=P, C=C, T=Tn, pos=pos, cor=cor, tri=tri))
        o = tri + 12 * Tn
    n = struct.unpack_from('<I', data, o + 24)[0]
    vars_ = [o, o + 28 + 36 * n]
    return parts, vars_, n


def test_lrm(T):
    T.section('LRM1 + index.tsv')
    with open(os.path.join(SPEC_DIR, 'sample_cube.lrm'), 'rb') as f:
        data = f.read()
    parts, vars_, n = _lrm_offsets(data)
    p0, p1 = parts
    L = lrm.read_lrm(data)

    def put(off, fmt, val, base=data):
        x = bytearray(base)
        struct.pack_into(fmt, x, off, val)
        return bytes(x)

    def with_body(body, flags=0):
        x = bytearray(data[:lrm.HEADER_SIZE])
        struct.pack_into('<H', x, 6, flags)
        struct.pack_into('<I', x, 0x20, len(body) if not flags else len(lrm.lrm_body(L)))
        return bytes(x) + body

    # tam giác có corner khác srcFace / tam giác không xếp theo srcFace
    cor = L.parts[1].corners
    tri = L.parts[1].tri
    src = cor['src']
    t0 = tri[0]
    other = int(np.nonzero(src != src[t0[0]])[0][0])
    i_desc = next(i for i in range(len(tri) - 1) if src[tri[i][0]] < src[tri[i + 1][0]])
    swapped = bytearray(data)
    a, b = p1['tri'] + 12 * i_desc, p1['tri'] + 12 * (i_desc + 1)
    swapped[a:a + 12], swapped[b:b + 12] = data[b:b + 12], data[a:a + 12]
    gen_after_nul = bytearray(data)
    gen_after_nul[0x3f] = 0x41
    trailing = bytearray(data) + b'\0'
    struct.pack_into('<I', trailing, 0x20, len(data) - lrm.HEADER_SIZE + 1)
    z_trailing = with_body(zlib.compress(lrm.lrm_body(L), 9) + b'\0', flags=1)
    corr = {
        'cat 1 byte cuoi': data[:-1],
        'cat header': data[:0x30],
        'magic': b'LRM2' + data[4:],
        'version 2': put(4, '<H', 2),
        'flags bit la': put(6, '<H', 2),
        'co deflate tren than khong nen': put(6, '<H', 1),
        'partCount 0': put(0x1c, '<H', 0),
        'partCount 65': put(0x1c, '<H', 65),
        'variantCount 5': put(0x1e, '<H', 5),
        'bodySize +4': put(0x20, '<I', len(data) - lrm.HEADER_SIZE + 4),
        'level 3': put(0x24, '<B', 3),
        'byte zero header': put(0x26, '<B', 1),
        'generator khong ASCII': put(0x28, '<B', 0x01),
        'generator co byte sau NUL': bytes(gen_after_nul),
        'modelKey sai': put(8, '<B', data[8] ^ 1),
        'partKey sai (toan ven)': put(p0['start'], '<B', data[p0['start']] ^ 1),
        'mode 2': put(p0['start'] + 24, '<B', 2),
        'byte zero phan': put(p0['start'] + 25, '<B', 1),
        'C > 200000': put(p0['start'] + 32, '<I', 200001),
        'P = 0': put(p0['start'] + 28, '<I', 0),
        'pos NaN': put(p0['pos'], '<f', float('nan')),
        'pos Inf': put(p0['pos'] + 4, '<f', float('inf')),
        'normal NaN': put(p0['cor'] + 4, '<f', float('nan')),
        'corner.pos >= P': put(p0['cor'], '<I', p0['P']),
        'corner.srcFace >= srcFaceCount': put(p0['cor'] + 16, '<I', 11),
        'role 3': put(p0['cor'] + 26, '<B', 3),
        'byte zero corner': put(p0['cor'] + 27, '<B', 1),
        'reserved corner': put(p0['cor'] + 28, '<I', 1),
        'tri >= C': put(p0['tri'], '<I', p0['C']),
        'tam giac khac srcFace': put(p1['tri'], '<I', other),
        'tam giac khong xep theo srcFace': bytes(swapped),
        'atlas w = 3': put(vars_[0] + 20, '<H', 3),
        'atlas h = 4096': put(vars_[1] + 22, '<H', 4096),
        'texturedFaceCount khac giua bien the': put(vars_[1] + 24, '<I', n - 1),
        'atlasUv 1.5': put(len(data) - 4, '<f', 1.5),
        'atlasUv am': put(vars_[0] + 28 + 4 * n, '<f', -0.25),
        'atlasUv NaN': put(vars_[0] + 28 + 4 * n + 4, '<f', float('nan')),
        'thua byte sau bien the cuoi': bytes(trailing),
        'deflate thua byte': z_trailing,
        'deflate hong': with_body(b'\x78\x9c\x00\x01\x02', flags=1),
    }
    rejected = 0
    for name, bad in corr.items():
        try:
            lrm.read_lrm(bad)
            T.check('tu choi: %s' % name, False)
        except LrmError:
            rejected += 1
    T.check('>= 20 loi gieo bi tu choi', rejected == len(corr) and rejected >= 20, '%d/%d' % (rejected, len(corr)))
    print('  LRM: %d/%d file loi bi tu choi' % (rejected, len(corr)))
    # kiểm runtime (số đếm của mô hình tổng hợp)
    with open(os.path.join(SPEC_DIR, 'sample_cube.json'), encoding='utf-8') as f:
        cc = bytes.fromhex(json.load(f)['files']['ccontainer']['hex'])
    rt = lrm.runtime_info(tmd.parse_ccontainer(cc))
    T.check('runtime_info', rt['src_face_counts'] == [p.src_face_count for p in L.parts] and rt['textured'] == n)
    T.check('runtime dung', lrm.read_lrm(data, expect_key=L.model_key, runtime=rt).parts[1].mode == 1)
    for name, kw in (('khoa runtime khac', dict(expect_key=b'\0' * 20)),
                     ('so phan runtime 1', dict(runtime=dict(rt, src_face_counts=rt['src_face_counts'][:1],
                                                              n_verts=rt['n_verts'][:1]))),
                     ('so phan runtime 3', dict(runtime=dict(rt, src_face_counts=rt['src_face_counts'] + [1],
                                                              n_verts=rt['n_verts'] + [1]))),
                     ('srcFaceCount runtime khac', dict(runtime=dict(rt, src_face_counts=[rt['src_face_counts'][0],
                                                                                   rt['src_face_counts'][1] + 1]))),
                     ('nearestTmdVertex >= n_vert', dict(runtime=dict(rt, n_verts=[1, rt['n_verts'][1]]))),
                     ('texturedFaceCount runtime khac', dict(runtime=dict(rt, textured=n + 1)))):
        try:
            lrm.read_lrm(data, **kw)
            T.check('tu choi: %s' % name, False)
        except LrmError:
            T.check('tu choi: %s' % name, True)
    # deflate
    L.deflate = True
    dz = lrm.write_lrm(L)
    L2 = lrm.read_lrm(dz)
    T.check('than deflate doc lai', lrm.lrm_body(L2) == lrm.lrm_body(lrm.read_lrm(data)) and L2.deflate)
    same, same_body = lrm.roundtrip(dz)
    T.check('round-trip than deflate', same_body)
    L.deflate = False
    # part_from_arrays (lược đồ npz) == phần đọc từ file
    p = L.parts[1]
    c = p.corners
    q = lrm.part_from_arrays(p.key, p.src_face_count, p.pos, c['pos'], c['n'], c['src'],
                             np.stack([c['s'], c['t']], 1), c['near'], c['role'], p.tri)
    T.check('part_from_arrays', q.corners.tobytes() == c.tobytes() and q.pos.tobytes() == p.pos.tobytes())
    L3 = lrm.Lrm(L.model_key, [L.parts[0], q], L.variants, level=1, generator='synth_cube 1')
    T.check('ghi lai tu mang == file', lrm.write_lrm(L3) == data)
    # mode 0 + không biến thể
    L4 = lrm.Lrm(L.model_key, [lrm.LrmPart(pp.key, pp.src_face_count, 0) for pp in L.parts], [], level=0)
    d4 = lrm.write_lrm(L4)
    T.check('mode 0, 0 bien the', len(d4) == 0x40 + 2 * 28 and lrm.read_lrm(d4).parts[0].mode == 0)
    try:
        lrm.write_lrm(lrm.Lrm(L.model_key, L.parts, L.variants, level=5))
        T.check('bo ghi tu choi level 5', False)
    except LrmError:
        T.check('bo ghi tu choi level 5', True)
    # index.tsv
    idx = lrm.write_index([('a' * 40, 'Dart / trường'), ('b' * 40, '')])
    T.check('index.tsv ghi/doc', lrm.read_index(idx) == {'a' * 40: 'Dart / trường', 'b' * 40: ''}
            and idx.startswith(b'LRMINDEX\t1\n') and b'\r' not in idx)
    for name, b in (('nhan co CR', b'LRMINDEX\t1\n' + b'a' * 40 + b'\tmodels/' + b'a' * 40 + b'.lrm\tx\ry\n'),
                    ('BOM', b'\xef\xbb\xbf' + idx),
                    ('dong 1 sai', b'LRMINDEX\t2\n'),
                    ('duong dan sai', b'LRMINDEX\t1\n' + b'a' * 40 + b'\tmodels/' + b'b' * 40 + b'.lrm\tx\n'),
                    ('khoa hoa', b'LRMINDEX\t1\n' + b'A' * 40 + b'\tmodels/' + b'A' * 40 + b'.lrm\tx\n'),
                    ('thieu cot', b'LRMINDEX\t1\n' + b'a' * 40 + b'\tmodels/' + b'a' * 40 + b'.lrm\n'),
                    ('khong phai UTF-8', b'LRMINDEX\t1\n' + b'a' * 40 + b'\tmodels/' + b'a' * 40 + b'.lrm\t\xff\n')):
        try:
            lrm.read_index(b)
            T.check('index tu choi: %s' % name, False)
        except LrmError:
            T.check('index tu choi: %s' % name, True)
    for name, ent in (('TAB', ('a' * 40, 'x\ty')), ('khoa co LF cuoi', ('a' * 40 + '\n', 'x')),
                      ('khoa 41 ky tu', ('a' * 41, 'x'))):
        try:
            lrm.write_index([ent])
            T.check('index ghi tu choi %s' % name, False)
        except LrmError:
            T.check('index ghi tu choi %s' % name, True)


def test_gamefiles_synth(T, tmpdir):
    T.section('gamefiles (cay game gia)')
    g = os.path.join(tmpdir, 'Trò chơi (VN) thử')
    files = os.path.join(g, 'files')
    d = os.path.join(files, 'SECT', 'X')
    os.makedirs(os.path.join(d, '7'))
    os.makedirs(os.path.join(files, 'characters'))
    os.makedirs(os.path.join(g, 'vi', 'files', 'SECT', 'X'))
    with open(os.path.join(d, 'mrg'), 'w', newline='\n') as f:
        f.write('0=0;4\n1=0;0\n2=;0\n3=3;2\n4=3;9\n5=6;0\n6=6;3\n7=7;0\n')
    for name, b in (('0', b'base'), ('3', b'xy'), ('6', b'six')):
        with open(os.path.join(d, name), 'wb') as f:
            f.write(b)
    with open(os.path.join(g, 'vi', 'files', 'SECT', 'X', '0'), 'wb') as f:
        f.write(b'OVERLAY!')
    nm = os.path.join(files, 'SECT', 'Y')
    os.makedirs(nm)
    for name in ('b', '10', '2', 'A'):
        with open(os.path.join(nm, name), 'wb') as f:
            f.write(name.encode())
    gf = gamefiles.GameFiles(g)
    T.check('resolve_game: game/ va game/files', gamefiles.GameFiles(files).files == gf.files)
    T.check('lop phu thang khi doc', gf.read('SECT/X/0') == b'OVERLAY!' and gf.is_overlaid('SECT/X/0'))
    es = gf.load_dir('SECT/X')
    T.check('so muc', len(es) == 8)
    e0, e1, e2, e3, e4 = es[0], es[1], es[2], es[3], es[4]
    T.check('muc that', e0.real_index == -1 and e0.real() and e0.data == b'OVERLAY!' and e0.virtual_size == 8)
    T.check('muc ao (co 0)', e1.virtual and e1.real_index == 0 and e1.data == b'OVERLAY!' and not e1.has_virtual_size()
            and not e1.real() and e1.path == 'SECT/X/0')
    T.check('khong co file', e2 is None)
    T.check('muc ao (co 9)', e4.real_index == 3 and e4.virtual_size == 9 and e4.has_virtual_size() and e4.data == b'xy')
    T.check('muc that 2', e3.data == b'xy' and es[6].data == b'six' and es[5].data == b'six')
    T.check('thu muc con', es[7].is_dir and es[7].data == b'' and not es[7].real())
    T.check('resolve muc ao', gf.resolve('SECT/X/4') == 'SECT/X/3' and gf.resolve('SECT/X/2') is None
            and gf.read_resolved('SECT/X/1') == b'OVERLAY!')
    ys = gf.load_dir('SECT/Y')
    T.check('thu tu khong mrg (so nguyen, roi khong phan biet hoa thuong)', [e.path for e in ys] ==
            ['SECT/Y/2', 'SECT/Y/10', 'SECT/Y/A', 'SECT/Y/b'], [e.path for e in ys])
    try:
        gf.read('SECT/X/99')
        T.check('thieu file -> GameFileError', False)
    except GameFileError:
        T.check('thieu file -> GameFileError', True)
    # BufferedReader.lines(): \r, \r\n, \n đều hết dòng
    with open(os.path.join(d, 'mrg'), 'wb') as f:
        f.write(b'0=0;4\r1=0;0\r\n2=;0\n3=3;2\r')
    es2 = gamefiles.GameFiles(g).load_dir('SECT/X')
    T.check('mrg xuong dong CR / CRLF / LF', len(es2) == 4 and es2[1].real_index == 0 and es2[2] is None
            and es2[3].data == b'xy', es2)
    # Integer.parseInt: '+3' hợp lệ; ' 3', '3_0', tràn int32 -> lỗi (int() của Python lại nhận khoảng trắng và '_')
    with open(os.path.join(d, 'mrg'), 'wb') as f:
        f.write(b'0=0;4\n+3=3;2\n')
    T.check('mrg so co dau +', gamefiles.GameFiles(g).load_dir('SECT/X')[1].data == b'xy')
    for name, body in (('mrg dong sai so phan', b'0=0;4\n1=5;\n'), ('mrg khoang trang trong so', b'0=0;4\n3= 3;2\n'),
                       ('mrg dau _ trong so', b'0=0;4\n3=3;2_0\n'), ('mrg tran int32', b'0=0;4\n3=3;4294967296\n'),
                       ('mrg khong phai UTF-8', b'0=0;4\n\xff=3;2\n'), ('mrg dong rong giua', b'0=0;4\n\n3=3;2\n')):
        with open(os.path.join(d, 'mrg'), 'wb') as f:
            f.write(body)
        try:
            gamefiles.GameFiles(g).load_dir('SECT/X')
            T.check('%s -> GameFileError' % name, False)
        except GameFileError:
            T.check('%s -> GameFileError' % name, True)


# ================================================================= dữ liệu game
def test_vectors(T, gf):
    T.section('spec/vectors.json (khoa + FaceHash, %s)' % gf.files)
    with open(os.path.join(SPEC_DIR, 'vectors.json'), encoding='utf-8') as f:
        V = json.load(f)
    bad = 0
    for m in V['models']:
        model = tmd.parse_ccontainer(gf.read(m['model']))
        t = timlib.parse_tim(gf.read(m['tim']))
        vram, irect, crect, adj = timlib.virtual_vram(t, m['placement'])
        k0 = lrmkey.model_keys(model)[0]
        if adj:
            tmd.uv_adjust_model(model, *adj)
        key, pks = lrmkey.model_keys(model)
        faces, _ = tmd.model_faces(model)
        raw = facehash.raw_hashes(vram, faces)
        tex = tmd.textured_faces(faces)
        stored = facehash.stored_hashes(vram, faces, irect, crect)
        got = dict(partCount=len(model.parts), modelKey=key.hex(), partKeys=[k.hex() for k in pks],
                   srcFaceCount=model.src_face_counts(), texturedFaceCount=len(tex), tris=tmd.gl_tri_count(faces),
                   faceHashVectorSha1=facehash.vector_sha1(raw), texAnimRects=len(facehash.anim_rects(model)),
                   liveFaceCount=len(facehash.live_set(model, faces)),
                   facesOutsideTim=sum(1 for f in tex if facehash.outside_tim(f, irect, crect)))
        diff = {k: (v, m[k]) for k, v in got.items() if m[k] != v}
        if k0 != key:
            diff['khoa doi sau UvAdjust'] = True
        nz = sum(1 for h in stored if h == 0) - sum(1 for f in tex if f.bpp == 3)
        if nz != m['facesOutsideTim']:
            diff['so 0 trong stored'] = (nz, m['facesOutsideTim'])
        if any(h == 0 for f, h in zip(tex, raw) if f.bpp != 3):
            diff['hash tho = 0'] = True
        if diff:
            bad += 1
            print('  khac %s: %s' % (m['id'], str(diff)[:300]))
    T.check('%d mo hinh vectors.json' % len(V['models']), bad == 0, '%d khac' % bad)
    return V


def test_keys(T, gf):
    T.section('khoa moi file truong (6722 -> 551)')
    import scan
    res, errs, _battle = scan.count_keys(gf)
    for k, v in scan.EXPECT_KEYS.items():
        T.check('keys %s = %d' % (k, v), res[k] == v, 'duoc %d' % res[k])
    T.check('keys khong loi', not errs, str(errs[:3]))


def _pilot_python(arg):
    cands = [arg, os.environ.get('LODSC_PILOT_PYTHON'), shutil.which('python'), shutil.which('py')]
    for c in cands:
        if not c:
            continue
        try:
            r = subprocess.run([c, '-c', 'import PIL, numpy'], capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0:
            return c
    return None


def _pilot_refs(T, gf, ref_dir, pilot_py):
    """Bản xuất của export_tmd.py (cần PIL) — tạo nếu thiếu / cũ (STAMP = SHA-1 của export_tmd.py)."""
    with open(PILOT, 'rb') as f:
        stamp = sha1(f.read())
    jobs = (('dart_battle', ['battle', 'dart']), ('dart_field', ['field', 'DRGN21.BIN/26', '0']))
    sp = os.path.join(ref_dir, 'STAMP')
    have = os.path.isfile(sp) and open(sp).read().strip() == stamp and all(
        os.path.isfile(os.path.join(ref_dir, n, n + '.json')) for n, _ in jobs)
    if have:
        return True
    py = _pilot_python(pilot_py)
    if py is None:
        T.skip('export so voi export_tmd.py', 'khong co ban tham chieu %s va khong tim thay Python co PIL' % ref_dir)
        return False
    for n, args in jobs:
        out = os.path.join(ref_dir, n)
        if os.path.isdir(out):
            shutil.rmtree(out)
        r = subprocess.run([py, PILOT] + args + ['--name', n, '--out', out, '--game', gf.files],
                           capture_output=True, text=True, encoding='utf-8', errors='replace',
                           env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        if r.returncode != 0:
            T.check('chay export_tmd.py %s' % n, False, r.stdout[-300:] + r.stderr[-300:])
            return False
    with open(sp, 'w') as f:
        f.write(stamp + '\n')
    print('  da tao ban tham chieu export_tmd.py bang %s' % py)
    return True


def test_export(T, gf, ref_dir, pilot_py, work):
    T.section('export.py so voi tools/sc_remodel/export_tmd.py')
    if not _pilot_refs(T, gf, ref_dir, pilot_py):
        return
    for name, fn in (('dart_battle', lambda o: export.export_battle(gf, 'dart', 'combat', anim='0', name='dart_battle',
                                                                     out_dir=o, gltf_generator=export.PILOT_GLTF_GENERATOR)),
                     ('dart_field', lambda o: export.export_field(gf, 'DRGN21.BIN/26', 0, name='dart_field', out_dir=o,
                                                                  gltf_generator=export.PILOT_GLTF_GENERATOR))):
        out = os.path.join(work, 'test_export', name)
        if os.path.isdir(out):
            shutil.rmtree(out)
        t = time.time()
        summary, errs = fn(out)
        T.check('%s khong loi' % name, not errs, str(errs[:3]))
        ref = os.path.join(ref_dir, name)
        nbytes = npix = 0
        bad = []
        for root, _ds, fs in os.walk(ref):
            for fn_ in fs:
                r = os.path.join(root, fn_)
                rel = os.path.relpath(r, ref)
                m = os.path.join(out, rel)
                if not os.path.isfile(m):
                    bad.append('thieu ' + rel)
                elif fn_.endswith('.png'):
                    a, b = imgio.read_png(r), imgio.read_png(m)
                    npix += 1
                    if a.shape != b.shape or not np.array_equal(a, b):
                        bad.append('PNG khac ' + rel)
                else:
                    nbytes += 1
                    if not filecmp.cmp(r, m, shallow=False):
                        bad.append('byte khac ' + rel)
        need = [name + ext for ext in ('.json', '.bin', '.mtl', '.gltf', '_posed.obj', '_atlas.png', '_atlas_pad.png')]
        miss = [x for x in need if not os.path.isfile(os.path.join(ref, x))]
        T.check('%s: JSON/.bin/.mtl/.gltf/.obj trung byte (%d file), PNG trung diem anh (%d)' % (name, nbytes, npix),
                not bad and not miss, '; '.join((bad + miss)[:5]))
        print('  %s: %d file so byte, %d PNG so diem anh, %.2fs' % (name, nbytes, npix, time.time() - t))
        if name == 'dart_battle':
            with open(os.path.join(ref, name + '.json'), encoding='utf-8') as f:
                pj = json.load(f)
    return pj


def test_anims(T, gf, pilot_json):
    T.section('anims')
    data = gf.read('characters/dart/models/combat/0')
    a = anims.parse_anim(data, 'characters/dart/models/combat/0')
    T.check('so phan', a.part_count == 17 and a.rot.shape[1:] == (17, 3))
    T.check('khung khoa = totalFrames/2', a.keyframes == int(a.total_frames / 2) and a.keyframes > 1)
    n, kf0 = anims.kf0(data)
    T.check('kf0 == khung 0', n == 17 and all(tuple(int(x) for x in a.rot[0, i]) == kf0[i][0]
                                              and tuple(int(x) for x in a.trans[0, i]) == kf0[i][1] for i in range(17)))
    if pilot_json is not None:
        ok = all(p['kf0_rot_psx'] == list(kf0[p['index']][0]) and p['kf0_trans'] == list(kf0[p['index']][1])
                 for p in pilot_json['parts'])
        R, _T = anims.part_transforms(a, 0)
        ok2 = all(np.allclose(R[p['index']], p['kf0_matrix'], atol=1e-8) for p in pilot_json['parts'])
        T.check('kf0 == JSON cua export_tmd.py', ok and ok2)
    fb = anims.find_anims(gf, 'battle', 'characters/dart/models/combat/32', 17)
    T.check('find_anims battle', fb and fb[0][0] == 'characters/dart/models/combat/0' and len(fb) >= 5,
            [x for x, _ in fb])
    ff = anims.find_anims(gf, 'field', 'SECT/DRGN21.BIN/26/0', 15)
    T.check('find_anims field', ff and ff[0][0] == 'SECT/DRGN21.BIN/26/1', [x for x, _ in ff][:3])
    fs = anims.find_anims(gf, 'story', 'SECT/DRGN0.BIN/0', 17)
    T.check('find_anims story', fs and fs[0][0] == 'SECT/DRGN0.BIN/2', [x for x, _ in fs][:3])
    fm = anims.find_anims(gf, 'monster', 'SECT/DRGN0.BIN/3402/32', 18)
    T.check('find_anims monster', len(fm) >= 1, [x for x, _ in fm])
    kfs = anims.all_keyframes(fb)
    T.check('all_keyframes', len(kfs) == sum(x.keyframes for _, x in fb) and kfs[0][2].shape == (17, 3, 3))
    try:
        anims.parse_anim(data[:0x10 + 12 * 17 * 2])
        T.check('hoat canh bi cat -> SpecError', False)
    except tmd.SpecError:
        T.check('hoat canh bi cat -> SpecError', True)


def test_gamefiles_real(T, gf):
    T.section('gamefiles (du lieu that)')
    e2 = gf.entry('characters/dart/models/combat', 2)
    e5 = gf.entry('characters/dart/models/combat', 5)
    e32 = gf.entry('characters/dart/models/combat', 32)
    T.check('muc ao 2 -> 5', e2 is not None and e2.virtual and e2.real_index == 5 and not e2.has_virtual_size()
            and e2.data == gf.read('characters/dart/models/combat/5'))
    T.check('muc that 5', e5.real() and e5.virtual_size == len(e5.data))
    T.check('muc 32 = CContainer', e32.real() and tmd.looks_like_ccontainer(e32.data))
    T.check('lop phu vi/files', gf.is_overlaid('SECT/DRGN0.BIN/4113') == os.path.isfile(
        os.path.join(gf.game, 'vi', 'files', 'SECT', 'DRGN0.BIN', '4113')))


def test_scan(T, gf, V):
    T.section('scan.run_scan')
    import scan
    cat = scan.load_catalog(scan.DEFAULT_CATALOG)
    t = time.time()
    doc, report = scan.run_scan(gf, cat, 'all', True, False, log=lambda s: print('  ' + s))
    dt = time.time() - t
    print('  run_scan: %d khoa, %d bien the, %.1fs' % (len(doc['keys']), doc['counts']['variants'], dt))
    T.check('scan khong loi', not doc['errors'], str(doc['errors'][:3]))
    miss = []
    for m in V['models']:
        k = doc['keys'].get(m['modelKey'])
        if k is None or m['faceHashVectorSha1'] not in [v['rawVectorSha1'] for v in k['variants']]:
            miss.append(m['id'])
    T.check('moi mau vectors.json co bien the trung vec-to tho', not miss, str(miss[:5]))
    k468 = doc['keys'].get(next(m['modelKey'] for m in V['models'] if m['id'] == 'story/DRGN0/468'))
    T.check('DRGN0/468: 12 mat ghi 0 (ngoai TIM)', k468 and k468['variants'][0]['zeroFaces'] == 12)
    for k, rec in doc['keys'].items():
        for v in rec['variants']:
            if len(v['faceHashes']) != rec['texturedFaceCount'] or facehash.vector_sha1(
                    [int(h, 16) for h in v['faceHashes']]) != v['faceHashVectorSha1']:
                T.check('bien the %s nhat quan' % k, False)
                break
    if cat is not None:
        T.check('bao cao catalog du muc', report is not None and len(report['entries']) == len(cat))
        print('  catalog: %s' % json.dumps(report['summary'], ensure_ascii=False))
        # --scope catalog: chạy lại từ đầu (kiểm xác định) và phải ra đúng tập con của --scope all
        docc, _ = scan.run_scan(gf, cat, 'catalog', True, False, log=lambda s: None)
        want = {e['key'] for e in report['entries'] if e['key']}
        T.check('scope catalog = tap con cua scope all (xac dinh)', set(docc['keys']) == want and all(
            json.dumps(docc['keys'][k], sort_keys=True) == json.dumps(doc['keys'][k], sort_keys=True) for k in want))


# ================================================================= main
def main():
    utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--game', default=None)
    ap.add_argument('--no-game', action='store_true')
    ap.add_argument('--quick', action='store_true', help='bo qua keys 6722 file va run_scan')
    ap.add_argument('--work', default=DEFAULT_WORK)
    ap.add_argument('--pilot-ref', default=None)
    ap.add_argument('--pilot-python', default=None)
    a = ap.parse_args()
    t0 = time.time()
    T = Checker()
    print('python %s, numpy %s, %s' % (sys.version.split()[0], np.__version__, sys.executable))
    tmpdir = tempfile.mkdtemp(prefix='sc_remaster_p1_')
    try:
        test_fnv(T)
        test_png(T, tmpdir)
        test_mip(T)
        test_sample_cube(T, tmpdir)
        test_lrm(T)
        test_gamefiles_synth(T, tmpdir)
        if a.no_game:
            T.skip('du lieu game', '--no-game')
        else:
            try:
                gf = gamefiles.GameFiles(a.game)
            except GameFileError as e:
                gf = None
                T.check('co game/files', False, str(e))
            if gf is not None:
                import scan
                before = scan.sample_hashes(gf, scan._sample_rels(gf))
                V = test_vectors(T, gf)
                if not a.quick:
                    test_keys(T, gf)
                pj = test_export(T, gf, a.pilot_ref or os.path.join(a.work, 'pilot_ref'), a.pilot_python, a.work)
                test_anims(T, gf, pj)
                test_gamefiles_real(T, gf)
                if not a.quick:
                    test_scan(T, gf, V)
                after = scan.sample_hashes(gf, scan._sample_rels(gf))
                changed = [p for p in before if after.get(p) != before[p]]
                T.check('chi doc: %d file mau khong doi' % len(before), not changed, str(changed[:3]))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    T.section('ket thuc')
    T.check("'PIL' khong co trong sys.modules", 'PIL' not in sys.modules and not any(
        m == 'PIL' or m.startswith('PIL.') for m in sys.modules))
    print('%d dat, %d loi, %d bo qua, %.1fs' % (T.ok, T.fail, len(T.skipped), time.time() - t0))
    print('DAT' if T.fail == 0 else 'KHONG DAT')
    return 0 if T.fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
