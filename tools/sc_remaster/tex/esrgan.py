"""esrgan.py — chạy Real-ESRGAN ncnn-vulkan an toàn cho đường texture HD (gói P3 của mô hình HD route B).

Real-ESRGAN ncnn (realesrgan-ncnn-vulkan.exe 20220424) hỏng với đường dẫn không phải ASCII (thoát 0xC0000409) và có thể
treo trên laptop hai GPU. Module này:
  1. Chọn thư mục staging CHỈ ASCII và ghi được (tự kiểm bằng file thử), theo thứ tự:
       --esrgan <thư mục> nếu có (công cụ PC đã chọn và tự kiểm, SPEC §3.9);
       thư mục công cụ (vd. <game>/remaster_tools/realesrgan) nếu đường dẫn ASCII;
       %PUBLIC%/LoD-SC-VN/realesrgan;
       <ổ đĩa của thư mục công cụ>:/LoD-SC-VN-tools/realesrgan.
     Thư mục staging khác thư mục công cụ thì chép exe, các .dll cạnh exe và đúng hai file models/<mô hình>.param/.bin
     (chỉ chép khi khác kích thước / SHA-1).
  2. Tự kiểm trên ảnh PNG 64x64 sinh ra (ra đúng 256x256, thu nhỏ trung bình khối 4x gần ảnh vào), ghi lại GPU Vulkan
     mà exe in ra.
  3. Chạy 'realesrgan-ncnn-vulkan.exe -i in/<x>.png -o out/<x>.png -n <mô hình> -s 4 -f png' với cwd = staging và đường
     dẫn TƯƠNG ĐỐI; stdout/stderr ghi vào staging/log (không dùng pipe để tiến trình con treo không làm treo bộ đọc;
     log chỉ giữ lại khi lần chạy hỏng).
     Quá thời gian (mặc định 600 s) -> diệt CẢ CÂY tiến trình (Windows: Job Object KILL_ON_JOB_CLOSE + taskkill /T /F;
     POSIX: killpg). Thử lại một lần với '-t 64'. Vẫn hỏng -> trả None để hd_atlas.py dùng scale4x.py.

Cách gọi (từ gốc repo, PYTHONIOENCODING=utf-8):
  python tools/sc_remaster/tex/esrgan.py probe [--esrgan DIR] [--tool DIR] [--model M] [--timeout 120]
      chọn staging + tự kiểm; in JSON (staging, gpus, giây); exit 0 = dùng được.
  python tools/sc_remaster/tex/esrgan.py run <vào.png> <ra.png> [--esrgan DIR] [--tool DIR] [--model M] [--timeout 600]
      phóng 4x một ảnh RGB (thử lại -t 64; không tự dự phòng), exit 0/1.
  python tools/sc_remaster/tex/esrgan.py selftest
      tự kiểm không cần Real-ESRGAN: nhận dạng ASCII, thứ tự staging (biến môi trường giả), diệt cây tiến trình python.
  python tools/sc_remaster/tex/esrgan.py test-fake [--work DIR]
      biên dịch exe giả (csc.exe của .NET Framework; không có thì dùng .cmd) cùng tên realesrgan-ncnn-vulkan.exe, chạy
      các kịch bản: treo cả tự kiểm, treo khi chạy thật cả hai lần (-t 64 cũng treo), treo khi không chia ô (thử lại
      -t 64 thì xong); kiểm mọi PID của cây tiến trình đã chết. Mặc định DIR = work/upscale/sc_remaster_p3/fake_esrgan.
Mặc định thư mục công cụ: deps/upscale/realesrgan (máy phát triển). Exit 0 = đạt, 1 = lỗi. Không dùng PIL.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import islands as isl  # noqa: E402

ROOT = isl.ROOT
WIN = os.name == 'nt'
EXE_NAME = 'realesrgan-ncnn-vulkan.exe' if WIN else 'realesrgan-ncnn-vulkan'
DEFAULT_MODEL = 'realesrgan-x4plus-anime'
DEFAULT_TOOL = os.path.join(ROOT, 'deps', 'upscale', 'realesrgan')
TIMEOUT = 600
SELFTEST_TIMEOUT = 120


class EsrganError(Exception):
    pass


def is_ascii_path(p):
    try:
        os.path.abspath(p).encode('ascii')
        return True
    except UnicodeEncodeError:
        return False


def writable_dir(d):
    """Tạo thư mục nếu cần và thử ghi / xoá một file; -> True nếu ghi được."""
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, '.lodsc_write_test_%d' % os.getpid())
        with open(probe, 'wb') as f:
            f.write(b'ok')
        os.remove(probe)
        return True
    except OSError:
        return False


def find_exe(d):
    """exe trong thư mục d: realesrgan-ncnn-vulkan(.exe), hoặc .cmd / .bat cùng tên (chỉ để thử)."""
    for name in (EXE_NAME, 'realesrgan-ncnn-vulkan.cmd', 'realesrgan-ncnn-vulkan.bat'):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return None


def has_tool(d, model):
    return (d is not None and find_exe(d) is not None
            and os.path.isfile(os.path.join(d, 'models', model + '.param'))
            and os.path.isfile(os.path.join(d, 'models', model + '.bin')))


def _sha1_file(p):
    h = hashlib.sha1()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def _copy_if_diff(src, dst):
    if os.path.isfile(dst) and os.path.getsize(dst) == os.path.getsize(src) and _sha1_file(dst) == _sha1_file(src):
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst + '.tmp')
    os.replace(dst + '.tmp', dst)
    return True


def tool_files(tool_dir, model):
    """Các file cần chép sang staging: exe (hoặc .cmd giả), mọi .dll cạnh exe, models/<model>.param/.bin."""
    exe = find_exe(tool_dir)
    files = [os.path.basename(exe)]
    for f in sorted(os.listdir(tool_dir)):
        if f.lower().endswith('.dll') and os.path.isfile(os.path.join(tool_dir, f)):
            files.append(f)
    files += ['models/%s.param' % model, 'models/%s.bin' % model]
    # exe giả để thử (test-fake) có thể kèm file .cs / .py cạnh nó
    for f in sorted(os.listdir(tool_dir)):
        if f.startswith('fake_') and os.path.isfile(os.path.join(tool_dir, f)):
            files.append(f)
    return files


def staging_candidates(esrgan=None, tool_dir=None, env=None):
    """Danh sách thư mục staging theo thứ tự ưu tiên (chưa kiểm ASCII / ghi được)."""
    env = os.environ if env is None else env
    if esrgan:
        return [os.path.abspath(esrgan)]
    out = []
    if tool_dir:
        out.append(os.path.abspath(tool_dir))
    pub = env.get('PUBLIC')
    if pub:
        out.append(os.path.join(pub, 'LoD-SC-VN', 'realesrgan'))
    drive = os.path.splitdrive(os.path.abspath(tool_dir or ROOT))[0]
    if drive:
        out.append(drive + os.sep + os.path.join('LoD-SC-VN-tools', 'realesrgan'))
    return out


class Staging:
    def __init__(self, d, source, copied, notes):
        self.dir = d
        self.exe = find_exe(d)
        self.source = source
        self.copied = copied
        self.notes = notes

    def info(self):
        return dict(dir=self.dir, exe=os.path.basename(self.exe or ''), source=self.source, copied=self.copied,
                    notes=self.notes)


def prepare_staging(esrgan=None, tool_dir=None, model=DEFAULT_MODEL, env=None):
    """Chọn staging ASCII ghi được và bảo đảm có exe + mô hình ở đó. -> Staging; lỗi -> EsrganError."""
    tool_dir = os.path.abspath(tool_dir) if tool_dir else None
    notes = []
    if esrgan:
        d = os.path.abspath(esrgan)
        if not is_ascii_path(d):
            raise EsrganError('--esrgan khong phai duong dan ASCII: %s' % d)
        if not writable_dir(d):
            raise EsrganError('--esrgan khong ghi duoc: %s' % d)
        if has_tool(d, model):
            return Staging(d, d, [], ['--esrgan'])
        if tool_dir and has_tool(tool_dir, model):
            copied = [f for f in tool_files(tool_dir, model)
                      if _copy_if_diff(os.path.join(tool_dir, *f.split('/')), os.path.join(d, *f.split('/')))]
            return Staging(d, tool_dir, copied, ['--esrgan (chep tu %s)' % tool_dir])
        raise EsrganError('--esrgan %s khong co %s + models/%s' % (d, EXE_NAME, model))
    if not (tool_dir and has_tool(tool_dir, model)):
        raise EsrganError('khong thay Real-ESRGAN (%s + models/%s) o %s' % (EXE_NAME, model, tool_dir))
    for d in staging_candidates(None, tool_dir, env):
        if not is_ascii_path(d):
            notes.append('bo qua (khong ASCII): %s' % d)
            continue
        if not writable_dir(d):
            notes.append('bo qua (khong ghi duoc): %s' % d)
            continue
        if os.path.normcase(d) == os.path.normcase(tool_dir):
            return Staging(d, tool_dir, [], notes + ['thu muc cong cu'])
        copied = [f for f in tool_files(tool_dir, model)
                  if _copy_if_diff(os.path.join(tool_dir, *f.split('/')), os.path.join(d, *f.split('/')))]
        return Staging(d, tool_dir, copied, notes + ['staging chep tu thu muc cong cu'])
    raise EsrganError('khong co thu muc staging ASCII ghi duoc: %s' % '; '.join(notes))


# ---------------------------------------------------------------- tiến trình: Job Object + diệt cây
class _Job:
    """Windows Job Object KILL_ON_JOB_CLOSE: đóng / Terminate giết mọi tiến trình con cháu đã vào job."""

    def __init__(self):
        self.h = None
        if not WIN:
            return
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL('kernel32', use_last_error=True)

            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [(n, ctypes.c_ulonglong) for n in ('r', 'w', 'o', 'rb', 'wb', 'ob')]

            class BASIC(ctypes.Structure):
                _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong),
                            ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                            ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                            ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD),
                            ('SchedulingClass', wintypes.DWORD)]

            class EXT(ctypes.Structure):
                _fields_ = [('Basic', BASIC), ('Io', IO_COUNTERS), ('ProcessMemoryLimit', ctypes.c_size_t),
                            ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t),
                            ('PeakJobMemoryUsed', ctypes.c_size_t)]

            k32.CreateJobObjectW.restype = wintypes.HANDLE
            k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
            k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            h = k32.CreateJobObjectW(None, None)
            if not h:
                return
            info = EXT()
            info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not k32.SetInformationJobObject(h, 9, ctypes.byref(info), ctypes.sizeof(info)):
                k32.CloseHandle(h)
                return
            self.k32 = k32
            self.h = h
        except Exception:
            self.h = None

    def assign(self, proc):
        if self.h is None:
            return False
        try:
            return bool(self.k32.AssignProcessToJobObject(self.h, int(proc._handle)))
        except Exception:
            return False

    def terminate(self):
        if self.h is not None:
            try:
                self.k32.TerminateJobObject(self.h, 1)
            except Exception:
                pass

    def close(self):
        if self.h is not None:
            try:
                self.k32.CloseHandle(self.h)
            except Exception:
                pass
            self.h = None


def kill_tree(proc, job=None):
    """Diệt tiến trình và mọi con cháu: taskkill /T /F khi tiến trình gốc CÒN sống (dò cây theo PID cha, bắt cả con sinh
    ra trước lúc gán vào job), rồi Job Object (con cháu đã vào job, kể cả con mồ côi); POSIX: killpg. PID không bị dùng
    lại giữa chừng vì proc còn giữ handle."""
    if WIN:
        try:
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=60, creationflags=0x08000000)
        except Exception:
            pass
    if job is not None:
        job.terminate()
    if not WIN:
        try:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=30)
    except Exception:
        pass


def pid_alive(pid, name=None):
    """Tiến trình pid còn chạy? name (vd. 'realesrgan-ncnn-vulkan.exe'): chỉ tính khi tên exe trùng — Windows dùng lại
    PID rất nhanh nên PID của tiến trình đã chết có thể thuộc một tiến trình mới khác."""
    if WIN:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL('kernel32')
        k32.OpenProcess.restype = ctypes.c_void_p
        h = k32.OpenProcess(0x00100000 | 0x1000, False, int(pid))  # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            if k32.WaitForSingleObject(ctypes.c_void_p(h), 0) != 0x102:  # WAIT_TIMEOUT -> còn chạy
                return False
            if name is None:
                return True
            buf = ctypes.create_unicode_buffer(32768)
            n = wintypes.DWORD(len(buf))
            if not k32.QueryFullProcessImageNameW(ctypes.c_void_p(h), 0, buf, ctypes.byref(n)):
                return True
            return os.path.basename(buf.value).lower() == name.lower()
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def run_process(args, cwd, timeout, log_path, env=None):
    """Chạy args (cwd, stdout+stderr -> log_path), chờ tối đa timeout giây; quá giờ -> diệt cả cây.
    -> dict(rc, timeout, seconds, log)."""
    exe = args[0]
    if exe.lower().endswith(('.cmd', '.bat')):
        args = ['cmd.exe', '/d', '/c'] + list(args)
    t0 = time.time()
    kw = {}
    if WIN:
        kw['creationflags'] = 0x00000200 | 0x08000000  # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    else:
        kw['start_new_session'] = True
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    job = _Job()
    timed_out = False
    with open(log_path, 'wb') as logf:
        p = subprocess.Popen(args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT, env=env,
                             **kw)
        job.assign(p)
        try:
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_tree(p, job)
            rc = p.returncode
        finally:
            job.close()
    try:
        with open(log_path, 'rb') as f:
            log = f.read().decode('utf-8', 'replace')
    except OSError:
        log = ''
    return dict(rc=rc, timeout=timed_out, seconds=round(time.time() - t0, 2), log=log[-1500:])


def _rc_text(rc):
    if rc is None:
        return 'None'
    return '0x%08X' % (rc & 0xFFFFFFFF) if rc < 0 or rc > 255 else str(rc)


def run_once(st, rgb, model=DEFAULT_MODEL, timeout=TIMEOUT, tile=None, tag='w'):
    """Một lần chạy exe trên ảnh RGB uint8 -> (ảnh 4x hoặc None, bản ghi lần thử)."""
    job = 'lodsc_%d_%s' % (os.getpid(), tag)
    rin = 'in/%s.png' % job
    rout = 'out/%s.png' % job
    pin = os.path.join(st.dir, 'in', job + '.png')
    pout = os.path.join(st.dir, 'out', job + '.png')
    os.makedirs(os.path.dirname(pin), exist_ok=True)
    os.makedirs(os.path.dirname(pout), exist_ok=True)
    if os.path.exists(pout):
        os.remove(pout)
    isl.png_write_file(pin, np.ascontiguousarray(rgb[..., :3], np.uint8))
    args = [st.exe, '-i', rin, '-o', rout, '-n', model, '-s', '4', '-f', 'png']
    if tile:
        args += ['-t', str(tile)]
    r = run_process(args, st.dir, timeout, os.path.join(st.dir, 'log', job + '.log'))
    rec = dict(tile=tile, rc=_rc_text(r['rc']), timeout=r['timeout'], seconds=r['seconds'])
    out = None
    try:
        if r['timeout']:
            rec['reason'] = 'qua %d s, da diet cay tien trinh' % timeout
        elif r['rc'] != 0:
            rec['reason'] = 'exe thoat %s' % rec['rc']
        elif not os.path.isfile(pout):
            rec['reason'] = 'khong co file ra'
        else:
            img = isl.png_read_file(pout)
            h, w = rgb.shape[:2]
            if img.shape[:2] != (h * 4, w * 4):
                rec['reason'] = 'kich thuoc ra %dx%d != %dx%d' % (img.shape[1], img.shape[0], w * 4, h * 4)
            else:
                out = np.ascontiguousarray(img[..., :3])
    except Exception as e:  # PNG hỏng
        rec['reason'] = 'doc PNG ra loi: %s' % e
    if out is None:
        rec['log_tail'] = r['log'][-600:]
    gpus = [ln.strip() for ln in r['log'].splitlines() if ln.startswith('[') and 'queueC' in ln]
    if gpus:
        rec['gpus'] = gpus
    # dọn file vào / ra; log chỉ giữ khi hỏng (để chẩn đoán), thành công thì xoá để staging không phình
    for p in (pin, pout) + ((os.path.join(st.dir, 'log', job + '.log'),) if out is not None else ()):
        try:
            os.remove(p)
        except OSError:
            pass
    return out, rec


def upscale(st, rgb, model=DEFAULT_MODEL, timeout=TIMEOUT, tag='w', log=None):
    """Phóng 4x: lần 1 mặc định, lần 2 '-t 64'. -> (ảnh 4x hoặc None, [bản ghi])."""
    attempts = []
    for tile in (None, 64):
        out, rec = run_once(st, rgb, model, timeout, tile, tag)
        attempts.append(rec)
        if log:
            log('esrgan %s: %s' % ('-t %d' % tile if tile else 'mac dinh',
                                   'xong %.1f s' % rec['seconds'] if out is not None else rec.get('reason')))
        if out is not None:
            return out, attempts
    return None, attempts


def selftest_image():
    """Ảnh thử 64x64: dải màu + ô bàn cờ 8 px + hình tròn (tạo bằng numpy, xác định)."""
    y, x = np.mgrid[0:64, 0:64]
    img = np.zeros((64, 64, 3), np.uint8)
    img[..., 0] = (x * 4).astype(np.uint8)
    img[..., 1] = (y * 4).astype(np.uint8)
    img[..., 2] = np.where(((x // 8) + (y // 8)) % 2 == 0, 200, 40)
    circ = (x - 40) ** 2 + (y - 24) ** 2 < 100
    img[circ] = [250, 250, 250]
    return img


def psnr_down4(big, small):
    b = big.astype(np.float64)
    h, w = small.shape[:2]
    d = b.reshape(h, 4, w, 4, -1).mean((1, 3))
    mse = ((d - small.astype(np.float64)) ** 2).mean()
    return 99.0 if mse <= 0 else 10 * np.log10(255.0 * 255.0 / mse)


def selftest_tool(st, model=DEFAULT_MODEL, timeout=SELFTEST_TIMEOUT):
    """Tự kiểm exe trên ảnh 64x64. -> (đạt?, dict)."""
    src = selftest_image()
    out, rec = run_once(st, src, model, timeout, None, 'selftest')
    info = dict(attempt=rec)
    if out is None:
        info['reason'] = rec.get('reason', '?')
        return False, info
    p = psnr_down4(out, src)
    info['psnr_down4'] = round(float(p), 2)
    if p < 18.0:
        info['reason'] = 'anh ra khong giong anh vao (PSNR %.1f dB)' % p
        return False, info
    return True, info


# ---------------------------------------------------------------- tự kiểm logic (không cần Real-ESRGAN)
def selftest(work=None):
    errs = []
    work = work or os.path.join(ROOT, 'work', 'upscale', 'sc_remaster_p3', 'esrgan_selftest')
    os.makedirs(work, exist_ok=True)
    if not is_ascii_path('C:/a b/c') or is_ascii_path('C:/Trò chơi (VN) thử'):
        errs.append('nhan dang ASCII sai')
    # thứ tự staging: thư mục công cụ Unicode bị bỏ, PUBLIC giả được chọn và nhận bản chép
    uni_tool = os.path.join(work, 'Trò chơi (VN) thử', 'remaster_tools', 'realesrgan')
    os.makedirs(os.path.join(uni_tool, 'models'), exist_ok=True)
    for f in (EXE_NAME, 'vcomp140.dll', 'models/%s.param' % DEFAULT_MODEL, 'models/%s.bin' % DEFAULT_MODEL):
        with open(os.path.join(uni_tool, *f.split('/')), 'wb') as fo:
            fo.write(b'gia ' + f.encode())
    pub = os.path.join(work, 'public')
    shutil.rmtree(os.path.join(pub, 'LoD-SC-VN'), ignore_errors=True)
    env = dict(os.environ, PUBLIC=pub)
    cands = staging_candidates(None, uni_tool, env)
    if cands[0] != os.path.abspath(uni_tool) or cands[1] != os.path.join(pub, 'LoD-SC-VN', 'realesrgan'):
        errs.append('thu tu staging sai: %s' % cands)
    st = prepare_staging(None, uni_tool, DEFAULT_MODEL, env)
    if os.path.normcase(st.dir) != os.path.normcase(os.path.join(pub, 'LoD-SC-VN', 'realesrgan')):
        errs.append('staging khong phai PUBLIC gia: %s' % st.dir)
    if sorted(st.copied) != sorted([EXE_NAME, 'vcomp140.dll', 'models/%s.param' % DEFAULT_MODEL,
                                    'models/%s.bin' % DEFAULT_MODEL]):
        errs.append('file chep sang staging sai: %s' % st.copied)
    st2 = prepare_staging(None, uni_tool, DEFAULT_MODEL, env)
    if st2.copied:
        errs.append('chep lai du file da giong: %s' % st2.copied)
    try:
        prepare_staging(os.path.join(work, 'Trò'), uni_tool, DEFAULT_MODEL, env)
        errs.append('--esrgan khong ASCII phai bi tu choi')
    except EsrganError:
        pass
    ascii_tool = os.path.join(work, 'tool_ascii')
    shutil.copytree(uni_tool, ascii_tool, dirs_exist_ok=True)
    st3 = prepare_staging(None, ascii_tool, DEFAULT_MODEL, env)
    if os.path.normcase(st3.dir) != os.path.normcase(os.path.abspath(ascii_tool)) or st3.copied:
        errs.append('thu muc cong cu ASCII phai duoc dung tai cho')
    # diệt cây: python cha sinh python con, cả hai ngủ; hết giờ -> cả hai chết
    pidf = os.path.join(work, 'tree_pids.txt')
    if os.path.exists(pidf):
        os.remove(pidf)
    code = ('import subprocess,sys,time,os;'
            'c=subprocess.Popen([sys.executable,"-c","import time;time.sleep(600)"]);'
            'open(sys.argv[1],"w").write("%d %d" % (os.getpid(), c.pid));time.sleep(600)')
    r = run_process([sys.executable, '-c', code, pidf], work, 3, os.path.join(work, 'tree.log'))
    if not r['timeout']:
        errs.append('tien trinh treo khong bi tinh la qua gio')
    try:
        pids = [int(v) for v in open(pidf).read().split()]
    except (OSError, ValueError):
        pids = []
    time.sleep(0.5)
    if len(pids) != 2 or any(pid_alive(p, os.path.basename(sys.executable)) for p in pids):
        errs.append('cay tien trinh chua chet: %s' % pids)
    r = run_process([sys.executable, '-c', 'import sys; sys.exit(3)'], work, 30, os.path.join(work, 'rc.log'))
    if r['rc'] != 3 or r['timeout']:
        errs.append('ma thoat sai %s' % r)
    if 'PIL' in sys.modules:
        errs.append('PIL da bi import')
    for e in errs:
        print('LOI:', e)
    print('esrgan selftest: %s (%d loi)' % ('DAT' if not errs else 'KHONG DAT', len(errs)))
    return not errs


# ---------------------------------------------------------------- exe giả treo
FAKE_CS = r'''
using System; using System.IO; using System.Diagnostics; using System.Threading;
using System.Drawing; using System.Drawing.Drawing2D; using System.Drawing.Imaging;
class FakeEsrgan {
  static int Main(string[] a) {
    if (a.Length > 0 && a[0] == "child") { Thread.Sleep(Timeout.Infinite); return 0; }
    string mode = Environment.GetEnvironmentVariable("FAKE_ESRGAN_MODE") ?? "copy";
    string pids = Environment.GetEnvironmentVariable("FAKE_ESRGAN_PIDS");
    string inp = null, outp = null; bool tiled = false;
    for (int i = 0; i < a.Length - 1; i++) { if (a[i] == "-i") inp = a[i+1]; if (a[i] == "-o") outp = a[i+1]; if (a[i] == "-t") tiled = true; }
    bool self = inp != null && Path.GetFileName(inp).Contains("selftest");
    bool hang = mode == "hang" || (mode == "hang_big" && !self) || (mode == "hang_untiled" && !tiled && !self);
    if (hang) {
      var psi = new ProcessStartInfo(Process.GetCurrentProcess().MainModule.FileName, "child");
      psi.UseShellExecute = false; psi.CreateNoWindow = true;
      var c = Process.Start(psi);
      if (pids != null) File.AppendAllText(pids, Process.GetCurrentProcess().Id + " " + c.Id + "\n");
      Thread.Sleep(Timeout.Infinite);
    }
    using (var src = new Bitmap(inp))
    using (var dst = new Bitmap(src.Width * 4, src.Height * 4, PixelFormat.Format24bppRgb)) {
      using (var g = Graphics.FromImage(dst)) {
        g.InterpolationMode = InterpolationMode.NearestNeighbor; g.PixelOffsetMode = PixelOffsetMode.Half;
        g.DrawImage(src, 0, 0, dst.Width, dst.Height);
      }
      dst.Save(outp, ImageFormat.Png);
    }
    Console.Error.WriteLine("[0 Fake GPU]  queueC=0[1]  queueG=0[1]  queueT=0[1]");
    return 0;
  }
}
'''

FAKE_PY = r'''
import os, subprocess, sys, time, zlib, struct
a = sys.argv[1:]
if a[:1] == ['child']:
    time.sleep(100000)
mode = os.environ.get('FAKE_ESRGAN_MODE', 'copy')
pids = os.environ.get('FAKE_ESRGAN_PIDS')
inp = a[a.index('-i') + 1]
tiled = '-t' in a
self_ = 'selftest' in os.path.basename(inp)
if mode == 'hang' or (mode == 'hang_big' and not self_) or (mode == 'hang_untiled' and not tiled and not self_):
    c = subprocess.Popen([sys.executable, os.path.abspath(__file__), 'child'])
    if pids:
        open(pids, 'a').write('%d %d\n' % (os.getpid(), c.pid))
    time.sleep(100000)
sys.exit(5)
'''


def build_fake(d):
    """exe giả: biên dịch C# bằng csc.exe (.NET Framework 4) nếu có; không thì .cmd gọi python. -> đường dẫn exe."""
    os.makedirs(os.path.join(d, 'models'), exist_ok=True)
    for m in (DEFAULT_MODEL,):
        for ext in ('.param', '.bin'):
            with open(os.path.join(d, 'models', m + ext), 'wb') as f:
                f.write(b'gia')
    exe = os.path.join(d, EXE_NAME)
    csc = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Microsoft.NET', 'Framework64', 'v4.0.30319', 'csc.exe')
    if WIN and os.path.isfile(csc):
        src = os.path.join(d, 'fake_esrgan.cs')
        with open(src, 'w', encoding='utf-8') as f:
            f.write(FAKE_CS)
        r = subprocess.run([csc, '/nologo', '/optimize', '/out:' + exe, '/r:System.Drawing.dll', src],
                           capture_output=True, text=True)
        if r.returncode == 0 and os.path.isfile(exe):
            return exe
        print('csc loi:', r.stdout[-500:], r.stderr[-500:])
    py = os.path.join(d, 'fake_esrgan.py')
    with open(py, 'w', encoding='utf-8') as f:
        f.write(FAKE_PY)
    cmd = os.path.join(d, 'realesrgan-ncnn-vulkan.cmd')
    with open(cmd, 'w', encoding='ascii') as f:
        f.write('@"%s" "%%~dp0fake_esrgan.py" %%*\r\n' % sys.executable)
    return cmd


