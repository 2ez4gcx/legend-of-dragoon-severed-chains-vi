"""fake_worker.py — worker GIẢ cho kiểm thử công cụ "Tạo mô hình HD" (tools/remaster_tool/test/run_tests.ps1).

Theo đúng hợp đồng dòng lệnh SPEC §3.9 mà công cụ gọi (chạy bằng python -I, chỉ thư viện chuẩn):
    worker.py run --game <g> --blender <exe> [--esrgan <dir> | --no-ai] [--scope v1|v1+optional]
                  [--quality pc|mobile|both] [--texture hd|retail] [--resume]
    worker.py probe --game <g> --blender <exe> [--esrgan <dir>]
    worker.py export-android --game <g> --out <zip>
    worker.py clean --game <g>
In "@@P {stage,i,n,label}", "@@E {key,stage,msg}", "@@DONE {ok,failed,skipped,minutes}" ra stdout (UTF-8);
mã thoát 0 xong / 2 một phần / 1 lỗi.

Lệnh run giả lập một lần tạo: sinh 1 tiến trình con (python ngủ) để kiểm "Huỷ diệt cả cây tiến trình", chạy N job
(mỗi job ghi vào remaster_work/state.json — --resume bỏ qua job đã xong), rồi ghi remaster/ từ bộ mẫu TỔNG HỢP
(không phải dữ liệu Sony) do tools/sc_remaster/spec/synth_cube.py --out tạo: textures/ trước, models/, rồi
index.tsv.tmp -> index.tsv, rồi manifest.json.

Biến môi trường:
    FAKE_WORKER_SAMPLE      thư mục chứa remaster/ mẫu (bắt buộc cho run)
    FAKE_WORKER_JOBS        số job (mặc định 6)
    FAKE_WORKER_DELAY       giây mỗi job (mặc định 0.05)
    FAKE_WORKER_FAIL_JOB    chỉ số job lỗi → @@E và mã thoát 2
    FAKE_WORKER_PROBE_FAIL  =1 → probe trả mã 1
    FAKE_WORKER_BADZIP      =1 → export-android thêm mục lạ "remaster/../evil.txt"
    FAKE_WORKER_BAD_LINES   =1 → run in thêm các dòng @@ sai dạng (JSON hỏng, sai kiểu, minutes là chữ) trước khi
                            chạy job — công cụ phải bỏ qua chúng, không được ngã (và không để worker mồ côi)
    FAKE_WORKER_ORPHAN      =1 → run thoát mà KHÔNG diệt tiến trình con (con kế thừa stdout, ngủ mãi) — công cụ phải
                            tự diệt con mồ côi và kết thúc, không chờ mãi ống stdout
Ghi thêm cho bộ kiểm: remaster_work/fake_calls.jsonl (mỗi lần gọi: argv, cwd, resumed_from, utf8_mode, isolated —
công cụ phải chạy worker với -I -X utf8),
remaster_work/fake_pids.txt (pid worker, pid con).
"""
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile

sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)


def emit(tag, obj):
    print('%s %s' % (tag, json.dumps(obj, ensure_ascii=True)), flush=True)


def parse(argv):
    if not argv:
        raise SystemExit('thieu lenh con')
    sub, rest = argv[0], argv[1:]
    opts = {'flags': set()}
    i = 0
    valued = {'--game', '--blender', '--esrgan', '--scope', '--quality', '--texture', '--out'}
    flags = {'--no-ai', '--resume'}
    while i < len(rest):
        a = rest[i]
        if a in valued:
            opts[a] = rest[i + 1]
            i += 2
        elif a in flags:
            opts['flags'].add(a)
            i += 1
        else:
            print('tham so la: %s' % a, file=sys.stderr)
            raise SystemExit(1)
    if '--game' not in opts:
        print('thieu --game', file=sys.stderr)
        raise SystemExit(1)
    if '--esrgan' in opts and '--no-ai' in opts['flags']:
        print('--esrgan va --no-ai loai tru nhau', file=sys.stderr)
        raise SystemExit(1)
    return sub, opts


