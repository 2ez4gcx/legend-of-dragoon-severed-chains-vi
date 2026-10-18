"""scan.py — quét mọi nguồn mô hình nhân vật trong game/files (CHỈ ĐỌC) -> remaster_work/scan.json (SPEC §3.8).

Nguồn được quét (đúng chỗ SC nạp; mrg đã giải, lớp phủ sc-vi):
  field   mọi cảnh SECT/DRGN21..24.BIN/<cảnh> có textures/ (RetailSubmap.prepareSobjs): số đối tượng = số mục của thư mục
          <cảnh+1> - 2; mô hình = mục obj*33 (liên kết ảo -> file thật), TIM = textures/<obj>; đặt TIM ô sobj 0 + UvAdjust.
  battle  characters/<c>/models/{combat,dragoon}/ mục 32 + characters/<c>/textures/<form>; TIM rect gốc.
  story   SECT/DRGN0.BIN/<N> (N = 0..690) là CContainer và <N+1> là TIM; TIM rect gốc.
  monster SECT/DRGN0.BIN/<3137+id>/ mục 32 + monsters/<id>/textures/combat; TIM rect gốc.
  + mọi nguồn {kind, model, tim} của catalog_v1.json (nếu có).
Mỗi cặp (byte mô hình, byte TIM, cách đặt) được băm một lần: khoá LRMK1 (§3.1), véc-tơ FaceHash thô (§3.3.6) và véc-tơ
lưu trong biến thể (§3.3.5, mặt đọc ngoài TIM = 0), mặt LIVE a-c (§3.4).

scan.json (UTF-8, gọn, xác định):
  {format: 'lodsc-remaster scan 1', game, scope, counts, errors[],
   keys: {<khoá>: {nobj, tris, srcFaceCount[], texturedFaceCount, partKeys[], clutAnim, subfile2, kinds[],
                   sources: [{kind, model, tim, placement, objects, examples[]}],
                   variants: [{tim, tims[], faceHashes[hex8], faceHashVectorSha1, rawVectorSha1, live[], zeroFaces,
                               objects}]}},
   catalog: {path, entries: [{id, tier, status, key, sources: [{model, tim, status, key, nobj, tris}]}]}}
  variants: khử trùng theo véc-tơ lưu (faceHashes), xếp theo số đối tượng dùng (giảm dần) rồi thứ tự gặp.
  catalog status: ok | not found | structure mismatch (nobj/tris khác expect) | parse error | key mismatch (các nguồn
  của một mục ra khoá khác nhau). Báo cáo riêng: remaster_work/catalog_report.json.

Cách gọi (từ gốc repo; PYTHONIOENCODING=utf-8; chạy được bằng python.exe của Blender với -I):
  python tools/sc_remaster/scan.py [--game game] [--work DIR | --out FILE] [--catalog FILE] [--scope all|catalog]
                                   [--no-face-hashes] [--progress] [--readonly-check]
      mặc định --work work/upscale/sc_remaster_p1 -> ghi DIR/remaster_work/scan.json (+ catalog_report.json)
      --scope catalog: chỉ giữ khoá mà catalog trỏ tới (vẫn quét mọi nguồn để tìm đủ biến thể, SPEC D12)
      --progress: in dòng '@@P {json}' cho worker; --readonly-check: SHA-256 50 file mẫu trước/sau phải trùng
  python tools/sc_remaster/scan.py keys [--game game] [--readonly-check]
      khoá của mọi file trường như ref_spec.py keys: 6722 file -> 551 khoá (532 trường + 19 trận), 0 khoá trận trong trường
  python tools/sc_remaster/scan.py export <battle|field|story|monster> <model> <tim> --out DIR [--name N] [--anim REL]
      xuất một nguồn theo lược đồ export_tmd.py (lib/export.py)
Exit 0 = đạt, 1 = lỗi. Không bao giờ ghi vào game/; đầu ra là dữ liệu suy ra từ đĩa (không commit).
"""
import argparse
import hashlib
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)          # python -I không tự thêm thư mục script

