package scvi.remastercheck;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import legend.core.gte.ModelPart10;
import legend.core.renderer.Translucency;
import legend.core.renderer.VertexOrder;
import legend.game.Models;
import legend.game.tmd.TmdObjTable1c;
import legend.game.tmd.UvAdjustmentMetrics14;
import legend.game.types.CContainer;
import legend.game.types.ClutAnimations;
import legend.game.types.Model124;
import legend.game.unpacker.FileData;

import javax.annotation.Nullable;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.zip.CRC32;
import java.util.zip.Deflater;

/**
 * Dựng Model124 như game (để gọi TmdObjLoader.fromModel ngoài game) và mô hình tổng hợp sample_cube (spec/sample_cube.*).
 * <ul>
 *   <li>{@link #model}: CContainer(tên, FileData) -> ModelPart10[nobj] (tmd_08 = objTable[i]) -> uvAdjustments_9d ->
 *       animationMetrics_d0 = CContainer +8 (mục 0..6, Models.java:87-93) -> clutAnimations_a4 như sc-vi SMap.modelLoaded (chỉ
 *       mô hình trường có CContainer +4 != 0) -> Models.adjustModelUvs. Mỗi lần gọi đọc từ BẢN SAO byte (TmdObjTable1c ghi đè
 *       16 bit thấp header và UvAdjust ghi đè uv/clut/tpage tại chỗ).</li>
 *   <li>{@link #uv}: tên chế độ UvAdjust -> UvAdjustmentMetrics14 (slot0 = ô sobj 0 (576, 256); slot1 / slot5 = vramSlots của
 *       trận; wmap = (1, 608, 256) = WmapStatics.tmdUvAdjustmentMetrics_800eee48[1]; png = PNG; none = NONE).</li>
 *   <li>{@link Cube}: đọc sample_cube.json (byte CContainer + TIM A-E dạng hex, khoá, hash, lưới mong đợi) và sample_cube.lrm;
 *       {@link Cube#keyVariant}: biến thể khoá (dịch đỉnh 0 của phần 1 thêm j đơn vị) để mỗi đột biến fuzz có khoá riêng.</li>
 *   <li>{@link #png}: PNG RGBA 8 bit tối giản (cho biến thể giả của mô hình thật, kiểm FaceHash runtime).</li>
 * </ul>
 */
public final class SynthModels {
  private SynthModels() { }

  public static UvAdjustmentMetrics14 uv(final String mode) {
    return switch(mode) {
      case "slot0" -> new UvAdjustmentMetrics14(1, 576, 256);
      case "slot1" -> Models.vramSlots_8005027c[1];
      case "slot5" -> Models.vramSlots_8005027c[5];
      // = WmapStatics.tmdUvAdjustmentMetrics_800eee48[1] (không nạp WmapStatics: khởi tạo tĩnh của nó kéo LodMod / GameEngine thật)
      case "wmap" -> new UvAdjustmentMetrics14(1, 608, 256);
      case "png" -> UvAdjustmentMetrics14.PNG;
      case "none" -> UvAdjustmentMetrics14.NONE;
      default -> throw new IllegalArgumentException("uv " + mode);
    };
  }

