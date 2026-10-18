import org.lwjgl.BufferUtils;
import org.lwjgl.opengl.ARBProgramInterfaceQuery;
import org.lwjgl.opengl.ARBSeparateShaderObjects;
import org.lwjgl.opengl.GL;
import org.lwjgl.opengl.GLCapabilities;

import java.nio.ByteBuffer;
import java.nio.FloatBuffer;
import java.nio.IntBuffer;
import java.nio.ShortBuffer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

import static org.lwjgl.opengl.GL33C.*;
import static org.lwjgl.sdl.SDLError.SDL_GetError;
import static org.lwjgl.sdl.SDLInit.SDL_INIT_VIDEO;
import static org.lwjgl.sdl.SDLInit.SDL_Init;
import static org.lwjgl.sdl.SDLInit.SDL_Quit;
import static org.lwjgl.sdl.SDLVideo.*;

/**
 * ShaderCheck — kiểm các bộ shader charfx trên GPU thật, không chạy game (dữ liệu thử đều tự sinh, không có dữ liệu Sony).
 *
 * Cách gọi: powershell -ExecutionPolicy Bypass -File tools/sc_charfx/check/run.ps1   (dịch + chạy lớp này)
 *   java ... ShaderCheck <thư mục gốc repo> [thư mục game]
 * Đọc: <game>/gfx/shaders (bộ "stock"), out/charfx_variants/&lt;bộ&gt;/ (make_variants.py), out/charfx_lint/&lt;bộ&gt;/ (lint.ps1).
 *
 * 1. Ngữ cảnh OpenGL 3.3 core (cửa sổ SDL ẩn, như SC): biên dịch + link chương trình "TMD" (tmd.vsh+tmd.gsh+tmd.fsh) và
 *    "Battle TMD" (battle_tmd.vsh+tmd.gsh+battle_tmd.fsh) của mọi bộ; in max_vertices, số thành phần GS_OUT do driver báo
 *    (GS tách riêng + GL_PROGRAM_OUTPUT nếu có ARB_separate_shader_objects/ARB_program_interface_query) và tổng so với
 *    GL_MAX_GEOMETRY_TOTAL_OUTPUT_COMPONENTS. Vị trí (location) của mọi uniform thường phải trùng bộ stock: RenderEngine
 *    giữ ShaderOptions (vị trí uniform) tạo lúc khởi động, sau F5 vẫn đặt uniform theo vị trí cũ trên chương trình mới.
 * 2. Transform feedback (đường hình học): primitive không có bit PN -> mọi bộ ra đúng như stock (vị trí, uv, màu rgb, cờ
 *    & 0x1f, depth); có bit PN -> level^2 tam giác, vị trí khớp công thức PN tính bằng double trong Java, không lật chiều,
 *    giải mã đúng số đoạn (kẹp về PN_MAX_SEG) / độ cong / cạnh thẳng; không tessellate khi thiếu LIT, có TRANSLUCENT,
 *    level <= 1, hoặc ctmdFlags & 0x2 (Battle); hai tam giác chung cạnh không hở (watertight). z_off: có bit PN nhưng
 *    backgroundColour.w = 0 (SC gốc) -> ra đúng như stock; w = 1 -> tessellate như all.
 * 3. Vẽ điểm ảnh (FBO 320x240, VRAM giả R16UI 1024x512, 3 chế độ chiếu, 3 chế độ discardTranslucency): z_off, pn, _off,
 *    _pnraw giống stock từng bit (màu + depth); l2t/all giống stock trên cảnh chỉ có primitive không bị L2/T chạm (unlit,
 *    lit không texture trong suốt) và ở Battle với ctmd; z_off khi backgroundColour.w = 1 ra đúng như all (có và không có bit
 *    PN); z_off có bit PN mà w = 0 giống stock từng bit; cờ PN không làm đổi hình của stock/l2t; l2t/all/pn khác stock ở cảnh
 *    có primitive bị chạm (kiểm hiệu lực).
 * 4. Ngữ cảnh OpenGL 4.6 core + ARB_ES3_2_compatibility: link bản GLSL ES 3.20 do lint.ps1 dịch (đường Android).
 * Exit 0 = đạt hết, 1 = có lỗi (dòng "LOI:").
 */
public class ShaderCheck {
  static final String[] FILES = {"tmd.vsh", "battle_tmd.vsh", "tmd.gsh", "tmd.fsh", "battle_tmd.fsh"};
  static final String[][] PROGRAMS = {{"TMD", "tmd.vsh", "tmd.gsh", "tmd.fsh"}, {"Battle TMD", "battle_tmd.vsh", "tmd.gsh", "battle_tmd.fsh"}};
  static final int LIT = 0x1, TEXTURED = 0x2, COLOURED = 0x4, TRANSLUCENT = 0x8, QUAD = 0x10;
  static final int PN_ENABLE = 0x800;
  static final int W = 320, H = 240;
  static final int FLOATS = 16;

  static Path root, game, variantsDir, lintDir;
  static final Map<String, Map<String, String>> sources = new LinkedHashMap<>();
  static int failures;
  static int pnMaxSeg = 4;

  static void fail(final String msg) {
    failures++;
    System.out.println("  LOI: " + msg);
  }

