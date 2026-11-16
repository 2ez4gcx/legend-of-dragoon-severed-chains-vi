package vn.lodsc;

import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.net.Uri;
import android.os.Environment;
import android.provider.MediaStore;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.text.SimpleDateFormat;
import java.util.Arrays;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.TreeMap;
import java.util.zip.ZipEntry;
import java.util.zip.ZipException;
import java.util.zip.ZipInputStream;
import java.util.zip.ZipOutputStream;

/**
 * Xuất/nhập bản lưu của Severed Chains (game/saves/&lt;lượt chơi&gt;/*.dsav + campaign_config.dcnf) thành tệp .zip, để chuyển
 * giữa điện thoại và máy tính: bản lưu nằm trong bộ nhớ riêng của ứng dụng (allowBackup tắt, bản phát hành không debuggable)
 * nên người chơi không tự chép ra được. Hai bản dùng chung một bản dựng SC nên tệp .dsav dùng được ở cả hai.
 *
 * <p>Xuất: Download/LoD-ban-luu-&lt;ngày&gt;.zip (MediaStore, không cần quyền), trong zip là saves/&lt;lượt chơi&gt;_android/…
 * và tên lượt chơi thêm " (Android)" — giải nén vào thư mục "Severed Chains (VN)" trên máy tính không đè lượt chơi sẵn có ở đó.</p>
 *
 * <p>Nhập: zip có saves/&lt;lượt chơi&gt;/&lt;tệp&gt; (hoặc &lt;lượt chơi&gt;/&lt;tệp&gt;), chỉ nhận .dsav và campaign_config.dcnf.
 * Lượt chơi trùng tên mà khác nội dung được nhập thành lượt chơi mới (thư mục &lt;tên&gt;_nhap, tên thêm " (nhập)"); trùng
 * hệt thì bỏ qua. Không ghi đè gì.</p>
 */
final class SaveTransfer {
  private SaveTransfer() { }

  private static final String CONFIG = "campaign_config.dcnf";
  private static final String NAME_KEY = "lod_core:campaign_name";
  private static final String EXPORT_SUFFIX = "_android";
  private static final String EXPORT_LABEL = " (Android)";
  private static final int MAX_ENTRIES = 5000;
  private static final long MAX_TOTAL = 256L * 1024 * 1024;

  static File savesDir(final Context c) {
    return new File(Payload.gameDir(c), "saves");
  }

  /** Ghi tệp zip vào Download, trả câu báo kết quả */
  static String export(final Context c) throws IOException {
    final File[] campaigns = savesDir(c).listFiles(File::isDirectory);
    final Map<File, File[]> withSaves = new TreeMap<>();
    if(campaigns != null) {
      for(final File dir : campaigns) {
        final File[] saves = dir.listFiles((d, n) -> n.toLowerCase(Locale.ROOT).endsWith(".dsav"));
        if(saves != null && saves.length > 0) {
          Arrays.sort(saves);
          withSaves.put(dir, saves);
        }
      }
    }
    if(withSaves.isEmpty()) {
      return "Chưa có bản lưu nào để xuất.";
    }

    final String name = "LoD-ban-luu-" + new SimpleDateFormat("yyyyMMdd-HHmm", Locale.ROOT).format(new Date()) + ".zip";
    final ContentResolver resolver = c.getContentResolver();
    final ContentValues v = new ContentValues();
    v.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
    v.put(MediaStore.MediaColumns.MIME_TYPE, "application/zip");
    v.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS);
    v.put(MediaStore.MediaColumns.IS_PENDING, 1);
    final Uri uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
    if(uri == null) {
      throw new IOException("không tạo được tệp trong Download");
    }

