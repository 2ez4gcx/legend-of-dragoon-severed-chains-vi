"""build_catalog.py — dựng danh mục mô hình v1 (catalog_v1.json) và danh sách cảnh xác minh (verify_scenes.json).

Danh mục chọn mô hình theo ĐƯỜNG DẪN NGUỒN + cấu trúc mong đợi (nobj, tris) — kiến trúc route B, quyết định D12. Khoá
`key_us` (LRMK1, SPEC §3.1) tính bằng bản tham chiếu WP0 `spec/ref_spec.py` trên đĩa US của máy dev, chỉ để tham khảo:
worker luôn tính lại khoá từ đĩa của người chơi. Bảng v1 bên dưới (FIELD, BATTLE, STORY, MONSTER, EXCLUDED) chép từ
danh sách mô hình v1 của kiến trúc (model_inventory.json của bản thiết kế: nhận diện bằng hoạt cảnh dùng chung với 9 mô
hình avatar bản đồ thế giới, khối đỉnh dùng chung và tờ ảnh xem trước).

Cách gọi (từ gốc repo, PYTHONIOENCODING=utf-8; python hệ thống hoặc python.exe -I của Blender):
  python tools/sc_remaster/catalog/build_catalog.py [--game game/files]
      quét game/files (chỉ đọc), kiểm bảng v1, ghi catalog_v1.json + verify_scenes.json cạnh file này, in báo cáo.
      Còn lỗi (kể cả thiếu bảng cut / LodEncounters, mục medium/low không có cảnh hay trận) thì KHÔNG ghi, exit 1.
      --game nhận mọi đường dẫn (kể cả Unicode); bảng cut đọc SUBMAP/NEWROOT.RDT của chính thư mục đó.
  python tools/sc_remaster/catalog/build_catalog.py --check [--game game/files]
      dựng lại trong bộ nhớ và so TỪNG BYTE với hai file đã có; phân giải lại mọi mục của file đã có (mỗi nguồn: file có,
      là mô hình, nobj/tris/khoá khớp); đối chiếu key_us với spec/vectors.json; kiểm nội dung JSON (validate_catalog,
      validate_verify, ref_spec.blob_check + lỗi gieo) chỉ gồm đường dẫn, số đếm, hash, giá trị liệt kê của lược đồ và
      văn bản tiếng Việt. Exit 0 = đạt, 1 = lỗi.
  thêm --report [FILE] (cùng --check): ghi báo cáo phân giải JSON, mặc định
      work/upscale/sc_remaster_c1/resolution.json (chỉ cho phép dưới work/upscale/sc_remaster*, git bỏ qua).

Lược đồ catalog_v1.json (SPEC §3.8): danh sách `[{id, char, form, tier: core|optional, confidence: high|medium|low,
label_vi, sources: [{kind: battle|field|story|monster, model, tim}], expect: {nobj, tris}, key_us}]`.
- Mỗi mục = MỘT khoá hình học (một việc dựng hình học). Các dòng bảng cùng khoá được gộp: ví dụ ô quái 289 (Shana) và
  255 (Rose Dragoon) có cùng khoá với shana/combat và rose/dragoon nên thành nguồn `monster` của hai mục trận đó; hai
  container cảnh chỉ khác bố cục UV gộp thành một mục nhiều nguồn.
- `sources`: mọi cặp (mô hình, TIM) đã thấy cho khoá đó. Trường (field): một nguồn cho mỗi cặp (container đã che header,
  TIM) khác nhau trong mọi cảnh, đại diện = file avatar bản đồ thế giới nếu có, rồi file của bảng v1, rồi cảnh đầu tiên.
  Trận cốt truyện: DRGN0/N + TIM N+1, kèm mọi file DRGN0 0..690 cùng khoá có TIM ở N+1. `model`, `tim` tương đối
  <game>/files. `kind` quyết định cách đặt TIM vào VRAM ảo (SPEC §3.3.7): field = ô sobj 0, còn lại = rect gốc.
- `expect.tris` = số tam giác GL (tam giác + 2 x tứ giác).

verify_scenes.json: các mục độ tin cậy medium/low (phải xác nhận trong game ở I1) với cảnh (số cut cho
tools/sc_dbg.ps1 -Warp, tra bằng tools/sc_cuts.py), trận (chỉ số LodEncounters.LEGACY cho tools/sc_dbg.ps1 -Encounter,
khi biết), và danh sách loại trừ (mô hình giống nhân vật nhưng không thuộc nhóm) kèm lý do — để I1 xác nhận chúng vẫn
retail. Trận của ô quái lấy thẳng từ LodEncounters; trận của mô hình cốt truyện DRGN0/N được truy tĩnh
(inventory.cutscene_story_tables/cutscene_callers): DEFF cảnh cắt trận i có N trong bảng chỉ số file, script quái
DRGN1/<id+1> gọi DEFF i, rồi id quái -> trận (trường deff_cutscenes, story_models, via_vi). Thiếu bản clone
Severed-Chains (LodEncounters.java) hay SUBMAP/NEWROOT.RDT là lỗi: verify_scenes.json không được dựng thiếu.
"""
import argparse
import collections
import io
import json
import os
import re
import struct
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import inventory as inv  # noqa: E402

ref_spec = inv.ref_spec
ROOT = inv.ROOT
CATALOG_PATH = os.path.join(HERE, 'catalog_v1.json')
VERIFY_PATH = os.path.join(HERE, 'verify_scenes.json')
VECTORS_PATH = os.path.join(inv.SPEC_DIR, 'vectors.json')
ENCOUNTERS_JAVA = os.path.join(ROOT, 'Severed-Chains', 'src', 'main', 'java', 'legend', 'lodmod', 'LodEncounters.java')

# ---------------------------------------------------------------- tên hiển thị
NAME = {'dart': 'Dart', 'lavitz': 'Lavitz', 'shana': 'Shana', 'rose': 'Rose', 'haschel': 'Haschel', 'meru': 'Meru',
        'kongol': 'Kongol', 'miranda': 'Miranda', 'albert': 'Albert', 'lavitz|albert': 'Lavitz/Albert',
        'composite': 'Mô hình ghép'}
DRAGOON_VI = {'dart': 'Mắt Đỏ', 'lavitz': 'Ngọc Bích', 'albert': 'Ngọc Bích', 'lavitz|albert': 'Ngọc Bích',
              'shana': 'Bạch Ngân', 'miranda': 'Bạch Ngân', 'rose': 'Bóng Tối', 'haschel': 'Tím', 'meru': 'Biển Xanh',
              'kongol': 'Vàng'}
CHARS = set(NAME)
FORMS = ('field', 'field_dragoon', 'field_child', 'field_composite', 'field_prop', 'battle_combat', 'battle_dragoon',
         'battle_divine_dragoon', 'battle_story', 'battle_story_dragoon', 'battle_enemy')
OPTIONAL_FIELD_FORMS = ('field_child', 'field_composite', 'field_prop')

