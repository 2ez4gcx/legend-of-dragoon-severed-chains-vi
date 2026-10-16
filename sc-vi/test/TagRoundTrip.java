import legend.core.font.Font;
import legend.game.i18n.ScriptTextTranslations;
import legend.game.types.LodString;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.function.IntUnaryOperator;

/**
 * Tự kiểm ScriptTextTranslations (không cần chạy game).
 * Gọi: java -cp "out/test;out/classes;game/lod-game-*.jar;game/libs/*" TagRoundTrip out/lang/dialogue.vi.tsv out/fonts/vietnamese.json
 * 1. Cột Anh và cột Việt: fromTags -> toTags phải ra đúng chuỗi (khoá tra bảng tính từ mã LodString như dump.py của D:\LOD);
 *    ký tự ngoài bảng gốc -> UNICODE_BASE + mã, fromLodChar trả lại đúng ký tự.
 * 2. wrap(chữ Việt, kiểu, w) với w = 16, 20, 24, 28, 32, 36 — đếm ký tự (mỗi ký tự 1) VÀ điểm ảnh của font Việt
 *    (bề rộng w*9 px, bước = glyph.w + 1 như Text.renderTextboxText; số {A8xx} và nút <action> đo như ScriptTextTranslations.widths):
 *    - bỏ hết xuống dòng/dấu cách thì giống hệt bản trước khi ngắt (không mất/đổi chữ, mã điều khiển);
 *    - không dòng nào dài hơn w ô, trừ dòng tên người nói (kiểu N) và dòng chỉ có một từ dài hơn w;
 *    - số trang ({p}) giữ nguyên; kiểu C (hộp chọn, khung 1 dòng): không đổi một mã nào.
 * 3. Như trong game (loadTable + lookup + layout, đúng đường Text/SMap.applyGrid đi): mọi câu Anh tra ra bản dịch, original()
 *    trả lại chuỗi gốc; với khung w = dòng Anh dài nhất và w + 4:
 *    - kiểu C: số dòng giữ nguyên (vạch chọn/lựa chọn trả về theo dòng), khung nới đủ cho dòng rộng nhất (tối đa 34 ô);
 *    - kiểu N/J/L: dòng vừa khung (trừ dòng tên/dòng một từ), khung giữ bề rộng gốc; kiểu N: dòng tên giữ nguyên;
 *    - lưới ký tự >= khung và >= số ô dòng dài nhất cần (số {A8xx} 10 ô) — engine không tự ngắt dòng lần nữa.
 * 4. Ca riêng: hack "?Funds ?G" của SC (quán trọ) vẫn nhận ra chuỗi gốc; hộp "DÙNG CỬA HÀNG?" (khung 10) giữ 3 dòng;
 *    bí danh câu SC đã sửa tra được (kể cả câu Lisa có phần <noterm> đệm dấu cách, chép từ dialogue_missing trong game;
 *    S08018, S10558, S02777 đã thấy trong game); <action> chiếm 1 ô lưới; hộp chọn số 1-5 "Hủy" giữ 8 dòng trong khung 6;
 *    tên dài + dòng sau mở bằng số chèn/ngoặc kép (Quầy Diệt Quái, Lapto 5) là kiểu N, dòng tên đứng riêng.
 * Exit 0 = đạt.
 */
public final class TagRoundTrip {
  private static int bad;

  private static void fail(final String msg) {
    if(bad < 20) {
      System.out.println(msg);
    }
    bad++;
  }

  private static String strip(final int[] codes) {
    final StringBuilder sb = new StringBuilder();
    for(final int c : codes) {
      if(c != 0xa1ff && c != 0x00) {
        sb.append(Integer.toHexString(c)).append(',');
      }
    }
    return sb.toString();
  }

  private static boolean visible(final int c) {
    return c < 0xa000 || c >= LodString.UNICODE_BASE;
  }

  private static int[] codes(final LodString str) {
    final int[] out = new int[str.length() + 1];
    for(int i = 0; i < out.length; i++) {
      out[i] = str.charAt(i);
    }
    return out;
  }