  public static void main(final String[] args) throws Exception {
    Locale.setDefault(Locale.ROOT);
    root = Path.of(args[0]).toAbsolutePath();
    game = args.length > 1 ? Path.of(args[1]).toAbsolutePath() : root.resolve("game");
    variantsDir = root.resolve("out/charfx_variants");
    lintDir = root.resolve("out/charfx_lint");

    sources.put("stock", readSet(game.resolve("gfx/shaders")));
    try(final Stream<Path> s = Files.list(variantsDir)) {
      s.filter(Files::isDirectory).map(p -> p.getFileName().toString()).sorted().forEach(v -> {
        try {
          sources.put(v, readSet(variantsDir.resolve(v)));
        } catch(final Exception e) {
          throw new RuntimeException(e);
        }
      });
    }
    for(final String v : new String[] {"z_off", "pn", "l2t", "all", "_off", "_pnraw"}) {
      if(!sources.containsKey(v)) {
        fail("thieu bo " + v + " trong " + variantsDir + " (chay make_variants.py)");
      }
    }
    if(failures > 0) {
      System.exit(1);
    }
    final Matcher seg = Pattern.compile("const int PN_MAX_SEG = (\\d);").matcher(sources.get("pn").get("tmd.gsh"));
    if(seg.find()) {
      pnMaxSeg = Integer.parseInt(seg.group(1));
    }

    // ---------------------------------------------------------------- 1-3: GL 3.3 core
    final long[] ctx = createContext(3, 3);
    final GLCapabilities caps = GL.createCapabilities();
    System.out.println("[GL 3.3 core] " + glGetString(GL_RENDERER) + " / " + glGetString(GL_VERSION));
    final int maxTotal = glGetInteger(GL_MAX_GEOMETRY_TOTAL_OUTPUT_COMPONENTS);
    System.out.println("  MAX_GEOMETRY_OUTPUT_VERTICES=" + glGetInteger(GL_MAX_GEOMETRY_OUTPUT_VERTICES)
      + " MAX_GEOMETRY_TOTAL_OUTPUT_COMPONENTS=" + maxTotal
      + " MAX_GEOMETRY_OUTPUT_COMPONENTS=" + glGetInteger(GL_MAX_GEOMETRY_OUTPUT_COMPONENTS)
      + " MAX_GEOMETRY_INPUT_COMPONENTS=" + glGetInteger(GL_MAX_GEOMETRY_INPUT_COMPONENTS)
      + " MAX_VERTEX_OUTPUT_COMPONENTS=" + glGetInteger(GL_MAX_VERTEX_OUTPUT_COMPONENTS)
      + " MAX_FRAGMENT_INPUT_COMPONENTS=" + glGetInteger(GL_MAX_FRAGMENT_INPUT_COMPONENTS));

    System.out.println("[1] link GL 3.3 core (+ vi tri uniform phai trung stock: RenderEngine giu ShaderOptions tao luc khoi dong,");
    System.out.println("    sau F5 van dat uniform theo vi tri cu)");
    final boolean driverQuery = caps.GL_ARB_separate_shader_objects && caps.GL_ARB_program_interface_query;
    final Map<String, Map<String, Integer>> stockLocations = new LinkedHashMap<>();
    for(final var e : sources.entrySet()) {
      final Map<String, String> s = e.getValue();
      final StringBuilder line = new StringBuilder(String.format("  %-7s", e.getKey()));
      for(final String[] p : PROGRAMS) {
        final int prog = link(e.getKey() + " " + p[0], s.get(p[1]), s.get(p[2]), s.get(p[3]), null);
        line.append(String.format(" %s: %s", p[0], prog != 0 ? "linked" : "LOI"));
        if(prog != 0) {
          final Map<String, Integer> loc = uniformLocations(prog);
          if(e.getKey().equals("stock")) {
            stockLocations.put(p[0], loc);
            line.append(String.format(" (%d uniform)", loc.size()));
          } else if(!loc.equals(stockLocations.get(p[0]))) {
            fail(e.getKey() + " " + p[0] + ": vi tri uniform khac stock " + loc + " / " + stockLocations.get(p[0]) + " -> F5 se dat sai uniform");
          } else {
            line.append(" (vi tri uniform = stock)");
          }
        }
        if(prog == 0) {
          fail(e.getKey() + " " + p[0] + " khong link duoc");
        } else if(p[0].equals("TMD")) {
          int mv = glGetProgrami(prog, GL_GEOMETRY_VERTICES_OUT);
          glGetError();
          if(mv <= 0) { // this NVIDIA driver answers 0: take the declared layout(max_vertices = N)
            final Matcher m = Pattern.compile("max_vertices\\s*=\\s*(\\d+)").matcher(s.get("tmd.gsh"));
            mv = m.find() ? Integer.parseInt(m.group(1)) : 0;
          }
          final int comps = driverQuery ? gsOutputComponents(s.get("tmd.gsh")) : -1;
          if(comps > 0) {
            line.append(String.format(" | GS %d dinh x %d thanh phan (driver, gom gl_Position) = %d / %d", mv, comps, mv * comps, maxTotal));
            if(mv * comps > maxTotal) {
              fail(e.getKey() + ": ngan sach GS vuot " + maxTotal);
            }
          } else {
            line.append(String.format(" | GS %d dinh (driver khong bao thanh phan)", mv));
          }
        }
        if(prog != 0) {
          glDeleteProgram(prog);
        }
      }
      System.out.println(line);
    }

    System.out.println("[2] transform feedback (duong hinh hoc)");
    final Scene scene = new Scene();
    tfRetailEquality(scene);
    for(final String v : new String[] {"pn", "all"}) {
      tfPn(scene, v, "");
    }
    // z_off (ENH_FORCE 0): PN also needs lights[modelIndex].backgroundColour.w > 0 -> with w = 1 it must tessellate like all
    scene.setLight(1.0f);
    tfPn(scene, "z_off", " (w=1)");
    scene.setLight(0.0f);

    System.out.println("[3] ve diem anh, so tung bit voi stock");
    pixelTests(scene);
    scene.delete();
    destroyContext(ctx);

    // ---------------------------------------------------------------- 4: ES 3.20 (Android path) on a 4.6 context
    System.out.println("[4] link ban GLSL ES 3.20 (lint.ps1) tren GL 4.6 + ARB_ES3_2_compatibility");
    final long[] ctx46 = createContext(4, 6);
    final GLCapabilities caps46 = GL.createCapabilities();
    if(!caps46.GL_ARB_ES3_2_compatibility) {
      System.out.println("  BO QUA: driver khong co ARB_ES3_2_compatibility");
    } else {
      for(final String v : sources.keySet()) {
        final Map<String, String> es = readLint(v);
        if(es == null) {
          fail(v + ": chua co ket qua lint (chay lint.ps1)");
          continue;
        }
        final StringBuilder line = new StringBuilder(String.format("  %-7s", v));
        for(final String[] p : PROGRAMS) {
          final int prog = link(v + " " + p[0] + " (ES)", es.get(p[1]), es.get(p[2]), es.get(p[3]), null);
          line.append(String.format(" %s: %s", p[0], prog != 0 ? "linked" : "LOI"));
          if(prog == 0) {
            fail(v + " " + p[0] + " (ES) khong link duoc");
          } else {
            glDeleteProgram(prog);
          }
        }
        System.out.println(line);
      }
    }
    destroyContext(ctx46);
    SDL_Quit();

    System.out.println(failures == 0 ? "DAT: moi kiem tra GPU deu dat" : "LOI: " + failures + " kiem tra khong dat");
    System.exit(failures == 0 ? 0 : 1);
  }

  // ======================================================================================== sources

  static Map<String, String> readSet(final Path dir) throws Exception {
    final Map<String, String> m = new LinkedHashMap<>();
    for(final String f : FILES) {
      m.put(f, Files.readString(dir.resolve(f)));
    }
    return m;
  }

  /** file name -> transpiled ES source of lint.ps1 (null if missing) */
  static Map<String, String> readLint(final String v) throws Exception {
    final Path d = lintDir.resolve(v);
    final Path log = d.resolve("lint.txt");
    if(!Files.exists(log)) {
      return null;
    }
    final Map<String, String> m = new LinkedHashMap<>();
    final Matcher mt = Pattern.compile("(?m)^(\\S+\\.(?:vsh|gsh|fsh)) \\w+ uniforms=\\d+ -> (\\w+)\\.glsl").matcher(Files.readString(log));
    while(mt.find()) {
      m.put(mt.group(1), Files.readString(d.resolve("es_out").resolve(mt.group(2) + ".glsl")));
    }
    for(final String f : FILES) {
      if(!m.containsKey(f)) {
        return null;
      }
    }
    return m;
  }

  // ======================================================================================== GL helpers

