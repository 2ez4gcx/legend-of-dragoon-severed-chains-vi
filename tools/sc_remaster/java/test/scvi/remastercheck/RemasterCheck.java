package scvi.remastercheck;

import legend.core.GameEngine;
import legend.core.gpu.Rect4i;
import legend.core.gte.ModelPart10;
import legend.core.renderer.MeshObj;
import legend.core.renderer.Obj;
import legend.core.renderer.Texture;
import legend.core.renderer.Translucency;
import legend.game.tmd.TmdObjLoader;
import legend.game.tmd.TmdObjTable1c;
import legend.game.types.ClutAnimations;
import legend.game.types.Model124;
import org.joml.Vector3f;

import javax.annotation.Nullable;
import java.io.BufferedWriter;
import java.io.IOException;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.SplittableRandom;
import java.util.TreeMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.ZipFile;

/**
 * RemasterCheck — bộ kiểm độc lập cho runtime "Mô hình HD" (gói R1: TmdObjLoader ghi đè + legend.scvi.remaster trong
 * out/sc-vi.jar), viết từ tools/sc_remaster/SPEC.md (LRM spec 1), coi R1 là hộp đen: chỉ gọi TmdObjLoader.fromModel của jar,
 * đặt -Dscvi.remaster / remaster.properties / remaster/ trong thư mục làm việc tạm, rồi đọc lưới qua CaptureApi.
 *
 * Gọi từ tools/sc_remaster/java/build.ps1 -Check (phần (a) javap nằm trong build.ps1):
 *   RemasterCheck all --game G --work W --spec S --synth Y --test T --cp "jar game;libs\*" --java java.exe
 *                     [--jar out/sc-vi.jar] [--mock] [--full] [--nogl] [--jobs N] [--fuzz N]
 *   RemasterCheck child <việc> ...     (JVM con do 'all' sinh ra, mỗi JVM một thư mục làm việc = một điều kiện)
 *
 * Các mục kiểm (exit 0 = mọi mục đạt):
 *   ref  tham chiếu của chính bộ kiểm khớp WP0: RefKey / RefFaceHash / RefLrm / RefBuild so với spec/vectors.json và
 *        spec/sample_cube.{json,lrm}; số khoá trên mọi file trường (6722 file -> 551 khoá, 19 khoá trận, 0 trùng).
 *   (b) same: mọi mô hình sobj trường (obj*33 thật trong DRGN21-24; liên kết mrg trỏ về file thật nên đã gồm), 19 trận,
 *        11 story, 3 ô quái; UvAdjust ô 0 / PNG / NONE (+ tên WmapEntityModel, tên bị loại BattleModel/Savepoint/Shadow);
 *        lưới của sc-vi khi: không có remaster.properties, enabled=false, index rỗng, index trượt khoá, index sai định dạng
 *        (dòng lạ / CRLF / BOM / khoá chữ hoa, §3.7), -Dscvi.remaster=off, log bật + trượt — phải TRÙNG TỪNG BYTE lưới của jar game
 *        (tên, số lưới, thứ tự, cờ, backface).
 *   (c) identity: RefLrm ghi bản L0 identity cho mọi khoá; ở GEOMETRY (properties textures=retail, hoặc -Dscvi.remaster=full
 *        khi không có biến thể) lưới = lưới gốc từng tam giác, chỉ khác QUAD_FLAG bị xoá và ô kề = [a, a, b, a, c, a] (§4.3);
 *        tên bị loại vẫn ra lưới gốc y hệt. Kèm: không đổi TmdObjTable1c, không tạo lưới/texture thừa, xoá hết khi xoá Obj.
 *   (d) khoá: RefKey == khoá runtime (dòng log 'scvi-remaster: <tên> key=<k>' với -Dscvi.remasterLog=true) == vectors.json.
 *   (e) fuzz: --fuzz đột biến (mặc định 2000) của file identity thật và sample_cube.lrm, mỗi đột biến một khoá riêng (không
 *        dính cache SoftReference / log một lần mỗi khoá); fromModel không ném lỗi; file sai -> lưới gốc y hệt; file vẫn hợp lệ
 *        -> đúng lưới dựng từ file mới; pngSha1 sai / PNG sai kích thước -> chỉ bộ VRAM. atlas4th (NaN ở góc thứ 4 của mặt tam
 *        giác) là file HỢP LỆ (§3.5.4 "không kiểm"): runtime từ chối = lỗi. --fuzz < 2000 -> (e) NOT RUN (exit 1).
 *   (f) FaceHash: sample_cube ở FULL với ngữ cảnh GL ẩn: TIM A -> ATLAS(0), B -> 1, C (CLUT khác) / D (lệch uv) -> VRAM,
 *        E (texel trong rect hoạt cảnh đổi, mặt đó LIVE) -> 0; float bộ VRAM / ATLAS = sample_cube.json; mip atlas (§3.6) đọc
 *        lại bằng glGetTexImage = runtimeMips; geometry / textures=retail / tw,th != 0 / clutAnimations / tên bị loại không
 *        dựng ATLAS; đổi VRAM giữa chừng -> về VRAM; ô VRAM khác (WmapEntityModel, combatant ô 5) vẫn khớp; véc-tơ face-hash
 *        runtime trong log = Python (kể cả ghi đè PNG: mặt bpp 3 ghi 0); 3 lần ATLAS -> PENDING -> khoá VRAM (khuyến nghị, ghi
 *        nhận); file hỏng nạp nhiều lần -> log fallback đúng một lần. RENDERER.api() là lớp con GlApi thật khi có ngữ cảnh GL.
 *        Vòng đời 'share': hai mô hình cùng atlas, xoá một -> atlas còn, mô hình kia vẫn ATLAS(0); nạp lại tại chỗ không tạo
 *        texture; xoá hết -> sạch; log JVM con không có 'used after being deleted'.
 *        Thêm 43 mẫu vectors.json (identity + 1 biến thể giả, atlasUv khác nhau từng góc): bộ ATLAS(0) vẽ ra trùng từng float
 *        RefBuild (LIVE b / d giữ uv VRAM) và véc-tơ log = vectors.
 *   (g) tự kiểm: MockRuntime gieo 1 float sai / bỏ 1 tam giác / đảo chiều / sai lớp lưới -> (c) phải bắt đúng loại; bộ kiểm
 *        file lỏng (bỏ luật role) -> fuzz phải bắt; so sánh digest / JSON bắt lỗi gieo; RefLrm phân loại đúng lỗi gieo;
 *        MockRuntime bỏ LIVE / mip không làm tròn / véc-tơ log ghi 1 cho mặt bpp 3 -> (f) phải bắt; cấp phát theo số đếm trong
 *        file trước khi kiểm cắt cụt -> JVM fuzz (-XX:+ExitOnOutOfMemoryError) phải thoát rc=3; xoá atlas dùng chung sớm
 *        (eagerfree) -> 'share' phải bắt; đảo góc atlasUv (atlascorner) -> so float ATLAS của mẫu vectors phải bắt.
 *   (e) còn có đột biến partsRekey (file tự nhất quán nhưng số phần != runtime) và mọi JVM fuzz chạy -XX:+ExitOnOutOfMemoryError.
 * --mock: thay runtime sc-vi bằng MockRuntime (kiểm chính đường ống khi chưa có R1); mục cần ATLAS ghi NOT RUN.
 * Dữ liệu suy ra từ đĩa (file identity, dump, log) chỉ ghi vào --work (work/upscale/sc_remaster_check, git bỏ qua).
 */
public final class RemasterCheck {
  private RemasterCheck() { }

  // =====================================================================================================================
  // tuỳ chọn
  // =====================================================================================================================

  static final class Opt {
    Path game;
    Path files;
    Path work;
    Path spec;
    Path synth;
    Path test;
    String cp;
    String java;
    @Nullable Path jar;
    boolean mock;
    boolean full;
    boolean nogl;
    int jobs = Math.max(1, Math.min(4, Runtime.getRuntime().availableProcessors() / 2));
    int fuzz = 2000;
    /** --only b,c,...: chỉ chạy các mục này (để phát triển; mục khác NOT RUN). */
    @Nullable Set<String> only;

    boolean on(final String check) {
      return this.only == null || this.only.contains(check);
    }
  }

  static Opt parse(final String[] a) {
    final Opt o = new Opt();
    for(int i = 1; i < a.length; i++) {
      switch(a[i]) {
        case "--game" -> o.game = Path.of(a[++i]).toAbsolutePath().normalize();
        case "--work" -> o.work = Path.of(a[++i]).toAbsolutePath().normalize();
        case "--spec" -> o.spec = Path.of(a[++i]).toAbsolutePath().normalize();
        case "--synth" -> o.synth = Path.of(a[++i]).toAbsolutePath().normalize();
        case "--test" -> o.test = Path.of(a[++i]).toAbsolutePath().normalize();
        case "--cp" -> o.cp = a[++i];
        case "--java" -> o.java = a[++i];
        case "--jar" -> {
          final String j = a[++i];
          o.jar = j.isEmpty() || "-".equals(j) ? null : Path.of(j).toAbsolutePath().normalize();
        }
        case "--mock" -> o.mock = true;
        case "--full" -> o.full = true;
        case "--nogl" -> o.nogl = true;
        case "--jobs" -> o.jobs = Integer.parseInt(a[++i]);
        case "--fuzz" -> o.fuzz = Integer.parseInt(a[++i]);
        case "--only" -> o.only = new HashSet<>(Arrays.asList(a[++i].split(",")));
        default -> throw new IllegalArgumentException("tuy chon la: " + a[i]);
      }
    }
    o.files = o.game.resolve("files");
    return o;
  }

  public static void main(final String[] args) throws Exception {
    final int rc;
    if(args.length > 0 && "all".equals(args[0])) {
      rc = all(parse(args));
    } else if(args.length > 1 && "child".equals(args[0])) {
      rc = child(Arrays.copyOfRange(args, 1, args.length));
    } else {
      System.out.println("RemasterCheck all --game G --work W --spec S --synth Y --test T --cp CP --java J [--jar J] [--mock] [--full] [--nogl] [--jobs N] [--fuzz N]");
      rc = 1;
    }
    System.out.flush();
    System.exit(rc);
  }

  // =====================================================================================================================
  // báo cáo
  // =====================================================================================================================

  static final class Report {
    final Map<String, List<String>> fails = new LinkedHashMap<>();
    final Map<String, List<String>> infos = new LinkedHashMap<>();
    final Map<String, String> notRun = new LinkedHashMap<>();
    final Set<String> ran = new LinkedHashSet<>();

    void ran(final String check) {
      this.ran.add(check);
      this.fails.computeIfAbsent(check, k -> new ArrayList<>());
    }

    void fail(final String check, final String msg) {
      this.ran(check);
      this.fails.get(check).add(msg);
    }

    boolean quiet;

    void info(final String check, final String msg) {
      this.infos.computeIfAbsent(check, k -> new ArrayList<>()).add(msg);
      if(!this.quiet) {
        System.out.println("  [" + check + "] " + msg);
      }
    }

    void notRun(final String check, final String why) {
      this.notRun.put(check, why);
    }

    int print() {
      System.out.println();
      System.out.println("================ KET QUA ================");
      int bad = 0;
      for(final String c : List.of("ref", "b", "c", "d", "e", "f", "g")) {
        final List<String> f = this.fails.get(c);
        if(this.notRun.containsKey(c) && (f == null || f.isEmpty())) {
          System.out.println(c + ": NOT RUN (" + this.notRun.get(c) + ')');
          if(!this.notRunOk.contains(c)) {
            bad++;
          }
          continue;
        }
        if(f == null) {
          System.out.println(c + ": NOT RUN");
          bad++;
          continue;
        }
        System.out.println(c + ": " + (f.isEmpty() ? "PASS" : "FAIL (" + f.size() + " loi)"));
        for(int i = 0; i < Math.min(12, f.size()); i++) {
          System.out.println("    - " + f.get(i));
        }
        if(f.size() > 12) {
          System.out.println("    ... (" + (f.size() - 12) + " loi nua)");
        }
        if(this.notRun.containsKey(c)) {
          System.out.println("    (mot phan NOT RUN: " + this.notRun.get(c) + ')');
        }
        if(!f.isEmpty()) {
          bad++;
        }
      }
      return bad;
    }

    final Set<String> notRunOk = new HashSet<>();
  }

  // =====================================================================================================================
  // ca thử (case)
  // =====================================================================================================================

  /** Một lần gọi fromModel: mô hình (file), tên, chế độ UvAdjust, tw/th, clutAnim; allowed = tên có tiền tố được phép. */
  record Case(int id, String group, String label, Path file, @Nullable Path tim, String name, String uv, int tw, int th, boolean clutAnim,
              boolean allowed, String key) {
    String tsv() {
      return this.id + "\t" + this.group + '\t' + this.label + '\t' + this.file + '\t' + (this.tim == null ? "-" : this.tim.toString()) + '\t' + this.name
        + '\t' + this.uv + '\t' + this.tw + '\t' + this.th + '\t' + (this.clutAnim ? 1 : 0) + '\t' + (this.allowed ? 1 : 0) + '\t' + this.key;
    }

    static Case of(final String line) {
      final String[] c = line.split("\t", -1);
      return new Case(Integer.parseInt(c[0]), c[1], c[2], Path.of(c[3]), "-".equals(c[4]) ? null : Path.of(c[4]), c[5], c[6],
        Integer.parseInt(c[7]), Integer.parseInt(c[8]), "1".equals(c[9]), "1".equals(c[10]), c[11]);
    }
  }

  static List<Case> readCases(final Path p) throws IOException {
    final List<Case> out = new ArrayList<>();
    for(final String l : Files.readAllLines(p, StandardCharsets.UTF_8)) {
      if(!l.isBlank()) {
        out.add(Case.of(l));
      }
    }
    return out;
  }

  static void writeCases(final Path p, final List<Case> cases) throws IOException {
    try(final BufferedWriter w = Files.newBufferedWriter(p, StandardCharsets.UTF_8)) {
      for(final Case c : cases) {
        w.write(c.tsv());
        w.write('\n');
      }
    }
  }

  /** Lớp phủ sc-vi (Loader.java): game/vi/files/<rel> thắng game/files/<rel>. */
  static Path resolve(final Opt o, final String rel) {
    final Path over = o.game.resolve("vi").resolve("files").resolve(rel);
    return Files.isRegularFile(over) ? over : o.files.resolve(rel);
  }

  static final String[] EXCLUDED = {"BattleModel c%d", "Savepoint", "Shadow"};

  /** Thông tin quét: khoá theo nhóm, số liên kết mrg. */
  static final class Scan {
    final List<Case> cases = new ArrayList<>();
    final Set<String> fieldKeys = new HashSet<>();
    final Set<String> battleKeys = new HashSet<>();
    int fieldFiles;
    int fieldRejected;
    int mrgLinks;
    int mrgLinkMismatch;
  }

  static Scan scan(final Opt o, final Report rep) throws IOException {
    final Scan s = new Scan();
    int id = 0;
    final Path sect = o.files.resolve("SECT");
    int fieldIndex = 0;
    for(final String drgn : List.of("DRGN21.BIN", "DRGN22.BIN", "DRGN23.BIN", "DRGN24.BIN")) {
      final Path root = sect.resolve(drgn);
      final List<Path> dirs = new ArrayList<>();
      try(final var ds = Files.newDirectoryStream(root)) {
        for(final Path d : ds) {
          if(Files.isDirectory(d) && d.getFileName().toString().matches("\\d+")) {
            dirs.add(d);
          }
        }
      }
      dirs.sort((a, b) -> Integer.compare(Integer.parseInt(a.getFileName().toString()), Integer.parseInt(b.getFileName().toString())));
      for(final Path d : dirs) {
        final List<Path> fs = new ArrayList<>();
        try(final var ds = Files.newDirectoryStream(d)) {
          for(final Path f : ds) {
            final String n = f.getFileName().toString();
            if(n.matches("\\d+") && Integer.parseInt(n) % 33 == 0 && Files.isRegularFile(f) && Files.size(f) >= 16) {
              fs.add(f);
            }
          }
        }
        fs.sort((a, b) -> Integer.compare(Integer.parseInt(a.getFileName().toString()), Integer.parseInt(b.getFileName().toString())));
        countMrg(d, s);
        for(final Path f : fs) {
          final byte[] b = Files.readAllBytes(f);
          if(!SynthModels.looksLikeModel(b)) {
            continue;
          }
          final String rel = drgn + '/' + d.getFileName() + '/' + f.getFileName();
          final Model124 m;
          try {
            m = SynthModels.model(rel, b, SynthModels.uv("none"), true);
            RefLrm.Runtime.of(SynthModels.tables(m));
          } catch(final Throwable t) {
            s.fieldRejected++;
            continue;
          }
          s.fieldFiles++;
          final String key = RefKey.modelKeyHex(SynthModels.tables(m));
          s.fieldKeys.add(key);
          final int obj = Integer.parseInt(f.getFileName().toString()) / 33;
          final Path tim = d.resolve("textures").resolve(String.valueOf(obj));
          final Path timP = Files.isRegularFile(tim) ? tim : null;
          final boolean clut = m.clutAnimations_a4 != null;
          s.cases.add(new Case(id, "field", rel, f, timP, "SobjModel (index " + id + ')', "slot0", 0, 0, clut, true, key));
          id++;
          final boolean extra = o.full || fieldIndex % 4 == 0;
          if(extra) {
            s.cases.add(new Case(id, "field", rel, f, timP, "SobjModel (index " + id + ')', "none", 0, 0, clut, true, key));
            id++;
            RefFaceHash.Tim t = null;
            try {
              t = timP == null ? null : RefFaceHash.parseTim(Files.readAllBytes(timP));
            } catch(final RuntimeException e) {
              t = null;
            }
            if(t != null && t.iw() > 0 && t.ih() > 0) {
              // nhánh ghi đè PNG của RetailSubmap.prepareSobjModel: tw = rect.w * widthDivisor, th = rect.h
              s.cases.add(new Case(id, "field", rel, f, timP, "SobjModel (index " + id + ')', "png", t.texelWidth(), t.ih(), clut, true, key));
              id++;
            }
          }
          if(o.full || fieldIndex % 10 == 3) {
            s.cases.add(new Case(id, "field", rel, f, timP, "WmapEntityModel (index " + id + ')', "wmap", 0, 0, false, true, key));
            id++;
          }
          if(o.full || fieldIndex % 25 == 7) {
            s.cases.add(new Case(id, "field", rel, f, timP, EXCLUDED[fieldIndex % 3].formatted(id), "slot0", 0, 0, clut, false, key));
            id++;
          }
          fieldIndex++;
        }
      }
    }
    // trận: characters/<c>/models/{combat,dragoon}/32
    final Path chars = o.files.resolve("characters");
    final List<String> cs = new ArrayList<>();
    try(final var ds = Files.newDirectoryStream(chars)) {
      for(final Path c : ds) {
        cs.add(c.getFileName().toString());
      }
    }
    Collections.sort(cs);
    for(final String c : cs) {
      for(final String form : List.of("combat", "dragoon")) {
        final String rel = "characters/" + c + "/models/" + form + "/32";
        final Path f = resolve(o, rel);
        if(!Files.isRegularFile(f)) {
          continue;
        }
        final Path tim = resolve(o, "characters/" + c + "/textures/" + form);
        final String key = RefKey.modelKeyHex(SynthModels.tables(SynthModels.model(rel, Files.readAllBytes(f), SynthModels.uv("none"), false)));
        s.battleKeys.add(key);
        final String label = "battle/" + c + '/' + form;
        s.cases.add(new Case(id, "battle", label, f, Files.isRegularFile(tim) ? tim : null, "CombatantModel (c" + id + ' ' + label + ')', "slot1", 0, 0, false, true, key));
        id++;
        s.cases.add(new Case(id, "battle", label, f, Files.isRegularFile(tim) ? tim : null, "CombatantModel (c" + id + ' ' + label + ')', "none", 0, 0, false, true, key));
        id++;
        s.cases.add(new Case(id, "battle", label, f, Files.isRegularFile(tim) ? tim : null, "BattleModel c" + id, "slot1", 0, 0, false, false, key));
        id++;
      }
    }
    // story + ô quái: theo vectors.json
    for(final Vec v : vectors(o)) {
      if(!"story".equals(v.kind) && !"monster".equals(v.kind)) {
        continue;
      }
      final Path f = resolve(o, v.model);
      final String key = RefKey.modelKeyHex(SynthModels.tables(SynthModels.model(v.model, Files.readAllBytes(f), SynthModels.uv("none"), false)));
      s.cases.add(new Case(id, v.kind, v.id, f, resolve(o, v.tim), "CombatantModel (c" + id + ' ' + v.id + ')', "slot1", 0, 0, false, true, key));
      id++;
    }
    return s;
  }