# ---------------------------------------------------------------- bảng v1
# A + B. Trường + bản đồ thế giới: (char, form, confidence, mô hình đại diện, nobj, tris, mô tả thêm, thay phần "ở đâu")
# Lõi = form field / field_dragoon (78 container); tuỳ chọn = field_child / field_composite / field_prop (7).
FIELD = [
    ('albert', 'field', 'high', 'SECT/DRGN21.BIN/536/99', 22, 256, '', ''),
    ('albert', 'field', 'medium', 'SECT/DRGN21.BIN/110/33', 18, 353, 'bị bắt, cởi trần quỳ', ''),
    ('albert', 'field', 'high', 'SECT/DRGN21.BIN/38/132', 22, 367, '', ''),
    ('albert', 'field', 'high', 'SECT/DRGN22.BIN/1136/165', 22, 367, '', ''),
    ('albert', 'field', 'high', 'SECT/DRGN22.BIN/869/363', 23, 392, 'cầm giáo', ''),
    ('albert', 'field', 'medium', 'SECT/DRGN21.BIN/284/99', 23, 465, 'áo choàng hoàng gia', ''),
    ('albert', 'field', 'high', 'SECT/DRGN21.BIN/329/165', 22, 542, '', ''),
    ('albert', 'field', 'high', 'SECT/DRGN21.BIN/689/330', 23, 567, 'cầm giáo', ''),
    ('albert', 'field_dragoon', 'medium', 'SECT/DRGN23.BIN/488/66', 28, 567, '', ''),
    ('dart', 'field', 'high', 'SECT/DRGN21.BIN/41/0', 15, 247, '', ''),
    ('dart', 'field', 'high', 'SECT/DRGN22.BIN/809/0', 15, 318, '', ''),
    ('dart', 'field', 'high', 'SECT/DRGN21.BIN/50/0', 15, 332, '', ''),
    ('dart', 'field', 'high', 'SECT/DRGN22.BIN/686/0', 15, 336, '', ''),
    ('dart', 'field', 'high', 'SECT/DRGN21.BIN/50/330', 15, 356, '', ''),
    ('dart', 'field', 'high', 'SECT/DRGN21.BIN/8/0', 15, 468, '', ''),
    ('dart', 'field', 'high', 'SECT/DRGN21.BIN/416/0', 15, 468, '', ''),
    ('dart', 'field', 'high', 'SECT/DRGN21.BIN/5/0', 15, 484, '', ''),
    ('dart', 'field', 'high', 'SECT/DRGN21.BIN/35/231', 15, 502, '', ''),
    ('dart', 'field', 'high', 'SECT/DRGN21.BIN/128/33', 16, 534, 'rút kiếm', ''),
    ('dart', 'field', 'high', 'SECT/DRGN21.BIN/20/0', 15, 855, 'nhiều đa giác', ''),
    ('dart', 'field', 'high', 'SECT/DRGN21.BIN/716/198', 15, 873, '', ''),
    ('dart', 'field', 'medium', 'SECT/DRGN24.BIN/788/0', 16, 951, 'đĩa 4, áo nâu', ''),
    ('dart', 'field_dragoon', 'high', 'SECT/DRGN21.BIN/17/0', 28, 583, '', ''),
    ('dart', 'field_dragoon', 'high', 'SECT/DRGN21.BIN/5/33', 28, 583, '', ''),
    ('haschel', 'field', 'high', 'SECT/DRGN21.BIN/452/132', 15, 252, '', ''),
    ('haschel', 'field', 'high', 'SECT/DRGN22.BIN/923/165', 15, 323, '', ''),
    ('haschel', 'field', 'high', 'SECT/DRGN21.BIN/38/66', 15, 327, '', ''),
    ('haschel', 'field', 'high', 'SECT/DRGN22.BIN/809/165', 15, 461, '', ''),
    ('haschel', 'field', 'high', 'SECT/DRGN24.BIN/866/0', 15, 461, '', ''),
    ('haschel', 'field', 'high', 'SECT/DRGN21.BIN/95/132', 15, 461, '', ''),
    ('haschel', 'field_dragoon', 'medium', 'SECT/DRGN23.BIN/491/66', 25, 524, '', ''),
    ('kongol', 'field', 'high', 'SECT/DRGN21.BIN/428/297', 17, 375, '', ''),
    ('kongol', 'field', 'high', 'SECT/DRGN22.BIN/809/198', 17, 510, '', ''),
    ('kongol', 'field', 'high', 'SECT/DRGN21.BIN/686/231', 17, 510, '', ''),
    ('kongol', 'field', 'high', 'SECT/DRGN21.BIN/341/66', 18, 552, 'cầm rìu', ''),
    ('kongol', 'field', 'high', 'SECT/DRGN21.BIN/686/165', 17, 645, '', ''),
    ('kongol', 'field', 'high', 'SECT/DRGN24.BIN/746/99', 17, 659, '', ''),
    ('kongol', 'field_dragoon', 'medium', 'SECT/DRGN23.BIN/494/66', 28, 554, '', ''),
    ('lavitz', 'field', 'high', 'SECT/DRGN21.BIN/50/66', 15, 327, '', ''),
    ('lavitz', 'field', 'high', 'SECT/DRGN21.BIN/50/363', 16, 352, 'cầm giáo', ''),
    ('lavitz', 'field', 'high', 'SECT/DRGN21.BIN/26/99', 15, 448, '', ''),
    ('lavitz', 'field', 'high', 'SECT/DRGN21.BIN/47/66', 16, 473, 'cầm giáo', ''),
    ('lavitz|albert', 'field_dragoon', 'medium', 'SECT/DRGN21.BIN/677/330', 29, 631, 'cầm giáo', ''),
    ('meru', 'field', 'high', 'SECT/DRGN22.BIN/968/66', 27, 303, '', ''),
    ('meru', 'field', 'medium', 'SECT/DRGN24.BIN/455/99', 17, 396, 'váy, đĩa 4', ''),
    ('meru', 'field', 'high', 'SECT/DRGN24.BIN/497/99', 27, 411, '', ''),
    ('meru', 'field', 'high', 'SECT/DRGN22.BIN/641/198', 27, 411, '', ''),
    ('meru', 'field', 'high', 'SECT/DRGN22.BIN/686/99', 27, 419, '', ''),
    ('meru', 'field', 'medium', 'SECT/DRGN24.BIN/854/0', 18, 432, 'váy, đĩa 4', ''),
    ('meru', 'field', 'high', 'SECT/DRGN24.BIN/614/132', 29, 439, 'cánh Wingly mở', ''),
    ('meru', 'field', 'high', 'SECT/DRGN22.BIN/755/33', 27, 541, '', ''),
    ('meru', 'field', 'high', 'SECT/DRGN22.BIN/809/66', 27, 541, '', ''),
    ('meru', 'field', 'high', 'SECT/DRGN23.BIN/221/132', 29, 561, 'cánh Wingly mở', ''),
    ('meru', 'field', 'high', 'SECT/DRGN22.BIN/755/264', 28, 579, 'cầm búa', ''),
    ('meru', 'field_dragoon', 'medium', 'SECT/DRGN23.BIN/485/66', 27, 512, '', ''),
    ('meru', 'field_dragoon', 'medium', 'SECT/DRGN22.BIN/980/165', 27, 580, '', ''),
    ('miranda', 'field', 'high', 'SECT/DRGN23.BIN/71/33', 15, 233, '', ''),
    ('miranda', 'field', 'high', 'SECT/DRGN22.BIN/689/132', 15, 354, '', ''),
    ('miranda', 'field', 'high', 'SECT/DRGN24.BIN/848/0', 15, 504, '', ''),
    ('miranda', 'field', 'high', 'SECT/DRGN23.BIN/50/66', 15, 504, '', ''),
    ('miranda', 'field', 'high', 'SECT/DRGN23.BIN/230/132', 18, 518, 'cầm cung', ''),
    ('miranda', 'field_dragoon', 'medium', 'SECT/DRGN23.BIN/167/396', 43, 481, '', ''),
    ('rose', 'field', 'high', 'SECT/DRGN21.BIN/368/99', 17, 262, '', ''),
    ('rose', 'field', 'high', 'SECT/DRGN22.BIN/809/99', 17, 349, '', ''),
    ('rose', 'field', 'high', 'SECT/DRGN21.BIN/38/99', 17, 350, '', ''),
    ('rose', 'field', 'high', 'SECT/DRGN21.BIN/98/396', 18, 372, 'cầm kiếm', ''),
    ('rose', 'field', 'high', 'SECT/DRGN21.BIN/14/0', 17, 485, '', ''),
    ('rose', 'field', 'high', 'SECT/DRGN21.BIN/95/198', 18, 507, 'cầm kiếm', ''),
    ('rose', 'field_dragoon', 'medium', 'SECT/DRGN24.BIN/758/363', 30, 533, 'đĩa 4', ''),
    ('rose', 'field_dragoon', 'medium', 'SECT/DRGN21.BIN/713/99', 31, 605, '', 'Quái Vật Đen (dạng tối có cánh) ngoài cảnh'),
    ('shana', 'field', 'high', 'SECT/DRGN21.BIN/41/363', 15, 250, '', ''),
    ('shana', 'field', 'high', 'SECT/DRGN22.BIN/809/33', 15, 324, '', ''),
    ('shana', 'field', 'high', 'SECT/DRGN21.BIN/26/66', 15, 326, '', ''),
    ('shana', 'field', 'high', 'SECT/DRGN24.BIN/875/33', 15, 464, '', ''),
    ('shana', 'field', 'medium', 'SECT/DRGN24.BIN/698/33', 15, 488, 'quỳ, đoạn kết', ''),
    ('shana', 'field', 'high', 'SECT/DRGN21.BIN/11/0', 15, 490, '', ''),
    ('shana', 'field', 'high', 'SECT/DRGN21.BIN/86/165', 15, 490, '', ''),
    ('shana', 'field', 'high', 'SECT/DRGN21.BIN/86/297', 17, 510, 'cầm cung', ''),
    # B. tuỳ chọn
    ('composite', 'field_composite', 'high', 'SECT/DRGN21.BIN/338/165', 30, 974, 'Dart + Shana trong một TMD', ''),
    ('composite', 'field_composite', 'high', 'SECT/DRGN22.BIN/971/231', 32, 681, 'Dart + Rose trong một TMD', ''),
    ('composite', 'field_composite', 'medium', 'SECT/DRGN22.BIN/800/132', 32, 577, 'Haschel + một NPC', ''),
    ('composite', 'field_composite', 'low', 'SECT/DRGN21.BIN/173/165', 48, 1368, 'Shana + ngựa + người cưỡi', ''),
    ('dart', 'field_child', 'medium', 'SECT/DRGN21.BIN/731/0', 17, 734, '', ''),
    ('kongol', 'field_child', 'medium', 'SECT/DRGN24.BIN/740/396', 17, 428, '', ''),
    ('meru', 'field_prop', 'low', 'SECT/DRGN23.BIN/59/231', 2, 20, 'cánh', ''),
]

# CharacterTemplate.loadWorldMapModel (Severed-Chains/src/main/java/legend/lodmod/characters/*Template.java):
# 9 avatar bản đồ thế giới — trùng byte với container cảnh (WMap.java:949 'WmapEntityModel (index 0)').
WMAP_REFS = {
    'dart': ('SECT/DRGN21.BIN/101/0', 'SECT/DRGN21.BIN/101/textures/0'),
    'lavitz': ('SECT/DRGN21.BIN/119/99', 'SECT/DRGN21.BIN/119/textures/3'),
    'shana': ('SECT/DRGN21.BIN/119/66', 'SECT/DRGN21.BIN/119/textures/2'),
    'rose': ('SECT/DRGN21.BIN/335/132', 'SECT/DRGN21.BIN/335/textures/4'),
    'haschel': ('SECT/DRGN22.BIN/800/33', 'SECT/DRGN22.BIN/800/textures/1'),
    'meru': ('SECT/DRGN22.BIN/755/33', 'SECT/DRGN22.BIN/755/textures/1'),
    'kongol': ('SECT/DRGN22.BIN/800/66', 'SECT/DRGN22.BIN/800/textures/2'),
    'miranda': ('SECT/DRGN23.BIN/116/33', 'SECT/DRGN23.BIN/116/textures/1'),
    'albert': ('SECT/DRGN21.BIN/554/66', 'SECT/DRGN21.BIN/554/textures/2'),
}

# C. Trận, mô hình gốc: (thư mục nhân vật, form thư mục, char, form, nobj, tris) — characters/<c>/models/<f>/32 + textures/<f>
BATTLE = [
    ('dart', 'combat', 'dart', 'battle_combat', 17, 870),
    ('dart', 'dragoon', 'dart', 'battle_dragoon', 29, 1005),
    ('lavitz', 'combat', 'lavitz', 'battle_combat', 16, 890),
    ('lavitz', 'dragoon', 'lavitz', 'battle_dragoon', 29, 952),
    ('shana', 'combat', 'shana', 'battle_combat', 20, 891),
    ('shana', 'dragoon', 'shana', 'battle_dragoon', 31, 941),
    ('rose', 'combat', 'rose', 'battle_combat', 19, 807),
    ('rose', 'dragoon', 'rose', 'battle_dragoon', 32, 887),
    ('haschel', 'combat', 'haschel', 'battle_combat', 17, 791),
    ('haschel', 'dragoon', 'haschel', 'battle_dragoon', 25, 820),
    ('meru', 'combat', 'meru', 'battle_combat', 22, 806),
    ('meru', 'dragoon', 'meru', 'battle_dragoon', 29, 875),
    ('kongol', 'combat', 'kongol', 'battle_combat', 18, 795),
    ('kongol', 'dragoon', 'kongol', 'battle_dragoon', 31, 894),
    ('miranda', 'combat', 'miranda', 'battle_combat', 19, 809),
    ('miranda', 'dragoon', 'miranda', 'battle_dragoon', 31, 855),
    ('albert', 'combat', 'albert', 'battle_combat', 21, 866),
    ('albert', 'dragoon', 'albert', 'battle_dragoon', 29, 958),
    ('divine', 'dragoon', 'dart', 'battle_divine_dragoon', 17, 865),
]

