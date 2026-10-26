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

  private static final Set<String> UI_LITERALS = Set.of("Load Game", "Move?", "No", "Yes", "Enter", "Don't enter", "No facilities", "Unknown location");
  private static final Pattern HITS = Pattern.compile("Hits: (\\d+), damage: (\\d+), SP: (\\d+)");

  private static final Map<Object, Object> originals = new IdentityHashMap<>();
  private static final Map<String, String> PLACE_NAMES = new java.util.HashMap<>();
  private static Locale appliedLocale;
  private static boolean failed;
  private static Locale renderLocale;
  private static long renderLocaleTime;

  private static Object titleState;
  private static Object titleTex;
  private static boolean titleTexTranslated;
  private static String titleTag;
  private static int[] titleOriginalWidths;
  private static Field titleTexField;
  private static Field titleWidthField;
  private static Field textureDeletedField;
  private static boolean titleFailed;

  /**
   * The title menu items are drawn from an image (gfx/ui/title_menu.png, Ttle.menuTextTex) centred with hard-coded English
   * text widths (Ttle.menuTextWidth). When the current language ships gfx/ui/title_menu.&lt;language tag&gt;.png plus
   * gfx/ui/title_menu.&lt;language tag&gt;.widths ("w0,w1,w2,w3,w4"), swap that image into the title screen and copy the
   * widths so the translated items stay centred; any other language gets the original image and widths back.
   *
   * <p>Ttle.loadTextures loads gfx/ui/title_menu.png again every time the main menu comes back (after Options, About...),
   * and Ttle.deallocate deletes it while those screens are open: a texture object not seen before is therefore the
   * original image, and a deleted one is left alone (the next loadTextures replaces it). Swapping mid-frame is safe:
   * Texture.delete() only marks the old texture, it is freed after the frame is drawn.</p>
   */
  private static void titleMenu(final Locale locale) {
    final Object state = legend.game.EngineStates.currentEngineState_8004dd04;
    if(titleFailed || !(state instanceof legend.game.title.Ttle)) {
      return;
    }

    try {
      if(titleTexField == null) {
        titleTexField = legend.game.title.Ttle.class.getDeclaredField("menuTextTex");
        titleTexField.setAccessible(true);
        titleWidthField = legend.game.title.Ttle.class.getDeclaredField("menuTextWidth");
        titleWidthField.setAccessible(true);
        textureDeletedField = legend.core.renderer.Texture.class.getDeclaredField("deleted");
        textureDeletedField.setAccessible(true);
      }

      final legend.core.renderer.Texture current = (legend.core.renderer.Texture)titleTexField.get(state);
      if(current == null || textureDeletedField.getBoolean(current)) {
        return; // textures not loaded yet, or deallocated while another screen is open
      }

      final String tag = locale == null ? "" : locale.toLanguageTag();
      if(state == titleState && current == titleTex && tag.equals(titleTag)) {
        return;
      }

      final int[] widths = (int[])titleWidthField.get(state);
      if(state != titleState) {
        titleState = state;
        titleOriginalWidths = widths.clone();
      }

      final boolean original = current != titleTex || !titleTexTranslated;
      titleTag = tag;

      final java.nio.file.Path png = java.nio.file.Path.of("gfx", "ui", "title_menu." + tag + ".png");
      final java.nio.file.Path widthFile = java.nio.file.Path.of("gfx", "ui", "title_menu." + tag + ".widths");
      System.arraycopy(titleOriginalWidths, 0, widths, 0, widths.length);

      if(!tag.isEmpty() && java.nio.file.Files.isRegularFile(png) && java.nio.file.Files.isRegularFile(widthFile)) {
        final String[] parts = java.nio.file.Files.readString(widthFile).trim().split(",");
        for(int i = 0; i < Math.min(widths.length, parts.length); i++) {
          widths[i] = Integer.parseInt(parts[i].trim());
        }
        current.delete();
        titleTex = legend.core.renderer.Texture.filteredPng("Menu", png);
        titleTexTranslated = true;
        titleTexField.set(state, titleTex);
        LOGGER.info("Title menu: %s", png);
      } else if(!original) {
        current.delete();
        titleTex = legend.core.renderer.Texture.filteredPng("Menu", java.nio.file.Path.of("gfx", "ui", "title_menu.png"));
        titleTexTranslated = false;
        titleTexField.set(state, titleTex);
        LOGGER.info("Title menu: original image");
      } else {
        titleTex = current;
        titleTexTranslated = false;
      }
    } catch(final Throwable t) {
      titleFailed = true;
      LOGGER.warn("Failed to swap the title menu image", t);
    }
  }

  /** Called at the start of Text.renderText: applies the tables once per language and translates UI literals */
  public static String onRender(final String text) {
    // This runs for every text drawn (dozens a frame). A saved language is a map lookup; without one the config works out its
    // default by walking the lang directory, so that is done at most twice a second.
    Locale locale = renderLocale;
    try {
      if(CONFIG.hasConfig(CoreMod.LANGUAGE_CONFIG.get())) {
        locale = CONFIG.getConfig(CoreMod.LANGUAGE_CONFIG.get());
      } else {
        final long now = System.nanoTime();
        if(locale == null || now - renderLocaleTime >= 500_000_000L) {
          locale = CONFIG.getConfig(CoreMod.LANGUAGE_CONFIG.get());
          renderLocale = locale;
          renderLocaleTime = now;
        }
      }
    } catch(final Throwable t) {
      // Config/registries not ready yet: try again on the next call
    }

    titleMenu(locale);

    if(!failed && locale != null && !locale.equals(appliedLocale)) {
      appliedLocale = locale;
      apply();
    }

    if(text == null || text.length() > 64) {
      return text;
    }

    if(UI_LITERALS.contains(text)) {
      return lookup("ui", text);
    }

    // Saves store the location name as text when written: saves made (or converted from memory cards) in English
    // still show e.g. "Ch.4 Moon & Fate" on the save card -> translate known place/chapter names when drawn
    final String place = PLACE_NAMES.get(text);
    if(place != null) {
      return place;
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
      PLACE_NAMES.clear();
      strings(Monsters.monsterNames_80112068, "monster");
      strings(SItem.chapterNames_80114248, "chapter");
      strings(SItem.submapNames_8011c108, "submap");
      strings(SItem.worldMapNames_8011c1ec, "worldmap");
      placeNames(SItem.chapterNames_80114248);
      placeNames(SItem.submapNames_8011c108);
      placeNames(SItem.worldMapNames_8011c1ec);
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

  /** English name -> translated name for every entry of an already translated location table (only entries that differ) */
  private static void placeNames(final String[] array) {
    final String[] original = (String[])originals.get(array);
    for(int i = 0; i < array.length; i++) {
      if(original[i] != null && !original[i].isEmpty() && !original[i].equals(array[i])) {
        PLACE_NAMES.putIfAbsent(original[i], array[i]);
      }
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
