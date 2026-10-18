package scvi.remastercheck;

import legend.core.GameEngine;
import legend.core.gte.ModelPart10;
import legend.core.renderer.BufferUsage;
import legend.core.renderer.Mesh;
import legend.core.renderer.Obj;
import legend.core.renderer.Texture;
import legend.core.renderer.TextureDataFormat;
import legend.core.renderer.TextureDataType;
import legend.core.renderer.TextureInternalFormat;
import legend.core.renderer.Translucency;
import legend.core.renderer.VertexOrder;
import legend.game.tmd.TmdMeshObj;
import legend.game.tmd.TmdObjLoader;
import legend.game.tmd.TmdObjTable1c;
import legend.game.types.Model124;

import javax.annotation.Nullable;
import java.io.IOException;
import java.io.Reader;
import java.lang.reflect.Field;
import java.nio.ByteBuffer;
import java.nio.IntBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Properties;
import java.util.Set;

/**
 * Runtime GIẢ (tham chiếu Java thứ hai), viết theo SPEC §3.4-§3.7, §4, §5 — để chạy TOÀN BỘ đường ống kiểm khi chưa có R1
 * (build.ps1 -Mock) và để tự kiểm (g). Có cả đường FULL: bộ ATLAS mỗi biến thể, atlas PNG (stb) đổi alpha §3.6.2 + mip CPU
 * §3.6.3 + tải mức 1..n bằng glTexImage2D (§3.6.4, cần ngữ cảnh GL của CaptureApi), trạng thái chung mỗi mô hình PENDING /
 * ATLAS(v) với FaceVerify (RefFaceHash trên GPU.getPixel15) ~ mỗi 4 khung trong 2 s rồi ~ mỗi 1 s, kiểm lại mỗi 1 s ở ATLAS,
 * khoá VRAM sau 3 lần ATLAS -> PENDING, log véc-tơ face-hash runtime (bpp 3 ghi 0) khi -Dscvi.remasterLog=true.
 * -Dremastercheck.fault gieo lỗi:
 * <ul>
 *   <li>floatoff: lật bit thấp của một float (đỉnh 0, thành phần 0, lưới 0 của phần mode 1 đầu tiên);</li>
 *   <li>droptri: bỏ tam giác cuối của lưới đó;</li>
 *   <li>winding: đảo chiều tam giác đầu (đổi đỉnh 2 và 3 của [a, a, b, a, c, a]);</li>
 *   <li>meshclass: đổi lớp (cờ textured) của lưới đó;</li>
 *   <li>lax:&lt;luật&gt;: bộ kiểm file bỏ qua một luật §3.5.4 (role, zero, near, triOrder, atlasUv) -> fuzz phải bắt;</li>
 *   <li>nolive: bỏ LIVE a-c (§3.4) khi xác minh -> sample_cube TIM E phải trượt (f bắt);</li>
 *   <li>mipround: mip lấy trung bình không làm tròn (§3.6.3) -> so texel mip của (f) phải bắt;</li>
 *   <li>bpp3hash: véc-tơ face-hash in ra ghi 1 (thay vì 0) cho mặt bpp 3 -> kiểm log của (f) (kịch bản tw, ghi đè PNG) phải bắt;</li>
 *   <li>eagerAlloc: cấp phát theo texturedFaceCount trong file trước khi kiểm cắt cụt -> fuzz tfcHuge phải làm JVM thoát rc=3;</li>
 *   <li>eagerfree: AtlasCache xoá texture ngay ở lần trả tham chiếu đầu tiên -> kịch bản vòng đời 'share' của (f) phải bắt;</li>
 *   <li>atlascorner: bộ ATLAS dùng atlasUv đã đổi chỗ góc 0 và góc 1 -> so float bộ ATLAS của mẫu vectors (f) phải bắt.</li>
 * </ul>
 * Atlas dùng chung giữa các mô hình qua {@link AtlasCacheMock} (một texture mỗi pngSha1, đếm tham chiếu, §4.2).
 * Mỗi lỗi lưới chỉ gieo vào MỘT mô hình mỗi JVM (mô hình trúng đầu tiên), như "một float sai" của đề.
 */
