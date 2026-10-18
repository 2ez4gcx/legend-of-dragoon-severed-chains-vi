package scvi.remastercheck;

import legend.core.renderer.Mesh;
import legend.core.renderer.MeshObj;
import legend.core.renderer.Obj;
import legend.core.renderer.Translucency;
import legend.core.renderer.VertexOrder;
import legend.game.tmd.TmdObjTable1c;
import org.joml.Vector3f;

import javax.annotation.Nullable;
import java.lang.reflect.Field;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;

/**
 * Bản dựng tham chiếu (viết từ SPEC.md và TmdObjLoader.java affcef0 GỐC — không đọc mã sc-vi):
 * <ul>
 *   <li>{@link #decode}: giải gói live của một phần như TmdObjLoader.fromObjTable :89-186 (specialFlags = 0);</li>
 *   <li>{@link #retail}: lưới gốc y hệt fromObjTable (tên, lớp, thứ tự đảo, 16 float, chỉ số [v+2, v+3, v+1, v+3, v, v+3]...);</li>
 *   <li>{@link #remaster}: lưới remaster một phần mode 1 theo §3.2.2, §3.2.3, §4.3 (bộ VRAM, hoặc bộ ATLAS khi có atlasUv);</li>
 *   <li>{@link #capture}: đọc lưới runtime đã tạo (MeshObj + CaptureApi.RecMesh) về cùng dạng {@link Part};</li>
 *   <li>{@link #digest}: băm RAW / STRICT / NORM; {@link #compare}: so chi tiết, mỗi lỗi có loại (float, flags, triangle,
 *       winding, meshClass...) để tự kiểm (g) biết lỗi gieo bị bắt đúng chỗ.</li>
 * </ul>
 */
public final class RefBuild {
  private RefBuild() { }

  public static final int VS = 16;
  public static final int LIT = 0x1;
  public static final int TEX = 0x2;
  public static final int COL = 0x4;
  public static final int TRANS = 0x8;
  public static final int QUAD = 0x10;
  public static final int OPAQUE = 0;
  public static final int UNTEX_TRANS = 1;
  /** 7 thuộc tính của TmdObjLoader.createMesh: (index, offset, size, stride). */
  public static final long[][] ATTRS = {{0, 0, 4, 16}, {1, 4, 3, 16}, {2, 7, 2, 16}, {3, 9, 1, 16}, {4, 10, 1, 16}, {5, 11, 4, 16}, {6, 15, 1, 16}};
  public static final String OVERLOAD = "indices+flags:STATIC";

  public static final class Face {
    public int index;
    public int header;
    public int vc;
    public boolean quad;
    public boolean textured;
    public boolean translucent;
    public boolean lit;
    public boolean gourad;
    public boolean shaded;
    public boolean coloured;
    public int[] u = new int[4];
    public int[] v = new int[4];
    public int clut;
    public int tpage;
    public int[] colours = new int[4];
    public int[] nidx = new int[4];
    public int[] vidx = new int[4];
    public int flags;
    public int cls;

    public int bpp() {
      return this.tpage >>> 7 & 3;
    }
  }

  public record MeshData(@Nullable String name, boolean textured, boolean translucent, @Nullable Translucency translucency, String order,
                         String overload, long[][] attrs, float[] v, int[] idx) {
    public MeshData withVertices(final float[] nv) {
      return new MeshData(this.name, this.textured, this.translucent, this.translucency, this.order, this.overload, this.attrs, nv, this.idx);
    }

    public MeshData withIndices(final int[] ni) {
      return new MeshData(this.name, this.textured, this.translucent, this.translucency, this.order, this.overload, this.attrs, this.v, ni);
    }

    public MeshData withClass(final boolean tex, final boolean tr, @Nullable final Translucency tl) {
      return new MeshData(this.name, tex, tr, tl, this.order, this.overload, this.attrs, this.v, this.idx);
    }
  }

