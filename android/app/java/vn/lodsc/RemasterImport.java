package vn.lodsc;

import android.content.ContentResolver;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.os.StatFs;
import android.provider.OpenableColumns;
import android.util.Log;

import org.json.JSONObject;
import org.json.JSONTokener;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayInputStream;
import java.io.EOFException;
import java.io.File;
import java.io.FileOutputStream;
import java.io.FilterInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Properties;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipException;
import java.util.zip.ZipInputStream;

/**
 * Nhập gói "Mô hình HD" cho Android và bật/tắt tính năng (LRM spec 1, tools/sc_remaster/SPEC.md §3.5–§3.7).
 *
 * <p>Gói .zip do công cụ "Tạo mô hình HD" trên máy tính xuất (bộ "mobile": L1 + atlas 2x), sinh từ đĩa của chính người
 * chơi — APK không bao giờ chứa dữ liệu này. Người chơi chọn tệp bằng trình chọn tệp Android (SAF, chỉ đọc một lần).
 *
 * <p>Quy trình {@link #importZip}:
 * <ol>
 *   <li>Kiểm bộ nhớ trống (StatFs): cần cỡ zip × 1,1 + 200 MB (không biết cỡ zip: kiểm dần khi giải nén).</li>
 *   <li>Giải nén luồng vào {@code game/remaster.import/}. Chỉ nhận đúng các mục {@code remaster/index.tsv},
 *       {@code remaster/manifest.json}, {@code remaster/models/<40 hex>.lrm}, {@code remaster/textures/<40 hex>.png}
 *       (+ ba mục thư mục tương ứng, + {@code DOC_TRUOC.txt} ở gốc zip: ghi chú "chỉ dùng cá nhân" của công cụ PC, bỏ qua,
 *       không giải nén). Mục khác, đường dẫn tuyệt đối / có {@code ..} / {@code \} / {@code :}, mục trùng tên → huỷ.
 *       Chặn đường dẫn bằng đường dẫn chuẩn hoá như Payload.java. Giới hạn: 64 MB mỗi mục (index.tsv, manifest.json:
 *       4 MB vì được đọc hết vào bộ nhớ), 1 GB tổng, 4096 mục. Tên mục không phải UTF-8 / zip hỏng / cụt → huỷ. Đọc hết
 *       tới cuối tệp: bản ghi kết thúc (EOCD) phải ở đúng cuối và mục lục phải đếm đúng số mục đã đọc, nếu không (zip cắt
 *       đúng ranh giới giữa hai mục, thiếu mục lục, đọc lệch) → huỷ ({@link #checkEnd}).</li>
 *   <li>Kiểm: {@code index.tsv} đúng §3.7 (dòng 1 {@code LRMINDEX<TAB>1}, UTF-8 không BOM, LF, mỗi dòng
 *       {@code <khoá><TAB>models/<khoá>.lrm<TAB><nhãn>}, khoá không trùng); mọi .lrm được chỉ mục có trong gói;
 *       mọi .lrm có magic {@code LRM1}, version 1 và modelKey trong header = tên tệp; mọi PNG có SHA-1 = tên tệp, chữ ký
 *       PNG, IHDR cỡ luỹ thừa 2 trong 1..2048; manifest.json (nếu có) là đối tượng JSON, {@code format} (nếu có) = 1.</li>
 *   <li>Đổi chỗ nguyên tử: {@code remaster → remaster.old}, {@code remaster.import/remaster → remaster}, xoá
 *       {@code remaster.old}. Lỗi ở bất kỳ bước nào trước đó: xoá {@code remaster.import}, {@code remaster/} giữ nguyên.
 *       {@link #recover} (gọi lúc mở app) dọn bản nhập dở và khôi phục {@code remaster.old} nếu app bị tắt giữa hai lần
 *       đổi tên.</li>
 *   <li>Bật tính năng ({@code remaster.properties}: {@code enabled=true}, giữ {@code textures}, {@code log}).</li>
 * </ol>
 *
 * <p>Vị trí: {@code filesDir/game/remaster/} và {@code filesDir/game/remaster.properties} — ngoài {@code Payload.PROGRAM}
 * nên còn nguyên khi cập nhật APK (android/make_apk.py kiểm điều này lúc dựng).
 *
 * <p>Log (tag {@value #TAG}): {@code import ...}, mục bị từ chối, và (SetupActivity) dòng kết quả
 * {@code result ok models=N} / {@code result fail code=<loại>/<lý do>} — android/test/remaster_import.ps1 đọc dòng này.
 */
