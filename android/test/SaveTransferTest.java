package vn.lodsc;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import java.util.zip.ZipOutputStream;

/**
 * Kiểm phần xuất/nhập bản lưu (SaveTransfer.writeZip / importFrom / exportFolders) trên máy tính, không cần điện thoại.
 *
 * Cách chạy: powershell -ExecutionPolicy Bypass -File android/test/save_transfer_test.ps1
 * (javac -source 8 cùng android.jar như make_apk.py; android.jar chỉ để nạp lớp, không gọi API Android). Exit 0 = đạt.
 */
public final class SaveTransferTest {
  private static int failures;

  public static void main(final String[] args) throws Exception {
    final File root = Files.createTempDirectory("savetransfer").toFile();
    try {
      exportWithSuffixClash(new File(root, "1"));
      exportPlain(new File(root, "2"));
      exportFoldersIgnoreCase();
      importOwnExportIsSkipped(new File(root, "3"));
      importIntoEmptyKeepsFolders(new File(root, "4"));
      importSameNameDifferentContent(new File(root, "5"));
      importRejectsOddPaths(new File(root, "6"));
      keybindsDoNotTravel(new File(root, "7"));
    } finally {
      delete(root);
    }
    System.out.println(failures == 0 ? "DAT: SaveTransferTest" : "LOI: " + failures + " kiem tra sai");
    System.exit(failures == 0 ? 0 : 1);
  }

  /** Lỗi người dùng báo (v0.4.3): máy có "l1" và "l1_android" -> "duplicate entry: saves/l1_android/campaign_config.dcnf" */
  private static void exportWithSuffixClash(final File saves) throws IOException {
    campaign(saves, "l1", "L1", "a.dsav", "A1", "b.dsav", "B1");
    campaign(saves, "l1_android", "L1 (Android)", "a.dsav", "A1");
    final Map<String, byte[]> zip = unzip(export(saves));
    check("clash: so muc", zip.size() == 5, zip.keySet());
    check("clash: l1 -> l1_android", "L1 (Android)".equals(nameIn(zip, "l1_android")) && zip.containsKey("saves/l1_android/b.dsav"), zip.keySet());
    check("clash: l1_android -> l1_android_2", "L1 (Android) 2".equals(nameIn(zip, "l1_android_2"))
      && zip.containsKey("saves/l1_android_2/a.dsav") && !zip.containsKey("saves/l1_android_2/b.dsav"), zip.keySet());
  }

  /** Trường hợp thường không đổi: "l1" -> "l1_android", tên thêm " (Android)" */
  private static void exportPlain(final File saves) throws IOException {
    campaign(saves, "l1", "L1", "a.dsav", "A1");
    campaign(saves, "empty", "Trong", new String[0]);
    final Map<String, byte[]> zip = unzip(export(saves));
    check("plain: chi luot choi co ban luu",zip.keySet().equals(new java.util.TreeSet<>(Arrays.asList(
      "saves/l1_android/a.dsav", "saves/l1_android/campaign_config.dcnf"))), zip.keySet());
    check("plain: ten", "L1 (Android)".equals(nameIn(zip, "l1_android")), nameIn(zip, "l1_android"));
  }

  /** Windows không phân biệt hoa thường: "A" -> "A_android" chiếm luôn "a_android" */
  private static void exportFoldersIgnoreCase() {
    final Map<File, String> f = SaveTransfer.exportFolders(Arrays.asList(new File("a_android"), new File("A")));
    check("hoa thuong", "A_android".equals(f.get(new File("A"))) && "a_android_2".equals(f.get(new File("a_android"))), f);
  }

  /** Nhập lại tệp xuất của chính máy này: bản lưu đã có y hệt (dù khác tên thư mục) -> bỏ qua, không thêm lượt chơi */
  private static void importOwnExportIsSkipped(final File saves) throws IOException {
    campaign(saves, "l1", "L1", "a.dsav", "A1", "b.dsav", "B1");
    final byte[] zip = export(saves);
    final String msg = SaveTransfer.importFrom(new ByteArrayInputStream(zip), saves);
    check("nhap lai: khong them thu muc", dirs(saves).equals(Arrays.asList("l1")), dirs(saves));
    check("nhap lai: bao da co", msg.contains("1 lượt chơi đã có sẵn y hệt"), msg);
  }