  /** Một phần: Obj có phải MeshObj, cờ backface, lưới theo thứ tự vẽ (layer). */
  public record Part(boolean meshObj, boolean backface, List<MeshData> meshes) { }

  static int u16(final byte[] d, final int o) {
    return d[o] & 0xff | (d[o + 1] & 0xff) << 8;
  }

  static int s32(final byte[] d, final int o) {
    return d[o] & 0xff | (d[o + 1] & 0xff) << 8 | (d[o + 2] & 0xff) << 16 | d[o + 3] << 24;
  }

  // ---------------------------------------------------------------- giải gói

  public static List<Face> decode(final TmdObjTable1c t) {
    final List<Face> faces = new ArrayList<>();
    for(final TmdObjTable1c.Primitive p : t.primitives_10) {
      final int command = p.header() & 0xff04_0000;
      final int id = command >>> 24;
      if((id >>> 5 & 0b11) != 1) {
        throw new RuntimeException("Unsupported primitive type");
      }
      final boolean shaded = (command & 0x4_0000) != 0;
      final boolean gourad = (id & 0x10) != 0;
      final boolean quad = (id & 0x8) != 0;
      final boolean textured = (id & 0x4) != 0;
      final boolean translucent = (id & 0x2) != 0;
      final boolean lit = (id & 0x1) == 0;
      if(textured && shaded) {
        throw new RuntimeException("Invalid primitive type");
      }
      if(!textured && !lit) {
        throw new RuntimeException("Invalid primitive type");
      }
      final int vc = quad ? 4 : 3;
      final boolean coloured = shaded || !lit || !textured;
      for(final byte[] d : p.data()) {
        final Face f = new Face();
        f.index = faces.size();
        f.header = p.header();
        f.vc = vc;
        f.quad = quad;
        f.textured = textured;
        f.translucent = translucent;
        f.lit = lit;
        f.gourad = gourad;
        f.shaded = shaded;
        f.coloured = coloured;
        int o = 0;
        if(textured) {
          for(int k = 0; k < vc; k++) {
            f.u[k] = d[o++] & 0xff;
            f.v[k] = d[o++] & 0xff;
            if(k == 0) {
              f.clut = u16(d, o);
            } else if(k == 1) {
              f.tpage = u16(d, o);
            }
            o += 2;
          }
        }
        if(shaded || !lit) {
          for(int k = 0; k < vc; k++) {
            f.colours[k] = s32(d, o);
            o += 4;
          }
        } else if(!textured) {
          final int c = s32(d, o);
          o += 4;
          for(int k = 0; k < vc; k++) {
            f.colours[k] = c;
          }
        }
        for(int k = 0; k < vc; k++) {
          if(lit) {
            if(gourad || k == 0) {
              f.nidx[k] = u16(d, o);
              o += 2;
            } else {
              f.nidx[k] = f.nidx[0];
            }
          }
          f.vidx[k] = u16(d, o);
          o += 2;
        }
        int fl = 0;
        if(lit) {
          fl |= LIT;
        }
        if(textured) {
          fl |= TEX;
        }
        if(coloured) {
          fl |= COL;
        }
        if(translucent) {
          fl |= TRANS;
        }
        if(quad) {
          fl |= QUAD;
        }
        f.flags = fl;
        f.cls = translucent && textured ? 2 + (f.tpage >>> 5 & 3) : translucent ? UNTEX_TRANS : OPAQUE;
        faces.add(f);
      }
    }
    return faces;
  }

  public static boolean backface(final List<Face> faces) {
    for(final Face f : faces) {
      if(f.translucent && !f.textured) {
        return false;
      }
    }
    return true;
  }

  public static boolean anyTextured(final List<Face> faces) {
    for(final Face f : faces) {
      if(f.textured) {
        return true;
      }
    }
    return false;
  }

