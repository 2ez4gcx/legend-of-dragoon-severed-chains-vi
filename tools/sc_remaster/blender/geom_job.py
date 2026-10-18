"""geom_job.py — chạy pipeline hình học v2 (P2) cho một lô mô hình trong MỘT phiên Blender không giao diện.

Cách gọi (từ gốc repo):
  <blender.exe> -b --factory-startup --python tools/sc_remaster/blender/geom_job.py -- <batch.json>
  <blender.exe> -b --factory-startup --python tools/sc_remaster/blender/geom_job.py -- --selftest
      tự kiểm trên mô hình tổng hợp (không cần dữ liệu game), mã thoát 0 = đạt, 1 = lỗi.
batch.json:
  {"jobs": [{"name": "dart_combat", "json": "<model.json theo lược đồ export_tmd.py>", "out": "<thư mục ra>"}, ...],
   "game": "<thư mục game/files, mặc định ROOT/game/files>", "rules": "<rules.json, mặc định cạnh file này>",
   "params": {<ghi đè rules, vd. "levels": [1], "inflate": {"enabled": false}>}, "levels": [1, 2]}
  Đường dẫn tương đối tính theo thư mục chứa batch.json. Mỗi job có thể có "params" riêng (gộp sau params của lô).
Mỗi job: đọc JSON + mọi hoạt cảnh (chỉ đọc game/files), remaster_core.process_model dựng ứng viên L0/L1/L2 từng phần,
qa/check_geom.select_levels hạ phần lỗi L2 -> L1 -> L0, ghi <out>/geom_L1.npz, <out>/geom_L2.npz (lược đồ SPEC §3.8, xem
docstring remaster_core.py) và <out>/qa.json (thống kê, hồ sơ phần, mức đạt, lý do hạ mức, báo cáo QA từng mức).
Giữa các job gọi bpy.ops.wm.read_factory_settings(use_empty=True).
stdout: '@@P {"stage": "G", "i": i, "n": n, "label": name}' trước mỗi job, '@@E {"key": name, "stage": "G", "msg": ...}'
khi job lỗi, '@@DONE {"ok": [...], "failed": [...], "seconds": s}' ở cuối.
Mã thoát: 0 = mọi job xong, 2 = một phần lỗi, 1 = lỗi nặng (batch hỏng).
"""
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'qa'))

import numpy as np  # noqa: E402

import remaster_core as rc  # noqa: E402
import check_geom as cg  # noqa: E402


def _emit(tag, obj):
    print('%s %s' % (tag, json.dumps(obj, ensure_ascii=False)), flush=True)


def _abs(base, p):
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))


def _rel_root(p):
    """Đường dẫn tương đối theo gốc repo nếu nằm trong đó, ngược lại đường dẫn tuyệt đối (khác ổ đĩa trên Windows:
    os.path.relpath ném ValueError)."""
    try:
        r = os.path.relpath(p, rc.ROOT)
    except ValueError:
        r = '..'
    return (p if r.startswith('..') else r).replace('\\', '/')


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return o


