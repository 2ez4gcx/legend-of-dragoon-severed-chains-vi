"""Tạo lại sc-vi/patches/sc-core-affcef0.diff: phần sửa lõi Severed Chains (sc-vi/src) so với mã nguồn SC đúng commit.

Cách gọi:
    python tools/sc_core_diff.py [--check]
Đầu vào: Severed-Chains/src/main/java (clone SC, phải ở commit affcef0; biến môi trường SC_ROOT để đổi chỗ, như sc_lang/sc_font) và sc-vi/src.
Mỗi file trong sc-vi/src: có trong SC -> unified diff "a/src/main/java/..." / "b/src/main/java/...", 3 dòng ngữ cảnh;
không có -> file mới (--- /dev/null). Xuống dòng chuẩn hoá LF (SC trên Windows checkout CRLF). Thứ tự cố định → kết quả
xác định. --check: chỉ so với file diff hiện có, khác thì exit 1.
"""
import difflib
import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SC = os.environ.get('SC_ROOT', os.path.join(ROOT, 'Severed-Chains'))
COMMIT = 'affcef0'
OUT = os.path.join(ROOT, 'sc-vi', 'patches', 'sc-core-%s.diff' % COMMIT)
ORDER = ['legend/game/types/LodString.java', 'legend/game/Text.java', 'legend/game/submap/SMap.java']


def lines(path):
    if not os.path.exists(path):
        return []
    return open(path, encoding='utf-8', newline='').read().replace('\r\n', '\n').splitlines(keepends=True)


def main():
    head = subprocess.run(['git', '-C', SC, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    if not head.startswith(COMMIT):
        print('LOI: %s dang o commit %s, can %s' % (SC, head[:7] or '?', COMMIT))
        sys.exit(1)
    src = os.path.join(ROOT, 'sc-vi', 'src')
    files = []
    for d, _, names in os.walk(src):
        for name in names:
            if name.endswith('.java'):
                files.append(os.path.relpath(os.path.join(d, name), src).replace('\\', '/'))
    files.sort(key=lambda f: (ORDER.index(f) if f in ORDER else len(ORDER), f))
    out = []
    for f in files:
        old = os.path.join(SC, 'src', 'main', 'java', f)
        a = '/dev/null' if not os.path.exists(old) else 'a/src/main/java/' + f
        out += difflib.unified_diff(lines(old), lines(os.path.join(src, f)), a, 'b/src/main/java/' + f, n=3)
    text = ''.join(out)
    if '--check' in sys.argv:
        same = os.path.exists(OUT) and open(OUT, encoding='utf-8', newline='').read().replace('\r\n', '\n') == text
        print('diff %s' % ('khop' if same else 'KHAC — chay lai khong co --check'))
        sys.exit(0 if same else 1)
    open(OUT, 'w', encoding='utf-8', newline='\n').write(text)
    print('%s: %d file, %d dong' % (os.path.relpath(OUT, ROOT), len(files), text.count('\n')))


if __name__ == '__main__':
    main()