  public static float[] normal(final TmdObjTable1c t, final int idx) {
    if(idx >= t.normal_top_08.length) {
      return new float[3];
    }
    final Vector3f n = t.normal_top_08[idx];
    return new float[] {n.x, n.y, n.z};
  }

  static void colour(final int c, final boolean textured, final float[] out, final int o) {
    out[o] = (c & 0xff) / 255.0f;
    out[o + 1] = (c >>> 8 & 0xff) / 255.0f;
    out[o + 2] = (c >>> 16 & 0xff) / 255.0f;
    out[o + 3] = (c >>> 24 & 0xff) / 255.0f;
    if(textured) {
      out[o] *= 2.0f;
      out[o + 1] *= 2.0f;
      out[o + 2] *= 2.0f;
      out[o + 3] *= 2.0f;
    }
  }

  /** Thứ tự lớp như getTranslucencySizes + đảo (:309-326): opaque, untextured translucent, Translucency theo ordinal, rồi đảo. */
  static int[] classOrder(final boolean[] present) {
    final List<Integer> order = new ArrayList<>();
    for(int c = 0; c < 6; c++) {
      if(present[c]) {
        order.add(c);
      }
    }
    final int[] out = new int[order.size()];
    for(int i = 0; i < out.length; i++) {
      out[i] = order.get(out.length - 1 - i);
    }
    return out;
  }

  static String className(final int c) {
    return c == OPAQUE ? "opaque" : c == UNTEX_TRANS ? "untextured translucent" : Translucency.values()[c - 2].toString();
  }

  // ---------------------------------------------------------------- lưới gốc

  /** = TmdObjLoader.fromObjTable(partName, t, 0, tw, th) (gốc affcef0). */
  public static Part retail(final String partName, final TmdObjTable1c t, final int tw, final int th) {
    final List<Face> faces = decode(t);
    final boolean anyTex = anyTextured(faces);
    final boolean[] present = new boolean[6];
    final int[] vcount = new int[6];
    final int[] icount = new int[6];
    for(final Face f : faces) {
      present[f.cls] = true;
      vcount[f.cls] += f.vc;
      icount[f.cls] += f.quad ? 12 : 6;
    }
    final float[][] verts = new float[6][];
    final int[][] idx = new int[6][];
    final int[] vo = new int[6];
    final int[] io = new int[6];
    final int[] vi = new int[6];
    for(int c = 0; c < 6; c++) {
      verts[c] = new float[vcount[c] * VS];
      idx[c] = new int[icount[c]];
    }
    for(final Face f : faces) {
      final int c = f.cls;
      final int[] ix = idx[c];
      final int base = vi[c];
      final int a1 = base + 3;
      final int a2 = base;
      ix[io[c]++] = base + 2;
      ix[io[c]++] = a1;
      ix[io[c]++] = base + 1;
      ix[io[c]++] = a1;
      ix[io[c]++] = base;
      ix[io[c]++] = a1;
      if(f.quad) {
        ix[io[c]++] = base + 1;
        ix[io[c]++] = a2;
        ix[io[c]++] = base + 2;
        ix[io[c]++] = a2;
        ix[io[c]++] = base + 3;
        ix[io[c]++] = a2;
      }
      final float[] vs = verts[c];
      for(int k = 0; k < f.vc; k++) {
        int o = vo[c];
        final Vector3f p = t.vert_top_00[f.vidx[k]];
        vs[o] = p.x;
        vs[o + 1] = p.y;
        vs[o + 2] = p.z;
        vs[o + 3] = f.vidx[k];
        o += 4;
        if(f.lit) {
          final float[] n = normal(t, f.nidx[k]);
          vs[o] = n[0];
          vs[o + 1] = n[1];
          vs[o + 2] = n[2];
        }
        o += 3;
        if(f.textured) {
          if(f.bpp() == 3) {
            if((tw | th) == 0) {
              throw new RuntimeException("24bpp textures must have texture width/height specified");
            }
            vs[o] = (float)f.u[k] / tw;
            vs[o + 1] = (float)f.v[k] / th;
          } else {
            vs[o] = f.u[k];
            vs[o + 1] = f.v[k];
          }
          vs[o + 2] = f.tpage;
          vs[o + 3] = f.clut;
        }
        o += 4;
        if(f.coloured) {
          colour(f.colours[k], f.textured, vs, o);
        } else {
          vs[o] = 1.0f;
          vs[o + 1] = 1.0f;
          vs[o + 2] = 1.0f;
          vs[o + 3] = 1.0f;
        }
        o += 4;
        vs[o++] = f.flags;
        vo[c] = o;
      }
      vi[c] += f.vc;
    }
    final List<MeshData> meshes = new ArrayList<>();
    for(final int c : classOrder(present)) {
      final boolean[] props = props(c, anyTex);
      meshes.add(new MeshData(partName + " (" + className(c) + ')', props[0], props[1], c >= 2 ? Translucency.values()[c - 2] : null,
        VertexOrder.TRIANGLES_ADJACENCY.name(), OVERLOAD, ATTRS, verts[c], idx[c]));
    }
    return new Part(true, backface(faces), meshes);
  }