public final class MockRuntime {
  private MockRuntime() { }

  private static final String FAULT = System.getProperty("remastercheck.fault", "");
  private static final Set<String> MESH_FAULTS = Set.of("floatoff", "droptri", "winding", "meshclass");
  private static boolean faultUsed;
  private static Field objField;

  static Field objField() throws NoSuchFieldException {
    if(objField == null) {
      objField = TmdObjTable1c.class.getDeclaredField("obj");
      objField.setAccessible(true);
    }
    return objField;
  }

  // ---------------------------------------------------------------- cấu hình (§3.7)

  private static String modeCache;
  private static Set<String> indexCache;
  private static boolean indexRead;
  private static Properties propsCache;

  static Properties props() {
    if(propsCache == null) {
      propsCache = new Properties();
      final Path p = Path.of("remaster.properties");
      if(Files.isRegularFile(p)) {
        try(final Reader r = Files.newBufferedReader(p, StandardCharsets.UTF_8)) {
          propsCache.load(r);
        } catch(final IOException e) {
          propsCache = null;
          return new Properties();
        }
      } else {
        propsCache.setProperty("__missing", "1");
      }
    }
    return propsCache;
  }

  /** off | geometry | full: -Dscvi.remaster, rồi remaster.properties (enabled thiếu -> false, textures thiếu -> hd), rồi tắt. */
  static String mode() {
    if(modeCache == null) {
      final String d = System.getProperty("scvi.remaster");
      if(d != null) {
        modeCache = d.trim().toLowerCase();
      } else if(props().containsKey("__missing") || !"true".equals(props().getProperty("enabled", "false").trim())) {
        modeCache = "off";
      } else {
        modeCache = "retail".equals(props().getProperty("textures", "hd").trim()) ? "geometry" : "full";
      }
    }
    return modeCache;
  }

  static boolean logEnabled() {
    return Boolean.getBoolean("scvi.remasterLog") || "true".equals(props().getProperty("log", "false").trim());
  }

  /** Khoá có trong index.tsv hợp lệ (§3.7); index thiếu / sai định dạng -> null (tắt). Đọc một lần (JVM thử không đổi engine state). */
  static Set<String> index() {
    if(!indexRead) {
      indexCache = readIndex();
      indexRead = true;
    }
    return indexCache;
  }

  static Set<String> readIndex() {
    final Path p = Path.of("remaster", "index.tsv");
    try {
      final String text = new String(Files.readAllBytes(p), StandardCharsets.UTF_8);
      final String[] lines = text.split("\n", -1);
      if(!"LRMINDEX\t1".equals(lines[0])) {
        return null;
      }
      final Set<String> keys = new HashSet<>();
      for(int i = 1; i < lines.length; i++) {
        if(lines[i].isEmpty()) {
          continue;
        }
        final String[] cols = lines[i].split("\t", -1);
        if(cols.length != 3 || !cols[0].matches("[0-9a-f]{40}") || !cols[1].equals("models/" + cols[0] + ".lrm") || cols[2].contains("\r")) {
          return null;
        }
        keys.add(cols[0]);
      }
      return keys;
    } catch(final IOException e) {
      return null;
    }
  }

  private static final Set<String> LOGGED = new HashSet<>();

  /** Dòng log §4.4 (một dòng mỗi khoá). */
  static void log(final String name, final String key, final String what) {
    if(logEnabled() && LOGGED.add(key)) {
      System.out.println("scvi-remaster: " + name + " key=" + key + ' ' + what);
    }
  }

  // ---------------------------------------------------------------- fromModel (§4.1, §4.2)

  record Found(RefLrm.Lrm lrm, String key) { }

