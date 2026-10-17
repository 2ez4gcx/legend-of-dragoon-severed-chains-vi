package legend.game.i18n;

import it.unimi.dsi.fastutil.ints.IntArrayList;
import it.unimi.dsi.fastutil.ints.IntList;
import legend.core.GameEngine;
import legend.core.font.Font;
import legend.game.modding.coremod.CoreMod;
import legend.game.types.LodString;
import legend.game.types.Textbox4c;
import legend.game.types.TextboxText84;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

import java.io.IOException;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.text.Normalizer;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.function.IntUnaryOperator;

import static legend.core.GameEngine.CONFIG;

/**
 * [sc-vi] Replaces textbox strings that come from retail scripts with translations.
 *
 * <p>File: {@code lang/dialogue.<language>.tsv} (UTF-8). One entry per line: {@code <english>\t<translation>\t<mode>},
 * lines starting with {@code #} are ignored. Both text columns use the tag format of the LoD Vietnamese project dumper:
 * {@code {n}} = 0xa1ff (line), {@code {p}} = 0xa3ff (new box), {@code {XXXX}} = raw 16-bit code (controls such as
 * {@code {A500}} speed, {@code {A705}} colour), other characters = retail glyph if it exists in {@link #RETAIL}, otherwise
 * the Unicode character (stored as {@link LodString#UNICODE_BASE} + codepoint, drawn with the selected font).</p>
 *
 * <p>Layout: retail textboxes are a grid of N chars x L lines drawn in 9 px cells, but glyphs are drawn with their real
 * (variable) width. {@link #applyGrid} (called when the string is put in a textbox) word-wraps the translation to the
 * PIXEL width of the retail box (N x 9 px) using the selected font, so the box keeps its retail size, then widens the
 * textbox's character grid so the engine does not break those lines again. Modes: {@code N} first line is the speaker
 * name (kept), the rest of each page is wrapped; {@code J} each page is wrapped; {@code L} explicit lines are kept and
 * only lines wider than the box are broken at spaces, unless the entry has a joined variant (columns 4-5: text, mode N/J)
 * and an explicit line other than the last of its page is wider than the box: then the variant is wrapped instead, so no
 * word is left alone before an explicit line break; {@code C} lines are never broken (selection boxes: the selection
 * bar and the selected index follow the lines; one-line boxes), the box is widened instead when a line does not fit.
 * Numbers inserted at run time ({@code {A8xx}}) get room for 3 digits (1 per code in runs like {@code {A800}{A801}})
 * when wrapping, and 10 cells in the grid. An input action ({@code {C0LL}} + LL packed ASCII bytes of its registry id,
 * {@code <action=...>} in SC script patches) takes 1 cell and room for 6 digits (key or button name).</p>
 *
 * <p>Strings without a translation are left untouched. With {@code -Dscvi.logMissing=true} every untranslated string is
 * appended once to {@code dialogue_missing.<language>.txt} (to measure coverage while playing).</p>
 */
public final class ScriptTextTranslations {
  private ScriptTextTranslations() { }

  private static final Logger LOGGER = LogManager.getFormatterLogger(ScriptTextTranslations.class);

  /** Retail glyph codes 0x00-0x55, same order as tools/dump.py of the LoD Vietnamese project (0x0e is never decoded) */
  private static final String RETAIL = " ,.·:?!_/'\"()-×%&*○□△0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz[];";

  /** Retail cell width */
  private static final int CELL = 9;
  /** Upper bound for the widened character grid */
  private static final int MAX_GRID = 64;
  /** Upper bound for a widened box (C mode), in cells: stays inside the 320 px screen */
  private static final int MAX_BOX = 34;
  /** Grid cells for a number inserted at run time (TextboxText84.digits_46) */
  private static final int VAR_CELLS = 10;
  /** Room (in digits) for the key/button name of an input action */
  private static final int ACTION_DIGITS = 6;

  private static final int SPACE = 0x00;
  private static final int DIGIT_0 = 0x15;
  private static final int LINE = 0xa1ff;
  private static final int PAGE = 0xa3ff;
  private static final int END = 0xa0ff;

