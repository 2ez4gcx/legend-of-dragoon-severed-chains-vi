"""Kiểm các file ngôn ngữ tiếng Việt của Severed Chains so với bản tiếng Anh.

Cách gọi:
    python tools/sc_lang_check.py [--chi-tiet]
Cặp kiểm (Việt -> Anh):
    out/lang/lod.vi.lang        -> Severed-Chains/src/main/resources/lod/lang/en.lang   (chạy tools/sc_lang.py trước)
    tr_sc/core.vi.lang          -> .../lod_core/lang/en.lang
    tr_sc/turnorder.vi.lang     -> .../turn_order/lang/en.lang
    tr_sc/unpacker.vi.lang      -> Severed-Chains/lang/unpacker.en.lang
Lỗi (exit 1): khoá không có trong bản Anh; tham số định dạng (%s %d %.2f ..., không tính %% là dấu %) khác bản Anh; giá trị rỗng khi bản Anh có chữ.
Cảnh báo: khoá chưa dịch (trừ khoá cố ý giữ tiếng Anh như bản PS1); dòng có thể tràn: bề rộng dòng Việt (phông Việt
out/fonts/vietnamese.json, bước = w + 1) lớn hơn dòng Anh tương ứng (phông Smooth mặc định của SC) quá 15% và quá 6 px.
"""
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SC = os.environ.get('SC_ROOT', os.path.join(ROOT, 'Severed-Chains'))
RES = os.path.join(SC, 'src', 'main', 'resources')
PAIRS = [
    (os.path.join(ROOT, 'out', 'lang', 'lod.vi.lang'), os.path.join(RES, 'lod', 'lang', 'en.lang')),
    (os.path.join(ROOT, 'tr_sc', 'core.vi.lang'), os.path.join(RES, 'lod_core', 'lang', 'en.lang')),
    (os.path.join(ROOT, 'tr_sc', 'turnorder.vi.lang'), os.path.join(RES, 'turn_order', 'lang', 'en.lang')),
    (os.path.join(ROOT, 'tr_sc', 'unpacker.vi.lang'), os.path.join(SC, 'lang', 'unpacker.en.lang')),
]
KEEP_EN = re.compile(r'^lod\.(equipment\.[a-z0-9_]+\.name|additions\.|character_templates\.|name$|campaign_type\.)'
                     r'|^lod_core\.(ui\.hotkey|ui\.title\.hotkey|ui\.fps|ui\.mods\.tooltip|ui\.options\.tooltip|ui\.about\.tooltip|'
                     r'config_presets\.severed_chains|config\.resolution\._|config\.shader_pixelate\.P)')
FMT = re.compile(r'%(?:\d+\$)?[-#+ 0,(]*\d*(?:\.\d+)?[a-zA-Z%]')


def load(path):
    """Java .properties tối giản: key=value, bỏ khoảng trắng quanh '=', \\n trong giá trị giữ dạng 2 ký tự."""
    d = {}
    for line in open(path, encoding='utf-8'):
        line = line.rstrip('\n').rstrip('\r')
        s = line.strip()
        if not s or s[0] in '#!' or '=' not in s:
            continue
        k, v = s.split('=', 1)
        d[k.strip()] = v.strip()
    return d


def widths(font_json):
    g = json.load(open(font_json, encoding='utf-8'))['glyphs']
    out = {}
    for k, v in g.items():
        ch = k if len(k) == 1 else chr(int(k[2:], 16))
        out[ch] = v['w'] + 1
    return out


def px(s, w):
    return sum(w.get(c, 9) for c in s)


def main():
    detail = '--chi-tiet' in sys.argv
    w_vi = widths(os.path.join(ROOT, 'out', 'fonts', 'vietnamese.json'))
    w_en = widths(os.path.join(SC, 'gfx', 'fonts', 'smooth.json'))
    errors, untranslated, wide = [], [], []
    for vi_path, en_path in PAIRS:
        if not os.path.exists(vi_path):
            errors.append('thieu file %s' % vi_path)
            continue
        vi, en = load(vi_path), load(en_path)
        name = os.path.relpath(vi_path, ROOT)
        for k, v in vi.items():
            if k not in en:
                errors.append('%s: khoa %s khong co trong ban Anh' % (name, k))
                continue
            fa = sorted(f for f in FMT.findall(en[k]) if f != '%%')   # %% = dấu % thường, không phải tham số
            fv = sorted(f for f in FMT.findall(v) if f != '%%')
            if fa != fv:
                errors.append('%s: %s ma dinh dang khac: Anh %s / Viet %s' % (name, k, fa, fv))
            if en[k] and not v:
                errors.append('%s: %s rong' % (name, k))
            en_lines = en[k].replace('%%', '%').split('\\n')
            vi_lines = v.replace('%%', '%').split('\\n')
            limit = max(px(x, w_en) for x in en_lines)
            for x in vi_lines:
                p = px(x, w_vi)
                if p > limit * 1.15 and p - limit > 6:
                    wide.append((p - limit, name, k, x, p, limit))
        for k, v in en.items():
            if k not in vi and v and not KEEP_EN.search(k):
                untranslated.append('%s: %s = %s' % (name, k, v))

    for e in errors:
        print('LOI ' + e)
    print('chua dich: %d' % len(untranslated))
    for u in untranslated if detail else untranslated[:20]:
        print('  ' + u)
    print('co the tran (dong Viet rong hon dong Anh dai nhat): %d' % len(wide))
    for d, name, k, x, p, limit in sorted(wide, reverse=True)[:40 if not detail else None]:
        print('  +%3d px %s %s: "%s" (%d px, Anh %d px)' % (d, name, k, x, p, limit))
    print('DAT' if not errors else 'LOI: %d' % len(errors))
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