  /** Lọc như keyscan.py: +0 = offset TMD hợp lệ, id 0x41, flags & 3 = 0, 1 <= nobj <= 64. */
  public static boolean looksLikeModel(final byte[] b) {
    if(b.length < 16) {
      return false;
    }
    final ByteBuffer d = ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN);
    final int tw = d.getInt(0);
    if(tw < 0 || tw + 12 > b.length || d.getInt(tw) != 0x41) {
      return false;
    }
    final int flags = d.getInt(tw + 4);
    final int nobj = d.getInt(tw + 8);
    return (flags & 3) == 0 && nobj > 0 && nobj <= 64;
  }

  public static Model124 model(final String label, final byte[] bytes, final UvAdjustmentMetrics14 uv, final boolean fieldClutAnim) {
    final CContainer cc = new CContainer(label, new FileData(bytes.clone()));
    final Model124 m = new Model124(label);
    final TmdObjTable1c[] tables = cc.tmdPtr_00.tmd.objTable;
    m.modelParts_00 = new ModelPart10[tables.length];
    for(int i = 0; i < tables.length; i++) {
      m.modelParts_00[i] = new ModelPart10();
      m.modelParts_00[i].tmd_08 = tables[i];
    }
    m.uvAdjustments_9d = uv;
    if(cc.ptr_08 != null) {
      m.ptr_a8 = cc.ptr_08;
      for(int i = 0; i < 7; i++) {
        m.animationMetrics_d0[i] = cc.ptr_08._00[i];
      }
    }
    if(fieldClutAnim && cc.clutAnimations_04 != null) {
      // sc-vi SMap.modelLoaded (SMap.java:1320-1350)
      final ClutAnimations a = new ClutAnimations();
      m.clutAnimations_a4 = a;
      a.source_00 = cc.clutAnimations_04;
      for(int i = 0; i < 4; i++) {
        a.clutAnimation_20[i] = a.source_00.clutAnimation_00[i];
        if(a.clutAnimation_20[i] == null) {
          a.used_04[i] = false;
        } else {
          a.dataIndex_08[i] = 0;
          a.frameIndex_10[i] = 0;
          a.clutIndex_18[i] = a.clutAnimation_20[i].clutIndex_02;
          a.used_04[i] = a.clutIndex_18[i] != -1;
        }
      }
    }
    Models.adjustModelUvs(m);
    return m;
  }

  public static TmdObjTable1c[] tables(final Model124 m) {
    final TmdObjTable1c[] t = new TmdObjTable1c[m.modelParts_00.length];
    for(int i = 0; i < t.length; i++) {
      t[i] = m.modelParts_00[i].tmd_08;
    }
    return t;
  }

  public static List<List<RefBuild.Face>> faces(final Model124 m) {
    final List<List<RefBuild.Face>> out = new ArrayList<>();
    for(final ModelPart10 p : m.modelParts_00) {
      out.add(RefBuild.decode(p.tmd_08));
    }
    return out;
  }

  // ---------------------------------------------------------------- PNG tối giản

  public static byte[] png(final int w, final int h, final byte[] rgba) {
    final ByteArrayOutputStream raw = new ByteArrayOutputStream();
    for(int y = 0; y < h; y++) {
      raw.write(0);
      raw.write(rgba, y * w * 4, w * 4);
    }
    final ByteArrayOutputStream out = new ByteArrayOutputStream();
    out.writeBytes(new byte[] {(byte)0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'});
    final ByteBuffer ihdr = ByteBuffer.allocate(13).putInt(w).putInt(h).put((byte)8).put((byte)6).put((byte)0).put((byte)0).put((byte)0);
    chunk(out, "IHDR", ihdr.array());
    final Deflater d = new Deflater(9);
    d.setInput(raw.toByteArray());
    d.finish();
    final ByteArrayOutputStream z = new ByteArrayOutputStream();
    final byte[] buf = new byte[8192];
    while(!d.finished()) {
      z.write(buf, 0, d.deflate(buf));
    }
    d.end();
    chunk(out, "IDAT", z.toByteArray());
    chunk(out, "IEND", new byte[0]);
    return out.toByteArray();
  }

  private static void chunk(final ByteArrayOutputStream out, final String type, final byte[] payload) {
    final byte[] t = type.getBytes(StandardCharsets.US_ASCII);
    out.writeBytes(ByteBuffer.allocate(4).putInt(payload.length).array());
    out.writeBytes(t);
    out.writeBytes(payload);
    final CRC32 crc = new CRC32();
    crc.update(t);
    crc.update(payload);
    out.writeBytes(ByteBuffer.allocate(4).putInt((int)crc.getValue()).array());
  }

  // ---------------------------------------------------------------- sample_cube

  public static final class Cube {
    public final byte[] ccontainer;
    public final Map<String, byte[]> tims = new HashMap<>();
    public final byte[] lrm;
    public final String modelKey;
    public final List<String> partKeys = new ArrayList<>();
    public final int[] srcFaceCount;
    public final int texturedFaceCount;
    public final Map<String, int[]> runtimeHashes = new HashMap<>();
    public final Map<String, String> vectorSha1 = new HashMap<>();
    public final int[][] storedHashes;
    public final Map<String, Integer> expectedVariant = new HashMap<>();
    /** [biến thể] -> {png sha1, w, h}. */
    public final String[] pngSha1;
    public final int[] pngW;
    public final int[] pngH;
    /** [biến thể][mức] -> sha1 RGBA đã đổi (§3.6.2-3). */
    public final String[][] mipSha1;
    public final int[][][] mipSize;
    public final List<RefBuild.Part> retail = new ArrayList<>();
    public final List<RefBuild.Part> vram = new ArrayList<>();
    /** [biến thể] -> phần. */
    public final List<List<RefBuild.Part>> atlas = new ArrayList<>();
    /** sha1 f32 LE / u32 LE ghi trong JSON, theo cùng thứ tự lưới (để kiểm chính bộ đọc JSON). */
    public final List<String> meshSha1 = new ArrayList<>();
    public final List<Integer> liveModel = new ArrayList<>();
    public final String name;
    public final String uvMode = "slot0";

    private Cube(final Path specDir) throws IOException {
      final JsonObject j = JsonParser.parseString(Files.readString(specDir.resolve("sample_cube.json"), StandardCharsets.UTF_8)).getAsJsonObject();
      this.name = j.getAsJsonObject("runtime").get("name").getAsString();
      final JsonObject files = j.getAsJsonObject("files");
      this.ccontainer = RefKey.HEX.parseHex(files.getAsJsonObject("ccontainer").get("hex").getAsString());
      for(final Map.Entry<String, JsonElement> e : files.getAsJsonObject("tims").entrySet()) {
        this.tims.put(e.getKey(), RefKey.HEX.parseHex(e.getValue().getAsJsonObject().get("hex").getAsString()));
      }
      this.lrm = Files.readAllBytes(specDir.resolve("sample_cube.lrm"));
      final JsonObject pngs = files.getAsJsonObject("pngs");
      this.pngSha1 = new String[pngs.size()];
      this.pngW = new int[pngs.size()];
      this.pngH = new int[pngs.size()];
      for(int v = 0; v < pngs.size(); v++) {
        final JsonObject p = pngs.getAsJsonObject(String.valueOf(v));
        this.pngSha1[v] = p.get("sha1").getAsString();
        this.pngW[v] = p.get("w").getAsInt();
        this.pngH[v] = p.get("h").getAsInt();
      }
      final JsonObject keys = j.getAsJsonObject("keys");
      this.modelKey = keys.get("modelKey").getAsString();
      keys.getAsJsonArray("partKeys").forEach(e -> this.partKeys.add(e.getAsString()));
      this.srcFaceCount = ints(j.getAsJsonArray("srcFaceCount"));
      this.texturedFaceCount = j.get("texturedFaceCount").getAsInt();
      for(final Map.Entry<String, JsonElement> e : j.getAsJsonObject("faceHashes").getAsJsonObject("runtime").entrySet()) {
        this.runtimeHashes.put(e.getKey(), hexInts(e.getValue().getAsJsonArray()));
      }
      final JsonArray stored = j.getAsJsonObject("faceHashes").getAsJsonArray("stored");
      this.storedHashes = new int[stored.size()][];
      for(int v = 0; v < stored.size(); v++) {
        this.storedHashes[v] = hexInts(stored.get(v).getAsJsonArray());
      }
      for(final Map.Entry<String, JsonElement> e : j.getAsJsonObject("faceHashVectorSha1").entrySet()) {
        this.vectorSha1.put(e.getKey(), e.getValue().getAsString());
      }
      for(final Map.Entry<String, JsonElement> e : j.getAsJsonObject("verify").getAsJsonObject("expected").entrySet()) {
        this.expectedVariant.put(e.getKey(), e.getValue().isJsonNull() ? -1 : e.getValue().getAsInt());
      }
      j.getAsJsonObject("live").getAsJsonArray("model").forEach(e -> this.liveModel.add(e.getAsInt()));
      final JsonArray atl = j.getAsJsonArray("atlas");
      this.mipSha1 = new String[atl.size()][];
      this.mipSize = new int[atl.size()][][];
      for(int v = 0; v < atl.size(); v++) {
        final JsonArray mips = atl.get(v).getAsJsonObject().getAsJsonArray("runtimeMips");
        this.mipSha1[v] = new String[mips.size()];
        this.mipSize[v] = new int[mips.size()][];
        for(int l = 0; l < mips.size(); l++) {
          final JsonObject m = mips.get(l).getAsJsonObject();
          this.mipSha1[v][l] = m.get("sha1").getAsString();
          this.mipSize[v][l] = new int[] {m.get("w").getAsInt(), m.get("h").getAsInt()};
        }
      }
      final JsonObject meshes = j.getAsJsonObject("meshes");
      meshes.getAsJsonArray("retail").forEach(e -> this.retail.add(this.part(e.getAsJsonObject())));
      meshes.getAsJsonArray("vram").forEach(e -> this.vram.add(this.part(e.getAsJsonObject())));
      for(final JsonElement v : meshes.getAsJsonArray("atlas")) {
        final List<RefBuild.Part> parts = new ArrayList<>();
        v.getAsJsonArray().forEach(e -> parts.add(this.part(e.getAsJsonObject())));
        this.atlas.add(parts);
      }
    }

    private RefBuild.Part part(final JsonObject p) {
      final List<RefBuild.MeshData> meshes = new ArrayList<>();
      for(final JsonElement e : p.getAsJsonArray("meshes")) {
        final JsonObject m = e.getAsJsonObject();
        final JsonArray va = m.getAsJsonArray("vertices");
        final float[] v = new float[va.size()];
        for(int i = 0; i < v.length; i++) {
          v[i] = (float)va.get(i).getAsDouble();
        }
        final int[] idx = ints(m.getAsJsonArray("indices"));
        final JsonElement tl = m.get("translucency");
        meshes.add(new RefBuild.MeshData(null, m.get("textured").getAsBoolean(), m.get("translucent").getAsBoolean(),
          tl == null || tl.isJsonNull() ? null : Translucency.valueOf(tl.getAsString()), VertexOrder.TRIANGLES_ADJACENCY.name(), RefBuild.OVERLOAD,
          RefBuild.ATTRS, v, idx));
        this.meshSha1.add(m.get("verticesSha1").getAsString() + '/' + m.get("indicesSha1").getAsString());
      }
      return new RefBuild.Part(true, p.get("backfaceCulling").getAsBoolean(), meshes);
    }

    public static Cube load(final Path specDir) throws IOException {
      return new Cube(specDir);
    }

    /** Lỗi tự kiểm của bộ đọc JSON: sha1 f32/u32 của lưới đọc được phải trùng sha1 ghi trong JSON. */
    public List<String> selfCheck() {
      final List<String> err = new ArrayList<>();
      final List<RefBuild.MeshData> all = new ArrayList<>();
      for(final RefBuild.Part p : this.retail) {
        all.addAll(p.meshes());
      }
      for(final RefBuild.Part p : this.vram) {
        all.addAll(p.meshes());
      }
      for(final List<RefBuild.Part> v : this.atlas) {
        for(final RefBuild.Part p : v) {
          all.addAll(p.meshes());
        }
      }
      for(int i = 0; i < all.size(); i++) {
        final String got = RefKey.sha1Hex(RefBuild.floatsLE(all.get(i).v())) + '/' + RefKey.sha1Hex(RefBuild.intsLE(all.get(i).idx()));
        if(!got.equals(this.meshSha1.get(i))) {
          err.add("sample_cube.json luoi " + i + ": sha1 " + got + " != " + this.meshSha1.get(i));
        }
      }
      return err;
    }

    /**
     * CContainer có khoá khác (đỉnh 0 của phần cuối dịch x thêm j); j = 0 -> bản gốc. Byte TMD: +0 = offset TMD; TMD = id u32,
     * flags u32, nobj u32, bảng obj 0x1c byte/phần (vert_top tương đối với đầu bảng obj).
     */
    public byte[] keyVariant(final int j) {
      final byte[] b = this.ccontainer.clone();
      if(j == 0) {
        return b;
      }
      final ByteBuffer d = ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN);
      final int tmd = d.getInt(0);
      final int nobj = d.getInt(tmd + 8);
      final int objBase = tmd + 12;
      final int rec = objBase + (nobj - 1) * 0x1c;
      final int vtop = objBase + d.getInt(rec);
      d.putShort(vtop, (short)(d.getShort(vtop) + j));
      return b;
    }

    /** sample_cube.lrm với modelKey / partKey đổi theo CContainer biến thể (thân giữ nguyên). */
    public byte[] lrmFor(final Model124 m) throws RefLrm.Invalid {
      final RefLrm.Lrm l = RefLrm.read(this.lrm, null);
      final TmdObjTable1c[] t = tables(m);
      final byte[][] pks = RefKey.partKeys(t);
      for(int i = 0; i < pks.length; i++) {
        l.parts[i].key = pks[i];
      }
      l.modelKey = RefKey.modelKey(pks);
      return RefLrm.write(l, false);
    }

    public Model124 model(final byte[] cc, final String uvMode) {
      return SynthModels.model("sample_cube", cc, uv(uvMode), true);
    }

    @Nullable
    public byte[] pngBytes(final Path synthDir, final int v) throws IOException {
      final Path p = synthDir.resolve("synth").resolve("atlas_" + v + ".png");
      return Files.isRegularFile(p) ? Files.readAllBytes(p) : null;
    }
  }

  static int[] ints(final JsonArray a) {
    final int[] out = new int[a.size()];
    for(int i = 0; i < out.length; i++) {
      out[i] = a.get(i).getAsInt();
    }
    return out;
  }

  static int[] hexInts(final JsonArray a) {
    final int[] out = new int[a.size()];
    for(int i = 0; i < out.length; i++) {
      out[i] = (int)Long.parseLong(a.get(i).getAsString(), 16);
    }
    return out;
  }
}
