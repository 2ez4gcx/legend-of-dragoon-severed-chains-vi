"""Đếm chuỗi tiếng Anh VIẾT CỨNG trong mã Java của Severed Chains (không đi qua .lang, chưa dịch được bằng file).

Cách gọi: python tools/sc_hardcoded.py
In: số mục từng bảng tên đã biết (tên quái, địa danh, chương...) + tổng chuỗi dạng chữ trong các gói UI/trận/bản đồ.
"""
import os
import re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SRC = os.path.join(ROOT, 'Severed-Chains', 'src', 'main', 'java')
STR = re.compile(r'"((?:[^"\\]|\\.)*)"')

TABLES = [
    ('legend/game/combat/Monsters.java', 'monsterNames_80112068', 'ten quai'),
    ('legend/game/SItem.java', 'chapterNames_80114248', 'ten chuong'),
    ('legend/game/SItem.java', 'submapNames_8011c108', 'dia danh (menu/luu)'),
    ('legend/game/SItem.java', 'worldMapNames_8011c1ec', 'vung ban do the gioi'),
    ('legend/game/combat/ui/BattleHud.java', 'ailments_800fb3a0', 'trang thai xau (tran)'),
    ('legend/game/combat/ui/BattleHud.java', 'targeting_800fb36c', 'muc tieu (tran)'),
    ('legend/game/wmap/WmapStatics.java', 'services_800f01cc', 'dich vu (ban do the gioi)'),
    ('legend/game/wmap/WmapStatics.java', 'regions_800f01ec', 'vung'),
]


def array_strings(path, name):
    s = open(os.path.join(SRC, path), encoding='utf-8').read()
    i = s.index(name)
    j = s.index('};', i)
    return STR.findall(s[i:j])


def main():
    total = 0
    for path, name, desc in TABLES:
        a = array_strings(path, name)
        a = [x for x in a if x.strip()]
        total += len(set(a))
        print('%-28s %-24s %4d muc (%d khac nhau) vd: %s' % (name, desc, len(a), len(set(a)), a[:3]))
    s = open(os.path.join(SRC, 'legend/game/wmap/WmapStatics.java'), encoding='utf-8').read()
    places = re.findall(r'new Place0c\(\s*"((?:[^"\\]|\\.)*)"', s)
    total += len(set(places))
    print('%-28s %-24s %4d muc (%d khac nhau) vd: %s' % ('Place0c', 'dia danh ban do the gioi', len(places), len(set(places)), places[:3]))
    print('tong cac bang ten: %d chuoi khac nhau' % total)


if __name__ == '__main__':
    main()
