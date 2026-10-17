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
Kiểu (cột 3) — lớp Java tự NGẮT DÒNG lúc chạy theo bề rộng thật của khung (w ô x 9 px, w = số script truyền cho
addTextbox, đúng lúc chuỗi được đặt vào khung):
    N  dòng đầu là tên người nói (giữ nguyên), các dòng còn lại trong mỗi trang đã được nối lại -> Java ngắt lấp đầy
    J  mọi dòng trong trang đã được nối lại -> Java ngắt lấp đầy
    L  giữ nguyên các dòng (bảng, câu có mã B0xx như vtext.reflow của D:\\LOD);
       Java chỉ ngắt (ở dấu cách) dòng nào dài hơn w để game không cắt giữa chữ. Cột 4, 5 (tuỳ chọn): bản đã nối dòng
       + kiểu N/J của nó — Java dùng bản này khi có dòng (không phải dòng cuối trang) dài hơn khung, để không còn chữ
       đứng lẻ trước chỗ xuống dòng cứng (build.py v1.11 của D:\\LOD: cut_before_break -> reflow force=True).
    C  không bao giờ ngắt (hộp lựa chọn — vạch chọn và lựa chọn trả về đi theo số dòng; khung 1 dòng: choices.json
       "choice" + "dong1"); dòng dài hơn khung thì Java nới khung cho vừa (như bản PS1: khung vừa dòng dài nhất).
Quy tắc nhận tên người nói và nối dòng lấy từ build.py / vtext.reflow của D:\\LOD (v1.11: speaker_line — clause_like,
"X, the Y", tên Việt đã biết; dòng sau tên mở bằng số chèn {A8xx} hoặc ngoặc kép + chữ hoa cũng là câu).