  /** (textured, translucent) truyền cho makeMesh theo lớp (§4.3 mục 2). */
  static boolean[] props(final int c, final boolean anyTex) {
    if(c == OPAQUE) {
      return new boolean[] {anyTex, false};
    }
    if(c == UNTEX_TRANS) {
      return new boolean[] {false, true};
    }
    return new boolean[] {anyTex, true};
  }

  // ---------------------------------------------------------------- lưới remaster (§3.2, §4.3)

  /** Trọng số §3.2.2 (float Java, không FMA). */
  public static float[] weights(final int S, final int T, final boolean quad) {
    final float s = (float)S / 65535.0f;
    float t = (float)T / 65535.0f;
    if(quad) {
      return new float[] {(1.0f - s) * (1.0f - t), s * (1.0f - t), (1.0f - s) * t, s * t};
    }
    if(s + t > 1.0f) {
      t = 1.0f - s;
    }
    return new float[] {(1.0f - s) - t, s, t};
  }

  /** I(x) = ((w0*x0 + w1*x1) + w2*x2) [+ w3*x3]. */
  public static float interp(final float[] w, final float[] x) {
    float acc = w[0] * x[0];
    for(int k = 1; k < w.length; k++) {
      acc = acc + w[k] * x[k];
    }
    return acc;
  }