  /**
   * @param alt L mode only, may be null: the same translation with its lines joined (mode {@code altMode}), used when an
   *            explicit line (not the last of its page) is wider than the box, so wrapping it would leave a word or two
   *            alone on a line before the explicit line break
   */
  private record Entry(String text, char mode, String alt, char altMode) { }

  private record Wrapped(int[] codes, int widestLine) { }

  /** A translated textbox string, wrapped for one box width; keeps what is needed to wrap it again for the real box */
  public static final class Translated extends LodString {
    /** The retail string this translation replaces */
    public final LodString original;
    private final String key;
    private final Entry entry;
    private final int boxChars;
    private final Font font;
    /** Grid cells the longest line needs */
    private final int gridChars;
    /** Widest line in pixels */
    private final int widestLine;

    private Translated(final LodString original, final String key, final Entry entry, final int boxChars, final Font font, final Wrapped wrapped) {
      super(wrapped.codes);
      this.original = original;
      this.key = key;
      this.entry = entry;
      this.boxChars = boxChars;
      this.font = font;
      this.gridChars = maxLineCells(wrapped.codes);
      this.widestLine = wrapped.widestLine;
    }

    public char mode() {
      return this.entry.mode;
    }
  }

  private static Locale loadedLocale;
  private static Map<String, Entry> table = Map.of();
  private static final Map<String, Wrapped> encoded = new HashMap<>();
  private static final Set<String> missingLogged = new HashSet<>();

  /** The retail string a translation replaced (for code that checks the retail text), or the string itself */
  public static LodString original(final LodString str) {
    return str instanceof final Translated translated ? translated.original : str;
  }

  public static LodString translate(final LodString original) {
    try {
      ensureLoaded();
      return lookup(original, GameEngine.DEFAULT_FONT);
    } catch(final Throwable t) {
      LOGGER.warn("Failed to translate textbox string", t);
      return original;
    }
  }

  /** Looks a retail string up in the loaded table: its translation, or the string itself */
  public static LodString lookup(final LodString original, final Font font) {
    if(table.isEmpty()) {
      return original;
    }

    final String key = toTags(original);
    final Entry entry = table.get(key);

    if(entry == null) {
      logMissing(key);
      return original;
    }

    // Wrapped for a guess of the box width; applyGrid wraps it again for the real box
    return wrapFor(original, key, entry, longestLine(original), font);
  }

  /**
   * A string laid out in a textbox
   *
   * @param boxChars box width in chars (textbox chars_18 - 1)
   * @param gridChars character grid width (textbox text chars_1c), may be wider than the box
   */
  public record Layout(LodString str, int boxChars, int gridChars) { }

  /**
   * Wraps a translation to a box {@code boxChars} wide (C mode: widens the box instead when a line doesn't fit) and
   * widens the character grid so no line is broken again by the engine. Other strings are returned unchanged.
   */
  public static Layout layout(final LodString str, final int boxChars, final Font font) {
    if(!(str instanceof final Translated translated)) {
      return new Layout(str, boxChars, boxChars);
    }

    final Translated wrapped = translated.boxChars == boxChars && translated.font == font ? translated : wrapFor(translated.original, translated.key, translated.entry, boxChars, font);
    int box = boxChars;

    if(wrapped.entry.mode == 'C') {
      box = Math.max(box, Math.min((wrapped.widestLine + CELL - 1) / CELL, MAX_BOX));
    }

    return new Layout(wrapped, box, Math.max(box, Math.min(wrapped.gridChars, MAX_GRID)));
  }

  public static void applyGrid(final Textbox4c textbox, final TextboxText84 textboxText) {
    applyGrid(textbox, textboxText, GameEngine.DEFAULT_FONT);
  }

  /**
   * Call after the string is set and {@code chars_1c} is the retail box width (clearTextboxText), before allocating
   * {@code chars_58}: lays a translation out with {@link #layout} (the box keeps its retail width, except C mode lines
   * that don't fit)
   */
  public static void applyGrid(final Textbox4c textbox, final TextboxText84 textboxText, final Font font) {
    if(!(textboxText.str_24 instanceof Translated)) {
      return;
    }

    try {
      final Layout layout = layout(textboxText.str_24, textboxText.chars_1c, font);
      textboxText.str_24 = layout.str;

      if(layout.boxChars != textboxText.chars_1c) {
        textbox.chars_18 = layout.boxChars + 1;
      }

      textboxText.chars_1c = layout.gridChars;
    } catch(final Throwable t) {
      LOGGER.warn("Failed to lay out textbox translation", t);
    }
  }