  public static void fromModel(final String name, final Model124 model, final int tw, final int th) {
    Found found = null;
    try {
      found = find(name, model);
    } catch(final Throwable t) {
      found = null;
    }
    Shared shared = null;
    final boolean atlas = found != null && "full".equals(mode()) && tw == 0 && th == 0 && model.clutAnimations_a4 == null
      && found.lrm().variants.length > 0 && CaptureApi.glTextures();
    if(found != null) {
      shared = new Shared(name, found.key(), model, found.lrm(), atlas);
      log(name, found.key(), "hit variant=" + (atlas ? "pending" : "vram"));
    }
    int texBase = 0;
    for(int i = 0; i < model.modelParts_00.length; i++) {
      final ModelPart10 part = model.modelParts_00[i];
      try {
        final Obj old = (Obj)objField().get(part.tmd_08);
        if(old != null) {
          old.delete();
        }
        Obj o = null;
        final List<RefBuild.Face> faces = RefBuild.decode(part.tmd_08);
        if(found != null && found.lrm().parts[i].mode == 1) {
          o = build(name + " part " + i, part.tmd_08, faces, found.lrm().parts[i], tw, th, shared, texBase);
        }
        if(o == null) {
          o = TmdObjLoader.fromObjTable(name + " part " + i, part.tmd_08, 0, tw, th);
        }
        for(final RefBuild.Face f : faces) {
          texBase += f.textured ? 1 : 0;
        }
        objField().set(part.tmd_08, o);
      } catch(final ReflectiveOperationException e) {
        throw new RuntimeException(e);
      }
    }
  }

  static Found find(final String name, final Model124 model) throws IOException {
    if("off".equals(mode())) {
      return null;
    }
    if(!name.startsWith("CombatantModel (") && !name.startsWith("SobjModel (") && !name.startsWith("WmapEntityModel (")) {
      return null;
    }
    final Set<String> idx = index();
    if(idx == null) {
      return null;
    }
    final TmdObjTable1c[] tables = SynthModels.tables(model);
    final String key = RefKey.modelKeyHex(tables);
    if(!idx.contains(key)) {
      log(name, key, "miss variant=vram");
      return null;
    }
    final byte[] data = Files.readAllBytes(Path.of("remaster", "models", key + ".lrm"));
    if("eagerAlloc".equals(FAULT)) {
      eagerAlloc(data);
    }
    final Set<String> ignore = new HashSet<>();
    if(FAULT.startsWith("lax:")) {
      ignore.add(FAULT.substring(4));
    }
    try {
      return new Found(RefLrm.read(data, RefLrm.Runtime.of(tables), ignore), key);
    } catch(final RefLrm.Invalid e) {
      log(name, key, "fallback(" + e.rule + ") variant=vram");
      return null;
    }
  }

  @SuppressWarnings("unused")
  private static int[] sink;

  /**
   * Lỗi gieo eagerAlloc: tin số đếm trong file, cấp phát mảng 9·texturedFaceCount int của biến thể 0 TRƯỚC khi kiểm cắt cụt
   * (vi phạm §3.5.4 mục 3). Với tfcHuge -> OutOfMemoryError; bộ kiểm chạy JVM fuzz với -XX:+ExitOnOutOfMemoryError nên phải thấy.
   */
  static void eagerAlloc(final byte[] data) {
    if(data.length < 0x40) {
      return;
    }
    final java.nio.ByteBuffer d = java.nio.ByteBuffer.wrap(data).order(java.nio.ByteOrder.LITTLE_ENDIAN);
    final int pc = d.getShort(0x1c) & 0xffff;
    final int vc = d.getShort(0x1e) & 0xffff;
    long o = 0x40;
    for(int i = 0; i < pc && o + 40 <= data.length; i++) {
      final int at = (int)o;
      if(data[at + 24] == 1) {
        o += 40 + 12L * (d.getInt(at + 28) & 0xffffffffL) + 32L * (d.getInt(at + 32) & 0xffffffffL) + 12L * (d.getInt(at + 36) & 0xffffffffL);
      } else {
        o += 28;
      }
    }
    if(vc > 0 && o + 28 <= data.length) {
      final long n = d.getInt((int)o + 24) & 0xffffffffL;
      sink = new int[(int)Math.min(Integer.MAX_VALUE - 16, 9 * n)];
    }
  }