  static void countMrg(final Path dir, final Scan s) throws IOException {
    final Path mrg = dir.resolve("mrg");
    if(!Files.isRegularFile(mrg)) {
      return;
    }
    final Map<Integer, int[]> map = new HashMap<>();
    for(final String line : Files.readAllLines(mrg)) {
      final String[] p = line.split("[=;]", -1);
      if(p.length != 3 || p[1].isBlank()) {
        continue;
      }
      map.put(Integer.parseInt(p[0].trim()), new int[] {Integer.parseInt(p[1].trim()), Integer.parseInt(p[2].trim())});
    }
    for(final var e : map.entrySet()) {
      final int v = e.getKey();
      int r = e.getValue()[0];
      if(v % 33 != 0 || r == v || e.getValue()[1] < 16) {
        continue;
      }
      while(map.containsKey(r) && map.get(r)[0] != r) {
        r = map.get(r)[0];
      }
      s.mrgLinks++;
      final Path real = dir.resolve(String.valueOf(r));
      if(!Files.isRegularFile(real) || r % 33 != 0 || Files.size(real) != e.getValue()[1]) {
        s.mrgLinkMismatch++;
      }
    }
  }

  // =====================================================================================================================
  // vectors.json
  // =====================================================================================================================

  record Vec(String id, String kind, String model, String tim, String placement, String modelKey, List<String> partKeys, int[] srcFaceCount,
             int texturedFaceCount, String vectorSha1, int liveFaceCount, int facesOutsideTim, List<String> aliases) { }

  static List<Vec> vectorsCache;

  static List<Vec> vectors(final Opt o) throws IOException {
    if(vectorsCache != null) {
      return vectorsCache;
    }
    final var j = com.google.gson.JsonParser.parseString(Files.readString(o.spec.resolve("vectors.json"), StandardCharsets.UTF_8)).getAsJsonObject();
    final List<Vec> out = new ArrayList<>();
    for(final var e : j.getAsJsonArray("models")) {
      final var m = e.getAsJsonObject();
      final List<String> pks = new ArrayList<>();
      m.getAsJsonArray("partKeys").forEach(x -> pks.add(x.getAsString()));
      final List<String> aliases = new ArrayList<>();
      if(m.has("aliases")) {
        m.getAsJsonArray("aliases").forEach(x -> aliases.add(x.getAsString()));
      }
      out.add(new Vec(m.get("id").getAsString(), m.get("kind").getAsString(), m.get("model").getAsString(), m.get("tim").getAsString(),
        m.get("placement").getAsString(), m.get("modelKey").getAsString(), pks, SynthModels.ints(m.getAsJsonArray("srcFaceCount")),
        m.get("texturedFaceCount").getAsInt(), m.get("faceHashVectorSha1").getAsString(), m.get("liveFaceCount").getAsInt(),
        m.get("facesOutsideTim").getAsInt(), aliases));
    }
    vectorsCache = out;
    return out;
  }

  /** Mô hình + VRAM ảo của một mẫu vectors.json đặt như bộ sinh. placed = rect đã đặt. */
  record VecModel(Model124 model, RefFaceHash.IntVram vram, int[] placed, RefFaceHash.Tim tim, String uv) { }

  static VecModel vecModel(final Opt o, final Vec v) throws IOException {
    final byte[] mb = Files.readAllBytes(resolve(o, v.model));
    final RefFaceHash.Tim tim = RefFaceHash.parseTim(Files.readAllBytes(resolve(o, v.tim)));
    final RefFaceHash.IntVram vram = new RefFaceHash.IntVram();
    final boolean field = "field_slot0".equals(v.placement);
    final String uv = field ? "slot0" : "none";
    final Model124 m = SynthModels.model(v.id, mb, SynthModels.uv(uv), field);
    final int[] placed = field ? RefFaceHash.placeAt(vram, tim, 576, 256, 576, 368) : RefFaceHash.placeNative(vram, tim);
    return new VecModel(m, vram, placed, tim, uv);
  }

  static void checkVectors(final Opt o, final Report rep) throws IOException {
    int ok = 0;
    for(final Vec v : vectors(o)) {
      try {
        final VecModel vm = vecModel(o, v);
        final TmdObjTable1c[] t = SynthModels.tables(vm.model);
        final byte[][] pks = RefKey.partKeys(t);
        final String mk = RefKey.HEX.formatHex(RefKey.modelKey(pks));
        final List<String> errs = new ArrayList<>();
        if(!mk.equals(v.modelKey)) {
          errs.add("modelKey " + mk + " != " + v.modelKey);
        }
        for(int i = 0; i < Math.min(pks.length, v.partKeys.size()); i++) {
          if(!RefKey.HEX.formatHex(pks[i]).equals(v.partKeys.get(i))) {
            errs.add("partKey " + i);
            break;
          }
        }
        if(pks.length != v.partKeys.size()) {
          errs.add("partCount " + pks.length + " != " + v.partKeys.size());
        }
        final List<List<RefBuild.Face>> faces = SynthModels.faces(vm.model);
        final int[] sfc = faces.stream().mapToInt(List::size).toArray();
        if(!Arrays.equals(sfc, v.srcFaceCount)) {
          errs.add("srcFaceCount");
        }
        final int[] raw = RefFaceHash.rawVector(vm.vram, faces);
        if(raw.length != v.texturedFaceCount) {
          errs.add("texturedFaceCount " + raw.length + " != " + v.texturedFaceCount);
        }
        final String vs = RefFaceHash.vectorSha1(raw);
        if(!vs.equals(v.vectorSha1)) {
          errs.add("faceHashVectorSha1 " + vs + " != " + v.vectorSha1);
        }
        final boolean[] live = RefFaceHash.liveModel(vm.model, faces);
        int nl = 0;
        for(final boolean b : live) {
          nl += b ? 1 : 0;
        }
        if(nl != v.liveFaceCount) {
          errs.add("liveFaceCount " + nl + " != " + v.liveFaceCount);
        }
        final int[] gen = RefFaceHash.generatorHashes(vm.vram, faces, vm.placed);
        int outside = 0;
        for(int g = 0; g < gen.length; g++) {
          if(gen[g] == 0 && raw[g] != 0) {
            outside++;
          }
        }
        if(outside != v.facesOutsideTim) {
          errs.add("facesOutsideTim " + outside + " != " + v.facesOutsideTim);
        }
        for(final String a : v.aliases) {
          final String aobj = a.substring(a.lastIndexOf('/') + 1);
          final String adir = a.substring(0, a.lastIndexOf('/'));
          final String atim = adir + "/textures/" + Integer.parseInt(aobj) / 33;
          if(!Arrays.equals(Files.readAllBytes(resolve(o, a)), Files.readAllBytes(resolve(o, v.model)))
            || !Arrays.equals(Files.readAllBytes(resolve(o, atim)), Files.readAllBytes(resolve(o, v.tim)))) {
            errs.add("alias " + a + " khac");
          }
        }
        if(errs.isEmpty()) {
          ok++;
        } else {
          rep.fail("ref", "vectors.json " + v.id + ": " + String.join("; ", errs));
        }
      } catch(final Throwable t) {
        rep.fail("ref", "vectors.json " + v.id + ": " + t);
      }
    }
    rep.ran("ref");
    rep.info("ref", "vectors.json: " + ok + '/' + vectors(o).size() + " mau khop (RefKey, srcFaceCount, FaceHash tho, LIVE a-c, mat ngoai TIM)");
  }

  // =====================================================================================================================
  // sample_cube (tĩnh: tham chiếu của bộ kiểm == WP0)
  // =====================================================================================================================

  static void checkCubeStatic(final Opt o, final SynthModels.Cube cube, final Report rep) throws Exception {
    final List<String> err = new ArrayList<>(cube.selfCheck());
    final Model124 m = cube.model(cube.ccontainer, "slot0");
    final TmdObjTable1c[] t = SynthModels.tables(m);
    final RefLrm.Runtime rt = RefLrm.Runtime.of(t);
    if(!RefKey.HEX.formatHex(rt.modelKey()).equals(cube.modelKey)) {
      err.add("RefKey sample_cube " + RefKey.HEX.formatHex(rt.modelKey()) + " != " + cube.modelKey);
    }
    for(int i = 0; i < t.length; i++) {
      if(!RefKey.HEX.formatHex(RefKey.partKey(t[i])).equals(cube.partKeys.get(i))) {
        err.add("partKey " + i);
      }
    }
    if(!Arrays.equals(rt.srcFaceCounts(), cube.srcFaceCount) || rt.texturedFaceCount() != cube.texturedFaceCount) {
      err.add("srcFaceCount/texturedFaceCount");
    }
    final RefLrm.Lrm l = RefLrm.read(cube.lrm, rt);
    if(!Arrays.equals(RefLrm.write(l, false), cube.lrm)) {
      err.add("RefLrm: doc + ghi lai sample_cube.lrm khong trung byte");
    }
    final RefLrm.Lrm lz = RefLrm.read(RefLrm.write(l, true), rt);
    if(!Arrays.equals(RefLrm.body(lz), RefLrm.body(l))) {
      err.add("RefLrm: than nen zlib doc lai khac");
    }
    final List<List<RefBuild.Face>> faces = SynthModels.faces(m);
    final boolean[] live = RefFaceHash.liveModel(m, faces);
    final List<Integer> lv = new ArrayList<>();
    for(int g = 0; g < live.length; g++) {
      if(live[g]) {
        lv.add(g);
      }
    }
    if(!lv.equals(cube.liveModel)) {
      err.add("LIVE a-c " + lv + " != " + cube.liveModel);
    }
    for(final String k : List.of("A", "B", "C", "D", "E")) {
      final RefFaceHash.IntVram v = new RefFaceHash.IntVram();
      final int[] placed = RefFaceHash.placeAt(v, RefFaceHash.parseTim(cube.tims.get(k)), 576, 256, 576, 368);
      final int[] raw = RefFaceHash.rawVector(v, faces);
      if(!Arrays.equals(raw, cube.runtimeHashes.get(k))) {
        err.add("FaceHash TIM " + k + " khac sample_cube.json");
      }
      if(!RefFaceHash.vectorSha1(raw).equals(cube.vectorSha1.get(k))) {
        err.add("faceHashVectorSha1 TIM " + k);
      }
      final int ev = RefFaceHash.expectedVariant(raw, cube.storedHashes, live);
      if(ev != cube.expectedVariant.get(k)) {
        err.add("bien the mong doi TIM " + k + ": " + ev + " != " + cube.expectedVariant.get(k));
      }
      if("A".equals(k) || "B".equals(k)) {
        final int[] gen = RefFaceHash.generatorHashes(v, faces, placed);
        if(!Arrays.equals(gen, cube.storedHashes["A".equals(k) ? 0 : 1])) {
          err.add("faceHash luu (quy tac bo sinh) TIM " + k);
        }
      }
    }
    for(int i = 0; i < t.length; i++) {
      final List<String> e1 = RefBuild.compare(cube.retail.get(i), stripNames(RefBuild.retail(cube.name + " part " + i, t[i], 0, 0)), false);
      if(!e1.isEmpty()) {
        err.add("RefBuild.retail phan " + i + ": " + e1.get(0));
      }
      final List<String> e2 = RefBuild.compare(cube.vram.get(i), RefBuild.remaster(t[i], faces.get(i), l.parts[i], 0, 0, null, null, texBase(faces, i)), false);
      if(!e2.isEmpty()) {
        err.add("RefBuild.remaster VRAM phan " + i + ": " + e2.get(0));
      }
      for(int v = 0; v < l.variants.length; v++) {
        final boolean[] lvv = RefFaceHash.liveVariant(live, l.variants[v].faceHash);
        final List<String> e3 = RefBuild.compare(cube.atlas.get(v).get(i),
          RefBuild.remaster(t[i], faces.get(i), l.parts[i], 0, 0, l.variants[v].atlasUv, lvv, texBase(faces, i)), false);
        if(!e3.isEmpty()) {
          err.add("RefBuild.remaster ATLAS(" + v + ") phan " + i + ": " + e3.get(0));
        }
      }
      // phần 0 là L0 identity: bộ VRAM = lưới gốc đã chuẩn hoá (§A)
    }
    final List<String> e4 = RefBuild.compare(RefBuild.normalized(cube.retail.get(0)), cube.vram.get(0), false);
    if(!e4.isEmpty()) {
      err.add("sample_cube phan 0: bo VRAM != luoi goc chuan hoa: " + e4.get(0));
    }
    if(o.synth != null) {
      for(int v = 0; v < cube.pngSha1.length; v++) {
        final byte[] png = cube.pngBytes(o.synth, v);
        if(png == null) {
          err.add("thieu " + o.synth.resolve("synth/atlas_" + v + ".png"));
        } else if(!RefKey.sha1Hex(png).equals(cube.pngSha1[v])) {
          err.add("atlas_" + v + ".png sha1 khac sample_cube.json");
        }
      }
      final Path ccp = o.synth.resolve("synth").resolve("cube.ccontainer");
      if(!Files.isRegularFile(ccp) || !Arrays.equals(Files.readAllBytes(ccp), cube.ccontainer)) {
        err.add("synth/cube.ccontainer khac sample_cube.json");
      }
    }
    for(final String e : err) {
      rep.fail("ref", "sample_cube: " + e);
    }
    rep.ran("ref");
    rep.info("ref", "sample_cube: RefKey/RefLrm/RefFaceHash/RefBuild == sample_cube.{json,lrm}" + (err.isEmpty() ? "" : " (" + err.size() + " loi)"));
  }

  static RefBuild.Part stripNames(final RefBuild.Part p) {
    final List<RefBuild.MeshData> m = new ArrayList<>();
    for(final RefBuild.MeshData x : p.meshes()) {
      m.add(new RefBuild.MeshData(null, x.textured(), x.translucent(), x.translucency(), x.order(), x.overload(), x.attrs(), x.v(), x.idx()));
    }
    return new RefBuild.Part(p.meshObj(), p.backface(), m);
  }

  static int texBase(final List<List<RefBuild.Face>> faces, final int part) {
    int g = 0;
    for(int i = 0; i < part; i++) {
      for(final RefBuild.Face f : faces.get(i)) {
        g += f.textured ? 1 : 0;
      }
    }
    return g;
  }

  // =====================================================================================================================
  // điều kiện (thư mục làm việc của JVM con)
  // =====================================================================================================================

  record Cond(String name, boolean identity, @Nullable String props, String index, List<String> dprops) { }

  static List<Cond> conditions() {
    return List.of(
      new Cond("none", false, null, "identity", List.of()),
      new Cond("disabled", false, "enabled=false\ntextures=hd\n", "identity", List.of()),
      new Cond("empty", false, "enabled=true\n", "empty", List.of()),
      new Cond("miss", false, "enabled=true\ntextures=hd\n", "miss", List.of()),
      new Cond("badindex", false, "enabled=true\ntextures=retail\n", "bad", List.of()),
      // §3.7: dòng 1 đúng 'LRMINDEX<TAB>1', UTF-8 không BOM, LF, khoá 40 hex THƯỜNG, nhãn không chứa CR; sai -> cả chỉ mục tắt
      new Cond("crlfindex", false, "enabled=true\ntextures=retail\n", "crlf", List.of()),
      new Cond("bomindex", false, "enabled=true\ntextures=retail\n", "bom", List.of()),
      new Cond("upperindex", false, "enabled=true\ntextures=retail\n", "upper", List.of()),
      new Cond("offD", false, "enabled=true\ntextures=hd\n", "identity", List.of("-Dscvi.remaster=off")),
      new Cond("logmiss", false, "enabled=true\nlog=true\n", "miss", List.of("-Dscvi.remasterLog=true")),
      new Cond("geometry", true, "enabled=true\ntextures=retail\n", "identity", List.of()),
      new Cond("fullD", true, "enabled=false\n", "identity", List.of("-Dscvi.remaster=full")),
      new Cond("loghit", true, "enabled=true\ntextures=retail\nlog=true\n", "identity", List.of("-Dscvi.remasterLog=true")));
  }

  static void link(final Path from, final Path to) throws IOException {
    Files.createDirectories(to.getParent());
    Files.deleteIfExists(to);
    try {
      Files.createLink(to, from);
    } catch(final IOException | UnsupportedOperationException e) {
      Files.copy(from, to);
    }
  }

  static void deleteTree(final Path p) throws IOException {
    if(!Files.exists(p)) {
      return;
    }
    try(final var s = Files.walk(p)) {
      for(final Path x : s.sorted(Collections.reverseOrder()).toList()) {
        Files.delete(x);
      }
    }
  }

  static String indexText(final Iterable<String> keys, final String label) {
    final StringBuilder sb = new StringBuilder("LRMINDEX\t1\n");
    for(final String k : keys) {
      sb.append(k).append("\tmodels/").append(k).append(".lrm\t").append(label).append('\n');
    }
    return sb.toString();
  }

  static void setupCond(final Path dir, final Cond c, final Map<String, Path> identity, final SynthModels.Cube cube) throws IOException {
    deleteTree(dir);
    Files.createDirectories(dir.resolve("remaster").resolve("models"));
    Files.createDirectories(dir.resolve("remaster").resolve("textures"));
    if(c.props() != null) {
      Files.writeString(dir.resolve("remaster.properties"), c.props(), StandardCharsets.UTF_8);
    }
    final Path idx = dir.resolve("remaster").resolve("index.tsv");
    switch(c.index()) {
      case "identity", "bad", "crlf", "bom", "upper" -> {
        for(final var e : identity.entrySet()) {
          link(e.getValue(), dir.resolve("remaster").resolve("models").resolve(e.getKey() + ".lrm"));
        }
        String text = indexText((Iterable<String>)identity.keySet(), "identity");
        switch(c.index()) {
          case "bad" -> text += "0000000000000000000000000000000000000000\tmodels/khac.lrm\tsai\n";
          case "crlf" -> text = text.replace("\n", "\r\n");   // Notepad: nhãn kết thúc bằng CR, dòng 1 != 'LRMINDEX\t1'
          case "bom" -> text = '﻿' + text;               // UTF-8 có BOM: dòng 1 != 'LRMINDEX\t1'
          case "upper" -> {                                   // khoá chữ HOA (file vẫn tìm thấy trên NTFS không phân biệt hoa thường)
            final String k = identity.keySet().iterator().next().toUpperCase(java.util.Locale.ROOT);
            text += k + "\tmodels/" + k + ".lrm\thoa\n";
          }
          default -> { }
        }
        Files.writeString(idx, text, StandardCharsets.UTF_8);
      }
      case "empty" -> Files.writeString(idx, "LRMINDEX\t1\n", StandardCharsets.UTF_8);
      case "miss" -> {
        Files.write(dir.resolve("remaster").resolve("models").resolve(cube.modelKey + ".lrm"), cube.lrm);
        Files.writeString(idx, indexText((Iterable<String>)List.of(cube.modelKey), "sample_cube"), StandardCharsets.UTF_8);
      }
      default -> throw new IllegalArgumentException(c.index());
    }
  }

  // =====================================================================================================================
  // chạy JVM con
  // =====================================================================================================================

  record Job(String name, Path cwd, String cp, List<String> props, List<String> args, Path log) { }

  static String log4j(final Opt o) throws IOException {
    final Path p = o.work.resolve("log4j2-check.xml");
    Files.writeString(p, """
      <?xml version="1.0" encoding="UTF-8"?>
      <Configuration status="warn">
        <Appenders>
          <Console name="c" target="SYSTEM_OUT"><PatternLayout pattern="LOG %-5level %c{1}: %msg%n%throwable"/></Console>
        </Appenders>
        <Loggers><Root level="info"><AppenderRef ref="c"/></Root></Loggers>
      </Configuration>
      """, StandardCharsets.UTF_8);
    return p.toString();
  }

  static String cpRetail(final Opt o) {
    return o.test + ";" + o.cp;
  }

  static String cpRuntime(final Opt o) {
    return o.mock || o.jar == null ? o.test + ";" + o.cp : o.test + ";" + o.jar + ';' + o.cp;
  }

  static List<String> runtimeProps(final Opt o, final boolean gl) {
    final List<String> p = new ArrayList<>();
    if(o.mock) {
      p.add("-Dremastercheck.mock=true");
    }
    if(gl) {
      p.add("-Dremastercheck.gl=true");
    }
    return p;
  }

  static Map<String, Integer> runJobs(final Opt o, final List<Job> jobs) throws Exception {
    final String l4j = log4j(o);
    final Map<String, Integer> rc = Collections.synchronizedMap(new LinkedHashMap<>());
    final ExecutorService ex = Executors.newFixedThreadPool(o.jobs);
    final List<Future<?>> fs = new ArrayList<>();
    for(final Job j : jobs) {
      fs.add(ex.submit(() -> {
        final List<String> cmd = new ArrayList<>(List.of(o.java, "-Xmx1g", "-Xss4m", "-XX:+UseParallelGC", "-XX:ParallelGCThreads=2", "-XX:CICompilerCount=2",
          "-XX:ErrorFile=" + o.work.resolve("hs_err_%p.log"), "-XX:ReplayDataFile=" + o.work.resolve("replay_%p.log"),
          "--enable-native-access=ALL-UNNAMED", "-Dfile.encoding=UTF-8",
          "-Dstdout.encoding=UTF-8", "-Dlog4j2.configurationFile=" + l4j));
        cmd.addAll(j.props());
        cmd.addAll(List.of("-cp", j.cp(), RemasterCheck.class.getName(), "child"));
        cmd.addAll(j.args());
        final long t0 = System.nanoTime();
        try {
          Files.createDirectories(j.cwd());
          final Process p = new ProcessBuilder(cmd).directory(j.cwd().toFile()).redirectErrorStream(true).redirectOutput(j.log().toFile()).start();
          if(!p.waitFor(20, TimeUnit.MINUTES)) {
            p.destroyForcibly();
            rc.put(j.name(), -2);
          } else {
            rc.put(j.name(), p.exitValue());
          }
        } catch(final Exception e) {
          rc.put(j.name(), -1);
        }
        System.out.printf("  JVM con %-16s rc=%s  %.1f s%n", j.name(), rc.get(j.name()), (System.nanoTime() - t0) / 1e9);
        return null;
      }));
    }
    for(final Future<?> f : fs) {
      f.get();
    }
    ex.shutdown();
    return rc;
  }