  /**
   * Máy trống (máy tính / điện thoại khác): giữ tên thư mục và tên lượt chơi trong zip. "l1_android" ở đây là lượt chơi khác
   * thật (nhập từ điện thoại khác); bản sao y hệt của "l1" thì chỉ nhập một lần.
   */
  private static void importIntoEmptyKeepsFolders(final File base) throws IOException {
    final File phone = new File(base, "phone");
    campaign(phone, "l1", "L1", "a.dsav", "A1", "b.dsav", "B1");
    campaign(phone, "l1_android", "L1 (Android)", "a.dsav", "KHAC");
    final File other = new File(base, "other");
    final String msg = SaveTransfer.importFrom(new ByteArrayInputStream(export(phone)), other);
    check("may trong: thu muc", dirs(other).equals(Arrays.asList("l1_android", "l1_android_2")), dirs(other));
    check("may trong: ten", "L1 (Android) 2".equals(nameOf(new File(other, "l1_android_2"))), nameOf(new File(other, "l1_android_2")));
    check("may trong: noi dung", "KHAC".equals(read(new File(other, "l1_android_2/a.dsav"))), read(new File(other, "l1_android_2/a.dsav")));
    check("may trong: bao", msg.startsWith("Đã nhập 2 lượt chơi (3 bản lưu)."), msg);

    // máy của người báo lỗi: "l1_android" là bản nhập lại của "l1" (cùng bản lưu) -> nhập sang máy khác chỉ ra một lượt chơi
    final File phone2 = new File(base, "phone2");
    campaign(phone2, "l1", "L1", "a.dsav", "A1", "b.dsav", "B1");
    campaign(phone2, "l1_android", "L1 (Android)", "a.dsav", "A1");
    final File other2 = new File(base, "other2");
    final String msg2 = SaveTransfer.importFrom(new ByteArrayInputStream(export(phone2)), other2);
    check("ban sao: mot luot choi", dirs(other2).equals(Arrays.asList("l1_android")), dirs(other2));
    check("ban sao: bao", msg2.contains("Đã nhập 1 lượt chơi (2 bản lưu).") && msg2.contains("1 lượt chơi đã có sẵn y hệt"), msg2);
  }

  /** Trùng tên thư mục, khác nội dung: thành <tên>_nhap, bản cũ không đổi */
  private static void importSameNameDifferentContent(final File saves) throws IOException {
    campaign(saves, "x", "X", "a.dsav", "OLD");
    final byte[] zip = zipOf("saves/x/a.dsav", "NEW");
    final String msg = SaveTransfer.importFrom(new ByteArrayInputStream(zip), saves);
    check("trung ten: thu muc", dirs(saves).equals(Arrays.asList("x", "x_nhap")), dirs(saves));
    check("trung ten: ban cu giu nguyen", "OLD".equals(read(new File(saves, "x/a.dsav"))), read(new File(saves, "x/a.dsav")));
    check("trung ten: bao", msg.contains("(nhập)"), msg);
  }

  /** Đường dẫn lạ (../, tệp không phải bản lưu) bị bỏ, không ghi ra ngoài saves */
  private static void importRejectsOddPaths(final File saves) throws IOException {
    final byte[] zip = zipOf("saves/../evil.dsav", "E", "saves/y/../../z.dsav", "E", "saves/ok/note.txt", "T");
    final String msg = SaveTransfer.importFrom(new ByteArrayInputStream(zip), saves);
    check("duong dan la: khong ghi gi", dirs(saves).isEmpty() && !new File(saves.getParentFile(), "evil.dsav").exists(), dirs(saves));
    check("duong dan la: bao", msg.startsWith("Tệp này không có bản lưu"), msg);
  }

