package legend.scvi.remaster;

import legend.game.EngineStates;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.lang.ref.WeakReference;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Locale;
import java.util.Properties;

/**
 * [sc-vi] Công tắc mô hình HD (LRM spec 1 §3.7).
 *
 * Thứ tự ưu tiên: thuộc tính -Dscvi.remaster=off|geometry|full, rồi &lt;game&gt;/remaster.properties
 * (java.util.Properties: enabled=true|false (thiếu = false), textures=hd|retail (thiếu = hd), log=true|false (thiếu = false);
 * BOM UTF-8 ở đầu file được bỏ qua), rồi tắt. geometry = enabled + textures=retail (chỉ bộ VRAM); full = enabled + textures=hd.
 * Nhật ký chi tiết: -Dscvi.remasterLog=true|false, nếu không có thì log= trong remaster.properties.
 * Thư mục game = thư mục làm việc của tiến trình (như vi/files, lang/ của sc-vi). Thiếu remaster/index.tsv hoặc chỉ mục sai
 * định dạng => tắt.
 *
 * Cấu hình và chỉ mục được đọc lại (kèm xoá cache LRM, quét AtlasCache, đặt lại nhật ký) khi đối tượng
 * EngineStates.currentEngineState_8004dd04 đổi (so theo danh tính) — tức là mỗi lần chuyển cảnh lớn (trường / trận / bản đồ).
 * Chế độ off không đọc chỉ mục và không ghi log.
 */
public final class RemasterConfig {
  public enum Mode { OFF, GEOMETRY, FULL }

  static final Path PROPERTIES = Path.of("remaster.properties");
  /** Cỡ tối đa của remaster.properties (vài dòng là đủ). */
  private static final long MAX_PROPERTIES = 1L << 20;

  final Mode mode;
  final boolean log;
  /** null = không có chỉ mục dùng được (tính năng tắt). */
  final RemasterIndex index;

  private RemasterConfig(final Mode mode, final boolean log, final RemasterIndex index) {
    this.mode = mode;
    this.log = log;
    this.index = index;
  }

  /** Bật (geometry/full) và có chỉ mục. */
  boolean active() {
    return this.mode != Mode.OFF && this.index != null;
  }

  private static boolean loaded;
  private static WeakReference<Object> lastState;
  private static RemasterConfig current;

  /** Cấu hình hiện tại; đọc lại khi engine state đổi. Không bao giờ ném. */
  static synchronized RemasterConfig current() {
    final Object state = EngineStates.currentEngineState_8004dd04;
    final Object last = lastState != null ? lastState.get() : null;

    if(!loaded || last != state) {
      loaded = true;
      lastState = state != null ? new WeakReference<>(state) : null;
      current = load();

      try {
        RemasterModels.onConfigReload(current);
      } catch(final Throwable t) {
        RemasterLog.warn("reload hook failed: %s", RemasterLog.reason(t));
      }
    }

    return current;
  }

  private static RemasterConfig load() {
    try {
      return load0();
    } catch(final Throwable t) {
      return new RemasterConfig(Mode.OFF, false, null);
    }
  }

  private static RemasterConfig load0() {
    Properties props = null;
    String propsError = null;

    try {
      if(Files.isRegularFile(PROPERTIES)) {
        if(Files.size(PROPERTIES) > MAX_PROPERTIES) {
          throw new java.io.IOException("file too large");
        }

        // bỏ BOM UTF-8 ở đầu (Notepad cũ / PowerShell 5.1 "-Encoding utf8" ghi BOM): nếu không, khoá đầu tiên thành
        // "<3 byte BOM>enabled" và tính năng tắt mà không có dòng log nào
        final byte[] bytes = Files.readAllBytes(PROPERTIES);
        final int skip = bytes.length >= 3 && (bytes[0] & 0xff) == 0xef && (bytes[1] & 0xff) == 0xbb && (bytes[2] & 0xff) == 0xbf ? 3 : 0;
        final Properties p = new Properties();
        try(final InputStream in = new ByteArrayInputStream(bytes, skip, bytes.length - skip)) {
          p.load(in);
        }
        props = p;
      }
    } catch(final Throwable t) {
      propsError = RemasterLog.reason(t);
    }

    Mode mode = Mode.OFF;
    String warning = null;
    final String sysMode = System.getProperty("scvi.remaster");

    if(sysMode != null) {
      switch(sysMode.trim().toLowerCase(Locale.ROOT)) {
        case "off" -> mode = Mode.OFF;
        case "geometry" -> mode = Mode.GEOMETRY;
        case "full" -> mode = Mode.FULL;
        default -> warning = "unknown -Dscvi.remaster=" + sysMode + " (expected off|geometry|full), feature off";
      }
    } else if(props != null) {
      if(bool(props.getProperty("enabled"), false)) {
        final String textures = props.getProperty("textures");
        if(textures == null || "hd".equalsIgnoreCase(textures.trim())) {
          mode = Mode.FULL;
        } else if("retail".equalsIgnoreCase(textures.trim())) {
          mode = Mode.GEOMETRY;
        } else {
          mode = Mode.GEOMETRY;
          warning = "unknown textures=" + textures + " in remaster.properties (expected hd|retail), using retail";
        }
      }
    } else if(propsError != null) {
      warning = "cannot read remaster.properties: " + propsError + ", feature off";
    }

    final String sysLog = System.getProperty("scvi.remasterLog");
    final boolean log = sysLog != null ? bool(sysLog, false) : props != null && bool(props.getProperty("log"), false);

    if(warning != null) {
      RemasterLog.warn("%s", warning);
    }

    if(mode == Mode.OFF) {
      return new RemasterConfig(Mode.OFF, log, null);
    }

    RemasterIndex index = null;
    try {
      index = RemasterIndex.load();
      if(index == null) {
        RemasterLog.warn("mode=%s but %s is missing, feature off", mode.name().toLowerCase(Locale.ROOT), RemasterIndex.FILE);
      }
    } catch(final Throwable t) {
      RemasterLog.warn("mode=%s but %s is invalid (%s), feature off", mode.name().toLowerCase(Locale.ROOT), RemasterIndex.FILE, RemasterLog.reason(t));
    }

    if(index != null) {
      RemasterLog.info("config mode=%s log=%s index=%d model(s)", mode.name().toLowerCase(Locale.ROOT), log, index.size());
    }

    return new RemasterConfig(mode, log, index);
  }

  private static boolean bool(final String value, final boolean fallback) {
    if(value == null) {
      return fallback;
    }

    final String v = value.trim();
    if("true".equalsIgnoreCase(v)) {
      return true;
    }

    if("false".equalsIgnoreCase(v)) {
      return false;
    }

    return fallback;
  }
}
