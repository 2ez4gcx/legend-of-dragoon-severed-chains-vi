"""Sinh bảng thoại tiếng Việt cho Severed Chains: out/lang/dialogue.vi.tsv

Cách gọi:
    python tools/sc_dialogue.py [--only S00101,S00102,...]

Đầu vào (dự án D:\\LOD, biến môi trường LOD_ROOT để đổi chỗ):
    tr/en/strings.tsv   uid \\t số lần \\t vị trí \\t chữ Anh dạng tag
    tr/vi/*.json        {uid: chữ Việt dạng tag}
    tr/choices.json     {"choice": {uid: ...}, "dong1": [...]} — hộp lựa chọn / khung 1 dòng
Đầu ra: mỗi dòng "<chữ Anh>\\t<chữ Việt>\\t<kiểu>" (UTF-8, NFC), tag giống tools/dump.py của D:\\LOD:
    {n} = A1FF, {p} = A3FF, {XXXX} = mã 16-bit giữ nguyên, ký tự thường = glyph LoD 0x00-0x56 (bảng EN).
    Lớp Java ScriptTextTranslations tính đúng chuỗi khoá này từ mảng mã LodString rồi tra bảng.
Kiểu (cột 3) — lớp Java tự NGẮT DÒNG lúc chạy theo bề rộng khung w của chính chuỗi (cặp (w,l) sau A0FF trong
script, thứ SC dùng để dựng khung; không có cặp thì lấy số ký tự dòng tiếng Anh dài nhất):
    N  dòng đầu là tên người nói (giữ nguyên), các dòng còn lại trong mỗi trang đã được nối lại -> Java ngắt lấp đầy
    J  mọi dòng trong trang đã được nối lại -> Java ngắt lấp đầy
    L  giữ nguyên các dòng (hộp lựa chọn, khung 1 dòng, bảng, câu có mã B0xx như vtext.reflow của D:\\LOD);
       Java chỉ ngắt (ở dấu cách) dòng nào dài hơn w để game không cắt giữa chữ.
Quy tắc nhận tên người nói và nối dòng lấy từ build.py / vtext.reflow của D:\\LOD.
"""
import collections
import glob
import json
import os
import re
import sys
import unicodedata

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
LOD = os.environ.get('LOD_ROOT', os.path.join(ROOT, '..', 'LOD'))
OUT = os.path.join(ROOT, 'out')

CODE = re.compile(r'\{[0-9A-Fa-f]{4}\}')
UNKNOWN = re.compile(r'\?{2,}')
PUNCT = re.compile(r'[.,!?…:"]')


def speakers(en):
    """như build._speakers của D:\\LOD: dòng đầu (trước {n}) xuất hiện >= 2 lần, <= 24 ký tự, không dấu câu."""
    c = collections.Counter()
    for text in en.values():
        if '{n}' not in text:
            continue
        f = CODE.sub('', text).split('{n}')[0].strip()
        if f and len(f) <= 24 and (UNKNOWN.fullmatch(f) or not PUNCT.search(f)):
            c[f] += 1
    return {k for k, v in c.items() if v >= 2}


def is_name(en, vi, spk):
    ens = [CODE.sub('', x).strip() for x in en.split('{p}')[0].split('{n}')]
    v0 = CODE.sub('', vi.split('{n}')[0]).strip()
    looks = len(ens[0]) <= 32 and not PUNCT.search(ens[0]) and v0 and not PUNCT.search(v0)
    return len(ens) > 1 and bool(ens[0] in spk or UNKNOWN.fullmatch(ens[0]) or (looks and ens[1][:1].isupper()))


def reflow(text, keep_first):
    """vtext.reflow của D:\\LOD: nối các {n} trong cùng trang bằng dấu cách. Giữ: dòng tên (keep_first),
    dòng có ':' và dòng sau nó, dòng rỗng, dòng bắt đầu bằng '-', '•', '*', chữ số."""
    pages = []
    for pg in text.split('{p}'):
        ls = pg.split('{n}')
        out = ls[0]
        for i in range(1, len(ls)):
            prev, cur = CODE.sub('', ls[i - 1]).strip(), CODE.sub('', ls[i]).strip()
            keep = (i == 1 and keep_first and not pages) or ':' in prev or ':' in cur or not prev or not cur \
                or cur[:1] in '-•*' or cur[:1].isdigit()
            out += ('{n}' if keep else ' ') + ls[i]
        pages.append(re.sub(r'(?<=\S)  +(?=\S)', ' ', out))
    return '{p}'.join(pages)


def main():
    only = None
    if '--only' in sys.argv:
        only = set(sys.argv[sys.argv.index('--only') + 1].split(','))
    en = {}
    for line in open(os.path.join(LOD, 'tr', 'en', 'strings.tsv'), encoding='utf-8'):
        uid, _, _, text = line.rstrip('\n').split('\t')
        en[uid] = text
    vi = {}
    for f in sorted(glob.glob(os.path.join(LOD, 'tr', 'vi', '*.json'))):
        vi.update(json.load(open(f, encoding='utf-8')))
    choices = json.load(open(os.path.join(LOD, 'tr', 'choices.json'), encoding='utf-8'))
    keep = set(choices.get('choice', {})) | set(choices.get('dong1', []))
    spk = speakers(en)

    os.makedirs(os.path.join(OUT, 'lang'), exist_ok=True)
    stat = collections.Counter()
    with open(os.path.join(OUT, 'lang', 'dialogue.vi.tsv'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('# Bang thoai tieng Viet cho Severed Chains (tools/sc_dialogue.py). '
                'Cot: chu Anh dang tag | chu Viet | kieu N/J/L\n')
        for uid, e in en.items():
            if not uid.startswith('S') or uid not in vi or (only and uid not in only):
                continue
            v = unicodedata.normalize('NFC', vi[uid])
            if '\t' in e or '\t' in v or '\n' in v:
                stat['bo'] += 1
                continue
            if uid in keep or re.search(r'\{B0[0-9A-Fa-f]{2}\}', v):
                mode = 'L'
            elif is_name(e, v, spk):
                mode = 'N'
                v = reflow(v, True)
            else:
                mode = 'J'
                v = reflow(v, False)
            stat[mode] += 1
            f.write('%s\t%s\t%s\n' % (e, v, mode))
    print('dialogue.vi.tsv: %d cau (N co ten %d, J noi dong %d, L giu dong %d, bo %d)' % (
        stat['N'] + stat['J'] + stat['L'], stat['N'], stat['J'], stat['L'], stat['bo']))


if __name__ == '__main__':
    main()