  /**
   * Lưới một phần mode 1. atlasUv = null: bộ VRAM; khác null: bộ ATLAS của một biến thể (n*8 float), live[g] = mặt g (chỉ số
   * toàn cục) LIVE cho biến thể đó (§3.4 a-d). texBase = chỉ số toàn cục của mặt có texture đầu tiên của phần.
   */
  public static Part remaster(final TmdObjTable1c t, final List<Face> faces, final RefLrm.Part lp, final int tw, final int th,
                              @Nullable final float[] atlasUv, @Nullable final boolean[] live, final int texBase) {
    final boolean anyTex = anyTextured(faces);
    final int[] texIndex = new int[faces.size()];
    int g = texBase;
    for(final Face f : faces) {
      texIndex[f.index] = f.textured ? g++ : -1;
    }
    final boolean[] present = new boolean[6];
    final int[] triCls = new int[lp.T];
    for(int i = 0; i < lp.T; i++) {
      triCls[i] = faces.get(lp.cSrc[lp.tri[3 * i]]).cls;
      present[triCls[i]] = true;
    }
    final List<MeshData> meshes = new ArrayList<>();
    for(final int c : classOrder(present)) {
      final int[] local = new int[lp.C];
      int count = 0;
      for(int i = 0; i < lp.C; i++) {
        local[i] = faces.get(lp.cSrc[i]).cls == c ? count++ : -1;
      }
      final float[] vs = new float[count * VS];
      int o = 0;
      final float[] xs = new float[4];
      for(int i = 0; i < lp.C; i++) {
        if(local[i] < 0) {
          continue;
        }
        final Face f = faces.get(lp.cSrc[i]);
        final int pp = lp.cPos[i];
        vs[o] = lp.pos[3 * pp];
        vs[o + 1] = lp.pos[3 * pp + 1];
        vs[o + 2] = lp.pos[3 * pp + 2];
        vs[o + 3] = lp.cNear[i];
        if(f.lit) {
          vs[o + 4] = lp.cN[3 * i];
          vs[o + 5] = lp.cN[3 * i + 1];
          vs[o + 6] = lp.cN[3 * i + 2];
        }
        final float[] w = weights(lp.cS[i], lp.cT[i], f.quad);
        final float[] xk = f.vc == 4 ? xs : new float[3];
        if(f.textured) {
          final int gi = texIndex[f.index];
          if(atlasUv != null && (live == null || !live[gi])) {
            for(int k = 0; k < f.vc; k++) {
              xk[k] = atlasUv[gi * 8 + k * 2];
            }
            vs[o + 7] = interp(w, xk);
            for(int k = 0; k < f.vc; k++) {
              xk[k] = atlasUv[gi * 8 + k * 2 + 1];
            }
            vs[o + 8] = interp(w, xk);
            vs[o + 9] = f.tpage & ~0x180 | 0x180;
          } else {
            for(int k = 0; k < f.vc; k++) {
              xk[k] = f.u[k];
            }
            float u = interp(w, xk);
            for(int k = 0; k < f.vc; k++) {
              xk[k] = f.v[k];
            }
            float v = interp(w, xk);
            if(f.bpp() == 3) {
              if((tw | th) == 0) {
                throw new RuntimeException("24bpp textures must have texture width/height specified");
              }
              u = u / (float)tw;
              v = v / (float)th;
            }
            vs[o + 7] = u;
            vs[o + 8] = v;
            vs[o + 9] = f.tpage;
          }
          vs[o + 10] = f.clut;
        }
        if(f.coloured) {
          final float[] cols = new float[16];
          for(int k = 0; k < f.vc; k++) {
            colour(f.colours[k], f.textured, cols, 4 * k);
          }
          for(int ch = 0; ch < 4; ch++) {
            for(int k = 0; k < f.vc; k++) {
              xk[k] = cols[4 * k + ch];
            }
            vs[o + 11 + ch] = interp(w, xk);
          }
        } else {
          vs[o + 11] = 1.0f;
          vs[o + 12] = 1.0f;
          vs[o + 13] = 1.0f;
          vs[o + 14] = 1.0f;
        }
        vs[o + 15] = f.flags & ~QUAD;
        o += VS;
      }
      int n = 0;
      for(int i = 0; i < lp.T; i++) {
        if(triCls[i] == c) {
          n++;
        }
      }
      final int[] idx = new int[6 * n];
      int k = 0;
      for(int i = 0; i < lp.T; i++) {
        if(triCls[i] != c) {
          continue;
        }
        final int a = local[lp.tri[3 * i]];
        final int b = local[lp.tri[3 * i + 1]];
        final int d = local[lp.tri[3 * i + 2]];
        idx[k++] = a;
        idx[k++] = a;
        idx[k++] = b;
        idx[k++] = a;
        idx[k++] = d;
        idx[k++] = a;
      }
      final boolean[] props = props(c, anyTex);
      meshes.add(new MeshData(null, props[0], props[1], c >= 2 ? Translucency.values()[c - 2] : null, VertexOrder.TRIANGLES_ADJACENCY.name(),
        OVERLOAD, ATTRS, vs, idx));
    }
    return new Part(true, backface(faces), meshes);
  }

  // ---------------------------------------------------------------- đọc lưới runtime

