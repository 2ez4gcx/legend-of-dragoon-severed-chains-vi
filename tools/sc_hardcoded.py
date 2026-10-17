"""Chuỗi tiếng Anh VIẾT CỨNG trong mã Java của Severed Chains: đếm, ghép bản dịch PS1, sinh file ngôn ngữ.

Cách gọi:
    python tools/sc_hardcoded.py            -> out/lang/scvi.vi.lang + out/hardcoded_missing.tsv + báo cáo
Lớp Java legend.game.i18n.HardcodedTranslations đọc khoá "scvi.<bảng>.<slug>" (slug = chữ Anh viết thường, mọi cụm ký tự
không phải a-z0-9 thành '_', bỏ '_' ở hai đầu — Java và Python tính giống nhau) rồi ghi bản dịch vào đúng mảng lúc nạp
ngôn ngữ; khoá không có thì giữ chữ Anh. Câu viết thẳng trong mã (hộp hỏi bản đồ thế giới, "Load Game", "Hits: …") dịch lúc
vẽ trong Text.renderText theo khoá "scvi.ui.<slug>".
Nguồn bản dịch: tr/vi của D:\\LOD (ghép theo chữ Anh của tr/en/menu.tsv, bỏ {n}/khoảng trắng), rồi tr_sc/gop/scvi.vi.lang
(dịch tay, đè lên). Bảng place (bản đồ thế giới) giữ chỗ xuống dòng như bản Anh ("Hellena\\nPrison").
"""
import collections
import glob
import json
import os
import re
import sys
import unicodedata

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SC = os.environ.get('SC_ROOT', os.path.join(ROOT, 'Severed-Chains'))
SRC = os.path.join(SC, 'src', 'main', 'java')
LOD = os.environ.get('LOD_ROOT', os.path.join(ROOT, '..', 'LOD'))
OUT = os.path.join(ROOT, 'out')
STR = re.compile(r'"((?:[^"\\]|\\.)*)"')
TAG = re.compile(r'\{[0-9A-F]{4}\}')

# (bảng, file, tên mảng hoặc biểu thức tìm, mô tả)
TABLES = [
    ('monster', 'legend/game/combat/Monsters.java', 'monsterNames_80112068', 'ten quai'),
    ('chapter', 'legend/game/SItem.java', 'chapterNames_80114248', 'ten chuong'),
    ('submap', 'legend/game/SItem.java', 'submapNames_8011c108', 'dia danh (menu/luu)'),
    ('worldmap', 'legend/game/SItem.java', 'worldMapNames_8011c1ec', 'vung ban do the gioi'),
    ('ailment', 'legend/game/combat/ui/BattleHud.java', 'ailments_800fb3a0', 'trang thai xau (tran)'),
    ('target', 'legend/game/combat/ui/BattleHud.java', 'targeting_800fb36c', 'muc tieu (tran)'),
    ('service', 'legend/game/wmap/WmapStatics.java', 'services_800f01cc', 'dich vu (ban do the gioi)'),
    ('region', 'legend/game/wmap/WmapStatics.java', 'regions_800f01ec', 'vung'),
    ('menustatus', 'legend/game/SItem.java', 'menuStatus_800fba7c', 'trang thai (menu)'),
]
# Câu viết thẳng trong mã, dịch lúc vẽ (Text.renderText). Phải khớp nguyên văn.
UI_LITERALS = ['Load Game', 'Move?', 'No', 'Yes', 'Enter', "Don't enter", 'No facilities',
               'Hits: %s, damage: %s, SP: %s']   # dòng cuối: mẫu, bản dịch dùng {0} {1} {2}
# Tên riêng (trùm, nhân vật, rồng) giữ tiếng Anh như bản PS1: không báo thiếu
KEEP_EN = {'rose', 'fruegel', 'rodriguez', 'guftas', 'kongol', 'lloyd', 'feyrbrand', 'regole', 'greham', 'shirley', 'shana',
           'albert', 'lenus', 'damia', 'syuveil', 'belzac', 'kanzas', 'mappi', 'gehrich', 'gorgaga', 'serfius', 'danton',
           'atlow', 'jiango', 'urobolus', 'mazo', 'kamuy', 'windigo', 'vector', 'selebus', 'kubila', 'zackwell', 'cleone',
           'claire', 'indora', 'michael', 'zieg_feld', 'melbu_frahma'}


