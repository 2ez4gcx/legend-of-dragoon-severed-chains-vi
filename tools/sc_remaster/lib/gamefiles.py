"""gamefiles.py — đọc file game đã giải nén đúng như Loader của Severed Chains (sc-vi), CHỈ ĐỌC.

Gốc: <game>/files (Unpacker.ROOT). Lớp phủ sc-vi: <game>/vi/files/<rel> thắng <game>/files/<rel> khi đọc nội dung
(sc-vi/src/legend/game/unpacker/Loader.java:32-50, readAll). File mrg luôn đọc ở <game>/files (không qua lớp phủ).

Hai kiểu nạp của SC:
  - một file (Loader.loadFileSync / DrgnFiles.loadDrgnFile): đường dẫn trực tiếp, không giải mrg -> GameFiles.read(rel);
  - một thư mục (Loader.loadDirectorySync, Loader.java:163-266) -> GameFiles.load_dir(rel) / entry(rel, i):
      có 'mrg' (mỗi dòng 'ảo=thật;cỡ', 'ảo=;0' = không có file): mục thật (ảo == thật) = byte của file;
      mục ảo (ảo != thật) = TOÀN BỘ byte của file thật cuối chuỗi liên kết (FileData.virtual: cùng mảng, offset 0, cỡ =
      độ dài file thật), giữ 'cỡ ảo' (hasVirtualSize = cỡ != 0) và realFileIndex = chỉ số file thật;
      thư mục con -> FileData rỗng; không có mrg -> các file thường xếp theo số (so khớp số nguyên, nếu không thì
      không phân biệt hoa thường).
  Java: FileData.real() = (realFileIndex == -1 và cỡ != 0); file thật có virtualSize = độ dài dữ liệu.

Cách dùng:
  gf = GameFiles('game')              # thư mục game/ (chứa files/) hoặc chính game/files
  data = gf.read('characters/dart/textures/combat')
  e = gf.entry('SECT/DRGN21.BIN/26', 0)   # Entry: e.data, e.path (file thật), e.real_index (-1 = thật), e.virtual_size
Không bao giờ ghi vào thư mục game (mọi file mở 'rb').
"""
import functools
import os
import re

from . import DEFAULT_GAME, GameFileError

_MRG_SPLIT = re.compile('[=;]')
_LINE_SPLIT = re.compile('\r\n|\r|\n')            # BufferedReader.lines(): chỉ \n, \r, \r\n là hết dòng
_JAVA_INT = re.compile(r'[+-]?\d+')                # Integer.parseInt: không nhận khoảng trắng / '_' như int() của Python


def _java_int(s):
    """Integer.parseInt(s) (cơ số 10, chữ số Unicode như Character.digit) -> int; ValueError nếu Java ném
    NumberFormatException (kể cả tràn int32)."""
    if not _JAVA_INT.fullmatch(s):
        raise ValueError('khong phai so nguyen Java: %r' % s)
    v = int(s)
    if not -0x80000000 <= v <= 0x7fffffff:
        raise ValueError('tran int32: %r' % s)
    return v


def resolve_game(game=None):
    """--game có thể là thư mục files/ hoặc thư mục game/ chứa files/ -> đường dẫn tuyệt đối tới files/."""
    game = os.path.abspath(game or DEFAULT_GAME)
    if os.path.isdir(os.path.join(game, 'SECT')) or os.path.isdir(os.path.join(game, 'characters')):
        return game
    sub = os.path.join(game, 'files')
    if os.path.isdir(sub):
        return sub
    raise GameFileError('khong thay thu muc files/ (SECT/, characters/) trong %s' % game)


def _java_name_cmp(a, b):
    """Bộ so sánh của Loader.loadDirectorySync khi không có mrg: số nguyên nếu cả hai là số, ngược lại không phân biệt hoa thường."""
    try:
        x, y = _java_int(a), _java_int(b)
        return (x > y) - (x < y)
    except ValueError:
        pass
    x, y = a.lower(), b.lower()
    return (x > y) - (x < y)


class Entry:
    """Một phần tử của danh sách FileData mà loadDirectorySync trả về."""
    __slots__ = ('gf', 'dir', 'index', 'real_index', 'source_index', 'virtual_size', 'path', 'is_dir')

    def __init__(self, gf, dir_rel, index, real_index, source_index, virtual_size, path, is_dir=False):
        self.gf = gf
        self.dir = dir_rel
        self.index = index                  # vị trí trong danh sách (= chỉ số ảo khi có mrg)
        self.real_index = real_index        # Java realFileIndex(): -1 với file thật, chỉ số file thật với mục ảo
        self.source_index = source_index    # chỉ số file thật cuối chuỗi (= index với file thật)
        self.virtual_size = virtual_size    # Java virtualSize (file thật: độ dài dữ liệu)
        self.path = path                    # đường dẫn tương đối (theo files/) của file thật chứa dữ liệu; None nếu thư mục
        self.is_dir = is_dir

    @property
    def data(self):
        if self.is_dir:
            return b''
        return self.gf.read(self.path)

    @property
    def size(self):
        return 0 if self.is_dir else self.gf.size(self.path)

    @property
    def virtual(self):
        return self.real_index != -1

    def real(self):
        """FileData.real(): không phải mục ảo và dài hơn 0 byte."""
        return self.real_index == -1 and self.size != 0

    def has_virtual_size(self):
        return self.virtual_size != 0

    def __repr__(self):
        return 'Entry(%s[%d] -> %s, virtual=%s, vsize=%d)' % (self.dir, self.index, self.path, self.virtual,
                                                              self.virtual_size)