# D. Trận, bản cốt truyện DRGN0 (mô hình N, TIM N+1): (N, char, form, confidence, tier, nobj, tris, mô tả thêm)
STORY = [
    (0, 'dart', 'battle_story', 'high', 'core', 17, 875, ''),
    (60, 'albert', 'battle_story', 'high', 'core', 21, 874, ''),
    (169, 'albert', 'battle_story', 'high', 'core', 21, 874, ''),
    (287, 'albert', 'battle_story', 'medium', 'core', 21, 876, 'áo choàng, cầm giáo'),
    (133, 'miranda', 'battle_story', 'medium', 'core', 19, 803, 'cầm cung'),
    (337, 'kongol', 'battle_story', 'high', 'core', 18, 795, ''),
    (468, 'kongol', 'battle_story', 'medium', 'core', 18, 797, ''),
    (324, 'dart', 'battle_story_dragoon', 'medium', 'core', 29, 1001, ''),
    (505, 'lavitz|albert', 'battle_story_dragoon', 'medium', 'core', 29, 950, ''),
    (539, 'albert', 'battle_story', 'low', 'optional', 14, 781, 'bị bắt, cởi trần quỳ'),
    (549, 'albert', 'battle_story', 'low', 'optional', 18, 773, 'bị bắt, biến thể của DRGN0/539'),
]

# E. Nhân vật trong ô quái: (id quái, char, form, confidence, tier, nobj, tris, mô tả thêm). 289 / 255 trùng khoá với
# shana/combat và rose/dragoon nên được gộp làm nguồn 'monster' của hai mục trận đó.
MONSTER = [
    (265, 'kongol', 'battle_enemy', 'medium', 'core', 18, 795, 'trùm Kongol'),
    (289, 'shana', 'battle_combat', 'high', 'core', 20, 891, ''),
    (255, 'rose', 'battle_dragoon', 'high', 'core', 32, 887, ''),
]

# F. Loại trừ (giống nhân vật nhưng không thuộc nhóm): (kind, mô hình, TIM, lý do)
EXCLUDED = [
    ('field', 'SECT/DRGN23.BIN/416/396', 'SECT/DRGN23.BIN/416/textures/12',
     'Zieg giáp đỏ — dùng chung bộ phận với Dart nhưng là NPC'),
    ('field', 'SECT/DRGN24.BIN/965/33', 'SECT/DRGN24.BIN/965/textures/1', 'Zieg (cùng dạng với mô hình Zieg giáp đỏ)'),
    ('field', 'SECT/DRGN21.BIN/731/33', 'SECT/DRGN21.BIN/731/textures/1', 'Zieg áo lông (hồi tưởng ở Neet)'),
    ('field', 'SECT/DRGN22.BIN/713/33', 'SECT/DRGN22.BIN/713/textures/1',
     'Lenus (có cánh, cùng cảnh với Dragoon Biển Xanh) — không thuộc nhóm'),
    ('field', 'SECT/DRGN21.BIN/29/0', 'SECT/DRGN21.BIN/29/textures/0', 'NPC dùng chung bộ phận với một NPC khác'),
    ('field', 'SECT/DRGN21.BIN/23/132', 'SECT/DRGN21.BIN/23/textures/4', 'bé gái làng Seles (NPC)'),
    ('story', 'SECT/DRGN0.BIN/157', 'SECT/DRGN0.BIN/158',
     'Dragoon Mắt Đỏ dùng chung TIM với ô quái 387 — nhiều khả năng là Zieg, không phải Dart'),
    ('monster', 'SECT/DRGN0.BIN/3524/32', 'monsters/387/textures/combat',
     'Dragoon Mắt Đỏ ở ô quái 387 — nhiều khả năng là Zieg'),
    ('monster', 'SECT/DRGN0.BIN/3424/32', 'monsters/287/textures/combat', 'Dragoon đối địch (ô quái 287)'),
    ('monster', 'SECT/DRGN0.BIN/3431/32', 'monsters/294/textures/combat', 'Dragoon đối địch (ô quái 294)'),
    ('monster', 'SECT/DRGN0.BIN/3432/32', 'monsters/295/textures/combat', 'Dragoon đối địch (ô quái 295)'),
    ('monster', 'SECT/DRGN0.BIN/3433/32', 'monsters/296/textures/combat', 'Dragoon đối địch (ô quái 296)'),
    ('monster', 'SECT/DRGN0.BIN/3434/32', 'monsters/297/textures/combat', 'Dragoon đối địch (ô quái 297)'),
    ('monster', 'SECT/DRGN0.BIN/3435/32', 'monsters/298/textures/combat', 'Dragoon đối địch (ô quái 298)'),
]

# Điều cần nhìn khi xác minh các mục medium/low (khoá = mô hình đại diện của dòng bảng).
CHECK_VI = {
    'SECT/DRGN21.BIN/110/33': 'Albert bị bắt, cởi trần, quỳ (8/18 phần chung với Albert) — đúng là Albert?',
    'SECT/DRGN21.BIN/284/99': 'Albert mặc áo choàng hoàng gia (3 phần chung với Albert) — đúng là Albert?',
    'SECT/DRGN23.BIN/488/66': 'Dragoon Ngọc Bích của Albert trong cảnh các Dragoon xếp hàng (đĩa 3).',
    'SECT/DRGN24.BIN/788/0': 'Dart áo nâu ở đĩa 4 (15/16 phần chung với Dart) — đúng là Dart?',
    'SECT/DRGN23.BIN/491/66': 'Dragoon Tím của Haschel trong cảnh các Dragoon xếp hàng (đĩa 3).',
    'SECT/DRGN23.BIN/494/66': 'Dragoon Vàng của Kongol (92 gói trong mờ) trong cảnh các Dragoon xếp hàng (đĩa 3).',
    'SECT/DRGN21.BIN/677/330': 'Dragoon Ngọc Bích cầm giáo — là Lavitz hay Albert? (thân chung với Dragoon Mắt Đỏ / '
                               'Ngọc Bích của Albert)',
    'SECT/DRGN24.BIN/455/99': 'Meru mặc váy ở đĩa 4 (có hoạt cảnh texture) — đúng là Meru?',
    'SECT/DRGN24.BIN/854/0': 'Meru mặc váy ở đĩa 4 (có hoạt cảnh texture) — đúng là Meru?',
    'SECT/DRGN23.BIN/485/66': 'Dragoon Biển Xanh của Meru (nhận diện bằng mắt).',
    'SECT/DRGN22.BIN/980/165': 'Dragoon Biển Xanh của Meru, 2 TIM (đổi bảng màu) — cùng cảnh với Lenus.',
    'SECT/DRGN23.BIN/167/396': 'Dragoon Bạch Ngân của Miranda, 43 phần, có hoạt cảnh texture (nhận diện bằng mắt).',
    'SECT/DRGN24.BIN/758/363': 'Dragoon Bóng Tối của Rose ở đĩa 4 (thân Dragoon nữ dùng chung).',
    'SECT/DRGN21.BIN/713/99': 'Rose dạng "Quái Vật Đen" tối có cánh (377 gói trong mờ, hoạt cảnh texture) — đúng là Rose?',
    'SECT/DRGN24.BIN/698/33': 'Shana quỳ ở đoạn kết (đĩa 4), phần chung với Shana.',
    'SECT/DRGN22.BIN/800/132': 'Mô hình ghép Haschel + một NPC trong một TMD.',
    'SECT/DRGN21.BIN/173/165': 'Mô hình ghép 48 phần: phần của Shana + ngựa + người cưỡi — có đáng làm không?',
    'SECT/DRGN21.BIN/731/0': 'Dart lúc nhỏ (hồi tưởng ở Neet, cùng cảnh với Zieg áo lông).',
    'SECT/DRGN24.BIN/740/396': 'Kongol lúc nhỏ (đĩa 4).',
    'SECT/DRGN23.BIN/59/231': 'Đạo cụ cánh 2 phần dùng chung khối đỉnh với Meru (hoạt cảnh texture) — có hiện ra không?',
    'story:287': 'Albert khoác áo choàng, cầm giáo, TIM riêng.',
    'story:133': 'Miranda cầm cung, TIM riêng (19 phần, 803 tam giác; bản trận thường 809).',
    'story:468': 'Kongol, TIM riêng; 12 mặt 8bpp đọc ngoài TIM (faceHash 0, mặt LIVE d) — kiểm không sai màu.',
    'story:324': 'Dragoon Mắt Đỏ bản cốt truyện (1001 tam giác; bản trận thường 1005), TIM riêng.',
    'story:505': 'Dragoon Ngọc Bích bản cốt truyện (950 tam giác), TIM riêng — Lavitz hay Albert?',
    'story:539': 'Albert bị bắt, cởi trần quỳ (khớp mô hình cảnh Albert bị bắt).',
    'story:549': 'Albert bị bắt, biến thể của DRGN0/539.',
    'monster:265': 'Trùm Kongol (ô quái 265): TIM trùng kongol/combat, TMD khác Kongol của nhóm.',
}
# Mục cốt truyện liên quan tới một mô hình cảnh (theo ghi chú thiết kế) -> cảnh gợi ý.
RELATED_FIELD = {539: 'SECT/DRGN21.BIN/110/33', 549: 'SECT/DRGN21.BIN/110/33'}