def slug(s):
    return re.sub(r'^_|_$', '', re.sub(r'[^a-z0-9]+', '_', s.lower()))


def java_unescape(s):
    return s.replace('\\n', '\n').replace('\\"', '"').replace("\\'", "'").replace('\\\\', '\\')


def array_strings(path, name):
    s = open(os.path.join(SRC, path), encoding='utf-8').read()
    i = s.index(name)
    j = s.index('};', i)
    return [java_unescape(x) for x in STR.findall(s[i:j])]


def places():
    s = open(os.path.join(SRC, 'legend/game/wmap/WmapStatics.java'), encoding='utf-8').read()
    return [java_unescape(x) for x in re.findall(r'new Place0c\(\s*"((?:[^"\\]|\\.)*)"', s)]


def norm(s):
    s = TAG.sub('', s.replace('{n}', ' ').replace('\n', ' '))
    return re.sub(r'\s+', ' ', s).strip().lower()


def load_lang(path):
    d = {}
    if not os.path.exists(path):
        return d
    for line in open(path, encoding='utf-8'):
        s = line.strip()
        if s and s[0] not in '#!' and '=' in s:
            k, v = s.split('=', 1)
            d[k.strip()] = v.strip()
    return d


def main():
    vi = {}
    for f in sorted(glob.glob(os.path.join(LOD, 'tr', 'vi', '*.json'))):
        vi.update(json.load(open(f, encoding='utf-8')))
    en2vi = collections.defaultdict(list)
    for line in open(os.path.join(LOD, 'tr', 'en', 'menu.tsv'), encoding='utf-8'):
        r = line.rstrip('\n').split('\t')
        if r[0] in vi:
            en2vi[norm(r[-1])].append(unicodedata.normalize('NFC', vi[r[0]]))

    entries = collections.OrderedDict()   # khoá -> (chữ Anh, bảng)
    for tab, path, name, _ in TABLES:
        for x in array_strings(path, name):
            if x.strip():
                entries.setdefault('scvi.%s.%s' % (tab, slug(x)), (x, tab))
    for x in places():
        entries.setdefault('scvi.place.%s' % slug(x), (x, 'place'))
    for x in UI_LITERALS:
        entries.setdefault('scvi.ui.%s' % slug(x), (x, 'ui'))

    manual = load_lang(os.path.join(ROOT, 'tr_sc', 'gop', 'scvi.vi.lang'))
    bad = [k for k in manual if k not in entries]
    if bad:
        print('LOI: khoa dich tay khong co trong bang: %s' % bad, file=sys.stderr)
        sys.exit(1)

    out, missing = {}, []
    stat = collections.Counter()
    for k, (en, tab) in entries.items():
        stat[tab, 'tong'] += 1
        cand = en2vi.get(norm(en), [])
        if k in manual:
            out[k] = manual[k]
            stat[tab, 'tay'] += 1
        elif cand:
            v = cand[0].replace('{n}', '\n')
            v = TAG.sub('', v).strip()
            if tab == 'place' and '\n' not in en:
                v = v.replace('\n', ' ')
            elif tab != 'place':
                v = re.sub(r'\s*\n\s*', ' ', v)
            out[k] = v.replace('\n', '\\n')
            stat[tab, 'ps1'] += 1
        elif not (tab == 'monster' and k.split('.')[-1] in KEEP_EN):
            missing.append((k, en))

    os.makedirs(os.path.join(OUT, 'lang'), exist_ok=True)
    with open(os.path.join(OUT, 'lang', 'scvi.vi.lang'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('# Chuoi viet cung trong ma SC (tools/sc_hardcoded.py: ban dich PS1 D:\\LOD + tr_sc/gop/scvi.vi.lang)\n')
        for k, v in out.items():
            f.write('%s=%s\n' % (k, v))
    with open(os.path.join(OUT, 'hardcoded_missing.tsv'), 'w', encoding='utf-8', newline='\n') as f:
        for k, en in missing:
            f.write('%s\t%s\n' % (k, en.replace('\n', '\\n')))
    for tab in [t[0] for t in TABLES] + ['place', 'ui']:
        print('%-11s %3d muc: %3d tu ban PS1, %3d dich tay' % (tab, stat[tab, 'tong'], stat[tab, 'ps1'], stat[tab, 'tay']))
    print('tong %d khoa, thieu %d (out/hardcoded_missing.tsv)' % (len(entries), len(missing)))


if __name__ == '__main__':
    main()