  private static final Field BACKFACE;

  static {
    try {
      BACKFACE = MeshObj.class.getDeclaredField("backfaceCulling");
      BACKFACE.setAccessible(true);
    } catch(final NoSuchFieldException e) {
      throw new RuntimeException(e);
    }
  }

  public static boolean backfaceOf(final MeshObj obj) {
    try {
      return BACKFACE.getBoolean(obj);
    } catch(final IllegalAccessException e) {
      throw new RuntimeException(e);
    }
  }

  /** Lưới bộ VRAM (= MeshObj.meshes) của Obj runtime. null nếu obj null. */
  @Nullable
  public static Part capture(@Nullable final Obj obj) {
    if(obj == null) {
      return null;
    }
    if(!(obj instanceof final MeshObj mo)) {
      return new Part(false, obj.useBackfaceCulling(), List.of());
    }
    final List<MeshData> meshes = new ArrayList<>();
    for(final Mesh m : mo.meshes) {
      meshes.add(of(m));
    }
    return new Part(true, backfaceOf(mo), meshes);
  }

  public static MeshData of(final Mesh m) {
    if(m instanceof final CaptureApi.RecMesh r) {
      return new MeshData(r.name, r.textured, r.translucent, r.translucency, r.order.name(), r.overload,
        r.attributes.toArray(long[][]::new), r.vertices, r.indices == null ? new int[0] : r.indices);
    }
    return new MeshData("FOREIGN " + m.getClass().getName(), m.textured(), m.translucent(), m.translucencyMode(), "?", "?", new long[0][], m.vertices(), new int[0]);
  }

  // ---------------------------------------------------------------- băm

  public static final int RAW = 0;
  public static final int STRICT = 1;
  public static final int NORM = 2;

  /** 16 hex đầu của SHA-1. RAW: có tên lưới. STRICT: không tên. NORM: không tên, xoá QUAD_FLAG, ô kề = đỉnh đầu tam giác. */
  private static final ThreadLocal<MessageDigest> MD = ThreadLocal.withInitial(RefKey::sha1);
  private static final ThreadLocal<ByteBuffer> BUF = ThreadLocal.withInitial(() -> ByteBuffer.allocate(1 << 16).order(ByteOrder.LITTLE_ENDIAN));

  public static String digest(@Nullable final Part p, final int kind) {
    if(p == null) {
      return "null";
    }
    final MessageDigest md = MD.get();
    md.reset();
    final ByteBuffer b = BUF.get();
    b.clear();
    b.put((byte)(p.meshObj() ? 1 : 0)).put((byte)(p.backface() ? 1 : 0)).putInt(p.meshes().size());
    for(final MeshData m : p.meshes()) {
      if(kind == RAW) {
        final byte[] n = String.valueOf(m.name()).getBytes(java.nio.charset.StandardCharsets.UTF_8);
        b.putInt(n.length).put(n);
      }
      b.put((byte)(m.textured() ? 1 : 0)).put((byte)(m.translucent() ? 1 : 0)).putInt(m.translucency() == null ? -1 : m.translucency().ordinal());
      final byte[] o = (m.order() + '|' + m.overload()).getBytes(java.nio.charset.StandardCharsets.UTF_8);
      b.putInt(o.length).put(o);
      b.putInt(m.attrs().length);
      for(final long[] a : m.attrs()) {
        for(final long x : a) {
          b.putLong(x);
        }
      }
      b.putInt(m.v().length);
      flush(md, b);
      for(int i = 0; i < m.v().length; i++) {
        float f = m.v()[i];
        if(kind == NORM && i % VS == VS - 1) {
          f = (int)f & ~QUAD;
        }
        if(b.remaining() < 4) {
          flush(md, b);
        }
        b.putInt(Float.floatToRawIntBits(f));
      }
      if(b.remaining() < 4) {
        flush(md, b);
      }
      b.putInt(m.idx().length);
      for(int i = 0; i < m.idx().length; i++) {
        int x = m.idx()[i];
        if(kind == NORM && (i % 6 & 1) == 1) {
          x = m.idx()[i - i % 6];
        }
        if(b.remaining() < 4) {
          flush(md, b);
        }
        b.putInt(x);
      }
      flush(md, b);
    }
    flush(md, b);
    return RefKey.HEX.formatHex(md.digest(), 0, 8);
  }