Bí danh: SC tự sửa 12 câu tiếng Anh trong script (Severed-Chains/patches/scripts/**/*.diff, dòng "-data str[...]" /
"+data str[...]"; biến môi trường SC_ROOT để đổi chỗ, như sc_lang/sc_font), khoá tra của các câu đó đổi theo. sc_patch_pairs() đọc các cặp
đó, đổi tag SC sang tag của bảng (<line> {n}, <multibox> {p}, <speed=0> {A500}, <colour=5> {A705}, <action=lod:x>
{C0LL} + tên đóng gói 2 ký tự/mã, ký tự theo bảng mã của script-recompiler: ` {000E}, @ ○, + □, □ {0056}) rồi ghi thêm
dòng "<câu Anh của SC> <chữ Việt> <kiểu>"; chữ Việt sửa theo SC_VI_FIX (nút bấm -> <action>, bỏ dấu cách thừa...).
Không khớp đủ 12 câu (SC đổi bản vá) thì dừng.
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

SC = os.environ.get('SC_ROOT', os.path.join(ROOT, 'Severed-Chains'))

CODE = re.compile(r'\{[0-9A-Fa-f]{4}\}')
UNKNOWN = re.compile(r'\?{2,}')
PUNCT = re.compile(r'[.,!?…:"]')
VAR_START = re.compile(r'(?:\{[0-9A-Fa-f]{4}\})*\{A8[0-9A-Fa-f]{2}\}')   # dòng mở đầu bằng số chèn {A8xx}


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


def opens_sentence(line):
    """dòng (Anh, dạng tag) mở đầu như một câu sau dòng tên: chữ hoa, ngoặc kép/ngoặc đơn + chữ hoa, hoặc số chèn {A8xx}.
    Không có hai trường hợp sau thì tên dài > 24 ký tự bị nối vào câu (S02757 "Monster Conquest Game Stand{n}{A800}…
    point(s)!", S11045 'Legislation Center Lapto 5{n}"THOSE…', S12214 'Event{n}"Description…')."""
    s = CODE.sub('', line).strip()
    return s[:1].isupper() or (s[:1] in '"(' and s[1:2].isupper()) or VAR_START.match(line) is not None


# Như build.py v1.11 của D:\LOD (speaker_line, 17/10/2026): dòng đầu (Anh) có từ chỉ gặp trong mệnh đề (đại từ, trợ động
# từ, từ hỏi) hoặc kết thúc bằng từ nối / danh xưng đứng trước tên là câu bị ngắt dòng, KHÔNG phải tên người nói
# ("My dream is to fill all of{n}Tiberoa…", "I heard that the rowdy Princess{n}Emille…", mảnh câu lặp lại lọt vào
# speakers() như "I might as well take").
CLAUSE = set("""i i'm i'll i've i'd me my mine myself you you're you've you'll your yours yourself we we're we've our ours
us he he's his him she she's her hers it it's its they they're their them there there's here this that these those
is isn't are aren't was wasn't were weren't am be been being has hasn't have haven't had do does did don't doesn't
didn't can can't cannot could couldn't will won't would wouldn't should shouldn't shall may might must
how what what's when where why who whom whose which if because not let let's please""".split())
TAIL = set("""of the a an for to in on at by from with into onto than as and or but nor so like about called named since
until while though although after before during through over under between all every some any such very more most
also just even too""".split())     # viết thường: "Ghost Knight A" là tên
TITLE = {'Miss', 'Mr', 'Mrs', 'Ms', 'Dr'}     # "The perky dance by Miss{n}Meru is very entertaining."
APPOS = re.compile(r"[A-Z][\w' -]*, the [\w' -]+")   # "Gorgaga, the berserk warrior" (S03659–61): dấu phẩy trong tên


def clause_like(s):
    ws = re.findall(r"[A-Za-z][A-Za-z']*", s)
    return bool(ws) and (any(w.lower() in CLAUSE for w in ws) or ws[-1] in TAIL or ws[-1] in TITLE)


def vi_speakers(en, vi, spk):
    """dòng đầu tiếng Việt của các câu có dòng tên người nói chắc chắn: nhận ra tên cả khi chuỗi Anh có tiền tố rác do
    lệnh script trỏ lệch (", q Greham{n}You have Servi's strength…" S04096) — như build.vi_speakers của D:\\LOD v1.11."""
    out = set()
    for uid, txt in en.items():
        vn = vi.get(uid)
        if not vn or '{n}' not in txt.split('{p}')[0] or '{n}' not in vn.split('{p}')[0]:
            continue
        e0 = CODE.sub('', txt.split('{n}')[0]).strip()
        v0 = CODE.sub('', unicodedata.normalize('NFC', vn).split('{n}')[0]).strip()
        if v0 and (UNKNOWN.fullmatch(e0) or (e0 in spk and not clause_like(e0))):
            out.add(v0)
    return out


def is_name(en, vi, spk, vnames):
    """dòng đầu là tên người nói (build.speaker_line của D:\\LOD v1.11): chưa lộ diện ("???"); dòng đầu Anh hay làm tên
    (speakers); dòng đầu Việt là tên đã biết (vi_speakers); hoặc dòng Anh ngắn không dấu câu (trừ "X, the Y") + dòng Việt
    không dấu câu + dòng sau mở đầu như câu (opens_sentence). Trừ khi dòng Anh trông như mệnh đề (clause_like)."""
    raw = en.split('{p}')[0].split('{n}')
    ens = [CODE.sub('', x).strip() for x in raw]
    if len(ens) < 2:
        return False
    if UNKNOWN.fullmatch(ens[0]):
        return True
    if clause_like(ens[0]):
        return False
    v0 = CODE.sub('', vi.split('{n}')[0]).strip()
    if ens[0] in spk or (v0 in vnames and '{n}' in vi.split('{p}')[0]):
        return True
    looks = (len(ens[0]) <= 32 and (not PUNCT.search(ens[0]) or APPOS.fullmatch(ens[0]))
             and v0 and not PUNCT.search(v0))
    return bool(looks and opens_sentence(raw[1]))


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


# Bảng mã ký tự của script-recompiler (LodString.fromString)
SC_CHARS = {' ': 0x00, ',': 0x01, '.': 0x02, '·': 0x03, ':': 0x04, '?': 0x05, '!': 0x06, '_': 0x07, '/': 0x08, "'": 0x09,
            '"': 0x0a, '(': 0x0b, ')': 0x0c, '-': 0x0d, '`': 0x0e, '%': 0x0f, '&': 0x10, '*': 0x11, '@': 0x12, '+': 0x13,
            '~': 0x14, '[': 0x53, ']': 0x54, ';': 0x55, '□': 0x56}