def run_job(job, base, batch, bpy_version):
    t0 = time.perf_counter()
    c0 = time.process_time()
    params = {}
    rc._merge(params, batch.get('params') or {})
    rc._merge(params, job.get('params') or {})
    rules_path = batch.get('rules')
    rules = rc.load_rules(_abs(base, rules_path) if rules_path else None, params)
    levels = list(job.get('levels') or batch.get('levels') or rules.get('levels', [1, 2]))
    game = _abs(base, batch['game']) if batch.get('game') else rc.DEFAULT_GAME
    src = _abs(base, job['json'])
    out = _abs(base, job['out'])
    os.makedirs(out, exist_ok=True)
    with open(src, encoding='utf-8') as f:
        doc = json.load(f)
    doc['name'] = job.get('name') or doc.get('name') or os.path.splitext(os.path.basename(src))[0]
    anims = rc.find_anims(doc, game)
    res = rc.process_model(doc, rules, anims, levels, name=doc['name'])
    t1 = time.perf_counter()
    model = cg.Model(doc, rules, game)
    cands = res['parts']
    sfc = [len(p['faces']) for p in doc['parts']]
    qa = dict(format=1, generator=rc.GENERATOR, blender=bpy_version, name=doc['name'], source=doc.get('source'),
              json=_rel_root(src),
              rules_sha1=rules['rules_sha1'], params=params, anims=[a['path'] for a in anims],
              anims_qa=model.anims, keyframes=res['stats']['keyframes'], profiles=res['profiles'], parts=res['info'],
              core=res['stats'], levels={})
    for L in levels:
        pms, log = cg.select_levels(model, cands, L)
        rep = cg.model_report(model, pms, L)
        arrays = rc.npz_arrays(pms, L, sfc)
        sha = rc.write_npz(os.path.join(out, 'geom_L%d.npz' % L), arrays)
        qa['levels'][str(L)] = dict(npz='geom_L%d.npz' % L, sha1=sha, tris=rep['tris'], part_levels=rep['part_levels'],
                                    fallbacks=log, report=rep, ok=not rep['fail'])
    t2 = time.perf_counter()
    qa['seconds'] = dict(core=round(t1 - t0, 3), qa=round(t2 - t1, 3), total=round(t2 - t0, 3),
                         cpu=round(time.process_time() - c0, 3))
    qa['ok'] = all(v['ok'] for v in qa['levels'].values())
    tmp = os.path.join(out, 'qa.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(_jsonable(qa), f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(out, 'qa.json'))
    return qa


def selftest(bpy):
    """Tự kiểm trong Blender, không cần dữ liệu game: remaster_core.selftest() (numpy), rồi hai lượt process_model trên mô
    hình tổng hợp (remaster_core.synth_model) -> select_levels / model_report không lỗi, có phần đạt L1 / L2, hai lượt ghi
    npz trùng byte, check_geom.check_files đọc lại npz đạt."""
    import shutil
    import tempfile
    errs = []
    if rc.selftest():
        errs.append('remaster_core.selftest')
    doc = rc.synth_model()
    rules = rc.load_rules()
    sfc = [len(p['faces']) for p in doc['parts']]
    R0, T0 = rc.kf0_pose(doc)
    tmp = tempfile.mkdtemp(prefix='geom_job_selftest_')
    shas = []
    try:
        for run in range(2):
            bpy.ops.wm.read_factory_settings(use_empty=True)
            res = rc.process_model(doc, rules, [], [1, 2], name='synth')
            for st in res['info']:
                for L, s in st['levels'].items():
                    if 'error' in s:
                        errs.append('phan %d L%s: %s' % (st['index'], L, s['error']))
            model = cg.Model(doc, rules, R=R0, T=T0)
            out = os.path.join(tmp, 'run%d' % run)
            os.makedirs(out)
            sh = {}
            for L in (1, 2):
                pms, log = cg.select_levels(model, res['parts'], L)
                rep = cg.model_report(model, pms, L)
                if rep['fail']:
                    errs.append('L%d: %s' % (L, rep['fail']))
                if max(rep['part_levels']) != L:
                    errs.append('L%d: khong phan nao dat muc %d (%s, ha muc %s)' % (L, L, rep['part_levels'], log))
                sh[L] = rc.write_npz(os.path.join(out, 'geom_L%d.npz' % L), rc.npz_arrays(pms, L, sfc))
                if run == 0:
                    print('selftest L%d: %d tam giac, muc %s, ha muc %s, IoU %.4f, hausdorff %s' % (
                        L, rep['tris'], rep['part_levels'], [(x['part'], x['frm'], x['to'], x['reason']) for x in log],
                        rep['iou']['min'], [p.get('hausdorff_rel') for p in rep['parts']]))
            shas.append(sh)
            chk = cg.check_files(doc, out, rules, tmp, [1, 2])
            if chk['fail']:
                errs.append('check_files: %s' % chk['fail'])
        if shas[0] != shas[1]:
            errs.append('npz hai luot khac nhau %s' % shas)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if 'PIL' in sys.modules:
        errs.append('PIL da duoc import')
    print('selftest geom_job:', 'DAT' if not errs else 'LOI %s' % errs, flush=True)
    return 0 if not errs else 1


def main():
    import bpy
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    if argv and argv[0] == '--selftest':
        return selftest(bpy)
    if not argv:
        print('LOI: thieu <batch.json>')
        return 1
    try:
        bpath = os.path.abspath(argv[0])
        with open(bpath, encoding='utf-8') as f:
            batch = json.load(f)
        jobs = batch['jobs']
    except Exception as e:
        print('LOI: batch hong: %s' % e)
        return 1
    base = os.path.dirname(bpath)
    t0 = time.perf_counter()
    ok, failed = [], []
    for i, job in enumerate(jobs):
        name = job.get('name') or os.path.splitext(os.path.basename(job.get('json', '?')))[0]
        _emit('@@P', dict(stage='G', i=i, n=len(jobs), label=name))
        try:
            bpy.ops.wm.read_factory_settings(use_empty=True)
            qa = run_job(job, base, batch, bpy.app.version_string)
            ok.append(name)
            print('G %s: %.2fs (core %.2f, qa %.2f, cpu %.2f) L1 %s tam giac, L2 %s tam giac, ha muc %s, dat=%s' % (
                name, qa['seconds']['total'], qa['seconds']['core'], qa['seconds']['qa'], qa['seconds']['cpu'],
                qa['levels'].get('1', {}).get('tris'), qa['levels'].get('2', {}).get('tris'),
                {L: len(v['fallbacks']) for L, v in qa['levels'].items()}, qa['ok']), flush=True)
        except Exception as e:
            failed.append(name)
            _emit('@@E', dict(key=name, stage='G', msg='%s: %s' % (type(e).__name__, e)))
            traceback.print_exc()
    _emit('@@DONE', dict(ok=ok, failed=failed, seconds=round(time.perf_counter() - t0, 2)))
    return 0 if not failed else 2


if __name__ == '__main__':
    code = main()
    sys.stdout.flush()
    sys.exit(code)