  /**
   * Nút điều khiển đã đổi không đi theo lượt chơi (tester: đổi "mở menu" sang phím trên máy tính, sang điện thoại không mở
   * được menu để sửa). Các mục khác của campaign_config.dcnf giữ nguyên.
   */
  private static void keybindsDoNotTravel(final File base) throws IOException {
    final byte[] keybinds = {1, 2, 3, 4};
    final byte[] other = {9};
    final byte[] cfg = dcnf("lod_core:campaign_name", new byte[] {2, 'P', 'C'}, SaveTransfer.KEYBINDS_KEY, keybinds,
      "lod_core:run_by_default", other);

    // điện thoại -> máy tính (Xuất)
    final File phone = new File(base, "phone");
    final File d = new File(phone, "pc");
    d.mkdirs();
    write(new File(d, "campaign_config.dcnf"), cfg);
    write(new File(d, "a.dsav"), "A".getBytes("UTF-8"));
    final Map<String, byte[]> zip = unzip(export(phone));
    final Map<String, byte[]> exported = records(zip.get("saves/pc_android/campaign_config.dcnf"));
    check("xuat: bo nut", !exported.containsKey(SaveTransfer.KEYBINDS_KEY), exported.keySet());
    check("xuat: giu muc khac", Arrays.equals(other, exported.get("lod_core:run_by_default")), exported.keySet());
    check("xuat: ten", "PC (Android)".equals(nameIn(zip, "pc_android")), nameIn(zip, "pc_android"));

    // máy tính -> điện thoại (Nhập), cả khi thư mục trùng tên khác nội dung (thành _nhap)
    final File target = new File(base, "target");
    campaign(target, "pc", "Cu", "a.dsav", "KHAC");
    final String msg = SaveTransfer.importFrom(new ByteArrayInputStream(zipOf2("saves/pc/campaign_config.dcnf", cfg,
      "saves/pc/a.dsav", "A".getBytes("UTF-8"), "saves/pc2/campaign_config.dcnf", cfg, "saves/pc2/b.dsav", "B".getBytes("UTF-8"))), target);
    final Map<String, byte[]> renamed = records(Files.readAllBytes(new File(target, "pc_nhap/campaign_config.dcnf").toPath()));
    final Map<String, byte[]> fresh = records(Files.readAllBytes(new File(target, "pc2/campaign_config.dcnf").toPath()));
    check("nhap: bo nut (thu muc moi)", !fresh.containsKey(SaveTransfer.KEYBINDS_KEY) && Arrays.equals(other, fresh.get("lod_core:run_by_default")), fresh.keySet());
    check("nhap: ten giu nguyen", "PC".equals(nameOf(new File(target, "pc2"))), nameOf(new File(target, "pc2")));
    check("nhap: bo nut (_nhap)", !renamed.containsKey(SaveTransfer.KEYBINDS_KEY) && Arrays.equals(other, renamed.get("lod_core:run_by_default")), renamed.keySet());
    check("nhap: bao nut mac dinh", msg.contains("nút mặc định"), msg);
  }

  // --- tiện ích ---

  /** campaign_config.dcnf: u32 số mục; mục = mã (3 byte LE + ASCII) + u32 độ dài + giá trị */
  private static byte[] dcnf(final Object... kv) throws IOException {
    final ByteArrayOutputStream out = new ByteArrayOutputStream();
    final java.nio.ByteBuffer b4 = java.nio.ByteBuffer.allocate(4).order(java.nio.ByteOrder.LITTLE_ENDIAN);
    out.write(b4.putInt(0, kv.length / 2).array());
    for(int i = 0; i + 1 < kv.length; i += 2) {
      final byte[] key = ((String)kv[i]).getBytes("US-ASCII");
      out.write(key.length);
      out.write(0);
      out.write(0);
      out.write(key);
      final byte[] v = (byte[])kv[i + 1];
      out.write(b4.putInt(0, v.length).array());
      out.write(v);
    }
    return out.toByteArray();
  }

  private static Map<String, byte[]> records(final byte[] cfg) {
    final java.nio.ByteBuffer b = java.nio.ByteBuffer.wrap(cfg).order(java.nio.ByteOrder.LITTLE_ENDIAN);
    final Map<String, byte[]> out = new TreeMap<>();
    for(int i = b.getInt(); i > 0; i--) {
      final byte[] key = new byte[(b.get() & 0xff) | (b.get() & 0xff) << 8 | (b.get() & 0xff) << 16];
      b.get(key);
      final byte[] v = new byte[b.getInt()];
      b.get(v);
      out.put(new String(key, java.nio.charset.StandardCharsets.US_ASCII), v);
    }
    return out;
  }