  // =====================================================================================================================
  // 'all'
  // =====================================================================================================================

  static int all(final Opt o) throws Exception {
    final long t0 = System.nanoTime();
    final Report rep = new Report();
    Files.createDirectories(o.work);
    final Path out = o.work.resolve("out");
    Files.createDirectories(out);
    System.out.println("RemasterCheck: game=" + o.game + " work=" + o.work + (o.mock ? " (MOCK: MockRuntime thay R1)" : " jar=" + o.jar));

    // R1 có mặt?
    boolean r1 = false;
    if(o.jar != null && Files.isRegularFile(o.jar)) {
      try(final ZipFile z = new ZipFile(o.jar.toFile())) {
        r1 = z.getEntry("legend/game/tmd/TmdObjLoader.class") != null;
      }
    }
    final boolean runtime = o.mock || r1;
    if(!runtime) {
      System.out.println("CANH BAO: " + (o.jar == null ? "khong co sc-vi.jar" : o.jar + " khong co legend/game/tmd/TmdObjLoader.class (chua co R1)")
        + " -> chi kiem (b) va tham chieu; cac muc can runtime remaster: NOT RUN");
    }

    // GL
    boolean gl = false;
    if(!o.nogl) {
      final Map<String, Integer> g = runJobs(o, List.of(new Job("glprobe", o.work.resolve("glprobe"), cpRetail(o), List.of(), List.of("glprobe"), out.resolve("glprobe.log"))));
      gl = g.get("glprobe") == 0;
      System.out.println("  ngu canh OpenGL an: " + (gl ? "co" : "KHONG (xem " + out.resolve("glprobe.log") + ')'));
    }

    // tham chiếu + quét
    final SynthModels.Cube cube = SynthModels.Cube.load(o.spec);
    checkCubeStatic(o, cube, rep);
    checkVectors(o, rep);
    final Scan s = scan(o, rep);
    rep.info("ref", "quet: " + s.fieldFiles + " file mo hinh truong (bo " + s.fieldRejected + "), " + s.mrgLinks + " lien ket mrg obj*33 (sai lech "
      + s.mrgLinkMismatch + "), " + s.cases.size() + " ca thu");
    final Set<String> all = new HashSet<>(s.fieldKeys);
    all.addAll(s.battleKeys);
    final Set<String> both = new HashSet<>(s.fieldKeys);
    both.retainAll(s.battleKeys);
    rep.info("ref", "khoa: " + s.fieldFiles + " file truong -> " + all.size() + " khoa (" + s.fieldKeys.size() + " truong + " + s.battleKeys.size()
      + " tran), khoa tran trong file truong: " + both.size());
    if(s.fieldFiles != 6722 || all.size() != 551 || s.fieldKeys.size() != 532 || s.battleKeys.size() != 19 || !both.isEmpty()) {
      rep.fail("ref", "so khoa khac nguyen mau (6722 / 551 / 532 + 19 / 0)");
    }
    if(s.mrgLinkMismatch != 0) {
      rep.fail("ref", s.mrgLinkMismatch + " lien ket mrg obj*33 khong tro ve file obj*33 that cung kich thuoc (can giai lien ket rieng)");
    }
    final Path casesFile = o.work.resolve("cases.tsv");
    writeCases(casesFile, s.cases);

    // file L0 identity: một file mỗi khoá
    final Path lrmDir = o.work.resolve("lrm");
    deleteTree(lrmDir);
    Files.createDirectories(lrmDir);
    final Map<String, Path> identity = new TreeMap<>();
    for(final Case c : s.cases) {
      if(identity.containsKey(c.key())) {
        continue;
      }
      try {
        final Model124 m = SynthModels.model(c.label(), Files.readAllBytes(c.file()), SynthModels.uv(c.uv()), c.clutAnim());
        final RefLrm.Lrm l = RefLrm.identity(SynthModels.tables(m));
        final byte[] b = RefLrm.write(l, false);
        RefLrm.read(b, RefLrm.Runtime.of(SynthModels.tables(m)));
        final Path p = lrmDir.resolve(c.key() + ".lrm");
        Files.write(p, b);
        identity.put(c.key(), p);
      } catch(final Throwable t) {
        rep.info("c", "khong dung duoc identity cho " + c.label() + ": " + t);
      }
    }
    rep.info("c", identity.size() + " file L0 identity trong " + lrmDir);

    // (b) (c) (d): JVM con
    final Path condRoot = o.work.resolve("cond");
    final List<Job> jobs = new ArrayList<>();
    final boolean bcd = o.on("b") || o.on("c") || o.on("d") || o.on("g");
    if(bcd) jobs.add(new Job("retail", condRoot.resolve("retail"), cpRetail(o), gl ? List.of("-Dremastercheck.gl=true") : List.of(),
      List.of("capture", casesFile.toString(), out.resolve("retail.tsv").toString(), "retail"), out.resolve("retail.log")));
    for(final Cond c : conditions()) {
      if(c.identity() && !runtime || !(o.on("b") || o.on("c") || o.on("d"))) {
        continue;
      }
      setupCond(condRoot.resolve(c.name()), c, identity, cube);
      final List<String> props = new ArrayList<>(runtimeProps(o, gl));
      props.addAll(c.dprops());
      jobs.add(new Job(c.name(), condRoot.resolve(c.name()), o.jar == null && !o.mock ? cpRetail(o) : cpRuntime(o), props,
        List.of("capture", casesFile.toString(), out.resolve(c.name() + ".tsv").toString(), c.identity() ? "identity" : "retail"), out.resolve(c.name() + ".log")));
    }
    final Map<String, Integer> rcs = runJobs(o, jobs);
    final Map<Integer, Res> retail = bcd ? readRes(out.resolve("retail.tsv")) : new HashMap<>();
    if(bcd) {
      checkRetailRun(s.cases, retail, rcs.get("retail"), rep);
    }
    for(final Cond c : conditions()) {
      if(c.identity() && !runtime || !(o.on("b") || o.on("c") || o.on("d"))) {
        continue;
      }
      final Map<Integer, Res> r = readRes(out.resolve(c.name() + ".tsv"));
      if(rcs.get(c.name()) != 0) {
        rep.fail(c.identity() ? "c" : "b", "JVM con " + c.name() + " rc=" + rcs.get(c.name()) + " (xem " + out.resolve(c.name() + ".log") + ')');
      }
      if(c.identity()) {
        checkIdentity(c.name(), s.cases, retail, r, rep);
      } else {
        checkSame(c.name(), s.cases, retail, r, rep);
      }
    }
    if(!runtime) {
      rep.notRun("c", "khong co runtime remaster");
      rep.notRun("d", "khong co runtime remaster");
    } else if(o.on("d")) {
      checkKeyLog(o, s, out.resolve("loghit.log"), true, rep);
      checkKeyLog(o, s, out.resolve("logmiss.log"), false, rep);
    }
    System.out.printf("  (b)-(d): %.1f s%n", (System.nanoTime() - t0) / 1e9);

    // (e) fuzz
    if(runtime && o.on("e")) {
      fuzzAll(o, s, cube, identity, gl, rep, "e", null, o.fuzz);
    } else {
      rep.notRun("e", runtime ? "--only" : "khong co runtime remaster");
    }
    System.out.printf("  (e): %.1f s%n", (System.nanoTime() - t0) / 1e9);

    // (f) FaceHash
    if(!runtime) {
      rep.notRun("f", "khong co runtime remaster");
    } else if(!o.on("f")) {
      rep.notRun("f", "--only");
    } else if(!gl) {
      rep.notRun("f", "khong tao duoc ngu canh OpenGL an (FULL tai atlas bang lenh GL truc tiep)");
    } else {
      cubeAll(o, cube, rep);
      vecRuntime(o, s, rep);
    }
    System.out.printf("  (f): %.1f s%n", (System.nanoTime() - t0) / 1e9);

    // (g) tự kiểm
    if(o.on("g")) {
      selftest(o, s, cube, identity, retail, rep, gl);
    }
    System.out.printf("  (g): %.1f s%n", (System.nanoTime() - t0) / 1e9);

    final int bad = rep.print();
    System.out.printf("Thoi gian: %.1f s; du lieu: %s%n", (System.nanoTime() - t0) / 1e9, o.work);
    System.out.println(bad == 0 ? "DAT" : "KHONG DAT: " + bad + " muc");
    return bad == 0 ? 0 : 1;
  }

  // =====================================================================================================================
  // kết quả JVM con 'capture'
  // =====================================================================================================================

  /** Một dòng kết quả: id, status, cmp, digests (phần: raw:strict:norm), extra, tex, leak, mut, render, idcmp. */
  record Res(int id, String status, String cmp, String[] raw, String[] strict, String[] norm, int extra, int tex, String leak, String mut, String render,
             String idcmp) {
    static Res of(final String line) {
      final String[] c = line.split("\t", -1);
      final String[] parts = c[3].isEmpty() ? new String[0] : c[3].split("\\|");
      final String[] raw = new String[parts.length];
      final String[] strict = new String[parts.length];
      final String[] norm = new String[parts.length];
      for(int i = 0; i < parts.length; i++) {
        final String[] d = parts[i].split(":");
        raw[i] = d[0];
        strict[i] = d.length > 1 ? d[1] : "";
        norm[i] = d.length > 2 ? d[2] : "";
      }
      return new Res(Integer.parseInt(c[0]), c[1], c[2], raw, strict, norm, Integer.parseInt(c[4]), Integer.parseInt(c[5]), c[6], c[7], c[8],
        c.length > 9 ? c[9] : "");
    }
  }

  static Map<Integer, Res> readRes(final Path p) throws IOException {
    final Map<Integer, Res> m = new HashMap<>();
    if(!Files.isRegularFile(p)) {
      return m;
    }
    for(final String l : Files.readAllLines(p, StandardCharsets.UTF_8)) {
      if(!l.isBlank()) {
        final Res r = Res.of(l);
        m.put(r.id(), r);
      }
    }
    return m;
  }

  static void checkRetailRun(final List<Case> cases, final Map<Integer, Res> retail, final Integer rc, final Report rep) {
    int exc = 0;
    int bad = 0;
    for(final Case c : cases) {
      final Res r = retail.get(c.id());
      if(r == null) {
        rep.fail("ref", "retail: thieu ket qua ca " + c.id());
        bad++;
        continue;
      }
      if(r.status().startsWith("PARSE")) {
        rep.fail("ref", "ca " + c.id() + ' ' + c.label() + " uv=" + c.uv() + ": bo kiem khong dung duoc Model124: " + r.status());
        bad++;
      } else if(!r.status().equals("OK")) {
        exc++;
      }
      if(!"ok".equals(r.cmp())) {
        rep.fail("ref", "RefBuild.retail != TmdObjLoader goc: ca " + c.id() + ' ' + c.label() + ": " + r.cmp());
        bad++;
      }
      if(!r.idcmp().isEmpty() && !"ok".equals(r.idcmp()) && !"-".equals(r.idcmp())) {
        rep.fail("ref", "RefBuild.remaster(identity) != luoi goc chuan hoa: ca " + c.id() + ' ' + c.label() + ": " + r.idcmp());
        bad++;
      }
      if(!"ok".equals(r.leak()) || !"ok".equals(r.mut()) || !"ok".equals(r.render())) {
        rep.fail("ref", "retail ca " + c.id() + ": leak=" + r.leak() + " mut=" + r.mut() + " render=" + r.render());
      }
    }
    if(rc == null || rc != 0) {
      rep.fail("ref", "JVM con retail rc=" + rc);
    }
    rep.info("ref", "retail (jar game): " + retail.size() + " ca, " + exc + " ca TmdObjLoader goc nem loi; RefBuild retail/identity khop lưới goc: "
      + (bad == 0 ? "tat ca" : bad + " ca SAI"));
  }

  static void checkSame(final String cond, final List<Case> cases, final Map<Integer, Res> retail, final Map<Integer, Res> r, final Report rep) {
    rep.ran("b");
    int ok = 0;
    for(final Case c : cases) {
      final Res a = retail.get(c.id());
      final Res b = r.get(c.id());
      if(a == null) {
        continue;
      }
      if(b == null) {
        rep.fail("b", cond + ": thieu ket qua ca " + c.id());
        continue;
      }
      final List<String> e = new ArrayList<>();
      if(!a.status().equals(b.status())) {
        e.add("status " + a.status() + " vs " + b.status());
      } else if(!Arrays.equals(a.raw(), b.raw())) {
        e.add("luoi khac (digest RAW) " + Arrays.toString(a.raw()) + " vs " + Arrays.toString(b.raw()));
      }
      if(!"ok".equals(b.cmp())) {
        e.add(b.cmp());
      }
      if(b.extra() != 0 || b.tex() != 0) {
        e.add("tao them " + b.extra() + " luoi, " + b.tex() + " texture");
      }
      if(!"ok".equals(b.leak()) || !"ok".equals(b.mut()) || !"ok".equals(b.render())) {
        e.add("leak=" + b.leak() + " mut=" + b.mut() + " render=" + b.render());
      }
      if(e.isEmpty()) {
        ok++;
      } else {
        rep.fail("b", cond + " ca " + c.id() + " [" + c.name() + " " + c.label() + " uv=" + c.uv() + "]: " + String.join("; ", e));
      }
    }
    rep.info("b", cond + ": " + ok + '/' + cases.size() + " ca trung tung byte voi jar game");
  }

  static void checkIdentity(final String cond, final List<Case> cases, final Map<Integer, Res> retail, final Map<Integer, Res> r, final Report rep) {
    rep.ran("c");
    int ok = 0;
    int hits = 0;
    for(final Case c : cases) {
      final Res a = retail.get(c.id());
      final Res b = r.get(c.id());
      if(a == null) {
        continue;
      }
      if(b == null) {
        rep.fail("c", cond + ": thieu ket qua ca " + c.id());
        continue;
      }
      final List<String> e = new ArrayList<>();
      final boolean expectRemaster = c.allowed() && "OK".equals(a.status());
      if(!a.status().equals(b.status())) {
        e.add("status " + a.status() + " vs " + b.status());
      } else if(expectRemaster) {
        hits++;
        if(!Arrays.equals(a.norm(), b.strict())) {
          e.add(Arrays.equals(a.norm(), b.norm()) ? "chi khac o kề / QUAD_FLAG (§4.3 [a,a,b,a,c,a])" : "luoi khac luoi goc chuan hoa");
        }
      } else if(!Arrays.equals(a.raw(), b.raw())) {
        e.add("ten bi loai / khong remaster: luoi khac luoi goc");
      }
      if(!"ok".equals(b.cmp())) {
        e.add(b.cmp());
      }
      if(b.extra() != 0 || b.tex() != 0) {
        e.add("tao them " + b.extra() + " luoi, " + b.tex() + " texture (khong co bien the: chi bo VRAM)");
      }
      if(!"ok".equals(b.leak()) || !"ok".equals(b.mut()) || !"ok".equals(b.render())) {
        e.add("leak=" + b.leak() + " mut=" + b.mut() + " render=" + b.render());
      }
      if(e.isEmpty()) {
        ok++;
      } else {
        rep.fail("c", cond + " ca " + c.id() + " [" + c.name() + " " + c.label() + " uv=" + c.uv() + "]: " + String.join("; ", e));
      }
    }
    rep.info("c", cond + ": " + ok + '/' + cases.size() + " ca dung (" + hits + " ca remaster identity, con lai duong goc)");
  }

  static final Pattern LOG_LINE = Pattern.compile("scvi-remaster:\\s*(.*?)\\s+key=([0-9a-f]{40})\\s*(\\S*)");

  /** (d): dòng log 'scvi-remaster: <tên> key=<k> hit|miss|...' khớp RefKey; mọi khoá được phép đều có mặt. */
  static void checkKeyLog(final Opt o, final Scan s, final Path log, final boolean hit, final Report rep) throws IOException {
    rep.ran("d");
    final Map<String, Case> byName = new HashMap<>();
    final Set<String> want = new HashSet<>();
    for(final Case c : s.cases) {
      byName.put(c.name(), c);
      if(c.allowed()) {
        want.add(c.key());
      }
    }
    final Set<String> seen = new HashSet<>();
    int lines = 0;
    int bad = 0;
    int wrongState = 0;
    final Map<String, Integer> hitLines = new HashMap<>();
    final Map<String, Integer> missLines = new HashMap<>();
    if(!Files.isRegularFile(log)) {
      rep.fail("d", "khong co " + log);
      return;
    }
    for(final String l : Files.readAllLines(log, StandardCharsets.UTF_8)) {
      final Matcher m = LOG_LINE.matcher(l);
      if(!m.find()) {
        continue;
      }
      lines++;
      final Case c = byName.get(m.group(1).trim());
      seen.add(m.group(2));
      if(c == null) {
        rep.fail("d", "log: ten la '" + m.group(1) + "'");
        bad++;
        continue;
      }
      if(!c.allowed()) {
        rep.fail("d", "log: ten bi loai van duoc xu ly: " + c.name());
        bad++;
      }
      if(!c.key().equals(m.group(2))) {
        rep.fail("d", "khoa runtime " + m.group(2) + " != RefKey " + c.key() + " (" + c.label() + ')');
        bad++;
      }
      final String state = m.group(3);
      if(!state.startsWith("hit") && !state.startsWith("miss") && !state.startsWith("fallback")) {
        continue;
      }
      (state.startsWith("hit") ? hitLines : missLines).merge(m.group(2), 1, Integer::sum);
      if(hit != state.startsWith("hit")) {
        wrongState++;
        if(wrongState <= 5) {
          rep.fail("d", "log " + (hit ? "loghit" : "logmiss") + ": " + c.label() + " trang thai '" + state + "' (mong doi " + (hit ? "hit" : "miss") + ')');
        }
      }
    }
    // §4.4 'một dòng mỗi khoá', §3.5.4 'ghi log một lần mỗi khoá': miss / fallback không có dòng trạng thái tiếp theo nên mỗi khoá
    // đúng một dòng (cùng khoá được nạp nhiều lần trong JVM này: nhiều tên / UvAdjust, engine state không đổi). Dòng hit có thể có
    // dòng cập nhật biến thể sau đó (pending -> v) nên chỉ ghi nhận số dòng.
    final long missDup = missLines.values().stream().filter(n -> n > 1).count();
    if(missDup > 0) {
      rep.fail("d", log.getFileName() + ": " + missDup + '/' + missLines.size() + " khoa co nhieu dong miss/fallback (toi da "
        + Collections.max(missLines.values()) + " dong; SPEC §4.4 'mot dong moi khoa', §3.5.4 'log mot lan moi khoa')");
    }
    if(!hitLines.isEmpty()) {
      rep.info("d", log.getFileName() + ": " + hitLines.values().stream().mapToInt(Integer::intValue).sum() + " dong hit cho " + hitLines.size()
        + " khoa (toi da " + Collections.max(hitLines.values()) + " dong / khoa)");
    }
    final Set<String> missing = new HashSet<>(want);
    missing.removeAll(seen);
    if(!missing.isEmpty()) {
      rep.fail("d", log.getFileName() + ": " + missing.size() + '/' + want.size() + " khoa khong co dong log 'scvi-remaster: ... key=' (vd " + missing.iterator().next() + ')');
    }
    // vectors.json: RefKey == vectors (đã kiểm trong ref) -> khoá runtime của các mẫu cũng phải == vectors
    int vecOk = 0;
    for(final Vec v : vectors(o)) {
      if(seen.contains(v.modelKey)) {
        vecOk++;
      }
    }
    if(vecOk != vectors(o).size()) {
      rep.fail("d", log.getFileName() + ": chi " + vecOk + '/' + vectors(o).size() + " khoa vectors.json xuat hien trong log runtime");
    }
    rep.info("d", log.getFileName() + ": " + lines + " dong log, " + seen.size() + " khoa, " + bad + " sai; khoa vectors.json trong log: " + vecOk + '/' + vectors(o).size());
  }

  // =====================================================================================================================
  // (e) fuzz
  // =====================================================================================================================

  static final Pattern SUSPICIOUS = Pattern.compile("OutOfMemoryError|NegativeArraySizeException|ArrayIndexOutOfBoundsException|IndexOutOfBoundsException"
    + "|BufferUnderflowException|BufferOverflowException|NullPointerException|ArithmeticException|ClassCastException|StackOverflowError");