  static long[] createContext(final int major, final int minor) {
    if(!SDL_Init(SDL_INIT_VIDEO)) {
      throw new RuntimeException("SDL_Init: " + SDL_GetError());
    }
    SDL_GL_ResetAttributes();
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, major);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, minor);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_CORE);
    final long window = SDL_CreateWindow("sc_charfx check", 64, 64, SDL_WINDOW_OPENGL | SDL_WINDOW_HIDDEN);
    if(window == 0) {
      throw new RuntimeException("SDL_CreateWindow: " + SDL_GetError());
    }
    final long context = SDL_GL_CreateContext(window);
    if(context == 0) {
      throw new RuntimeException("SDL_GL_CreateContext " + major + "." + minor + ": " + SDL_GetError());
    }
    SDL_GL_MakeCurrent(window, context);
    return new long[] {window, context};
  }

  static void destroyContext(final long[] c) {
    GL.setCapabilities(null);
    SDL_GL_DestroyContext(c[1]);
    SDL_DestroyWindow(c[0]);
  }

  static int compile(final String name, final int type, final String src) {
    final int s = glCreateShader(type);
    glShaderSource(s, src);
    glCompileShader(s);
    if(glGetShaderi(s, GL_COMPILE_STATUS) == 0) {
      System.out.println("  compile error " + name + ": " + glGetShaderInfoLog(s).trim());
      glDeleteShader(s);
      return 0;
    }
    return s;
  }

  static int link(final String name, final String vs, final String gs, final String fs, final String[] tfVaryings) {
    final int v = compile(name + " vs", GL_VERTEX_SHADER, vs);
    final int g = compile(name + " gs", GL_GEOMETRY_SHADER, gs);
    final int f = compile(name + " fs", GL_FRAGMENT_SHADER, fs);
    if(v == 0 || g == 0 || f == 0) {
      return 0;
    }
    final int p = glCreateProgram();
    glAttachShader(p, v);
    glAttachShader(p, g);
    glAttachShader(p, f);
    if(tfVaryings != null) {
      glTransformFeedbackVaryings(p, tfVaryings, GL_INTERLEAVED_ATTRIBS);
    }
    glLinkProgram(p);
    glDeleteShader(v);
    glDeleteShader(g);
    glDeleteShader(f);
    if(glGetProgrami(p, GL_LINK_STATUS) == 0) {
      System.out.println("  link error " + name + ": " + glGetProgramInfoLog(p).trim());
      glDeleteProgram(p);
      return 0;
    }
    return p;
  }

  /** name -> location of every active plain uniform (block members have no location) */
  static Map<String, Integer> uniformLocations(final int prog) {
    final Map<String, Integer> m = new java.util.TreeMap<>();
    final int n = glGetProgrami(prog, GL_ACTIVE_UNIFORMS);
    for(int i = 0; i < n; i++) {
      final String name = glGetActiveUniformName(prog, i);
      final int loc = glGetUniformLocation(prog, name);
      if(loc >= 0) {
        m.put(name, loc);
      }
    }
    return m;
  }

  /** Components of every active GS output (+4 for gl_Position) as the driver reports them; -1 if unknown */
  static int gsOutputComponents(final String gs) {
    final int p = ARBSeparateShaderObjects.glCreateShaderProgramv(GL_GEOMETRY_SHADER, gs);
    if(p == 0 || glGetProgrami(p, GL_LINK_STATUS) == 0) {
      if(p != 0) {
        glDeleteProgram(p);
      }
      return -1;
    }
    final int n = ARBProgramInterfaceQuery.glGetProgramInterfacei(p, ARBProgramInterfaceQuery.GL_PROGRAM_OUTPUT, ARBProgramInterfaceQuery.GL_ACTIVE_RESOURCES);
    int comps = 4;
    final int[] props = {ARBProgramInterfaceQuery.GL_TYPE, ARBProgramInterfaceQuery.GL_ARRAY_SIZE};
    final int[] vals = new int[2];
    for(int i = 0; i < n; i++) {
      final String name = ARBProgramInterfaceQuery.glGetProgramResourceName(p, ARBProgramInterfaceQuery.GL_PROGRAM_OUTPUT, i);
      if(name.startsWith("gl_")) {
        continue;
      }
      ARBProgramInterfaceQuery.glGetProgramResourceiv(p, ARBProgramInterfaceQuery.GL_PROGRAM_OUTPUT, i, props, null, vals);
      comps += typeComponents(vals[0]) * Math.max(1, vals[1]);
    }
    glDeleteProgram(p);
    return comps;
  }

  static int typeComponents(final int type) {
    return switch(type) {
      case GL_FLOAT, GL_INT, GL_UNSIGNED_INT, GL_BOOL -> 1;
      case GL_FLOAT_VEC2, GL_INT_VEC2, GL_UNSIGNED_INT_VEC2 -> 2;
      case GL_FLOAT_VEC3, GL_INT_VEC3, GL_UNSIGNED_INT_VEC3 -> 3;
      case GL_FLOAT_VEC4, GL_INT_VEC4, GL_UNSIGNED_INT_VEC4 -> 4;
      default -> throw new IllegalStateException("kieu GS output la 0x" + Integer.toHexString(type));
    };
  }

  static void checkGl(final String where) {
    final int e = glGetError();
    if(e != GL_NO_ERROR) {
      fail("GL error 0x" + Integer.toHexString(e) + " o " + where);
    }
  }

  // ======================================================================================== scene state (UBOs, textures)

  /** SC's uniform blocks + synthetic VRAM. Values are set per test via the setters, then bind(prog). */
  static final class Scene {
    final int[] ubo = new int[6];
    final String[] names = {"transforms", "transforms2", "lighting", "projectionInfo", "scissor", "clutAnimation"};
    final int tex15, tex24, vao, vbo, ebo;
    int projectionMode;
    float bgW;

    Scene() {
      glGenBuffers(this.ubo);
      this.vao = glGenVertexArrays();
      this.vbo = glGenBuffers();
      this.ebo = glGenBuffers();
      glBindVertexArray(this.vao);
      glBindBuffer(GL_ARRAY_BUFFER, this.vbo);
      glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, this.ebo);
      final int[] sizes = {4, 3, 2, 1, 1, 4, 1};
      int off = 0;
      for(int i = 0; i < sizes.length; i++) {
        glVertexAttribPointer(i, sizes[i], GL_FLOAT, false, FLOATS * 4, off * 4L);
        glEnableVertexAttribArray(i);
        off += sizes[i];
      }

      // VRAM: deterministic pseudo-random 16-bit words, ~1/8 zero (transparent), both STP states
      final Rng r = new Rng(1234);
      final ShortBuffer vram = BufferUtils.createShortBuffer(1024 * 512);
      for(int i = 0; i < 1024 * 512; i++) {
        final int x = r.nextInt(8) == 0 ? 0 : r.nextInt(0x10000);
        vram.put((short)x);
      }
      vram.flip();
      this.tex15 = glGenTextures();
      glBindTexture(GL_TEXTURE_2D, this.tex15);
      glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
      glTexImage2D(GL_TEXTURE_2D, 0, GL_R16UI, 1024, 512, 0, GL_RED_INTEGER, GL_UNSIGNED_SHORT, vram);
      glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
      glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
      final ByteBuffer rgba = BufferUtils.createByteBuffer(64 * 64 * 4);
      for(int i = 0; i < 64 * 64 * 4; i++) {
        rgba.put((byte)r.nextInt(256));
      }
      rgba.flip();
      this.tex24 = glGenTextures();
      glBindTexture(GL_TEXTURE_2D, this.tex24);
      glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 64, 64, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba);
      glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
      glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);

      final FloatBuffer clut = BufferUtils.createFloatBuffer(1024 * 4);
      clut.put(0, -1.0f);
      this.upload(5, clut);
      this.upload(4, BufferUtils.createFloatBuffer(4).put(new float[] {0, 0, W, H}).flip());
      final FloatBuffer t2 = BufferUtils.createFloatBuffer(128 * 20);
      for(int m = 0; m < 128; m++) {
        t2.put(identity()).put(new float[4]);
      }
      this.upload(1, t2.flip());
      this.setLight(0.0f);
      this.setProjection(0);
    }

    void upload(final int i, final FloatBuffer data) {
      glBindBuffer(GL_UNIFORM_BUFFER, this.ubo[i]);
      glBufferData(GL_UNIFORM_BUFFER, data, GL_STATIC_DRAW);
    }

    /** lights[0]: three directional lights (rows of lightDirection), coloured, ambient 0.25; w = the charfx per-model switch */
    void setLight(final float w) {
      this.bgW = w;
      final FloatBuffer l = BufferUtils.createFloatBuffer(128 * 32);
      final float[][] rows = {{0.0f, -0.9f, 0.3f}, {0.8f, 0.1f, -0.5f}, {-0.5f, 0.4f, 0.7f}};
      final float[][] colours = {{0.7f, 0.65f, 0.6f}, {0.25f, 0.3f, 0.45f}, {0.15f, 0.1f, 0.05f}};
      for(int m = 0; m < 128; m++) {
        final float[] dir = new float[16]; // column-major: element (row r, col c) at c * 4 + r
        for(int rr = 0; rr < 3; rr++) {
          for(int c = 0; c < 3; c++) {
            dir[c * 4 + rr] = rows[rr][c];
          }
        }
        dir[15] = 1.0f;
        l.put(dir);
        for(int c = 0; c < 3; c++) { // mat3 lightColour, column c = colour of light c, std140 vec4 padding
          l.put(colours[c]).put(0.0f);
        }
        l.put(new float[] {0.25f, 0.22f, 0.2f, w});
      }
      this.upload(2, l.flip());
    }

    /** TF tests: ortho mode with identity camera AND projection, so gl_Position = model-space position */
    void setIdentityProjection() {
      this.projectionMode = 0;
      this.upload(0, BufferUtils.createFloatBuffer(32).put(identity()).put(identity()).flip());
      this.upload(3, BufferUtils.createFloatBuffer(4).put(new float[] {0.0f, 100.0f, 1.0f, 0.0f}).flip());
    }

    /** 0: ortho, 1: PS1 perspective (H = 320), 2: modern perspective; model space = view space (camera identity) */
    void setProjection(final int mode) {
      this.projectionMode = mode;
      final float[] proj = new float[16];
      final float znear = 100.0f, zfar;
      if(mode == 2) {
        // clip.w = z (PS1 convention: +z forward), x/y in pixels from the centre
        final float n = 100.0f, f = 3000.0f;
        proj[0] = 320.0f / 160.0f;
        proj[5] = -320.0f / 120.0f;
        proj[10] = (f + n) / (f - n);
        proj[14] = -2.0f * f * n / (f - n);
        proj[11] = 1.0f;
        zfar = 320.0f;
      } else {
        proj[0] = 1.0f / 160.0f;
        proj[5] = -1.0f / 120.0f;
        proj[10] = 1.0f / 1000.0f;
        proj[14] = -0.5f;
        proj[15] = 1.0f;
        zfar = mode == 1 ? 320.0f : 100.0f;
      }
      final FloatBuffer t = BufferUtils.createFloatBuffer(32).put(identity()).put(proj).flip();
      this.upload(0, t);
      // mode 2: the FS writes gl_FragDepth = (clip z - znear) * zdiffInv + depthOffset; clip z is 60..760 for z = 250..900
      final float zn = mode == 2 ? 0.0f : znear;
      final float zdiffInv = mode == 2 ? 1.0f / 1000.0f : 1.0f / (3000.0f - znear);
      this.upload(3, BufferUtils.createFloatBuffer(4).put(new float[] {zn, zfar, zdiffInv, mode}).flip());
    }

    void bind(final int prog) {
      for(int i = 0; i < this.ubo.length; i++) {
        final int idx = glGetUniformBlockIndex(prog, this.names[i]);
        if(idx != GL_INVALID_INDEX) {
          glUniformBlockBinding(prog, idx, i);
        }
        glBindBufferBase(GL_UNIFORM_BUFFER, i, this.ubo[i]);
      }
      glUseProgram(prog);
      glActiveTexture(GL_TEXTURE0);
      glBindTexture(GL_TEXTURE_2D, this.tex24);
      glActiveTexture(GL_TEXTURE1);
      glBindTexture(GL_TEXTURE_2D, this.tex15);
      seti(prog, "tex24", 0);
      seti(prog, "tex15", 1);
      setf(prog, "modelIndex", 0.0f);
      set3(prog, "recolour", 1.0f, 1.0f, 1.0f);
      set3(prog, "battleColour", 1.0f, 1.0f, 1.0f);
      set2(prog, "uvOffset", 0.0f, 0.0f);
      set2(prog, "clutOverride", 0.0f, 0.0f);
      set2(prog, "tpageOverride", 0.0f, 0.0f);
      seti(prog, "tmdTranslucency", 0);
      seti(prog, "ctmdFlags", 0);
      seti(prog, "usePs1Depth", 0);
      setf(prog, "discardTranslucency", 0.0f);
    }

    void draw(final float[] verts, final int[] idx) {
      glBindVertexArray(this.vao);
      glBindBuffer(GL_ARRAY_BUFFER, this.vbo);
      glBufferData(GL_ARRAY_BUFFER, verts, GL_STREAM_DRAW);
      glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, this.ebo);
      glBufferData(GL_ELEMENT_ARRAY_BUFFER, idx, GL_STREAM_DRAW);
      glDrawElements(GL_TRIANGLES_ADJACENCY, idx.length, GL_UNSIGNED_INT, 0L);
    }

    void delete() {
      glDeleteBuffers(this.ubo);
      glDeleteBuffers(this.vbo);
      glDeleteBuffers(this.ebo);
      glDeleteVertexArrays(this.vao);
      glDeleteTextures(this.tex15);
      glDeleteTextures(this.tex24);
    }
  }

  static float[] identity() {
    return new float[] {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
  }

  static void seti(final int p, final String n, final int v) {
    final int l = glGetUniformLocation(p, n);
    if(l >= 0) {
      glUniform1i(l, v);
    }
  }

  static void setf(final int p, final String n, final float v) {
    final int l = glGetUniformLocation(p, n);
    if(l >= 0) {
      glUniform1f(l, v);
    }
  }

  static void set2(final int p, final String n, final float x, final float y) {
    final int l = glGetUniformLocation(p, n);
    if(l >= 0) {
      glUniform2f(l, x, y);
    }
  }

  static void set3(final int p, final String n, final float x, final float y, final float z) {
    final int l = glGetUniformLocation(p, n);
    if(l >= 0) {
      glUniform3f(l, x, y, z);
    }
  }

  /** small deterministic generator (same data on every run) */
  static final class Rng {
    long s;

    Rng(final long seed) {
      this.s = seed * 0x9E3779B97F4A7C15L + 1;
    }

    int nextInt(final int n) {
      this.s = this.s * 6364136223846793005L + 1442695040888963407L;
      return (int)((this.s >>> 33) % n);
    }

    float nextFloat() {
      return this.nextInt(1 << 24) / (float)(1 << 24);
    }
  }

  // ======================================================================================== mesh building (TmdObjLoader layout)

  /** Vertex/index lists in the TmdObjLoader layout: 16 floats per vertex, 6 indices per triangle (c0, adj, c1, adj, c2, adj) */
  static final class Mesh {
    final List<float[]> verts = new ArrayList<>();
    final List<Integer> idx = new ArrayList<>();

    int vertex(final double[] pos, final double[] norm, final float u, final float v, final int tpage, final int clut, final float[] colour, final int flags) {
      final float[] f = new float[FLOATS];
      f[0] = (float)pos[0];
      f[1] = (float)pos[1];
      f[2] = (float)pos[2];
      f[3] = this.verts.size();
      if(norm != null) {
        f[4] = (float)norm[0];
        f[5] = (float)norm[1];
        f[6] = (float)norm[2];
      }
      f[7] = u;
      f[8] = v;
      f[9] = tpage;
      f[10] = clut;
      System.arraycopy(colour, 0, f, 11, 4);
      f[15] = flags;
      this.verts.add(f);
      return this.verts.size() - 1;
    }

    /** = TmdObjLoader: triangle (v2, adj, v1, adj, v0, adj), quad adds (v1, v0, v2, v0, v3, v0) */
    void prim(final int base, final boolean quad) {
      final int adj1 = base + 3;
      this.idx.addAll(List.of(base + 2, adj1, base + 1, adj1, base, adj1));
      if(quad) {
        this.idx.addAll(List.of(base + 1, base, base + 2, base, base + 3, base));
      }
    }

    /** One GS triangle with explicit corners (c0 = vs_out[0], c1 = vs_out[2], c2 = vs_out[4]) */
    void tri(final int c0, final int c1, final int c2) {
      this.idx.addAll(List.of(c0, c0, c1, c0, c2, c0));
    }

    float[] vertexArray() {
      final float[] out = new float[(this.verts.size() + 4) * FLOATS]; // +4: TmdObjLoader's adjacency index may point past the last primitive
      for(int i = 0; i < this.verts.size(); i++) {
        System.arraycopy(this.verts.get(i), 0, out, i * FLOATS, FLOATS);
      }
      return out;
    }

    int[] indexArray() {
      return this.idx.stream().mapToInt(Integer::intValue).toArray();
    }
  }

  static double[] v3(final double x, final double y, final double z) {
    return new double[] {x, y, z};
  }

  static double[] norm(final double[] a) {
    final double l = Math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]);
    return v3(a[0] / l, a[1] / l, a[2] / l);
  }

  static double[] sub(final double[] a, final double[] b) {
    return v3(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
  }

  static double dot(final double[] a, final double[] b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  }

  static double[] cross(final double[] a, final double[] b) {
    return v3(a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]);
  }

  static double dist(final double[] a, final double[] b) {
    return Math.sqrt(dot(sub(a, b), sub(a, b)));
  }

  /**
   * PN flags of corner k: local index k, linear-edge bits for the given partner corners, enable, level, strength eighths.
   * eighths 8 is written as 0x40000 (bit 18) like tools/sc_charfx/java PnConfig does; the shader reads bits 15-17 = 0 = 1.0.
   */
  static int pnFlags(final int base, final int k, final int level, final int eighths, final int linearMask) {
    return base | k << 5 | (linearMask & 0xf) << 7 | PN_ENABLE | (level & 7) << 12 | (eighths & 0xf) << 15;
  }

  /** Random primitive soup in the TmdObjLoader layout (pixel tests). pnLevel > 0 adds PN bits to lit gouraud opaque ones. */
  static Mesh soup(final long seed, final int count, final boolean unaffectedOnly, final int pnLevel) {
    final Rng r = new Rng(seed);
    final Mesh m = new Mesh();
    for(int i = 0; i < count; i++) {
      boolean lit = r.nextInt(2) == 0;
      boolean textured = r.nextInt(5) < 3;
      final boolean coloured = r.nextInt(5) < 2;
      boolean translucent = r.nextInt(4) == 0;
      final boolean quad = r.nextInt(5) < 2;
      if(unaffectedOnly && lit) { // L2 needs lit && !translucent; T needs lit && textured -> keep lit only as untextured translucent
        textured = false;
        translucent = true;
      }
      final boolean gouraud = lit && r.nextInt(3) != 0;
      final int bpp = r.nextInt(3);
      final int pageX = bpp == 2 ? r.nextInt(12) : bpp == 1 ? r.nextInt(15) : r.nextInt(16);
      final int tpage = pageX | (r.nextInt(2) << 4) | (r.nextInt(4) << 5) | (bpp << 7);
      final int clut = r.nextInt(48) | (r.nextInt(512) << 6);
      final float cx = r.nextInt(300) - 150, cy = r.nextInt(220) - 110, z = 250 + r.nextInt(650);
      final float size = 15 + r.nextInt(70);
      final int n = quad ? 4 : 3;
      final double[] faceN = norm(v3(r.nextFloat() - 0.5, r.nextFloat() - 0.5, r.nextFloat() - 0.5));
      final float u0 = r.nextInt(200), v0 = r.nextInt(200);
      final int base = m.verts.size();
      for(int k = 0; k < n; k++) {
        final double ax = (k == 1 || k == 3) ? 1 : 0, ay = k >= 2 ? 1 : 0; // quad corner order 0,1,2,3 = TL TR BL BR
        final double[] pos = v3(cx + (ax - 0.5) * size + (r.nextFloat() - 0.5) * 8, cy + (ay - 0.5) * size, z + (r.nextFloat() - 0.5) * 40);
        final double[] nn = lit ? (gouraud ? norm(v3(faceN[0] + r.nextFloat() - 0.5, faceN[1] + r.nextFloat() - 0.5, faceN[2] + r.nextFloat() - 0.5)) : faceN) : null;
        final float[] colour = coloured ? new float[] {r.nextFloat(), r.nextFloat(), r.nextFloat(), 1.0f} : new float[] {1, 1, 1, 1};
        if(coloured && textured) {
          for(int c = 0; c < 4; c++) {
            colour[c] *= 2.0f;
          }
        }
        int flags = (lit ? LIT : 0) | (textured ? TEXTURED : 0) | (coloured ? COLOURED : 0) | (translucent ? TRANSLUCENT : 0) | (quad ? QUAD : 0);
        if(pnLevel > 0 && gouraud && !translucent) {
          flags = pnFlags(flags, k, pnLevel, 0, 0);
        }
        m.vertex(pos, nn, textured ? u0 + (float)ax * Math.min(size, 50) : 0, textured ? v0 + (float)ay * Math.min(size, 50) : 0,
          textured ? tpage : 0, textured ? clut : 0, colour, flags);
      }
      m.prim(base, quad);
    }
    return m;
  }

  // ======================================================================================== 2. transform feedback

  static final String[] TF = {"gl_Position", "GS_OUT.vertColour", "GS_OUT.vertUv", "GS_OUT.vertFlags", "GS_OUT.depth"};
  static final int TFW = 4 + 4 + 2 + 1 + 1;

  /** Captured GS output: [triangle][vertex][TFW] as raw floats (vertFlags as int bits) */
  static float[][][] capture(final Scene scene, final int prog, final Mesh mesh, final int ctmdFlags) {
    scene.bind(prog);
    seti(prog, "ctmdFlags", ctmdFlags);
    final int tfb = glGenBuffers();
    glBindBuffer(GL_TRANSFORM_FEEDBACK_BUFFER, tfb);
    glBufferData(GL_TRANSFORM_FEEDBACK_BUFFER, 4L * TFW * 3 * 64 * Math.max(1, mesh.idx.size() / 6), GL_STREAM_READ);
    glBindBufferBase(GL_TRANSFORM_FEEDBACK_BUFFER, 0, tfb);
    final int q = glGenQueries();
    glEnable(GL_RASTERIZER_DISCARD);
    glBeginQuery(GL_TRANSFORM_FEEDBACK_PRIMITIVES_WRITTEN, q);
    glBeginTransformFeedback(GL_TRIANGLES);
    scene.draw(mesh.vertexArray(), mesh.indexArray());
    glEndTransformFeedback();
    glEndQuery(GL_TRANSFORM_FEEDBACK_PRIMITIVES_WRITTEN);
    glDisable(GL_RASTERIZER_DISCARD);
    final int prims = glGetQueryObjecti(q, GL_QUERY_RESULT);
    final FloatBuffer out = BufferUtils.createFloatBuffer(prims * 3 * TFW);
    glGetBufferSubData(GL_TRANSFORM_FEEDBACK_BUFFER, 0, out);
    glDeleteQueries(q);
    glDeleteBuffers(tfb);
    checkGl("transform feedback");
    final float[][][] tris = new float[prims][3][TFW];
    for(int t = 0; t < prims; t++) {
      for(int k = 0; k < 3; k++) {
        out.get(tris[t][k]);
      }
    }
    return tris;
  }

  static int tfProgram(final String set, final String[] p) {
    final Map<String, String> s = sources.get(set);
    final int prog = link(set + " " + p[0] + " (TF)", s.get(p[1]), s.get(p[2]), s.get(p[3]), TF);
    if(prog == 0) {
      fail(set + " " + p[0] + ": khong link duoc voi transform feedback");
    }
    return prog;
  }

  /** Without PN bits every set must emit what stock emits (rgb of the colour; flags & 0x1f: the only bits the FS reads) */
  static void tfRetailEquality(final Scene scene) {
    for(final String[] p : PROGRAMS) {
      for(int mode = 0; mode <= 2; mode++) {
        scene.setProjection(mode);
        final Mesh mesh = soup(77 + mode, 60, false, 0);
        final int sp = tfProgram("stock", p);
        if(sp == 0) {
          return;
        }
        final float[][][] ref = capture(scene, sp, mesh, 0);
        glDeleteProgram(sp);
        final StringBuilder line = new StringBuilder(String.format("  khong bit PN, %-10s che do %d, %3d tam giac stock:", p[0], mode, ref.length));
        for(final String v : sources.keySet()) {
          if(v.equals("stock")) {
            continue;
          }
          final int prog = tfProgram(v, p);
          if(prog == 0) {
            continue;
          }
          final float[][][] got = capture(scene, prog, mesh, 0);
          glDeleteProgram(prog);
          final String diff = compareRetail(ref, got);
          line.append(' ').append(v).append(diff == null ? "=" : "!");
          if(diff != null) {
            fail(v + " " + p[0] + " che do " + mode + ": khac stock khi khong co bit PN: " + diff);
          }
        }
        // PN bits written by the loader but the per-model switch at 0 (stock SC): z_off must still emit what stock emits
        final Mesh meshPn = soup(77 + mode, 60, false, 3);
        final int sp2 = tfProgram("stock", p);
        final int zp = tfProgram("z_off", p);
        if(sp2 != 0 && zp != 0) {
          final float[][][] refPn = capture(scene, sp2, meshPn, 0);
          final String diff = compareRetail(refPn, capture(scene, zp, meshPn, 0));
          line.append(" | bit PN w=0: z_off").append(diff == null ? "=" : "!");
          if(diff != null) {
            fail("z_off " + p[0] + " che do " + mode + ": co bit PN, backgroundColour.w = 0 ma khac stock: " + diff);
          }
        }
        if(sp2 != 0) {
          glDeleteProgram(sp2);
        }
        if(zp != 0) {
          glDeleteProgram(zp);
        }
        System.out.println(line);
      }
    }
    scene.setProjection(0);
  }

  static String compareRetail(final float[][][] a, final float[][][] b) {
    if(a.length != b.length) {
      return "so tam giac " + b.length + " != " + a.length;
    }
    for(int t = 0; t < a.length; t++) {
      for(int k = 0; k < 3; k++) {
        for(int c = 0; c < TFW; c++) {
          if(c == 7) {
            continue; // vertColour.a: undefined in stock for lit primitives, material blue in L2/PN (dead in the FS)
          }
          int x = Float.floatToRawIntBits(a[t][k][c]), y = Float.floatToRawIntBits(b[t][k][c]);
          if(c == 10) {
            x &= 0x1f;
            y &= 0x1f;
          }
          if(x != y) {
            return String.format("tam giac %d dinh %d thanh phan %d: %s != %s", t, k, c, Float.intBitsToFloat(y), Float.intBitsToFloat(x));
          }
        }
      }
    }
    return null;
  }

  /** PN position in double precision, the formulas of tmd_pn.gsh (corners: P[0] w, P[1] u, P[2] v) */
  static double[] pnPoint(final double[][] P, final double[][] Nin, final boolean[] lin, final double s, final double u, final double v) {
    final double[][] N = {norm(Nin[0]), norm(Nin[1]), norm(Nin[2])};
    final double w = 1.0 - u - v;
    final double[] b210 = ctrl(P[0], P[1], N[0], lin[0], s), b120 = ctrl(P[1], P[0], N[1], lin[0], s);
    final double[] b021 = ctrl(P[1], P[2], N[1], lin[1], s), b012 = ctrl(P[2], P[1], N[2], lin[1], s);
    final double[] b102 = ctrl(P[2], P[0], N[2], lin[2], s), b201 = ctrl(P[0], P[2], N[0], lin[2], s);
    final double[] out = new double[3];
    for(int i = 0; i < 3; i++) {
      final double e = (b210[i] + b120[i] + b021[i] + b012[i] + b102[i] + b201[i]) / 6.0;
      final double vv = (P[0][i] + P[1][i] + P[2][i]) / 3.0;
      final double b111 = e + (e - vv) * 0.5;
      out[i] = P[0][i] * w * w * w + P[1][i] * u * u * u + P[2][i] * v * v * v
        + 3.0 * (b210[i] * w * w * u + b120[i] * w * u * u + b201[i] * w * w * v + b021[i] * u * u * v + b102[i] * w * v * v + b012[i] * u * v * v)
        + 6.0 * b111 * w * u * v;
    }
    return out;
  }

  static double[] ctrl(final double[] pi, final double[] pj, final double[] ni, final boolean linear, final double s) {
    final double w = linear ? 0.0 : s * dot(sub(pj, pi), ni);
    return v3((2 * pi[0] + pj[0] - w * ni[0]) / 3, (2 * pi[1] + pj[1] - w * ni[1]) / 3, (2 * pi[2] + pj[2] - w * ni[2]) / 3);
  }

  static double[] pos(final float[] vtx) {
    return v3(vtx[0], vtx[1], vtx[2]);
  }

  /** Sphere patch: radius 100 around (0, 0, 500), corners in directions d, normals = d (ortho, identity transforms) */
  static double[] onSphere(final double[] d) {
    return v3(100 * d[0], 100 * d[1], 500 + 100 * d[2]);
  }

  static void tfPn(final Scene scene, final String set, final String tag) {
    scene.setIdentityProjection();
    final String[] tmd = PROGRAMS[0];
    final int prog = tfProgram(set, tmd);
    final int bprog = tfProgram(set, PROGRAMS[1]);
    if(prog == 0 || bprog == 0) {
      return;
    }
    final double[][] dirs = {norm(v3(-0.35, -0.3, -1)), norm(v3(0.4, -0.25, -1)), norm(v3(0.0, 0.4, -1)), norm(v3(0.5, 0.45, -1))};
    final double[][] P = {onSphere(dirs[0]), onSphere(dirs[1]), onSphere(dirs[2])};
    final double[][] N = {dirs[0], dirs[1], dirs[2]};
    final float[] colour = {0.8f, 0.6f, 0.4f, 1.0f};
    final double[] on = cross(sub(P[1], P[0]), sub(P[2], P[0]));
    final StringBuilder line = new StringBuilder("  " + set + tag + ":");

    // (level bits, strength eighths, linear mask per corner as bits of partner local index, base flags, ctmdFlags, expected level, battle)
    final Object[][] cases = {
      {2, 0, 0, LIT, 0, 2, false}, {3, 0, 0, LIT | TEXTURED, 0, 3, false}, {4, 0, 0, LIT, 0, 4, false}, {4, 4, 0, LIT, 0, 4, false},
      {3, 8, 0, LIT, 0, 3, false}, {3, 8, 0, LIT, 0, 3, true}, {2, 1, 0, LIT, 0, 2, false},
      {7, 0, 0, LIT, 0, pnMaxSeg, false}, {1, 0, 0, LIT, 0, 1, false}, {0, 0, 0, LIT, 0, 1, false},
      {3, 0, 0, LIT | TRANSLUCENT, 0, 1, false}, {3, 0, 0, TEXTURED, 0, 1, false}, {3, 0, 0, LIT, 0x2, 1, true},
      {3, 0, 0, LIT, 0x20, 3, true}, {3, 0, -1, LIT, 0, 3, false}, {3, 0, -2, LIT, 0, 3, false},
    };
    int worstCase = 0;
    double worst = 0;
    for(final Object[] c : cases) {
      final int level = (int)c[0], eighths = (int)c[1], linSpec = (int)c[2], base = (int)c[3], ctmd = (int)c[4], expect = (int)c[5];
      final boolean battle = (boolean)c[6];
      // linSpec -1: all three edges linear; -2: only edge c0-c1 linear
      final boolean[] lin = {linSpec == -1 || linSpec == -2, linSpec == -1, linSpec == -1};
      final Mesh m = new Mesh();
      final int[] ids = new int[3];
      for(int k = 0; k < 3; k++) {
        int mask = 0;
        final int a = (k + 1) % 3, b = (k + 2) % 3; // partners
        if(lin[edgeIndex(k, a)]) {
          mask |= 1 << a;
        }
        if(lin[edgeIndex(k, b)]) {
          mask |= 1 << b;
        }
        ids[k] = m.vertex(P[k], N[k], 10 + 20 * k, 30 - 10 * k, 0x80, 0, colour, pnFlags(base, k, level, eighths, mask));
      }
      m.tri(ids[0], ids[1], ids[2]);
      final float[][][] got = capture(scene, battle ? bprog : prog, m, ctmd);
      final String label = String.format("level bit %d, do cong %d/8, co 0x%x, ctmd 0x%x, canh thang %d", level, eighths, base, ctmd, linSpec);
      if(got.length != expect * expect) {
        fail(set + " " + label + ": " + got.length + " tam giac, can " + expect * expect);
        continue;
      }
      if(expect == 1) {
        for(int k = 0; k < 3; k++) {
          // retail order: corners 0, 2, 4 = P0, P1, P2
          if(dist(pos(got[0][k]), P[k]) > 1e-4) {
            fail(set + " " + label + ": duong goc phai giu nguyen dinh goc");
          }
        }
        continue;
      }
      final double strength = eighths == 0 ? 1.0 : eighths / 8.0;
      final List<double[]> ref = new ArrayList<>();
      for(int r = 0; r <= expect; r++) {
        for(int cc = 0; cc <= expect - r; cc++) {
          ref.add(pnPoint(P, N, lin, strength, r / (double)expect, cc / (double)expect));
        }
      }
      double maxErr = 0;
      int flipped = 0;
      for(final float[][] t : got) {
        final double[] n = cross(sub(pos(t[1]), pos(t[0])), sub(pos(t[2]), pos(t[0])));
        if(dot(n, on) <= 0) {
          flipped++;
        }
        for(final float[] vtx : t) {
          double best = 1e9;
          for(final double[] rp : ref) {
            best = Math.min(best, dist(pos(vtx), rp));
          }
          maxErr = Math.max(maxErr, best);
          if((Float.floatToRawIntBits(vtx[10]) & ~0x3f) != 0) {
            fail(set + " " + label + ": co gui sang FS con bit ngoai 0x3f: 0x" + Integer.toHexString(Float.floatToRawIntBits(vtx[10])));
          }
        }
      }
      if(maxErr > worst) {
        worst = maxErr;
        worstCase = got.length;
      }
      if(maxErr > 2e-3 || flipped > 0) {
        fail(String.format("%s %s: sai so %.5f don vi, %d tam giac lat chieu", set, label, maxErr, flipped));
      }
      if(linSpec == -1) { // every edge linear -> flat patch: all points on the corner plane
        final double[] fn = norm(on);
        for(final float[][] t : got) {
          for(final float[] vtx : t) {
            if(Math.abs(dot(sub(pos(vtx), P[0]), fn)) > 1e-3) {
              fail(set + " " + label + ": canh thang het ma diem khong nam tren mat phang");
              break;
            }
          }
        }
      }
    }
    line.append(String.format(" %d truong hop, sai so lon nhat %.6f don vi (%d tam giac)", cases.length, worst, worstCase));

    // the curved patch must be closer to the sphere than the flat triangle (sanity: the bulge points outwards)
    final double[] mid = pnPoint(P, N, new boolean[3], 1.0, 1 / 3.0, 1 / 3.0);
    final double[] flat = v3((P[0][0] + P[1][0] + P[2][0]) / 3, (P[0][1] + P[1][1] + P[2][1]) / 3, (P[0][2] + P[1][2] + P[2][2]) / 3);
    final double[] c = v3(0, 0, 500);
    if(Math.abs(dist(mid, c) - 100) >= Math.abs(dist(flat, c) - 100)) {
      fail("tham chieu PN khong gan mat cau hon tam giac phang");
    }

    // watertight: A = (d0, d1, d2), B = (d2, d1, d3) share edge d1-d2 (A: corners 1-2, B: corners 0-1)
    final Mesh m = new Mesh();
    final double[] P3 = onSphere(dirs[3]);
    final int a0 = m.vertex(P[0], N[0], 0, 0, 0, 0, colour, pnFlags(LIT, 0, 4, 0, 0));
    final int a1 = m.vertex(P[1], N[1], 0, 0, 0, 0, colour, pnFlags(LIT, 1, 4, 0, 0));
    final int a2 = m.vertex(P[2], N[2], 0, 0, 0, 0, colour, pnFlags(LIT, 2, 4, 0, 0));
    final int b0 = m.vertex(P[2], N[2], 0, 0, 0, 0, colour, pnFlags(LIT, 0, 4, 0, 0));
    final int b1 = m.vertex(P[1], N[1], 0, 0, 0, 0, colour, pnFlags(LIT, 1, 4, 0, 0));
    final int b2 = m.vertex(P3, dirs[3], 0, 0, 0, 0, colour, pnFlags(LIT, 2, 4, 0, 0));
    m.tri(a0, a1, a2);
    m.tri(b0, b2, b1); // B wound like A (d2 -> d3 -> d1), shared edge between corners 0 and 2
    final float[][][] got = capture(scene, prog, m, 0);
    final int levelOut = Math.min(4, pnMaxSeg);
    if(got.length != 2 * levelOut * levelOut) {
      fail(set + " watertight: " + got.length + " tam giac, can " + 2 * levelOut * levelOut);
    } else {
      double crack = 0;
      for(int k = 0; k <= levelOut; k++) {
        final double t = k / (double)levelOut;
        final double[] e = pnPoint(P, N, new boolean[3], 1.0, 1 - t, t); // on A's edge c1-c2 (w = 0)
        double[] na = null, nb = null;
        double da = 1e9, db = 1e9;
        for(int tri = 0; tri < got.length; tri++) {
          for(final float[] vtx : got[tri]) {
            final double d = dist(pos(vtx), e);
            if(tri < levelOut * levelOut && d < da) {
              da = d;
              na = pos(vtx);
            }
            if(tri >= levelOut * levelOut && d < db) {
              db = d;
              nb = pos(vtx);
            }
          }
        }
        crack = Math.max(crack, dist(na, nb));
      }
      line.append(String.format("; canh chung 2 tam giac: khe lon nhat %.6f don vi", crack));
      if(crack > 1e-3) {
        fail(set + " watertight: khe " + crack);
      }
    }
    glDeleteProgram(prog);
    glDeleteProgram(bprog);
    System.out.println(line);
  }

  /** index into {e01, e12, e20} of the edge between corners a and b */
  static int edgeIndex(final int a, final int b) {
    final int lo = Math.min(a, b), hi = Math.max(a, b);
    return lo == 0 && hi == 1 ? 0 : lo == 1 && hi == 2 ? 1 : 2;
  }

  // ======================================================================================== 3. pixels

  static final class Target {
    final int fbo, colour, depth;

    Target() {
      this.fbo = glGenFramebuffers();
      glBindFramebuffer(GL_FRAMEBUFFER, this.fbo);
      this.colour = glGenTextures();
      glBindTexture(GL_TEXTURE_2D, this.colour);
      glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, W, H, 0, GL_RGBA, GL_UNSIGNED_BYTE, (ByteBuffer)null);
      glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, this.colour, 0);
      this.depth = glGenRenderbuffers();
      glBindRenderbuffer(GL_RENDERBUFFER, this.depth);
      glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT32F, W, H);
      glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, this.depth);
      if(glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
        throw new IllegalStateException("FBO incomplete");
      }
    }

    void delete() {
      glDeleteFramebuffers(this.fbo);
      glDeleteTextures(this.colour);
      glDeleteRenderbuffers(this.depth);
    }
  }

  record Config(int program, int mode, float discard, int ps1Depth, int ctmdFlags) {
    String label() {
      return String.format("%s chieu %d discard %d ps1Depth %d ctmd 0x%x", PROGRAMS[this.program][0], this.mode, (int)this.discard, this.ps1Depth, this.ctmdFlags);
    }
  }

  static final Map<String, Integer> progCache = new LinkedHashMap<>();

  static int program(final String set, final int program) {
    return progCache.computeIfAbsent(set + "|" + program, k -> {
      final String[] p = PROGRAMS[program];
      final Map<String, String> s = sources.get(set);
      final int prog = link(set + " " + p[0], s.get(p[1]), s.get(p[2]), s.get(p[3]), null);
      if(prog == 0) {
        fail(set + " " + p[0] + " khong link duoc");
      }
      return prog;
    });
  }

  /** RGBA8 + float depth of one frame (all primitives in one draw, depth test LESS, no blending) */
  static int[] render(final Scene scene, final Target target, final String set, final Config c, final Mesh mesh, final float bgW) {
    final int prog = program(set, c.program());
    if(prog == 0) {
      return new int[0];
    }
    scene.setProjection(c.mode());
    if(scene.bgW != bgW) {
      scene.setLight(bgW);
    }
    glBindFramebuffer(GL_FRAMEBUFFER, target.fbo);
    glViewport(0, 0, W, H);
    glDisable(GL_BLEND);
    glDisable(GL_CULL_FACE);
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);
    glClearColor(0.1f, 0.2f, 0.3f, 0.0f);
    glClearDepth(1.0);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    scene.bind(prog);
    setf(prog, "discardTranslucency", c.discard());
    seti(prog, "usePs1Depth", c.ps1Depth());
    seti(prog, "ctmdFlags", c.ctmdFlags());
    scene.draw(mesh.vertexArray(), mesh.indexArray());
    final IntBuffer rgba = BufferUtils.createIntBuffer(W * H);
    glReadPixels(0, 0, W, H, GL_RGBA, GL_UNSIGNED_BYTE, rgba);
    final FloatBuffer depth = BufferUtils.createFloatBuffer(W * H);
    glReadPixels(0, 0, W, H, GL_DEPTH_COMPONENT, GL_FLOAT, depth);
    checkGl("render " + set + " " + c.label());
    final int[] out = new int[W * H * 2];
    for(int i = 0; i < W * H; i++) {
      out[i] = rgba.get(i);
      out[W * H + i] = Float.floatToRawIntBits(depth.get(i));
    }
    return out;
  }

  /** number of pixels whose colour or depth differ */
  static int diffPixels(final int[] a, final int[] b) {
    if(a.length != b.length || a.length == 0) {
      return -1;
    }
    int n = 0;
    for(int i = 0; i < W * H; i++) {
      if(a[i] != b[i] || a[W * H + i] != b[W * H + i]) {
        n++;
      }
    }
    return n;
  }

  static int covered(final int[] a, final int[] clear) {
    int n = 0;
    for(int i = 0; i < W * H; i++) {
      if(a[W * H + i] != clear[W * H + i] || a[i] != clear[i]) {
        n++;
      }
    }
    return n;
  }

  static void pixelTests(final Scene scene) {
    final Target target = new Target();
    final List<Config> configs = new ArrayList<>();
    for(int prog = 0; prog < 2; prog++) {
      for(int mode = 0; mode <= 2; mode++) {
        for(int d = 0; d <= 2; d++) {
          configs.add(new Config(prog, mode, d, mode == 1 ? 1 : 0, 0));
        }
      }
    }
    final Mesh full = soup(4242, 140, false, 0);
    final Mesh fullPn = soup(4242, 140, false, 3);
    final Mesh unaffected = soup(999, 140, true, 0);
    final Mesh empty = new Mesh();
    final String[] same = {"z_off", "pn", "_off", "_pnraw"};

    int frames = 0;
    for(final Config c : configs) {
      final int[] stock = render(scene, target, "stock", c, full, 0.0f);
      final int[] blank = render(scene, target, "stock", c, empty, 0.0f);
      final int cover = covered(stock, blank);
      final StringBuilder line = new StringBuilder(String.format("  %-38s phu %5d px:", c.label(), cover));
      if(cover < W * H / 10) {
        fail(c.label() + ": canh thu phu qua it diem anh (" + cover + ")");
      }
      for(final String v : same) {
        final int d = diffPixels(stock, render(scene, target, v, c, full, 0.0f));
        line.append(String.format(" %s %d", v, d));
        frames++;
        if(d != 0) {
          fail(v + " " + c.label() + ": " + d + " diem anh khac stock (phai giong tung bit)");
        }
      }
      // PN bits must not change stock or l2t (the FS only reads the retail bits; l2t masks them)
      for(final String v : new String[] {"stock", "l2t"}) {
        final int[] a = v.equals("stock") ? stock : render(scene, target, v, c, full, 0.0f);
        final int d = diffPixels(a, render(scene, target, v, c, fullPn, 0.0f));
        line.append(String.format(" %s+bitPN %d", v, d));
        frames += 2;
        if(d != 0) {
          fail(v + " " + c.label() + ": bit PN lam doi hinh (" + d + " diem anh)");
        }
      }
      // l2t / all: untouched primitives identical, touched ones changed
      final int[] stockU = render(scene, target, "stock", c, unaffected, 0.0f);
      for(final String v : new String[] {"l2t", "all"}) {
        final int du = diffPixels(stockU, render(scene, target, v, c, unaffected, 0.0f));
        final int dt = diffPixels(stock, render(scene, target, v, c, full, 0.0f));
        line.append(String.format(" %s(khongcham %d, cham %d)", v, du, dt));
        frames += 2;
        if(du != 0) {
          fail(v + " " + c.label() + ": " + du + " diem anh khac stock tren canh khong co primitive bi L2/T cham");
        }
        if(dt == 0) {
          fail(v + " " + c.label() + ": khong doi gi tren canh co primitive lit (hieu luc?)");
        }
      }
      // z_off with the per-model switch raised = all
      final int[] all = render(scene, target, "all", c, full, 0.0f);
      final int dz = diffPixels(all, render(scene, target, "z_off", c, full, 1.0f));
      line.append(String.format(" z_off(w=1)/all %d", dz));
      frames += 2;
      if(dz != 0) {
        fail("z_off " + c.label() + ": backgroundColour.w = 1 nhung khac all (" + dz + " diem anh)");
      }
      // without PN bits 'all' = 'l2t' (eye vector from the GS on the PN base vs from the VS on the stock base)
      final int dl = diffPixels(all, render(scene, target, "l2t", c, full, 0.0f));
      line.append(String.format(" all/l2t %d", dl));
      frames++;
      if(dl != 0) {
        fail("all " + c.label() + ": khong co bit PN ma khac l2t (" + dl + " diem anh)");
      }
      // PN bits active: pn / all change the picture (not in discard pass 2: it draws only translucent pixels, never PN)
      int[] allPn = null;
      for(final String v : new String[] {"pn", "all"}) {
        final int[] ref = v.equals("all") ? all : stock; // all: compare with itself without PN bits (L2/T change the rest)
        final int[] got = render(scene, target, v, c, fullPn, 0.0f);
        if(v.equals("all")) {
          allPn = got;
        }
        final int d = diffPixels(ref, got);
        line.append(String.format(" %s+bitPN %d", v, d));
        frames++;
        if(c.discard() == 2.0f ? d != 0 : d == 0) {
          fail(v + " " + c.label() + (c.discard() == 2.0f ? ": luot trong suot doi hinh du PN chi cho primitive duc" : ": co bit PN ma hinh khong doi (PN khong chay?)"));
        }
      }
      // z_off: PN bits but backgroundColour.w = 0 (stock SC) -> exactly stock; w = 1 -> exactly all (PN + L2/T)
      final int dzPn = diffPixels(stock, render(scene, target, "z_off", c, fullPn, 0.0f));
      final int dzPnW = diffPixels(allPn, render(scene, target, "z_off", c, fullPn, 1.0f));
      line.append(String.format(" z_off+bitPN %d z_off(w=1)+bitPN/all %d", dzPn, dzPnW));
      frames += 2;
      if(dzPn != 0) {
        fail("z_off " + c.label() + ": co bit PN, backgroundColour.w = 0 (SC goc) ma khac stock " + dzPn + " diem anh (PN phai tat luc chay)");
      }
      if(dzPnW != 0) {
        fail("z_off " + c.label() + ": co bit PN, backgroundColour.w = 1 ma khac all " + dzPnW + " diem anh");
      }
      System.out.println(line);
    }

    // Battle gates: ctmd (0x20) -> neither L2 nor T; l2t/all must equal stock on the full scene
    for(int mode = 1; mode <= 2; mode++) {
      for(int d = 0; d <= 2; d++) {
        final Config c = new Config(1, mode, d, 0, 0x20);
        final int[] stock = render(scene, target, "stock", c, full, 0.0f);
        final StringBuilder line = new StringBuilder(String.format("  %-38s", c.label()));
        for(final String v : new String[] {"l2t", "all", "z_off", "pn"}) {
          final int dd = diffPixels(stock, render(scene, target, v, c, full, 0.0f));
          line.append(String.format(" %s %d", v, dd));
          frames++;
          if(dd != 0) {
            fail(v + " " + c.label() + ": ctmd phai tat L2/T nhung khac stock " + dd + " diem anh");
          }
        }
        System.out.println(line);
      }
    }
    System.out.println("  " + frames + " khung da so");
    for(final int p : progCache.values()) {
      if(p != 0) {
        glDeleteProgram(p);
      }
    }
    progCache.clear();
    target.delete();
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
  }

  static String fmt(final float[] a) {
    return Arrays.toString(a);
  }
}