from lib import (DEFAULT_WORK, GameFileError, SpecError, facehash, gamefiles, lrmkey,  # noqa: E402
                 rel_to_root, tim as timlib, tmd, utf8_stdio)

SCAN_FORMAT = 'lodsc-remaster scan 1'
DEFAULT_CATALOG = os.path.join(HERE, 'catalog', 'catalog_v1.json')
FIELD_DRGNS = ('DRGN21.BIN', 'DRGN22.BIN', 'DRGN23.BIN', 'DRGN24.BIN')
STORY_RANGE = range(0, 691)
MONSTER_BASE = 3137
WORKERS = 8                       # luồng đọc file (I/O; kết quả không phụ thuộc số luồng)
EXPECT_KEYS = dict(field_files=6722, unique_keys=551, field_keys=532, battle_keys=19, battle_keys_in_field=0)


def progress(on, stage, i, n, label=''):
    if on:
        print('@@P ' + json.dumps(dict(stage=stage, i=i, n=n, label=label), ensure_ascii=False), flush=True)


# ---------------------------------------------------------------- liệt kê nguồn
def _numeric_dirs(gf, rel):
    out = []
    for d in gf.listdir(rel):
        if d.isdigit() and gf.isdir(rel + '/' + d):
            out.append(int(d))
    return sorted(out)


def _scene_sources(gf, drgn, ad):
    """Một cảnh (thư mục tài nguyên ad có textures/) -> (nguồn, lỗi)."""
    out, errors = [], []
    root = 'SECT/' + drgn
    adir = '%s/%d' % (root, ad)
    sdir = '%s/%d' % (root, ad + 1)
    if not gf.isdir(sdir):
        return out, ['%s: khong co thu muc script %d' % (adir, ad + 1)]
    try:
        nobj = len(gf.load_dir(sdir)) - 2
        assets = gf.load_dir(adir)
        textures = gf.load_dir(adir + '/textures')
    except GameFileError as e:
        return out, ['%s: %s' % (adir, e)]
    for obj in range(max(nobj, 0)):
        if obj * 33 >= len(assets):
            continue
        e = assets[obj * 33]
        if e is None or e.is_dir:
            continue
        if not (e.has_virtual_size() and e.real()):
            # Java: obj.model = objects[realFileIndex / 33].model (mô hình của đối tượng được liên kết)
            if not e.virtual:
                continue
            tgt = e.real_index // 33 * 33
            e = assets[tgt] if tgt < len(assets) else None
            if e is None or e.is_dir or e.virtual or not e.real():
                continue
        te = textures[obj] if obj < len(textures) else None
        trel = te.path if te is not None and not te.is_dir and te.size else None
        out.append((dict(kind='field', model=e.path, tim=trel, placement='field_slot0'), '%s/%d:%d' % (drgn, ad, obj)))
    return out, errors


def field_sources(gf, errors, workers=WORKERS):
    """RetailSubmap.prepareSobjs trên mọi cảnh có textures/ -> [(nguồn, ví dụ 'DRGN21.BIN/26:0')] (thứ tự xác định;
    các cảnh đọc song song bằng luồng vì việc này chủ yếu là I/O)."""
    scenes = []
    for drgn in FIELD_DRGNS:
        root = 'SECT/' + drgn
        if not gf.isdir(root):
            continue
        for ad in _numeric_dirs(gf, root):
            if gf.isdir('%s/%d/textures' % (root, ad)):
                scenes.append((drgn, ad))
    out = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for res, errs in ex.map(lambda sc: _scene_sources(gf, *sc), scenes):
            out += res
            errors += errs
    return out