  /** check: "e" hoặc "g" (tự kiểm lax). kindsOnly: chỉ dùng các loại này (null = tất cả). */
  static void fuzzAll(final Opt o, final Scan s, final SynthModels.Cube cube, final Map<String, Path> identity, final boolean cubeRuns, final Report rep,
                      final String check, @Nullable final List<String> kindsOnly, final int total) throws Exception {
    rep.ran(check);
    final Path root = o.work.resolve("fuzz" + ("g".equals(check) ? "_selftest" : ""));
    deleteTree(root);
    final SplittableRandom rnd = new SplittableRandom("g".equals(check) ? 77 : 20261019);
    // kho: mỗi khoá một ca (tên được phép, gốc chạy được)
    final Map<String, Case> pool = new LinkedHashMap<>();
    for(final Case c : s.cases) {
      if(c.allowed() && identity.containsKey(c.key()) && !pool.containsKey(c.key()) && !"png".equals(c.uv())) {
        pool.put(c.key(), c);
      }
    }
    final List<Case> poolList = new ArrayList<>(pool.values());
    final int nCube = cubeRuns ? Math.min(400, total / 5) : 0;
    final int nReal = total - nCube;
    final List<Job> jobs = new ArrayList<>();
    final Map<String, Integer> kindCount = new TreeMap<>();
    int made = 0;
    int run = 0;
    if(poolList.isEmpty() && nReal > 0) {
      // không có ca gốc (không dựng được file identity nào): trước đây vòng dưới lặp vô hạn, tạo thư mục real_N mãi
      rep.fail(check, "fuzz: khong co mo hinh that nao lam goc (0 file identity / ten duoc phep) -> bo " + nReal + " dot bien mo hinh that");
    }
    while(made < nReal && !poolList.isEmpty()) {
      final Path dir = root.resolve("real_" + run);
      Files.createDirectories(dir.resolve("remaster").resolve("models"));
      final StringBuilder man = new StringBuilder();
      final List<String> keys = new ArrayList<>();
      final List<Case> runCases = new ArrayList<>();
      for(int i = 0; i < poolList.size() && made < nReal; i++, made++) {
        final Case c = poolList.get(i);
        final Model124 m = SynthModels.model(c.label(), Files.readAllBytes(c.file()), SynthModels.uv(c.uv()), c.clutAnim());
        final RefLrm.Runtime rt = RefLrm.Runtime.of(SynthModels.tables(m));
        final byte[] base = Files.readAllBytes(identity.get(c.key()));
        final RefLrm.Lrm l = RefLrm.read(base, rt);
        final List<String> kinds = kindsOnly != null ? kindsOnly : Fuzz.kinds(l);
        final String kind = kinds.get(rnd.nextInt(kinds.size()));
        final Fuzz.Mutation mu = Fuzz.mutate(base, l, rt, kind, rnd);
        Files.write(dir.resolve("remaster").resolve("models").resolve(c.key() + ".lrm"), mu.data());
        keys.add(c.key());
        runCases.add(c);
        man.append(made).append('\t').append(c.id()).append('\t').append(c.key()).append('\t').append(kind).append('\n');
        kindCount.merge(kind, 1, Integer::sum);
      }
      Files.writeString(dir.resolve("remaster").resolve("index.tsv"), indexText((Iterable<String>)keys, "fuzz"), StandardCharsets.UTF_8);
      Files.writeString(dir.resolve("remaster.properties"), "enabled=true\ntextures=retail\nlog=true\n", StandardCharsets.UTF_8);
      Files.writeString(dir.resolve("manifest.tsv"), man.toString(), StandardCharsets.UTF_8);
      writeCases(dir.resolve("cases.tsv"), runCases);
      final List<String> props = new ArrayList<>(runtimeProps(o, false));
      props.add("-Dscvi.remasterLog=true");
      // cấp phát theo số đếm trong file trước khi kiểm cắt cụt (§3.5.4 mục 3) -> OOM -> JVM thoát rc=3, không bị nuốt bởi catch Throwable
      props.add("-XX:+ExitOnOutOfMemoryError");
      if("g".equals(check)) {
        props.add("-Dremastercheck.mock=true");
        props.add("-Dremastercheck.fault=lax:role");
      }
      jobs.add(new Job("fuzz_real_" + run + ("g".equals(check) ? "_g" : ""), dir, "g".equals(check) ? cpRetail(o) : cpRuntime(o), props,
        List.of("fuzz", dir.resolve("manifest.tsv").toString(), dir.resolve("cases.tsv").toString(), dir.resolve("result.tsv").toString(), o.spec.toString()),
        dir.resolve("run.log")));
      run++;
    }
    if(nCube > 0) {
      final Path dir = root.resolve("cube");
      Files.createDirectories(dir.resolve("remaster").resolve("models"));
      Files.createDirectories(dir.resolve("remaster").resolve("textures"));
      for(int v = 0; v < cube.pngSha1.length; v++) {
        Files.write(dir.resolve("remaster").resolve("textures").resolve(cube.pngSha1[v] + ".png"), cube.pngBytes(o.synth, v));
      }
      final StringBuilder man = new StringBuilder();
      final List<String> keys = new ArrayList<>();
      for(int j = 1; j <= nCube; j++, made++) {
        final Model124 m = cube.model(cube.keyVariant(j), "slot0");
        final RefLrm.Runtime rt = RefLrm.Runtime.of(SynthModels.tables(m));
        final byte[] base = cube.lrmFor(m);
        final RefLrm.Lrm l = RefLrm.read(base, rt);
        final List<String> kinds = Fuzz.kinds(l);
        final String kind = kinds.get(rnd.nextInt(kinds.size()));
        final Fuzz.Mutation mu = Fuzz.mutate(base, l, rt, kind, rnd);
        final String key = RefKey.HEX.formatHex(rt.modelKey());
        Files.write(dir.resolve("remaster").resolve("models").resolve(key + ".lrm"), mu.data());
        keys.add(key);
        man.append(made).append("\tcube:").append(j).append('\t').append(key).append('\t').append(kind).append('\n');
        kindCount.merge(kind, 1, Integer::sum);
      }
      Files.writeString(dir.resolve("remaster").resolve("index.tsv"), indexText((Iterable<String>)keys, "fuzz cube"), StandardCharsets.UTF_8);
      Files.writeString(dir.resolve("remaster.properties"), "enabled=true\ntextures=hd\nlog=true\n", StandardCharsets.UTF_8);
      Files.writeString(dir.resolve("manifest.tsv"), man.toString(), StandardCharsets.UTF_8);
      final List<String> cprops = new ArrayList<>(runtimeProps(o, true));
      cprops.add("-Dscvi.remasterLog=true");
      cprops.add("-XX:+ExitOnOutOfMemoryError");
      jobs.add(new Job("fuzz_cube", dir, cpRuntime(o), cprops,
        List.of("fuzz", dir.resolve("manifest.tsv").toString(), "-", dir.resolve("result.tsv").toString(), o.spec.toString()), dir.resolve("run.log")));
    }
    final Map<String, Integer> rcs = runJobs(o, jobs);
    int total2 = 0;
    int valid = 0;
    int fallbacks = 0;
    final Map<String, Integer> failKinds = new TreeMap<>();
    for(final Job j : jobs) {
      if(rcs.get(j.name()) != 0) {
        rep.fail(check, "JVM con " + j.name() + " rc=" + rcs.get(j.name()) + (rcs.get(j.name()) == 3 ? " (OutOfMemoryError: cap phat theo so dem trong file truoc khi kiem cat cut?)" : "")
          + " (xem " + j.log() + ')');
      }
      if(!"g".equals(check)) {
        useAfterDelete(j.log(), x -> rep.fail(check, j.name() + ": " + x));
      }
      // runtime phải từ chối file bằng kiểm tra (§3.5.4, kiểm cắt cụt TRƯỚC khi cấp phát), không phải nhờ bắt ngoại lệ lập trình
      if(!"g".equals(check) && Files.isRegularFile(j.log())) {
        for(final String l : Files.readAllLines(j.log(), StandardCharsets.UTF_8)) {
          if(!l.contains("scvi-remaster") || !l.contains("fallback")) {
            continue;
          }
          fallbacks++;
          final Matcher sm = SUSPICIOUS.matcher(l);
          if(sm.find()) {
            rep.fail(check, "fallback do ngoai le " + sm.group() + " (thieu kiem tra truoc khi cap phat / doc?): " + clean(l.trim()));
          }
        }
      }
      final Path res = j.cwd().resolve("result.tsv");
      if(!Files.isRegularFile(res)) {
        continue;
      }
      for(final String l : Files.readAllLines(res, StandardCharsets.UTF_8)) {
        if(l.isBlank()) {
          continue;
        }
        final String[] c = l.split("\t", -1);
        total2++;
        if(c[2].startsWith("valid")) {
          valid++;
        }
        if("ok".equals(c[3])) {
          continue;
        }
        // atlas4th (NaN ở góc thứ 4 của mặt tam giác) giờ là lỗi thật: SPEC §3.5.4 ghi rõ góc đó "không kiểm", runtime từ chối
        // file đó là trái đặc tả (trước đây chỉ ghi nhận vì R1 cũ từ chối và ref_spec.py cũng từ chối)
        failKinds.merge(c[1], 1, Integer::sum);
        if(!"g".equals(check)) {
          rep.fail(check, "dot bien " + c[0] + " (" + c[1] + ", file " + c[2] + "): " + c[3]);
        }
      }
    }
    if("g".equals(check)) {
      // tự kiểm: bộ kiểm lỏng luật role -> chỉ đột biến roleBad bị bắt, và phải có ít nhất một
      if(!failKinds.containsKey("roleBad") || failKinds.size() != 1) {
        rep.fail("g", "MockRuntime lax:role: fuzz bat " + failKinds + " (mong doi chi roleBad)");
      } else {
        rep.info("g", "MockRuntime bo luat role: fuzz bat " + failKinds.get("roleBad") + " dot bien roleBad, khong bao nham loai khac");
      }
      return;
    }
    if(total2 != total) {
      rep.fail(check, "chi co ket qua cho " + total2 + '/' + total + " dot bien");
    }
    rep.info(check, total2 + " dot bien (" + valid + " van hop le, " + (total2 - valid) + " sai), " + nCube + " tren sample_cube (FULL), "
      + fallbacks + " dong log fallback, loai: " + kindCount);
    if(total < 2000) {
      // đề (e) đòi 2000 đột biến: chạy ít hơn (-Fuzz N) không được tính là đạt
      rep.notRun(check, "chi " + total + " dot bien (-Fuzz < 2000 cua de)");
    }
  }

  // =====================================================================================================================
  // (f) sample_cube ở FULL + mẫu vectors
  // =====================================================================================================================

  /** Kịch bản sample_cube: TIM trong VRAM, chế độ, tên, UvAdjust, tw/th, clutAnim, biến thể mong đợi (-1 = VRAM, -2 = đường gốc). */
  record Scenario(String id, String props, List<String> dprops, String tim, String name, String uv, int tw, int th, boolean clutAnim, int expect,
                  boolean atlasSets) { }

  static List<Scenario> scenarios() {
    final String full = "enabled=true\ntextures=hd\nlog=true\n";
    final List<String> log = List.of("-Dscvi.remasterLog=true");
    final String sobj = "SobjModel (index 0)";
    return List.of(
      new Scenario("A", full, log, "A", sobj, "slot0", 0, 0, false, 0, true),
      new Scenario("B", full, log, "B", sobj, "slot0", 0, 0, false, 1, true),
      new Scenario("C", full, log, "C", sobj, "slot0", 0, 0, false, -1, true),
      new Scenario("D", full, log, "D", sobj, "slot0", 0, 0, false, -1, true),
      new Scenario("E", full, log, "E", sobj, "slot0", 0, 0, false, 0, true),
      new Scenario("geometryD", full, List.of("-Dscvi.remaster=geometry", "-Dscvi.remasterLog=true"), "A", sobj, "slot0", 0, 0, false, -1, false),
      new Scenario("texRetail", "enabled=true\ntextures=retail\n", List.of(), "A", sobj, "slot0", 0, 0, false, -1, false),
      new Scenario("tw", full, log, "A", sobj, "png", 32, 32, false, -1, false),
      new Scenario("clutAnim", full, log, "A", sobj, "slot0", 0, 0, true, -1, false),
      new Scenario("excluded", full, log, "A", "Savepoint", "slot0", 0, 0, false, -2, false),
      new Scenario("wmap", full, log, "A", "WmapEntityModel (index 2)", "wmap", 0, 0, false, 0, true),
      new Scenario("slot5", full, log, "A", "CombatantModel (cube slot5)", "slot5", 0, 0, false, 0, true),
      new Scenario("trip", full, log, "A", sobj, "slot0", 0, 0, false, 0, true),
      // file hỏng (byte generator 0x7f), nạp 4 lần: luôn đường gốc, log fallback đúng MỘT lần cho khoá (§3.5.4)
      new Scenario("fallback3", full, log, "A", sobj, "slot0", 0, 0, false, -2, false));
  }

  /** Thư mục + job của kịch bản vòng đời 'share' (hai mô hình cùng atlas, xoá một, nạp lại tại chỗ, xoá hết). */
  static Job shareJob(final Opt o, final SynthModels.Cube cube, final Path dir, final String name, final List<String> props, final String cp) throws IOException {
    final Scenario a = scenarios().stream().filter(x -> x.id().equals("A")).findFirst().orElseThrow();
    prepareCube(o, cube, a, dir);
    final List<String> p = new ArrayList<>(props);
    p.addAll(a.dprops());
    return new Job(name, dir, cp, p, List.of("share", o.spec.toString(), dir.resolve("result.txt").toString()), dir.resolve("run.log"));
  }

  /** Đọc result.txt (FAIL / INFO) + log JVM con của kịch bản 'share' vào mục check. */
  static void shareResult(final Path dir, final Integer rc, final String label, final java.util.function.Consumer<String> fail,
                          final java.util.function.Consumer<String> info) throws IOException {
    final Path res = dir.resolve("result.txt");
    final List<String> lines = Files.isRegularFile(res) ? Files.readAllLines(res, StandardCharsets.UTF_8) : List.of("FAIL khong co ket qua");
    for(final String l : lines) {
      if(l.startsWith("FAIL ")) {
        fail.accept(label + ": " + l.substring(5));
      } else if(l.startsWith("INFO ")) {
        info.accept(label + ": " + l.substring(5));
      }
    }
    if(rc == null || rc != 0) {
      fail.accept(label + ": JVM con rc=" + rc + " (xem " + dir.resolve("run.log") + ')');
    }
    useAfterDelete(dir.resolve("run.log"), x -> fail.accept(label + ": " + x));
  }

  static void cubeAll(final Opt o, final SynthModels.Cube cube, final Report rep) throws Exception {
    rep.ran("f");
    final Path root = o.work.resolve("cube");
    deleteTree(root);
    final List<Job> jobs = new ArrayList<>();
    for(final Scenario sc : scenarios()) {
      final Path dir = root.resolve(sc.id());
      prepareCube(o, cube, sc, dir);
      final List<String> props = new ArrayList<>(runtimeProps(o, true));
      props.addAll(sc.dprops());
      jobs.add(new Job("cube_" + sc.id(), dir, cpRuntime(o), props, List.of("cube", sc.id(), o.spec.toString(), dir.resolve("result.txt").toString()), dir.resolve("run.log")));
    }
    jobs.add(shareJob(o, cube, root.resolve("share"), "cube_share", runtimeProps(o, true), cpRuntime(o)));
    final Map<String, Integer> rcs = runJobs(o, jobs);
    shareResult(root.resolve("share"), rcs.get("cube_share"), "sample_cube share", s -> rep.fail("f", s), s -> rep.info("f", s));
    for(final Scenario sc : scenarios()) {
      final Path dir = root.resolve(sc.id());
      final Path res = dir.resolve("result.txt");
      final List<String> lines = Files.isRegularFile(res) ? Files.readAllLines(res, StandardCharsets.UTF_8) : List.of("FAIL khong co ket qua");
      for(final String l : lines) {
        if(l.startsWith("FAIL ")) {
          rep.fail("f", "sample_cube " + sc.id() + ": " + l.substring(5));
        } else if(l.startsWith("INFO ")) {
          rep.info("f", "sample_cube " + sc.id() + ": " + l.substring(5));
        }
      }
      if(rcs.get("cube_" + sc.id()) != 0) {
        rep.fail("f", "sample_cube " + sc.id() + ": JVM con rc=" + rcs.get("cube_" + sc.id()) + " (xem " + dir.resolve("run.log") + ')');
      }
      useAfterDelete(dir.resolve("run.log"), x -> rep.fail("f", "sample_cube " + sc.id() + ": " + x));
      // số dòng log 'scvi-remaster: ... key=<k> <trạng thái>' của khoá sample_cube trong JVM con này
      final Map<String, Integer> states = new TreeMap<>();
      if(Files.isRegularFile(dir.resolve("run.log"))) {
        for(final String l : Files.readAllLines(dir.resolve("run.log"), StandardCharsets.UTF_8)) {
          final Matcher m = LOG_LINE.matcher(l);
          if(m.find() && m.group(2).equals(cube.modelKey)) {
            final String st = m.group(3).replaceAll("\\(.*", "");
            states.merge(st.isEmpty() ? "?" : st, 1, Integer::sum);
          }
        }
      }
      if("fallback3".equals(sc.id())) {
        if(states.getOrDefault("fallback", 0) != 1 || states.containsKey("hit")) {
          rep.fail("f", "sample_cube fallback3: file hong nap 4 lan -> log " + states + " (mong doi dung 1 dong fallback, §3.5.4 'log mot lan moi khoa')");
        } else {
          rep.info("f", "sample_cube fallback3: file hong nap 4 lan -> duong goc, log fallback 1 lan");
        }
      }
      vecLogCheck(sc, cube, lines, dir.resolve("run.log"), s -> rep.fail("f", s), s -> rep.info("f", s));
    }
  }

  /**
   * Véc-tơ face-hash runtime trong log (-Dscvi.remasterLog=true) = Python (§3.3.6, §4.4). JVM con ghi 'VEC <sha1> <số mặt bpp 3>'
   * tính từ VRAM + gói live của kịch bản (mặt bpp 3 ghi 0). Kịch bản có bộ ATLAS: log PHẢI có SHA-1 đó. Kịch bản có mặt bpp 3
   * (ghi đè PNG, §3.4 c; WP0): nếu runtime in véc-tơ thì đó PHẢI là véc-tơ ghi 0 cho mọi mặt bpp 3.
   */
  static void vecLogCheck(final Scenario sc, final SynthModels.Cube cube, final List<String> resultLines, final Path runLog,
                          final java.util.function.Consumer<String> fail, final java.util.function.Consumer<String> info) throws IOException {
    String want = cube.vectorSha1.get(sc.tim());
    int nBpp3 = 0;
    for(final String l : resultLines) {
      if(l.startsWith("VEC ")) {
        final String[] v = l.split(" ");
        want = v[1];
        nBpp3 = Integer.parseInt(v[2]);
      }
    }
    final String log = Files.isRegularFile(runLog) ? Files.readString(runLog, StandardCharsets.UTF_8) : "";
    final Set<String> known = new HashSet<>(cube.partKeys);
    known.add(cube.modelKey);
    known.addAll(Arrays.asList(cube.pngSha1));
    final Set<String> shas = new HashSet<>();
    final Pattern hex40 = Pattern.compile("\\b[0-9a-f]{40}\\b");
    for(final String l : log.split("\n")) {
      if(l.contains("scvi-remaster")) {
        final Matcher m = hex40.matcher(l);
        while(m.find()) {
          if(!known.contains(m.group())) {
            shas.add(m.group());
          }
        }
      }
    }
    if(sc.expect() >= 0 || sc.expect() == -1 && sc.atlasSets()) {
      if(!shas.contains(want)) {
        fail.accept("sample_cube " + sc.id() + ": log -Dscvi.remasterLog khong co SHA-1 vec-to face-hash runtime " + want + " (TIM " + sc.tim() + "); thay: " + shas);
      }
    } else if(nBpp3 > 0 && sc.dprops().contains("-Dscvi.remasterLog=true")) {
      if(shas.isEmpty()) {
        info.accept("sample_cube " + sc.id() + ": " + nBpp3 + " mat bpp 3, runtime khong in vec-to face-hash (khong co bo ATLAS) -> quy tac 'bpp 3 ghi 0' khong ap dung");
      } else if(!shas.contains(want) || shas.size() != 1) {
        fail.accept("sample_cube " + sc.id() + ": vec-to face-hash runtime trong log " + shas + " != " + want + " (" + nBpp3 + " mat bpp 3 phai ghi 0, §3.3.6)");
      } else {
        info.accept("sample_cube " + sc.id() + ": vec-to face-hash runtime trong log ghi 0 cho " + nBpp3 + " mat bpp 3 (= " + want + ')');
      }
    }
  }

  static void prepareCube(final Opt o, final SynthModels.Cube cube, final Scenario sc, final Path dir) throws IOException {
    Files.createDirectories(dir.resolve("remaster").resolve("models"));
    Files.createDirectories(dir.resolve("remaster").resolve("textures"));
    Files.write(dir.resolve("remaster").resolve("models").resolve(cube.modelKey + ".lrm"), cube.lrm);
    for(int v = 0; v < cube.pngSha1.length; v++) {
      Files.write(dir.resolve("remaster").resolve("textures").resolve(cube.pngSha1[v] + ".png"), cube.pngBytes(o.synth, v));
    }
    Files.writeString(dir.resolve("remaster").resolve("index.tsv"), indexText((Iterable<String>)List.of(cube.modelKey), "sample_cube"), StandardCharsets.UTF_8);
    Files.writeString(dir.resolve("remaster.properties"), sc.props(), StandardCharsets.UTF_8);
    if("fallback3".equals(sc.id())) {
      final byte[] bad = cube.lrm.clone();
      bad[0x28 + 3] = 0x7f; // generator: byte ngoài ASCII in được -> file sai (§3.5.4 mục 1)
      Files.write(dir.resolve("remaster").resolve("models").resolve(cube.modelKey + ".lrm"), bad);
    }
  }