  /** Lines of a code array: [line codes without line/page/end] */
  private static List<int[]> lines(final int[] codes) {
    final List<int[]> out = new ArrayList<>();
    int start = 0;
    for(int i = 0; i < codes.length; i++) {
      final int c = codes[i];
      if(c == 0xa1ff || c == 0xa3ff || c == 0xa0ff) {
        out.add(java.util.Arrays.copyOfRange(codes, start, i));
        start = i + 1;
        if(c == 0xa0ff) {
          break;
        }
      }
    }
    return out;
  }

  private static int width(final int[] line, final IntUnaryOperator adv) {
    int w = 0;
    for(final int x : ScriptTextTranslations.widths(line, adv)) {
      w += x;
    }
    return w;
  }

  private static int words(final int[] line) {
    int words = 0;
    boolean inWord = false;
    for(final int c : line) {
      if(c == 0x00) {
        inWord = false;
      } else if(!inWord) {
        inWord = true;
        words++;
      }
    }
    return words;
  }

  private static int pages(final int[] codes) {
    int n = 0;
    for(final int c : codes) {
      if(c == 0xa3ff) {
        n++;
      }
    }
    return n;
  }

  private static String tags(final int[] codes) {
    return ScriptTextTranslations.toTags(new LodString(codes));
  }