  private static Translated wrapFor(final LodString original, final String key, final Entry entry, final int boxChars, final Font font) {
    final IntUnaryOperator advance = c -> advance(font, c);
    final Wrapped wrapped = encoded.computeIfAbsent(key + '\u0000' + boxChars + '\u0000' + System.identityHashCode(font), k -> {
      final int[] codes = wrapText(entry.text, entry.mode, entry.alt, entry.altMode, boxChars * CELL, advance);
      return new Wrapped(codes, widestLine(codes, advance));
    });
    return new Translated(original, key, entry, boxChars, font, wrapped);
  }

  /**
   * Wraps a TSV entry for a box {@code maxWidth} wide: L mode with a joined variant ({@code alt}) uses the variant when
   * an explicit line other than the last of its page is wider than the box
   */
  public static int[] wrapText(final String text, final char mode, final String alt, final char altMode, final int maxWidth, final IntUnaryOperator advance) {
    final int[] codes = fromTags(text);
    if(mode == 'L' && alt != null && cutBeforeBreak(codes, maxWidth, advance)) {
      return wrap(fromTags(alt), altMode, maxWidth, advance);
    }

    return wrap(codes, mode, maxWidth, advance);
  }

  /** An explicit line that is not the last of its page is wider than {@code maxWidth} (vtext.cut_before_break of D:\LOD) */
  public static boolean cutBeforeBreak(final int[] codes, final int maxWidth, final IntUnaryOperator advance) {
    final IntList line = new IntArrayList();
    for(final int c : codes) {
      if(c == LINE || c == PAGE || c == END) {
        if(c == LINE) {
          int width = 0;
          for(final int w : widths(line.toIntArray(), advance)) {
            width += w;
          }

          if(width > maxWidth) {
            return true;
          }
        }

        line.clear();
        if(c == END) {
          break;
        }
      } else {
        line.add(c);
      }
    }

    return false;
  }

  /** Pixel advance of one code with the given font, as drawn by Text.renderTextboxText (glyph width + 1) */
  private static int advance(final Font font, final int c) {
    if(!visible(c)) {
      return 0;
    }

    final char chr = LodString.fromLodChar(c);
    return font != null ? font.charWidth(chr) + 1 : CELL;
  }

  private static synchronized void ensureLoaded() {
    final Locale locale;
    try {
      locale = CONFIG.getConfig(CoreMod.LANGUAGE_CONFIG.get());
    } catch(final Throwable t) {
      return; // config not ready yet
    }

    if(locale == null || locale.equals(loadedLocale)) {
      return;
    }

    loadedLocale = locale;
    loadTable(Path.of("lang", "dialogue." + locale.getLanguage() + ".tsv"));
  }

  /** Replaces the translation table with the one in {@code file} (empty if it doesn't exist) */
  public static synchronized void loadTable(final Path file) {
    encoded.clear();
    missingLogged.clear();

    if(!Files.isRegularFile(file)) {
      table = Map.of();
      return;
    }

    final Map<String, Entry> map = new HashMap<>();
    try {
      final List<String> lines = Files.readAllLines(file, StandardCharsets.UTF_8);
      for(final String line : lines) {
        if(line.isEmpty() || line.charAt(0) == '#') {
          continue;
        }

        final String[] cols = line.split("\t", -1);
        if(cols.length < 2) {
          continue;
        }

        final char mode = cols.length > 2 && !cols[2].isEmpty() ? cols[2].charAt(0) : 'L';
        final boolean hasAlt = mode == 'L' && cols.length > 4 && !cols[3].isEmpty() && !cols[4].isEmpty();
        map.put(cols[0], new Entry(Normalizer.normalize(cols[1], Normalizer.Form.NFC), mode,
          hasAlt ? Normalizer.normalize(cols[3], Normalizer.Form.NFC) : null, hasAlt ? cols[4].charAt(0) : 'L'));
      }

      LOGGER.info("Loaded %d script text translations from %s", map.size(), file);
    } catch(final IOException e) {
      LOGGER.warn("Failed to load %s", file, e);
    }

    table = map;
  }