  // =====================================================================================================================
  // JVM con
  // =====================================================================================================================

  static int child(final String[] a) throws Exception {
    if(Boolean.getBoolean("remastercheck.gl")) {
      if(CaptureApi.GlContext.create()) {
        CaptureApi.useGlTextures();
        System.out.println("GL: ngu canh an, RENDERER.api() = " + CaptureApi.apiName());
      } else {
        System.out.println("GL: khong tao duoc ngu canh (tiep tuc khong GL)");
      }
    }
    return switch(a[0]) {
      case "glprobe" -> CaptureApi.GlContext.create() ? 0 : 1;
      case "capture" -> childCapture(Path.of(a[1]), Path.of(a[2]), a[3]);
      case "fuzz" -> childFuzz(Path.of(a[1]), "-".equals(a[2]) ? null : Path.of(a[2]), Path.of(a[3]), Path.of(a[4]));
      case "cube" -> childCube(a[1], Path.of(a[2]), Path.of(a[3]));
      case "share" -> childShare(Path.of(a[1]), Path.of(a[2]));
      case "vecrt" -> childVec(Path.of(a[1]), Path.of(a[2]), Path.of(a[3]));
      default -> {
        System.out.println("viec la: " + a[0]);
        yield 1;
      }
    };
  }

  static void fromModel(final String name, final Model124 m, final int tw, final int th) {
    if(Boolean.getBoolean("remastercheck.mock")) {
      MockRuntime.fromModel(name, m, tw, th);
    } else {
      TmdObjLoader.fromModel(name, m, tw, th);
    }
  }

  private static Field objField;
  private static Field objListField;

  @Nullable
  static Obj objOf(final TmdObjTable1c t) {
    try {
      if(objField == null) {
        objField = TmdObjTable1c.class.getDeclaredField("obj");
        objField.setAccessible(true);
      }
      return (Obj)objField.get(t);
    } catch(final ReflectiveOperationException e) {
      throw new RuntimeException(e);
    }
  }

  @SuppressWarnings("unchecked")
  static List<Obj> objList() {
    try {
      if(objListField == null) {
        objListField = Obj.class.getDeclaredField("objList");
        objListField.setAccessible(true);
      }
      return (List<Obj>)objListField.get(null);
    } catch(final ReflectiveOperationException e) {
      throw new RuntimeException(e);
    }
  }

  /** Băm dữ liệu live của TmdObjTable1c (đỉnh, pháp tuyến, header + byte gói) để phát hiện runtime sửa dữ liệu mô hình. */
  static String liveDigest(final TmdObjTable1c[] tables) {
    final MessageDigest md = RefKey.sha1();
    for(final TmdObjTable1c t : tables) {
      for(final Vector3f v : t.vert_top_00) {
        RefKey.u32(md, Float.floatToRawIntBits(v.x));
        RefKey.u32(md, Float.floatToRawIntBits(v.y));
        RefKey.u32(md, Float.floatToRawIntBits(v.z));
      }
      for(final Vector3f v : t.normal_top_08) {
        RefKey.u32(md, Float.floatToRawIntBits(v.x));
        RefKey.u32(md, Float.floatToRawIntBits(v.y));
        RefKey.u32(md, Float.floatToRawIntBits(v.z));
      }
      for(final TmdObjTable1c.Primitive p : t.primitives_10) {
        RefKey.u32(md, p.header());
        for(final byte[] d : p.data()) {
          md.update(d);
        }
      }
    }
    return RefKey.HEX.formatHex(md.digest(), 0, 8);
  }

  /** Vẽ một Obj như RenderEngine (lượt đục rồi lượt trong mờ), trả về lưới được vẽ theo từng layer. */
  static List<List<CaptureApi.RecMesh>> renderLikeEngine(final Obj obj) {
    final List<List<CaptureApi.RecMesh>> out = new ArrayList<>();
    CaptureApi.renderPhase = true;
    try {
      for(int layer = 0; layer < obj.getLayers(); layer++) {
        CaptureApi.DRAWS.clear();
        if(obj.shouldRender(null, layer)) {
          obj.render(null, layer, 0, 0);
        }
        if(obj.hasTranslucency(layer)) {
          for(final Translucency t : Translucency.FOR_RENDERING) {
            if(obj.shouldRender(t, layer)) {
              obj.render(t, layer, 0, 0);
            }
          }
        }
        out.add(new ArrayList<>(new LinkedHashSet<>(CaptureApi.DRAWS)));
      }
      if(obj.hasTranslucency()) {
        for(int layer = 0; layer < obj.getLayers(); layer++) {
          CaptureApi.DRAWS.clear();
          for(final Translucency t : Translucency.FOR_RENDERING) {
            if(obj.shouldRender(t, layer)) {
              obj.render(t, layer, 0, 0);
            }
          }
          for(final CaptureApi.RecMesh m : CaptureApi.DRAWS) {
            if(!out.get(layer).contains(m)) {
              out.get(layer).add(m);
            }
          }
        }
      }
    } finally {
      CaptureApi.renderPhase = false;
    }
    return out;
  }

  /** Xoá Obj của mọi phần như game (TmdObjTable1c.delete -> Obj.deleteObjects -> Texture.deleteTextures), trả về lỗi rò rỉ. */
  static String cleanup(final TmdObjTable1c[] tables, final List<CaptureApi.RecMesh> meshes, final List<CaptureApi.RecTexture> textures) {
    for(final TmdObjTable1c t : tables) {
      t.delete();
    }
    Obj.deleteObjects();
    Texture.deleteTextures();
    final List<String> e = new ArrayList<>();
    int live = 0;
    for(final CaptureApi.RecMesh m : meshes) {
      if(!m.deleted) {
        live++;
      }
    }
    if(live > 0) {
      e.add(live + " luoi chua delete()");
    }
    int tex = 0;
    for(final CaptureApi.RecTexture t : textures) {
      if(!CaptureApi.textureDeleted(t.texture())) {
        tex++;
      }
    }
    if(tex > 0) {
      e.add(tex + " texture chua delete()");
    }
    final List<Obj> objs = objList();
    if(!objs.isEmpty()) {
      e.add(objs.size() + " Obj con trong danh sach (" + objs.get(0).name + ')');
      objs.clear();
    }
    return e.isEmpty() ? "ok" : String.join(",", e).replace('\t', ' ');
  }

  static String clean(final String s) {
    return s.replace('\t', ' ').replace('\n', ' ').replace('\r', ' ');
  }

  static int childCapture(final Path casesFile, final Path outFile, final String expect) throws Exception {
    final List<Case> cases = readCases(casesFile);
    final boolean identity = "identity".equals(expect);
    final boolean retailRun = !Boolean.getBoolean("remastercheck.mock") && TmdObjLoader.class.getProtectionDomain().getCodeSource().getLocation().toString().contains("lod-game");
    System.out.println("capture " + expect + ": " + cases.size() + " ca; TmdObjLoader tu " + TmdObjLoader.class.getProtectionDomain().getCodeSource().getLocation()
      + (Boolean.getBoolean("remastercheck.mock") ? " (MockRuntime)" : ""));
    final long t0 = System.nanoTime();
    try(final BufferedWriter w = Files.newBufferedWriter(outFile, StandardCharsets.UTF_8)) {
      for(final Case c : cases) {
        w.write(captureOne(c, identity, retailRun));
        w.write('\n');
      }
    }
    System.out.printf("thoi gian %.1f s: nap %.1f, mong doi %.1f, identity %.1f, fromModel %.1f, so+bam %.1f, ve %.1f, xoa %.1f%n",
      (System.nanoTime() - t0) / 1e9, PROF[0] / 1e9, PROF[1] / 1e9, PROF[2] / 1e9, PROF[3] / 1e9, PROF[4] / 1e9, PROF[5] / 1e9, PROF[6] / 1e9);
    return 0;
  }

  static final long[] PROF = new long[8];
  private static long profT;

  static void prof(final int phase) {
    final long now = System.nanoTime();
    if(phase >= 0) {
      PROF[phase] += now - profT;
    }
    profT = now;
  }

  private static Path lastFile;
  private static byte[] lastBytes;

  /** Các ca liền nhau thường cùng file (ô 0 / NONE / PNG / Wmap / tên bị loại): giữ file vừa đọc (SynthModels.model tự chép). */
  static byte[] read(final Path p) throws IOException {
    if(!p.equals(lastFile)) {
      lastBytes = Files.readAllBytes(p);
      lastFile = p;
    }
    return lastBytes;
  }

  static String captureOne(final Case c, final boolean identity, final boolean retailRun) throws IOException {
    prof(-1);
    final Model124 m;
    final TmdObjTable1c[] tables;
    try {
      m = SynthModels.model(c.label(), read(c.file()), SynthModels.uv(c.uv()), c.clutAnim());
      tables = SynthModels.tables(m);
    } catch(final Throwable t) {
      return c.id() + "\tPARSE:" + clean(t.toString()) + "\tok\t\t0\t0\tok\tok\tok\t-";
    }
    final String before = liveDigest(tables);
    prof(0);
    // lưới mong đợi (tính TRƯỚC fromModel)
    final List<RefBuild.Part> expected = new ArrayList<>();
    String expStatus = "OK";
    String idErr = "";
    RefLrm.Lrm idLrm = null;
    if(identity && c.allowed()) {
      final Path f = Path.of("remaster", "models", c.key() + ".lrm");
      if(Files.isRegularFile(f)) {
        try {
          idLrm = RefLrm.read(Files.readAllBytes(f), RefLrm.Runtime.of(tables));
        } catch(final Throwable t) {
          idErr = "file identity khong doc duoc: " + t.getMessage();
        }
      }
    }
    try {
      for(int i = 0; i < tables.length; i++) {
        if(idLrm != null && idLrm.parts[i].mode == 1) {
          expected.add(RefBuild.remaster(tables[i], RefBuild.decode(tables[i]), idLrm.parts[i], c.tw(), c.th(), null, null, 0));
        } else {
          expected.add(RefBuild.retail(c.name() + " part " + i, tables[i], c.tw(), c.th()));
        }
      }
    } catch(final Throwable t) {
      expStatus = "EXC";
    }
    prof(1);
    // retail run: RefBuild.remaster(identity trong bộ nhớ) == lưới gốc chuẩn hoá (tự kiểm bộ dựng trên mọi mô hình)
    final List<RefBuild.Part> idExpected = new ArrayList<>();
    if(retailRun && "OK".equals(expStatus)) {
      try {
        final RefLrm.Lrm l = RefLrm.identity(tables);
        for(int i = 0; i < tables.length; i++) {
          idExpected.add(RefBuild.remaster(tables[i], RefBuild.decode(tables[i]), l.parts[i], c.tw(), c.th(), null, null, 0));
        }
      } catch(final Throwable t) {
        idExpected.clear();
      }
    }
    prof(2);
    CaptureApi.reset();
    String status = "OK";
    try {
      fromModel(c.name(), m, c.tw(), c.th());
    } catch(final Throwable t) {
      status = "EXC:" + t.getClass().getName();
    }
    prof(3);
    final List<String> cmp = new ArrayList<>();
    if(!idErr.isEmpty()) {
      cmp.add(idErr);
    }
    final StringBuilder dig = new StringBuilder();
    final Set<CaptureApi.RecMesh> vram = Collections.newSetFromMap(new IdentityHashMap<>());
    String idcmp = retailRun ? "ok" : "-";
    if(status.equals("OK") != expStatus.equals("OK")) {
      cmp.add("status: mong doi " + expStatus + " vs " + status);
    }
    if(status.equals("OK")) {
      for(int i = 0; i < tables.length; i++) {
        final Obj obj = objOf(tables[i]);
        final RefBuild.Part act = RefBuild.capture(obj);
        if(obj instanceof final MeshObj mo) {
          for(final var mesh : mo.meshes) {
            if(mesh instanceof final CaptureApi.RecMesh r) {
              vram.add(r);
            }
          }
        }
        if(i > 0) {
          dig.append('|');
        }
        dig.append(RefBuild.digest(act, RefBuild.RAW)).append(':').append(RefBuild.digest(act, RefBuild.STRICT)).append(':').append(RefBuild.digest(act, RefBuild.NORM));
        if(expStatus.equals("OK")) {
          for(final String e : RefBuild.compare(expected.get(i), act, !identity || idLrm == null)) {
            cmp.add("phan " + i + ' ' + e);
          }
        }
        if(!idExpected.isEmpty() && act != null) {
          final List<String> e = RefBuild.compare(idExpected.get(i), RefBuild.normalized(act), false);
          if(!e.isEmpty()) {
            idcmp = "phan " + i + ' ' + e.get(0);
          }
        }
      }
    }
    int extra = 0;
    for(final CaptureApi.RecMesh r : CaptureApi.MESHES) {
      if(!vram.contains(r)) {
        extra++;
      }
    }
    final int tex = CaptureApi.TEXTURES.size();
    prof(4);
    // vẽ 2 khung như engine: không ném lỗi, chỉ vẽ lưới bộ VRAM, không tạo lưới / texture trong lúc vẽ
    String render = "ok";
    if(status.equals("OK")) {
      try {
        for(int frame = 0; frame < 2; frame++) {
          for(final TmdObjTable1c t : tables) {
            final Obj obj = objOf(t);
            if(obj == null) {
              continue;
            }
            for(final List<CaptureApi.RecMesh> layer : renderLikeEngine(obj)) {
              for(final CaptureApi.RecMesh r : layer) {
                if(!vram.contains(r)) {
                  render = "ve luoi ngoai bo VRAM: " + r.name;
                }
              }
            }
          }
        }
        if(CaptureApi.createdDuringRender > 0) {
          render = CaptureApi.createdDuringRender + " luoi/texture tao trong luc ve";
        }
        for(final CaptureApi.RecMesh r : CaptureApi.MESHES) {
          if(r.updates > 0) {
            render = "mesh.update() tren " + r.name;
          }
        }
      } catch(final Throwable t) {
        render = "render nem " + t;
      }
    }
    prof(5);
    final String leak = cleanup(tables, new ArrayList<>(CaptureApi.MESHES), new ArrayList<>(CaptureApi.TEXTURES));
    final String mut = before.equals(liveDigest(tables)) ? "ok" : "MUTATED";
    prof(6);
    final String cmpS = cmp.isEmpty() ? "ok" : clean(cmp.size() + " loi: " + String.join(" / ", cmp.subList(0, Math.min(3, cmp.size()))));
    return c.id() + "\t" + status + '\t' + cmpS + '\t' + dig + '\t' + extra + '\t' + tex + '\t' + clean(leak) + '\t' + mut + '\t' + clean(render) + '\t' + clean(idcmp);
  }

  // ---------------------------------------------------------------- fuzz (JVM con)

  /** Lưới bộ VRAM mong đợi cho file (đã đột biến) theo phân loại của RefLrm; null = file sai -> đường gốc. */
  record Expect(@Nullable RefLrm.Lrm lrm, String why, List<RefBuild.Part> vram) { }

  static Expect expectFor(final byte[] data, final Model124 m, final String name, final int tw, final int th) {
    final TmdObjTable1c[] t = SynthModels.tables(m);
    RefLrm.Lrm l = null;
    String why;
    try {
      l = RefLrm.read(data, RefLrm.Runtime.of(t));
      why = "valid";
    } catch(final RefLrm.Invalid e) {
      why = "invalid:" + e.rule;
    }
    final List<RefBuild.Part> parts = new ArrayList<>();
    for(int i = 0; i < t.length; i++) {
      if(l != null && l.parts[i].mode == 1) {
        parts.add(RefBuild.remaster(t[i], RefBuild.decode(t[i]), l.parts[i], tw, th, null, null, 0));
      } else {
        parts.add(RefBuild.retail(name + " part " + i, t[i], tw, th));
      }
    }
    return new Expect(l, why, parts);
  }

