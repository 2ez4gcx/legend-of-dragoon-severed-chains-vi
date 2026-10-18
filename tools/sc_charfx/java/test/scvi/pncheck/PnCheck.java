package scvi.pncheck;

import legend.core.renderer.MeshObj;
import legend.game.tmd.TmdObjLoader;
import legend.game.tmd.TmdObjTable1c;
import legend.game.types.CContainer;
import legend.game.unpacker.FileData;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.lang.reflect.Field;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * PnCheck — phép thử không cần GL cho jar thử sc-charfx (gọi từ tools/sc_charfx/java/build.ps1 -Check).
 *
 * Nạp vài TMD thật của bản build SC (game/files: Dart chiến đấu/rồng, Dart ở cảnh DRGN21/26 và DRGN21/5, một quái, một sàn trận)
 * qua TmdObjLoader.fromObjTable(tên, phần, 0, 0, 0) — đúng lớp nào đứng đầu classpath thì lớp đó chạy (jar game = bản gốc,
 * out/sc-charfx.jar = bản ghi đè) — mỗi TMD hai lần: tên kiểu nhân vật (PnConfig phải bật) và tên không phải nhân vật
 * (Shadow/Savepoint/BattleModel/Particle/sàn trận: phải giữ nguyên). Lưới được CaptureApi ghi lại (GameEngine giả).
 *
 * Cách gọi (classpath: out/sc_charfx_test; [out/sc-charfx.jar;] jar game; game/libs/*):
 *   PnCheck dump <ra.bin> <thư mục game/files>     ghi mọi lưới (đỉnh dạng bit float thô, chỉ số, cờ backface) ra tệp;
 *                                                  có -Dscvi.pn>0 thì kèm tổng góc / góc PN / bit cạnh thẳng tính thẳng bằng
 *                                                  PnEdgeFlags.compute để đối chiếu
 *   PnCheck same <a.bin> <b.bin>                   hai tệp phải giống từng byte (bản gốc vs bản ghi đè khi tắt PN)
 *   PnCheck pn <goc.bin> <pn.bin> <mức> <độ mạnh>  tệp có PN so với bản gốc: mọi float ngoài cờ giống hệt, 5 bit cờ gốc giữ nguyên,
 *                                                  mức/độ mạnh đúng, không có bit PN trên mặt trong suốt/không LIT (tmd_pn.gsh vẽ
 *                                                  chúng theo đường gốc), chỉ số góc cục bộ đúng thứ tự, bit cạnh thẳng đối xứng trong mặt và
 *                                                  thống nhất giữa các mặt chung cạnh (kín), tổng khớp PnEdgeFlags; tên không phải
 *                                                  nhân vật: lưới giống hệt
 * Định dạng tệp: "PCK1", số mục; mỗi mục: nhãn, tên, expectPn, backface, 3 số tổng (-1 nếu không tính), số lưới; mỗi lưới: tên,
 * kiểu đỉnh, textured, translucent, translucency, số float + bit float, số chỉ số + chỉ số (DataOutputStream, big-endian).
 * Tệp chứa dữ liệu mô hình của Sony: chỉ ghi vào work/upscale (git bỏ qua). Exit 0 = đạt, 1 = lỗi.
 */
public final class PnCheck {
  private PnCheck() { }

  static final int STRIDE = TmdObjLoader.VERTEX_SIZE;
  static final int FLAGS = STRIDE - 1;
  static final int MAGIC = 0x50434B31;
  /**
   * characters/dart/models/combat/32 ở mức 4: số góc, bit cạnh thẳng. PnCount của bước nghiên cứu ra 1954 / 1360 khi mặt trong suốt
   * còn được bật PN; từ khi PnEdgeFlags loại mặt TRANSLUCENT (1 mặt tứ giác của Dart: +18 bit, 1950 góc PN) con số là 1954 / 1378,
   * khớp một bản cài lại độc lập bằng Python (bộ đọc TMD + luật cạnh viết riêng, so từng góc trong tệp dump).
   */
  static final int REF_DART_CORNERS = 1954;
  static final int REF_DART_PN = 1950;
  static final int REF_DART_LINEAR = 1378;

  record Model(String label, String path, int subfileSize, String pnName, String plainName) { }

  static final Model[] MODELS = {
    new Model("dart_combat", "characters/dart/models/combat/32", 7, "CombatantModel (Dart) part %d", "BattleModel dart part %d"),
    new Model("dart_dragoon", "characters/dart/models/dragoon/32", 7, "CombatantModel (Dart dragoon) part %d", "Shadow part %d"),
    new Model("dart_field_26", "SECT/DRGN21.BIN/26/0", 7, "SobjModel (index 0) part %d", "Savepoint part %d"),
    new Model("dart_field_5", "SECT/DRGN21.BIN/5/0", 7, "SobjModel (index 1) part %d", "Particle %d"),
    new Model("enemy_3137", "SECT/DRGN0.BIN/3137/32", 7, "CombatantModel (enemy 0) part %d", "Kongol rock %d"),
    new Model("stage_2497", "SECT/DRGN0.BIN/2497/0/0", 10, "WmapEntityModel (index 0) part %d", "DRGN0/2497/0 obj %d"),
  };

  record MeshData(String name, String order, boolean textured, boolean translucent, String translucency, int[] vertexBits, int[] indices) { }

  record Entry(String label, String name, boolean expectPn, boolean backface, int[] direct, List<MeshData> meshes) { }

  public static void main(final String[] args) throws Exception {
    final int rc = switch(args.length > 0 ? args[0] : "") {
      case "dump" -> dump(Path.of(args[1]), Path.of(args[2]));
      case "same" -> same(Path.of(args[1]), Path.of(args[2]));
      case "pn" -> pn(read(Path.of(args[1])), read(Path.of(args[2])), Integer.parseInt(args[3]), Integer.parseInt(args[4]));
      case "selftest" -> selftest(Path.of(args[1]), Path.of(args[2]));
      default -> {
        System.out.println("PnCheck dump <out.bin> <files> | same <a> <b> | pn <orig> <pn> <level> <strength8> | selftest <orig> <pn4>");
        yield 1;
      }
    };
    System.exit(rc);
  }

  // ---------- dump ----------

  static int dump(final Path out, final Path files) throws Exception {
    final boolean direct = Integer.getInteger("scvi.pn", 0) > 0;
    final Field backfaceField = MeshObj.class.getDeclaredField("backfaceCulling");
    backfaceField.setAccessible(true);
    final List<Entry> entries = new ArrayList<>();
    int meshes = 0;
    int vertices = 0;

    for(final Model model : MODELS) {
      final byte[] bytes = Files.readAllBytes(files.resolve(model.path()));

      for(int variant = 0; variant < 2; variant++) {
        final CContainer container = new CContainer(model.label(), new FileData(bytes), model.subfileSize());
        final TmdObjTable1c[] tables = container.tmdPtr_00.tmd.objTable;

        for(int part = 0; part < tables.length; part++) {
          final String name = (variant == 0 ? model.pnName() : model.plainName()).formatted(part);
          final int before = CaptureApi.MESHES.size();
          final MeshObj obj = TmdObjLoader.fromObjTable(name, tables[part], 0, 0, 0);
          final List<MeshData> list = new ArrayList<>();

          for(final CaptureApi.Captured c : CaptureApi.MESHES.subList(before, CaptureApi.MESHES.size())) {
            final int[] bits = new int[c.vertices().length];
            for(int i = 0; i < bits.length; i++) {
              bits[i] = Float.floatToRawIntBits(c.vertices()[i]);
            }
            list.add(new MeshData(c.name(), c.order().name(), c.textured(), c.translucent(), c.translucency() == null ? "" : c.translucency().name(), bits, c.indices()));
            vertices += bits.length / STRIDE;
          }

          meshes += list.size();
          final int[] agg = direct && variant == 0 ? Direct.aggregate(tables[part]) : new int[] {-1, -1, -1};
          entries.add(new Entry(model.label(), name, variant == 0, backfaceField.getBoolean(obj), agg, list));
        }
      }
    }

    write(out, entries);
    System.out.printf("dump %s: %d phan mo hinh, %d luoi, %d dinh (TmdObjLoader tu %s)%n", out.getFileName(), entries.size(), meshes, vertices,
      TmdObjLoader.class.getProtectionDomain().getCodeSource().getLocation());
    return 0;
  }

  /** Tính thẳng bằng PnEdgeFlags (chỉ gọi khi có lớp ghi đè trên classpath). */
  static final class Direct {
    static int[] aggregate(final TmdObjTable1c table) {
      int corners = 0;
      int pn = 0;
      int linear = 0;
      for(final int[][] group : legend.game.tmd.PnEdgeFlags.compute(table, 0, true)) {
        for(final int[] packet : group) {
          for(final int f : packet) {
            corners++;
            if((f & 0x800) != 0) {
              pn++;
            }
            linear += Integer.bitCount(f >> 7 & 0xf);
          }
        }
      }
      return new int[] {corners, pn, linear};
    }
  }

  // ---------- same ----------

  static int same(final Path a, final Path b) throws IOException {
    final long mismatch = Files.mismatch(a, b);
    if(mismatch == -1) {
      System.out.printf("DAT: %s == %s (%d byte)%n", a.getFileName(), b.getFileName(), Files.size(a));
      return 0;
    }

    System.out.printf("LOI: %s khac %s tu byte %d%n", a.getFileName(), b.getFileName(), mismatch);
    final List<Entry> ea = read(a);
    final List<Entry> eb = read(b);
    for(int i = 0; i < Math.min(ea.size(), eb.size()); i++) {
      final Entry x = ea.get(i);
      final Entry y = eb.get(i);
      for(int m = 0; m < Math.min(x.meshes().size(), y.meshes().size()); m++) {
        final int[] vx = x.meshes().get(m).vertexBits();
        final int[] vy = y.meshes().get(m).vertexBits();
        for(int k = 0; k < Math.min(vx.length, vy.length); k++) {
          if(vx[k] != vy[k]) {
            System.out.printf("  dau tien: %s luoi %d dinh %d thanh phan %d: %s vs %s%n", x.name(), m, k / STRIDE, k % STRIDE,
              Float.intBitsToFloat(vx[k]), Float.intBitsToFloat(vy[k]));
            return 1;
          }
        }
      }
    }
    return 1;
  }

  // ---------- pn ----------

  static int pn(final List<Entry> orig, final List<Entry> pn, final int level, final int strength8) {
    final List<String> errors = new ArrayList<>();
    final Map<String, int[]> totals = new LinkedHashMap<>(); // nhãn -> góc, góc PN, bit cạnh thẳng, cạnh chung, phần

    if(orig.size() != pn.size()) {
      System.out.printf("LOI: so muc khac nhau %d vs %d%n", orig.size(), pn.size());
      return 1;
    }

    for(int e = 0; e < orig.size(); e++) {
      final Entry o = orig.get(e);
      final Entry p = pn.get(e);
      final String where = p.name();

      if(!o.label().equals(p.label()) || !o.name().equals(p.name()) || o.expectPn() != p.expectPn() || o.meshes().size() != p.meshes().size()) {
        errors.add(where + ": muc/luoi khong khop");
        continue;
      }

      if(o.backface() != p.backface()) {
        errors.add(where + ": backfaceCulling khac");
      }

      final Map<Long, Integer> edgeLinear = new HashMap<>();
      final int[] agg = new int[3];
      int sharedEdges = 0;

      for(int m = 0; m < o.meshes().size(); m++) {
        final MeshData mo = o.meshes().get(m);
        final MeshData mp = p.meshes().get(m);
        final String at = where + " luoi " + m;

        if(!mo.name().equals(mp.name()) || !mo.order().equals(mp.order()) || mo.textured() != mp.textured() || mo.translucent() != mp.translucent()
          || !mo.translucency().equals(mp.translucency()) || !java.util.Arrays.equals(mo.indices(), mp.indices()) || mo.vertexBits().length != mp.vertexBits().length) {
          errors.add(at + ": thong tin luoi/chi so/so dinh khac");
          continue;
        }

        final int[] vo = mo.vertexBits();
        final int[] vp = mp.vertexBits();
        final int count = vo.length / STRIDE;

        if(!p.expectPn()) {
          if(!java.util.Arrays.equals(vo, vp)) {
            errors.add(at + ": ten khong phai nhan vat nhung du lieu dinh bi doi");
          }
          continue;
        }

        // Từng đỉnh: ngoài cờ phải giống hệt; cờ = cờ gốc | bit PN
        final int[] flags = new int[count];
        boolean ok = true;
        for(int v = 0; v < count && ok; v++) {
          for(int c = 0; c < FLAGS; c++) {
            if(vo[v * STRIDE + c] != vp[v * STRIDE + c]) {
              errors.add(at + " dinh " + v + ": thanh phan " + c + " bi doi");
              ok = false;
              break;
            }
          }
          final float fo = Float.intBitsToFloat(vo[v * STRIDE + FLAGS]);
          final float fp = Float.intBitsToFloat(vp[v * STRIDE + FLAGS]);
          final int io = (int)fo;
          final int ip = (int)fp;
          if(ok && ((float)io != fo || (float)ip != fp || io < 0 || io >= 0x20 || ip < 0)) {
            errors.add(at + " dinh " + v + ": co khong nguyen/ngoai mien (" + fo + ", " + fp + ")");
            ok = false;
          }
          if(ok && ((ip & 0x1f) != io || (ip >> 12 & 7) != level || (ip >> 15 & 0xf) != strength8 || ip >>> 19 != 0)) {
            errors.add(at + " dinh " + v + ": co sai 0x" + Integer.toHexString(ip) + " (goc 0x" + Integer.toHexString(io) + ")");
            ok = false;
          }
          // tmd_pn.gsh vẽ mặt TRANSLUCENT/không LIT theo đường gốc -> bit PN ở đó sẽ làm hở cạnh chung với mặt đục
          if(ok && (ip & 0x800) != 0 && ((io & 0x8) != 0 || (io & 0x1) == 0)) {
            errors.add(at + " dinh " + v + ": bit PN tren mat trong suot/khong LIT (0x" + Integer.toHexString(ip) + ")");
            ok = false;
          }
          flags[v] = ip;
        }
        if(!ok) {
          continue;
        }

        // Từng mặt (3 hoặc 4 đỉnh liên tiếp, theo bit QUAD)
        int pos = 0;
        while(pos < count) {
          final boolean quad = (flags[pos] & 0x10) != 0;
          final int n = quad ? 4 : 3;
          if(pos + n > count) {
            errors.add(at + ": mat cuoi thieu dinh");
            break;
          }
          for(int k = 0; k < n; k++) {
            final int f = flags[pos + k];
            if((f >> 5 & 3) != k || ((f & 0x10) != 0) != quad || ((f & 0x800) != 0) != ((flags[pos] & 0x800) != 0)) {
              errors.add(at + " mat tai dinh " + pos + ": goc " + k + " sai chi so goc/QUAD/PN (0x" + Integer.toHexString(f) + ")");
            }
            for(int j = 0; j < n; j++) {
              if(j != k && linear(f, j) != linear(flags[pos + j], k)) {
                errors.add(at + " mat tai dinh " + pos + ": bit canh thang " + k + "-" + j + " khong doi xung");
              }
            }
            agg[0]++;
            if((f & 0x800) != 0) {
              agg[1]++;
            }
            agg[2] += Integer.bitCount(f >> 7 & 0xf);
          }
          final int[][] ring = quad ? new int[][] {{0, 1}, {1, 3}, {3, 2}, {2, 0}} : new int[][] {{0, 1}, {1, 2}, {2, 0}};
          for(final int[] edge : ring) {
            final int a = (int)Float.intBitsToFloat(vp[(pos + edge[0]) * STRIDE + 3]);
            final int b = (int)Float.intBitsToFloat(vp[(pos + edge[1]) * STRIDE + 3]);
            final long key = (long)Math.min(a, b) << 32 | Math.max(a, b);
            final int value = linear(flags[pos + edge[0]], edge[1]) ? 1 : 0;
            final Integer prev = edgeLinear.putIfAbsent(key, value);
            if(prev != null) {
              sharedEdges++;
              if(prev != value) {
                errors.add(at + ": canh " + a + "-" + b + " thang o mat nay nhung cong o mat kia (ho)");
              }
            }
          }
          pos += n;
        }
      }

      if(p.expectPn()) {
        if(p.direct()[0] >= 0 && (p.direct()[0] != agg[0] || p.direct()[1] != agg[1] || p.direct()[2] != agg[2])) {
          errors.add(where + ": tong doc lai " + java.util.Arrays.toString(agg) + " khac PnEdgeFlags.compute " + java.util.Arrays.toString(p.direct()));
        }
        final int[] t = totals.computeIfAbsent(p.label(), k -> new int[5]);
        t[0] += agg[0];
        t[1] += agg[1];
        t[2] += agg[2];
        t[3] += sharedEdges;
        t[4]++;
      }
    }

    final int[] dart = totals.get("dart_combat");
    if(dart != null && (dart[0] != REF_DART_CORNERS || dart[1] != REF_DART_PN || dart[2] != REF_DART_LINEAR)) {
      errors.add("dart_combat: " + dart[0] + " goc / " + dart[1] + " goc PN / " + dart[2] + " bit canh thang, tham chieu "
        + REF_DART_CORNERS + " / " + REF_DART_PN + " / " + REF_DART_LINEAR);
    }

    lastErrors = errors;
    if(quiet) {
      return errors.isEmpty() ? 0 : 1;
    }

    for(final Map.Entry<String, int[]> t : totals.entrySet()) {
      final int[] v = t.getValue();
      System.out.printf("  %-14s %3d phan: %5d goc, %5d goc PN, %5d bit canh thang, %5d lan gap canh chung%n", t.getKey(), v[4], v[0], v[1], v[2], v[3]);
    }

    for(int i = 0; i < Math.min(errors.size(), 40); i++) {
      System.out.println("LOI: " + errors.get(i));
    }
    if(errors.size() > 40) {
      System.out.println("... them " + (errors.size() - 40) + " loi");
    }
    System.out.println(errors.isEmpty() ? "DAT: PN muc " + level + " do manh " + strength8 + "/8" : "KHONG DAT: " + errors.size() + " loi");
    return errors.isEmpty() ? 0 : 1;
  }

  static boolean linear(final int flags, final int corner) {
    return (flags >> 7 + corner & 1) != 0;
  }

  // ---------- tự kiểm bộ kiểm ----------

  static boolean quiet;
  static List<String> lastErrors = List.of();

  /**
   * Bộ kiểm "pn" phải BẮT được lỗi: sửa từng chỗ một trong bản PN mức 4 (đọc lại tệp mỗi lần) và mong đúng loại lỗi
   * (chuỗi con trong thông báo), không chỉ "có lỗi".
   */
  static int selftest(final Path origPath, final Path pnPath) throws IOException {
    final List<Entry> orig = read(origPath);
    quiet = true;
    int bad = 0;

    if(pn(orig, read(pnPath), 4, 8) != 0) {
      System.out.println("LOI: ban PN muc 4 khong dat ngay tu dau");
      return 1;
    }

    final String[] names = {
      "lat 1 bit canh thang (goc 0 -> 1)", "doi chi so goc cuc bo", "doi toa do x", "them bit vao mo hinh khong phai nhan vat",
      "sai muc", "sai do manh", "canh chung khong thong nhat giua hai mat", "bo bit PN o mot goc", "bit PN tren mat trong suot",
    };
    final String[] expect = {
      "khong doi xung", "sai chi so goc", "thanh phan 0 bi doi", "ten khong phai nhan vat", "co sai", "co sai", "thang o mat nay", "sai chi so goc/QUAD/PN",
      "tren mat trong suot",
    };

    for(int t = 0; t < names.length; t++) {
      final List<Entry> pn = read(pnPath);
      final Entry e = pn.stream().filter(x -> x.expectPn() && x.label().equals("dart_combat")).findFirst().orElseThrow();
      final int[] v = e.meshes().get(0).vertexBits();
      int level = 4;
      int strength = 8;

      switch(t) {
        case 0 -> v[FLAGS] = Float.floatToRawIntBits((int)Float.intBitsToFloat(v[FLAGS]) ^ 1 << 8);
        case 1 -> v[STRIDE + FLAGS] = Float.floatToRawIntBits((int)Float.intBitsToFloat(v[STRIDE + FLAGS]) ^ 3 << 5);
        case 2 -> v[0] = Float.floatToRawIntBits(Float.intBitsToFloat(v[0]) + 1.0f);
        case 3 -> {
          final Entry plain = pn.stream().filter(x -> !x.expectPn()).findFirst().orElseThrow();
          final int[] w = plain.meshes().get(0).vertexBits();
          w[FLAGS] = Float.floatToRawIntBits((int)Float.intBitsToFloat(w[FLAGS]) | 0x800);
        }
        case 4 -> level = 3;
        case 5 -> strength = 7;
        // lật bit một cạnh có mặt kề ở CẢ hai góc của một mặt (giữ đối xứng trong mặt) -> phải ra lỗi "không thống nhất"
        case 6 -> flipSharedEdge(e);
        case 7 -> {
          final int f = (int)Float.intBitsToFloat(v[FLAGS]);
          v[FLAGS] = Float.floatToRawIntBits(f & ~0x800);
        }
        default -> setPnOnTranslucent(pn);
      }

      final boolean failed = pn(orig, pn, level, strength) != 0;
      final int kind = t;
      final boolean caught = failed && lastErrors.stream().anyMatch(s -> s.contains(expect[kind]));
      System.out.printf("  tu kiem: %-45s -> %s%n", names[t], caught ? "bat duoc" : "KHONG bat duoc " + lastErrors.subList(0, Math.min(3, lastErrors.size())));
      if(!caught) {
        bad++;
      }
    }

    quiet = false;
    System.out.println(bad == 0 ? "DAT: bo kiem pn bat duoc ca " + names.length + " loi gia" : "LOI: bo kiem bo sot " + bad + " loi gia");
    return bad == 0 ? 0 : 1;
  }

  /** Bật bit PN ở mọi góc của mặt TRANSLUCENT đầu tiên trong một mô hình nhân vật (giữ thống nhất trong mặt). */
  private static void setPnOnTranslucent(final List<Entry> entries) {
    for(final Entry e : entries) {
      if(!e.expectPn()) {
        continue;
      }
      for(final MeshData m : e.meshes()) {
        final int[] v = m.vertexBits();
        final int count = v.length / STRIDE;
        int pos = 0;
        while(pos < count) {
          final int f0 = (int)Float.intBitsToFloat(v[pos * STRIDE + FLAGS]);
          final int n = (f0 & 0x10) != 0 ? 4 : 3;
          if((f0 & 0x9) == 0x9) { // LIT + TRANSLUCENT
            for(int k = 0; k < n; k++) {
              final int i = (pos + k) * STRIDE + FLAGS;
              v[i] = Float.floatToRawIntBits((int)Float.intBitsToFloat(v[i]) | 0x800);
            }
            return;
          }
          pos += n;
        }
      }
    }
    throw new IllegalStateException("khong co mat LIT + TRANSLUCENT trong mo hinh nhan vat nao");
  }

  /** Tìm một cạnh vòng có mặt kề (hai mặt cùng phần) và lật bit cạnh đó ở cả hai góc của MỘT mặt. */
  private static void flipSharedEdge(final Entry target) {
    final Map<Long, Integer> seen = new HashMap<>();
    for(final MeshData m : target.meshes()) {
      final int[] v = m.vertexBits();
      final int count = v.length / STRIDE;
      int pos = 0;
      while(pos < count) {
        final int f0 = (int)Float.intBitsToFloat(v[pos * STRIDE + FLAGS]);
        final boolean quad = (f0 & 0x10) != 0;
        final int n = quad ? 4 : 3;
        final int[][] ring = quad ? new int[][] {{0, 1}, {1, 3}, {3, 2}, {2, 0}} : new int[][] {{0, 1}, {1, 2}, {2, 0}};
        for(final int[] edge : ring) {
          final int a = (int)Float.intBitsToFloat(v[(pos + edge[0]) * STRIDE + 3]);
          final int b = (int)Float.intBitsToFloat(v[(pos + edge[1]) * STRIDE + 3]);
          final long key = (long)Math.min(a, b) << 32 | Math.max(a, b);
          if(seen.containsKey(key)) {
            final int i0 = (pos + edge[0]) * STRIDE + FLAGS;
            final int i1 = (pos + edge[1]) * STRIDE + FLAGS;
            v[i0] = Float.floatToRawIntBits((int)Float.intBitsToFloat(v[i0]) ^ 1 << 7 + edge[1]);
            v[i1] = Float.floatToRawIntBits((int)Float.intBitsToFloat(v[i1]) ^ 1 << 7 + edge[0]);
            return;
          }
          seen.put(key, pos);
        }
        pos += n;
      }
    }
    throw new IllegalStateException("khong tim thay canh chung");
  }

  // ---------- định dạng tệp ----------

  static void write(final Path out, final List<Entry> entries) throws IOException {
    Files.createDirectories(out.toAbsolutePath().getParent());
    try(DataOutputStream s = new DataOutputStream(new BufferedOutputStream(Files.newOutputStream(out)))) {
      s.writeInt(MAGIC);
      s.writeInt(entries.size());
      for(final Entry e : entries) {
        s.writeUTF(e.label());
        s.writeUTF(e.name());
        s.writeBoolean(e.expectPn());
        s.writeBoolean(e.backface());
        for(final int d : e.direct()) {
          s.writeInt(d);
        }
        s.writeInt(e.meshes().size());
        for(final MeshData m : e.meshes()) {
          s.writeUTF(m.name());
          s.writeUTF(m.order());
          s.writeBoolean(m.textured());
          s.writeBoolean(m.translucent());
          s.writeUTF(m.translucency());
          s.writeInt(m.vertexBits().length);
          for(final int v : m.vertexBits()) {
            s.writeInt(v);
          }
          s.writeInt(m.indices().length);
          for(final int i : m.indices()) {
            s.writeInt(i);
          }
        }
      }
    }
  }

  static List<Entry> read(final Path in) throws IOException {
    try(DataInputStream s = new DataInputStream(new BufferedInputStream(Files.newInputStream(in)))) {
      if(s.readInt() != MAGIC) {
        throw new IOException(in + ": khong phai tep PnCheck");
      }
      final int count = s.readInt();
      final List<Entry> entries = new ArrayList<>(count);
      for(int e = 0; e < count; e++) {
        final String label = s.readUTF();
        final String name = s.readUTF();
        final boolean expectPn = s.readBoolean();
        final boolean backface = s.readBoolean();
        final int[] direct = {s.readInt(), s.readInt(), s.readInt()};
        final int meshCount = s.readInt();
        final List<MeshData> meshes = new ArrayList<>(meshCount);
        for(int m = 0; m < meshCount; m++) {
          final String meshName = s.readUTF();
          final String order = s.readUTF();
          final boolean textured = s.readBoolean();
          final boolean translucent = s.readBoolean();
          final String translucency = s.readUTF();
          final int[] bits = new int[s.readInt()];
          for(int i = 0; i < bits.length; i++) {
            bits[i] = s.readInt();
          }
          final int[] indices = new int[s.readInt()];
          for(int i = 0; i < indices.length; i++) {
            indices[i] = s.readInt();
          }
          meshes.add(new MeshData(meshName, order, textured, translucent, translucency, bits, indices));
        }
        entries.add(new Entry(label, name, expectPn, backface, direct, meshes));
      }
      return entries;
    }
  }
}