  /** Same as codes_to_text in tools/dump.py: the key column of the TSV */
  public static String toTags(final LodString str) {
    final StringBuilder sb = new StringBuilder();

    for(int i = 0; i < str.length() + 1; i++) {
      final int c = str.charAt(i);

      if(c == END) {
        break;
      }

      if(c == LINE) {
        sb.append("{n}");
      } else if(c == PAGE) {
        sb.append("{p}");
      } else if(c < RETAIL.length() && c != 0x0e) {
        sb.append(RETAIL.charAt(c));
      } else if(c >= LodString.UNICODE_BASE) {
        sb.append((char)(c - LodString.UNICODE_BASE));
      } else {
        sb.append("{%04X}".formatted(c));
      }
    }

    return sb.toString();
  }

  /** Tag text -> code array terminated by 0xa0ff */
  public static int[] fromTags(final String text) {
    final IntList out = new IntArrayList(text.length() + 1);

    for(int i = 0; i < text.length(); i++) {
      final char c = text.charAt(i);

      if(c == '{') {
        final int end = text.indexOf('}', i);

        if(end > i) {
          final String tag = text.substring(i + 1, end);

          if("n".equals(tag)) {
            out.add(LINE);
            i = end;
            continue;
          }

          if("p".equals(tag)) {
            out.add(PAGE);
            i = end;
            continue;
          }

          if(tag.length() == 4) {
            try {
              out.add(Integer.parseInt(tag, 16));
              i = end;
              continue;
            } catch(final NumberFormatException ignored) {
            }
          }
        }
      }

      final int retail = c == '×' ? -1 : RETAIL.indexOf(c);
      out.add(retail >= 0 ? retail : LodString.UNICODE_BASE + c);
    }

    out.add(END);
    return out.toIntArray();
  }

  /** Characters that take a cell in the textbox (controls 0xa000-0xffff don't) */
  public static boolean visible(final int c) {
    return c < 0xa000 || c >= LodString.UNICODE_BASE;
  }

  /** {A8xx}: a number inserted at run time */
  public static boolean isVar(final int c) {
    return c >>> 8 == TextboxText84.VAR;
  }

  /** {C0LL}: input action, followed by (LL + 1) / 2 words of its packed registry id */
  public static boolean isAction(final int c) {
    return c >>> 8 == TextboxText84.ACTION;
  }

  /** Number of words after an input action code that hold its registry id */
  public static int actionPayload(final int c) {
    return ((c & 0xff) + 1) / 2;
  }

  /** Grid cells the longest line needs: visible chars + {@link #VAR_CELLS} per number, 1 per input action */
  public static int maxLineCells(final int[] codes) {
    int max = 0;
    int current = 0;
    for(int i = 0; i < codes.length; i++) {
      final int c = codes[i];
      if(c == LINE || c == PAGE || c == END) {
        max = Math.max(max, current);
        current = 0;
      } else if(isVar(c)) {
        current += VAR_CELLS;
      } else if(isAction(c)) {
        current++;
        i += actionPayload(c);
      } else if(visible(c)) {
        current++;
      }
    }
    return Math.max(max, current);
  }

  private static int longestLine(final LodString str) {
    int longest = 0;
    int current = 0;
    boolean firstLine = true;
    for(int i = 0; i < str.length() + 1; i++) {
      final int c = str.charAt(i);
      if(c == END || c == LINE || c == PAGE) {
        // Skip the first line, usually the speaker name
        if(!firstLine) {
          longest = Math.max(longest, current);
        }
        firstLine = false;
        current = 0;
        if(c == END) {
          break;
        }
      } else if(visible(c)) {
        current++;
      }
    }
    return longest > 0 ? longest : Math.max(current, 1);
  }