def battle_sources(gf):
    out = []
    for c in sorted(gf.listdir('characters')):
        for form in ('combat', 'dragoon'):
            d = 'characters/%s/models/%s' % (c, form)
            if not gf.isdir(d):
                continue
            e = gf.entry(d, 32)
            t = 'characters/%s/textures/%s' % (c, form)
            if e is None or e.is_dir:
                continue
            out.append((dict(kind='battle', model=e.path, tim=t if gf.exists(t) else None, placement='native'),
                        'characters/%s/%s' % (c, form)))
    return out


def story_sources(gf):
    out = []
    for n in STORY_RANGE:
        rel = 'SECT/DRGN0.BIN/%d' % n
        trel = 'SECT/DRGN0.BIN/%d' % (n + 1)
        if not gf.exists(rel) or not gf.exists(trel):
            continue
        if not tmd.looks_like_ccontainer(gf.read(rel)):
            continue
        with open(gf.source_path(trel), 'rb') as f:
            if not timlib.is_tim(f.read(8)):
                continue
        out.append((dict(kind='story', model=rel, tim=trel, placement='native'), 'DRGN0/%d' % n))
    return out


def monster_sources(gf):
    out = []
    ids = sorted(int(x) for x in gf.listdir('monsters') if x.isdigit())
    for mid in ids:
        t = 'monsters/%d/textures/combat' % mid
        d = 'SECT/DRGN0.BIN/%d' % (MONSTER_BASE + mid)
        if not gf.exists(t) or not gf.isdir(d):
            continue
        if gf.size(t) < 8:
            t = None            # TIM rỗng: quái dùng texture nạp ở chỗ khác -> chỉ lấy khoá, không băm
        try:
            e = gf.entry(d, 32)
        except GameFileError:
            continue
        if e is None or e.is_dir or e.size < 16:
            continue
        out.append((dict(kind='monster', model=e.path, tim=t, placement='native'), 'monster/%d' % mid))
    return out


