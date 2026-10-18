"""tools/sc_remaster/lib — thư viện lõi Python cho mô hình HD (route B, 'LRM spec 1', tools/sc_remaster/SPEC.md).

Dùng chung cho mọi công đoạn của bộ sinh (scan, export, pack, verify). Chạy được dưới python.exe đi kèm Blender 5.2.2
với cờ -I (không PIL, không tkinter) và dưới Python hệ thống. Chỉ dùng thư viện chuẩn + numpy; OpenImageIO là tuỳ chọn
(imgio). KHÔNG BAO GIỜ import PIL.

Mô-đun:
  gamefiles  đọc <game>/files như Loader của SC (lớp phủ sc-vi <game>/vi/files thắng; mục ảo 'v=thật;cỡ' trong mrg)
  tmd        CContainer (+4 hoạt cảnh CLUT, +8 Subfile2), TMD, gói đã làm phẳng theo thứ tự TmdObjLoader, UvAdjust
  tim        TIM, VRAM ảo 1024x512 (đặt như export_tmd.py: rect gốc / ô sobj 0), giải mã texel như tmd.fsh
  export     đầu ra theo lược đồ tools/sc_remodel/export_tmd.py (JSON + _atlas.png + _atlas_pad.png + glTF/OBJ)
  lrmkey     khoá hình học LRMK1 (SPEC §3.1)
  facehash   FaceHash FNV-1a32 (SPEC §3.3), mặt LIVE (§3.4), xác minh biến thể (§4.4)
  lrm        file LRM1 ghi / đọc / kiểm (§3.5), index.tsv (§3.7), lưới 16 float của runtime (§3.2, §4.3)
  imgio      PNG xác định (ghi zlib 9 lọc 0), bộ đọc PNG thuần Python + numpy, OIIO tuỳ chọn, alpha + mip (§3.6)
  anims      TmdAnimationFile: mọi khung khoá của mọi phần (QA hình học), tìm file hoạt cảnh của một nguồn

Cách dùng (từ mã của gói khác; thư mục chứa 'lib' phải nằm trong sys.path — với -I phải tự thêm):
  sys.path.insert(0, os.path.join(<repo>, 'tools', 'sc_remaster'))
  from lib import gamefiles, tmd, lrmkey
  gf = gamefiles.GameFiles('game/files')
  model = tmd.parse_ccontainer(gf.entry('characters/dart/models/combat', 32).data)
  key, part_keys = lrmkey.model_keys(model)
Tự kiểm: python tools/sc_remaster/tests/test_lib.py (exit 0 = đạt).
"""
import os

LIB_VERSION = 1
GENERATOR = 'lodsc-remaster 1'          # chuỗi 'generator' mặc định trong header LRM1 (SPEC §3.5.5)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
DEFAULT_GAME = os.path.join(ROOT, 'game', 'files')
# Dữ liệu suy ra từ đĩa (export, npz, atlas, ảnh xem trước) chỉ được ghi dưới work/upscale/sc_remaster* (git bỏ qua).
DEFAULT_WORK = os.path.join(ROOT, 'work', 'upscale', 'sc_remaster_p1')


class RemasterError(Exception):
    """Lỗi chung của thư viện."""


class SpecError(RemasterError):
    """Dữ liệu sai theo SC (Java sẽ ném ngoại lệ) hoặc theo SPEC (runtime phải quay về đường gốc)."""


class LrmError(SpecError):
    """File LRM1 / index.tsv không hợp lệ (SPEC §3.5.4, §3.7)."""


class GameFileError(RemasterError):
    """Không đọc được file game (thiếu file, mrg sai)."""


class PngError(RemasterError):
    """PNG hỏng hoặc kiểu không hỗ trợ."""


def utf8_stdio():
    """Đặt stdout/stderr UTF-8 (errors='replace'): với python -I (bỏ PYTHONIOENCODING) Windows dùng cp1252 khi bị dẫn ống,
    in đường dẫn / nhãn tiếng Việt sẽ lỗi. Gọi ở đầu main() của mọi công cụ dòng lệnh."""
    import sys
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass


def rel_to_root(path):
    """Đường dẫn tương đối theo gốc repo (dấu '/') để in; khác ổ đĩa thì giữ tuyệt đối."""
    try:
        return os.path.relpath(path, ROOT).replace('\\', '/')
    except ValueError:
        return os.path.abspath(path).replace('\\', '/')