  public static void main(final String[] args) throws Exception {
    final List<String> lines = Files.readAllLines(Path.of(args[0]), StandardCharsets.UTF_8);
    final Font font = new legend.core.font.FontManager().get(Path.of(args[1]));
    final IntUnaryOperator count = c -> visible(c) ? 1 : 0;
    final IntUnaryOperator pixels = c -> visible(c) ? font.charWidth(LodString.fromLodChar(c)) + 1 : 0;
    ScriptTextTranslations.loadTable(Path.of(args[0]));
    int n = 0;
    int widened = 0;

    for(final String line : lines) {
      if(line.startsWith("#")) {
        continue;
      }

      final String[] cols = line.split("\t", -1);

      // 1. tags
      for(int col = 0; col < 2; col++) {
        final String s = cols[col];
        final int[] codes = ScriptTextTranslations.fromTags(s);

        if(!tags(codes).equals(s)) {
          fail("LECH tag: [" + s + "] -> [" + tags(codes) + "]");
        }

        for(final int c : codes) {
          if(c >= LodString.UNICODE_BASE && LodString.fromLodChar(c) != (char)(c - LodString.UNICODE_BASE)) {
            fail("fromLodChar sai: " + Integer.toHexString(c));
          }
        }
      }

      final char mode = cols[2].charAt(0);
      final int[] vi = ScriptTextTranslations.fromTags(cols[1]);

      // 2. wrap
      for(int k = 0; k < 12; k++) {
        final int w = 16 + (k % 6) * 4;
        final IntUnaryOperator adv = k < 6 ? count : pixels;
        final int max = k < 6 ? w : w * 9;
        final int[] out = ScriptTextTranslations.wrap(vi, mode, max, adv);

        if(mode == 'C' && !java.util.Arrays.equals(out, vi)) {
          fail("KIEU C bi ngat (w=" + w + "): " + cols[1]);
        }

        if(!strip(out).equals(strip(vi))) {
          fail("NOI DUNG doi (w=" + w + "): " + cols[1] + " -> " + tags(out));
        }

        final List<int[]> ls = lines(out);
        for(int i = 0; i < ls.size(); i++) {
          final boolean nameLine = mode == 'N' && i == 0;
          if(mode != 'C' && !nameLine && words(ls.get(i)) > 1 && width(ls.get(i), adv) > max) {
            fail("TRAN KHUNG " + (k < 6 ? "o" : "px") + " max=" + max + " (" + width(ls.get(i), adv) + "): " + tags(ls.get(i)) + "  <- " + cols[1]);
          }
        }

        if(pages(vi) != pages(out)) {
          fail("SO TRANG doi: " + cols[1]);
        }
      }

      // 3. lookup + layout as in game
      final LodString en = new LodString(ScriptTextTranslations.fromTags(cols[0]));
      final LodString tr = ScriptTextTranslations.lookup(en, font);

      if(!(tr instanceof ScriptTextTranslations.Translated) || ScriptTextTranslations.original(tr) != en) {
        fail("KHONG TRA DUOC: " + cols[0]);
        continue;
      }

      int enWidth = 1;
      for(final int[] l : lines(ScriptTextTranslations.fromTags(cols[0]))) {
        int v = 0;
        for(final int c : l) {
          if(visible(c)) {
            v++;
          }
        }
        enWidth = Math.max(enWidth, v);
      }

      for(final int box : new int[] {enWidth, enWidth + 4}) {
        final ScriptTextTranslations.Layout layout = ScriptTextTranslations.layout(tr, box, font);
        final int[] out = codes(layout.str());
        final List<int[]> ls = lines(out);

        if(!strip(out).equals(strip(vi)) || pages(out) != pages(vi)) {
          fail("LAYOUT doi noi dung (box " + box + "): " + cols[1] + " -> " + tags(out));
        }

        if(mode == 'C') {
          if(ls.size() != lines(vi).size()) {
            fail("HOP CHON doi so dong (box " + box + "): " + cols[1] + " -> " + tags(out));
          }

          int widest = 0;
          for(final int[] l : ls) {
            widest = Math.max(widest, width(l, pixels));
          }

          if(widest > layout.boxChars() * 9 && layout.boxChars() < 34) {
            fail("HOP CHON khong noi khung (box " + box + " -> " + layout.boxChars() + ", " + widest + " px): " + cols[1]);
          }

          if(layout.boxChars() > box) {
            widened++;
          }
        } else {
          if(layout.boxChars() != box) {
            fail("KHUNG doi (" + box + " -> " + layout.boxChars() + "): " + cols[1]);
          }

          // Kiểu N: dòng tên người nói đứng riêng, không bị nối/ngắt
          if(mode == 'N' && !tags(ls.get(0)).equals(cols[1].split("\\{[np]\\}", 2)[0])) {
            fail("DONG TEN bi doi (box " + box + "): " + tags(ls.get(0)) + "  <- " + cols[1]);
          }

          for(int i = 0; i < ls.size(); i++) {
            final boolean nameLine = mode == 'N' && i == 0;
            if(!nameLine && words(ls.get(i)) > 1 && width(ls.get(i), pixels) > box * 9) {
              fail("LAYOUT tran khung " + box * 9 + " px (" + width(ls.get(i), pixels) + "): " + tags(ls.get(i)) + "  <- " + cols[1]);
            }
          }
        }

        if(layout.gridChars() < layout.boxChars() || layout.gridChars() < Math.min(ScriptTextTranslations.maxLineCells(out), 64)) {
          fail("LUOI nho (" + layout.gridChars() + " < " + ScriptTextTranslations.maxLineCells(out) + "): " + cols[1]);
        }
      }

      n++;
    }

    // 4. special cases
    final LodString funds = new LodString(ScriptTextTranslations.fromTags("{B000}Funds {A800}G"));
    final LodString fundsVi = ScriptTextTranslations.lookup(funds, font);
    if(fundsVi == funds || !"?Funds ?G".equals(ScriptTextTranslations.original(fundsVi).get())) {
      fail("FUNDS: hack quan tro khong nhan ra chuoi goc");
    }

    final LodString shop = new LodString(ScriptTextTranslations.fromTags("{B000}USE SHOP?{n}DO NOT USE{n}USE"));
    final ScriptTextTranslations.Layout shopLayout = ScriptTextTranslations.layout(ScriptTextTranslations.lookup(shop, font), 10, font);
    if(lines(codes(shopLayout.str())).size() != 3 || shopLayout.boxChars() <= 10) {
      fail("HOP CUA HANG: " + ScriptTextTranslations.toTags(shopLayout.str()) + " khung " + shopLayout.boxChars());
    }

    // Chuỗi đúng như SC đọc trong game (dialogue_missing.vi.txt): phần <noterm> lẻ mã được đệm 0x00 -> "to  find" 2 dấu cách
    for(final String key : new String[] {"{A500}Dart{n}Is this civil war!?",
      "Lisa{n}I heard you are heading to the{n}{A705}Valley of Corrupted Gravity{A700}.{n}And I have a favor to ask.{n}I would like you to  find out about{n}the relationship between my sister{n}Emille and the Gehrich Gang."}) {
      if(!(ScriptTextTranslations.lookup(new LodString(ScriptTextTranslations.fromTags(key)), font) instanceof ScriptTextTranslations.Translated)) {
        fail("BI DANH: cau SC da sua khong tra duoc: " + key);
      }
    }

    if(ScriptTextTranslations.maxLineCells(ScriptTextTranslations.fromTags("ab{C00F}{6F6C}{3A64}{7462}{6C74}{615F}{7474}{6361}{006B}c")) != 4) {
      fail("ACTION: <action> phai chiem 1 o");
    }

    // Câu đã chụp trong game (phiên kiểm đĩa 3-4, Quầy Diệt Quái, khoá số), khoá đúng như SC đọc:
    // bí danh S08018 (Furni, SC sửa " gainst"), S10558 (Vellweb, SC bỏ "Rose" thừa), S02777 (khoá số, SC "?" -> "Cancel")
    for(final String key : new String[] {"Against a Dragon, there is{n}nothing we can do.",
      "Rose{n}Let's move on.{n}There is no reason to be{n}here now.", "{B001}{n}1{n}2{n}3{n}4{n}5{n}Cancel{n}"}) {
      if(!(ScriptTextTranslations.lookup(new LodString(ScriptTextTranslations.fromTags(key)), font) instanceof ScriptTextTranslations.Translated)) {
        fail("BI DANH: cau SC da sua khong tra duoc: " + key);
      }
    }

    // Hộp chọn số (khung 6 x 8): 7 dòng giữ nguyên, dòng cuối "Hủy" (vạch chọn dòng 6 = lựa chọn 5 = huỷ)
    final ScriptTextTranslations.Layout lock = ScriptTextTranslations.layout(ScriptTextTranslations.lookup(new LodString(ScriptTextTranslations.fromTags("{B001}{n}1{n}2{n}3{n}4{n}5{n}Cancel{n}")), font), 6, font);
    final List<int[]> lockLines = lines(codes(lock.str()));
    if(lockLines.size() != 8 || !"Hủy".equals(tags(lockLines.get(6))) || lock.boxChars() != 6) {
      fail("HOP CHON SO: " + ScriptTextTranslations.toTags(lock.str()) + " khung " + lock.boxChars());
    }

    // Tên người nói dài (> 24 ký tự) + dòng sau mở bằng số chèn / ngoặc kép: dòng tên phải đứng riêng (trước khi sửa
    // sc_dialogue.is_name, Quầy Diệt Quái hiện "Quầy Trò Chơi Diệt Quái 000000 điểm! Lại tới nhé!!" trên một dòng)
    for(final String[] c : new String[][] {
      {"{A500}Monster Conquest Game Stand{n}{A800}{A801}{A802}{A803}{A804}{A805} point(s)!{n}Come again!!", "{A500}Quầy Trò Chơi Diệt Quái", "36"},
      {"{A500}Legislation Center Lapto 5{n}\"THOSE WITH LEGAL LICENSES{n}SHALL NOT AMEND LAWS\".", "{A500}Lapto Trung Tâm Lập Pháp 5", "31"}}) {
      final LodString name = ScriptTextTranslations.lookup(new LodString(ScriptTextTranslations.fromTags(c[0])), font);
      final ScriptTextTranslations.Layout nameLayout = ScriptTextTranslations.layout(name, Integer.parseInt(c[2]), font);
      final List<int[]> nameLines = lines(codes(nameLayout.str()));
      if(!(name instanceof final ScriptTextTranslations.Translated t) || t.mode() != 'N' || nameLines.size() < 2 || !c[1].equals(tags(nameLines.get(0)))) {
        fail("DONG TEN bi noi: " + ScriptTextTranslations.toTags(nameLayout.str()));
      }
    }

    System.out.println("Kiem " + n + " cau (tag 2 cot + ngat 6 be rong x 2 kieu do + layout nhu trong game 2 khung; " + widened + " lan noi khung hop chon) + 7 ca rieng, loi " + bad);
    System.exit(bad == 0 ? 0 : 1);
  }
}
