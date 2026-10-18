"""check_iface.py — sau lint.ps1: kiểm giao diện giữa các tầng shader và các điều kiện "không đổi so với gốc" của mọi bộ charfx.

shaderc dịch từng tầng riêng lẻ, nên VS_OUT/GS_OUT lệch giữa các file chỉ lộ ra lúc link trong game; script này bắt trước.
Cách gọi:
  python tools/sc_charfx/check_iface.py          (lint.ps1 tự gọi sau khi dịch)
Đầu vào: out/charfx_lint/<bộ>/{lint.txt, es_out/*.glsl} (lint.ps1), out/charfx_variants/<bộ>/*.{vsh,gsh,fsh} + manifest.json
(make_variants.py). Kiểm cho từng bộ:
  1. đủ 13 shader đã dịch
  2. VS_OUT của tmd.vsh == battle_tmd.vsh == đầu vào tmd.gsh (tên, kiểu, nội suy, thứ tự)
  3. GS_OUT đầu ra tmd.gsh == đầu vào tmd.fsh == đầu vào battle_tmd.fsh
  4. tập uniform thường và tập khối uniform của từng chương trình (TMD = tmd.vsh+gsh+fsh, Battle TMD = battle_tmd.vsh +
     tmd.gsh + battle_tmd.fsh) == bản gốc (SC chỉ đặt uniform qua ShaderOptions: uniform mới sẽ không bao giờ được đặt)
  5. số vị trí: VS_OUT <= 16, GS_OUT <= 15 (mức tối thiểu GLES 3.2 của bản Android: mỗi biến một vị trí)
  6. ngân sách GS: max_vertices x (thành phần GS_OUT + 4 của gl_Position) <= 1024 (in thêm cách tính theo ô vec4)
  7. 8 shader không thuộc TMD dịch ra y hệt gốc
  8. tự kiểm: _off (mọi công tắc 0) dịch ra y hệt gốc; _pnraw (pn/ nguyên trạng) dịch ra y hệt bộ pn
  9. z_off và all: nguồn giống hệt nhau trừ dòng "#define ENH_FORCE" (z_off = đúng mã của all, tắt lúc chạy); ENH_FORCE là
     0 ở z_off / 1 ở all trong cả tmd.fsh, battle_tmd.fsh và tmd.gsh (cổng PN), và 1 trong tmd.gsh của pn
 10. dòng #define ENH_* giống nhau trong cả 5 file của mỗi bộ; SHA-256 trong manifest.json khớp file trên đĩa
Exit 0 = đạt hết, 1 = có lỗi (in từng lỗi).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
LINT = os.path.join(ROOT, 'out', 'charfx_lint')
VARIANTS = os.path.join(ROOT, 'out', 'charfx_variants')
TMD = ('tmd.vsh', 'battle_tmd.vsh', 'tmd.gsh', 'tmd.fsh', 'battle_tmd.fsh')
PROGRAMS = {'TMD': ('tmd.vsh', 'tmd.gsh', 'tmd.fsh'), 'Battle TMD': ('battle_tmd.vsh', 'tmd.gsh', 'battle_tmd.fsh')}
COMPONENTS = {'float': 1, 'int': 1, 'uint': 1, 'bool': 1, 'vec2': 2, 'ivec2': 2, 'uvec2': 2, 'vec3': 3, 'ivec3': 3,
              'uvec3': 3, 'vec4': 4, 'ivec4': 4, 'uvec4': 4}
REQUIRED = ('z_off', 'pn', 'l2t', 'all', '_off', '_pnraw')


def load(variant):
    """file name -> transpiled ES source, matched through lint.txt ('<name> <STAGE> uniforms=N -> <key>.glsl')."""
    d = os.path.join(LINT, variant)
    raw = open(os.path.join(d, 'lint.txt'), 'rb').read()
    txt = raw.decode('utf-16') if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else raw.decode('utf-8', 'replace')
    out = {}
    for m in re.finditer(r'^(\S+\.(?:vsh|gsh|fsh)) \w+ uniforms=\d+ -> (\w+)\.glsl', txt, re.M):
        with open(os.path.join(d, 'es_out', m.group(2) + '.glsl'), encoding='utf-8') as fh:
            out[m.group(1)] = fh.read()
    return out


def block(src, direction, name):
    m = re.search(r'layout\(location = 0\) ' + direction + r' ' + name + r'\s*\{(.*?)\}', src, re.S)
    if not m:
        return None
    # precision qualifiers differ by stage default only (GS implicit highp, FS explicit highp): ignore them
    return [' '.join(w for w in l.split() if w not in ('highp', 'mediump', 'lowp')) for l in m.group(1).split(';') if l.strip()]


def components(members):
    return sum(COMPONENTS[m.split()[-2]] for m in members)


def uniforms(src):
    """plain uniforms incl. samplers ('layout(location = 6, binding = 3) uniform highp usampler2D tex15;')"""
    return set(re.findall(r'^(?:layout\([^)]*\)\s*)?uniform\s+(?:highp\s+|mediump\s+|lowp\s+)?\w+\s+(\w+)\s*;', src, re.M))


def ublocks(src):
    """uniform blocks: 'layout(std140) uniform lighting' + newline + '{'"""
    return set(re.findall(r'^layout\([^)]*\)\s*uniform\s+(\w+)\s*\n\s*\{', src, re.M))


def sha(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def src_files(v):
    out = {}
    for f in TMD:
        with open(os.path.join(VARIANTS, v, f), encoding='utf-8', newline='') as fh:
            out[f] = fh.read()
    return out


def main():
    errors = []
    if not os.path.isdir(LINT):
        print('LOI: chua co %s (chay lint.ps1)' % LINT)
        return 1
    with open(os.path.join(VARIANTS, 'manifest.json'), encoding='utf-8') as fh:
        manifest = json.load(fh)
    lint_dirs = sorted(d for d in os.listdir(LINT) if os.path.isfile(os.path.join(LINT, d, 'lint.txt')))
    for v in ('stock',) + REQUIRED:
        if v not in lint_dirs:
            errors.append('thieu ket qua lint cua bo %s' % v)
    for v in manifest['variants']:
        if v not in lint_dirs:
            errors.append('bo %s co trong manifest nhung chua lint (chay lai lint.ps1)' % v)
    if errors:
        for e in errors:
            print('LOI:', e)
        return 1

    es = {v: load(v) for v in lint_dirs}
    stock = es['stock']
    stock_unis = {p: set().union(*(uniforms(stock[f]) for f in fs)) for p, fs in PROGRAMS.items()}
    stock_blocks = {p: set().union(*(ublocks(stock[f]) for f in fs)) for p, fs in PROGRAMS.items()}

    for v in lint_dirs:
        s = es[v]
        msgs = []
        if len(s) != 13:
            msgs.append('chi dich %d/13 shader' % len(s))
        if not all(f in s for f in TMD):
            print('%-8s FAIL thieu shader TMD' % v)
            errors.append(v)
            continue
        vs = [block(s['tmd.vsh'], 'out', 'VS_OUT'), block(s['battle_tmd.vsh'], 'out', 'VS_OUT'), block(s['tmd.gsh'], 'in', 'VS_OUT')]
        gs = [block(s['tmd.gsh'], 'out', 'GS_OUT'), block(s['tmd.fsh'], 'in', 'GS_OUT'), block(s['battle_tmd.fsh'], 'in', 'GS_OUT')]
        if None in vs or not (vs[0] == vs[1] == vs[2]):
            msgs.append('VS_OUT lech giua tmd.vsh / battle_tmd.vsh / tmd.gsh: %r' % (vs,))
        if None in gs or not (gs[0] == gs[1] == gs[2]):
            msgs.append('GS_OUT lech giua tmd.gsh / tmd.fsh / battle_tmd.fsh: %r' % (gs,))
        for p, fs in PROGRAMS.items():
            u = set().union(*(uniforms(s[f]) for f in fs))
            if u != stock_unis[p]:
                msgs.append('%s: uniform khac goc: them %s, mat %s' % (p, sorted(u - stock_unis[p]), sorted(stock_unis[p] - u)))
            b = set().union(*(ublocks(s[f]) for f in fs))
            if b != stock_blocks[p]:
                msgs.append('%s: khoi uniform khac goc: them %s, mat %s' % (p, sorted(b - stock_blocks[p]), sorted(stock_blocks[p] - b)))
        nvs, ngs = len(vs[0] or []), len(gs[0] or [])
        if nvs > 16 or ngs > 15:
            msgs.append('vuot muc toi thieu GLES 3.2: VS_OUT %d (<= 16), GS_OUT %d (<= 15)' % (nvs, ngs))
        mv = re.search(r'max_vertices = (\d+)', s['tmd.gsh'])
        mv = int(mv.group(1)) if mv else 0
        comps = components(gs[0] or []) + 4
        total, total4 = mv * comps, mv * (ngs + 1) * 4
        if not mv or total > 1024:
            msgs.append('ngan sach GS: %d dinh x %d thanh phan = %d > 1024' % (mv, comps, total))
        for f in s:
            if f not in TMD and stock.get(f) != s[f]:
                msgs.append('%s (khong thuoc TMD) dich ra khac goc' % f)
        if v == '_off':
            for f in TMD:
                if s[f] != stock[f]:
                    msgs.append('_off: %s dich ra khac goc (cho sua khong tro thanh "tat" khi cong tac = 0)' % f)
        if v == '_pnraw':
            for f in s:
                if s[f] != es['pn'].get(f):
                    msgs.append('_pnraw: %s dich ra khac bo pn (cho sua L2/T khong tro thanh "tat" tren nen PN)' % f)
        if v != 'stock':
            src = src_files(v)
            defs = [tuple(l for l in src[f].split('\n') if re.match(r'#define ENH_(PN|LIGHTING|TEXFILTER|PACK) ', l)) for f in TMD]
            expected = 0 if v == '_pnraw' else 4  # _pnraw = pn/ files untouched + stock FS: no switch lines at all
            if len(set(defs)) != 1 or len(defs[0]) != expected:
                msgs.append('dong #define ENH_* khong giong nhau trong 5 file: %r' % (defs,))
            want = manifest['variants'].get(v, {}).get('sha256', {})
            for f in TMD:
                if want.get(f) != sha(src[f]):
                    msgs.append('%s khac SHA-256 trong manifest.json (sua tay hoac chua chay lai make_variants.py)' % f)
        print('%-8s VS_OUT %2d  GS_OUT %2d  GS %2d dinh x %2d = %4d thanh phan (%4d theo o vec4)  %s' % (
            v, nvs, ngs, mv, comps, total, total4, 'OK' if not msgs else 'FAIL'))
        for m in msgs:
            print('    ', m)
        if msgs:
            errors.append(v)

    # z_off must run exactly the code of 'all' with the runtime gates closed
    a, z = src_files('all'), src_files('z_off')
    for f in TMD:
        la = [l for l in a[f].split('\n') if not l.startswith('#define ENH_FORCE ')]
        lz = [l for l in z[f].split('\n') if not l.startswith('#define ENH_FORCE ')]
        if la != lz:
            print('FAIL z_off/%s khac all/%s ngoai dong #define ENH_FORCE' % (f, f))
            errors.append('z_off~all')
        fa = re.findall(r'^#define ENH_FORCE (\d)', a[f], re.M)
        fz = re.findall(r'^#define ENH_FORCE (\d)', z[f], re.M)
        # FS: L2/T gate; tmd.gsh (PN base): PN gate -> z_off stays stock even when the loader writes PN bits
        if f.endswith('.fsh') or f == 'tmd.gsh':
            if fa != ['1'] or fz != ['0']:
                print('FAIL %s: ENH_FORCE all=%s z_off=%s (can 1 / 0)' % (f, fa, fz))
                errors.append('force')
    # pn: PN must follow the loader bits only (ENH_FORCE 1 in its geometry shader)
    if re.findall(r'^#define ENH_FORCE (\d)', src_files('pn')['tmd.gsh'], re.M) != ['1']:
        print('FAIL pn/tmd.gsh: can dung mot dong #define ENH_FORCE 1')
        errors.append('force pn')
    if errors:
        print('LOI: %d muc khong dat' % len(errors))
        return 1
    print('DAT: %d bo (gom stock) — giao dien khop, uniform khong doi, _off = goc, _pnraw = pn, z_off = all tat luc chay' % len(lint_dirs))
    return 0


if __name__ == '__main__':
    sys.exit(main())