class GameFiles:
    """Truy cập chỉ đọc vào <game>/files + lớp phủ <game>/vi/files."""

    def __init__(self, game=None):
        self.files = resolve_game(game)
        self.game = os.path.dirname(self.files)
        self.overlay = os.path.join(self.game, 'vi', 'files')
        self._mrg = {}
        self._dirs = {}
        self._ls = {}           # (gốc, thư mục rel) -> {tên: (là file, là thư mục, cỡ)} (scandir một lần; dữ liệu chỉ đọc)

    # ------------------------------------------------------------ đường dẫn
    @staticmethod
    def norm(rel):
        rel = rel.replace('\\', '/')
        while rel.startswith('/'):
            rel = rel[1:]
        return rel

    def abs(self, rel):
        """Đường dẫn tuyệt đối trong files/ (không xét lớp phủ)."""
        rel = self.norm(rel)
        return os.path.join(self.files, *rel.split('/')) if rel else self.files

    def overlay_abs(self, rel):
        return os.path.join(self.overlay, *self.norm(rel).split('/'))

    def _listing(self, root, dir_rel):
        k = (root, dir_rel)
        ls = self._ls.get(k)
        if ls is None:
            ls = {}
            p = os.path.join(root, *dir_rel.split('/')) if dir_rel else root
            try:
                with os.scandir(p) as it:
                    for de in it:
                        try:
                            isf = de.is_file()
                            isd = de.is_dir()
                            size = de.stat().st_size if isf else 0
                        except OSError:
                            continue
                        ls[de.name] = (isf, isd, size)
            except OSError:
                pass
            self._ls[k] = ls
        return ls

    def _stat(self, root, rel):
        rel = self.norm(rel)
        d, _, name = rel.rpartition('/')
        return self._listing(root, d).get(name)

    def source_path(self, rel):
        """File thực sự được đọc (readAll): lớp phủ nếu là file thường, ngược lại files/."""
        return self.overlay_abs(rel) if self.is_overlaid(rel) else self.abs(rel)

    def is_overlaid(self, rel):
        st = self._stat(self.overlay, rel)
        return bool(st and st[0])

    def isfile(self, rel):
        """Files.isRegularFile trên files/ (cách loadDirectorySync kiểm)."""
        st = self._stat(self.files, rel)
        return bool(st and st[0])

    def exists(self, rel):
        """loadFileSync đọc được: file thường trong lớp phủ hoặc trong files/."""
        return self.is_overlaid(rel) or self.isfile(rel)

    def isdir(self, rel):
        rel = self.norm(rel)
        if not rel:
            return os.path.isdir(self.files)
        st = self._stat(self.files, rel)
        return bool(st and st[1])

    def listdir(self, rel=''):
        return sorted(self._listing(self.files, self.norm(rel)))

    def size(self, rel):
        st = self._stat(self.overlay, rel)
        if st and st[0]:
            return st[2]
        st = self._stat(self.files, rel)
        if st and st[0]:
            return st[2]
        raise GameFileError('khong co file %s' % self.norm(rel))

    def read(self, rel):
        """Loader.loadFileSync(rel): byte của lớp phủ nếu có, ngược lại của files/ (không giải mrg)."""
        p = self.source_path(rel)
        try:
            with open(p, 'rb') as f:
                return f.read()
        except OSError as e:
            raise GameFileError('khong doc duoc %s: %s' % (self.norm(rel), e))

    # ------------------------------------------------------------ mrg / thư mục
    def mrg(self, dir_rel):
        """-> list[(ảo, thật hoặc -1, cỡ ảo)] theo thứ tự dòng, hoặc None khi thư mục không có mrg."""
        dir_rel = self.norm(dir_rel)
        if dir_rel in self._mrg:
            return self._mrg[dir_rel]
        p = os.path.join(self.abs(dir_rel), 'mrg')
        out = None
        if self.isfile(dir_rel + '/mrg'):
            out = []
            with open(p, 'rb') as f:
                raw = f.read()
            try:
                text = raw.decode('utf-8')
            except UnicodeDecodeError as e:               # Java: MalformedInputException
                raise GameFileError('%s/mrg: khong phai UTF-8: %s' % (dir_rel, e))
            lines = _LINE_SPLIT.split(text)
            if lines and lines[-1] == '':
                lines.pop()
            for ln in lines:
                parts = _MRG_SPLIT.split(ln)
                while parts and parts[-1] == '':          # String.split của Java bỏ chuỗi rỗng ở cuối
                    parts.pop()
                if len(parts) != 3:                        # Java: "Invalid MRG entry!"
                    raise GameFileError('%s/mrg: dong sai %r' % (dir_rel, ln))
                try:
                    virt = _java_int(parts[0])
                    if parts[1].strip() == '':
                        out.append((virt, -1, 0))
                    else:
                        out.append((virt, _java_int(parts[1]), _java_int(parts[2])))
                except ValueError:
                    raise GameFileError('%s/mrg: dong sai %r' % (dir_rel, ln))
        self._mrg[dir_rel] = out
        return out

    def load_dir(self, dir_rel):
        """Loader.loadDirectorySync(dir) -> list[Entry | None] (dữ liệu đọc lười khi truy cập Entry.data)."""
        dir_rel = self.norm(dir_rel)
        if dir_rel in self._dirs:
            return self._dirs[dir_rel]
        if not self.isdir(dir_rel):
            raise GameFileError('khong co thu muc %s' % dir_rel)
        mrg = self.mrg(dir_rel)
        files = []
        if mrg is None:
            names = [n for n, st in self._listing(self.files, dir_rel).items() if st[0]]
            names.sort(key=functools.cmp_to_key(_java_name_cmp))
            for i, n in enumerate(names):
                rel = dir_rel + '/' + n
                files.append(Entry(self, dir_rel, i, -1, i, self.size(rel), rel))
            self._dirs[dir_rel] = files
            return files
        # Int2IntArrayMap: khoá trùng ghi đè giá trị nhưng giữ vị trí đầu tiên
        order = []
        fmap = {}
        vsize = {}
        for virt, real, size in mrg:
            if virt not in fmap:
                order.append(virt)
            fmap[virt] = real
            vsize[virt] = size
        for virt in order:
            real = fmap[virt]
            if real == -1:
                files.append(None)
                continue
            rel = '%s/%d' % (dir_rel, real)
            if self.isfile(rel):
                if virt == real:
                    files.append(Entry(self, dir_rel, len(files), -1, real, self.size(rel), rel))
                else:
                    files.append(None)
            elif self.isdir(rel):
                files.append(Entry(self, dir_rel, len(files), -1, real, 0, None, is_dir=True))
            # (Java: không thêm gì nếu file thật không tồn tại -> chỉ số lệch; giữ đúng như vậy)
        for virt in order:
            real = fmap[virt]
            if virt == real or real == -1:
                continue
            seen = set()
            while fmap.get(real, 0) != real:            # Int2IntArrayMap.get trả 0 khi thiếu khoá
                if real in seen:
                    raise GameFileError('%s/mrg: vong lien ket o %d' % (dir_rel, real))
                seen.add(real)
                real = fmap.get(real, 0)
            rel = '%s/%d' % (dir_rel, real)
            if self.isfile(rel):
                if not 0 <= real < len(files) or files[real] is None or not 0 <= virt < len(files):
                    raise GameFileError('%s/mrg: muc ao %d -> %d khong co du lieu (Java: loi)' % (dir_rel, virt, real))
                src = files[real]
                files[virt] = Entry(self, dir_rel, virt, real, src.source_index, vsize[virt], src.path, src.is_dir)
        self._dirs[dir_rel] = files
        return files

    def entry(self, dir_rel, index):
        """Phần tử thứ index của loadDirectorySync(dir_rel), hoặc None (không có file / ngoài danh sách)."""
        files = self.load_dir(dir_rel)
        if 0 <= index < len(files):
            return files[index]
        return None

    def resolve(self, rel):
        """Đường dẫn 'dir/N': nếu là file thật -> rel; nếu không có trên đĩa nhưng mrg của dir có mục ảo N -> đường dẫn file
        thật của mục đó; ngược lại None. (Tiện cho bộ quét; nạp một file của SC không tự giải mrg.)"""
        rel = self.norm(rel)
        if self.exists(rel):
            return rel
        d, _, name = rel.rpartition('/')
        if not name.isdigit() or not self.isdir(d) or self.mrg(d) is None:
            return None
        e = self.entry(d, int(name))
        if e is None or e.is_dir:
            return None
        return e.path

    def read_resolved(self, rel):
        """read(resolve(rel)); GameFileError nếu không giải được."""
        r = self.resolve(rel)
        if r is None:
            raise GameFileError('khong co file %s (ke ca qua mrg)' % rel)
        return self.read(r)