def record(work, entry):
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, 'fake_calls.jsonl'), 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def cmd_run(game, opts):
    work = os.path.join(game, 'remaster_work')
    os.makedirs(work, exist_ok=True)
    state_p = os.path.join(work, 'state.json')
    done = []
    if '--resume' in opts['flags'] and os.path.isfile(state_p):
        with open(state_p, encoding='utf-8') as f:
            done = json.load(f).get('done', [])
    record(work, {'sub': 'run', 'argv': sys.argv, 'cwd': os.getcwd(), 'resumed_from': len(done),
                  'utf8_mode': sys.flags.utf8_mode, 'isolated': sys.flags.isolated})
    child = subprocess.Popen([sys.executable, '-I', '-c', 'import time\nwhile True: time.sleep(0.5)'])
    with open(os.path.join(work, 'fake_pids.txt'), 'w', encoding='utf-8') as f:
        f.write('%d\n%d\n' % (os.getpid(), child.pid))
    n = int(os.environ.get('FAKE_WORKER_JOBS', '6'))
    delay = float(os.environ.get('FAKE_WORKER_DELAY', '0.05'))
    fail = os.environ.get('FAKE_WORKER_FAIL_JOB')
    failed = 0
    t0 = time.time()
    print('fake worker: bat dau, %d job, da xong %d' % (n, len(done)), flush=True)
    if os.environ.get('FAKE_WORKER_BAD_LINES') == '1':
        for ln in ('@@P not json', '@@P {"stage": "G", "i": "x", "n": null, "label": [1]}', '@@E [1, 2]',
                   '@@E {"key": 5}', '@@DONE {"ok": "a", "failed": 1e99, "minutes": "abc"}',
                   '@@DONE {"minutes": {"x": 1}}', '@@P', '@@DONE'):
            print(ln, flush=True)
    for i in range(n):
        if i in done:
            continue
        emit('@@P', {'stage': 'G', 'i': i + 1, 'n': n, 'label': 'job%d' % i})
        time.sleep(delay)
        if fail is not None and int(fail) == i:
            failed += 1
            emit('@@E', {'key': '%040x' % i, 'stage': 'G', 'msg': 'loi gia lap'})
        done.append(i)
        tmp = state_p + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'done': done}, f)
        os.replace(tmp, state_p)
    sample = os.environ.get('FAKE_WORKER_SAMPLE')
    if not sample or not os.path.isfile(os.path.join(sample, 'remaster', 'index.tsv')):
        emit('@@E', {'key': '', 'stage': 'C', 'msg': 'thieu FAKE_WORKER_SAMPLE'})
        child.kill()
        return 1
    src = os.path.join(sample, 'remaster')
    dst = os.path.join(game, 'remaster')
    for sub in ('textures', 'models'):
        os.makedirs(os.path.join(dst, sub), exist_ok=True)
        for name in sorted(os.listdir(os.path.join(src, sub))):
            shutil.copyfile(os.path.join(src, sub, name), os.path.join(dst, sub, name))
    shutil.copyfile(os.path.join(src, 'index.tsv'), os.path.join(dst, 'index.tsv.tmp'))
    os.replace(os.path.join(dst, 'index.tsv.tmp'), os.path.join(dst, 'index.tsv'))
    man = {'format': 1, 'tool': 'fake_worker', 'pipeline': 'test', 'quality': opts.get('--quality', 'pc'),
           'models': [], 'failed': []}
    with open(os.path.join(dst, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(man, f)
    if os.environ.get('FAKE_WORKER_ORPHAN') != '1':
        child.kill()
        child.wait()
    else:
        time.sleep(1.0)  # worker thật chạy hàng phút: để công cụ kịp chụp cây tiến trình trước khi worker thoát
    emit('@@DONE', {'ok': n - failed, 'failed': failed, 'skipped': 0, 'minutes': round((time.time() - t0) / 60, 3)})
    return 2 if failed else 0


def cmd_probe(game, opts):
    record(os.path.join(game, 'remaster_work'), {'sub': 'probe', 'argv': sys.argv, 'cwd': os.getcwd()})
    print('python %s' % sys.version.split()[0])
    print('blender %s' % opts.get('--blender'))
    if os.environ.get('FAKE_WORKER_PROBE_FAIL') == '1':
        print('numpy: KHONG CO')
        return 1
    return 0


def cmd_export(game, opts):
    out = opts.get('--out')
    if not out:
        return 1
    rem = os.path.join(game, 'remaster')
    with zipfile.ZipFile(out + '.tmp', 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(rem, 'index.tsv'), 'remaster/index.tsv')
        z.write(os.path.join(rem, 'manifest.json'), 'remaster/manifest.json')
        for sub in ('models', 'textures'):
            for name in sorted(os.listdir(os.path.join(rem, sub))):
                z.write(os.path.join(rem, sub, name), 'remaster/%s/%s' % (sub, name))
        z.writestr('DOC_TRUOC.txt', 'Chi dung cho may cua ban, khong chia se.\n')
        if os.environ.get('FAKE_WORKER_BADZIP') == '1':
            z.writestr('remaster/../evil.txt', 'x')
    os.replace(out + '.tmp', out)
    emit('@@DONE', {'ok': 1, 'failed': 0, 'skipped': 0, 'minutes': 0})
    return 0


def cmd_clean(game, opts):
    work = os.path.join(game, 'remaster_work')
    for name in os.listdir(work) if os.path.isdir(work) else []:
        if name != 'logs':
            p = os.path.join(work, name)
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
    return 0


def main():
    sub, opts = parse(sys.argv[1:])
    game = opts['--game']
    if not os.path.isdir(game):
        print('khong thay thu muc game: %r' % game, file=sys.stderr)
        return 1
    fn = {'run': cmd_run, 'probe': cmd_probe, 'export-android': cmd_export, 'clean': cmd_clean}.get(sub)
    if fn is None:
        print('lenh con la: %s' % sub, file=sys.stderr)
        return 1
    return fn(game, opts)


if __name__ == '__main__':
    sys.exit(main())
