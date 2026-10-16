"""Tạo file ngôn ngữ tiếng Việt cho Severed Chains từ bản dịch của dự án D:\\LOD.

Cách gọi:
    python tools/sc_lang.py [--report]

Đầu vào:
    Severed-Chains/src/main/resources/lod/lang/en.lang   (khoá -> tiếng Anh, định dạng Java .properties)
    D:/LOD/tr/en/menu.tsv  (uid, module, offset, w,l, tiếng Anh với {n})
    D:/LOD/tr/vi/*.json    ({uid: tiếng Việt})
Đầu ra:
    out/lang/lod.vi.lang       (chỉ các khoá ghép được; khoá thiếu SC tự lấy tiếng Anh)
    out/lang_missing.tsv       (khoá chưa ghép được, để dịch tay)

Ghép theo chữ tiếng Anh đã chuẩn hoá (bỏ {n}/\\n, gộp khoảng trắng, chữ thường).
Trùng chữ tiếng Anh nhưng khác bản dịch: lấy uid đầu tiên có bản dịch, ghi cảnh báo.
"""
import collections
import glob
import json
import os
import re
import sys
import unicodedata

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SC = os.path.join(ROOT, 'Severed-Chains')
LOD = os.environ.get('LOD_ROOT', os.path.join(ROOT, '..', 'LOD'))
OUT = os.path.join(ROOT, 'out')

TAG = re.compile(r'\{[0-9A-F]{4}\}')


def norm(s):
    s = s.replace('{n}', ' ').replace('\\n', ' ').replace('\n', ' ').replace('%%', '%')
    s = TAG.sub('', s)
    return re.sub(r'\s+', ' ', s).strip().lower()


def load_lang(path):
    d = {}
    for line in open(path, encoding='utf-8'):
        line = line.rstrip('\n')
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        d[k] = v
    return d


def load_vi():
    vi = {}
    for f in sorted(glob.glob(os.path.join(LOD, 'tr', 'vi', '*.json'))):
        vi.update(json.load(open(f, encoding='utf-8')))
    return vi


def to_lang_value(vi_text):
    """Chuỗi Việt có {n} -> giá trị .properties (\\n, %% cho String.format)."""
    s = unicodedata.normalize('NFC', vi_text)
    s = TAG.sub('', s)
    s = s.replace('{n}', '\\n')
    return s.replace('%', '%%')


def main():
    en = load_lang(os.path.join(SC, 'src', 'main', 'resources', 'lod', 'lang', 'en.lang'))
    vi = load_vi()
    menu = [l.rstrip('\n').split('\t') for l in open(os.path.join(LOD, 'tr', 'en', 'menu.tsv'), encoding='utf-8')]
    en2m = collections.defaultdict(list)
    for r in menu:
        en2m[norm(r[-1])].append(r[0])

    out, missing = {}, []
    stat = collections.Counter()
    for k, v in en.items():
        p = k.split('.')
        cat = '.'.join(p[:2]) + ('.' + p[-1] if len(p) > 2 and p[1] not in ('ui', 'input_actions', 'config') else '')
        stat[cat, 'tong'] += 1
        if not v.strip():
            stat[cat, 'rong'] += 1
            continue
        uids = [u for u in en2m.get(norm(v), []) if u in vi]
        if uids:
            vals = {to_lang_value(vi[u]) for u in uids}
            if len(vals) > 1:
                print('canh bao: %s co %d ban dich khac nhau %s' % (k, len(vals), uids), file=sys.stderr)
            out[k] = to_lang_value(vi[uids[0]])
            stat[cat, 'khop'] += 1
        else:
            missing.append((k, v))

    os.makedirs(os.path.join(OUT, 'lang'), exist_ok=True)
    with open(os.path.join(OUT, 'lang', 'lod.vi.lang'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('# Ban dich tieng Viet cho Severed Chains (tao boi tools/sc_lang.py tu du an D:\\LOD)\n')
        for k in en:
            if k in out:
                f.write('%s=%s\n' % (k, out[k]))
    with open(os.path.join(OUT, 'lang_missing.tsv'), 'w', encoding='utf-8', newline='\n') as f:
        for k, v in missing:
            f.write('%s\t%s\n' % (k, v))

    if True:
        cats = sorted({c for c, _ in stat})
        for c in cats:
            print('%-34s khop %4d / %4d (rong %d)' % (c, stat[c, 'khop'], stat[c, 'tong'], stat[c, 'rong']))
        print('tong: %d khoa co ban dich, %d chua ghep' % (len(out), len(missing)))


if __name__ == '__main__':
    main()