  static Mesh[] meshes(final String partName, final RefBuild.Part p) {
    final Mesh[] meshes = new Mesh[p.meshes().size()];
    for(int i = 0; i < meshes.length; i++) {
      final RefBuild.MeshData m = p.meshes().get(i);
      final String cls = m.translucency() != null ? m.translucency().toString() : m.translucent() ? "untextured translucent" : "opaque";
      final Mesh mesh = GameEngine.RENDERER.api().makeMesh(partName + " (" + cls + ')', VertexOrder.TRIANGLES_ADJACENCY, m.v(), m.idx(),
        m.textured(), m.translucent(), m.translucency(), BufferUsage.STATIC);
      for(final long[] a : RefBuild.ATTRS) {
        mesh.attribute((int)a[0], a[1], (int)a[2], (int)a[3]);
      }
      meshes[i] = mesh;
    }
    return meshes;
  }

  static Obj build(final String partName, final TmdObjTable1c t, final List<RefBuild.Face> faces, final RefLrm.Part lp, final int tw, final int th,
                   final Shared s, final int texBase) {
    RefBuild.Part p = RefBuild.remaster(t, faces, lp, tw, th, null, null, 0);
    if(MESH_FAULTS.contains(FAULT) && !faultUsed && !p.meshes().isEmpty()) {
      faultUsed = true;
      p = inject(p, FAULT);
    }
    final Mesh[] vram = meshes(partName, p);
    final Mesh[][] atlasSets = new Mesh[s.lrm.variants.length][];
    if(s.atlas != null) {
      for(int v = 0; v < atlasSets.length; v++) {
        if(s.atlas[v] != null) {
          final boolean[] live = RefFaceHash.liveVariant(s.liveModel, s.lrm.variants[v].faceHash);
          final float[] auv = "atlascorner".equals(FAULT) ? swapCorners01(s.lrm.variants[v].atlasUv) : s.lrm.variants[v].atlasUv;
          atlasSets[v] = meshes(partName + " atlas " + v, RefBuild.remaster(t, faces, lp, 0, 0, auv, live, texBase));
        }
      }
    }
    s.owners++;
    return new MockMeshObj(partName, vram, p.backface(), atlasSets, s);
  }

  /** Lỗi gieo atlascorner: đổi chỗ góc 0 và góc 1 của atlasUv mọi mặt. */
  static float[] swapCorners01(final float[] uv) {
    final float[] o = uv.clone();
    for(int g = 0; g + 8 <= o.length; g += 8) {
      for(int c = 0; c < 2; c++) {
        final float x = o[g + c];
        o[g + c] = o[g + 2 + c];
        o[g + 2 + c] = x;
      }
    }
    return o;
  }

  // ---------------------------------------------------------------- trạng thái chung + xác minh (§4.4)

  static final class Shared {
    final String name;
    final String key;
    final Model124 model;
    final RefLrm.Lrm lrm;
    final List<List<RefBuild.Face>> faces;
    final boolean[] liveModel;
    @Nullable final Texture[] atlas;
    int state = -1;
    final long born = System.nanoTime();
    long lastVerify;
    int trips;
    boolean latched;
    int owners;
    boolean vectorLogged;

