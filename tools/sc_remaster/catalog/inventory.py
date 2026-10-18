"""inventory.py — quét kho mô hình nhân vật (CHỈ ĐỌC game/files) cho danh mục v1 của route B ("Mô hình HD").

Chuyển từ các script nháp thiết kế (scratchpad/remaster_design): lodmodels.py (đọc mrg, CContainer, TIM, hoạt cảnh),
scan_field.py (mọi sobj của mọi cảnh DRGN21-24), scan_drgn0.py (mô hình DRGN0/DRGN1/characters/monsters), anims.py (băm
hoạt cảnh theo đối tượng cảnh) và comp.py (khối đỉnh dùng chung giữa các mô hình — bằng chứng nhận diện nhân vật).
Khoá LRMK1 lấy từ bản tham chiếu WP0 `tools/sc_remaster/spec/ref_spec.py` (không tự cài lại).

Cách gọi (từ gốc repo, PYTHONIOENCODING=utf-8; chạy được bằng python hệ thống và python.exe -I của Blender):
  python tools/sc_remaster/catalog/inventory.py field  [--game game/files] [--anims] [--out FILE]
      liệt kê mọi đối tượng cảnh (sobj) như RetailSubmap.prepareSobjs: thư mục tài nguyên = DRGN2x/<n> (có textures/),
      thư mục script = <n+1>, số đối tượng = số mục mrg của script - 2; mô hình = tài nguyên[obj*33] (giải liên kết mrg),
      texture = textures[obj], hoạt cảnh = tài nguyên[obj*33+1 .. +32] đầu tiên có cùng số phần (--anims).
  python tools/sc_remaster/catalog/inventory.py drgn0  [--game game/files] [--out FILE]
      mọi CContainer / TmdWithId trong SECT/DRGN0.BIN, SECT/DRGN1.BIN, characters/, monsters/ (như scan_drgn0.py).
  python tools/sc_remaster/catalog/inventory.py anims  [--game game/files] [--out FILE]
      với mỗi đối tượng cảnh: SHA-1 (16 hex) của các hoạt cảnh cùng số phần (như anims.py).
  python tools/sc_remaster/catalog/inventory.py parts  <đường dẫn mô hình> [...] [--game game/files]
      khối đỉnh từng phần (SHA-1 12 hex) và các mô hình cảnh khác dùng chung khối đó (như comp.py).
  python tools/sc_remaster/catalog/inventory.py cutscenes [--game game/files]
      truy mô hình cốt truyện DRGN0/N (0..690, TIM N+1) qua DEFF cảnh cắt trận: DEFF i (DRGN0/<5512+2i>) có N trong
      bảng chỉ số file của script, script quái DRGN1/<id+1> gọi DEFF i (call 637 / call 623 kiểu 0x5000000).
  python tools/sc_remaster/catalog/inventory.py selftest [--game game/files]
      tự kiểm trên dữ liệu: mẫu đã biết (số phần / tam giác / khoá = spec/vectors.json), mặt nạ header bền vững,
      giải liên kết mrg, game/files không đổi (băm trước/sau). Exit 0 = đạt, 1 = lỗi.

Mặc định --out ghi vào work/upscale/sc_remaster_c1/ (git bỏ qua). KHÔNG BAO GIỜ ghi vào game/files.
Định dạng bản ghi cảnh (scan_field): disc, scene_dir (thư mục tài nguyên), script_dir, obj, model (đường dẫn file thật
sau mrg, tương đối game/files), symlinked, texture (đường dẫn TIM thật hoặc None), tim {bpp, clut_rect, img_rect, size,
sha1}, anim (hoặc None), nobj, verts, prims, tris_gl (tam giác GL = tam giác + 2 x tứ giác), quads, untextured,
translucent, clut_anim, subfile2, sha1_file, sha1_norm (SHA-1 cả file với 16 bit thấp mọi header gói đặt 0), size.
"""
import argparse
import collections
import hashlib
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
SPEC_DIR = os.path.normpath(os.path.join(HERE, '..', 'spec'))
DEFAULT_GAME = os.path.join(ROOT, 'game', 'files')
OUT_DIR = os.path.join(ROOT, 'work', 'upscale', 'sc_remaster_c1')

if SPEC_DIR not in sys.path:
    sys.path.insert(0, SPEC_DIR)
import ref_spec  # noqa: E402  (bản tham chiếu WP0: LRMK1, đọc file qua lớp phủ vi/files)

FIELD_DRGN = ('DRGN21.BIN', 'DRGN22.BIN', 'DRGN23.BIN', 'DRGN24.BIN')
STORY_RANGE = (0, 690)          # DRGN0 0..690: mô hình cốt truyện N + TIM N+1 (thiết kế, mục D)
MONSTER_BASE = 3137             # SECT/DRGN0.BIN/<3137 + id>/32 + monsters/<id>/textures/combat (Battle.java:2897, 2242)


