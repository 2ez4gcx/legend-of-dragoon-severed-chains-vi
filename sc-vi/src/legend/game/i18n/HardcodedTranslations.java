package legend.game.i18n;

import legend.game.SItem;
import legend.game.combat.Monsters;
import legend.game.combat.ui.BattleHud;
import legend.game.modding.coremod.CoreMod;
import legend.game.types.MenuStatus08;
import legend.game.wmap.Place0c;
import legend.game.wmap.WmapStatics;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

import java.lang.reflect.Field;
import java.util.IdentityHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static legend.core.GameEngine.CONFIG;

/**
 * [sc-vi] Translates English strings that are hard-coded in Java (not in .lang files): monster names, submap/world map
 * place names, chapter names, ailment/targeting labels, world map services/regions, menu status labels, and a few UI
 * literals rendered directly (world map prompts, "Load Game", the addition "Hits: ..." line).
 *
 * <p>Lang keys: {@code scvi.<table>.<slug>} where slug = the English text in lower case with every run of characters other
 * than a-z/0-9 replaced by '_' and leading/trailing '_' removed (tools/sc_hardcoded.py computes the same). Missing key =
 * keep English. Tables are rewritten in place (originals kept, so switching back to English restores them).</p>
 *
 * <p>Applied lazily from {@link #onRender} (first text drawn after the language is known/changed), so the classes holding
 * the tables are only initialized once the engine is fully running.</p>
 */
public final class HardcodedTranslations {
  private HardcodedTranslations() { }

  private static final Logger LOGGER = LogManager.getFormatterLogger(HardcodedTranslations.class);

  private static final Set<String> UI_LITERALS = Set.of("Load Game", "Move?", "No", "Yes", "Enter", "Don't enter", "No facilities");
  private static final Pattern HITS = Pattern.compile("Hits: (\\d+), damage: (\\d+), SP: (\\d+)");

  private static final Map<Object, Object> originals = new IdentityHashMap<>();
  private static Locale appliedLocale;
  private static boolean failed;

  private static Object titlePatched;
  private static int[] titleWidths;
  private static boolean titleWidthsRead;

  /**
   * The title menu image (gfx/ui/title_menu.png) is centred with hard-coded English text widths (Ttle.menuTextWidth).
   * When a translated image ships with gfx/ui/title_menu.widths ("w0,w1,w2,w3,w4"), copy those widths into the title
   * screen instance so the translated items stay centred.
   */
  private static void titleMenu() {
    final Object state = legend.game.EngineStates.currentEngineState_8004dd04;
    if(!(state instanceof legend.game.title.Ttle) || state == titlePatched) {
      return;
    }

    titlePatched = state;

    try {
      if(!titleWidthsRead) {
        titleWidthsRead = true;
        final java.nio.file.Path file = java.nio.file.Path.of("gfx", "ui", "title_menu.widths");
        if(java.nio.file.Files.isRegularFile(file)) {
          final String[] parts = java.nio.file.Files.readString(file).trim().split(",");
          titleWidths = new int[parts.length];
          for(int i = 0; i < parts.length; i++) {
            titleWidths[i] = Integer.parseInt(parts[i].trim());
          }
        }
      }

      if(titleWidths != null) {
        final Field field = legend.game.title.Ttle.class.getDeclaredField("menuTextWidth");
        field.setAccessible(true);
        final int[] widths = (int[])field.get(state);
        System.arraycopy(titleWidths, 0, widths, 0, Math.min(widths.length, titleWidths.length));
      }
    } catch(final Throwable t) {
      LOGGER.warn("Failed to apply title menu widths", t);
    }
  }

  /** Called at the start of Text.renderText: applies the tables once per language and translates UI literals */
  public static String onRender(final String text) {
    titleMenu();

    if(!failed) {
      try {
        final Locale locale = CONFIG.getConfig(CoreMod.LANGUAGE_CONFIG.get());
        if(locale != null && !locale.equals(appliedLocale)) {
          appliedLocale = locale;
          apply();
        }
      } catch(final Throwable t) {
        // Config/registries not ready yet: try again on the next call
      }
    }

    if(text == null || text.length() > 64) {
      return text;
    }

    if(UI_LITERALS.contains(text)) {
      return lookup("ui", text);
    }

    if(text.startsWith("Hits: ")) {
      final Matcher m = HITS.matcher(text);
      if(m.matches()) {
        final String format = lookup("ui", "Hits: %s, damage: %s, SP: %s");
        if(!format.startsWith("Hits: ")) {
          return format.replace("{0}", m.group(1)).replace("{1}", m.group(2)).replace("{2}", m.group(3));
        }
      }
    }

    return text;
  }

  public static synchronized void apply() {
    try {
      strings(Monsters.monsterNames_80112068, "monster");
      strings(SItem.chapterNames_80114248, "chapter");
      strings(SItem.submapNames_8011c108, "submap");
      strings(SItem.worldMapNames_8011c1ec, "worldmap");
      strings(BattleHud.ailments_800fb3a0, "ailment");
      strings(privateStrings(BattleHud.class, "targeting_800fb36c"), "target");
      strings(WmapStatics.services_800f01cc, "service");
      strings(WmapStatics.regions_800f01ec, "region");
      places(WmapStatics.places_800f0234);
      menuStatus(SItem.menuStatus_800fba7c);
      LOGGER.info("Applied hard-coded string translations for %s", appliedLocale);
    } catch(final Throwable t) {
      failed = true;
      LOGGER.warn("Failed to apply hard-coded string translations", t);
    }
  }

  private static String[] privateStrings(final Class<?> cls, final String name) throws ReflectiveOperationException {
    final Field field = cls.getDeclaredField(name);
    field.setAccessible(true);
    return (String[])field.get(null);
  }

  private static void strings(final String[] array, final String table) {
    final String[] original = (String[])originals.computeIfAbsent(array, a -> array.clone());
    for(int i = 0; i < array.length; i++) {
      array[i] = lookup(table, original[i]);
    }
  }

  private static void places(final Place0c[] places) {
    final String[] original = (String[])originals.computeIfAbsent(places, a -> {
      final String[] names = new String[places.length];
      for(int i = 0; i < places.length; i++) {
        names[i] = places[i].name_00;
      }
      return names;
    });

    for(int i = 0; i < places.length; i++) {
      places[i].name_00 = lookup("place", original[i]);
    }
  }

  private static void menuStatus(final MenuStatus08[] statuses) {
    final MenuStatus08[] original = (MenuStatus08[])originals.computeIfAbsent(statuses, a -> statuses.clone());
    for(int i = 0; i < statuses.length; i++) {
      final String text = lookup("menustatus", original[i].text_00);
      statuses[i] = text.equals(original[i].text_00) ? original[i] : new MenuStatus08(text, original[i].colour_04);
    }
  }

  /** Translation of {@code english} from key scvi.&lt;table&gt;.&lt;slug&gt;, or {@code english} itself (null/empty kept) */
  public static String lookup(final String table, final String english) {
    if(english == null || english.isEmpty()) {
      return english;
    }

    final String key = "scvi." + table + '.' + slug(english);
    final String value = I18n.translate(key);
    return value.equals(key) ? english : value;
  }

  public static String slug(final String english) {
    return english.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]+", "_").replaceAll("^_|_$", "");
  }
}
