import legend.game.i18n.ScriptTextTranslations;
import legend.game.types.LodString;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

/**
 * Tự kiểm ScriptTextTranslations (không cần chạy game).
 * Gọi: java -cp "out/test;out/classes;game/lod-game-*.jar;game/libs/*" TagRoundTrip out/lang/dialogue.vi.tsv
 * 1. Cột Anh và cột Việt: fromTags -> toTags phải ra đúng chuỗi (khoá tra bảng tính từ mã LodString như dump.py của D:\LOD);
 *    ký tự ngoài bảng gốc -> UNICODE_BASE + mã, fromLodChar trả lại đúng ký tự.
 * 2. wrap(chữ Việt, kiểu, w) với w = 16, 20, 24, 28, 32, 36 — đếm ký tự (mỗi ký tự 1) VÀ điểm ảnh của font Việt
 *    (gfx/fonts/vietnamese.json của thư mục game, bề rộng w*9 px, bước = glyph.w + 1 như Text.renderTextboxText):
 *    - bỏ hết xuống dòng/dấu cách thì giống hệt bản trước khi ngắt (không mất/đổi chữ, mã điều khiển);
 *    - không dòng nào dài hơn w ô, trừ dòng tên người nói (kiểu N) và dòng chỉ có một từ dài hơn w;
 *    - số trang ({p}) giữ nguyên; kiểu L: dòng vừa khung giữ nguyên từng mã.
 * Exit 0 = đạt.
 */
public final class TagRoundTrip {
  private static int bad;

  private static void fail(final String msg) {
    if(bad < 15) {
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

  public static void main(final String[] args) throws Exception {
    final List<String> lines = Files.readAllLines(Path.of(args[0]), StandardCharsets.UTF_8);
    final legend.core.font.Font font = new legend.core.font.FontManager().get(Path.of(args[1]));
    final java.util.function.IntUnaryOperator count = c -> visible(c) ? 1 : 0;
    final java.util.function.IntUnaryOperator pixels = c -> visible(c) ? font.charWidth(LodString.fromLodChar(c)) + 1 : 0;
    int n = 0;

    for(final String line : lines) {
      if(line.startsWith("#")) {
        continue;
      }

      final String[] cols = line.split("\t", -1);

      for(int col = 0; col < 2; col++) {
        final String s = cols[col];
        final int[] codes = ScriptTextTranslations.fromTags(s);
        final String back = ScriptTextTranslations.toTags(new LodString(codes));

        if(!back.equals(s)) {
          fail("LECH tag: [" + s + "] -> [" + back + "]");
        }

        for(final int c : codes) {
          if(c >= LodString.UNICODE_BASE && LodString.fromLodChar(c) != (char)(c - LodString.UNICODE_BASE)) {
            fail("fromLodChar sai: " + Integer.toHexString(c));
          }
        }
      }

      final char mode = cols[2].charAt(0);
      final int[] vi = ScriptTextTranslations.fromTags(cols[1]);

      for(int k = 0; k < 12; k++) {
        final int w = 16 + (k % 6) * 4;
        final java.util.function.IntUnaryOperator adv = k < 6 ? count : pixels;
        final int max = k < 6 ? w : w * 9;
        final int[] out = ScriptTextTranslations.wrap(vi, mode, max, adv);

        if(!strip(out).equals(strip(vi))) {
          fail("NOI DUNG doi (w=" + w + "): " + cols[1] + " -> " + ScriptTextTranslations.toTags(new LodString(out)));
        }

        int pagesIn = 0;
        int pagesOut = 0;
        for(final int c : vi) {
          if(c == 0xa3ff) {
            pagesIn++;
          }
        }

        int width = 0;
        int words = 1;
        boolean first = true;
        int lineStart = 0;
        for(int i = 0; i < out.length; i++) {
          final int c = out[i];
          if(c == 0xa1ff || c == 0xa3ff || c == 0xa0ff) {
            final boolean nameLine = mode == 'N' && first;
            if(width > max && !nameLine && words > 1) {
              fail("TRAN KHUNG " + (k < 6 ? "o" : "px") + " max=" + max + " (" + width + "): " + ScriptTextTranslations.toTags(new LodString(java.util.Arrays.copyOfRange(out, lineStart, i))) + "  <- " + cols[1]);
            }
            if(c == 0xa3ff) {
              pagesOut++;
            }
            first = false;
            width = 0;
            words = 1;
            lineStart = i + 1;
          } else {
            width += adv.applyAsInt(c);
            if(c == 0x00 && i > lineStart) {
              words++;
            }
          }
        }

        if(pagesIn != pagesOut) {
          fail("SO TRANG doi: " + cols[1]);
        }
      }

      n++;
    }

    System.out.println("Kiem " + n + " cau (tag 2 cot + ngat dong 6 be rong x 2 kieu do), loi " + bad);
    System.exit(bad == 0 ? 0 : 1);
  }
}