  private static void flush(final MessageDigest md, final ByteBuffer b) {
    b.flip();
    md.update(b);
    b.clear();
  }

  public static byte[] floatsLE(final float[] v) {
    final ByteBuffer b = ByteBuffer.allocate(v.length * 4).order(ByteOrder.LITTLE_ENDIAN);
    for(final float f : v) {
      b.putFloat(f);
    }
    return b.array();
  }

  public static byte[] intsLE(final int[] v) {
    final ByteBuffer b = ByteBuffer.allocate(v.length * 4).order(ByteOrder.LITTLE_ENDIAN);
    for(final int x : v) {
      b.putInt(x);
    }
    return b.array();
  }

  // ---------------------------------------------------------------- so sánh chi tiết

  /**
   * So lưới mong đợi với lưới thực tế. names: có so tên lưới không. Trả về danh sách lỗi "loại: chi tiết" (rỗng = khớp).
   * Loại: obj, backface, meshCount, meshClass, order, attrs, name, vertexCount, float, flags, indexCount, triangle, winding,
   * rotation, adjacency.
   */
  public static List<String> compare(@Nullable final Part exp, @Nullable final Part act, final boolean names) {
    final List<String> err = new ArrayList<>();
    if(exp == null || act == null) {
      if(exp != act) {
        err.add("obj: " + (exp == null ? "khong mong doi Obj" : "khong co Obj"));
      }
      return err;
    }
    if(exp.meshObj() != act.meshObj()) {
      err.add("obj: MeshObj " + exp.meshObj() + " vs " + act.meshObj());
      return err;
    }
    if(exp.backface() != act.backface()) {
      err.add("backface: " + exp.backface() + " vs " + act.backface());
    }
    if(exp.meshes().size() != act.meshes().size()) {
      err.add("meshCount: " + exp.meshes().size() + " vs " + act.meshes().size() + " luoi " + classes(exp) + " vs " + classes(act));
      return err;
    }
    for(int mi = 0; mi < exp.meshes().size(); mi++) {
      final MeshData e = exp.meshes().get(mi);
      final MeshData a = act.meshes().get(mi);
      final String at = "luoi " + mi + ' ';
      if(e.textured() != a.textured() || e.translucent() != a.translucent() || e.translucency() != a.translucency()) {
        err.add("meshClass: " + at + cls(e) + " vs " + cls(a));
      }
      if(!e.order().equals(a.order()) || !e.overload().equals(a.overload())) {
        err.add("order: " + at + e.order() + '/' + e.overload() + " vs " + a.order() + '/' + a.overload());
      }
      if(!java.util.Arrays.deepEquals(e.attrs(), a.attrs())) {
        err.add("attrs: " + at + attrs(e.attrs()) + " vs " + attrs(a.attrs()));
      }
      if(names && !String.valueOf(e.name()).equals(String.valueOf(a.name()))) {
        err.add("name: " + at + e.name() + " vs " + a.name());
      }
      if(e.v().length != a.v().length) {
        err.add("vertexCount: " + at + e.v().length / VS + " vs " + a.v().length / VS + " dinh");
      } else {
        for(int i = 0; i < e.v().length; i++) {
          if(Float.floatToRawIntBits(e.v()[i]) != Float.floatToRawIntBits(a.v()[i])) {
            final int comp = i % VS;
            err.add((comp == VS - 1 ? "flags: " : "float: ") + at + "dinh " + i / VS + " thanh phan " + comp + ": " + e.v()[i] + " vs " + a.v()[i]);
            break;
          }
        }
      }
      compareIndices(e.idx(), a.idx(), at, err);
    }
    return err;
  }