    Shared(final String name, final String key, final Model124 model, final RefLrm.Lrm lrm, final boolean atlas) {
      this.name = name;
      this.key = key;
      this.model = model;
      this.lrm = lrm;
      this.faces = SynthModels.faces(model);
      this.liveModel = RefFaceHash.liveModel(model, this.faces);
      if("nolive".equals(FAULT)) {
        Arrays.fill(this.liveModel, false);
      }
      this.atlas = atlas ? new Texture[lrm.variants.length] : null;
      if(atlas) {
        for(int v = 0; v < lrm.variants.length; v++) {
          this.atlas[v] = AtlasCacheMock.acquire(lrm.variants[v]);
        }
      } else if(CaptureApi.GlContext.active()) {
        // không có bộ ATLAS (vd ghi đè PNG, tw/th != 0): vẫn in véc-tơ face-hash runtime một lần khi nạp (để so với Python)
        this.logVector(RefFaceHash.rawVector((x, y) -> GameEngine.GPU.getPixel15(x, y), this.faces));
      }
    }

    /** Dòng log véc-tơ face-hash runtime (§3.3.6, bpp 3 ghi 0), một lần mỗi mô hình; lỗi gieo bpp3hash: mặt bpp 3 ghi 1. */
    void logVector(final int[] rt) {
      if(this.vectorLogged || !logEnabled()) {
        return;
      }
      this.vectorLogged = true;
      final int[] out = rt.clone();
      if("bpp3hash".equals(FAULT)) {
        int g = 0;
        for(final List<RefBuild.Face> fs : this.faces) {
          for(final RefBuild.Face f : fs) {
            if(f.textured) {
              if(f.bpp() == 3) {
                out[g] = 1;
              }
              g++;
            }
          }
        }
      }
      System.out.println("scvi-remaster: " + this.name + " key=" + this.key + " faceHashVectorSha1=" + RefFaceHash.vectorSha1(out));
    }

    void tick() {
      if(this.atlas == null || this.latched) {
        return;
      }
      final long now = System.nanoTime();
      final long interval = this.state >= 0 || now - this.born > 2_000_000_000L ? 1_000_000_000L : 66_000_000L;
      if(this.lastVerify != 0 && now - this.lastVerify < interval) {
        return;
      }
      this.lastVerify = now;
      final RefFaceHash.Vram gpu = (x, y) -> GameEngine.GPU.getPixel15(x, y);
      final int[] rt = RefFaceHash.rawVector(gpu, this.faces);
      this.logVector(rt);
      int next = -1;
      for(int v = 0; v < this.lrm.variants.length && next < 0; v++) {
        if(this.atlas[v] == null) {
          continue;
        }
        boolean ok = true;
        final int[] stored = this.lrm.variants[v].faceHash;
        for(int g = 0; g < rt.length && ok; g++) {
          if(!this.liveModel[g] && stored[g] != 0 && stored[g] != rt[g]) {
            ok = false;
          }
        }
        if(ok) {
          next = v;
        }
      }
      if(this.state >= 0 && next != this.state) {
        this.trips++;
        if(this.trips >= 3) {
          this.latched = true;
          next = -1;
          if(logEnabled()) {
            System.out.println("scvi-remaster: " + this.name + " key=" + this.key + " latched vram after " + this.trips + " trips");
          }
        }
      }
      this.state = next;
    }

    void release() {
      if(--this.owners == 0 && this.atlas != null) {
        for(int v = 0; v < this.atlas.length; v++) {
          if(this.atlas[v] != null) {
            AtlasCacheMock.release(this.lrm.variants[v]);
          }
        }
      }
    }
  }

  /**
   * AtlasCache giả (§4.2): một texture mỗi (pngSha1, w, h), đếm tham chiếu, xoá khi chủ cuối cùng trả. Lỗi gieo eagerfree: xoá
   * ngay ở lần trả đầu tiên (mô hình khác còn dùng) -> kịch bản 'share' của (f) phải bắt.
   */
  static final class AtlasCacheMock {
    private AtlasCacheMock() { }

    private record Entry(Texture tex, int[] refs) { }

    private static final java.util.Map<String, Entry> MAP = new java.util.HashMap<>();