def test_fake(work=None, timeout=4):
    """Kịch bản exe giả treo. -> True nếu đạt."""
    work = os.path.abspath(work or os.path.join(ROOT, 'work', 'upscale', 'sc_remaster_p3', 'fake_esrgan'))
    d = os.path.join(work, 'tool')
    exe = build_fake(d)
    print('exe gia:', isl.rel(exe))
    errs = []
    img = selftest_image()[:32, :40]
    pidf = os.path.join(work, 'pids.txt')
    old = {k: os.environ.get(k) for k in ('FAKE_ESRGAN_MODE', 'FAKE_ESRGAN_PIDS')}
    try:
        os.environ['FAKE_ESRGAN_PIDS'] = pidf
        st = prepare_staging(None, d, DEFAULT_MODEL)
        scen = []
        for mode in ('hang', 'hang_big', 'hang_untiled', 'copy'):
            if os.path.exists(pidf):
                os.remove(pidf)
            os.environ['FAKE_ESRGAN_MODE'] = mode
            t0 = time.time()
            ok, info = selftest_tool(st, DEFAULT_MODEL, timeout)
            out = attempts = None
            if ok:
                out, attempts = upscale(st, img, DEFAULT_MODEL, timeout)
            time.sleep(0.5)
            pids = []
            if os.path.exists(pidf):
                pids = [int(v) for v in open(pidf).read().split()]
            alive = [p for p in pids if pid_alive(p, os.path.basename(exe))]
            res = dict(mode=mode, selftest=ok, upscaled=out is not None, attempts=[a.get('reason', 'ok') for a in
                                                                                 (attempts or [])],
                       tiles=[a['tile'] for a in (attempts or [])], killed_pids=pids, alive=alive,
                       seconds=round(time.time() - t0, 1))
            scen.append(res)
            print(json.dumps(res, ensure_ascii=False))
            if alive:
                errs.append('%s: PID con song %s' % (mode, alive))
            if mode == 'hang' and (ok or len(pids) != 2):
                errs.append('hang: tu kiem phai that bai va diet 2 tien trinh')
            if mode == 'hang_big' and (not ok or out is not None or res['tiles'] != [None, 64] or len(pids) != 4):
                errs.append('hang_big: phai thu 2 lan (-t 64) roi bo cuoc, diet 4 tien trinh')
            if mode == 'hang_untiled' and (not ok or out is None or res['tiles'] != [None, 64] or len(pids) != 2):
                errs.append('hang_untiled: lan 2 (-t 64) phai xong')
            if mode == 'copy' and (not ok or out is None or res['tiles'] != [None]):
                errs.append('copy: phai xong ngay lan 1')
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    for e in errs:
        print('LOI:', e)
    print('esrgan test-fake: %s' % ('DAT' if not errs else 'KHONG DAT'))
    return not errs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('probe', 'run'):
        p = sub.add_parser(name)
        if name == 'run':
            p.add_argument('src')
            p.add_argument('dst')
        p.add_argument('--esrgan')
        p.add_argument('--tool', default=DEFAULT_TOOL)
        p.add_argument('--model', default=DEFAULT_MODEL)
        p.add_argument('--timeout', type=float, default=SELFTEST_TIMEOUT if name == 'probe' else TIMEOUT)
    sub.add_parser('selftest')
    p = sub.add_parser('test-fake')
    p.add_argument('--work')
    p.add_argument('--timeout', type=float, default=4)
    a = ap.parse_args(argv)
    if a.cmd == 'selftest':
        return 0 if selftest() else 1
    if a.cmd == 'test-fake':
        return 0 if test_fake(a.work, a.timeout) else 1
    try:
        st = prepare_staging(a.esrgan, a.tool, a.model)
    except EsrganError as e:
        print(json.dumps(dict(ok=False, reason=str(e)), ensure_ascii=False))
        return 1
    if a.cmd == 'probe':
        t0 = time.time()
        ok, info = selftest_tool(st, a.model, a.timeout)
        print(json.dumps(dict(ok=ok, staging=st.info(), selftest=info, seconds=round(time.time() - t0, 2)),
                         ensure_ascii=False, indent=1))
        return 0 if ok else 1
    src = isl.png_read_file(a.src)[..., :3]
    out, attempts = upscale(st, src, a.model, a.timeout, log=print)
    print(json.dumps(dict(staging=st.info(), attempts=attempts), ensure_ascii=False, indent=1))
    if out is None:
        return 1
    isl.png_write_file(a.dst, out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