SC_CHARS.update({c: 0x15 + i for i, c in enumerate('0123456789')})
SC_CHARS.update({c: 0x1f + i for i, c in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ')})
SC_CHARS.update({c: 0x39 + i for i, c in enumerate('abcdefghijklmnopqrstuvwxyz')})
# Mã glyph -> ký tự trong tag của bảng (như tools/dump.py của D:\LOD và ScriptTextTranslations.RETAIL; 0x0e không giải)
RETAIL = ' ,.·:?!_/\'"()-×%&*○□△0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz[];'
SC_CONTROLS = {'line': 0xa1ff, 'button': 0xa200, 'multibox': 0xa3ff, 'speed': 0xa500, 'pause': 0xa600,
               'colour': 0xa700, 'var': 0xa800, 'xoffset': 0xad00, 'yoffset': 0xae00, 'sauto': 0xb000,
               'element': 0xb100, 'arrow': 0xb200, 'action': 0xc000, 'chr': 0}

# Sửa chữ Việt của các câu SC đổi (theo uid của D:\LOD): [(cũ, mới)], "mới" viết được bằng tag SC (<action=...>);
# hoặc cả câu cho câu D:\LOD không dịch. Mỗi "cũ" phải có trong chữ Việt (sau khi nối dòng theo kiểu).
SC_VI_FIX = {
    'S12563': [('nút {000E}', '<action=lod:bttl_attack>')],         # SC: "press <action>."
    'S12568': [('Nhấn nút ○', 'Nhấn <action=lod:bttl_counter>')],   # SC: "Press <action> when..."
    'S04301': [('{000E}', '<action=lod:bttl_attack>')],             # SC: "Press the <action> button"
    'S03598': [('{000E}', '<action=lod:smap_interact>')],
    'S03709': [('{000E}', '<action=lod:smap_interact>')],
    'S13556': [(' Nội chiến à!? ', 'Nội chiến à!?')],               # SC bỏ dấu cách thừa
    'S05792': [(' Thị trưởng nói đúng.', 'Thị trưởng nói đúng.')],  # SC: " he Mayor" -> "The Mayor"
    'S08018': [(' Trước Rồng', 'Trước Rồng')],                      # SC: " gainst" -> "Against"
    'S02777': '{B001}{n}1{n}2{n}3{n}4{n}5{n}Hủy{n}',                # SC: "?" -> "Cancel"
}


def sc_codes(text):
    """chuỗi trong data str[...] của SC -> (danh sách mã 16-bit, có <noterm> không)"""
    out, noterm, i = [], False, 0
    while i < len(text):
        c = text[i]
        if c == '<':
            end = text.index('>', i)
            m = re.fullmatch(r'<\s*([a-z]+)(?:\s*=\s*([^>]*?))?\s*>', text[i:end + 1], re.I)
            name, param = m.group(1).lower(), m.group(2)
            if name == 'noterm':
                noterm = True
            elif name == 'action':
                out.append(0xc000 | len(param))
                for n in range((len(param) + 1) // 2):
                    w = ord(param[2 * n])
                    if 2 * n + 1 < len(param):
                        w |= ord(param[2 * n + 1]) << 8
                    out.append(w)
            elif param is None:
                out.append(SC_CONTROLS[name])
            else:
                out.append(SC_CONTROLS[name] | int(param, 0))
            i = end + 1
            continue
        out.append(SC_CHARS[c])
        i += 1
    return out, noterm


def codes_to_text(codes):
    """như codes_to_text của D:\\LOD tools/dump.py và ScriptTextTranslations.toTags"""
    s = ''
    for c in codes:
        if c == 0xa1ff:
            s += '{n}'
        elif c == 0xa3ff:
            s += '{p}'
        elif c < len(RETAIL) and c != 0x0e:
            s += RETAIL[c]
        else:
            s += '{%04X}' % c
    return s


def sc_tags(text):
    """chữ lẫn tag SC (<action=...>) -> chỉ tag của bảng"""
    return re.sub(r'<[^>]*>', lambda m: codes_to_text(sc_codes(m.group(0))[0]), text)


def sc_patch_pairs():
    """[(câu Anh gốc, câu Anh SC, noterm)] từ patches/scripts/**/*.diff của SC, dạng tag của bảng"""
    pairs = []
    for f in sorted(glob.glob(os.path.join(SC, 'patches', 'scripts', '**', '*.diff'), recursive=True)):
        minus = []
        for line in open(f, encoding='utf-8'):
            line = line.rstrip('\n')
            if line.startswith('-data str['):
                minus.append(line[len('-data str['):-1])
            elif line.startswith('+data str['):
                (oc, ont), (nc, nnt) = sc_codes(minus.pop(0)), sc_codes(line[len('+data str['):-1])
                assert ont == nnt, f
                if ont:
                    # script-recompiler đóng 2 mã/word: phần <noterm> lẻ mã được đệm 0x00 (dấu cách) trước phần sau
                    # (DRGN22/1137: "Valley" dài hơn "Vally" 1 ký tự -> "to  find" hai dấu cách)
                    oc, nc = oc + [0] * (len(oc) % 2), nc + [0] * (len(nc) % 2)
                pairs.append((codes_to_text(oc), codes_to_text(nc), ont))
            elif not line.startswith(('-', '+')):
                minus = []
    return pairs


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
    vnames = vi_speakers(en, vi, spk)
    pairs = [] if only else sc_patch_pairs()
    if not only and len(pairs) != 12:
        print('LOI: patches/scripts cua SC (%s) co %d cau doi, can 12: kiem lai SC_VI_FIX' % (SC, len(pairs)))
        sys.exit(1)

    os.makedirs(os.path.join(OUT, 'lang'), exist_ok=True)
    stat = collections.Counter()
    aliases = []
    with open(os.path.join(OUT, 'lang', 'dialogue.vi.tsv'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('# Bang thoai tieng Viet cho Severed Chains (tools/sc_dialogue.py). '
                'Cot: chu Anh dang tag | chu Viet | kieu N/J/L/C [| ban noi dong | kieu N/J] (kieu L)\n')
        for uid, e in en.items():
            if not uid.startswith('S') or (uid not in vi and uid not in SC_VI_FIX) or (only and uid not in only):
                continue
            fix = SC_VI_FIX.get(uid, [])
            v = unicodedata.normalize('NFC', vi[uid] if uid in vi else sc_tags(fix))
            if '\t' in e or '\t' in v or '\n' in v:
                stat['bo'] += 1
                continue
            alt = ''
            if uid in keep:
                mode = 'C'
            elif re.search(r'\{B0[0-9A-Fa-f]{2}\}', v):
                mode = 'L'
                # câu có mã {B0xx}: giữ chỗ xuống dòng của người dịch; nếu lúc chạy có dòng dài hơn khung (không phải dòng
                # cuối trang) thì ngắt lấp đầy sẽ để chữ lẻ trước {n} cứng ("…phủ xanh / cả / Tiberoa", S12610) -> Java
                # dùng bản nối dòng này (build.py v1.11 của D:\LOD: reflow force=True)
                named = is_name(e, v, spk, vnames)
                joined = reflow(v, named)
                if joined != v:
                    alt = '\t%s\t%s' % (joined, 'N' if named else 'J')
                    stat['L_noi'] += 1
            elif is_name(e, v, spk, vnames):
                mode = 'N'
                v = reflow(v, True)
            else:
                mode = 'J'
                v = reflow(v, False)
            for old, new, noterm in pairs:
                if e == old or (noterm and e.startswith(old)):
                    va = v
                    for a, b in (fix if isinstance(fix, list) else []):
                        assert a in va, (uid, a, va)
                        va = va.replace(a, sc_tags(b))
                    aliases.append((new + e[len(old):], va, mode))
            if uid in vi:
                stat[mode] += 1
                f.write('%s\t%s\t%s%s\n' % (e, v, mode, alt))
        for row in aliases:
            f.write('%s\t%s\t%s\n' % row)
    if len(aliases) != len(pairs):
        print('LOI: %d/%d cau SC doi khop duoc cau cua D:\\LOD' % (len(aliases), len(pairs)))
        sys.exit(1)
    print('dialogue.vi.tsv: %d cau (N co ten %d, J noi dong %d, L giu dong %d [co ban noi %d], C khong ngat %d, bo %d)'
          ' + %d bi danh SC' % (sum(stat[k] for k in 'NJLC'), stat['N'], stat['J'], stat['L'], stat['L_noi'], stat['C'],
                                stat['bo'], len(aliases)))


if __name__ == '__main__':
    main()