# ---------------------------------------------------------------- nhãn
def label_vi(char, form, nobj, tris, extra='', where='', n=None, mid=None, wmap=False):
    name = NAME[char]
    if where:
        what = where
    elif form == 'field':
        what = 'ngoài cảnh'
    elif form == 'field_dragoon':
        what = 'Dragoon %s ngoài cảnh' % DRAGOON_VI[char]
    elif form == 'field_child':
        what = 'lúc nhỏ, ngoài cảnh'
    elif form == 'field_composite':
        what = 'ngoài cảnh'
    elif form == 'field_prop':
        what = 'đạo cụ ngoài cảnh'
    elif form == 'battle_combat':
        what = 'trong trận'
    elif form == 'battle_dragoon':
        what = 'Dragoon %s trong trận' % DRAGOON_VI[char]
    elif form == 'battle_divine_dragoon':
        what = 'Dragoon Thần Long trong trận'
    elif form == 'battle_story':
        what = 'trong trận, bản cốt truyện DRGN0/%d' % n
    elif form == 'battle_story_dragoon':
        what = 'Dragoon %s trong trận, bản cốt truyện DRGN0/%d' % (DRAGOON_VI[char], n)
    elif form == 'battle_enemy':
        what = 'trong trận, ô quái %d' % mid
    else:
        raise ValueError(form)
    s = '%s — %s' % (name, what)
    if extra:
        s += ' (%s)' % extra
    s += ', %d phần, %d tam giác' % (nobj, tris)
    if wmap:
        s += '; cũng là avatar bản đồ thế giới'
    return s


# ---------------------------------------------------------------- dựng
class Built:
    def __init__(self):
        self.catalog = []
        self.verify = None
        self.errors = []
        self.warnings = []
        self.report = []
        self.paths_by_id = {}      # id -> mọi đường dẫn mô hình mang khoá đó (để đối chiếu vectors.json)
        self.resolution = []
        self.tim_counts = []       # số TIM khác nhau (theo nội dung) mỗi mục ~ cận trên số biến thể


def _err(b, msg):
    b.errors.append(msg)


def build(game):
    b = Built()
    recs, ferrs = inv.scan_field(game)
    b.report.append('quet canh: %d doi tuong, %d container (che header), %d loi doc (bo qua)' % (
        len(recs), len({r['sha1_norm'] for r in recs}), len(ferrs)))
    # khoá cho mọi container cảnh (theo nội dung file)
    key_by_sha = {}
    nokey = set()
    for r in recs:
        if r['sha1_file'] not in key_by_sha:
            try:
                key_by_sha[r['sha1_file']] = inv.model_key(game, r['model'])
            except (ValueError, ref_spec.SpecError) as e:
                key_by_sha[r['sha1_file']] = None      # SC không dựng được (ref_spec từ chối) -> không là ứng viên
                nokey.add('%s: %s' % (r['model'], e))
    if nokey:
        b.report.append('container canh khong co khoa LRMK1 (ref_spec tu choi): %d' % len(nokey))
    rec_by_model = {}
    for r in recs:
        rec_by_model.setdefault(r['model'], r)
    recs_by_key = collections.defaultdict(list)
    for r in recs:
        k = key_by_sha[r['sha1_file']]
        if k is not None:
            recs_by_key[k['key']].append(r)
    story = inv.story_models(game)
    story_by_key = collections.defaultdict(list)
    for s in story:
        story_by_key[s['key']].append(s)

    # ---- các dòng bảng -> (khoá, mô tả dòng)
    rows = []   # dict(kind, char, form, conf, tier, model, tim, nobj, tris, extra, where, n, mid, key)

    def keyed(rel):
        if not inv.exists(game, rel):
            _err(b, '%s: khong co file' % rel)
            return None
        try:
            return inv.model_key(game, rel)
        except (ValueError, ref_spec.SpecError) as e:
            _err(b, '%s: %s' % (rel, e))
            return None

    for char, form, conf, path, nobj, tris, extra, where in FIELD:
        r = rec_by_model.get(path)
        if r is None or key_by_sha[r['sha1_file']] is None:
            _err(b, '%s: khong phai mo hinh doi tuong canh nao (hoac khong co khoa)' % path)
            continue
        k = key_by_sha[r['sha1_file']]
        tier = 'optional' if form in OPTIONAL_FIELD_FORMS else 'core'
        rows.append(dict(kind='field', char=char, form=form, conf=conf, tier=tier, model=path, tim=r['texture'],
                         nobj=nobj, tris=tris, extra=extra, where=where, n=None, mid=None, k=k))
    for cdir, fdir, char, form, nobj, tris in BATTLE:
        m = 'characters/%s/models/%s/32' % (cdir, fdir)
        t = 'characters/%s/textures/%s' % (cdir, fdir)
        k = keyed(m)
        if k:
            rows.append(dict(kind='battle', char=char, form=form, conf='high', tier='core', model=m, tim=t, nobj=nobj,
                             tris=tris, extra='', where='', n=None, mid=None, k=k))
    for n, char, form, conf, tier, nobj, tris, extra in STORY:
        m, t = 'SECT/DRGN0.BIN/%d' % n, 'SECT/DRGN0.BIN/%d' % (n + 1)
        k = keyed(m)
        if k:
            rows.append(dict(kind='story', char=char, form=form, conf=conf, tier=tier, model=m, tim=t, nobj=nobj,
                             tris=tris, extra=extra, where='', n=n, mid=None, k=k))
    for mid, char, form, conf, tier, nobj, tris, extra in MONSTER:
        mt = inv.monster_model(game, mid)
        if mt is None:
            _err(b, 'o quai %d: khong co mo hinh/TIM' % mid)
            continue
        k = keyed(mt[0])
        if k:
            rows.append(dict(kind='monster', char=char, form=form, conf=conf, tier=tier, model=mt[0], tim=mt[1],
                             nobj=nobj, tris=tris, extra=extra, where='', n=None, mid=mid, k=k))
    for row in rows:
        k = row['k']
        if (k['nobj'], k['tris']) != (row['nobj'], row['tris']):
            _err(b, '%s: du lieu %dp/%dt != bang v1 %dp/%dt' % (row['model'], k['nobj'], k['tris'], row['nobj'], row['tris']))
        if row['tim'] is None or inv.parse_tim_info(inv.read_file(game, row['tim'])) is None:
            _err(b, '%s: TIM %s khong doc duoc' % (row['model'], row['tim']))

    # ---- gộp theo khoá (dòng đầu theo thứ tự bảng quyết định char/form/tier/confidence/nhãn)
    groups = collections.OrderedDict()
    for row in rows:
        groups.setdefault(row['k']['key'], []).append(row)
    wmap_model = {}
    for ch, (m, t) in WMAP_REFS.items():
        r = rec_by_model.get(m)
        if r is None or r['texture'] != t:
            _err(b, 'avatar ban do the gioi %s: %s/%s khong khop doi tuong canh' % (ch, m, t))
            continue
        wmap_model[m] = ch

    ids = collections.Counter()
    used_ids = set()
    for key, grp in groups.items():
        head = grp[0]
        for other in grp[1:]:
            if other['char'] != head['char']:
                _err(b, 'khoa %s gop hai nhan vat: %s / %s' % (key[:12], head['model'], other['model']))
            if other['kind'] == head['kind'] and other['kind'] != 'field':
                _err(b, 'khoa %s: hai dong cung loai %s' % (key[:12], other['kind']))
            b.report.append('gop: %s -> cung khoa %s voi %s' % (other['model'], key[:12], head['model']))
        sources = []
        all_models = set()
        # nguồn field: một cặp (container che header, TIM) -> một nguồn
        frecs = recs_by_key.get(key, [])
        row_models = {g['model'] for g in grp if g['kind'] == 'field'}
        pairs = collections.OrderedDict()
        notex = 0
        for r in sorted(frecs, key=lambda x: (x['disc'], x['scene_dir'], x['obj'])):
            all_models.add(r['model'])
            if r['texture'] is None:
                notex += 1
                continue
            pairs.setdefault((r['sha1_norm'], r['tim']['sha1']), []).append(r)
        if notex:
            b.warnings.append('%s: %d doi tuong canh khong co TIM (bo qua)' % (head['model'], notex))
        classified = {rec_by_model[m]['sha1_norm'] for m in row_models}
        reps = []
        wm = False
        for (norm, _tsha), rs in pairs.items():
            rep = next((r for r in rs if r['model'] in wmap_model), None)
            if rep is not None:
                wm = True
            rep = rep or next((r for r in rs if r['model'] in row_models), None) or rs[0]
            reps.append(rep)
            if norm not in classified:
                b.report.append('khoa %s: them container chua phan loai %s (cung khoa, khac UV/header)' % (
                    key[:12], rep['model']))
        first = [r for r in reps if r['model'] in row_models]
        rest = sorted((r for r in reps if r['model'] not in row_models), key=lambda r: (inv.natkey(r['model']), inv.natkey(r['texture'])))
        for r in first + rest:
            sources.append(dict(kind='field', model=r['model'], tim=r['texture']))
        # nguồn trận / cốt truyện / quái của các dòng bảng
        for g in grp:
            if g['kind'] != 'field':
                src = dict(kind=g['kind'], model=g['model'], tim=g['tim'])
                if src not in sources:
                    sources.append(src)
                all_models.add(g['model'])
        # bản sao DRGN0 0..690 cùng khoá (TIM ở N+1)
        for s in story_by_key.get(key, []):
            src = dict(kind='story', model=s['model'], tim=s['tim'])
            all_models.add(s['model'])
            if src not in sources:
                sources.append(src)
        tims = set()
        for s in sources:
            tims.add(inv.sha1(inv.read_file(game, s['tim'])))
        b.tim_counts.append(len(tims))
        if len(tims) > 4:
            b.warnings.append('%s: %d TIM khac nhau (> 4 bien the toi da, P4 phai chon)' % (head['model'], len(tims)))
        k = head['k']
        cid = '%s.%s' % (head['char'].replace('|', '-'), head['form'])
        if head['kind'] == 'field':
            cid += '.%dp%dt' % (k['nobj'], k['tris'])
        elif head['kind'] == 'story':
            cid += '.drgn0-%d' % head['n']
        elif head['kind'] == 'monster':
            cid += '.monster-%d' % head['mid']
        ids[cid] += 1
        if ids[cid] > 1 or cid in used_ids:
            cid = '%s-%d' % (cid, ids[cid])
        used_ids.add(cid)
        entry = collections.OrderedDict()
        entry['id'] = cid
        entry['char'] = head['char']
        entry['form'] = head['form']
        entry['tier'] = head['tier']
        entry['confidence'] = head['conf']
        entry['label_vi'] = label_vi(head['char'], head['form'], k['nobj'], k['tris'], head['extra'], head['where'],
                                     head['n'], head['mid'], wm)
        entry['sources'] = sources
        entry['expect'] = collections.OrderedDict([('nobj', k['nobj']), ('tris', k['tris'])])
        entry['key_us'] = key
        b.catalog.append(entry)
        b.paths_by_id[cid] = all_models
        entry_meta = dict(head=head, grp=grp, frecs=frecs)
        b.resolution.append((entry, entry_meta))

    # ---- avatar bản đồ thế giới phải nằm trong danh mục
    cat_models = {s['model']: e for e in b.catalog for s in e['sources']}
    for m, ch in wmap_model.items():
        e = cat_models.get(m)
        if e is None or e['char'] != ch:
            _err(b, 'avatar ban do the gioi %s (%s) khong la nguon cua muc %s nao' % (ch, m, ch))
    # ---- loại trừ: khoá không được trùng mục nào
    cat_keys = {e['key_us']: e['id'] for e in b.catalog}
    excluded = []
    for kind, m, t, reason in EXCLUDED:
        k = keyed(m)
        if not k:
            continue
        if k['key'] in cat_keys:
            _err(b, 'loai tru %s trung khoa voi muc %s' % (m, cat_keys[k['key']]))
        if inv.parse_tim_info(inv.read_file(game, t)) is None:
            _err(b, 'loai tru %s: TIM %s khong doc duoc' % (m, t))
        excluded.append(dict(kind=kind, model=m, tim=t, key=k['key'], nobj=k['nobj'], tris=k['tris'], reason=reason,
                             recs=recs_by_key.get(k['key'], []) if kind == 'field' else []))
    # ---- số đếm
    core_field = sum(1 for row in rows if row['kind'] == 'field' and row['tier'] == 'core')
    opt_field = sum(1 for row in rows if row['kind'] == 'field' and row['tier'] == 'optional')
    if (core_field, opt_field) != (78, 7):
        _err(b, 'so container canh %d loi + %d tuy chon != 78 + 7' % (core_field, opt_field))
    if len([r for r in rows if r['kind'] == 'battle']) != 19 or len([r for r in rows if r['kind'] == 'story']) != 11 \
            or len([r for r in rows if r['kind'] == 'monster']) != 3:
        _err(b, 'so dong tran/cot truyen/quai khac 19/11/3')
    b.report.append('dong bang v1: %d canh loi + %d canh tuy chon, %d tran, %d cot truyen, %d o quai' % (
        core_field, opt_field, len([r for r in rows if r['kind'] == 'battle']),
        len([r for r in rows if r['kind'] == 'story']), len([r for r in rows if r['kind'] == 'monster'])))
    tiers = collections.Counter(e['tier'] for e in b.catalog)
    b.report.append('muc danh muc (= khoa hinh hoc): %d (loi %d, tuy chon %d); nguon: %d' % (
        len(b.catalog), tiers['core'], tiers['optional'], sum(len(e['sources']) for e in b.catalog)))
    b.report.append('TIM khac nhau theo noi dung: tong %d, toi da %d moi muc (gioi han bien the 4)' % (
        sum(b.tim_counts), max(b.tim_counts)))
    b.verify = build_verify(game, b, recs, excluded)
    return b


