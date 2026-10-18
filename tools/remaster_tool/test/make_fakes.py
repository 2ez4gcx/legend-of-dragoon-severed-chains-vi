"""make_fakes.py — dựng dữ liệu GIẢ cho run_tests.ps1 (không tải gì, không dùng dữ liệu Sony).

Cách gọi:
    python -I tools/remaster_tool/test/make_fakes.py --out DIR --port N --python PYEXE --fake-esrgan CMD --fake-worker PY

Ghi vào DIR:
    srv/blender-5.2.2-windows-x64.zip       Blender giả: <gốc>/blender.cmd (in "Blender 5.2.2 (gia)"),
                                            <gốc>/5.2/python/bin/python.cmd (chuyển tiếp sang PYEXE), filler ngẫu nhiên
                                            (seed cố định) để file đủ lớn cho kiểm tải tiếp
    srv/cut/blender-5.2.2-windows-x64.zip   cùng nội dung (máy chủ cắt kết nối ở đường dẫn này)
    srv/realesrgan-fake.zip                 Real-ESRGAN giả: các file trong danh sách cho phép (exe = fake_esrgan.cmd,
                                            CRLF) + file KHÔNG được giải (input.jpg, README_windows.md, evil.dll, …)
    srv/slip_dotdot.zip, slip_backslash.zip, slip_abs.zip, slip_drive.zip   zip độc (zip-slip)
    pins_ok.json, pins_badsha.json, pins_cut.json, pins_redirect.json, pins_redirect_bad.json, pins_slip_*.json
    game_ascii/, game_hang/, game_manual/, game_new/, game_new2/, game_bad/, "Trò chơi (VN) thử"/   thư mục game giả
        (jdk25\\bin\\java(w).exe rỗng, lod-game-affcef0….jar rỗng, files\\…\\32, files\\SECT\\DRGN21.BIN\\,
         vi\\remaster\\py\\worker.py = fake_worker.py)
    unicode_name.txt                        tên thư mục game Unicode (UTF-8) cho run_tests.ps1
"""
import argparse
import hashlib
import io
import json
import os
import random
import shutil
import zipfile

