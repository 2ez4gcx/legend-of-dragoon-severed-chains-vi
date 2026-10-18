package legend.scvi.remaster;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

import java.util.HashSet;
import java.util.Set;

/**
 * [sc-vi] Nhật ký mô hình HD (LRM spec 1 §4.4). Mọi dòng bắt đầu bằng "scvi-remaster: " và đi qua log4j (INFO/WARN), nên
 * trong game nằm ở debug.log và stdout.txt; khi chạy không cửa sổ (bộ thử) thêm -Dlog4j2.level=INFO để thấy trên console.
 *
 * Dòng chuẩn (mỗi khoá):  scvi-remaster: &lt;name&gt; key=&lt;k&gt; hit|miss|fallback(&lt;lý do&gt;) variant=&lt;v&gt;|vram [(ghi chú)]
 *   - miss / fallback: một dòng mỗi khoá mỗi "thế hệ" cấu hình (đọc lại khi engine state đổi), cả ở chế độ chi tiết
 *     (§3.5.4 "log một lần mỗi khoá").
 *   - hit: khi trạng thái texture của lần nạp đó ngã ngũ — "variant=v" lúc xác minh đạt, "variant=vram (...)" khi không
 *     có bộ ATLAS hoặc hết cửa sổ xác minh nhanh (2 s) mà chưa đạt.
 * Chế độ chi tiết (-Dscvi.remasterLog=true hoặc log=true trong remaster.properties) thêm:
 *   - "hit variant=pending" ngay lúc nạp (để mọi mô hình đều có khoá trong log),
 *   - "mismatch variant=v face=g runtime=xxxxxxxx expected=xxxxxxxx" (mặt sai đầu tiên của từng biến thể),
 *   - "facehash n=N sha1=..." = SHA-1 véc-tơ FaceHash runtime (§3.3.6: FaceHash thô mọi mặt có texture, mặt bpp 3 ghi 0)
 *     để so với ref_spec.py / vectors.json.
 * Chế độ off: không ghi gì.
 */
final class RemasterLog {
  private RemasterLog() { }

  private static final Logger LOGGER = LogManager.getFormatterLogger(RemasterLog.class);
  private static final String PREFIX = "scvi-remaster: ";

  private static boolean verbose;
  private static final Set<String> missLogged = new HashSet<>();
  private static final Set<String> fallbackLogged = new HashSet<>();

  /** Gọi khi đọc lại cấu hình (engine state đổi): xoá bộ nhớ "đã ghi" của miss/fallback. */
  static synchronized void reset(final boolean verboseLog) {
    verbose = verboseLog;
    missLogged.clear();
    fallbackLogged.clear();
  }

  static synchronized boolean verbose() {
    return verbose;
  }

  /** Một dòng mỗi khoá (§3.5.4, §4.1, §4.4) kể cả ở chế độ chi tiết; đặt lại khi đọc lại cấu hình. */
  static synchronized void miss(final String name, final String key) {
    if(missLogged.add(key)) {
      info("%s key=%s miss variant=vram", name, key);
    }
  }

  /** Một dòng mỗi khoá (§3.5.4 "log một lần mỗi khoá") kể cả ở chế độ chi tiết; đặt lại khi đọc lại cấu hình. */
  static synchronized void fallback(final String name, final String key, final String reason) {
    if(fallbackLogged.add(key)) {
      warn("%s key=%s fallback(%s) variant=vram", name, key, reason);
    }
  }

  /** variant &lt; 0 = vram. note có thể null. */
  static void hit(final String name, final String key, final int variant, final String note) {
    final String v = variant >= 0 ? Integer.toString(variant) : "vram";
    if(note == null) {
      info("%s key=%s hit variant=%s", name, key, v);
    } else {
      info("%s key=%s hit variant=%s (%s)", name, key, v, note);
    }
  }

  static void info(final String format, final Object... args) {
    try {
      LOGGER.info(PREFIX + format, args);
    } catch(final Throwable ignored) {
      // nhật ký không bao giờ được làm hỏng đường nạp mô hình
    }
  }

  static void warn(final String format, final Object... args) {
    try {
      LOGGER.warn(PREFIX + format, args);
    } catch(final Throwable ignored) {
      // như trên
    }
  }

  static String hex(final byte[] bytes) {
    final char[] out = new char[bytes.length * 2];
    final char[] digits = "0123456789abcdef".toCharArray();
    for(int i = 0; i < bytes.length; i++) {
      out[i * 2] = digits[bytes[i] >>> 4 & 0xf];
      out[i * 2 + 1] = digits[bytes[i] & 0xf];
    }
    return new String(out);
  }

  static String hex8(final int value) {
    return String.format("%08x", value);
  }

  /** Lý do ngắn gọn của một Throwable (không có dấu ngoặc đóng để không vỡ "fallback(...)"). */
  static String reason(final Throwable t) {
    String msg = t.getMessage();
    if(msg == null || msg.isEmpty()) {
      msg = t.getClass().getSimpleName();
    } else if(!(t instanceof LrmFile.Invalid)) {
      msg = t.getClass().getSimpleName() + ": " + msg;
    }
    return msg.replace('(', '[').replace(')', ']').replace('\n', ' ').replace('\r', ' ');
  }
}