  static int childFuzz(final Path manifest, @Nullable final Path casesFile, final Path outFile, final Path spec) throws Exception {
    final Map<Integer, Case> cases = new HashMap<>();
    if(casesFile != null) {
      for(final Case c : readCases(casesFile)) {
        cases.put(c.id(), c);
      }
    }
    SynthModels.Cube cube = null;
    RefFaceHash.Vram gpu = null;
    final List<String[]> rows = new ArrayList<>();
    for(final String l : Files.readAllLines(manifest, StandardCharsets.UTF_8)) {
      if(!l.isBlank()) {
        rows.add(l.split("\t"));
      }
    }
    // mô hình sample_cube: giữ lại tới vòng vẽ (xác minh theo khung)
    record Live(String[] row, Model124 m, Expect exp, String name, List<CaptureApi.RecMesh> meshes, List<CaptureApi.RecTexture> textures, int expectVariant,
                Set<CaptureApi.RecMesh> vram, StringBuilder err, boolean asRetail) { }
    final List<Live> lives = new ArrayList<>();
    try(final BufferedWriter w = Files.newBufferedWriter(outFile, StandardCharsets.UTF_8)) {
      for(final String[] row : rows) {
        final boolean isCube = row[1].startsWith("cube:");
        final Model124 m;
        final String name;
        int tw = 0;
        int th = 0;
        if(isCube) {
          if(cube == null) {
            cube = SynthModels.Cube.load(spec);
            final RefFaceHash.Tim tim = RefFaceHash.parseTim(cube.tims.get("A"));
            GameEngine.GPU.uploadData15(new Rect4i(576, 256, tim.iw(), tim.ih()), tim.img());
            GameEngine.GPU.uploadData15(new Rect4i(576, 368, tim.cw(), tim.ch()), tim.clut());
            gpu = (x, y) -> GameEngine.GPU.getPixel15(x, y);
          }
          m = cube.model(cube.keyVariant(Integer.parseInt(row[1].substring(5))), "slot0");
          name = "SobjModel (index " + row[0] + ')';
        } else {
          final Case c = cases.get(Integer.parseInt(row[1]));
          m = SynthModels.model(c.label(), Files.readAllBytes(c.file()), SynthModels.uv(c.uv()), c.clutAnim());
          name = c.name();
          tw = c.tw();
          th = c.th();
        }
        final TmdObjTable1c[] tables = SynthModels.tables(m);
        final byte[] data = Files.readAllBytes(Path.of("remaster", "models", row[2] + ".lrm"));
        final Expect exp = expectFor(data, m, name, tw, th);
        final String before = liveDigest(tables);
        CaptureApi.reset();
        final StringBuilder err = new StringBuilder();
        boolean asRetail = true;
        try {
          fromModel(name, m, tw, th);
        } catch(final Throwable t) {
          err.append("fromModel nem ").append(t).append("; ");
        }
        final Set<CaptureApi.RecMesh> vram = Collections.newSetFromMap(new IdentityHashMap<>());
        if(err.isEmpty()) {
          for(int i = 0; i < tables.length; i++) {
            final RefBuild.Part act = RefBuild.capture(objOf(tables[i]));
            if(objOf(tables[i]) instanceof final MeshObj mo) {
              for(final var mesh : mo.meshes) {
                if(mesh instanceof final CaptureApi.RecMesh r) {
                  vram.add(r);
                }
              }
            }
            final List<String> e = RefBuild.compare(exp.vram().get(i), act, exp.lrm() == null);
            if(!e.isEmpty()) {
              err.append("phan ").append(i).append(' ').append(e.get(0)).append("; ");
            }
            if(exp.lrm() != null && exp.lrm().parts[i].mode == 1) {
              // file hợp lệ: có thật là runtime đã đi đường gốc không? (để phân biệt 'tu choi file hop le')
              final RefBuild.Part ret = RefBuild.retail(name + " part " + i, tables[i], tw, th);
              if(!RefBuild.compare(ret, act, true).isEmpty()) {
                asRetail = false;
              }
            }
          }
        }
        if(!before.equals(liveDigest(tables))) {
          err.append("runtime sua TmdObjTable1c; ");
        }
        int expectVariant = -1;
        if(isCube && exp.lrm() != null && exp.lrm().variants.length > 0) {
          final List<List<RefBuild.Face>> faces = SynthModels.faces(m);
          final boolean[] live = RefFaceHash.liveModel(m, faces);
          final int[] rt = RefFaceHash.rawVector(gpu, faces);
          final int[][] stored = Arrays.stream(exp.lrm().variants).map(v -> v.faceHash).toArray(int[][]::new);
          expectVariant = RefFaceHash.expectedVariant(rt, stored, live);
          if(expectVariant >= 0 && !pngOk(exp.lrm().variants[expectVariant])) {
            expectVariant = -1;
          }
        }
        if(isCube) {
          lives.add(new Live(row, m, exp, name, new ArrayList<>(CaptureApi.MESHES), new ArrayList<>(CaptureApi.TEXTURES), expectVariant, vram, err,
            exp.lrm() != null && asRetail && !err.isEmpty()));
          continue;
        }
        // mô hình thật: vẽ 2 khung, chỉ được vẽ bộ VRAM
        if(err.isEmpty()) {
          try {
            for(int f = 0; f < 2; f++) {
              for(final TmdObjTable1c t : tables) {
                if(objOf(t) != null) {
                  for(final List<CaptureApi.RecMesh> layer : renderLikeEngine(objOf(t))) {
                    for(final CaptureApi.RecMesh r : layer) {
                      if(!vram.contains(r)) {
                        err.append("ve luoi ngoai bo VRAM; ");
                      }
                    }
                  }
                }
              }
            }
          } catch(final Throwable t) {
            err.append("render nem ").append(t).append("; ");
          }
        }
        final String leak = cleanup(tables, new ArrayList<>(CaptureApi.MESHES), new ArrayList<>(CaptureApi.TEXTURES));
        if(!"ok".equals(leak)) {
          err.append("leak ").append(leak).append("; ");
        }
        w.write(row[0] + '\t' + row[3] + '\t' + exp.why() + '\t' + (err.isEmpty() ? "ok" : (exp.lrm() != null && asRetail ? "retail: " : "") + clean(err.toString())) + '\n');
      }
      if(!lives.isEmpty()) {
        // vòng vẽ: tới 6 s; mô hình mong đợi ATLAS(v) phải vẽ đúng bộ ATLAS v, mô hình mong đợi VRAM không bao giờ vẽ lưới khác bộ VRAM
        final Map<Live, Integer> atlasFrames = new HashMap<>();
        final Map<Live, List<List<List<CaptureApi.RecMesh>>>> last = new HashMap<>();
        final long end = System.nanoTime() + 6_000_000_000L;
        int frame = 0;
        while(System.nanoTime() < end) {
          boolean done = frame > 30;
          for(final Live lv : lives) {
            if(!lv.err.isEmpty() && lv.err.indexOf("render") >= 0) {
              continue;
            }
            final List<List<List<CaptureApi.RecMesh>>> parts = new ArrayList<>();
            boolean nonVram = false;
            try {
              for(final ModelPart10 p : lv.m.modelParts_00) {
                final Obj o = objOf(p.tmd_08);
                final List<List<CaptureApi.RecMesh>> layers = o == null ? List.of() : renderLikeEngine(o);
                for(final List<CaptureApi.RecMesh> l : layers) {
                  for(final CaptureApi.RecMesh r : l) {
                    nonVram |= !lv.vram.contains(r);
                  }
                }
                parts.add(layers);
              }
            } catch(final Throwable t) {
              lv.err.append("render nem ").append(t).append("; ");
              continue;
            }
            last.put(lv, parts);
            if(nonVram) {
              if(lv.expectVariant < 0) {
                if(lv.err.indexOf("ve ATLAS") < 0) {
                  lv.err.append("ve ATLAS du mong doi chi VRAM (khung ").append(frame).append("); ");
                }
              } else {
                atlasFrames.merge(lv, 1, Integer::sum);
              }
            }
            if(lv.expectVariant >= 0 && atlasFrames.getOrDefault(lv, 0) < 20) {
              done = false;
            }
          }
          frame++;
          if(done && frame > 60) {
            break;
          }
          Thread.sleep(5);
        }
        for(final Live lv : lives) {
          if(lv.expectVariant >= 0 && lv.err.isEmpty()) {
            final List<List<List<CaptureApi.RecMesh>>> parts = last.get(lv);
            final TmdObjTable1c[] t = SynthModels.tables(lv.m);
            final List<List<RefBuild.Face>> faces = SynthModels.faces(lv.m);
            final boolean[] liveM = RefFaceHash.liveModel(lv.m, faces);
            final RefLrm.Variant v = lv.exp.lrm().variants[lv.expectVariant];
            final boolean[] liveV = RefFaceHash.liveVariant(liveM, v.faceHash);
            for(int i = 0; i < t.length && parts != null; i++) {
              final RefBuild.Part want = lv.exp.lrm().parts[i].mode == 1
                ? RefBuild.remaster(t[i], faces.get(i), lv.exp.lrm().parts[i], 0, 0, v.atlasUv, liveV, texBase(faces, i))
                : RefBuild.retail(lv.name + " part " + i, t[i], 0, 0);
              final RefBuild.Part got = drawnPart(parts.get(i), want);
              final List<String> e = RefBuild.compare(want, got, false);
              if(!e.isEmpty()) {
                lv.err.append("ATLAS(").append(lv.expectVariant).append(") phan ").append(i).append(' ').append(e.get(0)).append("; ");
              }
            }
            if(atlasFrames.getOrDefault(lv, 0) == 0) {
              lv.err.append("khong bao gio ve ATLAS(").append(lv.expectVariant).append("); ");
            }
          }
        }
        // xoá mọi mô hình rồi mới kiểm (Obj.deleteObjects xử lý cả danh sách)
        for(final Live lv : lives) {
          for(final TmdObjTable1c t : SynthModels.tables(lv.m)) {
            t.delete();
          }
        }
        Obj.deleteObjects();
        Texture.deleteTextures();
        final List<Obj> left = objList();
        if(!left.isEmpty()) {
          lives.get(0).err.append("leak ").append(left.size()).append(" Obj con trong danh sach (").append(left.get(0).name).append("); ");
          left.clear();
        }
        for(final Live lv : lives) {
          final long meshes = lv.meshes.stream().filter(r -> !r.deleted).count();
          final long tex = lv.textures.stream().filter(r -> !CaptureApi.textureDeleted(r.texture())).count();
          if(meshes + tex > 0) {
            lv.err.append("leak ").append(meshes).append(" luoi, ").append(tex).append(" texture chua delete(); ");
          }
          w.write(lv.row[0] + '\t' + lv.row[3] + '\t' + lv.exp.why() + (lv.expectVariant >= 0 ? "/atlas" + lv.expectVariant : "/vram") + '\t'
            + (lv.err.isEmpty() ? "ok" : (lv.asRetail ? "retail: " : "") + clean(lv.err.toString())) + '\n');
        }
      }
    }
    return 0;
  }

  static boolean pngOk(final RefLrm.Variant v) {
    final Path p = Path.of("remaster", "textures", RefKey.HEX.formatHex(v.png) + ".png");
    try {
      if(!Files.isRegularFile(p)) {
        return false;
      }
      final byte[] b = Files.readAllBytes(p);
      if(!Arrays.equals(RefKey.sha1(b), v.png)) {
        return false;
      }
      final int w = (b[16] & 0xff) << 24 | (b[17] & 0xff) << 16 | (b[18] & 0xff) << 8 | b[19] & 0xff;
      final int h = (b[20] & 0xff) << 24 | (b[21] & 0xff) << 16 | (b[22] & 0xff) << 8 | b[23] & 0xff;
      return w == v.w && h == v.h;
    } catch(final IOException e) {
      return false;
    }
  }

  /** Lưới đã vẽ theo layer -> Part (một lưới mỗi layer). */
  static RefBuild.Part drawnPart(final List<List<CaptureApi.RecMesh>> layers, final RefBuild.Part want) {
    final List<RefBuild.MeshData> meshes = new ArrayList<>();
    for(final List<CaptureApi.RecMesh> l : layers) {
      if(l.size() == 1) {
        meshes.add(RefBuild.of(l.get(0)));
      } else {
        meshes.add(new RefBuild.MeshData("VE " + l.size() + " LUOI", false, false, null, "?", "?", new long[0][], new float[0], new int[0]));
      }
    }
    return new RefBuild.Part(true, want.backface(), meshes);
  }

  // ---------------------------------------------------------------- sample_cube (JVM con)

  static int childCube(final String id, final Path spec, final Path outFile) throws Exception {
    final Scenario sc = scenarios().stream().filter(x -> x.id().equals(id)).findFirst().orElseThrow();
    final SynthModels.Cube cube = SynthModels.Cube.load(spec);
    final List<String> out = new ArrayList<>();
    final java.util.function.Consumer<String> fail = s -> out.add("FAIL " + clean(s));
    final java.util.function.Consumer<String> info = s -> out.add("INFO " + clean(s));
    if(!CaptureApi.GlContext.active()) {
      fail.accept("khong co ngu canh GL");
    }
    final legend.game.tmd.UvAdjustmentMetrics14 uv = SynthModels.uv(sc.uv());
    final boolean slotted = !"png".equals(sc.uv()) && !"none".equals(sc.uv());
    final int ix = slotted ? uv.tpageX : 576;
    final int iy = slotted ? uv.tpageY : 256;
    final int cx = slotted ? uv.clutX : 576;
    final int cy = slotted ? uv.clutY : 368;
    final java.util.function.Consumer<String> place = k -> {
      final RefFaceHash.Tim tim = RefFaceHash.parseTim(cube.tims.get(k));
      GameEngine.GPU.uploadData15(new Rect4i(ix, iy, tim.iw(), tim.ih()), tim.img());
      GameEngine.GPU.uploadData15(new Rect4i(cx, cy, tim.cw(), tim.ch()), tim.clut());
    };
    place.accept(sc.tim());
    final Model124 m = cube.model(cube.ccontainer, sc.uv());
    if(sc.clutAnim()) {
      m.clutAnimations_a4 = new ClutAnimations();
    }
    final TmdObjTable1c[] t = SynthModels.tables(m);
    final List<List<RefBuild.Face>> faces = SynthModels.faces(m);
    final RefLrm.Lrm l = RefLrm.read(cube.lrm, RefLrm.Runtime.of(t));
    final boolean[] liveM = RefFaceHash.liveModel(m, faces);
    final RefFaceHash.Vram gpu = (x, y) -> GameEngine.GPU.getPixel15(x, y);
    final int[] rtHashes = RefFaceHash.rawVector(gpu, faces);
    // véc-tơ face-hash runtime mong đợi của kịch bản (§3.3.6: mặt bpp 3 ghi 0) -> 'all' so với dòng log -Dscvi.remasterLog
    int nBpp3 = 0;
    for(final List<RefBuild.Face> fs : faces) {
      for(final RefBuild.Face f : fs) {
        if(f.textured && f.bpp() == 3) {
          nBpp3++;
        }
      }
    }
    out.add("VEC " + RefFaceHash.vectorSha1(rtHashes) + ' ' + nBpp3);
    if("slot0".equals(sc.uv()) && !RefFaceHash.vectorSha1(rtHashes).equals(cube.vectorSha1.get(sc.tim()))) {
      fail.accept("bo kiem: vec-to face-hash tinh tu VRAM != sample_cube.json faceHashVectorSha1[" + sc.tim() + ']');
    }
    final int[][] stored = Arrays.stream(l.variants).map(v -> v.faceHash).toArray(int[][]::new);
    int expect = sc.expect();
    if(expect >= -1 && sc.atlasSets()) {
      final int ev = RefFaceHash.expectedVariant(rtHashes, stored, liveM);
      if(ev != expect) {
        fail.accept("bo kiem: bien the mong doi tinh tu VRAM = " + ev + " != kich ban " + expect);
      }
    }
    // mong đợi: bộ VRAM + bộ ATLAS từng biến thể
    final List<RefBuild.Part> wantVram = new ArrayList<>();
    final List<List<RefBuild.Part>> wantAtlas = new ArrayList<>();
    for(int i = 0; i < t.length; i++) {
      wantVram.add(expect == -2 ? stripNames(RefBuild.retail(sc.name() + " part " + i, t[i], sc.tw(), sc.th()))
        : RefBuild.remaster(t[i], faces.get(i), l.parts[i], sc.tw(), sc.th(), null, null, texBase(faces, i)));
    }
    for(int v = 0; v < l.variants.length && sc.atlasSets(); v++) {
      final boolean[] lv = RefFaceHash.liveVariant(liveM, l.variants[v].faceHash);
      final List<RefBuild.Part> ps = new ArrayList<>();
      for(int i = 0; i < t.length; i++) {
        ps.add(RefBuild.remaster(t[i], faces.get(i), l.parts[i], 0, 0, l.variants[v].atlasUv, lv, texBase(faces, i)));
      }
      wantAtlas.add(ps);
    }
    if("slot0".equals(sc.uv()) && expect != -2) {
      for(int i = 0; i < t.length; i++) {
        final List<String> e = RefBuild.compare(cube.vram.get(i), wantVram.get(i), false);
        if(!e.isEmpty()) {
          fail.accept("bo kiem: RefBuild VRAM != sample_cube.json phan " + i + ": " + e.get(0));
        }
      }
    }
    if("fallback3".equals(sc.id())) {
      // nạp lại 3 lần trước lần nạp chính: mỗi lần phải ra đúng lưới gốc, không ném lỗi
      for(int k = 0; k < 3; k++) {
        CaptureApi.reset();
        try {
          fromModel(sc.name(), m, sc.tw(), sc.th());
          for(int i = 0; i < t.length; i++) {
            final List<String> e = RefBuild.compare(wantVram.get(i), RefBuild.capture(objOf(t[i])), false);
            if(!e.isEmpty()) {
              fail.accept("lan nap " + (k + 1) + " phan " + i + ": " + e.get(0));
            }
          }
        } catch(final Throwable e) {
          fail.accept("lan nap " + (k + 1) + ": fromModel nem " + e);
        }
        cleanup(t, new ArrayList<>(CaptureApi.MESHES), new ArrayList<>(CaptureApi.TEXTURES));
      }
    }
    CaptureApi.reset();
    try {
      fromModel(sc.name(), m, sc.tw(), sc.th());
    } catch(final Throwable e) {
      fail.accept("fromModel nem " + e);
      Files.write(outFile, out, StandardCharsets.UTF_8);
      return 0;
    }
    final int glErr = CaptureApi.GlContext.error();
    if(glErr != 0) {
      fail.accept("loi GL sau khi nap: 0x" + Integer.toHexString(glErr));
    }
    // bộ VRAM
    final Set<CaptureApi.RecMesh> vram = Collections.newSetFromMap(new IdentityHashMap<>());
    for(int i = 0; i < t.length; i++) {
      final Obj o = objOf(t[i]);
      final List<String> e = RefBuild.compare(wantVram.get(i), RefBuild.capture(o), false);
      if(!e.isEmpty()) {
        fail.accept((expect == -2 ? "duong goc" : "bo VRAM") + " phan " + i + ": " + e.get(0));
      }
      if(o instanceof final MeshObj mo) {
        for(final var mesh : mo.meshes) {
          if(mesh instanceof final CaptureApi.RecMesh r) {
            vram.add(r);
          }
        }
      }
    }
    // lưới thêm = bộ ATLAS (so như tập, không phụ thuộc thứ tự tạo / tên)
    final List<CaptureApi.RecMesh> extra = new ArrayList<>();
    for(final CaptureApi.RecMesh r : CaptureApi.MESHES) {
      if(!vram.contains(r)) {
        extra.add(r);
      }
    }
    if(sc.atlasSets()) {
      final List<String> want = new ArrayList<>();
      for(final List<RefBuild.Part> ps : wantAtlas) {
        for(final RefBuild.Part p : ps) {
          for(final RefBuild.MeshData md : p.meshes()) {
            want.add(meshKey(md));
          }
        }
      }
      final List<String> got = new ArrayList<>();
      for(final CaptureApi.RecMesh r : extra) {
        got.add(meshKey(RefBuild.of(r)));
      }
      Collections.sort(want);
      Collections.sort(got);
      if(!want.equals(got)) {
        fail.accept("bo ATLAS: " + got.size() + " luoi them, mong doi " + want.size() + " (khop " + countCommon(want, got) + ')');
      }
      // texture atlas: 1 mỗi PNG, mip §3.6
      checkAtlasTextures(cube, fail, info);
    } else {
      if(!extra.isEmpty()) {
        fail.accept("tao " + extra.size() + " luoi ngoai bo VRAM (kich ban khong duoc dung bo ATLAS)");
      }
      if(!CaptureApi.TEXTURES.isEmpty()) {
        fail.accept("tao " + CaptureApi.TEXTURES.size() + " texture (kich ban khong duoc nap atlas)");
      }
    }
    // vòng vẽ
    final java.util.function.Supplier<Integer> frame = () -> {
      int st = -1;
      boolean mixed = false;
      for(int i = 0; i < t.length; i++) {
        final Obj o = objOf(t[i]);
        if(o == null) {
          continue;
        }
        final List<List<CaptureApi.RecMesh>> layers = renderLikeEngine(o);
        final RefBuild.Part drawn = drawnPart(layers, wantVram.get(i));
        int ps = RefBuild.compare(wantVram.get(i), drawn, false).isEmpty() ? -1 : -3;
        for(int v = 0; v < wantAtlas.size() && ps == -3; v++) {
          if(RefBuild.compare(wantAtlas.get(v).get(i), drawn, false).isEmpty()) {
            ps = v;
          }
        }
        if(i == 0) {
          st = ps;
        } else if(ps != st) {
          mixed = true;
        }
      }
      return mixed ? -4 : st;
    };
    final int target = expect == -2 ? -1 : expect;
    // chờ tới khi trạng thái vẽ = want ổn định 10 khung (trả về want), hoặc hết giờ (trả về trạng thái cuối); gặp lưới lạ -> trả về ngay
    final java.util.function.BiFunction<Integer, Double, Integer> waitFor = (want, seconds) -> {
      final long end = System.nanoTime() + (long)(seconds * 1e9);
      int st = Integer.MIN_VALUE;
      int stable = 0;
      while(System.nanoTime() < end) {
        final int s = frame.get();
        if(s == -3 || s == -4) {
          return s;
        }
        stable = s == st ? stable + 1 : 0;
        st = s;
        if(s == want && stable >= 10) {
          return s;
        }
        try {
          Thread.sleep(5);
        } catch(final InterruptedException e) {
          Thread.currentThread().interrupt();
        }
      }
      return st;
    };
    // suốt thời gian cho trước chỉ được vẽ bộ VRAM; khung đầu tiên khác -> trả về trạng thái đó
    final java.util.function.Function<Double, Integer> vramOnly = seconds -> {
      final long end = System.nanoTime() + (long)(seconds * 1e9);
      int st = Integer.MIN_VALUE;
      while(System.nanoTime() < end) {
        st = frame.get();
        if(st != -1) {
          return st;
        }
        try {
          Thread.sleep(5);
        } catch(final InterruptedException e) {
          Thread.currentThread().interrupt();
        }
      }
      return st;
    };
    try {
      final int s1 = target >= 0 ? waitFor.apply(target, 4.0) : vramOnly.apply(3.0);
      if(s1 != target) {
        fail.accept("trang thai ve " + stateName(s1) + ", mong doi " + stateName(target));
      } else {
        info.accept("ve " + stateName(s1) + " dung mong doi");
      }
      if("trip".equals(sc.id()) && s1 == 0) {
        int trips = 0;
        for(int k = 0; k < 4; k++) {
          place.accept("C");
          final int s2 = waitFor.apply(-1, 3.0);
          if(s2 != -1) {
            fail.accept("doi VRAM sang TIM C: van ve " + stateName(s2) + " (phai ve bo VRAM trong ~1-2 s)");
            break;
          }
          trips++;
          place.accept("A");
          final int s3 = waitFor.apply(0, 3.5);
          if(s3 != 0) {
            if(trips >= 3 && s3 == -1) {
              info.accept("chong nhap nhay: sau " + trips + " lan ATLAS->PENDING mo hinh khoa o VRAM (khuyen nghi RISKS)");
            } else {
              fail.accept("tra lai TIM A sau " + trips + " lan: ve " + stateName(s3) + ", mong doi ATLAS(0)" + (trips < 3 ? "" : " hoac khoa VRAM"));
            }
            break;
          }
          if(trips >= 3) {
            info.accept("sau " + trips + " lan ATLAS->PENDING van quay lai ATLAS(0) (chua khoa VRAM - khuyen nghi, khong bat buoc)");
            break;
          }
        }
      }
    } catch(final Throwable e) {
      fail.accept("render nem " + e);
    }
    if(CaptureApi.createdDuringRender > 0) {
      fail.accept(CaptureApi.createdDuringRender + " luoi/texture tao trong luc ve (D5)");
    }
    for(final CaptureApi.RecMesh r : CaptureApi.MESHES) {
      if(r.updates > 0) {
        fail.accept("mesh.update() trong luc ve (D5): " + r.name);
        break;
      }
    }
    final String leak = cleanup(t, new ArrayList<>(CaptureApi.MESHES), new ArrayList<>(CaptureApi.TEXTURES));
    if(!"ok".equals(leak)) {
      fail.accept("sau khi xoa moi Obj: " + leak);
    }
    if(out.stream().noneMatch(x -> x.startsWith("FAIL"))) {
      out.add("OK");
    }
    Files.write(outFile, out, StandardCharsets.UTF_8);
    return 0;
  }