    private static String key(final RefLrm.Variant v) {
      return RefKey.HEX.formatHex(v.png) + '/' + v.w + 'x' + v.h;
    }

    @Nullable
    static Texture acquire(final RefLrm.Variant v) {
      Entry e = MAP.get(key(v));
      if(e == null) {
        final Texture t = AtlasMock.load(v);
        if(t == null) {
          return null;
        }
        e = new Entry(t, new int[1]);
        MAP.put(key(v), e);
      }
      e.refs()[0]++;
      return e.tex();
    }

    static void release(final RefLrm.Variant v) {
      final Entry e = MAP.get(key(v));
      if(e == null) {
        return;
      }
      if(--e.refs()[0] <= 0 || "eagerfree".equals(FAULT)) {
        e.tex().delete();
        MAP.remove(key(v));
      }
    }
  }

  static final class MockMeshObj extends TmdMeshObj {
    final Mesh[][] atlasSets;
    final Shared s;

    MockMeshObj(final String name, final Mesh[] meshes, final boolean backfaceCulling, final Mesh[][] atlasSets, final Shared s) {
      super(name, meshes, backfaceCulling);
      this.atlasSets = atlasSets;
      this.s = s;
    }

    @Nullable
    Mesh[] current() {
      this.s.tick();
      final int v = this.s.state;
      return v >= 0 && this.atlasSets[v] != null ? this.atlasSets[v] : null;
    }

    @Override
    public void render(final int layer, final int startVertex, final int vertexCount) {
      final Mesh[] a = this.current();
      if(a == null) {
        super.render(layer, startVertex, vertexCount);
      } else {
        this.s.atlas[this.s.state].use(0);
        a[layer].draw(startVertex, vertexCount);
      }
    }

    @Override
    public void render(@Nullable final Translucency translucency, final int layer, final int startVertex, final int vertexCount) {
      final Mesh[] a = this.current();
      if(a == null) {
        super.render(translucency, layer, startVertex, vertexCount);
        return;
      }
      final Mesh mesh = a[layer];
      if(!mesh.translucent() && translucency == null || mesh.translucent() && mesh.translucencyMode() == translucency) {
        this.s.atlas[this.s.state].use(0);
        mesh.draw(startVertex, vertexCount);
      }
    }

    @Override
    protected void performDelete() {
      super.performDelete();
      for(final Mesh[] set : this.atlasSets) {
        if(set != null) {
          for(final Mesh m : set) {
            m.delete();
          }
        }
      }
      this.s.release();
    }
  }

  // ---------------------------------------------------------------- atlas PNG (§3.6)

  static final class AtlasMock {
    private AtlasMock() { }

