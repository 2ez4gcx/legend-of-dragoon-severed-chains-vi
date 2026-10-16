package legend.game.i18n;

import it.unimi.dsi.fastutil.ints.IntArrayList;
import it.unimi.dsi.fastutil.ints.IntList;
import legend.core.GameEngine;
import legend.core.font.Font;
import legend.game.modding.coremod.CoreMod;
import legend.game.types.LodString;
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
 * (variable) width. Translations are word-wrapped to the PIXEL width of the original box (N x 9 px, N = textbox width read
 * from the script) using the selected font, so the box keeps its retail size; {@link #applyGrid} then widens the textbox's
 * character grid so the engine does not break those lines again. Modes: {@code N} first line is the speaker name (kept),
 * the rest of each page is wrapped; {@code J} each page is wrapped; {@code L} explicit lines are kept and only lines wider
 * than the box are broken at spaces (selection boxes, tables).</p>
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

  private static final int SPACE = 0x00;
  private static final int LINE = 0xa1ff;
  private static final int PAGE = 0xa3ff;
  private static final int END = 0xa0ff;

  private record Entry(String text, char mode) { }

  private static Locale loadedLocale;
  private static Map<String, Entry> table = Map.of();
  private static final Map<String, int[]> encoded = new HashMap<>();
  private static final Set<String> missingLogged = new HashSet<>();

  public static LodString translate(final LodString original) {
    return translate(original, -1);
  }

  /**
   * @param boxChars textbox width in characters from the script (the 2 words after the string), or -1 if unknown
   */
  public static LodString translate(final LodString original, final int boxChars) {
    try {
      ensureLoaded();

      if(table.isEmpty()) {
        return original;
      }

      final String key = toTags(original);
      final Entry entry = table.get(key);

      if(entry == null) {
        logMissing(key);
        return original;
      }

      final int width = boxChars > 0 ? boxChars : longestLine(original);
      final Font font = GameEngine.DEFAULT_FONT;
      final int[] codes = encoded.computeIfAbsent(key + '\u0000' + width + '\u0000' + System.identityHashCode(font), k -> wrap(fromTags(entry.text), entry.mode, width * CELL, c -> advance(font, c)));
      final LodString out = new LodString(codes);
      out.gridChars = maxLineChars(codes);
      return out;
    } catch(final Throwable t) {
      LOGGER.warn("Failed to translate textbox string", t);
      return original;
    }
  }

  /** Widens the textbox character grid when a translated line has more characters than the retail box (call before allocating chars_58) */
  public static void applyGrid(final TextboxText84 textboxText) {
    if(textboxText.str_24 != null && textboxText.str_24.gridChars > textboxText.chars_1c) {
      textboxText.chars_1c = Math.min(textboxText.str_24.gridChars, MAX_GRID);
    }
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
    encoded.clear();
    missingLogged.clear();

    final Path file = Path.of("lang", "dialogue." + locale.getLanguage() + ".tsv");
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
        map.put(cols[0], new Entry(Normalizer.normalize(cols[1], Normalizer.Form.NFC), mode));
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

  private static int maxLineChars(final int[] codes) {
    int max = 0;
    int current = 0;
    for(final int c : codes) {
      if(c == LINE || c == PAGE || c == END) {
        max = Math.max(max, current);
        current = 0;
      } else if(visible(c)) {
        current++;
      }
    }
    return max;
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
   * Word-wraps a code array (terminated by 0xa0ff) so no line is wider than {@code maxWidth}
   *
   * @param advance width of one code (pixels with a font, or 1 per visible char to wrap by count)
   */
  public static int[] wrap(final int[] codes, final char mode, final int maxWidth, final IntUnaryOperator advance) {
    final IntList out = new IntArrayList(codes.length + 16);
    final IntList line = new IntArrayList();
    boolean firstLine = true;

    for(final int c : codes) {
      if(c == LINE || c == PAGE || c == END) {
        if(mode == 'N' && firstLine) {
          out.addAll(line); // speaker name: never wrapped
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
    int total = 0;
    for(int i = 0; i < line.size(); i++) {
      total += advance.applyAsInt(line.getInt(i));
    }

    // Lines that fit are kept as-is (keeps alignment spaces in selection boxes and tables)
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
        wordWidth += advance.applyAsInt(line.getInt(i));
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
    if(!Boolean.getBoolean("scvi.logMissing") || !missingLogged.add(key)) {
      return;
    }

    try(final Writer writer = Files.newBufferedWriter(Path.of("dialogue_missing." + loadedLocale.getLanguage() + ".txt"), StandardCharsets.UTF_8, StandardOpenOption.CREATE, StandardOpenOption.APPEND)) {
      writer.write(key);
      writer.write('\n');
    } catch(final IOException ignored) {
    }
  }
}