  /**
   * Trạng thái vẽ một khung của một mô hình (các phần t): -1 = bộ VRAM, v = ATLAS(v), -3 = lưới lạ, -4 = các phần vẽ bộ khác
   * nhau, Integer.MIN_VALUE = không vẽ gì. wantVram / wantAtlas: lưới mong đợi theo phần (wantAtlas[v][phần]).
   */
  static int drawState(final TmdObjTable1c[] t, final List<RefBuild.Part> wantVram, final List<List<RefBuild.Part>> wantAtlas) {
    int st = Integer.MIN_VALUE;
    boolean first = true;
    for(int i = 0; i < t.length; i++) {
      final Obj o = objOf(t[i]);
      if(o == null) {
        continue;
      }
      final RefBuild.Part drawn = drawnPart(renderLikeEngine(o), wantVram.get(i));
      int ps = RefBuild.compare(wantVram.get(i), drawn, false).isEmpty() ? -1 : -3;
      for(int v = 0; v < wantAtlas.size() && ps == -3; v++) {
        if(RefBuild.compare(wantAtlas.get(v).get(i), drawn, false).isEmpty()) {
          ps = v;
        }
      }
      if(first) {
        st = ps;
        first = false;
      } else if(ps != st) {
        return -4;
      }
    }
    return st;
  }

  /** Vẽ tới khi mọi mô hình ở trạng thái want ổn định 10 khung (true) hoặc hết giờ (false); last[k] = trạng thái cuối mô hình k. */
  static boolean waitAll(final List<TmdObjTable1c[]> models, final List<RefBuild.Part> wantVram, final List<List<RefBuild.Part>> wantAtlas,
                         final int want, final double seconds, final int[] last) throws InterruptedException {
    final long end = System.nanoTime() + (long)(seconds * 1e9);
    int stable = 0;
    while(System.nanoTime() < end) {
      boolean all = true;
      for(int k = 0; k < models.size(); k++) {
        last[k] = drawState(models.get(k), wantVram, wantAtlas);
        all &= last[k] == want;
      }
      stable = all ? stable + 1 : 0;
      if(stable >= 10) {
        return true;
      }
      Thread.sleep(5);
    }
    return false;
  }

  /**
   * Kịch bản vòng đời 'share' (§4.2 AtlasCache đếm tham chiếu theo pngSha1, §4.4 performDelete, D5), sample_cube ở FULL, TIM A:
   * hai mô hình cùng khoá -> cả hai ATLAS(0) và đúng một texture mỗi PNG; xoá mô hình 1 (TmdObjTable1c.delete +
   * Obj.deleteObjects + Texture.deleteTextures như game) -> atlas dùng chung còn sống, mô hình 2 vẫn vẽ ATLAS(0) mọi khung; nạp lại
   * mô hình 2 tại chỗ -> không tạo texture mới, atlas không bị xoá, lại ATLAS(0); xoá hết -> mọi lưới / texture được xoá.
   * 'all' còn quét log JVM con tìm 'used after being deleted' (GlTexture.use trên texture đã xoá).
   */
  static int childShare(final Path spec, final Path outFile) throws Exception {
    final SynthModels.Cube cube = SynthModels.Cube.load(spec);
    final List<String> out = new ArrayList<>();
    final java.util.function.Consumer<String> fail = s -> out.add("FAIL " + clean(s));
    final java.util.function.Consumer<String> info = s -> out.add("INFO " + clean(s));
    if(!CaptureApi.GlContext.active()) {
      fail.accept("khong co ngu canh GL");
    }
    final RefFaceHash.Tim tim = RefFaceHash.parseTim(cube.tims.get("A"));
    GameEngine.GPU.uploadData15(new Rect4i(576, 256, tim.iw(), tim.ih()), tim.img());
    GameEngine.GPU.uploadData15(new Rect4i(576, 368, tim.cw(), tim.ch()), tim.clut());
    final Model124 m1 = cube.model(cube.ccontainer, "slot0");
    final Model124 m2 = cube.model(cube.ccontainer, "slot0");
    final TmdObjTable1c[] t1 = SynthModels.tables(m1);
    final TmdObjTable1c[] t2 = SynthModels.tables(m2);
    final List<List<RefBuild.Face>> faces = SynthModels.faces(m1);
    final RefLrm.Lrm l = RefLrm.read(cube.lrm, RefLrm.Runtime.of(t1));
    final boolean[] liveM = RefFaceHash.liveModel(m1, faces);
    final List<RefBuild.Part> wantVram = new ArrayList<>();
    final List<List<RefBuild.Part>> wantAtlas = new ArrayList<>();
    for(int i = 0; i < t1.length; i++) {
      wantVram.add(RefBuild.remaster(t1[i], faces.get(i), l.parts[i], 0, 0, null, null, texBase(faces, i)));
    }
    for(int v = 0; v < l.variants.length; v++) {
      final boolean[] lv = RefFaceHash.liveVariant(liveM, l.variants[v].faceHash);
      final List<RefBuild.Part> ps = new ArrayList<>();
      for(int i = 0; i < t1.length; i++) {
        ps.add(RefBuild.remaster(t1[i], faces.get(i), l.parts[i], 0, 0, l.variants[v].atlasUv, lv, texBase(faces, i)));
      }
      wantAtlas.add(ps);
    }
    final int[] last = new int[2];
    CaptureApi.reset();
    try {
      fromModel("SobjModel (index 0)", m1, 0, 0);
      fromModel("SobjModel (index 1)", m2, 0, 0);
      final List<CaptureApi.RecTexture> tex = new ArrayList<>(CaptureApi.TEXTURES);
      final java.util.function.Supplier<Long> deadTex = () -> tex.stream().filter(r -> CaptureApi.textureDeleted(r.texture())).count();
      if(tex.size() != cube.pngSha1.length) {
        fail.accept(tex.size() + " texture sau khi nap 2 mo hinh cung khoa, mong doi " + cube.pngSha1.length
          + " (AtlasCache dung chung mot texture moi pngSha1, §4.2)");
      }
      // 1. cả hai ATLAS(0)
      if(!waitAll(List.of(t1, t2), wantVram, wantAtlas, 0, 4.0, last)) {
        fail.accept("2 mo hinh cung khoa: ve " + stateName(last[0]) + " / " + stateName(last[1]) + ", mong doi ATLAS(0) ca hai");
      }
      // 2. xoá mô hình 1 như game -> atlas dùng chung phải còn, mô hình 2 vẫn ATLAS(0) mọi khung trong 1.5 s
      for(final TmdObjTable1c t : t1) {
        t.delete();
      }
      Obj.deleteObjects();
      Texture.deleteTextures();
      if(deadTex.get() > 0) {
        fail.accept("xoa mo hinh 1 lam xoa " + deadTex.get() + " texture atlas dung chung trong khi mo hinh 2 con dung (§4.2 dem tham chieu)");
      }
      final long end = System.nanoTime() + 1_500_000_000L;
      int frames = 0;
      while(System.nanoTime() < end) {
        final int st = drawState(t2, wantVram, wantAtlas);
        frames++;
        if(st != 0) {
          fail.accept("sau khi xoa mo hinh 1, mo hinh 2 ve " + stateName(st) + " o khung " + frames + " (mong doi ATLAS(0) moi khung)");
          break;
        }
        Thread.sleep(5);
      }
      // 3. nạp lại mô hình 2 tại chỗ (fromModel trên cùng Model124, như đổi hoạt cảnh / nạp lại cảnh): không texture mới
      final int texBefore = CaptureApi.TEXTURES.size();
      fromModel("SobjModel (index 1)", m2, 0, 0);
      Obj.deleteObjects();
      Texture.deleteTextures();
      if(CaptureApi.TEXTURES.size() != texBefore) {
        fail.accept("nap lai mo hinh 2 tai cho tao them " + (CaptureApi.TEXTURES.size() - texBefore) + " texture (atlas dang dung phai duoc dung lai, §4.2)");
      }
      if(deadTex.get() > 0) {
        fail.accept("nap lai mo hinh 2 tai cho lam xoa " + deadTex.get() + " texture atlas dung chung dang dung");
      }
      if(!waitAll(Collections.singletonList(t2), wantVram, wantAtlas, 0, 4.0, last)) {
        fail.accept("sau khi nap lai tai cho: mo hinh 2 ve " + stateName(last[0]) + ", mong doi ATLAS(0)");
      }
      if(CaptureApi.createdDuringRender > 0) {
        fail.accept(CaptureApi.createdDuringRender + " luoi/texture tao trong luc ve (D5)");
      }
      for(final CaptureApi.RecMesh r : CaptureApi.MESHES) {
        if(r.updates > 0) {
          fail.accept("mesh.update() trong luc ve (D5): " + r.name);
          break;
        }
      }
      // 4. xoá hết: mọi lưới (cả của mô hình 1 và lần nạp trước của mô hình 2) và texture phải được xoá
      final String leak = cleanup(t2, new ArrayList<>(CaptureApi.MESHES), new ArrayList<>(CaptureApi.TEXTURES));
      if(!"ok".equals(leak)) {
        fail.accept("sau khi xoa ca hai mo hinh: " + leak);
      }
    } catch(final Throwable e) {
      fail.accept("nem " + e);
    }
    if(out.stream().noneMatch(x -> x.startsWith("FAIL"))) {
      info.accept("2 mo hinh cung atlas: xoa mot -> atlas con, mo hinh con lai van ATLAS(0); nap lai tai cho khong tao texture; xoa het -> sach");
      out.add("OK");
    }
    Files.write(outFile, out, StandardCharsets.UTF_8);
    return 0;
  }

  static String stateName(final int s) {
    return switch(s) {
      case -1 -> "bo VRAM";
      case -3 -> "luoi la (khong khop VRAM / ATLAS nao)";
      case -4 -> "cac phan ve bo khac nhau";
      case Integer.MIN_VALUE -> "khong ve gi";
      default -> s < -1 ? "duong goc" : "ATLAS(" + s + ')';
    };
  }

  static String meshKey(final RefBuild.MeshData m) {
    return RefBuild.cls(m) + '/' + RefKey.sha1Hex(RefBuild.floatsLE(m.v())) + '/' + RefKey.sha1Hex(RefBuild.intsLE(m.idx())) + '/' + RefBuild.attrs(m.attrs()) + '/' + m.order() + '/' + m.overload();
  }

  static int countCommon(final List<String> a, final List<String> b) {
    final List<String> x = new ArrayList<>(b);
    int n = 0;
    for(final String s : a) {
      if(x.remove(s)) {
        n++;
      }
    }
    return n;
  }

  /** §3.6.2-3.6.4: mỗi PNG một texture GL, chuỗi mip tới 1x1, NEAREST_MIPMAP_NEAREST / NEAREST / CLAMP, persistent, texel từng mức. */
  static void checkAtlasTextures(final SynthModels.Cube cube, final java.util.function.Consumer<String> fail0, final java.util.function.Consumer<String> info) {
    final int[] nFail = {0};
    final java.util.function.Consumer<String> fail = s -> {
      nFail[0]++;
      fail0.accept(s);
    };
    final List<CaptureApi.RecTexture> tex = CaptureApi.TEXTURES;
    if(tex.size() != cube.pngSha1.length) {
      fail.accept(tex.size() + " texture duoc tao, mong doi " + cube.pngSha1.length + " (moi PNG mot texture)");
    }
    final Set<Integer> matched = new HashSet<>();
    for(final CaptureApi.RecTexture rt : tex) {
      if(!rt.texture().persistent) {
        fail.accept("texture atlas " + rt.name() + " khong persistent");
      }
      final int id = CaptureApi.glTextureId(rt.texture());
      if(id <= 0) {
        fail.accept("texture " + rt.name() + " khong phai GlTexture");
        continue;
      }
      final int[] inf = CaptureApi.GlContext.textureInfo(id);
      final String l0 = RefKey.sha1Hex(CaptureApi.GlContext.textureLevel(id, 0));
      int v = -1;
      for(int k = 0; k < cube.mipSha1.length; k++) {
        if(cube.mipSha1[k][0].equals(l0)) {
          v = k;
        }
      }
      if(v < 0) {
        fail.accept("texture " + rt.name() + " (" + inf[0] + 'x' + inf[1] + "): muc 0 sau doi alpha (§3.6.2) khong khop runtimeMips[0] nao");
        continue;
      }
      matched.add(v);
      if(inf[2] != cube.mipSha1[v].length) {
        fail.accept("atlas bien the " + v + ": " + inf[2] + " muc mip, mong doi " + cube.mipSha1[v].length + " (toi 1x1)");
      }
      for(int lvl = 1; lvl < Math.min(inf[2], cube.mipSha1[v].length); lvl++) {
        if(!RefKey.sha1Hex(CaptureApi.GlContext.textureLevel(id, lvl)).equals(cube.mipSha1[v][lvl])) {
          fail.accept("atlas bien the " + v + " muc " + lvl + ": texel khac runtimeMips (§3.6.3)");
          break;
        }
      }
      if(inf[3] != org.lwjgl.opengl.GL11C.GL_NEAREST_MIPMAP_NEAREST || inf[4] != org.lwjgl.opengl.GL11C.GL_NEAREST
        || inf[5] != org.lwjgl.opengl.GL12C.GL_CLAMP_TO_EDGE || inf[6] != org.lwjgl.opengl.GL12C.GL_CLAMP_TO_EDGE) {
        fail.accept("atlas bien the " + v + ": MIN/MAG/WRAP = 0x" + Integer.toHexString(inf[3]) + "/0x" + Integer.toHexString(inf[4]) + "/0x"
          + Integer.toHexString(inf[5]) + "/0x" + Integer.toHexString(inf[6]) + " (§3.6.4)");
      }
    }
    if(matched.size() == cube.pngSha1.length && nFail[0] == 0) {
      info.accept("texture atlas: " + matched.size() + " texture, chuoi mip + bo loc dung §3.6");
    }
  }

  // ---------------------------------------------------------------- 43 mẫu vectors.json ở FULL (JVM con)

  /**
   * atlasUv giả, KHÁC NHAU ở từng mặt / góc / thành phần (trong [0, 1)) để so được thứ tự góc và chỉ số mặt của bộ ATLAS
   * (trước đây mọi góc = 0.5 nên đảo góc / lệch mặt không bị phát hiện). Góc thứ 4 của mặt tam giác = (0, 0) như bộ ghi (§3.5.2).
   */
  static float[] distinctAtlasUv(final List<List<RefBuild.Face>> faces) {
    final List<RefBuild.Face> tex = new ArrayList<>();
    for(final List<RefBuild.Face> fs : faces) {
      for(final RefBuild.Face f : fs) {
        if(f.textured) {
          tex.add(f);
        }
      }
    }
    final float[] uv = new float[8 * tex.size()];
    for(int g = 0; g < tex.size(); g++) {
      for(int j = 0; j < 8; j++) {
        uv[8 * g + j] = j / 2 < tex.get(g).vc ? (float)(((8 * g + j) * 0.6180339887498949 + 0.1) % 1.0) : 0.0f;
      }
    }
    return uv;
  }

  static void vecRuntime(final Opt o, final Scan s, final Report rep) throws Exception {
    vecRuntime(o, rep, "f", "vecrt", runtimeProps(o, true), cpRuntime(o));
  }

  /** Chạy JVM con 'vecrt' (43 mẫu vectors.json ở FULL, identity + 1 biến thể giả) trong o.work/dirName; lỗi ghi vào mục check. */
  static void vecRuntime(final Opt o, final Report rep, final String check, final String dirName, final List<String> baseProps, final String cp) throws Exception {
    final Path dir = o.work.resolve(dirName);
    deleteTree(dir);
    Files.createDirectories(dir.resolve("remaster").resolve("models"));
    Files.createDirectories(dir.resolve("remaster").resolve("textures"));
    final byte[] png = SynthModels.png(2, 2, new byte[] {10, 20, 30, (byte)255, 40, 50, 60, (byte)255, 70, 80, 90, (byte)128, 0, 0, 0, 0});
    final byte[] pngSha = RefKey.sha1(png);
    Files.write(dir.resolve("remaster").resolve("textures").resolve(RefKey.HEX.formatHex(pngSha) + ".png"), png);
    final List<String> keys = new ArrayList<>();
    final StringBuilder man = new StringBuilder();
    final Set<String> done = new HashSet<>();
    for(final Vec v : vectors(o)) {
      if(!done.add(v.modelKey)) {
        man.append(v.id).append("\tdup\n");
        continue;
      }
      final VecModel vm = vecModel(o, v);
      final TmdObjTable1c[] t = SynthModels.tables(vm.model);
      final RefLrm.Lrm l = RefLrm.identity(t);
      final List<List<RefBuild.Face>> faces = SynthModels.faces(vm.model);
      final RefLrm.Variant var = new RefLrm.Variant();
      var.png = pngSha;
      var.w = 2;
      var.h = 2;
      var.faceHash = RefFaceHash.generatorHashes(vm.vram, faces, vm.placed);
      var.n = var.faceHash.length;
      var.atlasUv = distinctAtlasUv(faces);
      l.variants = new RefLrm.Variant[] {var};
      Files.write(dir.resolve("remaster").resolve("models").resolve(v.modelKey + ".lrm"), RefLrm.write(l, false));
      keys.add(v.modelKey);
      man.append(v.id).append('\t').append(v.modelKey).append('\n');
    }
    Files.writeString(dir.resolve("remaster").resolve("index.tsv"), indexText((Iterable<String>)keys, "vectors"), StandardCharsets.UTF_8);
    Files.writeString(dir.resolve("remaster.properties"), "enabled=true\ntextures=hd\nlog=true\n", StandardCharsets.UTF_8);
    Files.writeString(dir.resolve("manifest.tsv"), man.toString(), StandardCharsets.UTF_8);
    final List<String> props = new ArrayList<>(baseProps);
    props.add("-Dscvi.remasterLog=true");
    final Map<String, Integer> rc = runJobs(o, List.of(new Job(dirName, dir, cp, props,
      List.of("vecrt", o.spec.toString(), dir.resolve("result.tsv").toString(), o.game.toString()), dir.resolve("run.log"))));
    if(rc.get(dirName) != 0) {
      rep.fail(check, "JVM con " + dirName + " rc=" + rc.get(dirName) + " (xem " + dir.resolve("run.log") + ')');
    }
    final String log = Files.isRegularFile(dir.resolve("run.log")) ? Files.readString(dir.resolve("run.log"), StandardCharsets.UTF_8) : "";
    useAfterDelete(dir.resolve("run.log"), x -> rep.fail(check, dirName + ": " + x));
    int ok = 0;
    int n = 0;
    for(final String l : Files.isRegularFile(dir.resolve("result.tsv")) ? Files.readAllLines(dir.resolve("result.tsv"), StandardCharsets.UTF_8) : List.<String>of()) {
      if(l.isBlank()) {
        continue;
      }
      n++;
      final String[] c = l.split("\t", -1);
      final Vec v = vectors(o).stream().filter(x -> x.id.equals(c[0])).findFirst().orElseThrow();
      final List<String> e = new ArrayList<>();
      if(!"ok".equals(c[1])) {
        e.add(c[1]);
      }
      boolean logged = false;
      for(final String line : log.split("\n")) {
        if(line.contains("scvi-remaster") && line.contains(v.vectorSha1)) {
          logged = true;
        }
      }
      if(!logged) {
        e.add("log khong co SHA-1 vec-to face-hash " + v.vectorSha1 + " (= vectors.json)");
      }
      if(e.isEmpty()) {
        ok++;
      } else {
        rep.fail(check, "vectors " + v.id + ": " + String.join("; ", e));
      }
    }
    if(n == 0) {
      rep.fail(check, dirName + ": khong co ket qua");
    }
    rep.info(check, "vectors.json o FULL (identity + 1 bien the gia, atlasUv khac nhau tung goc): " + ok + '/' + n
      + " mau ve ATLAS(0) dung tung float (LIVE b/d giu uv VRAM) + vec-to face-hash runtime trong log = Python");
  }

  /** Cảnh báo của SC khi dùng texture đã xoá (GlTexture.use: '... used after being deleted') trong log JVM con. */
  static void useAfterDelete(final Path log, final java.util.function.Consumer<String> fail) throws IOException {
    if(!Files.isRegularFile(log)) {
      return;
    }
    int n = 0;
    String first = null;
    for(final String l : Files.readAllLines(log, StandardCharsets.UTF_8)) {
      if(l.contains("used after being deleted")) {
        n++;
        if(first == null) {
          first = clean(l.trim());
        }
      }
    }
    if(n > 0) {
      fail.accept(n + " dong 'used after being deleted' (texture atlas bi xoa khi con dung?): " + first);
    }
  }