    /** null khi PNG thiếu / sai SHA-1 / sai kích thước / không giải được (§5 -> chỉ bộ VRAM cho biến thể này). */
    @Nullable
    static Texture load(final RefLrm.Variant v) {
      try {
        final Path p = Path.of("remaster", "textures", RefKey.HEX.formatHex(v.png) + ".png");
        if(!Files.isRegularFile(p)) {
          return null;
        }
        final byte[] file = Files.readAllBytes(p);
        if(!Arrays.equals(RefKey.sha1(file), v.png)) {
          return null;
        }
        final byte[] rgba;
        final int w;
        final int h;
        try(final org.lwjgl.system.MemoryStack stack = org.lwjgl.system.MemoryStack.stackPush()) {
          final IntBuffer wb = stack.mallocInt(1);
          final IntBuffer hb = stack.mallocInt(1);
          final IntBuffer cb = stack.mallocInt(1);
          final ByteBuffer in = org.lwjgl.BufferUtils.createByteBuffer(file.length).put(file).flip();
          final ByteBuffer img = org.lwjgl.stb.STBImage.stbi_load_from_memory(in, wb, hb, cb, 4);
          if(img == null) {
            return null;
          }
          w = wb.get(0);
          h = hb.get(0);
          rgba = new byte[w * h * 4];
          img.get(0, rgba); // đọc tuyệt đối: stbi_image_free dùng memAddress(img) = địa chỉ + position
          org.lwjgl.stb.STBImage.stbi_image_free(img);
        }
        if(w != v.w || h != v.h) {
          return null;
        }
        final List<int[]> levels = Mips.chain(rgba, w, h);
        final int[] l0 = levels.get(0);
        final ByteBuffer b0 = org.lwjgl.BufferUtils.createByteBuffer(w * h * 4).put(Mips.runtime(l0)).flip();
        final Texture t = Texture.create("remaster atlas " + RefKey.HEX.formatHex(v.png), b -> {
          b.data(b0, w, h);
          b.internalFormat(TextureInternalFormat.RGBA_8);
          b.dataFormat(TextureDataFormat.RGBA);
          b.dataType(TextureDataType.UBYTE);
          b.wrapS(false);
          b.wrapT(false);
        });
        org.lwjgl.opengl.GL13C.glActiveTexture(org.lwjgl.opengl.GL13C.GL_TEXTURE0);
        int lw = w;
        int lh = h;
        for(int lvl = 1; lvl < levels.size(); lvl++) {
          lw = Math.max(1, lw / 2);
          lh = Math.max(1, lh / 2);
          final ByteBuffer bl = org.lwjgl.BufferUtils.createByteBuffer(lw * lh * 4).put(Mips.runtime(levels.get(lvl))).flip();
          org.lwjgl.opengl.GL11C.glTexImage2D(org.lwjgl.opengl.GL11C.GL_TEXTURE_2D, lvl, org.lwjgl.opengl.GL11C.GL_RGBA8, lw, lh, 0,
            org.lwjgl.opengl.GL11C.GL_RGBA, org.lwjgl.opengl.GL11C.GL_UNSIGNED_BYTE, bl);
        }
        org.lwjgl.opengl.GL11C.glTexParameteri(org.lwjgl.opengl.GL11C.GL_TEXTURE_2D, org.lwjgl.opengl.GL11C.GL_TEXTURE_MIN_FILTER, org.lwjgl.opengl.GL11C.GL_NEAREST_MIPMAP_NEAREST);
        org.lwjgl.opengl.GL11C.glTexParameteri(org.lwjgl.opengl.GL11C.GL_TEXTURE_2D, org.lwjgl.opengl.GL11C.GL_TEXTURE_MAG_FILTER, org.lwjgl.opengl.GL11C.GL_NEAREST);
        t.persistent = true;
        return t;
      } catch(final Throwable e) {
        return null;
      }
    }
  }

  /**
   * §3.6.1-§3.6.3: mức = int[w*h] mã hoá lớp (bit 24-25: 0 trong suốt, 1 STP=0, 2 STP=1) + RGB 24 bit; mip CPU theo khối
   * 2x2 / 2x1 / 1x1; đổi sang dạng shader cần ở {@link #runtime}.
   */
  static final class Mips {
    private Mips() { }

    static final int T = 0;
    static final int S0 = 1;
    static final int S1 = 2;