final class RemasterImport {
  private RemasterImport() { }

  static final String TAG = "LodscHd";

  static final long ENTRY_CAP = 64L << 20;
  static final long TOTAL_CAP = 1L << 30;
  static final long SPACE_MARGIN = 200L << 20;
  /** index.tsv và manifest.json được đọc hết vào bộ nhớ: giới hạn chặt hơn (116 mô hình v1: index ≈ 10 KB, manifest ≈ 100 KB) */
  static final long INDEX_CAP = 4L << 20;
  static final long NOTE_CAP = 1L << 20;
  static final int MAX_ENTRIES = 4096;

  private static final String INDEX = "remaster/index.tsv";
  private static final String MANIFEST = "remaster/manifest.json";
  private static final String NOTE = "DOC_TRUOC.txt";
  private static final Pattern DATA = Pattern.compile(
    "remaster/(index\\.tsv|manifest\\.json|models/[0-9a-f]{40}\\.lrm|textures/[0-9a-f]{40}\\.png)");
  private static final Set<String> DIRS = new HashSet<>(Arrays.asList("remaster/", "remaster/models/", "remaster/textures/"));
  private static final Pattern KEY = Pattern.compile("[0-9a-f]{40}");
  private static final byte[] PNG_SIG = {(byte)0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'};
  private static final int HEAD = 64;

  /** đang nhập (luồng nền): SetupActivity khoá nút nhập / Bật-Tắt / tự vào game, kể cả ở Activity tạo lại giữa chừng */
  private static volatile boolean running;

  static boolean running() {
    return running;
  }

  /** Giới hạn khi nhập; bản debuggable cho phép android/test/remaster_import.ps1 đổi (thử giới hạn tổng, thiếu chỗ) */
  static final class Limits {
    long entryCap = ENTRY_CAP;
    long totalCap = TOTAL_CAP;
    /** byte cộng thêm vào lượng bộ nhớ trống cần có (chỉ để thử thông báo thiếu chỗ) */
    long reserve;
  }

  /** Lỗi nhập: thông điệp tiếng Việt cho người chơi; {@link #code} = "loại/lý do" cho log và thử nghiệm */
  static final class Failure extends Exception {
    private static final long serialVersionUID = 1L;
    final String code;

    Failure(final String code, final String message) {
      super(message);
      this.code = code;
    }
  }

  static File dataDir(final Context c) {
    return new File(Payload.gameDir(c), "remaster");
  }

  private static File stagingDir(final Context c) {
    return new File(Payload.gameDir(c), "remaster.import");
  }

  private static File oldDir(final Context c) {
    return new File(Payload.gameDir(c), "remaster.old");
  }

  static File propsFile(final Context c) {
    return new File(Payload.gameDir(c), "remaster.properties");
  }

  /** Đã có bộ mô hình HD (chỉ mục là điểm commit của bộ sinh, §3.7) */
  static boolean hasData(final Context c) {
    return new File(dataDir(c), "index.tsv").isFile();
  }

  // ---------------------------------------------------------------- công tắc (remaster.properties, §3.7)

  /** Đọc như runtime (sc-vi RemasterConfig): java.util.Properties, bỏ BOM UTF-8 ở đầu tệp nếu có */
  private static Properties loadProps(final Context c) {
    final Properties p = new Properties();
    final File f = propsFile(c);
    if(f.isFile()) {
      try {
        final byte[] b = Files.readAllBytes(f.toPath());
        final int skip = b.length >= 3 && (b[0] & 0xff) == 0xef && (b[1] & 0xff) == 0xbb && (b[2] & 0xff) == 0xbf ? 3 : 0;
        p.load(new ByteArrayInputStream(b, skip, b.length - skip));
      } catch(final IOException | IllegalArgumentException e) {
        Log.w(TAG, "doc remaster.properties loi: " + e);
      }
    }
    return p;
  }

  /** enabled thiếu → false (§3.7) */
  static boolean isEnabled(final Context c) {
    return "true".equalsIgnoreCase(loadProps(c).getProperty("enabled", "false").trim());
  }

  /**
   * Ghi {@code enabled=<on>}, giữ {@code textures} và {@code log} theo đúng nghĩa runtime đang hiểu (sc-vi RemasterConfig):
   * textures thiếu / "hd" (không phân biệt hoa thường) → hd, giá trị khác ("retail", lạ) → retail; log "true" (không phân
   * biệt hoa thường) → true, còn lại → false. Ghi tạm rồi đổi tên.
   */
  static synchronized void setEnabled(final Context c, final boolean on) throws IOException {
    final Properties p = loadProps(c);
    final String tex = p.getProperty("textures");
    final String textures = tex == null || "hd".equalsIgnoreCase(tex.trim()) ? "hd" : "retail";
    final String log = "true".equalsIgnoreCase(p.getProperty("log", "false").trim()) ? "true" : "false";
    final String text = "enabled=" + on + "\ntextures=" + textures + "\nlog=" + log + "\n";
    final File f = propsFile(c);
    mkdirs(f.getParentFile());
    final File tmp = new File(f.getPath() + ".tmp");
    try(OutputStream os = new FileOutputStream(tmp)) {
      os.write(text.getBytes(StandardCharsets.US_ASCII));
      os.flush();
    }
    Files.move(tmp.toPath(), f.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
    Log.i(TAG, "remaster.properties enabled=" + on);
  }

  // ---------------------------------------------------------------- dọn dẹp lúc mở app

  /** Xoá bản nhập dở (remaster.import); nếu app bị tắt giữa hai lần đổi tên thì khôi phục remaster.old → remaster */
  static synchronized void recover(final Context c) {
    final File cur = dataDir(c);
    final File old = oldDir(c);
    try {
      deleteTree(stagingDir(c));
      if(old.exists()) {
        if(!cur.exists()) {
          Files.move(old.toPath(), cur.toPath(), StandardCopyOption.ATOMIC_MOVE);
          Log.w(TAG, "khoi phuc remaster.old -> remaster");
        } else {
          deleteTree(old);
        }
      }
    } catch(final IOException | RuntimeException e) {
      Log.w(TAG, "recover: " + e);
    }
  }

  // ---------------------------------------------------------------- nhập

  /** @return số mô hình trong index.tsv mới */
  static synchronized int importZip(final Context c, final Uri uri, final Limits lim, final Payload.Progress progress) throws Failure {
    final File game = Payload.gameDir(c);
    final File staging = stagingDir(c);
    Log.i(TAG, "import " + uri);
    boolean done = false;
    running = true;
    try {
      recover(c);
      mkdirs(game);
      final long size = zipSize(c, uri);
      final long avail = new StatFs(game.getPath()).getAvailableBytes();
      final long need = (size >= 0 ? size + size / 10 : 0) + SPACE_MARGIN + lim.reserve;
      if(avail < need) {
        throw noSpace(c, need, avail);
      }
      deleteTree(staging);
      mkdirs(staging);
      final Map<String, File> files = extract(c, uri, staging, size, avail, lim, progress);
      final int models = validate(c, files);
      swap(c, staging);
      try {
        setEnabled(c, true);
      } catch(final IOException e) {
        Log.w(TAG, "khong ghi duoc remaster.properties sau khi nhap", e);   // dữ liệu đã thay; nút Bật/Tắt cho thấy trạng thái thật
      }
      Log.i(TAG, "import xong: " + models + " mo hinh, " + files.size() + " tep");
      done = true;
      return models;
    } catch(final Failure f) {
      Log.w(TAG, "import that bai " + f.code);
      throw f;
    } catch(final IOException | RuntimeException e) {
      Log.w(TAG, "import loi", e);
      throw new Failure("io", c.getString(R.string.hd_failed, String.valueOf(e)));
    } finally {
      try {
        if(!done) {
          // cả khi gặp Error (OutOfMemoryError, StackOverflowError…): xoá bản nhập dở ngay, và nếu đổi chỗ hỏng giữa chừng
          // (remaster đã thành remaster.old nhưng chưa trả lại được) thì khôi phục ngay, không đợi lần mở app sau
          recover(c);
        }
      } finally {
        running = false;
      }
    }
  }

  private static long zipSize(final Context c, final Uri uri) {
    if("file".equals(uri.getScheme()) && uri.getPath() != null) {
      return new File(uri.getPath()).length();
    }
    final ContentResolver cr = c.getContentResolver();
    try(Cursor cur = cr.query(uri, new String[] {OpenableColumns.SIZE}, null, null, null)) {
      if(cur != null && cur.moveToFirst() && !cur.isNull(0)) {
        return cur.getLong(0);
      }
    } catch(final RuntimeException ignored) {
      // một số nhà cung cấp không hỗ trợ truy vấn cỡ
    }
    try(ParcelFileDescriptor pfd = cr.openFileDescriptor(uri, "r")) {
      if(pfd != null) {
        return pfd.getStatSize();
      }
    } catch(final IOException | RuntimeException ignored) {
      // không biết cỡ: kiểm chỗ trống dần khi giải nén
    }
    return -1;
  }

  /** Tên mục nguy hiểm: tuyệt đối, có thành phần rỗng / "." / "..", dấu \, ':' hay ký tự NUL */
  private static boolean unsafe(final String name) {
    if(name.isEmpty() || name.startsWith("/") || name.indexOf('\\') >= 0 || name.indexOf(':') >= 0 || name.indexOf('\0') >= 0) {
      return true;
    }
    final String body = name.endsWith("/") ? name.substring(0, name.length() - 1) : name;
    for(final String seg : body.split("/", -1)) {
      if(seg.isEmpty() || ".".equals(seg) || "..".equals(seg)) {
        return true;
      }
    }
    return false;
  }

  private static Map<String, File> extract(final Context c, final Uri uri, final File staging, final long size, final long avail,
                                           final Limits lim, final Payload.Progress progress) throws Failure, IOException {
    final Map<String, File> files = new LinkedHashMap<>();
    final String root = staging.getCanonicalPath() + File.separator;
    final byte[] buf = new byte[1 << 16];
    long total = 0;
    int entries = 0;
    boolean note = false;
    final InputStream raw = c.getContentResolver().openInputStream(uri);
    if(raw == null) {
      throw new IOException("openInputStream null");
    }
    final Counting counting = new Counting(raw, size, progress);
    final BufferedInputStream bin = new BufferedInputStream(counting, 1 << 16);
    try(ZipInputStream zip = new ZipInputStream(bin)) {
      while(true) {
        final ZipEntry e;
        try {
          e = zip.getNextEntry();
        } catch(final ZipException ex) {
          // Android 14+ (targetSdk >= 34) tự chặn mục ".." / "/..." bằng ZipPathValidator: "Invalid zip entry path"
          final String m = String.valueOf(ex.getMessage());
          if(m.contains("Invalid zip entry path")) {
            throw fail(c, R.string.hd_bad_zip, "bad_zip", R.string.hd_why_unsafe, "unsafe", m.replaceFirst("^.*path:\\s*", ""));
          }
          throw fail(c, R.string.hd_bad_zip, "bad_zip", R.string.hd_why_corrupt, "corrupt", m);
        } catch(final EOFException ex) {
          throw fail(c, R.string.hd_bad_zip, "bad_zip", R.string.hd_why_corrupt, "corrupt", "EOF");
        } catch(final IllegalArgumentException ex) {
          // tên mục không phải UTF-8 hợp lệ (ZipCoder: "MALFORMED")
          throw fail(c, R.string.hd_bad_zip, "bad_zip", R.string.hd_why_corrupt, "corrupt", String.valueOf(ex.getMessage()));
        }
        if(e == null) {
          break;
        }
        if(++entries > MAX_ENTRIES) {
          throw fail(c, R.string.hd_bad_zip, "bad_zip", R.string.hd_why_many, "many", MAX_ENTRIES);
        }
        final String name = e.getName();
        if(name.indexOf('\uFFFD') >= 0) {
          // tên mục không phải UTF-8: ZipInputStream của Android thay byte hỏng bằng U+FFFD (JDK máy tính thì ném
          // IllegalArgumentException ở trên) — cùng một lỗi cho cả hai
          throw fail(c, R.string.hd_bad_zip, "bad_zip", R.string.hd_why_corrupt, "corrupt", "tên mục không phải UTF-8");
        }
        if(unsafe(name)) {
          throw fail(c, R.string.hd_bad_zip, "bad_zip", R.string.hd_why_unsafe, "unsafe", name);
        }
        if(e.isDirectory()) {
          if(!DIRS.contains(name)) {
            throw fail(c, R.string.hd_wrong_format, "wrong_format", R.string.hd_why_extra, "extra", name);
          }
          continue;
        }
        final boolean isNote = NOTE.equals(name);
        if(!isNote && !DATA.matcher(name).matches()) {
          throw fail(c, R.string.hd_wrong_format, "wrong_format", R.string.hd_why_extra, "extra", name);
        }
        if(isNote ? note : files.containsKey(name)) {
          throw fail(c, R.string.hd_bad_zip, "bad_zip", R.string.hd_why_dup, "dup", name);
        }
        final long cap = isNote ? NOTE_CAP : INDEX.equals(name) || MANIFEST.equals(name) ? Math.min(INDEX_CAP, lim.entryCap) : lim.entryCap;
        if(e.getSize() > cap) {
          throw fail(c, R.string.hd_bad_zip, "bad_zip", R.string.hd_why_big, "big", name, (cap + (1 << 20) - 1) >> 20);
        }
        if(e.getSize() > 0 && total + e.getSize() > lim.totalCap) {
          throw fail(c, R.string.hd_bad_zip, "bad_zip", R.string.hd_why_total, "total", lim.totalCap >> 20);
        }

        final File out;
        if(isNote) {
          note = true;
          out = null;
        } else {
          out = new File(staging, name).getCanonicalFile();
          if(!out.getPath().startsWith(root)) {
            throw fail(c, R.string.hd_bad_zip, "bad_zip", R.string.hd_why_unsafe, "unsafe", name);
          }
          mkdirs(out.getParentFile());
        }
        final MessageDigest sha = name.endsWith(".png") ? sha1() : null;
        final byte[] head = new byte[HEAD];
        int headLen = 0;
        long n = 0;
        try(OutputStream os = out == null ? null : new BufferedOutputStream(new FileOutputStream(out), 1 << 16)) {
          int r;
          while((r = zip.read(buf)) > 0) {
            n += r;
            total += r;
            if(n > cap) {
              throw fail(c, R.string.hd_bad_zip, "bad_zip", R.string.hd_why_big, "big", name, (cap + (1 << 20) - 1) >> 20);
            }
            if(total > lim.totalCap) {
              throw fail(c, R.string.hd_bad_zip, "bad_zip", R.string.hd_why_total, "total", lim.totalCap >> 20);
            }
            if(total + SPACE_MARGIN + lim.reserve > avail) {
              throw noSpace(c, total + SPACE_MARGIN + lim.reserve, avail);
            }
            if(headLen < HEAD) {
              final int k = Math.min(r, HEAD - headLen);
              System.arraycopy(buf, 0, head, headLen, k);
              headLen += k;
            }
            if(sha != null) {
              sha.update(buf, 0, r);
            }
            if(os != null) {
              os.write(buf, 0, r);
            }
          }
        } catch(final ZipException | EOFException ex) {
          // zip cụt / CRC sai: ZipInputStream ném EOFException ("Unexpected end of ZLIB input stream") hoặc ZipException
          throw fail(c, R.string.hd_bad_zip, "bad_zip", R.string.hd_why_corrupt, "corrupt", name + ": " + ex.getMessage());
        }
        if(isNote) {
          continue;
        }
        if(name.endsWith(".lrm") && !lrmHeaderOk(head, headLen, n, name)) {
          throw fail(c, R.string.hd_wrong_format, "wrong_format", R.string.hd_why_lrm, "lrm", name);
        }
        if(sha != null && !pngOk(head, headLen, sha, name)) {
          throw fail(c, R.string.hd_wrong_format, "wrong_format", R.string.hd_why_png, "png", name);
        }
        files.put(name, out);
      }
      if(entries == 0) {
        throw fail(c, R.string.hd_bad_zip, "bad_zip", R.string.hd_why_empty, "empty");
      }
      checkEnd(c, bin, counting, entries);
    } catch(final ZipException | EOFException ex) {
      throw fail(c, R.string.hd_bad_zip, "bad_zip", R.string.hd_why_corrupt, "corrupt", String.valueOf(ex.getMessage()));
    }
    return files;
  }

  /** dữ liệu sau mục cuối được đọc tiếp tối đa chừng này để tìm mục lục cuối zip (4096 mục × ~200 byte, dư nhiều) */
  private static final long TRAILER_CAP = 16L << 20;

  /**
   * ZipInputStream đọc tuần tự các mục và coi "hết tệp ngay trước một mục" hay "gặp byte lạ thay cho mục kế" là hết zip, nên
   * một zip bị cắt đúng ranh giới giữa hai mục (chép chưa xong), thiếu mục lục cuối (bộ ghi chết giữa chừng) hoặc bị đọc lệch
   * (mục STORED có data descriptor trên Android) sẽ lọt qua với ít tệp hơn (ví dụ thiếu texture). Kiểm: đọc hết phần còn lại,
   * bản ghi kết thúc (EOCD, "PK\5\6") phải nằm đúng cuối tệp (sau nó chỉ có chú thích zip), đĩa 0, số mục trong mục lục = số
   * mục đã đọc, mục lục nằm liền ngay trước EOCD (hoặc trước bản ghi zip64).
   */
  private static void checkEnd(final Context c, final InputStream bin, final Counting counting, final int entries)
      throws Failure, IOException {
    final byte[] b = new byte[1 << 16];
    long extra = 0;
    int r;
    while((r = bin.read(b)) >= 0) {
      extra += r;
      if(extra > TRAILER_CAP) {
        throw incomplete(c, "có dữ liệu thừa sau mục cuối");
      }
    }
    final byte[] t = counting.tail();
    final long fileLen = counting.done;
    for(int i = t.length - 22; i >= 0 && i >= t.length - 22 - 0xffff; i--) {
      if(t[i] != 'P' || t[i + 1] != 'K' || t[i + 2] != 5 || t[i + 3] != 6 || i + 22 + u16(t, i + 20) != t.length) {
        continue;
      }
      final int disk = u16(t, i + 4);
      final int cdDisk = u16(t, i + 6);
      final int onDisk = u16(t, i + 8);
      final int count = u16(t, i + 10);
      final long cdSize = u32(t, i + 12);
      final long cdOff = u32(t, i + 16);
      final long eocdPos = fileLen - t.length + i;
      final boolean zip64 = i >= 20 && t[i - 20] == 'P' && t[i - 19] == 'K' && t[i - 18] == 6 && t[i - 17] == 7;
      if(disk != 0 || cdDisk != 0 || onDisk != count) {
        throw incomplete(c, "zip chia nhiều phần");
      }
      if(count != 0xffff && count != entries) {
        throw incomplete(c, "mục lục ghi " + count + " mục nhưng đọc được " + entries + " mục");
      }
      if(!zip64 && cdOff + cdSize != eocdPos) {
        throw incomplete(c, "mục lục cuối zip sai vị trí");
      }
      return;
    }
    throw incomplete(c, "thiếu mục lục cuối zip, có thể tệp chưa chép xong");
  }

  private static Failure incomplete(final Context c, final String detail) {
    Log.w(TAG, "zip khong tron ven: " + detail);
    return fail(c, R.string.hd_bad_zip, "bad_zip", R.string.hd_why_incomplete, "incomplete", detail);
  }

  private static int u16(final byte[] b, final int o) {
    return b[o] & 0xff | (b[o + 1] & 0xff) << 8;
  }

  private static long u32(final byte[] b, final int o) {
    return (u16(b, o) | (long)u16(b, o + 2) << 16) & 0xffffffffL;
  }

  /** §3.5.1: 'LRM1', u16 version = 1, modelKey (byte 8..27) = tên tệp; tệp >= 0x40 byte. Phần còn lại runtime tự kiểm (§3.5.4) */
  private static boolean lrmHeaderOk(final byte[] h, final int len, final long size, final String name) {
    if(len < 0x40 || size < 0x40 || h[0] != 'L' || h[1] != 'R' || h[2] != 'M' || h[3] != '1') {
      return false;
    }
    if(((h[4] & 0xff) | (h[5] & 0xff) << 8) != 1) {
      return false;
    }
    final String key = name.substring(name.lastIndexOf('/') + 1, name.length() - ".lrm".length());
    return hex(Arrays.copyOfRange(h, 8, 28)).equals(key);
  }

  /** §3.6.1: tên = SHA-1 của cả tệp; chữ ký PNG; IHDR rộng/cao luỹ thừa 2 trong 1..2048 */
  private static boolean pngOk(final byte[] h, final int len, final MessageDigest sha, final String name) {
    final String key = name.substring(name.lastIndexOf('/') + 1, name.length() - ".png".length());
    if(!hex(sha.digest()).equals(key) || len < 24) {
      return false;
    }
    for(int i = 0; i < PNG_SIG.length; i++) {
      if(h[i] != PNG_SIG[i]) {
        return false;
      }
    }
    if(h[12] != 'I' || h[13] != 'H' || h[14] != 'D' || h[15] != 'R') {
      return false;
    }
    final long w = be32(h, 16);
    final long hh = be32(h, 20);
    return pow2(w) && pow2(hh);
  }

  private static boolean pow2(final long v) {
    return v >= 1 && v <= 2048 && (v & (v - 1)) == 0;
  }

  private static long be32(final byte[] b, final int o) {
    return (b[o] & 0xffL) << 24 | (b[o + 1] & 0xffL) << 16 | (b[o + 2] & 0xffL) << 8 | b[o + 3] & 0xffL;
  }

  private static int validate(final Context c, final Map<String, File> files) throws Failure, IOException {
    final File index = files.get(INDEX);
    if(index == null) {
      throw fail(c, R.string.hd_wrong_format, "wrong_format", R.string.hd_why_noindex, "noindex");
    }
    final Set<String> keys = parseIndex(c, Files.readAllBytes(index.toPath()));
    for(final String k : keys) {
      if(!files.containsKey("remaster/models/" + k + ".lrm")) {
        throw fail(c, R.string.hd_wrong_format, "wrong_format", R.string.hd_why_missing, "missing", "models/" + k + ".lrm");
      }
    }
    final File manifest = files.get(MANIFEST);
    if(manifest != null) {
      boolean ok;
      try {
        final Object o = new JSONTokener(new String(Files.readAllBytes(manifest.toPath()), StandardCharsets.UTF_8)).nextValue();
        ok = o instanceof JSONObject && (!((JSONObject)o).has("format") || ((JSONObject)o).optInt("format", -1) == 1);
      } catch(final Exception | StackOverflowError e) {
        ok = false;   // StackOverflowError: JSON lồng quá sâu ("[[[[…"), org.json đọc đệ quy
      }
      if(!ok) {
        throw fail(c, R.string.hd_wrong_format, "wrong_format", R.string.hd_why_manifest, "manifest");
      }
    }
    return keys.size();
  }

  /** §3.7: UTF-8 không BOM, LF; dòng 1 "LRMINDEX\t1"; dòng sau "<khoá>\tmodels/<khoá>.lrm\t<nhãn>" hoặc rỗng; khoá không trùng */
  private static Set<String> parseIndex(final Context c, final byte[] b) throws Failure {
    if(b.length >= 3 && (b[0] & 0xff) == 0xef && (b[1] & 0xff) == 0xbb && (b[2] & 0xff) == 0xbf) {
      throw badIndex(c, 1);
    }
    final String s;
    try {
      s = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
        .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(b)).toString();
    } catch(final CharacterCodingException e) {
      throw badIndex(c, 1);
    }
    final String[] lines = s.split("\n", -1);
    final Set<String> keys = new LinkedHashSet<>();
    for(int i = 0; i < lines.length; i++) {
      final String line = lines[i];
      if(line.indexOf('\r') >= 0) {
        throw badIndex(c, i + 1);
      }
      if(i == 0) {
        if(!"LRMINDEX\t1".equals(line)) {
          throw badIndex(c, 1);
        }
        continue;
      }
      if(line.isEmpty()) {
        continue;
      }
      final String[] f = line.split("\t", -1);
      if(f.length != 3 || !KEY.matcher(f[0]).matches() || !("models/" + f[0] + ".lrm").equals(f[1]) || !keys.add(f[0])) {
        throw badIndex(c, i + 1);
      }
    }
    return keys;
  }

  private static Failure badIndex(final Context c, final int line) {
    return fail(c, R.string.hd_wrong_format, "wrong_format", R.string.hd_why_index, "index", line);
  }

  /** remaster → remaster.old, remaster.import/remaster → remaster, xoá remaster.old; lỗi đổi tên lần 2 thì trả bản cũ */
  private static void swap(final Context c, final File staging) throws IOException {
    final File cur = dataDir(c);
    final File old = oldDir(c);
    final File src = new File(staging, "remaster");
    deleteTree(old);
    if(cur.exists()) {
      Files.move(cur.toPath(), old.toPath(), StandardCopyOption.ATOMIC_MOVE);
    }
    try {
      Files.move(src.toPath(), cur.toPath(), StandardCopyOption.ATOMIC_MOVE);
    } catch(final IOException | RuntimeException e) {
      if(old.exists() && !cur.exists()) {
        Files.move(old.toPath(), cur.toPath(), StandardCopyOption.ATOMIC_MOVE);
      }
      throw e;
    }
    deleteQuiet(staging);
    deleteQuiet(old);
  }

  // ---------------------------------------------------------------- tiện ích

  private static Failure fail(final Context c, final int kindRes, final String kind, final int whyRes, final String why,
                              final Object... args) {
    return new Failure(kind + "/" + why, c.getString(kindRes, c.getString(whyRes, args)));
  }

  private static Failure noSpace(final Context c, final long need, final long avail) {
    return new Failure("no_space", c.getString(R.string.hd_no_space, (need + (1 << 20) - 1) >> 20, avail >> 20));
  }

  private static MessageDigest sha1() {
    try {
      return MessageDigest.getInstance("SHA-1");
    } catch(final NoSuchAlgorithmException e) {
      throw new IllegalStateException(e);
    }
  }

  private static String hex(final byte[] b) {
    final StringBuilder sb = new StringBuilder(b.length * 2);
    for(final byte x : b) {
      sb.append(Character.forDigit(x >> 4 & 0xf, 16)).append(Character.forDigit(x & 0xf, 16));
    }
    return sb.toString();
  }

  private static void mkdirs(final File d) throws IOException {
    if(!d.isDirectory() && !d.mkdirs()) {
      throw new IOException("mkdir " + d);
    }
  }

  private static void deleteQuiet(final File f) {
    try {
      deleteTree(f);
    } catch(final IOException e) {
      Log.w(TAG, "khong xoa duoc " + f + ": " + e);
    }
  }

  private static void deleteTree(final File f) throws IOException {
    if(Files.isSymbolicLink(f.toPath())) {
      Files.delete(f.toPath());
      return;
    }
    final File[] kids = f.listFiles();
    if(kids != null) {
      for(final File k : kids) {
        deleteTree(k);
      }
    }
    if(f.exists() && !f.delete()) {
      throw new IOException("delete " + f);
    }
  }

  /**
   * Đếm byte nén đã đọc để báo tiến độ (total < 0: không biết cỡ) và giữ 64 KB + 22 byte cuối cùng đã đọc (EOCD + chú thích
   * zip tối đa) cho {@link #checkEnd}. skip() cũng đọc qua đây để không byte nào lọt khỏi phần đuôi.
   */
  private static final class Counting extends FilterInputStream {
    private static final int TAIL = 0xffff + 22;
    private final long total;
    private final Payload.Progress progress;
    private final byte[] ring = new byte[TAIL];
    private long done;
    private long last;

    Counting(final InputStream in, final long total, final Payload.Progress progress) {
      super(in);
      this.total = total;
      this.progress = progress;
    }

    @Override
    public int read() throws IOException {
      final int b = super.read();
      if(b >= 0) {
        this.ring[(int)(this.done % TAIL)] = (byte)b;
        this.count(1);
      }
      return b;
    }

    @Override
    public int read(final byte[] b, final int off, final int len) throws IOException {
      final int n = super.read(b, off, len);
      if(n > 0) {
        // chỉ giữ tối đa TAIL byte cuối của lần đọc này, chép vào vòng (nhiều nhất hai đoạn)
        final int k = Math.min(n, TAIL);
        final int src = off + n - k;
        final int pos = (int)((this.done + n - k) % TAIL);
        final int first = Math.min(k, TAIL - pos);
        System.arraycopy(b, src, this.ring, pos, first);
        System.arraycopy(b, src + first, this.ring, 0, k - first);
        this.count(n);
      }
      return n;
    }

    @Override
    public long skip(final long n) throws IOException {
      final byte[] b = new byte[(int)Math.min(Math.max(n, 0), 1 << 16)];
      final int r = b.length == 0 ? 0 : this.read(b, 0, b.length);
      return Math.max(r, 0);
    }

    @Override
    public boolean markSupported() {
      return false;
    }

    /** các byte cuối cùng đã đọc (tối đa TAIL), theo thứ tự */
    byte[] tail() {
      final int n = (int)Math.min(this.done, TAIL);
      final byte[] t = new byte[n];
      for(int i = 0; i < n; i++) {
        t[i] = this.ring[(int)((this.done - n + i) % TAIL)];
      }
      return t;
    }

    private void count(final int n) {
      this.done += n;
      if(this.done - this.last >= (256 << 10)) {
        this.last = this.done;
        this.progress.update(this.done, this.total);
      }
    }
  }
}