# ---------------------------------------------------------------- tiện ích
def u16(b, o):
    return struct.unpack_from('<H', b, o)[0]


def u32(b, o):
    return struct.unpack_from('<I', b, o)[0]


def sha1(b):
    return hashlib.sha1(b).hexdigest()


def resolve_game(game):
    """--game: thư mục files/ hoặc thư mục game/ chứa files/ (như ref_spec)."""
    return ref_spec.resolve_game(game or DEFAULT_GAME)


def read_file(game, rel):
    """Đọc <rel> (tương đối files/) — lớp phủ sc-vi <game>/vi/files thắng (sc-vi Loader.java:32-50)."""
    return ref_spec.read_game_file(game, rel)


def exists(game, rel):
    over = os.path.join(os.path.dirname(game), 'vi', 'files', *rel.split('/'))
    return os.path.isfile(over) or os.path.isfile(os.path.join(game, *rel.split('/')))


def utf8_stdout():
    """python.exe -I bỏ qua PYTHONIOENCODING: tự đặt stdout/stderr UTF-8 để in nhãn tiếng Việt trên console cp1252."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass


def natkey(path):
    """Khoá sắp xếp tự nhiên cho đường dẫn kiểu SECT/DRGN21.BIN/5/0."""
    return tuple((0, int(x), '') if x.isdigit() else (1, 0, x) for x in str(path).split('/'))


def out_path(name, out=None):
    p = out or os.path.join(OUT_DIR, name)
    guard_out(p)
    return p


def guard_out(p):
    """Dữ liệu suy ra từ đĩa chỉ được ghi dưới work/upscale/sc_remaster* (git bỏ qua)."""
    ap = os.path.normcase(os.path.abspath(p))
    base = os.path.normcase(os.path.join(ROOT, 'work', 'upscale'))
    try:
        rel = os.path.relpath(ap, base)
    except ValueError:          # Windows: khác ổ đĩa -> chắc chắn ngoài work/upscale
        rel = '..'
    if rel.startswith('..') or not rel.split(os.sep)[0].startswith('sc_remaster'):
        raise SystemExit('LOI: chi ghi du lieu suy ra tu dia vao work/upscale/sc_remaster*: %s' % p)


# ---------------------------------------------------------------- mrg (SC Loader.loadDirectorySync)
def read_mrg(d):
    """'virtual=real;size' mỗi dòng; real trống = không có file; size 0 = liên kết. -> {virtual: (real|-1, size)}."""
    p = os.path.join(d, 'mrg')
    if not os.path.isfile(p):
        return None
    m = {}
    with open(p, encoding='ascii') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            v, rest = line.split('=', 1)
            r, s = rest.split(';', 1)
            m[int(v)] = (int(r) if r.strip() else -1, int(s) if s.strip() else 0)
    return m


def resolve(m, v):
    """Chỉ số ảo -> (file thật hoặc -1, kích thước ảo); đi theo chuỗi liên kết tới file 'thật nhất' như Loader."""
    if m is None:
        return v, None
    if v not in m:
        return -1, 0
    r, s = m[v]
    seen = set()
    while r != -1 and m.get(r, (r, 0))[0] != r and r not in seen:
        seen.add(r)
        r = m[r][0]
    return r, s


# ---------------------------------------------------------------- CContainer / TIM / hoạt cảnh (đọc nhẹ)
def parse_container(b):
    """Đọc nhẹ một CContainer -> dict thống kê; ValueError nếu không phải mô hình TMD hợp lệ.

    CContainer: u32 @0 -> TmdWithId (u32 id 0x41 + TMD), u32 @4 -> hoạt cảnh CLUT (hoặc 0), u32 @8 -> Subfile2 (hoặc 0).
    TMD: flags, nobj, bảng đối tượng 0x1c byte (vtop, nv, ntop, nn, ptop, np, scale), offset tính từ đầu bảng.
    Mỗi gói có header 4 byte riêng; Models.updateTmdPacketIlen ghi đè 16 bit thấp header đầu mỗi run lúc nạp, nên
    sha1_norm che 16 bit thấp của MỌI header gói (bền vững trước/sau khi game nạp).
    """
    if len(b) < 0x20:
        raise ValueError('qua nho')
    t = u32(b, 0)
    if t + 12 > len(b):
        raise ValueError('offset TMD sai')
    tid = u32(b, t)
    base = t + 4
    flags, nobj = struct.unpack_from('<II', b, base)
    if flags & 3:
        raise ValueError('CTMD/fixp flags=%x' % flags)
    if not 0 < nobj < 200:
        raise ValueError('nobj=%d' % nobj)
    ob = base + 8
    parts = []
    hdr_offs = []
    tmd_end = ob + nobj * 0x1c
    for i in range(nobj):
        vtop, nv, ntop, nn, ptop, npr, _scale = struct.unpack_from('<IIIIIIi', b, ob + i * 0x1c)
        off = ob + ptop
        tris = quads = textured = translucent = 0
        for _ in range(npr):
            h = u32(b, off)
            hdr_offs.append(off)
            pid = h >> 24
            if (pid >> 5 & 3) != 1:
                raise ValueError('goi %08x' % h)
            sz = ref_spec.packet_size(h)
            if pid & 0x8:
                quads += 1
            else:
                tris += 1
            if pid & 0x4:
                textured += 1
            if pid & 0x2:
                translucent += 1
            off += 4 + sz
        tmd_end = max(tmd_end, off, ob + vtop + nv * 8, ob + ntop + nn * 8)
        parts.append(dict(nv=nv, nn=nn, npr=npr, tris=tris, quads=quads, textured=textured, translucent=translucent,
                          vblock=sha1(b[ob + vtop:ob + vtop + nv * 8])[:12]))
    nb = bytearray(b)
    for o in hdr_offs:
        nb[o] = 0
        nb[o + 1] = 0
    return dict(tmd_id=tid, flags=flags, nobj=nobj, parts=parts,
                verts=sum(p['nv'] for p in parts), prims=sum(p['npr'] for p in parts),
                tris_gl=sum(p['tris'] + 2 * p['quads'] for p in parts), quads=sum(p['quads'] for p in parts),
                untextured=sum(p['npr'] - p['textured'] for p in parts),
                translucent=sum(p['translucent'] for p in parts),
                clut_anim=u32(b, 4) != 0, subfile2=u32(b, 8) != 0, tmd_off=t, tmd_end=tmd_end,
                sha1_file=sha1(b), sha1_norm=sha1(bytes(nb)), size=len(b))


def parse_tim_info(b):
    """Đầu TIM -> {bpp, clut_rect, img_rect, size, sha1} hoặc None nếu không phải TIM."""
    if len(b) < 8 or u32(b, 0) != 0x10:
        return None
    flags = u32(b, 4)
    o = 8
    clut = None
    if flags & 8:
        if o + 12 > len(b):
            return None
        ln, cx, cy, cw, ch = struct.unpack_from('<IHHHH', b, o)
        clut = [cx, cy, cw, ch]
        o += ln
    if o + 12 > len(b):
        return None
    _ln, ix, iy, iw, ih = struct.unpack_from('<IHHHH', b, o)
    return dict(bpp=flags & 3, clut_rect=clut, img_rect=[ix, iy, iw, ih], size=len(b), sha1=sha1(b))


def anim_parts(b):
    """Số phần của file hoạt cảnh TMD (u16 @0xc); None nếu không phải (CMB 0x11 hoặc quá ngắn)."""
    if len(b) < 0x10 or u32(b, 0) == 0x11:
        return None
    return u16(b, 0xc)


def is_container(b):
    """CContainer (u32 @0 -> 0x41) hoặc TmdWithId trần (u32 @0 = 0x41)."""
    if len(b) < 0x30:
        return None
    o = u32(b, 0)
    if o == 0x41:
        return 'tmdwithid'
    if 0xc <= o < len(b) - 12 and o % 4 == 0 and u32(b, o) == 0x41:
        return 'ccontainer'
    return None


def container_info(b):
    """Như parse_container nhưng nhận cả TmdWithId trần (bọc vào CContainer giả 12 byte)."""
    kind = is_container(b)
    if kind is None:
        raise ValueError('khong phai CContainer/TmdWithId')
    if kind == 'tmdwithid':
        return parse_container(struct.pack('<III', 12, 0, 0) + b)
    return parse_container(b)


# ---------------------------------------------------------------- khoá LRMK1 (bản tham chiếu WP0)
_KEY_CACHE = {}


def model_key(game, rel, data=None):
    """-> dict(key, partKeys, nobj, tris) theo SPEC §3.1 (ref_spec); cache theo SHA-1 nội dung file."""
    b = data if data is not None else read_file(game, rel)
    h = sha1(b)
    if h not in _KEY_CACHE:
        m = ref_spec.parse_ccontainer(b, scan_filter=True)
        if m is None:
            raise ValueError('%s: khong phai mo hinh TMD' % rel)
        mk, pks = ref_spec.model_keys(m)
        tris = 0
        for p in m.parts:
            for header, _d in p.packets():
                tris += 2 if (header >> 24) & 0x8 else 1
        _KEY_CACHE[h] = dict(key=mk.hex(), partKeys=[k.hex() for k in pks], nobj=len(m.parts), tris=tris)
    return _KEY_CACHE[h]


# ---------------------------------------------------------------- quét cảnh (scan_field.py)
def field_scene_dirs(game, drgn):
    root = os.path.join(game, 'SECT', drgn)
    return sorted(int(d) for d in os.listdir(root) if d.isdigit() and os.path.isdir(os.path.join(root, d, 'textures')))


def find_anim(game, drgn, ad, obj, nobj, am=None):
    """Hoạt cảnh đầu tiên trong tài nguyên[obj*33+1 .. obj*33+32] có cùng số phần (như scan_field.py) hoặc None."""
    adir = os.path.join(game, 'SECT', drgn, str(ad))
    if am is None:
        am = read_mrg(adir)
    for k in range(obj * 33 + 1, obj * 33 + 33):
        r, _ = resolve(am, k)
        if r < 0:
            continue
        ap = os.path.join(adir, str(r))
        if os.path.isfile(ap) and os.path.getsize(ap) >= 0x10:
            with open(ap, 'rb') as f:
                hb = f.read(0x10)
            if anim_parts(hb) == nobj:
                return 'SECT/%s/%d/%d' % (drgn, ad, r)
    return None


def scan_field(game, with_anims=False):
    """-> (records, errors). Một bản ghi cho mỗi đối tượng cảnh có mô hình; thứ tự (đĩa, thư mục cảnh, obj)."""
    recs = []
    errors = []
    cache = {}
    for disc, drgn in enumerate(FIELD_DRGN, 1):
        root = os.path.join(game, 'SECT', drgn)
        for ad in field_scene_dirs(game, drgn):
            adir = os.path.join(root, str(ad))
            am = read_mrg(adir)
            sdir = os.path.join(root, str(ad + 1))
            sm = read_mrg(sdir) if os.path.isdir(sdir) else None
            if sm is None:
                errors.append('%s/%d: khong co mrg script' % (drgn, ad + 1))
                continue
            nobj_scene = len(sm) - 2
            tm = read_mrg(os.path.join(adir, 'textures'))
            for obj in range(nobj_scene):
                real, _vsize = resolve(am, obj * 33)
                if real < 0:
                    continue
                mpath = os.path.join(adir, str(real))
                if not os.path.isfile(mpath) or os.path.getsize(mpath) == 0:
                    continue
                rel = 'SECT/%s/%d/%d' % (drgn, ad, real)
                if rel not in cache:
                    b = read_file(game, rel)
                    try:
                        cache[rel] = parse_container(b)
                    except (ValueError, struct.error) as e:
                        cache[rel] = dict(error=str(e), size=len(b))
                info = cache[rel]
                if 'error' in info:
                    errors.append('%s: %s' % (rel, info['error']))
                    continue
                treal, _ = resolve(tm, obj)
                tinfo = tpath = None
                if treal >= 0:
                    trel = 'SECT/%s/%d/textures/%d' % (drgn, ad, treal)
                    tp = os.path.join(adir, 'textures', str(treal))
                    if os.path.isfile(tp) and os.path.getsize(tp) > 0:
                        tinfo = parse_tim_info(read_file(game, trel))
                        tpath = trel if tinfo else None
                anim = find_anim(game, drgn, ad, obj, info['nobj'], am) if with_anims else None
                recs.append(dict(disc=disc, scene_dir=ad, script_dir=ad + 1, obj=obj, model=rel, model_virtual=obj * 33,
                                 symlinked=(real != obj * 33), texture=tpath, tim=tinfo, anim=anim,
                                 **{k: info[k] for k in ('nobj', 'verts', 'prims', 'tris_gl', 'quads', 'untextured',
                                                         'translucent', 'clut_anim', 'subfile2', 'sha1_file',
                                                         'sha1_norm', 'size', 'flags')},
                                 part_sig=[[p['nv'], p['npr']] for p in info['parts']]))
    return recs, errors


# ---------------------------------------------------------------- quét DRGN0 / nhân vật / quái (scan_drgn0.py)
def scan_drgn0(game):
    """-> (models, errors): mọi CContainer/TmdWithId trong SECT/DRGN0.BIN, SECT/DRGN1.BIN, characters/, monsters/."""
    roots = [os.path.join(game, 'SECT', 'DRGN0.BIN'), os.path.join(game, 'SECT', 'DRGN1.BIN'),
             os.path.join(game, 'characters'), os.path.join(game, 'monsters')]
    out = []
    errs = []
    for root in roots:
        for dp, dns, fns in os.walk(root):
            dns.sort(key=lambda x: natkey(x))
            for fn in sorted(fns, key=lambda x: natkey(x)):
                if fn == 'mrg' or fn.endswith('.png'):
                    continue
                p = os.path.join(dp, fn)
                if os.path.getsize(p) < 0x30:
                    continue
                with open(p, 'rb') as f:
                    h = f.read(16)
                o = u32(h, 0)
                kind = None
                if o == 0x41:
                    kind = 'tmdwithid'
                elif 0xc <= o < os.path.getsize(p) - 12 and o % 4 == 0:
                    with open(p, 'rb') as f:
                        f.seek(o)
                        x = f.read(4)
                    if len(x) == 4 and u32(x, 0) == 0x41:
                        kind = 'ccontainer'
                if not kind:
                    continue
                rel = os.path.relpath(p, game).replace(os.sep, '/')
                b = read_file(game, rel)
                try:
                    info = container_info(b)
                except (ValueError, struct.error) as e:
                    errs.append((rel, kind, str(e)))
                    continue
                out.append(dict(path=rel, kind=kind, nobj=info['nobj'], tris=info['tris_gl'], verts=info['verts'],
                                size=info['size'], sha1_file=info['sha1_file'], sha1_norm=info['sha1_norm'],
                                clut_anim=info['clut_anim'], subfile2=info['subfile2'],
                                translucent=info['translucent'],
                                textured_parts=sum(1 for q in info['parts'] if q['textured'])))
    return out, errs


def story_models(game, lo=STORY_RANGE[0], hi=STORY_RANGE[1]):
    """Mô hình cốt truyện DRGN0/N (lo..hi) có TIM ở N+1 -> [{model, tim, nobj, tris, key, tim_sha1}] (theo N)."""
    out = []
    for n in range(lo, hi + 1):
        rel = 'SECT/DRGN0.BIN/%d' % n
        trel = 'SECT/DRGN0.BIN/%d' % (n + 1)
        if not exists(game, rel) or not exists(game, trel):
            continue
        b = read_file(game, rel)
        if is_container(b) != 'ccontainer':
            continue
        tinfo = parse_tim_info(read_file(game, trel))
        if tinfo is None:
            continue
        try:
            k = model_key(game, rel, b)
        except (ValueError, ref_spec.SpecError, struct.error):
            continue
        out.append(dict(model=rel, tim=trel, nobj=k['nobj'], tris=k['tris'], key=k['key'], tim_sha1=tinfo['sha1']))
    return out


def monster_model(game, mid):
    """Ô quái `mid`: (đường dẫn mô hình, đường dẫn TIM) hoặc None."""
    rel = 'SECT/DRGN0.BIN/%d/32' % (MONSTER_BASE + mid)
    trel = 'monsters/%d/textures/combat' % mid
    if exists(game, rel) and exists(game, trel):
        return rel, trel
    return None


# ---------------------------------------------------------------- truy mô hình cốt truyện qua DEFF cảnh cắt trận
# Mô hình cốt truyện DRGN0/N (TIM N+1) không do trận nạp trực tiếp: script DEFF cảnh cắt trận i (thư mục
# DRGN0/<5512 + 2i>, TIM ở 5511 + 2i — Battle.loadCutsceneDeff) giữ bảng chỉ số file rồi gọi scriptLoadGlobalAsset
# (call 354) + scriptLoadModelToCombatantFromGlobalAssets (call 361). DEFF i được script quái DRGN1/<id quái + 1>
# (Battle.loadEnemyDropsAndScript) gọi bằng call 637 scriptLoadCutsceneDeff hoặc call 623 scriptLoadDeff kiểu 0x5000000.
# Lệnh script: u32 = opcode | số tham số << 8 | chỉ số hàm << 16 (ScriptState.tick); call = opcode 56.
CUTSCENE_DEFF_BASE = 5512
CUTSCENE_DEFF_LAST = 5654            # DRGN0/5655.. là dữ liệu khác (5696 = MCQ bản đồ thế giới)
OP_LOAD_GLOBAL_ASSET = 0x01620338    # call 354, 3 tham số (Battle.java:831)
OP_LOAD_CUTSCENE_DEFF = 0x027d0438   # call 637, 4 tham số (Battle.java:1021)
OP_LOAD_DEFF = 0x026f0538            # call 623, 5 tham số; tham số 5 = 0x5000000 -> cảnh cắt (Battle.java:1007, 7027)
_PARAM_2WORD = (0x1, 0xc, 0x15, 0x16, 0x17, 0x24, 0x25, 0x26, 0x27)
_PARAM_1WORD = tuple(range(0x2, 0x12)) + (0x13, 0x14, 0x20, 0x22, 0x23)


def script_param(b, o):
    """Một tham số lệnh script (ScriptState.parseParam) tại byte o -> (hằng | None, offset sau).

    Kiểu (byte cao): 1 = hằng ở từ kế tiếp; 0 và kiểu lạ = chính từ đó là hằng; còn lại = biến (None)."""
    w = u32(b, o)
    t = w >> 24
    if t == 1:
        return struct.unpack_from('<i', b, o + 4)[0], o + 8
    if t in _PARAM_2WORD:
        return None, o + 8
    if t == 0x21:
        return None, o + 4 + 4 * (((w >> 16 & 0xff) + 3) // 4)
    if t in _PARAM_1WORD or t == 0x12:
        return None, o + 4
    return w, o + 4


def cutscene_deff_dirs(game):
    """[(i, 'SECT/DRGN0.BIN/<5512+2i>')] cho mọi DEFF cảnh cắt trận có trên đĩa."""
    out = []
    i = 0
    while CUTSCENE_DEFF_BASE + 2 * i <= CUTSCENE_DEFF_LAST:
        d = CUTSCENE_DEFF_BASE + 2 * i
        if os.path.isdir(os.path.join(game, 'SECT', 'DRGN0.BIN', str(d))):
            out.append((i, 'SECT/DRGN0.BIN/%d' % d))
        i += 1
    return out


def cutscene_story_tables(game, story_ns):
    """DEFF cảnh cắt trận -> mô hình cốt truyện trong bảng chỉ số của nó. -> {i: [N tăng dần]}.

    Bảng là các bộ ba từ u32 [anim đầu, N, số anim] trong file script của DEFF (file có call 354). Chỉ nhận N thuộc
    story_ns (mô hình DRGN0 có TIM ở N+1), anim đầu trong N+2..N+40 và số anim 1..40 — lọc chặt để bỏ trùng ngẫu nhiên
    với hằng số khác trong script."""
    story_ns = set(story_ns)
    out = {}
    for i, rel in cutscene_deff_dirs(game):
        d = os.path.join(game, *rel.split('/'))
        found = set()
        for fn in sorted(os.listdir(d), key=natkey):
            p = os.path.join(d, fn)
            if fn == 'mrg' or not os.path.isfile(p) or os.path.getsize(p) < 16:
                continue
            b = read_file(game, rel + '/' + fn)
            if struct.pack('<I', OP_LOAD_GLOBAL_ASSET) not in b:
                continue
            n = len(b) // 4
            ws = struct.unpack_from('<%dI' % n, b)
            for k in range(1, n - 1):
                v = ws[k]
                if v in story_ns and v + 2 <= ws[k - 1] <= v + 40 and 1 <= ws[k + 1] <= 40:
                    found.add(v)
        if found:
            out[i] = sorted(found)
    return out


def cutscene_callers(game):
    """{i: [id quái]}: script quái SECT/DRGN1.BIN/<id + 1> gọi DEFF cảnh cắt i bằng hằng (call 637, hoặc call 623 kiểu
    0x5000000). Lệnh có chỉ số là biến thì bỏ (không xác định tĩnh)."""
    root = os.path.join(game, 'SECT', 'DRGN1.BIN')
    pats = (struct.pack('<I', OP_LOAD_CUTSCENE_DEFF), struct.pack('<I', OP_LOAD_DEFF))
    out = collections.defaultdict(set)
    if not os.path.isdir(root):
        return {}
    for fn in sorted(os.listdir(root), key=natkey):
        if not fn.isdigit() or int(fn) < 1:
            continue
        p = os.path.join(root, fn)
        if not os.path.isfile(p) or os.path.getsize(p) < 16:
            continue
        b = read_file(game, 'SECT/DRGN1.BIN/' + fn)
        if not any(x in b for x in pats):
            continue
        n = len(b) // 4
        for k in range(n - 1):
            w = u32(b, 4 * k)
            if w not in (OP_LOAD_CUTSCENE_DEFF, OP_LOAD_DEFF):
                continue
            try:
                ps = []
                o = 4 * k + 4
                for _ in range(w >> 8 & 0xff):
                    v, o = script_param(b, o)
                    ps.append(v)
            except struct.error:
                continue
            if w == OP_LOAD_DEFF and ps[4] != 0x5000000:
                continue
            if ps[0] is not None:
                out[ps[0] & 0xffff].add(int(fn) - 1)
    return {i: sorted(v) for i, v in sorted(out.items())}


# ---------------------------------------------------------------- hoạt cảnh (anims.py)
def anim_hashes(game, records):
    """{'<model>#<obj>': [SHA-1 16 hex của mọi hoạt cảnh cùng số phần]} — dùng chung hoạt cảnh = cùng bộ xương."""
    mrgs = {}
    seen = {}       # đường dẫn file -> SHA-1 16 hex hoặc None (không phải hoạt cảnh cùng số phần)
    out = {}
    for r in records:
        drgn = FIELD_DRGN[r['disc'] - 1]
        adir = os.path.join(game, 'SECT', drgn, str(r['scene_dir']))
        if adir not in mrgs:
            mrgs[adir] = read_mrg(adir)
        am = mrgs[adir]
        hs = set()
        obj = r['obj']
        for k in range(obj * 33 + 1, obj * 33 + 33):
            rr, _ = resolve(am, k)
            if rr < 0:
                continue
            p = os.path.join(adir, str(rr))
            if p not in seen:
                seen[p] = None
                if os.path.isfile(p) and os.path.getsize(p) >= 0x10:
                    with open(p, 'rb') as f:
                        b = f.read()
                    if u32(b, 0) != 0x11:
                        seen[p] = (u16(b, 0xc), sha1(b)[:16])
            if seen[p] is not None and seen[p][0] == r['nobj']:
                hs.add(seen[p][1])
        out['%s#%d' % (r['model'], obj)] = sorted(hs)
    return out


# ---------------------------------------------------------------- khối đỉnh dùng chung (comp.py)
def part_blocks(game, rel):
    """SHA-1 (12 hex) của khối đỉnh từng phần — hai mô hình chung khối = chung bộ phận cơ thể."""
    b = read_file(game, rel)
    try:
        info = parse_container(b)
    except (ValueError, struct.error):
        info = container_info(b)
    return [p['vblock'] for p in info['parts']]


def shared_parts(game, rels, records):
    """Với mỗi mô hình trong rels: từng phần dùng chung khối đỉnh với những mô hình cảnh nào (khác chính nó)."""
    index = collections.defaultdict(set)
    seen = set()
    for r in records:
        if r['model'] in seen:
            continue
        seen.add(r['model'])
        try:
            hs = part_blocks(game, r['model'])
        except (ValueError, struct.error):
            continue
        for h in hs:
            index[h].add(r['model'])
    out = {}
    for rel in rels:
        hs = part_blocks(game, rel)
        mine = {x for x in seen if x != rel}
        out[rel] = [sorted(index[h] & mine, key=natkey) for h in hs]
    return out


# ---------------------------------------------------------------- tự kiểm
def sampled_hashes(game, n=40):
    """SHA-256 của n file mẫu cố định trong game/files (kiểm chỉ đọc)."""
    picks = ['SECT/DRGN21.BIN/5/0', 'SECT/DRGN21.BIN/5/textures/0', 'characters/dart/models/combat/32',
             'characters/dart/textures/combat', 'SECT/DRGN0.BIN/0', 'SECT/DRGN0.BIN/1', 'SUBMAP/NEWROOT.RDT']
    for drgn in FIELD_DRGN:
        ds = field_scene_dirs(game, drgn)
        step = max(1, len(ds) // 8)
        for ad in ds[::step][:8]:
            picks.append('SECT/%s/%d/mrg' % (drgn, ad))
    out = {}
    for rel in picks[:n]:
        p = os.path.join(game, *rel.split('/'))
        if os.path.isfile(p):
            with open(p, 'rb') as f:
                out[rel] = hashlib.sha256(f.read()).hexdigest()
    return out


def selftest(game):
    errs = []
    before = sampled_hashes(game)
    # 1) mẫu đã biết: số phần / tam giác / khoá trùng spec/vectors.json
    with open(os.path.join(SPEC_DIR, 'vectors.json'), encoding='utf-8') as f:
        vec = json.load(f)['models']
    for v in vec:
        k = model_key(game, v['model'])
        if k['key'] != v['modelKey'] or k['nobj'] != v['partCount'] or k['tris'] != v['tris']:
            errs.append('%s: khoa/so lieu %s %d %d != vectors %s %d %d' % (
                v['model'], k['key'][:12], k['nobj'], k['tris'], v['modelKey'][:12], v['partCount'], v['tris']))
        info = container_info(read_file(game, v['model']))
        if info['nobj'] != v['partCount'] or info['tris_gl'] != v['tris']:
            errs.append('%s: doc nhe %dp/%dt != %dp/%dt' % (v['model'], info['nobj'], info['tris_gl'],
                                                            v['partCount'], v['tris']))
    # 2) sha1_norm bền vững: mô phỏng updateTmdPacketIlen (ref_spec) rồi che lại -> cùng sha1_norm
    b = read_file(game, 'SECT/DRGN21.BIN/5/0')
    info = parse_container(b)
    buf = bytearray(b)
    t = u32(buf, 0)
    ob = t + 12
    for i in range(info['nobj']):
        _vt, _nv, _nt, _nn, ptop, npr, _s = struct.unpack_from('<IIIIIIi', buf, ob + i * 0x1c)
        ref_spec.update_tmd_packet_ilen(buf, ob + ptop, npr)
    if parse_container(bytes(buf))['sha1_norm'] != info['sha1_norm']:
        errs.append('sha1_norm doi sau updateTmdPacketIlen')
    if (info['nobj'], info['tris_gl']) != (15, 484):
        errs.append('DRGN21.BIN/5/0: %dp/%dt != 15p/484t' % (info['nobj'], info['tris_gl']))
    # 3) mrg: chuỗi liên kết
    m = {0: (0, 10), 1: (0, 0), 2: (1, 0), 3: (-1, 0)}
    if resolve(m, 2) != (0, 0) or resolve(m, 3) != (-1, 0) or resolve(m, 9) != (-1, 0) or resolve(None, 5) != (5, None):
        errs.append('resolve mrg sai')
    # 4) một cảnh thật: Dart (DRGN21/5 obj 0) có mô hình + TIM + hoạt cảnh cùng số phần
    anim = find_anim(game, 'DRGN21.BIN', 5, 0, 15)
    if anim is None:
        errs.append('khong thay hoat canh 15 phan cho DRGN21.BIN/5 obj 0')
    # 5) tham số script: hằng 1 từ / 2 từ, biến, chuỗi registry (kiểu 0x21 dài theo cmd2)
    blob = struct.pack('<8I', 0x00000144, 0x01000000, 0x05000000, 0x0200000e, 0x21050000, 0, 0, 0x00000007)
    o = 0
    got = []
    for _ in range(5):
        v, o = script_param(blob, o)
        got.append(v)
    if got != [324, 0x5000000, None, None, 7] or o != 32:
        errs.append('script_param sai: %s, o=%d' % (got, o))
    # 6) truy cảnh cắt trận trên dữ liệu: Dragoon Mắt Đỏ cốt truyện DRGN0/324 nằm trong DEFF cảnh cắt 4, do script quái
    #    265 (Kongol) gọi; DRGN0/157 (loại trừ) nằm trong DEFF 49 do quái 387 gọi
    tabs = cutscene_story_tables(game, [324, 157])
    calls = cutscene_callers(game)
    if 324 not in tabs.get(4, []) or 157 not in tabs.get(49, []):
        errs.append('bang DEFF canh cat thieu DRGN0/324 (DEFF 4) hoac DRGN0/157 (DEFF 49): %s' % tabs)
    if calls.get(4) != [265] or 387 not in calls.get(49, []):
        errs.append('nguoi goi DEFF canh cat 4/49 sai: %s / %s' % (calls.get(4), calls.get(49)))
    after = sampled_hashes(game)
    if before != after or not before:
        errs.append('game/files thay doi trong luc chay (hoac khong doc duoc file mau)')
    for e in errs:
        print('LOI:', e)
    print('selftest:', 'DAT' if not errs else 'LOI (%d)' % len(errs), '- %d mau vectors, %d file bam' % (len(vec), len(before)))
    return 0 if not errs else 1


# ---------------------------------------------------------------- CLI
def _dump(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, indent=0, ensure_ascii=False)
        f.write('\n')
    print('ghi', os.path.relpath(path, ROOT))


def main(argv=None):
    utf8_stdout()
    ap = argparse.ArgumentParser(description='Quet kho mo hinh nhan vat (chi doc game/files).')
    ap.add_argument('cmd', choices=['field', 'drgn0', 'anims', 'parts', 'cutscenes', 'selftest'])
    ap.add_argument('paths', nargs='*')
    ap.add_argument('--game', default=None)
    ap.add_argument('--anims', action='store_true', help='field: tim ca hoat canh cung so phan')
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv)
    game = resolve_game(a.game)
    if a.cmd == 'selftest':
        return selftest(game)
    if a.cmd == 'field':
        recs, errors = scan_field(game, with_anims=a.anims)
        _dump(dict(records=recs, errors=errors), out_path('field_scan.json', a.out))
        print('ban ghi', len(recs), 'loi', len(errors), 'container duy nhat', len({r['sha1_norm'] for r in recs}))
        return 0
    if a.cmd == 'drgn0':
        models, errs = scan_drgn0(game)
        _dump(dict(models=models, errors=errs), out_path('drgn0_scan.json', a.out))
        print('mo hinh', len(models), 'loi', len(errs))
        return 0
    if a.cmd == 'anims':
        recs, _ = scan_field(game)
        _dump(anim_hashes(game, recs), out_path('anim_hashes.json', a.out))
        return 0
    if a.cmd == 'cutscenes':
        story = story_models(game)
        tabs = cutscene_story_tables(game, [int(s['model'].rsplit('/', 1)[1]) for s in story])
        calls = cutscene_callers(game)
        for i, ns in sorted(tabs.items()):
            print('DEFF canh cat %2d (SECT/DRGN0.BIN/%d): mo hinh %s <- quai %s' % (
                i, CUTSCENE_DEFF_BASE + 2 * i, ns, calls.get(i, [])))
        return 0
    if a.cmd == 'parts':
        if not a.paths:
            raise SystemExit('LOI: can duong dan mo hinh')
        recs, _ = scan_field(game)
        res = shared_parts(game, a.paths, recs)
        for rel, rows in res.items():
            print(rel)
            for i, others in enumerate(rows):
                print('  phan %2d: %s' % (i, ', '.join(others[:6]) + (' ...' if len(others) > 6 else '') or '-'))
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main())
