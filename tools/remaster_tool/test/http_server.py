"""http_server.py — máy chủ HTTP cục bộ (chỉ 127.0.0.1) cho kiểm thử Downloader của công cụ "Tạo mô hình HD".

Cách gọi (run_tests.ps1 chạy nền):
    python -I tools/remaster_tool/test/http_server.py --root DIR --port-file F --log F [--cut PATH:BYTES:TIMES ...]

    GET /<đường dẫn>          file DIR/<đường dẫn>; ETag = "<sha1 nội dung>", Last-Modified cố định;
                              Range "bytes=N-" + If-Range khớp ETag (hoặc không có If-Range) → 206 + Content-Range,
                              If-Range không khớp → 200 cả file; N >= cỡ file → 416.
    GET /redirect/<p>         302 → /<p> (cùng máy)
    GET /redirect-bad/<p>     302 → https://evil.invalid/<p> (máy ngoài danh sách cho phép — công cụ phải từ chối
                              trước khi kết nối)
    GET /__quit               dừng máy chủ
    --cut PATH:BYTES:TIMES    TIMES lần đầu GET đúng PATH (ví dụ /cut/blender-5.2.2-windows-x64.zip) chỉ gửi BYTES
                              byte thân rồi đóng kết nối (giả mất mạng giữa chừng); header vẫn khai đủ Content-Length.
Mỗi yêu cầu ghi một dòng JSON vào --log: {method, path, range, if_range, status, sent}. Cổng do hệ điều hành chọn,
ghi vào --port-file sau khi đã lắng nghe. Chỉ thư viện chuẩn.
"""
import argparse
import hashlib
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

ARGS = None
CUTS = {}
LOCK = threading.Lock()
LAST_MODIFIED = 'Fri, 16 Oct 2026 00:00:00 GMT'


def log(entry):
    with LOCK:
        with open(ARGS.log, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *a):
        pass

    def _end(self, status, sent, extra=None):
        e = {'method': self.command, 'path': self.path, 'range': self.headers.get('Range'),
             'if_range': self.headers.get('If-Range'), 'status': status, 'sent': sent}
        if extra:
            e.update(extra)
        log(e)

    def _simple(self, status, body=b'', headers=None):
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        if body and self.command != 'HEAD':
            self.wfile.write(body)
        self._end(status, len(body))

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = unquote(self.path.split('?', 1)[0])
        if path == '/__quit':
            self._simple(200, b'bye')
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path.startswith('/redirect/'):
            self._simple(302, headers={'Location': '/' + path[len('/redirect/'):]})
            return
        if path.startswith('/redirect-bad/'):
            self._simple(302, headers={'Location': 'https://evil.invalid/' + path[len('/redirect-bad/'):]})
            return
        rel = path.lstrip('/')
        full = os.path.normpath(os.path.join(ARGS.root, rel))
        if not full.startswith(os.path.normpath(ARGS.root) + os.sep) or not os.path.isfile(full):
            self._simple(404, b'not found')
            return
        with open(full, 'rb') as f:
            data = f.read()
        etag = '"%s"' % hashlib.sha1(data).hexdigest()
        start = 0
        status = 200
        rng = self.headers.get('Range')
        if rng and rng.startswith('bytes=') and rng.endswith('-'):
            if_range = self.headers.get('If-Range')
            if if_range is None or if_range == etag or if_range == LAST_MODIFIED:
                start = int(rng[len('bytes='):-1])
                if start >= len(data):
                    self._simple(416, headers={'Content-Range': 'bytes */%d' % len(data)})
                    return
                status = 206
        body = data[start:]
        self.send_response(status)
        self.send_header('Content-Type', 'application/zip')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('ETag', etag)
        self.send_header('Last-Modified', LAST_MODIFIED)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Connection', 'close')
        if status == 206:
            self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, len(data) - 1, len(data)))
        self.end_headers()
        if self.command == 'HEAD':
            self._end(status, 0)
            return
        limit = None
        with LOCK:
            c = CUTS.get(path)
            if c and c[1] > 0:
                c[1] -= 1
                limit = c[0]
        if limit is not None:
            self.wfile.write(body[:limit])
            self.wfile.flush()
            self._end(status, min(limit, len(body)), {'cut': True})
            self.close_connection = True
            try:
                self.connection.shutdown(2)
            except OSError:
                pass
            return
        self.wfile.write(body)
        self._end(status, len(body))


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--port-file', required=True)
    ap.add_argument('--log', required=True)
    ap.add_argument('--cut', action='append', default=[])
    ARGS = ap.parse_args()
    ARGS.root = os.path.abspath(ARGS.root)
    for c in ARGS.cut:
        p, b, t = c.rsplit(':', 2)
        CUTS[p] = [int(b), int(t)]
    srv = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    tmp = ARGS.port_file + '.tmp'
    with open(tmp, 'w', encoding='ascii') as f:
        f.write(str(srv.server_address[1]))
    os.replace(tmp, ARGS.port_file)
    srv.serve_forever()


if __name__ == '__main__':
    main()