  /**
   * Widths of the codes of one line (without line/page/end codes): a number {A8xx} counts as 3 digits, or 1 digit next
   * to another number; an input action as {@link #ACTION_DIGITS} digits and its registry id words as 0
   */
  public static int[] widths(final int[] line, final IntUnaryOperator advance) {
    final int[] widths = new int[line.length];
    final int digit = advance.applyAsInt(DIGIT_0);
    for(int i = 0; i < widths.length; i++) {
      final int c = line[i];
      if(isVar(c)) {
        final boolean run = i > 0 && isVar(line[i - 1]) || i + 1 < widths.length && isVar(line[i + 1]);
        widths[i] = run ? digit : 3 * digit;
      } else if(isAction(c)) {
        widths[i] = ACTION_DIGITS * digit;
        i += actionPayload(c); // payload widths stay 0
      } else {
        widths[i] = advance.applyAsInt(c);
      }
    }
    return widths;
  }

  /** Widest line of a code array (terminated by 0xa0ff), measured like {@link #wrap} */
  public static int widestLine(final int[] codes, final IntUnaryOperator advance) {
    final IntList line = new IntArrayList();
    int widest = 0;
    for(final int c : codes) {
      if(c == LINE || c == PAGE || c == END) {
        int width = 0;
        for(final int w : widths(line.toIntArray(), advance)) {
          width += w;
        }
        widest = Math.max(widest, width);
        line.clear();
        if(c == END) {
          break;
        }
      } else {
        line.add(c);
      }
    }
    return widest;
  }

  /**
   * Word-wraps a code array (terminated by 0xa0ff) so no line is wider than {@code maxWidth} (mode C: unchanged)
   *
   * @param advance width of one code (pixels with a font, or 1 per visible char to wrap by count)
   */
  public static int[] wrap(final int[] codes, final char mode, final int maxWidth, final IntUnaryOperator advance) {
    final IntList out = new IntArrayList(codes.length + 16);
    final IntList line = new IntArrayList();
    boolean firstLine = true;

    for(final int c : codes) {
      if(c == LINE || c == PAGE || c == END) {
        if(mode == 'C' || mode == 'N' && firstLine) {
          out.addAll(line); // selection boxes, one-line boxes and the speaker name: never wrapped
        } else {
          wrapLine(line, maxWidth, advance, out);
        }

        firstLine = false;
        line.clear();
        out.add(c);
        if(c == END) {
          break;
        }
      } else {
        line.add(c);
      }
    }

    return out.toIntArray();
  }

  private static void wrapLine(final IntList line, final int maxWidth, final IntUnaryOperator advance, final IntList out) {
    final int[] widths = widths(line.toIntArray(), advance);
    int total = 0;
    for(final int w : widths) {
      total += w;
    }

    // Lines that fit are kept as-is (keeps alignment spaces in tables)
    if(total <= maxWidth) {
      out.addAll(line);
      return;
    }

    // Greedy fill: words are runs without spaces (controls stick to their word); a word wider than the box stays
    // on its own line
    final int spaceWidth = advance.applyAsInt(SPACE);
    int width = 0;
    boolean lineEmpty = true;
    int i = 0;
    while(i < line.size()) {
      while(i < line.size() && line.getInt(i) == SPACE) {
        i++;
      }

      final int start = i;
      int wordWidth = 0;
      while(i < line.size() && line.getInt(i) != SPACE) {
        wordWidth += widths[i];
        i++;
      }

      if(start == i) {
        break;
      }

      if(!lineEmpty && width + spaceWidth + wordWidth > maxWidth) {
        out.add(LINE);
        width = 0;
        lineEmpty = true;
      }

      if(!lineEmpty) {
        out.add(SPACE);
        width += spaceWidth;
      }

      for(int k = start; k < i; k++) {
        out.add(line.getInt(k));
      }

      width += wordWidth;
      lineEmpty = false;
    }
  }

  private static void logMissing(final String key) {
    if(loadedLocale == null || !Boolean.getBoolean("scvi.logMissing") || !missingLogged.add(key)) {
      return;
    }

    try(final Writer writer = Files.newBufferedWriter(Path.of("dialogue_missing." + loadedLocale.getLanguage() + ".txt"), StandardCharsets.UTF_8, StandardOpenOption.CREATE, StandardOpenOption.APPEND)) {
      writer.write(key);
      writer.write('\n');
    } catch(final IOException ignored) {
    }
  }
}