SC_COMMIT = 'affcef0cba71819515fdf05521c1fedb1d7a92f0'
UNICODE_GAME = 'Tr\u00f2 ch\u01a1i (VN) th\u1eed'
FIXED = (2026, 10, 16, 0, 0, 0)
ESRGAN_WHITELIST = ['realesrgan-ncnn-vulkan.cmd', 'vcomp140.dll', 'models/realesrgan-x4plus-anime.bin',
                    'models/realesrgan-x4plus-anime.param', 'models/realesrgan-x4plus.bin',
                    'models/realesrgan-x4plus.param']


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def zip_bytes(entries):
    """entries: [(tên, bytes | None (thư mục))]; tên giữ nguyên (kể cả '..', '\\')."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in entries:
            zi = zipfile.ZipInfo('x', FIXED)
            zi.filename = name          # đặt thẳng để giữ '\\' và '..' (ZipInfo() sẽ đổi '\\' thành '/')
            zi.orig_filename = name
            zi.compress_type = zipfile.ZIP_DEFLATED
            if data is None:
                zi.external_attr = 0x10
                z.writestr(zi, b'')
            else:
                z.writestr(zi, data)
    return buf.getvalue()


def crlf(b):
    return b.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')


def make_game(path, worker_src):
    for d in ('jdk25/bin', 'files/characters/dart/models/combat', 'files/SECT/DRGN21.BIN', 'vi/remaster/py'):
        os.makedirs(os.path.join(path, d), exist_ok=True)
    for f in ('jdk25/bin/java.exe', 'jdk25/bin/javaw.exe', 'lod-game-%s.jar' % SC_COMMIT,
              'files/characters/dart/models/combat/32'):
        open(os.path.join(path, f), 'wb').close()
    shutil.copyfile(worker_src, os.path.join(path, 'vi', 'remaster', 'py', 'worker.py'))


def tool_pins(base, blender, esrgan):
    return {'format': 1, 'tools': [blender, esrgan]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--port', required=True, type=int)
    ap.add_argument('--python', required=True)
    ap.add_argument('--fake-esrgan', required=True)
    ap.add_argument('--fake-worker', required=True)
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    srv = os.path.join(out, 'srv')
    os.makedirs(os.path.join(srv, 'cut'), exist_ok=True)
    url = 'http://127.0.0.1:%d/' % a.port

    root = 'blender-5.2.2-windows-x64/'
    rnd = random.Random(20261016)
    filler = bytes(rnd.getrandbits(8) for _ in range(300000))
    py_cmd = ('@"%s" %%*\r\n' % a.python).encode('mbcs')
    blender_entries = [
        (root, None),
        (root + 'blender.cmd', b'@echo Blender 5.2.2 (gia)\r\n@echo build hash: fake\r\n'),
        (root + '5.2/', None),
        (root + '5.2/python/bin/python.cmd', py_cmd),
        (root + '5.2/filler.bin', filler),
        (root + 'readme.txt', b'Blender gia cho kiem thu\r\n'),
    ]
    bz = zip_bytes(blender_entries)
    for p in (os.path.join(srv, 'blender-5.2.2-windows-x64.zip'), os.path.join(srv, 'cut', 'blender-5.2.2-windows-x64.zip')):
        with open(p, 'wb') as f:
            f.write(bz)

    with open(a.fake_esrgan, 'rb') as f:
        esr_cmd = crlf(f.read())
    esr_files = {
        'realesrgan-ncnn-vulkan.cmd': esr_cmd,
        'vcomp140.dll': b'fake vcomp140\r\n',
        'models/realesrgan-x4plus-anime.bin': b'fake anime bin' * 100,
        'models/realesrgan-x4plus-anime.param': b'fake anime param\r\n',
        'models/realesrgan-x4plus.bin': b'fake x4plus bin' * 100,
        'models/realesrgan-x4plus.param': b'fake x4plus param\r\n',
    }
    esr_extra = {
        'input.jpg': b'not really a jpg',
        'README_windows.md': b'# fake\r\n',
        'evil.dll': b'MZ fake',
        'models/realesr-animevideov3-x2.bin': b'extra model',
        'vcomp140d.dll': b'debug dll',
    }
    ez = zip_bytes([('models/', None)] + sorted(esr_files.items()) + sorted(esr_extra.items()))
    with open(os.path.join(srv, 'realesrgan-fake.zip'), 'wb') as f:
        f.write(ez)

    slips = {
        'slip_dotdot.zip': root + '../../evil_slip.txt',
        'slip_backslash.zip': root + '..\\..\\evil_slip_bs.txt',
        'slip_abs.zip': '/evil_slip_abs.txt',
        'slip_drive.zip': 'C:/evil_slip_drive.txt',
    }
    for name, bad in slips.items():
        z = zip_bytes(blender_entries + [(bad, b'evil')])
        with open(os.path.join(srv, name), 'wb') as f:
            f.write(z)

    blender = {
        'id': 'blender', 'name': 'Blender', 'version': '5.2.2', 'url': url + 'blender-5.2.2-windows-x64.zip',
        'file': 'blender-5.2.2-windows-x64.zip', 'size': len(bz), 'sha256': sha256(bz),
        'root': 'blender-5.2.2-windows-x64', 'dir': 'blender-5.2.2-windows-x64', 'extract': None, 'file_sha256': {},
        'exe': 'blender.cmd', 'python': '5.2/python/bin/python.cmd', 'verify': ['-b', '--factory-startup', '--version'],
        'expect': 'Blender 5.2.2', 'installed_size': 400000, 'required': True, 'license': 'GPL-3.0-or-later',
        'home': 'https://www.blender.org/download/', 'host_label': '127.0.0.1'}
    esrgan = {
        'id': 'realesrgan', 'name': 'Real-ESRGAN', 'version': 'gia', 'url': url + 'realesrgan-fake.zip',
        'file': 'realesrgan-ncnn-vulkan-20220424-windows.zip', 'size': len(ez), 'sha256': sha256(ez), 'root': '',
        'dir': 'realesrgan', 'extract': ESRGAN_WHITELIST,
        'file_sha256': {k: sha256(v) for k, v in esr_files.items()},
        'exe': 'realesrgan-ncnn-vulkan.cmd', 'selftest_model': 'realesrgan-x4plus-anime', 'installed_size': 10000,
        'required': False, 'license': 'BSD-3-Clause', 'home': 'https://github.com/xinntao/Real-ESRGAN',
        'host_label': '127.0.0.1'}

    def write_pins(name, b, e):
        with open(os.path.join(out, name), 'w', encoding='utf-8') as f:
            json.dump(tool_pins(out, b, e), f, ensure_ascii=False, indent=1)

    write_pins('pins_ok.json', blender, esrgan)
    write_pins('pins_badsha.json', dict(blender, sha256='0' * 64), esrgan)
    write_pins('pins_cut.json', dict(blender, url=url + 'cut/blender-5.2.2-windows-x64.zip'), esrgan)
    write_pins('pins_redirect.json', dict(blender, url=url + 'redirect/blender-5.2.2-windows-x64.zip'), esrgan)
    write_pins('pins_redirect_bad.json', dict(blender, url=url + 'redirect-bad/blender-5.2.2-windows-x64.zip'), esrgan)
    for name in slips:
        with open(os.path.join(srv, name), 'rb') as f:
            zb = f.read()
        write_pins('pins_' + name[:-4] + '.json', dict(blender, url=url + name, size=len(zb), sha256=sha256(zb)), esrgan)

    for g in ('game_ascii', 'game_hang', 'game_manual', 'game_new', 'game_new2', 'game_bad', 'game_redirect',
              UNICODE_GAME):
        make_game(os.path.join(out, g), a.fake_worker)
    with open(os.path.join(out, 'unicode_name.txt'), 'w', encoding='utf-8') as f:
        f.write(UNICODE_GAME)
    print('da dung du lieu gia trong %s' % out)


if __name__ == '__main__':
    main()