# ---------------------------------------------------------------- cảnh xác minh
def parse_encounters(path=ENCOUNTERS_JAVA):
    """LodEncounters.java -> {id quái: [(chỉ số LEGACY, tên)]}; {} nếu không có bản clone Severed-Chains."""
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as f:
        t = f.read()
    mons = {}
    for m in re.finditer(r'register\("([a-z0-9_]+)",\s*\(\)\s*->\s*new\s+\w+\((.*?)\)\);\s*$', t, re.M):
        mons[m.group(1)] = sorted({int(x) for x in re.findall(r'Monster\((\d+),', m.group(2))})
    leg = re.search(r'LEGACY\s*=\s*\{(.*?)\};', t, re.S)
    names = re.findall(r'"([a-z0-9_]+)"', leg.group(1)) if leg else []
    out = collections.defaultdict(list)
    for i, name in enumerate(names):
        for mid in mons.get(name, []):
            out[mid].append((i, name))
    return out


def cut_table(game):
    """Bảng cut của tools/sc_cuts.py (SUBMAP/NEWROOT.RDT) cho <game> bất kỳ (kể cả đường dẫn Unicode, thư mục không tên
    game/files); None nếu không đọc được.

    sc_cuts.cut_table() luôn mở <ROOT>/game/files/SUBMAP/NEWROOT.RDT: chạy nguyên hàm đó nhưng đặt tạm một hàm `open`
    vào không gian tên của module (che builtin) trả đúng byte NEWROOT.RDT của <game> (đọc qua lớp phủ như mọi file khác)."""
    tools = os.path.join(ROOT, 'tools')
    if tools not in sys.path:
        sys.path.insert(0, tools)
    try:
        import sc_cuts  # noqa: E402
    except ImportError:
        return None
    rel = 'SUBMAP/NEWROOT.RDT'
    if not inv.exists(game, rel):
        return None
    data = inv.read_file(game, rel)

    def _open(path, mode='r', *_a, **_k):
        if os.path.basename(str(path)) != 'NEWROOT.RDT' or 'b' not in mode:
            raise OSError('sc_cuts mo file khong mong doi: %s' % path)
        return io.BytesIO(data)
    missing = object()
    old = sc_cuts.__dict__.get('open', missing)
    sc_cuts.open = _open
    try:
        return sc_cuts.cut_table()
    except (OSError, struct.error):
        return None
    finally:
        if old is missing:
            del sc_cuts.open
        else:
            sc_cuts.open = old


def scene_list(recs, cuts):
    by_scene = collections.OrderedDict()
    for r in sorted(recs, key=lambda x: (x['disc'], x['scene_dir'], x['obj'])):
        by_scene.setdefault((r['disc'], r['scene_dir']), []).append(r['obj'])
    out = []
    for (disc, ad), objs in by_scene.items():
        sc = collections.OrderedDict()
        sc['scene'] = 'DRGN2%d/%d' % (disc, ad)
        sc['sobj'] = sorted(set(objs))
        cl = sorted((cuts or {}).get('DRGN2%d/%04d' % (disc, ad + 1), []))
        sc['cuts'] = [collections.OrderedDict([('cut', c), ('when', 'early' if k == 'dau' else 'late')]) for c, k in cl]
        sc['cmd'] = ['powershell -File tools/sc_dbg.ps1 -Warp %d' % c for c, _k in cl]
        out.append(sc)
    return out


def encounter_list(encs, mid):
    out = []
    for idx, name in (encs or {}).get(mid, []):
        e = collections.OrderedDict()
        e['encounter'] = idx
        e['name'] = name
        e['monster'] = mid
        e['cmd'] = 'powershell -File tools/sc_dbg.ps1 -Encounter %d' % idx
        out.append(e)
    return out


def story_n(model):
    """'SECT/DRGN0.BIN/N' -> N (mô hình cốt truyện), còn lại None."""
    m = re.match(r'^SECT/DRGN0\.BIN/(\d+)$', model)
    return int(m.group(1)) if m else None


def story_encounters(ns, tabs, calls, encs):
    """Trận có cảnh cắt nạp một trong các mô hình cốt truyện ns (inventory.cutscene_story_tables/cutscene_callers)."""
    by_enc = collections.OrderedDict()
    for i in sorted(tabs):
        hit = [n for n in tabs[i] if n in ns]
        if not hit:
            continue
        for mid in calls.get(i, []):
            for e in encounter_list(encs, mid):
                k = (e['encounter'], mid)
                if k not in by_enc:
                    e['deff_cutscenes'] = []
                    e['story_models'] = []
                    by_enc[k] = e
                g = by_enc[k]
                g['deff_cutscenes'].append(i)
                g['story_models'] = sorted(set(g['story_models']) | set(hit))
    out = []
    for (_enc, mid), e in sorted(by_enc.items()):
        e['via_vi'] = ('script quái DRGN1/%d gọi DEFF cảnh cắt trận %s (%s); bảng chỉ số file của DEFF có %s' % (
            mid + 1, ', '.join(str(i) for i in e['deff_cutscenes']),
            ', '.join('SECT/DRGN0.BIN/%d' % (inv.CUTSCENE_DEFF_BASE + 2 * i) for i in e['deff_cutscenes']),
            ', '.join('DRGN0/%d' % n for n in e['story_models'])))
        out.append(e)
    return out