    static List<int[]> chain(final byte[] rgba, final int w, final int h) {
      final int[] l0 = new int[w * h];
      for(int i = 0; i < l0.length; i++) {
        final int a = rgba[4 * i + 3] & 0xff;
        final int cls = a < 64 ? T : a < 192 ? S1 : S0;
        l0[i] = cls == T ? 0 : cls << 24 | (rgba[4 * i] & 0xff) << 16 | (rgba[4 * i + 1] & 0xff) << 8 | rgba[4 * i + 2] & 0xff;
      }
      final List<int[]> out = new java.util.ArrayList<>(List.of(l0));
      int cw = w;
      int ch = h;
      final int n = 32 - Integer.numberOfLeadingZeros(Math.max(w, h));
      for(int k = 1; k < n; k++) {
        final int[] src = out.get(out.size() - 1);
        final int nw = Math.max(1, cw / 2);
        final int nh = Math.max(1, ch / 2);
        final int[] dst = new int[nw * nh];
        for(int y = 0; y < nh; y++) {
          for(int x = 0; x < nw; x++) {
            int cnt = 0;
            int tr = 0;
            int s1 = 0;
            int r = 0;
            int g = 0;
            int b = 0;
            for(int j = 0; j < 2; j++) {
              for(int i = 0; i < 2; i++) {
                final int sx = 2 * x + i;
                final int sy = 2 * y + j;
                if(sx >= cw || sy >= ch) {
                  continue;
                }
                cnt++;
                final int px = src[sy * cw + sx];
                final int cls = px >>> 24;
                if(cls == T) {
                  tr++;
                  continue;
                }
                if(cls == S1) {
                  s1++;
                }
                r += px >>> 16 & 0xff;
                g += px >>> 8 & 0xff;
                b += px & 0xff;
              }
            }
            if(2 * tr >= cnt) {
              dst[y * nw + x] = 0;
            } else {
              final int o = cnt - tr;
              final int cls = s1 >= o - s1 ? S1 : S0;
              final int half = "mipround".equals(FAULT) ? 0 : o / 2;
              dst[y * nw + x] = cls << 24 | (r + half) / o << 16 | (g + half) / o << 8 | (b + half) / o;
            }
          }
        }
        out.add(dst);
        cw = nw;
        ch = nh;
      }
      return out;
    }

    /** §3.6.2: trong suốt -> (0,0,0,0); STP=0 -> (R,G,B,0) với (0,0,0) -> (1,1,1); STP=1 -> (R,G,B,255). */
    static byte[] runtime(final int[] level) {
      final byte[] out = new byte[level.length * 4];
      for(int i = 0; i < level.length; i++) {
        final int px = level[i];
        final int cls = px >>> 24;
        if(cls == T) {
          continue;
        }
        int r = px >>> 16 & 0xff;
        int g = px >>> 8 & 0xff;
        int b = px & 0xff;
        if(cls == S0 && r == 0 && g == 0 && b == 0) {
          r = g = b = 1;
        }
        out[4 * i] = (byte)r;
        out[4 * i + 1] = (byte)g;
        out[4 * i + 2] = (byte)b;
        out[4 * i + 3] = (byte)(cls == S1 ? 255 : 0);
      }
      return out;
    }
  }

  // ---------------------------------------------------------------- gieo lỗi

  /** Gieo một lỗi vào lưới đầu tiên của phần. */
  public static RefBuild.Part inject(final RefBuild.Part p, final String fault) {
    final List<RefBuild.MeshData> meshes = new java.util.ArrayList<>(p.meshes());
    final RefBuild.MeshData m = meshes.get(0);
    switch(fault) {
      case "floatoff" -> {
        final float[] v = m.v().clone();
        v[0] = Float.intBitsToFloat(Float.floatToRawIntBits(v[0]) ^ 1);
        meshes.set(0, m.withVertices(v));
      }
      case "droptri" -> meshes.set(0, m.withIndices(Arrays.copyOf(m.idx(), Math.max(0, m.idx().length - 6))));
      case "winding" -> {
        final int[] idx = m.idx().clone();
        if(idx.length >= 6) {
          final int b = idx[2];
          idx[2] = idx[4];
          idx[4] = b;
          if(idx[2] == idx[4]) {
            idx[2] = idx[0];
          }
        }
        meshes.set(0, m.withIndices(idx));
      }
      case "meshclass" -> meshes.set(0, m.withClass(!m.textured(), m.translucent(), m.translucency() == null && m.translucent() ? Translucency.B_PLUS_F : m.translucency()));
      default -> throw new IllegalArgumentException("fault " + fault);
    }
    return new RefBuild.Part(p.meshObj(), p.backface(), meshes);
  }
}