def load_catalog(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


# ---------------------------------------------------------------- băm
class Cache:
    """Byte file khử trùng theo SHA-1 (nhiều file trường là bản sao), mô hình parse một lần theo SHA-1, cặp (mô hình, TIM,
    cách đặt) băm một lần."""

    def __init__(self, gf):
        self.gf = gf
        self.files = {}        # rel -> sha1 hex
        self.blobs = {}        # sha1 hex -> bytes
        self.models = {}       # sha1 -> dict(key, ...) hoặc dict(error)
        self.pairs = {}

    def _store(self, rel, data):
        h = hashlib.sha1(data).hexdigest()
        self.blobs.setdefault(h, data)
        self.files[rel] = h
        return h

    def prefetch(self, rels, workers=WORKERS):
        """Đọc trước (song song, I/O) các file chưa có trong bộ đệm; file không đọc được để lại cho file() báo lỗi."""
        todo = [r for r in rels if r not in self.files]

        def rd(rel):
            try:
                return rel, self.gf.read(rel)
            except GameFileError:
                return rel, None
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for rel, data in ex.map(rd, todo):
                if data is not None:
                    self._store(rel, data)

    def file(self, rel):
        """-> (sha1 hex, bytes); GameFileError nếu không đọc được."""
        h = self.files.get(rel)
        if h is None:
            h = self._store(rel, self.gf.read(rel))
        return h, self.blobs[h]

    def model(self, rel):
        sha, data = self.file(rel)
        if sha not in self.models:
            try:
                m = tmd.parse_ccontainer(data, name=rel)
                key, pks = lrmkey.model_keys(m)
                faces, _ = tmd.model_faces(m)
                tex = tmd.textured_faces(faces)
                self.models[sha] = dict(key=key.hex(), nobj=len(m.parts), tris=tmd.gl_tri_count(faces),
                                        srcFaceCount=m.src_face_counts(), texturedFaceCount=len(tex),
                                        partKeys=[k.hex() for k in pks], clutAnim=m.clut_anim,
                                        subfile2=m.tex_anims is not None)
            except SpecError as e:
                self.models[sha] = dict(error=str(e))
        return sha, self.models[sha]

    def pair(self, mrel, trel, placement):
        msha, mdata = self.file(mrel)
        tsha, tdata = self.file(trel)
        k = (msha, tsha, placement)
        if k in self.pairs:
            return self.pairs[k]
        try:
            m = tmd.parse_ccontainer(mdata, name=mrel)
            t = timlib.parse_tim(tdata)
            vram, irect, crect, adj = timlib.virtual_vram(t, placement)
            if adj is not None:
                tmd.uv_adjust_model(m, *adj)
            faces, _ = tmd.model_faces(m)
            raw = facehash.raw_hashes(vram, faces)
            stored = facehash.stored_from_raw(raw, faces, irect, crect)
            live = sorted(facehash.live_set(m, faces))
            res = dict(stored=stored, raw=raw, live=live, storedSha1=facehash.vector_sha1(stored),
                       rawSha1=facehash.vector_sha1(raw))
        except SpecError as e:
            res = dict(error=str(e))
        self.pairs[k] = res
        return res


# ---------------------------------------------------------------- quét
def run_scan(gf, catalog=None, scope='all', face_hashes=True, show_progress=False, log=print):
    """-> (doc scan.json, báo cáo catalog hoặc None)."""
    t0 = time.time()
    errors = []
    srcs = []
    srcs += field_sources(gf, errors)
    srcs += battle_sources(gf)
    srcs += story_sources(gf)
    srcs += monster_sources(gf)
    if catalog:
        for ent in catalog:
            for s in ent.get('sources', []):
                mrel = gf.resolve(s['model'])
                trel = gf.resolve(s['tim']) if s.get('tim') else None
                if mrel is not None:
                    srcs.append((dict(kind=s['kind'], model=mrel, tim=trel, placement=timlib.placement_for(s['kind'])),
                                 'catalog:' + ent['id']))
    per_kind = defaultdict(int)
    for s, ex in srcs:
        per_kind['catalog' if ex.startswith('catalog:') else s['kind']] += 1
    log('nguon: %d %s (liet ke %.1fs)' % (len(srcs), json.dumps(dict(sorted(per_kind.items()))), time.time() - t0))
    cache = Cache(gf)
    cache.prefetch(sorted({s['model'] for s, _ in srcs} | {s['tim'] for s, _ in srcs if s['tim']}))
    log('doc %d file (%d noi dung khac nhau) trong %.1fs' % (len(cache.files), len(cache.blobs), time.time() - t0))
    # khoá của mọi nguồn
    by_key = {}
    for i, (s, ex) in enumerate(srcs):
        if i % 500 == 0:
            progress(show_progress, 'scan-keys', i, len(srcs), s['model'])
        try:
            _sha, info = cache.model(s['model'])
        except GameFileError as e:
            errors.append('%s: %s' % (s['model'], e))
            continue
        if 'error' in info:
            errors.append('%s: %s' % (s['model'], info['error']))
            continue
        k = info['key']
        rec = by_key.get(k)
        if rec is None:
            rec = by_key[k] = dict(info=info, kinds=set(), sources={}, clut=False, sub2=False)
        rec['kinds'].add(s['kind'])
        rec['clut'] |= info['clutAnim']
        rec['sub2'] |= info['subfile2']
        sk = (s['kind'], s['model'], s['tim'], s['placement'])
        src = rec['sources'].get(sk)
        if src is None:
            src = rec['sources'][sk] = dict(kind=s['kind'], model=s['model'], tim=s['tim'], placement=s['placement'],
                                            objects=0, examples=[])
        if not ex.startswith('catalog:'):
            src['objects'] += 1
        if len(src['examples']) < 3 and ex not in src['examples']:
            src['examples'].append(ex)
    # catalog
    report = None
    keep = None
    if catalog is not None:
        report = catalog_report(gf, cache, catalog)
        if scope == 'catalog':
            keep = {e['key'] for e in report['entries'] if e['key']}
    # biến thể
    keys = sorted(by_key) if keep is None else sorted(k for k in by_key if k in keep)
    out_keys = {}
    for i, k in enumerate(keys):
        if i % 50 == 0:
            progress(show_progress, 'scan-hash', i, len(keys), k)
        rec = by_key[k]
        info = rec['info']
        variants = {}
        order = []
        for sk, src in rec['sources'].items():
            if src['tim'] is None:
                continue
            try:
                ph = cache.pair(src['model'], src['tim'], src['placement'])
            except GameFileError as e:
                errors.append('%s: %s' % (src['tim'], e))
                continue
            if 'error' in ph:
                errors.append('%s + %s: %s' % (src['model'], src['tim'], ph['error']))
                continue
            vk = ph['storedSha1']
            v = variants.get(vk)
            if v is None:
                v = variants[vk] = dict(tim=src['tim'], tims=[], faceHashes=['%08x' % h for h in ph['stored']],
                                        faceHashVectorSha1=vk, rawVectorSha1=ph['rawSha1'], live=ph['live'],
                                        zeroFaces=sum(1 for h in ph['stored'] if h == 0), objects=0)
                order.append(vk)
            if src['tim'] not in v['tims']:
                v['tims'].append(src['tim'])
            v['objects'] += src['objects']
        vlist = sorted((variants[vk] for vk in order), key=lambda v: (-v['objects'], order.index(v['faceHashVectorSha1'])))
        if not face_hashes:
            for v in vlist:
                del v['faceHashes']
        sources = sorted(rec['sources'].values(), key=lambda s: (s['kind'], s['model'], s['tim'] or ''))
        out_keys[k] = dict(nobj=info['nobj'], tris=info['tris'], srcFaceCount=info['srcFaceCount'],
                           texturedFaceCount=info['texturedFaceCount'], partKeys=info['partKeys'],
                           clutAnim=rec['clut'], subfile2=rec['sub2'], kinds=sorted(rec['kinds']),
                           sources=sources, variants=vlist)
    progress(show_progress, 'scan-hash', len(keys), len(keys), 'xong')
    counts = dict(sources=len(srcs), unique_model_files=len(cache.models), keys_total=len(by_key), keys_written=len(keys),
                  pairs_hashed=len(cache.pairs), variants=sum(len(v['variants']) for v in out_keys.values()),
                  errors=len(errors))
    doc = dict(format=SCAN_FORMAT, spec='LRM spec 1 (tools/sc_remaster/SPEC.md §3.1, §3.3, §3.4)',
               game=gf.files.replace('\\', '/'), scope=scope, counts=counts, errors=errors, keys=out_keys)
    if report is not None:
        doc['catalog'] = report
    return doc, report


def catalog_report(gf, cache, catalog):
    """Mỗi mục catalog_v1: khoá, 'not found' hoặc 'structure mismatch' (SPEC P1)."""
    entries = []
    for ent in catalog:
        srep = []
        keys = []
        for s in ent.get('sources', []):
            r = dict(model=s['model'], tim=s.get('tim'))
            mrel = gf.resolve(s['model'])
            if mrel is None:
                r.update(status='not found', key=None)
                srep.append(r)
                continue
            try:
                _sha, info = cache.model(mrel)
            except GameFileError:
                r.update(status='not found', key=None)
                srep.append(r)
                continue
            if 'error' in info:
                r.update(status='parse error', key=None, error=info['error'])
                srep.append(r)
                continue
            r.update(key=info['key'], nobj=info['nobj'], tris=info['tris'])
            exp = ent.get('expect') or {}
            if ('nobj' in exp and exp['nobj'] != info['nobj']) or ('tris' in exp and exp['tris'] != info['tris']):
                r['status'] = 'structure mismatch'
            elif s.get('tim') and gf.resolve(s['tim']) is None:
                r['status'] = 'not found'
                r['error'] = 'thieu TIM'
            else:
                r['status'] = 'ok'
                keys.append(info['key'])
            srep.append(r)
        if not srep:
            status, key = 'not found', None
        elif len(set(keys)) > 1:
            status, key = 'key mismatch', None
        elif keys and all(x['status'] == 'ok' for x in srep):
            status, key = 'ok', keys[0]
        elif keys:
            status, key = 'partial', keys[0]
        else:
            st = [x['status'] for x in srep]
            status = 'structure mismatch' if 'structure mismatch' in st else st[0]
            key = None
        e = dict(id=ent.get('id'), tier=ent.get('tier'), status=status, key=key, sources=srep)
        if ent.get('key_us'):
            e['key_us_equal'] = (key == ent['key_us'])
        entries.append(e)
    summary = defaultdict(int)
    for e in entries:
        summary[e['status']] += 1
    return dict(entries=entries, summary=dict(sorted(summary.items())))


# ---------------------------------------------------------------- keys (đối chiếu ref_spec.py keys)
def field_candidates(gf):
    """Như keyscan.py / ref_spec.py: file thật tên số, chia hết cho 33, >= 16 byte (không giải mrg)."""
    out = []
    for drgn in FIELD_DRGNS:
        root = 'SECT/' + drgn
        for d in _numeric_dirs(gf, root):
            dp = '%s/%d' % (root, d)
            for f in sorted(gf.listdir(dp)):
                if not f.isdigit() or int(f) % 33:
                    continue
                rel = dp + '/' + f
                if gf.isfile(rel) and os.path.getsize(gf.abs(rel)) >= 16:
                    out.append(rel)
    return out


def count_keys(gf, log=print):
    """-> (dict số liệu, danh sách lỗi) giống ref_spec.py keys."""
    keys = defaultdict(list)
    errs = []
    battle = {}
    for s, ex in battle_sources(gf):
        m = tmd.parse_ccontainer(gf.read(s['model']), scan_filter=True)
        if m is None:
            errs.append('%s: khong doc duoc' % s['model'])
            continue
        k = lrmkey.model_keys(m)[0].hex()
        battle[ex] = k
        keys[k].append(ex)
    nfield = 0
    rejected = 0
    field_keys = set()
    memo = {}                      # SHA-1 byte file -> khoá hex | None | 'spec' (file trùng nhau rất nhiều)
    for rel in field_candidates(gf):
        data = gf.read(rel)
        h = hashlib.sha1(data).digest()
        if h not in memo:
            try:
                m = tmd.parse_ccontainer(data, scan_filter=True)
                memo[h] = None if m is None else lrmkey.model_keys(m)[0].hex()
            except SpecError:
                memo[h] = 'spec'
        k = memo[h]
        if k == 'spec':
            rejected += 1
            continue
        if k is None:
            continue
        nfield += 1
        keys[k].append(rel)
        field_keys.add(k)
    bkeys = set(battle.values())
    res = dict(field_files=nfield, unique_keys=len(keys), field_keys=len(field_keys), battle_keys=len(bkeys),
               battle_keys_in_field=len(bkeys & field_keys), field_rejected_spec=rejected)
    return res, errs, battle


# ---------------------------------------------------------------- kiểm chỉ-đọc
def sample_hashes(gf, rels, n=50):
    rels = sorted(set(r for r in rels if r))
    step = max(1, len(rels) // n)
    out = {}
    for r in rels[::step][:n]:
        p = gf.source_path(r)
        with open(p, 'rb') as f:
            out[p] = hashlib.sha256(f.read()).hexdigest()
    return out


def _sample_rels(gf):
    rels = [s['model'] for s, _ in battle_sources(gf)] + [s['tim'] for s, _ in battle_sources(gf)]
    rels += field_candidates(gf)[::50]
    return rels


# ---------------------------------------------------------------- CLI
def main(argv=None):
    utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('cmd', nargs='?', default='run', choices=['run', 'keys', 'export'])
    ap.add_argument('args', nargs='*')
    ap.add_argument('--game', default=None)
    ap.add_argument('--work', default=DEFAULT_WORK)
    ap.add_argument('--out')
    ap.add_argument('--catalog', default=DEFAULT_CATALOG)
    ap.add_argument('--scope', default='all', choices=['all', 'catalog'])
    ap.add_argument('--no-face-hashes', action='store_true')
    ap.add_argument('--progress', action='store_true')
    ap.add_argument('--readonly-check', action='store_true')
    ap.add_argument('--name')
    ap.add_argument('--anim')
    a = ap.parse_args(argv)
    gf = gamefiles.GameFiles(a.game)
    before = sample_hashes(gf, _sample_rels(gf)) if a.readonly_check else None
    ok = True
    t0 = time.time()
    if a.cmd == 'keys':
        res, errs, battle = count_keys(gf)
        print('field sobj models parsed: %d  unique keys total: %d  (field %d + battle %d)' % (
            res['field_files'], res['unique_keys'], res['field_keys'], res['battle_keys']))
        print('battle keys also seen in field files: %d' % res['battle_keys_in_field'])
        for ex, k in sorted(battle.items()):
            print('  %-28s %s' % (ex, k))
        for k, v in EXPECT_KEYS.items():
            if res[k] != v:
                print('LOI: %s = %d, mong doi %d' % (k, res[k], v))
                ok = False
        for e in errs:
            print('LOI:', e)
            ok = False
    elif a.cmd == 'export':
        from lib import export
        if len(a.args) != 3 or not a.out:
            ap.error('export <kind> <model> <tim> --out DIR')
        kind, model, tim = a.args
        try:
            summary, errs = export.export_source(gf, kind, model, tim, anim_rel=a.anim, name=a.name, out_dir=a.out)
        except (export.ExportError, ValueError) as e:      # ValueError: kind lạ
            summary, errs = None, [str(e)]
        if summary is not None:
            print(json.dumps(summary, ensure_ascii=False, indent=1))
        for e in errs[:50]:
            print('LOI: ' + e)
        ok = not errs
    else:
        catalog = load_catalog(a.catalog)
        if a.scope == 'catalog' and catalog is None:
            print('LOI: --scope catalog nhung khong co %s' % a.catalog)
            sys.exit(1)
        doc, report = run_scan(gf, catalog, a.scope, not a.no_face_hashes, a.progress)
        out = a.out or os.path.join(a.work, 'remaster_work', 'scan.json')
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        text = json.dumps(doc, ensure_ascii=False, separators=(',', ':')) + '\n'
        tmp = out + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        os.replace(tmp, out)
        c = doc['counts']
        print('scan: %d nguon, %d file mo hinh, %d khoa (ghi %d), %d cap bam, %d bien the, %d loi, %.1fs' % (
            c['sources'], c['unique_model_files'], c['keys_total'], c['keys_written'], c['pairs_hashed'],
            c['variants'], c['errors'], time.time() - t0))
        print('da ghi %s (%d byte)' % (rel_to_root(out), len(text.encode('utf-8'))))
        if report is not None:
            rp = os.path.join(os.path.dirname(os.path.abspath(out)), 'catalog_report.json')
            with open(rp, 'w', encoding='utf-8', newline='\n') as f:
                f.write(json.dumps(report, ensure_ascii=False, indent=1) + '\n')
            print('catalog: %s -> %s' % (json.dumps(report['summary'], ensure_ascii=False), rel_to_root(rp)))
            for e in report['entries']:
                if e['status'] != 'ok':
                    print('  %-34s %s' % (e['id'], e['status']))
        for e in doc['errors'][:20]:
            print('  canh bao: %s' % e)
    if before is not None:
        after = sample_hashes(gf, _sample_rels(gf))
        changed = [p for p in before if after.get(p) != before[p]]
        print('readonly-check: %d file mau, %d thay doi' % (len(before), len(changed)))
        if changed:
            ok = False
    print('%s (%.1fs)' % ('DAT' if ok else 'KHONG DAT', time.time() - t0))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