  private static byte[] zipOf2(final Object... entries) throws IOException {
    final ByteArrayOutputStream out = new ByteArrayOutputStream();
    try(ZipOutputStream zip = new ZipOutputStream(out)) {
      for(int i = 0; i + 1 < entries.length; i += 2) {
        zip.putNextEntry(new ZipEntry((String)entries[i]));
        zip.write((byte[])entries[i + 1]);
        zip.closeEntry();
      }
    }
    return out.toByteArray();
  }

  private static void campaign(final File saves, final String dir, final String name, final String... files) throws IOException {
    final File d = new File(saves, dir);
    if(!d.mkdirs()) {
      throw new IOException("mkdirs " + d);
    }
    write(new File(d, "campaign_config.dcnf"), SaveTransfer.withCampaignName(null, name));
    for(int i = 0; i + 1 < files.length; i += 2) {
      write(new File(d, files[i]), files[i + 1].getBytes("UTF-8"));
    }
  }

  private static byte[] export(final File saves) throws IOException {
    final ByteArrayOutputStream out = new ByteArrayOutputStream();
    SaveTransfer.writeZip(SaveTransfer.campaignsWithSaves(saves), out);
    return out.toByteArray();
  }

  private static byte[] zipOf(final String... entries) throws IOException {
    final ByteArrayOutputStream out = new ByteArrayOutputStream();
    try(ZipOutputStream zip = new ZipOutputStream(out)) {
      for(int i = 0; i + 1 < entries.length; i += 2) {
        zip.putNextEntry(new ZipEntry(entries[i]));
        zip.write(entries[i + 1].getBytes("UTF-8"));
        zip.closeEntry();
      }
    }
    return out.toByteArray();
  }

  private static Map<String, byte[]> unzip(final byte[] data) throws IOException {
    final Map<String, byte[]> out = new TreeMap<>();
    try(ZipInputStream zip = new ZipInputStream(new ByteArrayInputStream(data))) {
      ZipEntry e;
      while((e = zip.getNextEntry()) != null) {
        final ByteArrayOutputStream b = new ByteArrayOutputStream();
        final byte[] buf = new byte[8192];
        int n;
        while((n = zip.read(buf)) > 0) {
          b.write(buf, 0, n);
        }
        if(out.put(e.getName(), b.toByteArray()) != null) {
          throw new IOException("muc trung " + e.getName());
        }
      }
    }
    return out;
  }

  private static String nameIn(final Map<String, byte[]> zip, final String folder) {
    return SaveTransfer.campaignName(zip.get("saves/" + folder + "/campaign_config.dcnf"), null);
  }

  private static String nameOf(final File dir) throws IOException {
    return SaveTransfer.campaignName(Files.readAllBytes(new File(dir, "campaign_config.dcnf").toPath()), null);
  }

  private static List<String> dirs(final File saves) {
    final List<String> out = new ArrayList<>();
    final File[] list = saves.listFiles(File::isDirectory);
    if(list != null) {
      for(final File f : list) {
        out.add(f.getName());
      }
    }
    out.sort(Comparator.naturalOrder());
    return out;
  }

  private static String read(final File f) throws IOException {
    return new String(Files.readAllBytes(f.toPath()), "UTF-8");
  }

  private static void write(final File f, final byte[] data) throws IOException {
    try(FileOutputStream out = new FileOutputStream(f)) {
      out.write(data);
    }
  }

  private static void check(final String what, final boolean ok, final Object detail) {
    System.out.println((ok ? "  ok   " : "  SAI  ") + what + (ok ? "" : "  -> " + detail));
    if(!ok) {
      failures++;
    }
  }

  private static void delete(final File f) {
    final File[] kids = f.listFiles();
    if(kids != null) {
      for(final File k : kids) {
        delete(k);
      }
    }
    f.delete();
  }
}