  private static void compareIndices(final int[] e, final int[] a, final String at, final List<String> err) {
    if(e.length != a.length) {
      err.add("indexCount: " + at + e.length / 6 + " vs " + a.length / 6 + " tam giac");
      return;
    }
    for(int t = 0; t + 5 < e.length; t += 6) {
      final int e0 = e[t];
      final int e1 = e[t + 2];
      final int e2 = e[t + 4];
      final int a0 = a[t];
      final int a1 = a[t + 2];
      final int a2 = a[t + 4];
      if(e0 != a0 || e1 != a1 || e2 != a2) {
        final int[] es = {e0, e1, e2};
        final int[] as = {a0, a1, a2};
        java.util.Arrays.sort(es);
        java.util.Arrays.sort(as);
        if(!java.util.Arrays.equals(es, as)) {
          err.add("triangle: " + at + "tam giac " + t / 6 + ": (" + e0 + ',' + e1 + ',' + e2 + ") vs (" + a0 + ',' + a1 + ',' + a2 + ')');
        } else if(a0 == e1 && a1 == e2 && a2 == e0 || a0 == e2 && a1 == e0 && a2 == e1) {
          err.add("rotation: " + at + "tam giac " + t / 6 + ": (" + e0 + ',' + e1 + ',' + e2 + ") vs (" + a0 + ',' + a1 + ',' + a2 + ')');
        } else {
          err.add("winding: " + at + "tam giac " + t / 6 + ": (" + e0 + ',' + e1 + ',' + e2 + ") vs (" + a0 + ',' + a1 + ',' + a2 + ')');
        }
        return;
      }
      if(e[t + 1] != a[t + 1] || e[t + 3] != a[t + 3] || e[t + 5] != a[t + 5]) {
        err.add("adjacency: " + at + "tam giac " + t / 6 + ": [" + e[t + 1] + ',' + e[t + 3] + ',' + e[t + 5] + "] vs [" + a[t + 1] + ',' + a[t + 3] + ',' + a[t + 5] + ']');
        return;
      }
    }
  }

  static String cls(final MeshData m) {
    return (m.textured() ? "T" : "-") + (m.translucent() ? "R" : "-") + (m.translucency() == null ? "" : ":" + m.translucency());
  }

  static String classes(final Part p) {
    final StringBuilder sb = new StringBuilder("[");
    for(final MeshData m : p.meshes()) {
      if(sb.length() > 1) {
        sb.append(' ');
      }
      sb.append(cls(m));
    }
    return sb.append(']').toString();
  }

  static String attrs(final long[][] a) {
    final StringBuilder sb = new StringBuilder();
    for(final long[] x : a) {
      sb.append(java.util.Arrays.toString(x));
    }
    return sb.toString();
  }

  /** Bản "đã chuẩn hoá identity" của lưới gốc: xoá QUAD_FLAG, ô kề = đỉnh đầu, bỏ tên (mong đợi của bộ VRAM L0 identity). */
  public static Part normalized(final Part p) {
    final List<MeshData> out = new ArrayList<>();
    for(final MeshData m : p.meshes()) {
      final float[] v = m.v().clone();
      for(int i = VS - 1; i < v.length; i += VS) {
        v[i] = (int)v[i] & ~QUAD;
      }
      final int[] idx = m.idx().clone();
      for(int i = 0; i < idx.length; i++) {
        if((i % 6 & 1) == 1) {
          idx[i] = idx[i - i % 6];
        }
      }
      out.add(new MeshData(null, m.textured(), m.translucent(), m.translucency(), m.order(), m.overload(), m.attrs(), v, idx));
    }
    return new Part(p.meshObj(), p.backface(), out);
  }
}