def build_verify(game, b, recs, excluded):
    cuts = cut_table(game)
    encs = parse_encounters()
    # thiếu nguồn -> verify_scenes.json thiếu cut / trận: là LỖI (không ghi, --check không đạt), không chỉ cảnh báo
    if cuts is None:
        _err(b, 'khong doc duoc bang cut (tools/sc_cuts.py, SUBMAP/NEWROOT.RDT) cho %s' % game)
    if encs is None:
        _err(b, 'khong co %s: thieu chi so tran' % os.path.relpath(ENCOUNTERS_JAVA, ROOT))
    # mô hình cốt truyện của mục medium/low + loại trừ -> DEFF cảnh cắt trận -> quái gọi -> trận
    want = set()
    for e, _meta in b.resolution:
        if e['confidence'] != 'high':
            want |= {story_n(s['model']) for s in e['sources'] if s['kind'] == 'story'}
    want |= {story_n(x['model']) for x in excluded if x['kind'] == 'story'}
    want.discard(None)
    tabs = inv.cutscene_story_tables(game, want)
    calls = inv.cutscene_callers(game)
    b.report.append('DEFF canh cat tran co mo hinh cot truyen can xac minh: %s' % (
        ', '.join('%d:%s<-quai%s' % (i, ns, calls.get(i, [])) for i, ns in sorted(tabs.items())) or '-'))
    entries = []
    id_by_model = {}
    for e in b.catalog:
        for s in e['sources']:
            id_by_model.setdefault(s['model'], e['id'])
    for e, meta in b.resolution:
        if e['confidence'] == 'high':
            continue
        head = meta['head']
        v = collections.OrderedDict()
        for k in ('id', 'key_us', 'char', 'form', 'tier', 'confidence', 'label_vi'):
            v[k] = e[k]
        if head['kind'] == 'field':
            ck = head['model']
        elif head['kind'] == 'story':
            ck = 'story:%d' % head['n']
        else:
            ck = 'monster:%d' % head['mid']
        v['check_vi'] = CHECK_VI[ck]
        v['scenes'] = scene_list(meta['frecs'], cuts)
        encl = []
        for g in meta['grp']:
            if g['kind'] == 'monster':
                encl += encounter_list(encs, g['mid'])
        ns = {story_n(s['model']) for s in e['sources'] if s['kind'] == 'story'} - {None}
        if ns:
            encl += story_encounters(ns, tabs, calls, encs)
        v['encounters'] = encl
        related = []
        if head['kind'] == 'story' and head['n'] in RELATED_FIELD:
            rid = id_by_model.get(RELATED_FIELD[head['n']])
            if rid:
                related.append(rid)
        v['related'] = related
        if head['kind'] == 'field':
            how = ('Warp tới một cut ở trên (tools/sc_dbg.ps1 -Warp N), chạy tools/run_sc.ps1 -Remaster full '
                   '-RemasterLog; trên hình phải đúng nhân vật như check_vi và debug.log có dòng hit cho key_us.')
        elif head['kind'] == 'monster':
            how = ('Bắt đầu trận ở trên (tools/sc_dbg.ps1 -Encounter N) với -Remaster full -RemasterLog; mô hình phải '
                   'đúng như check_vi và debug.log có dòng hit CombatantModel cho key_us.')
        elif encl:
            how = ('Mô hình cốt truyện do DEFF cảnh cắt trận nạp (lệnh script call 354 nạp tài nguyên toàn cục rồi '
                   'call 361 gắn mô hình vào combatant, Battle.java:831, 838), truy tĩnh: xem via_vi của từng trận. Bắt đầu trận '
                   '(tools/sc_dbg.ps1 -Encounter N) với tools/run_sc.ps1 -Remaster full -RemasterLog, đánh tới cảnh cắt '
                   'trong trận (deff_cutscenes; thường ở đầu trận, khi máu đối thủ thấp hoặc khi thắng); mô hình phải '
                   'đúng như check_vi và debug.log có dòng hit CombatantModel cho key_us. Không thấy thì hạ xuống '
                   'optional.')
        else:
            how = ('Chưa truy được trận nào nạp DRGN0/%d: mô hình cốt truyện được script trận / cảnh cắt DEFF nạp bằng '
                   'call 354 (Battle.java:831) với chỉ số tính lúc chạy. Kiểm trong các trận cốt truyện có %s với '
                   '-Remaster full -RemasterLog: tìm dòng CombatantModel có key_us. Không thấy thì hạ xuống optional.'
                   % (head['n'], NAME[head['char']]))
        v['how_vi'] = how
        entries.append(v)
    nocov = [v['id'] for v in entries if not v['encounters'] and not any(s['cuts'] for s in v['scenes'])]
    if nocov:
        _err(b, 'muc medium/low chua co cut hay tran de xac minh: %s' % nocov)
    exc = []
    for x in excluded:
        o = collections.OrderedDict()
        o['kind'] = x['kind']
        o['model'] = x['model']
        o['tim'] = x['tim']
        o['key_us'] = x['key']
        o['expect'] = collections.OrderedDict([('nobj', x['nobj']), ('tris', x['tris'])])
        o['reason_vi'] = x['reason']
        o['scenes'] = scene_list(x['recs'], cuts) if x['kind'] == 'field' else []
        mid = None
        mm = re.match(r'monsters/(\d+)/', x['tim'])
        if x['kind'] == 'monster' and mm:
            mid = int(mm.group(1))
        o['encounters'] = encounter_list(encs, mid) if mid is not None else []
        if x['kind'] == 'story':
            o['encounters'] = story_encounters({story_n(x['model'])}, tabs, calls, encs)
        exc.append(o)
    out = collections.OrderedDict()
    out['format'] = 1
    out['catalog'] = 'tools/sc_remaster/catalog/catalog_v1.json'
    out['how_vi'] = ('Mỗi mục medium/low phải được xác nhận trong game ở I1 trước khi phát hành; mục không xác nhận được '
                     'thì hạ xuống optional hoặc bỏ (không chặn bản dựng). Mục loại trừ: kiểm chúng vẫn retail '
                     '(debug.log không có hit). scenes: thư mục cảnh DRGN2x/<tài nguyên>, sobj = số đối tượng trong '
                     'cảnh (danh sách Submap Debugger), cuts = số cut cho tools/sc_dbg.ps1 -Warp (when=late: bản cuối '
                     'game của cut đó, đặt -Chapter trước khi Warp); cảnh không có cut là bản sao đĩa 2 của cảnh đĩa 1. '
                     'encounters: chỉ số LodEncounters.LEGACY cho tools/sc_dbg.ps1 -Encounter; trận có deff_cutscenes '
                     'là trận mà cảnh cắt trong trận nạp mô hình cốt truyện (truy tĩnh từ script, xem via_vi).')
    out['counts'] = collections.OrderedDict([
        ('entries', len(entries)),
        ('medium', sum(1 for v in entries if v['confidence'] == 'medium')),
        ('low', sum(1 for v in entries if v['confidence'] == 'low')),
        ('with_scenes', sum(1 for v in entries if any(s['cuts'] for s in v['scenes']))),
        ('with_encounters', sum(1 for v in entries if v['encounters'])),
        ('excluded', len(exc))])
    out['entries'] = entries
    out['excluded'] = exc
    return out


# ---------------------------------------------------------------- kiểm nội dung
PATH_RE = re.compile(r'^(SECT/DRGN(0|1|2[1-4])\.BIN/\d+(/\d+)?(/textures/\d+)?'
                     r'|characters/[a-z]+/(models/(combat|dragoon)/32|textures/(combat|dragoon))'
                     r'|monsters/\d+/textures/combat)$')
KEY_RE = re.compile(r'^[0-9a-f]{40}$')
ID_RE = re.compile(r'^[a-z0-9_.-]+$')
# Nhãn tiếng Việt: chỉ chữ cái Latin / chữ có dấu tiếng Việt (nguyên âm + dấu mũ, trăng, móc, 5 thanh; đ), số, dấu câu
# dưới đây; phải có ít nhất một chữ có dấu; mọi từ toàn ASCII phải là tên riêng / thuật ngữ / từ tiếng Việt không dấu
# trong VI_ASCII_WORDS (chặn câu tiếng Anh lọt vào nhãn; thêm từ vào đây khi đổi nhãn).
VI_MARKS = {0x0300, 0x0301, 0x0303, 0x0309, 0x0323, 0x0302, 0x0306, 0x031B}
VI_PUNCT = set(" ()+,/;:—-.'")
VI_ASCII_WORDS = {w for n in NAME.values() for w in re.findall(r'[A-Za-z]+', n)} | {
    'Dragoon', 'Wingly', 'Zieg', 'Lenus', 'DRGN', 'TMD', 'NPC', 'TIM', 'avatar',
    'trong', 'tam', 'cung', 'gia', 'Long', 'Xanh', 'xanh', 'cho', 'con', 'khi', 'hay', 'theo', 'sau', 'tay', 'cao'}
VI_WORD_RE = re.compile(r'[^\W\d_]+')


def _vi_letter(ch):
    if ch in 'đĐ':
        return True
    d = unicodedata.normalize('NFD', ch)
    return len(d) > 1 and d[0] in 'aeiouyAEIOUY' and all(ord(m) in VI_MARKS for m in d[1:])


def vi_text_errors(s, maxlen=200, words=True):
    """Lỗi của một chuỗi tiếng Việt một dòng (rỗng = đạt). words=False: không kiểm từ ASCII (văn bản hướng dẫn có tên
    lệnh / file)."""
    if not isinstance(s, str) or not s:
        return ['khong phai chuoi']
    out = []
    if any(c in s for c in '\t\r\n') or len(s) > maxlen:
        out.append('nhieu dong hoac dai qua %d' % maxlen)
    if unicodedata.normalize('NFC', s) != s:
        out.append('khong o dang NFC')
    if not any(_vi_letter(c) for c in s):
        out.append('khong co chu co dau tieng Viet')
    if words:
        bad = sorted({c for c in s if not (c.isascii() and c.isalnum()) and c not in VI_PUNCT and not _vi_letter(c)})
        if bad:
            out.append('ky tu ngoai bang chu tieng Viet: %r' % ''.join(bad))
        eng = sorted({w for w in VI_WORD_RE.findall(s) if w.isascii() and w not in VI_ASCII_WORDS})
        if eng:
            out.append('tu khong thuoc tieng Viet/ten rieng da biet: %s' % eng)
    if ref_spec.blob_check(json.dumps(s, ensure_ascii=False)):
        out.append('co chuoi hex/base64')
    return out


def validate_catalog(cat):
    """Chỉ đường dẫn, số đếm, hash, nhãn tiếng Việt (và các giá trị liệt kê của lược đồ). -> danh sách lỗi."""
    errs = []
    if not isinstance(cat, list) or not cat:
        return ['catalog phai la danh sach khong rong']
    seen_id, seen_key = set(), set()
    for i, e in enumerate(cat):
        where = 'muc %d' % i
        if not isinstance(e, dict) or list(e) != ['id', 'char', 'form', 'tier', 'confidence', 'label_vi', 'sources',
                                                   'expect', 'key_us']:
            errs.append('%s: khoa truong sai %s' % (where, list(e) if isinstance(e, dict) else type(e)))
            continue
        where = e['id']
        if not isinstance(e['id'], str) or not ID_RE.match(e['id']) or e['id'] in seen_id:
            errs.append('%s: id sai/trung' % where)
        seen_id.add(e['id'])
        if e['char'] not in CHARS:
            errs.append('%s: char %r' % (where, e['char']))
        if e['form'] not in FORMS:
            errs.append('%s: form %r' % (where, e['form']))
        if e['tier'] not in ('core', 'optional'):
            errs.append('%s: tier %r' % (where, e['tier']))
        if e['confidence'] not in ('high', 'medium', 'low'):
            errs.append('%s: confidence %r' % (where, e['confidence']))
        lerr = vi_text_errors(e['label_vi'])
        if lerr:
            errs.append('%s: label_vi khong phai nhan tieng Viet mot dong (%s)' % (where, '; '.join(lerr)))
        if not isinstance(e['key_us'], str) or not KEY_RE.match(e['key_us']) or e['key_us'] in seen_key:
            errs.append('%s: key_us sai/trung' % where)
        seen_key.add(e['key_us'])
        ex = e['expect']
        if not isinstance(ex, dict) or list(ex) != ['nobj', 'tris'] or not all(
                type(ex[k]) is int and ex[k] > 0 for k in ex):
            errs.append('%s: expect sai' % where)
        elif not 1 <= ex['nobj'] <= 64:
            errs.append('%s: nobj ngoai 1..64 (SPEC partCount)' % where)
        srcs = e['sources']
        if not isinstance(srcs, list) or not srcs:
            errs.append('%s: sources rong' % where)
            continue
        for s in srcs:
            if not isinstance(s, dict) or list(s) != ['kind', 'model', 'tim'] or s['kind'] not in (
                    'battle', 'field', 'story', 'monster'):
                errs.append('%s: nguon sai %r' % (where, s))
                continue
            for k in ('model', 'tim'):
                if not isinstance(s[k], str) or not PATH_RE.match(s[k]):
                    errs.append('%s: duong dan %s sai %r' % (where, k, s[k]))
        if len({(s['model'], s['tim']) for s in srcs if isinstance(s, dict) and 'model' in s}) != len(srcs):
            errs.append('%s: nguon trung' % where)
    return errs