  static int childVec(final Path spec, final Path outFile, final Path game) throws Exception {
    final Opt o = new Opt();
    o.spec = spec;
    o.game = game;
    o.files = game.resolve("files");
    final List<String> out = new ArrayList<>();
    final Set<String> seen = new HashSet<>();
    for(final Vec v : vectors(o)) {
      if(!seen.add(v.modelKey)) {
        continue;
      }
      final StringBuilder err = new StringBuilder();
      // VRAM = đúng VRAM ảo của bộ sinh (khởi tạo 0, TIM đặt như export_tmd.py)
      final VecModel vm = vecModel(o, v);
      GameEngine.GPU.uploadData15(new Rect4i(0, 0, 1024, 512), vm.vram.px);
      final Model124 m = vm.model;
      final TmdObjTable1c[] t = SynthModels.tables(m);
      final String name = "field".equals(v.kind) ? "SobjModel (index 7)" : "CombatantModel (" + v.id + ')';
      // bộ ATLAS(0) mong đợi (tính TRƯỚC fromModel, từ file đã ghi): uv = I(atlasUv) cho mặt không LIVE, mặt LIVE a-c và LIVE d
      // (faceHash 0: mặt đọc ngoài TIM, bpp 3) giữ uv / tpage VRAM (§3.2.3, §3.4)
      final List<RefBuild.Part> wantAtlas = new ArrayList<>();
      try {
        final RefLrm.Lrm lrm = RefLrm.read(Files.readAllBytes(Path.of("remaster", "models", v.modelKey + ".lrm")), RefLrm.Runtime.of(t));
        final List<List<RefBuild.Face>> faces = SynthModels.faces(m);
        final boolean[] liveV = RefFaceHash.liveVariant(RefFaceHash.liveModel(m, faces), lrm.variants[0].faceHash);
        for(int i = 0; i < t.length; i++) {
          wantAtlas.add(RefBuild.remaster(t[i], faces.get(i), lrm.parts[i], 0, 0, lrm.variants[0].atlasUv, liveV, texBase(faces, i)));
        }
      } catch(final Throwable e) {
        err.append("bo kiem: khong dung duoc bo ATLAS mong doi: ").append(e).append("; ");
      }
      CaptureApi.reset();
      try {
        fromModel(name, m, 0, 0);
      } catch(final Throwable e) {
        err.append("fromModel nem ").append(e).append("; ");
      }
      final Set<CaptureApi.RecMesh> vram = Collections.newSetFromMap(new IdentityHashMap<>());
      for(final TmdObjTable1c x : t) {
        if(objOf(x) instanceof final MeshObj mo) {
          for(final var mesh : mo.meshes) {
            if(mesh instanceof final CaptureApi.RecMesh r) {
              vram.add(r);
            }
          }
        }
      }
      final boolean expectAtlas = m.clutAnimations_a4 == null;
      int atlasFrames = 0;
      int anyAtlasFrames = 0;
      // khung cuối mà MỌI phần vẽ lưới ngoài bộ VRAM (bỏ khung lẫn lúc chuyển trạng thái giữa các phần)
      List<List<List<CaptureApi.RecMesh>>> lastAtlas = null;
      final long end = System.nanoTime() + 4_000_000_000L;
      int frames = 0;
      while(System.nanoTime() < end && err.isEmpty()) {
        boolean nonVram = false;
        boolean allNonVram = true;
        int drawn = 0;
        final List<List<List<CaptureApi.RecMesh>>> parts = new ArrayList<>();
        try {
          for(final TmdObjTable1c x : t) {
            final List<List<CaptureApi.RecMesh>> layers = objOf(x) == null ? List.of() : renderLikeEngine(objOf(x));
            for(final List<CaptureApi.RecMesh> l : layers) {
              for(final CaptureApi.RecMesh r : l) {
                drawn++;
                nonVram |= !vram.contains(r);
                allNonVram &= !vram.contains(r);
              }
            }
            parts.add(layers);
          }
        } catch(final Throwable e) {
          err.append("render nem ").append(e).append("; ");
        }
        anyAtlasFrames += nonVram ? 1 : 0;
        if(nonVram && allNonVram && drawn > 0) {
          atlasFrames++;
          lastAtlas = parts;
        }
        frames++;
        if(atlasFrames >= 10 || !expectAtlas && frames > 100) {
          break;
        }
        Thread.sleep(5);
      }
      if(expectAtlas && atlasFrames == 0) {
        err.append("khong bao gio ve ATLAS(0) (hash luu = FaceHash cua TIM trong VRAM)");
      }
      if(expectAtlas && lastAtlas != null && wantAtlas.size() == t.length) {
        for(int i = 0; i < t.length; i++) {
          final List<String> e = RefBuild.compare(wantAtlas.get(i), drawnPart(lastAtlas.get(i), wantAtlas.get(i)), false);
          if(!e.isEmpty()) {
            err.append("ATLAS(0) phan ").append(i).append(": ").append(e.get(0)).append("; ");
            break;
          }
        }
      }
      if(!expectAtlas && anyAtlasFrames > 0) {
        err.append("clutAnimations: van ve ATLAS");
      }
      final String leak = cleanup(t, new ArrayList<>(CaptureApi.MESHES), new ArrayList<>(CaptureApi.TEXTURES));
      if(!"ok".equals(leak)) {
        err.append(" leak ").append(leak);
      }
      out.add(v.id + '\t' + (err.isEmpty() ? "ok" : clean(err.toString())));
    }
    Files.write(outFile, out, StandardCharsets.UTF_8);
    return 0;
  }

  // =====================================================================================================================
  // (g) tự kiểm bộ kiểm
  // =====================================================================================================================

  static void selftest(final Opt o, final Scan s, final SynthModels.Cube cube, final Map<String, Path> identity, final Map<Integer, Res> retail,
                       final Report rep, final boolean gl) throws Exception {
    rep.ran("g");
    // 1. so sánh chi tiết bắt đúng loại lỗi gieo (trên lưới sample_cube.json)
    final Map<String, String> want = Map.of("floatoff", "float", "droptri", "indexCount", "winding", "winding", "meshclass", "meshClass");
    for(final var e : want.entrySet()) {
      for(int i = 0; i < cube.vram.size(); i++) {
        final RefBuild.Part p = cube.vram.get(i);
        final List<String> err = RefBuild.compare(p, MockRuntime.inject(p, e.getKey()), false);
        if(err.size() != 1 || !err.get(0).startsWith(e.getValue() + ':')) {
          rep.fail("g", "compare: loi gieo " + e.getKey() + " phan " + i + " -> " + err + " (mong doi 1 loi '" + e.getValue() + "')");
        }
      }
    }
    if(!RefBuild.compare(cube.vram.get(0), cube.vram.get(0), false).isEmpty()) {
      rep.fail("g", "compare bao loi tren hai luoi giong nhau");
    }
    // 2. RefLrm phân loại đúng lỗi gieo (file sai / vẫn hợp lệ)
    final Model124 m = cube.model(cube.ccontainer, "slot0");
    final RefLrm.Runtime rt = RefLrm.Runtime.of(SynthModels.tables(m));
    final RefLrm.Lrm l = RefLrm.read(cube.lrm, rt);
    final List<String> invalid = List.of("magic", "version", "hdrzero", "partCount", "variantCount99", "level", "modelKey", "partKey", "partKeyRekey", "partsRekey",
      "srcFaceCount", "modeBad", "partZero", "pctLimit", "pctCount", "posNaN", "normNaN", "cornerPos", "cornerSrcRange", "nearBad", "roleBad", "cornerZero",
      "triIndex", "sizeBad", "tfc", "tfcHuge", "atlasNaN", "atlasRange", "deflateTrunc", "deflateTrail", "deflateNoFlag", "deflateBodySize", "append", "truncate",
      "bodySize", "generator");
    final List<String> valid = List.of("posFinite", "normFinite", "st", "near", "role", "faceHash", "faceHashZero", "atlasIn", "atlas4th", "deflate", "toMode0",
      "variantDrop", "variantDup", "pngSha", "sizeOther");
    final SplittableRandom r = new SplittableRandom(5);
    int ok = 0;
    for(final String k : invalid) {
      for(int rep2 = 0; rep2 < 3; rep2++) {
        try {
          RefLrm.read(Fuzz.mutate(cube.lrm, l, rt, k, r).data(), rt);
          rep.fail("g", "RefLrm chap nhan dot bien sai '" + k + "'");
        } catch(final RefLrm.Invalid e) {
          ok++;
        }
      }
    }
    for(final String k : valid) {
      for(int rep2 = 0; rep2 < 3; rep2++) {
        try {
          RefLrm.read(Fuzz.mutate(cube.lrm, l, rt, k, r).data(), rt);
          ok++;
        } catch(final RefLrm.Invalid e) {
          rep.fail("g", "RefLrm tu choi dot bien hop le '" + k + "': " + e.getMessage());
        }
      }
    }
    rep.info("g", "RefLrm phan loai " + ok + '/' + 3 * (invalid.size() + valid.size()) + " dot bien gieo dung (sai -> tu choi, hop le -> nhan)");
    // 3. so digest (b): sửa một digest -> bị bắt
    if(!retail.isEmpty()) {
      final Map<Integer, Res> fake = new HashMap<>(retail);
      final Res r0 = retail.values().stream().filter(x -> x.raw().length > 0 && "OK".equals(x.status())).findFirst().orElse(null);
      if(r0 != null) {
        final String[] raw = r0.raw().clone();
        raw[0] = "0000000000000000";
        fake.put(r0.id(), new Res(r0.id(), r0.status(), r0.cmp(), raw, r0.strict(), r0.norm(), 0, 0, "ok", "ok", "ok", ""));
        final Report tmp = new Report();
        tmp.quiet = true;
        checkSame("selftest", s.cases, retail, fake, tmp);
        if(tmp.fails.get("b").size() != 1) {
          rep.fail("g", "so digest (b): sua 1 digest -> bat " + tmp.fails.get("b").size() + " ca (mong doi 1)");
        }
      }
    }
    // 3b. log (d): hai dòng miss cho cùng một khoá -> bị bắt; một dòng -> không báo trùng
    if(!s.cases.isEmpty()) {
      final Case c0 = s.cases.stream().filter(Case::allowed).findFirst().orElseThrow();
      final String line = "LOG INFO  X: scvi-remaster: " + c0.name() + " key=" + c0.key() + " miss variant=vram\n";
      for(final int n : new int[] {1, 2}) {
        final Path fake = o.work.resolve("selftest_log_" + n + ".log");
        Files.writeString(fake, line.repeat(n), StandardCharsets.UTF_8);
        final Report tmp = new Report();
        tmp.quiet = true;
        checkKeyLog(o, s, fake, false, tmp);
        final boolean dup = tmp.fails.get("d").stream().anyMatch(x -> x.contains("nhieu dong miss/fallback"));
        if(dup != (n == 2)) {
          rep.fail("g", "kiem log (d): " + n + " dong miss cho mot khoa -> bao trung = " + dup);
        }
      }
      rep.info("g", "kiem log (d): 2 dong miss cho mot khoa bi bat, 1 dong khong bao trung");
    }
    // 4. MockRuntime gieo lỗi -> (c) bắt đúng loại, qua đủ đường ống JVM con
    final List<Case> sub = new ArrayList<>();
    for(final Case c : s.cases) {
      if(!"field".equals(c.group()) || sub.size() < 150) {
        sub.add(c);
      }
    }
    final Path subFile = o.work.resolve("cases_selftest.tsv");
    writeCases(subFile, sub);
    final Cond geo = conditions().stream().filter(c -> c.name().equals("geometry")).findFirst().orElseThrow();
    final Path dir = o.work.resolve("cond").resolve("selftest");
    setupCond(dir, geo, identity, cube);
    final List<Job> jobs = new ArrayList<>();
    final Map<String, String> faults = new LinkedHashMap<>();
    faults.put("none", "");
    faults.putAll(want);
    for(final String f : faults.keySet()) {
      final List<String> props = new ArrayList<>(List.of("-Dremastercheck.mock=true"));
      if(!"none".equals(f)) {
        props.add("-Dremastercheck.fault=" + f);
      }
      jobs.add(new Job("mock_" + f, dir, cpRetail(o), props, List.of("capture", subFile.toString(), o.work.resolve("out").resolve("mock_" + f + ".tsv").toString(), "identity"),
        o.work.resolve("out").resolve("mock_" + f + ".log")));
    }
    runJobs(o, jobs);
    for(final String f : faults.keySet()) {
      final Map<Integer, Res> res = readRes(o.work.resolve("out").resolve("mock_" + f + ".tsv"));
      final Report tmp = new Report();
      tmp.quiet = true;
      checkIdentity("mock_" + f, sub, retail, res, tmp);
      final List<String> fl = tmp.fails.get("c");
      if("none".equals(f)) {
        if(!fl.isEmpty()) {
          rep.fail("g", "MockRuntime khong loi: (c) van bao " + fl.size() + " loi: " + fl.get(0));
        }
        continue;
      }
      final String cat = faults.get(f);
      final boolean digestCaught = fl.size() == 1 && fl.get(0).contains("luoi khac luoi goc chuan hoa");
      final boolean catCaught = fl.size() == 1 && fl.get(0).contains(cat + ':');
      if(!digestCaught || !catCaught) {
        rep.fail("g", "MockRuntime " + f + ": (c) bao " + fl.size() + " ca " + (fl.isEmpty() ? "" : fl.get(0)) + " (mong doi dung 1 ca, digest khac + loai '" + cat + "')");
      } else {
        rep.info("g", "MockRuntime " + f + ": (c) bat dung 1 ca, loai '" + cat + "' (va digest khac luoi goc)");
      }
    }
    // 5. bộ kiểm file lỏng -> fuzz bắt
    fuzzAll(o, s, cube, identity, false, rep, "g", List.of("roleBad", "nearBad", "st", "role", "cornerZero", "triIndex"), 150);
    // 5b. cấp phát theo số đếm trước khi kiểm cắt cụt (MockRuntime eagerAlloc) + tfcHuge -> JVM fuzz (-XX:+ExitOnOutOfMemoryError)
    //     phải thoát rc=3; cùng bộ file không gieo lỗi -> rc=0, mọi đột biến 'ok'
    {
      final Path od = o.work.resolve("fuzz_selftest").resolve("oom");
      deleteTree(od);
      Files.createDirectories(od.resolve("remaster").resolve("models"));
      final SplittableRandom rr = new SplittableRandom(91);
      final StringBuilder man = new StringBuilder();
      final List<String> keys = new ArrayList<>();
      for(int j = 1; j <= 8; j++) {
        final Model124 mj = cube.model(cube.keyVariant(1000 + j), "slot0");
        final RefLrm.Runtime rtj = RefLrm.Runtime.of(SynthModels.tables(mj));
        final byte[] base = cube.lrmFor(mj);
        final Fuzz.Mutation mu = Fuzz.mutate(base, RefLrm.read(base, rtj), rtj, "tfcHuge", rr);
        final String key = RefKey.HEX.formatHex(rtj.modelKey());
        Files.write(od.resolve("remaster").resolve("models").resolve(key + ".lrm"), mu.data());
        keys.add(key);
        man.append(j).append("\tcube:").append(1000 + j).append('\t').append(key).append("\ttfcHuge\n");
      }
      Files.writeString(od.resolve("remaster").resolve("index.tsv"), indexText((Iterable<String>)keys, "oom"), StandardCharsets.UTF_8);
      Files.writeString(od.resolve("remaster.properties"), "enabled=true\ntextures=retail\nlog=true\n", StandardCharsets.UTF_8);
      Files.writeString(od.resolve("manifest.tsv"), man.toString(), StandardCharsets.UTF_8);
      final List<Job> oj = new ArrayList<>();
      for(final String f : List.of("eagerAlloc", "none")) {
        final List<String> props = new ArrayList<>(List.of("-Dremastercheck.mock=true", "-XX:+ExitOnOutOfMemoryError"));
        if(!"none".equals(f)) {
          props.add("-Dremastercheck.fault=" + f);
        }
        oj.add(new Job("oom_" + f, od, cpRetail(o), props,
          List.of("fuzz", od.resolve("manifest.tsv").toString(), "-", od.resolve("result_" + f + ".tsv").toString(), o.spec.toString()), od.resolve("run_" + f + ".log")));
      }
      final Map<String, Integer> orc = runJobs(o, oj);
      final Path okRes = od.resolve("result_none.tsv");
      final long okRows = Files.isRegularFile(okRes) ? Files.readAllLines(okRes, StandardCharsets.UTF_8).stream().filter(x -> x.endsWith("\tok")).count() : 0;
      if(orc.get("oom_eagerAlloc") != 3) {
        rep.fail("g", "MockRuntime eagerAlloc + tfcHuge: JVM fuzz rc=" + orc.get("oom_eagerAlloc") + " (mong doi 3 = OutOfMemoryError, khong bi catch nuot)");
      } else if(orc.get("oom_none") != 0 || okRows != 8) {
        rep.fail("g", "MockRuntime khong gieo loi + tfcHuge: rc=" + orc.get("oom_none") + ", " + okRows + "/8 dot bien ok");
      } else {
        rep.info("g", "MockRuntime eagerAlloc: tfcHuge -> OutOfMemoryError -> JVM fuzz rc=3 (bat duoc); khong gieo loi -> rc=0, 8/8 ok");
      }
    }
    // 6. (f): MockRuntime bỏ LIVE -> TIM E phải trượt; mip không làm tròn -> so texel mip phải bắt
    if(gl) {
      final Path cr = o.work.resolve("cube_selftest");
      deleteTree(cr);
      final List<Job> cj = new ArrayList<>();
      final Map<String, String[]> cf = new LinkedHashMap<>();
      cf.put("nolive", new String[] {"E", "trang thai ve bo VRAM"});
      cf.put("mipround", new String[] {"A", "texel khac runtimeMips"});
      cf.put("bpp3hash", new String[] {"tw", "mat bpp 3 phai ghi 0"});
      for(final var e : cf.entrySet()) {
        final Scenario sc = scenarios().stream().filter(x -> x.id().equals(e.getValue()[0])).findFirst().orElseThrow();
        final Path d = cr.resolve(e.getKey());
        prepareCube(o, cube, sc, d);
        final List<String> props = new ArrayList<>(List.of("-Dremastercheck.mock=true", "-Dremastercheck.gl=true", "-Dremastercheck.fault=" + e.getKey()));
        props.addAll(sc.dprops());
        cj.add(new Job("cube_g_" + e.getKey(), d, cpRetail(o), props, List.of("cube", sc.id(), o.spec.toString(), d.resolve("result.txt").toString()), d.resolve("run.log")));
      }
      runJobs(o, cj);
      for(final var e : cf.entrySet()) {
        final Path res = cr.resolve(e.getKey()).resolve("result.txt");
        String txt = Files.isRegularFile(res) ? Files.readString(res, StandardCharsets.UTF_8) : "";
        // kiểm log véc-tơ face-hash (phần của 'all', không nằm trong result.txt)
        final Scenario sc = scenarios().stream().filter(x -> x.id().equals(e.getValue()[0])).findFirst().orElseThrow();
        final List<String> vf = new ArrayList<>();
        vecLogCheck(sc, cube, Files.isRegularFile(res) ? Files.readAllLines(res, StandardCharsets.UTF_8) : List.of(), cr.resolve(e.getKey()).resolve("run.log"),
          x -> vf.add("FAIL " + x), x -> { });
        txt += String.join("\n", vf);
        if(!txt.contains("FAIL") || !txt.contains(e.getValue()[1])) {
          rep.fail("g", "MockRuntime " + e.getKey() + ": kich ban sample_cube " + e.getValue()[0] + " khong bat '" + e.getValue()[1] + "': " + clean(txt));
        } else {
          rep.info("g", "MockRuntime " + e.getKey() + ": (f) kich ban " + e.getValue()[0] + " bat '" + e.getValue()[1] + "'");
        }
      }
      // 7. vòng đời 'share': MockRuntime xoá atlas ngay ở lần trả tham chiếu đầu tiên (eagerfree) -> phải bị bắt
      {
        final Path d = cr.resolve("share_eagerfree");
        final Job j = shareJob(o, cube, d, "share_g_eagerfree", List.of("-Dremastercheck.mock=true", "-Dremastercheck.gl=true",
          "-Dremastercheck.fault=eagerfree"), cpRetail(o));
        final Map<String, Integer> rc = runJobs(o, List.of(j));
        final List<String> f = new ArrayList<>();
        shareResult(d, rc.get(j.name()), "share", f::add, x -> { });
        if(f.stream().noneMatch(x -> x.contains("atlas dung chung"))) {
          rep.fail("g", "MockRuntime eagerfree: kich ban share khong bat 'xoa atlas dung chung': " + f);
        } else {
          rep.info("g", "MockRuntime eagerfree: (f) kich ban share bat 'xoa atlas dung chung'" + (f.stream().anyMatch(x -> x.contains("used after being deleted"))
            ? " va 'used after being deleted'" : ""));
        }
      }
      // 8. vectors ở FULL: MockRuntime đảo góc 0 / 1 của atlasUv trong bộ ATLAS (atlascorner) -> so float bộ ATLAS phải bắt,
      //    và chỉ loại lỗi đó (atlasUv giả khác nhau từng góc; với atlasUv hằng số lỗi này lọt)
      {
        final Report tmp = new Report();
        tmp.quiet = true;
        vecRuntime(o, tmp, "f", "vecrt_selftest", List.of("-Dremastercheck.mock=true", "-Dremastercheck.gl=true", "-Dremastercheck.fault=atlascorner"), cpRetail(o));
        final List<String> fl = tmp.fails.getOrDefault("f", List.of());
        final long content = fl.stream().filter(x -> x.contains("ATLAS(0) phan")).count();
        if(content == 0 || content != fl.size()) {
          rep.fail("g", "MockRuntime atlascorner: vecrt bat " + content + '/' + fl.size() + " loi so float ATLAS(0)" + (fl.isEmpty() ? "" : ": " + fl.get(0)));
        } else {
          rep.info("g", "MockRuntime atlascorner: (f) vecrt bat " + content + " mau ve ATLAS(0) sai float (dao goc atlasUv), khong bao nham loai khac");
        }
      }
    }
  }
}
