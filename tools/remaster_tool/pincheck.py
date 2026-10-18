"""pincheck.py — (người bảo trì) đối chiếu tools/remaster_tool/pins.json với nguồn chính thức, KHÔNG tải file zip lớn.

Cách gọi:
    python tools/remaster_tool/pincheck.py [--pins tools/remaster_tool/pins.json] [--head] [--offline] [--zip FILE ...]
    python tools/remaster_tool/pincheck.py --selftest      (tự kiểm offline bằng zip + pins tổng hợp; run_tests.ps1 gọi)

Kiểm:
  Tĩnh (luôn chạy): format 1; URL https, máy chủ trong danh sách cho phép (giống Downloader.ALLOWED_HOSTS của công cụ);
      sha256 / file_sha256 là 64 hex thường; khoá file_sha256 nằm trong extract; Real-ESRGAN có extract chứa exe.
  Blender: tải file nhỏ chính thức sha256_source (ví dụ .../Blender5.2/blender-5.2.2.sha256), tìm dòng của tên file zip
      → SHA-256 phải bằng pins.sha256; url phải cùng thư mục với file .sha256.
      --head: thêm một yêu cầu HEAD tới url (không tải thân file) → Content-Length phải bằng pins.size
      (kích thước Blender mặc định chỉ được đối chiếu khi có --head).
  Real-ESRGAN: GitHub API (github_api, JSON metadata của release) → asset có name = tên file trong url: size bằng
      pins.size, browser_download_url bằng pins.url; GitHub có trường digest ("sha256:…") thì phải bằng pins.sha256
      (với v0.2.5.0 digest là null: pin là SHA-256 tự tính trên bản có đúng kích thước — in cảnh báo).
  --offline: chỉ kiểm tĩnh (không mạng).
  --zip FILE (lặp được, không cần mạng): đối chiếu một zip đã có trên máy (ví dụ bản người bảo trì đã tải) với công cụ
      có "file" trùng tên: kích thước + SHA-256 của zip; mọi mục an toàn như Installer của công cụ (không "..", "\\",
      đường dẫn tuyệt đối, ổ đĩa; nằm dưới "root"); đủ mục "extract" và đúng "file_sha256"; tổng dung lượng các file sẽ
      giải nén = "installed_size" (công cụ dùng làm ước tính và giới hạn chống zip bom).
Exit 0 = đạt, 1 = lệch hoặc lỗi mạng. Chỉ thư viện chuẩn.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
ALLOWED_HOSTS = {'download.blender.org', 'github.com', 'objects.githubusercontent.com',
                 'release-assets.githubusercontent.com'}
HEX64 = re.compile(r'^[0-9a-f]{64}$')
UA = 'LoD-SC-VN-pincheck/1'


def fetch(url, method='GET', limit=1 << 20):
    """GET (giới hạn limit byte) hoặc HEAD. Lỗi xác minh chứng chỉ trên Windows (kho gốc của OpenSSL trong Python
    thiếu gốc mới, ví dụ Let's Encrypt YE1 của download.blender.org) → thử lại qua PowerShell Invoke-WebRequest
    (schannel, Windows tự cập nhật gốc). Vẫn xác minh chứng chỉ, không bao giờ tắt kiểm tra."""
    req = urllib.request.Request(url, method=method, headers={'User-Agent': UA, 'Accept': '*/*'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            if method == 'HEAD':
                return r.status, dict(r.headers), b''
            data = r.read(limit + 1)
    except urllib.error.URLError as e:
        if os.name == 'nt' and isinstance(getattr(e, 'reason', None), ssl.SSLCertVerificationError):
            print('(OpenSSL cua Python khong xac minh duoc chung chi %s - thu lai qua schannel cua Windows)'
                  % urllib.parse.urlparse(url).hostname)
            return fetch_schannel(url, method, limit)
        raise
    if len(data) > limit:
        raise IOError('phan hoi qua lon tu %s (> %d byte) - khong tai file lon' % (url, limit))
    return r.status, dict(r.headers), data


def fetch_schannel(url, method, limit):
    if "'" in url or '"' in url:
        raise IOError('url la: %s' % url)
    ps = ("$ProgressPreference = 'SilentlyContinue'; "
          "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; "
          "$r = Invoke-WebRequest -UseBasicParsing -MaximumRedirection 5 -Method %s -Uri '%s' -UserAgent '%s'; "
          "$b = New-Object byte[] 0; if ($r.RawContentStream) { $b = $r.RawContentStream.ToArray() }; "
          "if ($null -eq $b) { $b = New-Object byte[] 0 }; "
          "$h = @{}; foreach ($k in $r.Headers.Keys) { $h[$k] = [string]$r.Headers[$k] }; "
          "@{ status = [int]$r.StatusCode; headers = $h; body = [Convert]::ToBase64String($b) } | ConvertTo-Json -Compress"
          % ('Head' if method == 'HEAD' else 'Get', url, UA))
    out = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], capture_output=True,
                         timeout=120)
    if out.returncode:
        raise IOError('PowerShell Invoke-WebRequest loi: %s' % out.stderr.decode('utf-8', 'replace').strip()[:300])
    j = json.loads(out.stdout.decode('utf-8', 'replace'))
    data = base64.b64decode(j.get('body') or '')
    if len(data) > limit:
        raise IOError('phan hoi qua lon tu %s' % url)
    return j.get('status'), j.get('headers') or {}, data


def static_checks(pins, errs):
    if pins.get('format') != 1:
        errs.append('format phai la 1')
    tools = {t.get('id'): t for t in pins.get('tools', [])}
    for need in ('blender', 'realesrgan'):
        if need not in tools:
            errs.append('thieu cong cu %s' % need)
    for t in tools.values():
        tid = t.get('id')
        u = urllib.parse.urlparse(t.get('url', ''))
        if u.scheme != 'https' or u.hostname not in ALLOWED_HOSTS:
            errs.append('%s: url phai la https tren may cho phep: %s' % (tid, t.get('url')))
        if not HEX64.match(t.get('sha256') or ''):
            errs.append('%s: sha256 sai dinh dang' % tid)
        if not isinstance(t.get('size'), int) or t['size'] <= 0:
            errs.append('%s: size sai' % tid)
        ext = t.get('extract')
        for k, v in (t.get('file_sha256') or {}).items():
            if not HEX64.match(v or ''):
                errs.append('%s: file_sha256[%s] sai dinh dang' % (tid, k))
            if ext is not None and k not in ext:
                errs.append('%s: file_sha256[%s] khong nam trong extract' % (tid, k))
        if tid == 'realesrgan' and (not ext or t.get('exe') not in ext):
            errs.append('realesrgan: extract phai chua exe')
        if os.path.basename(u.path) != t.get('file'):
            errs.append('%s: ten file trong url (%s) khac "file" (%s)' % (tid, os.path.basename(u.path), t.get('file')))
    return tools


def check_blender(t, head, errs, notes):
    src = t.get('sha256_source', '')
    if os.path.dirname(urllib.parse.urlparse(src).path) != os.path.dirname(urllib.parse.urlparse(t['url']).path):
        errs.append('blender: sha256_source khong cung thu muc voi url')
    st, _, data = fetch(src)
    text = data.decode('utf-8', 'replace')
    found = None
    for ln in text.splitlines():
        parts = ln.split()
        if len(parts) >= 2 and parts[-1].lstrip('*') == t['file']:
            found = parts[0].lower()
    if found is None:
        errs.append('blender: %s khong co dong cho %s' % (src, t['file']))
    elif found != t['sha256']:
        errs.append('blender: SHA-256 chinh thuc %s != pins %s' % (found, t['sha256']))
    else:
        notes.append('blender: SHA-256 khop file chinh thuc %s' % src)
    if head:
        st, hdr, _ = fetch(t['url'], method='HEAD')
        cl = {k.lower(): v for k, v in hdr.items()}.get('content-length')
        if cl is None or int(cl) != t['size']:
            errs.append('blender: Content-Length %s != pins size %d' % (cl, t['size']))
        else:
            notes.append('blender: kich thuoc %d khop (HEAD)' % t['size'])
    else:
        notes.append('blender: chua doi chieu kich thuoc (them --head)')


def check_github(t, errs, notes):
    st, _, data = fetch(t['github_api'], limit=4 << 20)
    rel = json.loads(data.decode('utf-8'))
    name = os.path.basename(urllib.parse.urlparse(t['url']).path)
    asset = next((a for a in rel.get('assets', []) if a.get('name') == name), None)
    if asset is None:
        errs.append('realesrgan: release %s khong co asset %s' % (rel.get('tag_name'), name))
        return
    if asset.get('size') != t['size']:
        errs.append('realesrgan: size GitHub %s != pins %d' % (asset.get('size'), t['size']))
    else:
        notes.append('realesrgan: size %d khop GitHub' % t['size'])
    if asset.get('browser_download_url') != t['url']:
        errs.append('realesrgan: browser_download_url %s != pins url' % asset.get('browser_download_url'))
    dg = asset.get('digest')
    if dg:
        if dg.lower() != 'sha256:' + t['sha256']:
            errs.append('realesrgan: digest GitHub %s != pins sha256' % dg)
        else:
            notes.append('realesrgan: digest GitHub khop')
    else:
        notes.append('realesrgan: GitHub khong cong bo digest (null) - pin la SHA-256 tu tinh tren ban dung kich thuoc')


def check_zip(tools, path, errs, notes):
    name = os.path.basename(path)
    t = next((x for x in tools.values() if x.get('file') == name), None)
    if t is None:
        errs.append('%s: khong co cong cu nao co "file" = %s' % (path, name))
        return
    tid = t['id']
    h = hashlib.sha256()
    size = 0
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
            size += len(chunk)
    if size != t['size']:
        errs.append('%s: zip %s co %d byte, pins %d' % (tid, name, size, t['size']))
    if h.hexdigest() != t['sha256']:
        errs.append('%s: SHA-256 zip %s != pins %s' % (tid, h.hexdigest(), t['sha256']))
    else:
        notes.append('%s: zip %s dung kich thuoc + SHA-256' % (tid, name))
    root = (t.get('root') or '')
    prefix = root + '/' if root else ''
    ext = t.get('extract')
    want = dict(t.get('file_sha256') or {})
    seen = set()
    total = 0
    with zipfile.ZipFile(path) as z:
        for zi in z.infolist():
            n = zi.filename
            segs = n.split('/')
            if (not n or '\\' in n or '\0' in n or n.startswith('/') or (len(n) >= 2 and n[1] == ':')
                    or '..' in segs or '.' in segs):
                errs.append('%s: muc zip khong an toan (Installer se tu choi ca ban cai): %r' % (tid, n))
                continue
            if prefix:
                if n == prefix:
                    continue
                if not n.startswith(prefix):
                    errs.append('%s: muc zip ngoai thu muc goc %s: %r' % (tid, root, n))
                    continue
                n = n[len(prefix):]
            if not n or n.endswith('/'):
                continue
            if ext is not None and n not in ext:
                continue
            seen.add(n)
            total += zi.file_size
            if n in want:
                got = hashlib.sha256(z.read(zi)).hexdigest()
                if got != want.pop(n):
                    errs.append('%s: file_sha256[%s] khac SHA-256 trong zip (%s)' % (tid, n, got))
    for n in (ext or []):
        if n not in seen:
            errs.append('%s: zip thieu muc extract %s' % (tid, n))
    for n in want:
        errs.append('%s: zip thieu file %s (co trong file_sha256)' % (tid, n))
    for n in [t.get('exe'), t.get('python')]:
        if n and n not in seen:
            errs.append('%s: zip thieu %s' % (tid, n))
    if total != t.get('installed_size'):
        errs.append('%s: tong dung luong giai nen %d != installed_size %s' % (tid, total, t.get('installed_size')))
    else:
        notes.append('%s: %d file se giai nen, %d byte = installed_size; file_sha256 khop' % (tid, len(seen), total))


def selftest():
    """Tự kiểm offline (không mạng): zip + pins TỔNG HỢP trong thư mục tạm. Bản đúng phải đạt; mỗi bản lệch (sha, size,
    file_sha256, installed_size, thiếu mục extract, url http, máy ngoài danh sách, file_sha256 ngoài extract, zip có mục
    "..") phải bị bắt. Trả số ca sai."""
    import copy
    import tempfile
    files = {'tool.exe': b'fake exe\r\n', 'lib.dll': b'fake dll', 'models/m.bin': b'fake bin' * 50,
             'models/m.param': b'fake param\r\n'}
    extra = {'readme.txt': b'not extracted', 'models/other.bin': b'other model'}

    def make_zip(path, entries):
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            for n, b in entries:
                z.writestr(zipfile.ZipInfo(n, (2026, 10, 16, 0, 0, 0)), b)
        with open(path, 'rb') as f:
            return f.read()

    bad = 0
    with tempfile.TemporaryDirectory() as td:
        good = os.path.join(td, 'good', 'fake-tool.zip')
        slip = os.path.join(td, 'slip', 'fake-tool.zip')
        os.makedirs(os.path.dirname(good))
        os.makedirs(os.path.dirname(slip))
        entries = sorted(files.items()) + sorted(extra.items())
        data = make_zip(good, entries)
        sdata = make_zip(slip, entries + [('models/../../evil.txt', b'evil')])
        base = {'format': 1, 'tools': [
            {'id': 'blender', 'url': 'https://download.blender.org/release/Blender5.2/blender-x.zip',
             'file': 'blender-x.zip', 'size': 1, 'sha256': '0' * 64, 'extract': None, 'file_sha256': {}},
            {'id': 'realesrgan', 'url': 'https://github.com/o/r/releases/download/v1/fake-tool.zip',
             'file': 'fake-tool.zip', 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'root': '',
             'extract': sorted(files), 'exe': 'tool.exe',
             'file_sha256': {k: hashlib.sha256(v).hexdigest() for k, v in files.items()},
             'installed_size': sum(len(v) for v in files.values())}]}

        def mutate(fn):
            p = copy.deepcopy(base)
            fn(p['tools'][1])
            return p

        def setk(k, v):
            return lambda t: t.__setitem__(k, v)

        def fsha(t):
            t['file_sha256']['models/m.bin'] = 'f' * 64

        def missing(t):
            t['extract'] = t['extract'] + ['models/missing.bin']

        def outside(t):
            t['file_sha256']['readme.txt'] = 'a' * 64

        def slip_pins(t):
            # đúng size + sha của zip độc: chỉ kiểm mục ".." mới bắt được
            t['size'] = len(sdata)
            t['sha256'] = hashlib.sha256(sdata).hexdigest()

        cases = [
            ('dung', base, good, False),
            ('sha256 sai', mutate(setk('sha256', 'e' * 64)), good, True),
            ('size sai', mutate(setk('size', len(data) + 1)), good, True),
            ('file_sha256 sai', mutate(fsha), good, True),
            ('installed_size sai', mutate(setk('installed_size', 1)), good, True),
            ('thieu muc extract', mutate(missing), good, True),
            ('url http', mutate(setk('url', 'http://github.com/o/r/releases/download/v1/fake-tool.zip')), good, True),
            ('may ngoai danh sach', mutate(setk('url', 'https://evil.invalid/fake-tool.zip')), good, True),
            ('file_sha256 ngoai extract', mutate(outside), good, True),
            ('zip co muc ..', mutate(slip_pins), slip, True),
        ]
        for name, pins, zp, want_err in cases:
            errs, notes = [], []
            tools = static_checks(pins, errs)
            try:
                check_zip(tools, zp, errs, notes)
            except (OSError, zipfile.BadZipFile) as e:
                errs.append(str(e))
            ok = bool(errs) == want_err
            bad += 0 if ok else 1
            print('%s  tu kiem: %-26s -> %s' % ('OK ' if ok else 'SAI', name, ('bat duoc: ' + errs[0]) if errs else 'dat'))
    print('TU KIEM DAT' if not bad else 'TU KIEM KHONG DAT (%d ca sai)' % bad)
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pins', default=os.path.join(ROOT, 'tools', 'remaster_tool', 'pins.json'))
    ap.add_argument('--head', action='store_true', help='them HEAD toi url Blender de doi chieu Content-Length')
    ap.add_argument('--offline', action='store_true', help='chi kiem tinh')
    ap.add_argument('--zip', action='append', default=[], help='zip da co tren may de doi chieu (khong can mang)')
    ap.add_argument('--selftest', action='store_true', help='tu kiem offline bang zip + pins tong hop roi thoat')
    a = ap.parse_args()
    if a.selftest:
        return 0 if selftest() == 0 else 1
    with open(a.pins, encoding='utf-8') as f:
        pins = json.load(f)
    errs, notes = [], []
    tools = static_checks(pins, errs)
    for zp in a.zip:
        try:
            check_zip(tools, zp, errs, notes)
        except (OSError, zipfile.BadZipFile) as e:
            errs.append('%s: khong doc duoc: %s' % (zp, e))
    if not a.offline and not errs:
        try:
            check_blender(tools['blender'], a.head, errs, notes)
        except Exception as e:  # noqa: BLE001 - báo lỗi mạng rõ ràng
            errs.append('blender: loi mang: %s' % e)
        try:
            check_github(tools['realesrgan'], errs, notes)
        except Exception as e:  # noqa: BLE001
            errs.append('realesrgan: loi mang: %s' % e)
    for n in notes:
        print('OK   ' + n)
    for e in errs:
        print('LOI  ' + e)
    print('DAT' if not errs else 'KHONG DAT (%d loi)' % len(errs))
    return 0 if not errs else 1


if __name__ == '__main__':
    sys.exit(main())