SCENE_RE = re.compile(r'^DRGN2[1-4]/\d+$')
WARP_RE = re.compile(r'^powershell -File tools/sc_dbg\.ps1 -Warp \d+$')
ENC_RE = re.compile(r'^powershell -File tools/sc_dbg\.ps1 -Encounter \d+$')
ENC_NAME_RE = re.compile(r'^[a-z0-9_]+$')


def _ints(x, lo=0):
    return isinstance(x, list) and all(type(v) is int and v >= lo for v in x)


def validate_verify(ver, cat):
    """verify_scenes.json: lược đồ, chỉ đường dẫn / số / hash / tên trận SC / văn bản tiếng Việt, phủ ĐÚNG các mục
    medium/low của danh mục (cùng thứ tự, mỗi mục có ít nhất một cut hoặc một trận). -> danh sách lỗi."""
    errs = []
    if not isinstance(ver, dict) or list(ver) != ['format', 'catalog', 'how_vi', 'counts', 'entries', 'excluded']:
        return ['verify: khoa truong goc sai %s' % (list(ver) if isinstance(ver, dict) else type(ver))]
    if ver['format'] != 1 or ver['catalog'] != 'tools/sc_remaster/catalog/catalog_v1.json':
        errs.append('verify: format/catalog sai')
    for m in vi_text_errors(ver['how_vi'], 2000, False):
        errs.append('verify how_vi: %s' % m)
    by_id = {e['id']: e for e in cat if isinstance(e, dict) and 'id' in e}
    want = [e['id'] for e in cat if isinstance(e, dict) and e.get('confidence') != 'high']
    got = [v.get('id') for v in ver['entries'] if isinstance(v, dict)]
    if got != want:
        errs.append('verify: muc %s != cac muc medium/low cua danh muc %s' % (got[:4], want[:4]))

    def scenes_ok(where, scenes):
        if not isinstance(scenes, list):
            return errs.append('%s: scenes khong phai danh sach' % where)
        for s in scenes:
            if not isinstance(s, dict) or list(s) != ['scene', 'sobj', 'cuts', 'cmd'] or not isinstance(s['scene'], str) \
                    or not SCENE_RE.match(s['scene']) or not _ints(s['sobj']) or not isinstance(s['cuts'], list) \
                    or not isinstance(s['cmd'], list):
                errs.append('%s: canh sai %r' % (where, s))
                continue
            for c in s['cuts']:
                if not isinstance(c, dict) or list(c) != ['cut', 'when'] or type(c['cut']) is not int \
                        or c['when'] not in ('early', 'late'):
                    errs.append('%s: cut sai %r' % (where, c))
            if len(s['cmd']) != len(s['cuts']) or not all(isinstance(x, str) and WARP_RE.match(x) for x in s['cmd']):
                errs.append('%s: lenh Warp sai %r' % (where, s['cmd']))

    def encs_ok(where, encs):
        if not isinstance(encs, list):
            return errs.append('%s: encounters khong phai danh sach' % where)
        for x in encs:
            keys = list(x) if isinstance(x, dict) else None
            if keys not in (['encounter', 'name', 'monster', 'cmd'],
                            ['encounter', 'name', 'monster', 'cmd', 'deff_cutscenes', 'story_models', 'via_vi']) \
                    or type(x['encounter']) is not int or type(x['monster']) is not int \
                    or not isinstance(x['name'], str) or not ENC_NAME_RE.match(x['name']) \
                    or not isinstance(x['cmd'], str) or not ENC_RE.match(x['cmd']):
                errs.append('%s: tran sai %r' % (where, x))
                continue
            if len(keys) == 7:
                if not _ints(x['deff_cutscenes']) or not x['deff_cutscenes'] or not _ints(x['story_models']) \
                        or not x['story_models']:
                    errs.append('%s: deff_cutscenes/story_models sai' % where)
                for m in vi_text_errors(x['via_vi'], 1000, False):
                    errs.append('%s via_vi: %s' % (where, m))
    for v in ver['entries']:
        if not isinstance(v, dict) or list(v) != ['id', 'key_us', 'char', 'form', 'tier', 'confidence', 'label_vi',
                                                  'check_vi', 'scenes', 'encounters', 'related', 'how_vi']:
            errs.append('verify: muc sai truong %r' % (list(v) if isinstance(v, dict) else v))
            continue
        where = 'verify %s' % v['id']
        e = by_id.get(v['id'])
        if e is None or any(v[k] != e[k] for k in ('key_us', 'char', 'form', 'tier', 'confidence', 'label_vi')):
            errs.append('%s: khong khop muc danh muc' % where)
        for k in ('check_vi', 'how_vi'):
            for m in vi_text_errors(v[k], 1000, False):
                errs.append('%s %s: %s' % (where, k, m))
        scenes_ok(where, v['scenes'])
        encs_ok(where, v['encounters'])
        if not isinstance(v['related'], list) or any(r not in by_id for r in v['related']):
            errs.append('%s: related sai' % where)
        if not v['encounters'] and not any(isinstance(s, dict) and s.get('cuts') for s in v['scenes']):
            errs.append('%s: khong co cut hay tran de xac minh' % where)
    cat_keys = {e.get('key_us') for e in cat if isinstance(e, dict)}
    for x in ver['excluded']:
        if not isinstance(x, dict) or list(x) != ['kind', 'model', 'tim', 'key_us', 'expect', 'reason_vi', 'scenes',
                                                  'encounters']:
            errs.append('verify: loai tru sai truong %r' % x)
            continue
        where = 'loai tru %s' % x['model']
        if x['kind'] not in ('field', 'story', 'monster') or not all(
                isinstance(x[k], str) and PATH_RE.match(x[k]) for k in ('model', 'tim')):
            errs.append('%s: kind/duong dan sai' % where)
        if not isinstance(x['key_us'], str) or not KEY_RE.match(x['key_us']) or x['key_us'] in cat_keys:
            errs.append('%s: key_us sai hoac trung muc danh muc' % where)
        ex = x['expect']
        if not isinstance(ex, dict) or list(ex) != ['nobj', 'tris'] or not all(type(ex[k]) is int and ex[k] > 0
                                                                              for k in ex):
            errs.append('%s: expect sai' % where)
        for m in vi_text_errors(x['reason_vi'], 300, False):
            errs.append('%s reason_vi: %s' % (where, m))
        scenes_ok(where, x['scenes'])
        encs_ok(where, x['encounters'])
    c = ver['counts']
    exp = collections.OrderedDict([
        ('entries', len(ver['entries'])),
        ('medium', sum(1 for v in ver['entries'] if isinstance(v, dict) and v.get('confidence') == 'medium')),
        ('low', sum(1 for v in ver['entries'] if isinstance(v, dict) and v.get('confidence') == 'low')),
        ('with_scenes', sum(1 for v in ver['entries'] if isinstance(v, dict) and any(
            isinstance(s, dict) and s.get('cuts') for s in v.get('scenes', [])))),
        ('with_encounters', sum(1 for v in ver['entries'] if isinstance(v, dict) and v.get('encounters'))),
        ('excluded', len(ver['excluded']))])
    if c != exp:
        errs.append('verify: counts %s != dem lai %s' % (dict(c), dict(exp)))
    for s in ref_spec.blob_check(json.dumps(ver, ensure_ascii=False)):
        errs.append('verify: blob %s' % s)
    return errs


def resolve_catalog(game, cat):
    """Phân giải từng mục của danh mục: mọi nguồn có file, là mô hình, khoá/nobj/tris khớp; TIM là TIM.
    -> (lỗi, báo cáo [{id, tier, key, status, sources}])."""
    errs = []
    rep = []
    for e in cat:
        st = 'ok'
        rows = []
        for s in e['sources']:
            if not inv.exists(game, s['model']) or not inv.exists(game, s['tim']):
                rows.append(dict(model=s['model'], status='not found'))
                st = 'not found' if st == 'ok' else st
                continue
            try:
                k = inv.model_key(game, s['model'])
            except (ValueError, ref_spec.SpecError) as ex:
                rows.append(dict(model=s['model'], status='not a model: %s' % ex))
                st = 'structure mismatch'
                continue
            if inv.parse_tim_info(inv.read_file(game, s['tim'])) is None:
                rows.append(dict(model=s['model'], status='tim not a TIM'))
                st = 'structure mismatch'
                continue
            if (k['nobj'], k['tris']) != (e['expect']['nobj'], e['expect']['tris']):
                rows.append(dict(model=s['model'], status='structure mismatch %dp/%dt' % (k['nobj'], k['tris'])))
                st = 'structure mismatch'
                continue
            if k['key'] != e['key_us']:
                rows.append(dict(model=s['model'], status='key differs %s' % k['key']))
                st = 'key differs' if st == 'ok' else st
                continue
            rows.append(dict(model=s['model'], status='ok'))
        rep.append(dict(id=e['id'], tier=e['tier'], key=e['key_us'], status=st, sources=rows))
        if st != 'ok':
            errs.append('%s (%s): %s' % (e['id'], e['tier'], st))
    return errs, rep