    int saveCount = 0;
    try(OutputStream os = resolver.openOutputStream(uri)) {
      if(os == null) {
        throw new IOException("không ghi được tệp trong Download");
      }
      final ZipOutputStream zip = new ZipOutputStream(os);
      for(final Map.Entry<File, File[]> e : withSaves.entrySet()) {
        final File dir = e.getKey();
        final String folder = dir.getName().endsWith(EXPORT_SUFFIX) ? dir.getName() : dir.getName() + EXPORT_SUFFIX;
        final File cfg = new File(dir, CONFIG);
        final byte[] oldCfg = cfg.isFile() ? Files.readAllBytes(cfg.toPath()) : null;
        final String oldName = campaignName(oldCfg, dir.getName());
        final String newName = oldName.endsWith(EXPORT_LABEL) ? oldName : oldName + EXPORT_LABEL;
        put(zip, "saves/" + folder + "/" + CONFIG, withCampaignName(oldCfg, newName));
        for(final File save : e.getValue()) {
          put(zip, "saves/" + folder + "/" + save.getName(), Files.readAllBytes(save.toPath()));
          saveCount++;
        }
      }
      zip.finish();
    } catch(final IOException | RuntimeException ex) {
      resolver.delete(uri, null, null);
      throw ex;
    }

    v.clear();
    v.put(MediaStore.MediaColumns.IS_PENDING, 0);
    resolver.update(uri, v, null, null);
    return "Đã xuất " + withSaves.size() + " lượt chơi (" + saveCount + " bản lưu) vào tệp:\n\nDownload/" + name
      + "\n\nTrên máy tính: chép tệp này sang, giải nén vào thư mục \"Severed Chains (VN)\" (trong zip có sẵn thư mục saves)."
      + " Trong game, lượt chơi có thêm chữ \"(Android)\" sau tên.";
  }

  /** Nhập bản lưu từ tệp zip người chơi chọn, trả câu báo kết quả */
  static String importZip(final Context c, final Uri uri) throws IOException {
    // lượt chơi -> (tên tệp -> nội dung), theo thứ tự trong zip
    final Map<String, Map<String, byte[]>> campaigns = new LinkedHashMap<>();
    int skipped = 0;
    try(InputStream in = c.getContentResolver().openInputStream(uri)) {
      if(in == null) {
        throw new IOException("không mở được tệp");
      }
      final ZipInputStream zip = new ZipInputStream(in);
      long total = 0;
      int entries = 0;
      ZipEntry entry;
      while((entry = nextEntry(zip)) != null) {
        if(++entries > MAX_ENTRIES) {
          throw new IOException("tệp zip có quá nhiều mục");
        }
        if(entry.isDirectory()) {
          continue;
        }
        final String[] path = savePath(entry.getName());
        if(path == null) {
          skipped++;
          continue;
        }
        final byte[] data = readAll(zip, MAX_TOTAL - total);
        total += data.length;
        Map<String, byte[]> files = campaigns.get(path[0]);
        if(files == null) {
          files = new TreeMap<>();
          campaigns.put(path[0], files);
        }
        files.put(path[1], data);
      }
    }

    final File saves = savesDir(c);
    if(!saves.isDirectory() && !saves.mkdirs()) {
      throw new IOException("không tạo được thư mục saves");
    }

    int added = 0;
    int renamed = 0;
    int same = 0;
    int saveCount = 0;
    for(final Map.Entry<String, Map<String, byte[]>> e : campaigns.entrySet()) {
      final Map<String, byte[]> files = e.getValue();
      int dsav = 0;
      for(final String f : files.keySet()) {
        if(!f.equals(CONFIG)) {
          dsav++;
        }
      }
      if(dsav == 0) {
        continue;
      }

      String folder = e.getKey();
      File dest = new File(saves, folder);
      if(dest.exists()) {
        if(sameContent(dest, files)) {
          same++;
          continue;
        }
        // trùng tên, khác nội dung: thành lượt chơi mới, không ghi đè
        final String baseName = campaignName(files.get(CONFIG), folder);
        int n = 1;
        do {
          folder = e.getKey() + "_nhap" + (n == 1 ? "" : "_" + n);
          dest = new File(saves, folder);
          n++;
        } while(dest.exists());
        files.put(CONFIG, withCampaignName(files.get(CONFIG), baseName + (n == 2 ? " (nhập)" : " (nhập " + (n - 1) + ")")));
        renamed++;
      } else if(!files.containsKey(CONFIG)) {
        files.put(CONFIG, withCampaignName(null, folder));
      }

      // ghi vào thư mục tạm rồi đổi tên: game không thấy lượt chơi ghi dở
      final File tmp = new File(saves, ".nhap-" + System.nanoTime());
      if(!tmp.mkdirs()) {
        throw new IOException("không tạo được " + tmp);
      }
      for(final Map.Entry<String, byte[]> f : files.entrySet()) {
        try(FileOutputStream out = new FileOutputStream(new File(tmp, f.getKey()))) {
          out.write(f.getValue());
        }
      }
      if(!tmp.renameTo(dest)) {
        throw new IOException("không đổi tên được thành " + dest.getName());
      }
      added++;
      saveCount += dsav;
    }

    if(added == 0 && same == 0) {
      return "Tệp này không có bản lưu Severed Chains.\n\nCần tệp .zip chứa thư mục saves/<lượt chơi>/ với các tệp .dsav"
        + " (trên máy tính: nén thư mục saves trong \"Severed Chains (VN)\").";
    }
    final StringBuilder msg = new StringBuilder();
    if(added > 0) {
      msg.append("Đã nhập ").append(added).append(" lượt chơi (").append(saveCount).append(" bản lưu).");
      if(renamed > 0) {
        msg.append(' ').append(renamed).append(" lượt chơi trùng tên với lượt chơi sẵn có nên được nhập thành lượt chơi mới,"
          + " tên thêm chữ \"(nhập)\".");
      }
      msg.append("\n\nMở ở màn tựa → Chơi tiếp.");
    }
    if(same > 0) {
      msg.append(msg.length() > 0 ? "\n\n" : "").append(same).append(" lượt chơi đã có sẵn y hệt, bỏ qua.");
    }
    if(skipped > 0) {
      msg.append("\n\nBỏ qua ").append(skipped).append(" tệp không phải bản lưu.");
    }
    return msg.toString();
  }

  /**
   * [lượt chơi, tệp] của một mục zip, hoặc null nếu không phải bản lưu. Nhận saves/&lt;lượt chơi&gt;/&lt;tệp&gt; (có thể nằm
   * dưới thư mục khác, ví dụ "Severed Chains (VN)/saves/…") hoặc &lt;lượt chơi&gt;/&lt;tệp&gt;; tệp phải là .dsav hoặc
   * campaign_config.dcnf; không nhận "..", tên ẩn hay ký tự lạ.
   */
  private static String[] savePath(final String entryName) {
    final String[] all = entryName.replace('\\', '/').split("/");
    int start = 0;
    for(int i = 0; i < all.length; i++) {
      if(all[i].equalsIgnoreCase("saves")) {
        start = i + 1;
      }
    }
    final java.util.List<String> parts = new java.util.ArrayList<>();
    for(int i = start; i < all.length; i++) {
      if(!all[i].isEmpty() && !all[i].equals(".")) {
        parts.add(all[i]);
      }
    }
    if(parts.size() != 2) {
      return null;
    }
    final String campaign = parts.get(0);
    final String file = parts.get(1);
    if(!safeName(campaign) || !safeName(file)) {
      return null;
    }
    if(!file.equals(CONFIG) && !file.toLowerCase(Locale.ROOT).endsWith(".dsav")) {
      return null;
    }
    return new String[] {campaign, file};
  }

  /** Android 14+ từ chối mục zip có ".." hoặc đường dẫn tuyệt đối (ZipException): báo bằng tiếng Việt, không nhập gì */
  private static ZipEntry nextEntry(final ZipInputStream zip) throws IOException {
    try {
      return zip.getNextEntry();
    } catch(final ZipException e) {
      throw new IOException("tệp zip hỏng hoặc có đường dẫn không hợp lệ (" + e.getMessage() + "). Không có gì được nhập.", e);
    }
  }

  private static boolean safeName(final String s) {
    if(s.length() > 120 || s.startsWith(".")) {
      return false;
    }
    for(int i = 0; i < s.length(); i++) {
      final char ch = s.charAt(i);
      if(ch < 0x20 || "/\\:*?\"<>|".indexOf(ch) >= 0) {
        return false;
      }
    }
    return true;
  }

  private static boolean sameContent(final File dir, final Map<String, byte[]> files) throws IOException {
    for(final Map.Entry<String, byte[]> f : files.entrySet()) {
      if(f.getKey().equals(CONFIG)) {
        continue; // tùy chọn của lượt chơi có thể đã đổi; so các bản lưu
      }
      final File existing = new File(dir, f.getKey());
      if(!existing.isFile() || !Arrays.equals(Files.readAllBytes(existing.toPath()), f.getValue())) {
        return false;
      }
    }
    return true;
  }

  private static byte[] readAll(final InputStream in, final long limit) throws IOException {
    final ByteArrayOutputStream out = new ByteArrayOutputStream();
    final byte[] buf = new byte[64 * 1024];
    int n;
    while((n = in.read(buf)) > 0) {
      out.write(buf, 0, n);
      if(out.size() > limit) {
        throw new IOException("tệp zip quá lớn");
      }
    }
    return out.toByteArray();
  }

  private static void put(final ZipOutputStream zip, final String name, final byte[] data) throws IOException {
    zip.putNextEntry(new ZipEntry(name));
    zip.write(data);
    zip.closeEntry();
  }

  // campaign_config.dcnf (legend.game.saves.ConfigStorage): u32 số mục; mục = mã (độ dài 3 byte LE + ASCII) + u32 độ dài + giá
  // trị. Tên lượt chơi (lod_core:campaign_name, StringConfigEntry 1 byte độ dài) là tên hiện trong danh sách lượt chơi.

  /** Tên lượt chơi trong campaign_config.dcnf, hoặc fallback (SC cũng dùng tên thư mục khi thiếu) */
  static String campaignName(final byte[] cfg, final String fallback) {
    final Map<String, byte[]> records = parse(cfg);
    final byte[] v = records == null ? null : records.get(NAME_KEY);
    if(v == null || v.length < 1 || (v[0] & 0xff) > v.length - 1 || (v[0] & 0xff) == 0) {
      return fallback;
    }
    return new String(v, 1, v[0] & 0xff, StandardCharsets.UTF_8);
  }

  /** campaign_config.dcnf với tên lượt chơi mới, giữ các mục khác (tệp hỏng/không có thì chỉ có mục tên) */
  static byte[] withCampaignName(final byte[] cfg, final String name) {
    Map<String, byte[]> records = parse(cfg);
    if(records == null) {
      records = new LinkedHashMap<>();
    }
    byte[] utf8 = name.getBytes(StandardCharsets.UTF_8);
    if(utf8.length > 255) {
      int end = 255;
      while(end > 0 && (utf8[end] & 0xc0) == 0x80) {
        end--; // không cắt giữa một ký tự UTF-8
      }
      utf8 = Arrays.copyOf(utf8, end);
    }
    final byte[] value = new byte[utf8.length + 1];
    value[0] = (byte)utf8.length;
    System.arraycopy(utf8, 0, value, 1, utf8.length);
    records.put(NAME_KEY, value);

    final ByteArrayOutputStream out = new ByteArrayOutputStream();
    final ByteBuffer b4 = ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN);
    out.write(b4.putInt(0, records.size()).array(), 0, 4);
    for(final Map.Entry<String, byte[]> r : records.entrySet()) {
      final byte[] key = r.getKey().getBytes(StandardCharsets.US_ASCII);
      out.write(key.length & 0xff);
      out.write(key.length >>> 8 & 0xff);
      out.write(key.length >>> 16 & 0xff);
      out.write(key, 0, key.length);
      out.write(b4.putInt(0, r.getValue().length).array(), 0, 4);
      out.write(r.getValue(), 0, r.getValue().length);
    }
    return out.toByteArray();
  }

  /** mã -> giá trị theo thứ tự trong tệp, hoặc null nếu tệp không có/không đọc được */
  private static Map<String, byte[]> parse(final byte[] cfg) {
    if(cfg == null || cfg.length < 4) {
      return null;
    }
    try {
      final ByteBuffer b = ByteBuffer.wrap(cfg).order(ByteOrder.LITTLE_ENDIAN);
      final int count = b.getInt();
      final Map<String, byte[]> out = new LinkedHashMap<>();
      for(int i = 0; i < count; i++) {
        final int keyLength = (b.get() & 0xff) | (b.get() & 0xff) << 8 | (b.get() & 0xff) << 16;
        final byte[] key = new byte[keyLength];
        b.get(key);
        final int length = b.getInt();
        if(length < 0 || length > b.remaining()) {
          return null;
        }
        final byte[] value = new byte[length];
        b.get(value);
        out.put(new String(key, StandardCharsets.US_ASCII), value);
      }
      return out;
    } catch(final RuntimeException e) {
      return null;
    }
  }
}
