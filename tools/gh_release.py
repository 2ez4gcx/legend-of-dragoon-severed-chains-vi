"""Tạo bản phát hành GitHub (Releases) và tải tệp lên, rồi tải ngược về kiểm SHA-256.

Cách gọi:
    python tools/gh_release.py --repo 2ez4gcx/legend-of-dragoon-severed-chains-vi --tag v0.1-sc-affcef0 \
        --target <commit> --name "..." --notes release_notes/v0.1-sc-affcef0.md [--prerelease] \
        --asset release/X.zip --asset release/SHA256SUMS.txt
Token: biến môi trường GH_TOKEN, nếu không có thì lấy bằng `git credential fill` (không in ra).
Tag đã có release thì dùng lại release đó; tệp trùng tên đã có thì báo lỗi (không ghi đè). Exit 0 = mọi tệp tải lên và tải
về khớp SHA-256.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

API = 'https://api.github.com'


def token():
    t = os.environ.get('GH_TOKEN')
    if t:
        return t
    out = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n', capture_output=True,
                         text=True, check=True).stdout
    for line in out.splitlines():
        if line.startswith('password='):
            return line[len('password='):]
    sys.exit('LOI: khong lay duoc token GitHub')


class _DropAuthRedirect(urllib.request.HTTPRedirectHandler):
    """Tải tệp release: GitHub chuyển hướng sang máy chủ lưu trữ có URL ký sẵn — không gửi kèm token sang đó."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlparse(newurl).netloc != urllib.parse.urlparse(req.full_url).netloc:
            new.headers.pop('Authorization', None)
            new.unredirected_hdrs.pop('Authorization', None)
        return new


_OPENER = urllib.request.build_opener(_DropAuthRedirect)


def call(method, url, tok, data=None, ctype='application/json', accept='application/vnd.github+json'):
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Authorization', 'Bearer ' + tok)
    req.add_header('Accept', accept)
    req.add_header('X-GitHub-Api-Version', '2022-11-28')
    if data is not None:
        req.add_header('Content-Type', ctype)
    with _OPENER.open(req, timeout=1800) as r:
        body = r.read()
        return r.status, body


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', required=True)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--target', required=True)
    ap.add_argument('--name', required=True)
    ap.add_argument('--notes', required=True)
    ap.add_argument('--prerelease', action='store_true')
    ap.add_argument('--asset', action='append', default=[])
    a = ap.parse_args()
    tok = token()

    rel = None
    try:
        _, body = call('GET', '%s/repos/%s/releases/tags/%s' % (API, a.repo, a.tag), tok)
        rel = json.loads(body)
        print('dung lai release co san: %s' % rel['html_url'])
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    if rel is None:
        payload = {'tag_name': a.tag, 'target_commitish': a.target, 'name': a.name,
                   'body': open(a.notes, encoding='utf-8').read(), 'draft': False, 'prerelease': a.prerelease}
        _, body = call('POST', '%s/repos/%s/releases' % (API, a.repo), tok, json.dumps(payload).encode('utf-8'))
        rel = json.loads(body)
        print('tao release: %s' % rel['html_url'])

    existing = {x['name'] for x in rel.get('assets', [])}
    upload = rel['upload_url'].split('{')[0]
    ok = True
    for path in a.asset:
        name = os.path.basename(path)
        data = open(path, 'rb').read()
        if name in existing:
            sys.exit('LOI: release da co tep %s (khong ghi de)' % name)
        ctype = ('application/zip' if name.endswith('.zip') else
                 'application/vnd.android.package-archive' if name.endswith('.apk') else 'text/plain')
        _, body = call('POST', '%s?name=%s' % (upload, urllib.request.quote(name)), tok, data, ctype)
        asset = json.loads(body)
        # tải ngược về (API asset, octet-stream) và so SHA-256
        _, back = call('GET', asset['url'], tok, accept='application/octet-stream')
        same = sha256_bytes(back) == sha256_bytes(data)
        ok &= same
        print('%s: %d byte, tai ve %s SHA-256 %s' % (name, len(data), 'KHOP' if same else 'KHAC', sha256_bytes(back)))
    print('xong: %s' % rel['html_url'])
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