def check_vectors(cat, paths_by_id=None, game=None):
    """key_us == spec/vectors.json modelKey ở mọi mẫu có mặt trong danh mục. -> (lỗi, số đã so, số không có).

    Mẫu được tìm theo đường dẫn nguồn (hoặc mọi đường dẫn cùng khoá khi có paths_by_id). Với file danh mục đã có (chỉ có
    nguồn đại diện), mẫu không là nguồn được tìm qua khoá tính lại từ dữ liệu (game) rồi so như thường."""
    with open(VECTORS_PATH, encoding='utf-8') as f:
        vec = json.load(f)['models']
    by_path = {}
    by_key = {e['key_us']: e for e in cat}
    for e in cat:
        paths = set(paths_by_id.get(e['id'], ())) if paths_by_id else set()
        paths |= {s['model'] for s in e['sources']}
        for p in paths:
            by_path.setdefault(p, e)
    errs = []
    n = 0
    missing = []
    for v in vec:
        e = None
        for p in [v['model']] + list(v.get('aliases', [])):
            e = by_path.get(p)
            if e:
                break
        if e is None and game is not None:
            e = by_key.get(inv.model_key(game, v['model'])['key'])
        if e is None:
            missing.append(v['id'])
            continue
        n += 1
        if e['key_us'] != v['modelKey'] or e['expect']['nobj'] != v['partCount'] or e['expect']['tris'] != v['tris']:
            errs.append('%s: catalog %s %s %dp/%dt != vectors %s %dp/%dt' % (
                v['id'], e['id'], e['key_us'][:12], e['expect']['nobj'], e['expect']['tris'], v['modelKey'][:12],
                v['partCount'], v['tris']))
    return errs, n, missing


def dumps(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=1) + '\n').encode('utf-8')


def validator_selftest(cat, ver):
    """Gieo lỗi vào bản sao danh mục / verify_scenes; validate_catalog / validate_verify phải bắt từng lỗi.
    -> (danh sách lỗi của chính bộ kiểm, số lỗi gieo)."""
    import copy

    def mut(fn):
        c = copy.deepcopy(cat)
        fn(c)
        return c

    def vmut(fn):
        v = copy.deepcopy(ver)
        fn(v)
        return v
    seeds = {
        'ghi chu tieng Anh': lambda c: c[0].__setitem__('note', 'visual only'),
        'nhan khong dau': lambda c: c[0].__setitem__('label_vi', 'Dart field model'),
        'nhan nhieu dong': lambda c: c[0].__setitem__('label_vi', c[0]['label_vi'] + '\nx'),
        'blob base64 trong duong dan': lambda c: c[0]['sources'][0].__setitem__('model', 'QUJDREVGR0hJSktMTU5PUA=='),
        'hex dai': lambda c: c[0].__setitem__('key_us', c[0]['key_us'] * 2),
        'khoa trung': lambda c: c[1].__setitem__('key_us', c[0]['key_us']),
        'id trung': lambda c: c[1].__setitem__('id', c[0]['id']),
        'tier la': lambda c: c[0].__setitem__('tier', 'excluded'),
        'nguon thua truong': lambda c: c[0]['sources'][0].__setitem__('note', 'x'),
        'kind la': lambda c: c[0]['sources'][0].__setitem__('kind', 'npc'),
        'expect chuoi': lambda c: c[0]['expect'].__setitem__('tris', '484'),
        'duong dan tuyet doi': lambda c: c[0]['sources'][0].__setitem__('tim', 'D:/LOD-SC/game/files/x'),
        'nguon rong': lambda c: c[0].__setitem__('sources', []),
        'nhan tieng Anh co mot chu dau': lambda c: c[0].__setitem__('label_vi', 'Dart field model with sword (é)'),
        'nhan chu Kirin': lambda c: c[0].__setitem__('label_vi', 'Дарт — ngoài cảnh'),
        'nhan co hex': lambda c: c[0].__setitem__('label_vi', c[0]['label_vi'] + ' 0123456789abcdef0123'),
        'nhan dang NFD': lambda c: c[0].__setitem__('label_vi', unicodedata.normalize('NFD', c[0]['label_vi'])),
    }
    vseeds = {
        'verify thieu muc': lambda v: v['entries'].pop(),
        'verify blob base64': lambda v: v['entries'][0].__setitem__('check_vi', 'xem QUJDREVGR0hJSktMTU5PUFFSU1Q='),
        'verify ghi chu tieng Anh': lambda v: v['entries'][0].__setitem__('check_vi', 'visual identification only'),
        'verify muc khong co cut/tran': lambda v: (v['entries'][0].__setitem__('scenes', []),
                                                   v['entries'][0].__setitem__('encounters', [])),
        'verify duong dan tuyet doi': lambda v: v['excluded'][0].__setitem__('model', 'D:/LOD-SC/game/files/x'),
        'verify khoa trung danh muc': lambda v: v['excluded'][0].__setitem__('key_us', cat[0]['key_us']),
        'verify truong thua': lambda v: v['entries'][0].__setitem__('note', 'x'),
    }
    bad = []
    if validate_catalog(cat):
        bad.append('danh muc that bi bao loi: %s' % validate_catalog(cat)[:3])
    if validate_verify(ver, cat):
        bad.append('verify_scenes that bi bao loi: %s' % validate_verify(ver, cat)[:3])
    for name, fn in seeds.items():
        if not validate_catalog(mut(fn)):
            bad.append('khong bat duoc loi gieo: %s' % name)
    for name, fn in vseeds.items():
        if not validate_verify(vmut(fn), cat):
            bad.append('khong bat duoc loi gieo: %s' % name)
    return bad, len(seeds) + len(vseeds)


# ---------------------------------------------------------------- CLI
def main(argv=None):
    inv.utf8_stdout()
    ap = argparse.ArgumentParser(description='Dung catalog_v1.json + verify_scenes.json (chi doc game/files).')
    ap.add_argument('--game', default=None)
    ap.add_argument('--check', action='store_true', help='so byte voi file da co + phan giai + doi chieu vectors')
    ap.add_argument('--report', nargs='?', const='', default=None,
                    help='ghi bao cao phan giai JSON (mac dinh work/upscale/sc_remaster_c1/resolution.json)')
    a = ap.parse_args(argv)
    game = inv.resolve_game(a.game)
    before = inv.sampled_hashes(game)
    b = build(game)
    cat_bytes, ver_bytes = dumps(b.catalog), dumps(b.verify)
    errs = list(b.errors)
    errs += validate_catalog(b.catalog)
    errs += validate_verify(b.verify, b.catalog)
    serrs, nseed = validator_selftest(b.catalog, b.verify)
    errs += serrs
    errs += ['blob trong catalog: %s' % s for s in ref_spec.blob_check(cat_bytes.decode('utf-8'))]
    errs += ['blob trong verify_scenes: %s' % s for s in ref_spec.blob_check(ver_bytes.decode('utf-8'))]
    print('bo kiem noi dung JSON: %d loi gieo, %d khong bat duoc' % (nseed, len(serrs)))
    verrs, nvec, missing = check_vectors(b.catalog, b.paths_by_id)
    errs += verrs
    want_ids = [e['id'] for e in b.catalog if e['confidence'] != 'high']
    if [v['id'] for v in b.verify['entries']] != want_ids:
        errs.append('verify_scenes khong phu dung moi muc medium/low cua danh muc')
    for line in b.report:
        print(line)
    for w in b.warnings:
        print('CANH BAO:', w)
    print('vectors.json: %d mau so khop key_us, %d khong co trong danh muc %s' % (nvec, len(missing), missing))
    c = b.verify['counts']
    print('verify_scenes: %d muc (%d medium, %d low), %d co cut, %d co tran; %d loai tru' % (
        c['entries'], c['medium'], c['low'], c['with_scenes'], c['with_encounters'], c['excluded']))
    for x in b.verify['excluded']:
        print('  loai tru %-26s %s  %s' % (x['model'], x['key_us'][:12], x['reason_vi']))
    if a.check:
        for path, data in ((CATALOG_PATH, cat_bytes), (VERIFY_PATH, ver_bytes)):
            if not os.path.isfile(path):
                errs.append('%s: chua co' % os.path.relpath(path, ROOT))
                continue
            with open(path, 'rb') as f:
                old = f.read()
            if old != data:
                errs.append('%s: khac ban dung lai (%d vs %d byte)' % (os.path.relpath(path, ROOT), len(old), len(data)))
        if os.path.isfile(CATALOG_PATH):
            with open(CATALOG_PATH, encoding='utf-8') as f:
                committed = json.load(f)
            errs += validate_catalog(committed)
            if os.path.isfile(VERIFY_PATH):
                with open(VERIFY_PATH, encoding='utf-8') as f:
                    errs += validate_verify(json.load(f), committed)
            rerrs, rep = resolve_catalog(game, committed)
            errs += rerrs
            cerrs, nv2, _m2 = check_vectors(committed, game=game)
            errs += cerrs
            core_ok = sum(1 for r in rep if r['tier'] == 'core' and r['status'] == 'ok')
            print('phan giai file da co: %d/%d muc ok (loi %d/%d ok), vectors so %d' % (
                sum(1 for r in rep if r['status'] == 'ok'), len(rep), core_ok,
                sum(1 for r in rep if r['tier'] == 'core'), nv2))
            if a.report is not None:
                p = inv.out_path('resolution.json', a.report or None)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, 'wb') as f:
                    f.write(dumps(rep))
                print('ghi', os.path.relpath(p, ROOT))
    elif errs:
        print('KHONG GHI catalog_v1.json / verify_scenes.json vi con loi (giu nguyen file cu)')
    else:
        for path, data in ((CATALOG_PATH, cat_bytes), (VERIFY_PATH, ver_bytes)):
            with open(path, 'wb') as f:
                f.write(data)
            print('ghi %s (%d byte)' % (os.path.relpath(path, ROOT), len(data)))
    if inv.sampled_hashes(game) != before:
        errs.append('game/files thay doi trong luc chay')
    for e in errs:
        print('LOI:', e)
    print('KET QUA:', 'DAT' if not errs else 'LOI (%d)' % len(errs))
    return 0 if not errs else 1


if __name__ == '__main__':
    sys.exit(main())
