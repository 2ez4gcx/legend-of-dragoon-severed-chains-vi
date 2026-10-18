package scvi.remastercheck;

import legend.game.tmd.TmdObjTable1c;

import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.zip.DataFormatException;
import java.util.zip.Deflater;
import java.util.zip.Inflater;

/**
 * Đọc / kiểm / ghi file LRM1 (SPEC §3.5), viết lại độc lập từ SPEC.md, cộng bộ sinh file L0 identity.
 *
 * {@link #read(byte[], Runtime)} kiểm ĐỦ danh sách §3.5.4 (sai một điều -> {@link Invalid} kèm lý do); mọi số đếm đọc từ file
 * được kiểm với số byte còn lại TRƯỚC khi cấp phát (mục 3). Các giá trị §3.5.4 ghi "không kiểm (hợp lệ)" được chấp nhận:
 * giá trị faceHash, S/T, độ dài pháp tuyến, corner không được tam giác nào dùng, atlasUv góc thứ 4 của mặt tam giác.
 * {@link #write(Lrm, boolean)} ghi xác định (thân không nén) hoặc nén zlib mức 9 (bit 0 của flags).
 * {@link #identity(TmdObjTable1c[], String)} dựng bản L0 identity: mỗi phần mode 1, P = đỉnh TMD, corner theo từng góc TMD với
 * (S, T) ∈ {0, 65535}, nearest = chỉ số đỉnh của chính góc, tam giác theo thứ tự phát của SC: (2, 1, 0) và với tứ giác thêm (1, 2, 3).
 */
public final class RefLrm {
  private RefLrm() { }

  public static final int HEADER = 0x40;
  public static final int MAX_PARTS = 64;
  public static final int MAX_VARIANTS = 4;
  public static final long MAX_PCT = 200_000;
  public static final long MAX_BODY = 0x1000_0000L;
  public static final int MAX_TEX = 2048;

  /** File không hợp lệ theo §3.5.4. */
  public static final class Invalid extends Exception {
    public final String rule;

    public Invalid(final String rule, final String msg) {
      super(rule + ": " + msg);
      this.rule = rule;
    }
  }

  public static final class Part {
    public byte[] key;
    public long srcFaceCount;
    public int mode;
    public int P;
    public int C;
    public int T;
    public float[] pos = new float[0];       // 3P
    public int[] cPos = new int[0];
    public float[] cN = new float[0];        // 3C
    public int[] cSrc = new int[0];
    public int[] cS = new int[0];
    public int[] cT = new int[0];
    public int[] cNear = new int[0];
    public int[] cRole = new int[0];
    public int[] tri = new int[0];           // 3T

    public Part copy() {
      final Part p = new Part();
      p.key = this.key.clone();
      p.srcFaceCount = this.srcFaceCount;
      p.mode = this.mode;
      p.P = this.P;
      p.C = this.C;
      p.T = this.T;
      p.pos = this.pos.clone();
      p.cPos = this.cPos.clone();
      p.cN = this.cN.clone();
      p.cSrc = this.cSrc.clone();
      p.cS = this.cS.clone();
      p.cT = this.cT.clone();
      p.cNear = this.cNear.clone();
      p.cRole = this.cRole.clone();
      p.tri = this.tri.clone();
      return p;
    }
  }

  public static final class Variant {
    public byte[] png;
    public int w;
    public int h;
    public int n;
    public int[] faceHash;
    public float[] atlasUv;                  // n * 8 (4 góc x (u, v))

    public Variant copy() {
      final Variant v = new Variant();
      v.png = this.png.clone();
      v.w = this.w;
      v.h = this.h;
      v.n = this.n;
      v.faceHash = this.faceHash.clone();
      v.atlasUv = this.atlasUv.clone();
      return v;
    }
  }

  public static final class Lrm {
    public byte[] modelKey;
    public int flags;
    public int level;
    public String generator = "";
    public long bodySize;
    public Part[] parts;
    public Variant[] variants = new Variant[0];

    public Lrm copy() {
      final Lrm l = new Lrm();
      l.modelKey = this.modelKey.clone();
      l.flags = this.flags;
      l.level = this.level;
      l.generator = this.generator;
      l.bodySize = this.bodySize;
      l.parts = Arrays.stream(this.parts).map(Part::copy).toArray(Part[]::new);
      l.variants = Arrays.stream(this.variants).map(Variant::copy).toArray(Variant[]::new);
      return l;
    }
  }

  /** Số liệu runtime của mô hình đang nạp (để kiểm mục 4-7 của §3.5.4). */
  public record Runtime(byte[] modelKey, int[] srcFaceCounts, int[] nVerts, int[] texturedVc) {
    public int partCount() {
      return this.srcFaceCounts.length;
    }

    public int texturedFaceCount() {
      return this.texturedVc.length;
    }

    public static Runtime of(final TmdObjTable1c[] parts) {
      final int[] sfc = new int[parts.length];
      final int[] nv = new int[parts.length];
      final List<Integer> vcs = new ArrayList<>();
      for(int i = 0; i < parts.length; i++) {
        sfc[i] = RefKey.packetCount(parts[i]);
        nv[i] = parts[i].vert_top_00.length;
        for(final TmdObjTable1c.Primitive p : parts[i].primitives_10) {
          final int id = p.header() >>> 24;
          if((id & 4) != 0) {
            for(int k = 0; k < p.data().length; k++) {
              vcs.add((id & 8) != 0 ? 4 : 3);
            }
          }
        }
      }
      return new Runtime(RefKey.modelKey(RefKey.partKeys(parts)), sfc, nv, vcs.stream().mapToInt(Integer::intValue).toArray());
    }
  }

  // ---------------------------------------------------------------- đọc + kiểm

  private static final class Cursor {
    final ByteBuffer b;

    Cursor(final byte[] body) {
      this.b = ByteBuffer.wrap(body).order(ByteOrder.LITTLE_ENDIAN);
    }

    long remaining() {
      return this.b.remaining();
    }

    void need(final long n, final String what) throws Invalid {
      if(n < 0 || n > this.b.remaining()) {
        throw new Invalid("truncated", "than bi cat (" + what + " can " + n + " byte, con " + this.b.remaining() + ")");
      }
    }

    byte[] bytes(final int n, final String what) throws Invalid {
      this.need(n, what);
      final byte[] out = new byte[n];
      this.b.get(out);
      return out;
    }

    long u32(final String what) throws Invalid {
      this.need(4, what);
      return this.b.getInt() & 0xffff_ffffL;
    }

    int u16(final String what) throws Invalid {
      this.need(2, what);
      return this.b.getShort() & 0xffff;
    }

    int u8(final String what) throws Invalid {
      this.need(1, what);
      return this.b.get() & 0xff;
    }

    float f32() {
      return this.b.getFloat();
    }
  }

  static int u16(final byte[] d, final int o) {
    return d[o] & 0xff | (d[o + 1] & 0xff) << 8;
  }

  static long u32(final byte[] d, final int o) {
    return (d[o] & 0xff | (d[o + 1] & 0xff) << 8 | (d[o + 2] & 0xff) << 16 | (long)(d[o + 3] & 0xff) << 24) & 0xffff_ffffL;
  }

  /**
   * Kiểm đủ §3.5.4. rt = null: chỉ kiểm phần không cần mô hình runtime (mục 1-3, 6, 7 trừ so với runtime, toàn vẹn khoá);
   * khi đó quy tắc "atlasUv góc thứ 4 của mặt tam giác không kiểm" không áp được nên mọi góc đều được kiểm.
   */
  public static Lrm read(final byte[] data, final Runtime rt) throws Invalid {
    return read(data, rt, java.util.Set.of());
  }

  /** ignore: luật bỏ qua (chỉ để MockRuntime gieo lỗi "bộ kiểm lỏng" cho tự kiểm): role, zero, near, triOrder, atlasUv. */
  public static Lrm read(final byte[] data, final Runtime rt, final java.util.Set<String> ignore) throws Invalid {
    if(data.length < HEADER) {
      throw new Invalid("header", "file ngan hon 0x40 byte");
    }
    if(data[0] != 'L' || data[1] != 'R' || data[2] != 'M' || data[3] != '1') {
      throw new Invalid("header", "magic sai");
    }
    final int version = u16(data, 4);
    final int flags = u16(data, 6);
    if(version != 1) {
      throw new Invalid("header", "version " + version);
    }
    if((flags & ~1) != 0) {
      throw new Invalid("header", "flags co bit la 0x" + Integer.toHexString(flags));
    }
    final Lrm l = new Lrm();
    l.flags = flags;
    l.modelKey = Arrays.copyOfRange(data, 8, 28);
    final int partCount = u16(data, 0x1c);
    final int variantCount = u16(data, 0x1e);
    l.bodySize = u32(data, 0x20);
    l.level = data[0x24] & 0xff;
    if(data[0x25] != 0 || data[0x26] != 0 || data[0x27] != 0) {
      throw new Invalid("header", "byte zero 0x25..0x27 != 0");
    }
    boolean zero = false;
    final StringBuilder gen = new StringBuilder();
    for(int i = 0x28; i < 0x40; i++) {
      final int c = data[i] & 0xff;
      if(zero) {
        if(c != 0) {
          throw new Invalid("header", "generator: byte khac 0 sau byte 0");
        }
      } else if(c == 0) {
        zero = true;
      } else if(c < 0x20 || c > 0x7e) {
        throw new Invalid("header", "generator: byte ngoai ASCII 0x20..0x7e");
      } else {
        gen.append((char)c);
      }
    }
    l.generator = gen.toString();
    if(partCount < 1 || partCount > MAX_PARTS) {
      throw new Invalid("header", "partCount " + partCount);
    }
    if(variantCount > MAX_VARIANTS) {
      throw new Invalid("header", "variantCount " + variantCount);
    }
    if(l.level > 2) {
      throw new Invalid("header", "level " + l.level);
    }
    if(l.bodySize > MAX_BODY) {
      throw new Invalid("header", "bodySize " + l.bodySize);
    }
    if(rt != null && partCount != rt.partCount()) {
      throw new Invalid("partCount", "partCount " + partCount + " != so phan runtime " + rt.partCount());
    }

    // mục 2: thân
    final byte[] body;
    if((flags & 1) != 0) {
      body = inflate(Arrays.copyOfRange(data, HEADER, data.length), l.bodySize);
    } else {
      if(data.length - HEADER != l.bodySize) {
        throw new Invalid("body", "bodySize " + l.bodySize + " != " + (data.length - HEADER) + " byte con lai");
      }
      body = Arrays.copyOfRange(data, HEADER, data.length);
    }

    final Cursor c = new Cursor(body);
    l.parts = new Part[partCount];
    for(int pi = 0; pi < partCount; pi++) {
      final Part p = new Part();
      l.parts[pi] = p;
      p.key = c.bytes(20, "partKey");
      p.srcFaceCount = c.u32("srcFaceCount");
      p.mode = c.u8("mode");
      if(c.u8("zero") != 0 | c.u8("zero") != 0 | c.u8("zero") != 0) {
        throw new Invalid("zero", "phan " + pi + ": byte zero != 0");
      }
      if(p.mode != 0 && p.mode != 1) {
        throw new Invalid("mode", "phan " + pi + ": mode " + p.mode);
      }
      if(rt != null && p.srcFaceCount != rt.srcFaceCounts()[pi]) {
        throw new Invalid("srcFaceCount", "phan " + pi + ": srcFaceCount " + p.srcFaceCount + " != runtime " + rt.srcFaceCounts()[pi]);
      }
      if(p.mode == 0) {
        continue;
      }
      final long P = c.u32("P");
      final long C = c.u32("C");
      final long T = c.u32("T");
      if(P > MAX_PCT || C > MAX_PCT || T > MAX_PCT || P < 1 || C < 3 || T < 1) {
        throw new Invalid("limits", "phan " + pi + ": P/C/T " + P + '/' + C + '/' + T);
      }
      c.need(12 * P + 32 * C + 12 * T, "pos/corner/tri phan " + pi);
      p.P = (int)P;
      p.C = (int)C;
      p.T = (int)T;
      p.pos = new float[3 * p.P];
      for(int i = 0; i < p.pos.length; i++) {
        p.pos[i] = c.f32();
        if(!Float.isFinite(p.pos[i])) {
          throw new Invalid("nonfinite", "phan " + pi + ": pos khong huu han");
        }
      }
      p.cPos = new int[p.C];
      p.cN = new float[3 * p.C];
      p.cSrc = new int[p.C];
      p.cS = new int[p.C];
      p.cT = new int[p.C];
      p.cNear = new int[p.C];
      p.cRole = new int[p.C];
      for(int i = 0; i < p.C; i++) {
        final long cpos = c.u32("corner");
        final float nx = c.f32();
        final float ny = c.f32();
        final float nz = c.f32();
        final long src = c.u32("corner");
        p.cS[i] = c.u16("corner");
        p.cT[i] = c.u16("corner");
        p.cNear[i] = c.u16("corner");
        p.cRole[i] = c.u8("corner");
        final int z = c.u8("corner");
        final long reserved = c.u32("corner");
        if(cpos >= P) {
          throw new Invalid("cornerPos", "phan " + pi + " corner " + i + ": pos " + cpos + " >= P");
        }
        if(!Float.isFinite(nx) || !Float.isFinite(ny) || !Float.isFinite(nz)) {
          throw new Invalid("nonfinite", "phan " + pi + " corner " + i + ": phap tuyen khong huu han");
        }
        if(src >= p.srcFaceCount) {
          throw new Invalid("cornerSrc", "phan " + pi + " corner " + i + ": srcFace " + src + " >= " + p.srcFaceCount);
        }
        if(p.cRole[i] > 2 && !ignore.contains("role")) {
          throw new Invalid("role", "phan " + pi + " corner " + i + ": role " + p.cRole[i]);
        }
        if((z != 0 || reserved != 0) && !ignore.contains("zero")) {
          throw new Invalid("zero", "phan " + pi + " corner " + i + ": byte zero/reserved != 0");
        }
        if(rt != null && p.cNear[i] >= rt.nVerts()[pi] && !ignore.contains("near")) {
          throw new Invalid("near", "phan " + pi + " corner " + i + ": nearestTmdVertex " + p.cNear[i] + " >= n_vert " + rt.nVerts()[pi]);
        }
        p.cPos[i] = (int)cpos;
        p.cN[3 * i] = nx;
        p.cN[3 * i + 1] = ny;
        p.cN[3 * i + 2] = nz;
        p.cSrc[i] = (int)src;
      }
      p.tri = new int[3 * p.T];
      long prevSrc = -1;
      for(int t = 0; t < p.T; t++) {
        final long a = c.u32("tri");
        final long b = c.u32("tri");
        final long d = c.u32("tri");
        if(a >= C || b >= C || d >= C) {
          throw new Invalid("triIndex", "phan " + pi + " tam giac " + t + ": chi so >= C");
        }
        p.tri[3 * t] = (int)a;
        p.tri[3 * t + 1] = (int)b;
        p.tri[3 * t + 2] = (int)d;
        final int s0 = p.cSrc[(int)a];
        if(s0 != p.cSrc[(int)b] || s0 != p.cSrc[(int)d]) {
          throw new Invalid("triSrc", "phan " + pi + " tam giac " + t + ": goc khac srcFace");
        }
        if(s0 < prevSrc && !ignore.contains("triOrder")) {
          throw new Invalid("triOrder", "phan " + pi + " tam giac " + t + ": khong xep theo srcFace tang dan");
        }
        prevSrc = s0;
      }
    }

    // toàn vẹn + khoá runtime (mục 4)
    final byte[][] pks = new byte[partCount][];
    for(int i = 0; i < partCount; i++) {
      pks[i] = l.parts[i].key;
    }
    if(!Arrays.equals(RefKey.modelKey(pks), l.modelKey)) {
      throw new Invalid("integrity", "modelKey != SHA-1(LRMK1 + partKeys)");
    }
    if(rt != null && !Arrays.equals(rt.modelKey(), l.modelKey)) {
      throw new Invalid("key", "modelKey != khoa runtime");
    }

    // mục 7: biến thể
    l.variants = new Variant[variantCount];
    long tcount = -1;
    for(int vi = 0; vi < variantCount; vi++) {
      final Variant v = new Variant();
      l.variants[vi] = v;
      v.png = c.bytes(20, "pngSha1");
      v.w = c.u16("w");
      v.h = c.u16("h");
      final long n = c.u32("texturedFaceCount");
      if(!pow2(v.w) || !pow2(v.h)) {
        throw new Invalid("size", "bien the " + vi + ": " + v.w + 'x' + v.h);
      }
      if(tcount >= 0 && n != tcount) {
        throw new Invalid("texturedFaceCount", "bien the " + vi + ": texturedFaceCount khac bien the 0");
      }
      if(rt != null && n != rt.texturedFaceCount()) {
        throw new Invalid("texturedFaceCount", "bien the " + vi + ": texturedFaceCount " + n + " != runtime " + rt.texturedFaceCount());
      }
      c.need(36 * n, "faceHash/atlasUv bien the " + vi);
      tcount = n;
      v.n = (int)n;
      v.faceHash = new int[v.n];
      for(int g = 0; g < v.n; g++) {
        v.faceHash[g] = (int)c.u32("faceHash");
      }
      v.atlasUv = new float[8 * v.n];
      for(int i = 0; i < v.atlasUv.length; i++) {
        final float f = c.f32();
        v.atlasUv[i] = f;
        final int g = i / 8;
        final int corner = i % 8 / 2;
        if(corner == 3 && rt != null && rt.texturedVc()[g] == 3) {
          continue; // §3.5.4: góc thứ 4 của mặt tam giác không kiểm
        }
        if((!Float.isFinite(f) || f < 0.0f || f > 1.0f) && !ignore.contains("atlasUv")) {
          throw new Invalid("atlasUv", "bien the " + vi + " mat " + g + ": atlasUv " + f);
        }
      }
    }
    if(c.remaining() != 0) {
      throw new Invalid("trailing", "thua " + c.remaining() + " byte cuoi than");
    }
    return l;
  }

  static boolean pow2(final int v) {
    return v >= 1 && v <= MAX_TEX && (v & v - 1) == 0;
  }

  private static byte[] inflate(final byte[] raw, final long bodySize) throws Invalid {
    final Inflater inf = new Inflater();
    try {
      inf.setInput(raw);
      final ByteArrayOutputStream out = new ByteArrayOutputStream((int)Math.min(bodySize + 1, 1 << 20));
      final byte[] buf = new byte[65536];
      while(!inf.finished()) {
        final int n = inf.inflate(buf);
        if(n == 0) {
          if(inf.needsInput() || inf.needsDictionary()) {
            throw new Invalid("deflate", "luong zlib chua ket thuc");
          }
        }
        out.write(buf, 0, n);
        if(out.size() > bodySize) {
          throw new Invalid("deflate", "giai nen ra hon bodySize");
        }
      }
      if(inf.getRemaining() != 0) {
        throw new Invalid("deflate", "thua " + inf.getRemaining() + " byte sau luong zlib");
      }
      if(out.size() != bodySize) {
        throw new Invalid("deflate", "giai nen ra " + out.size() + " != bodySize " + bodySize);
      }
      return out.toByteArray();
    } catch(final DataFormatException e) {
      throw new Invalid("deflate", "zlib loi: " + e.getMessage());
    } finally {
      inf.end();
    }
  }

  // ---------------------------------------------------------------- ghi

  public static byte[] body(final Lrm l) {
    final ByteArrayOutputStream out = new ByteArrayOutputStream();
    final ByteBuffer b4 = ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN);
    final java.util.function.IntConsumer u32 = v -> out.write(b4.clear().putInt(v).array(), 0, 4);
    final java.util.function.IntConsumer u16 = v -> out.write(b4.clear().putShort((short)v).array(), 0, 2);
    final java.util.function.Consumer<Float> f32 = v -> out.write(b4.clear().putFloat(v).array(), 0, 4);
    for(final Part p : l.parts) {
      out.writeBytes(p.key);
      u32.accept((int)p.srcFaceCount);
      out.write(p.mode);
      out.write(0);
      out.write(0);
      out.write(0);
      if(p.mode != 1) {
        continue;
      }
      u32.accept(p.P);
      u32.accept(p.C);
      u32.accept(p.T);
      for(final float f : p.pos) {
        f32.accept(f);
      }
      for(int i = 0; i < p.C; i++) {
        u32.accept(p.cPos[i]);
        f32.accept(p.cN[3 * i]);
        f32.accept(p.cN[3 * i + 1]);
        f32.accept(p.cN[3 * i + 2]);
        u32.accept(p.cSrc[i]);
        u16.accept(p.cS[i]);
        u16.accept(p.cT[i]);
        u16.accept(p.cNear[i]);
        out.write(p.cRole[i]);
        out.write(0);
        u32.accept(0);
      }
      for(final int t : p.tri) {
        u32.accept(t);
      }
    }
    for(final Variant v : l.variants) {
      out.writeBytes(v.png);
      u16.accept(v.w);
      u16.accept(v.h);
      u32.accept(v.n);
      for(final int h : v.faceHash) {
        u32.accept(h);
      }
      for(final float f : v.atlasUv) {
        f32.accept(f);
      }
    }
    return out.toByteArray();
  }

  public static byte[] write(final Lrm l, final boolean deflate) {
    final byte[] body = body(l);
    final ByteBuffer h = ByteBuffer.allocate(HEADER).order(ByteOrder.LITTLE_ENDIAN);
    h.put("LRM1".getBytes(StandardCharsets.US_ASCII));
    h.putShort((short)1);
    h.putShort((short)(deflate ? 1 : 0));
    h.put(l.modelKey);
    h.putShort((short)l.parts.length);
    h.putShort((short)l.variants.length);
    h.putInt(body.length);
    h.put((byte)l.level);
    h.put(new byte[3]);
    final byte[] gen = l.generator.getBytes(StandardCharsets.US_ASCII);
    h.put(gen, 0, Math.min(24, gen.length));
    final byte[] head = h.array();
    final byte[] payload = deflate ? deflate(body) : body;
    final byte[] out = Arrays.copyOf(head, HEADER + payload.length);
    System.arraycopy(payload, 0, out, HEADER, payload.length);
    return out;
  }

  public static byte[] deflate(final byte[] body) {
    final Deflater d = new Deflater(9);
    try {
      d.setInput(body);
      d.finish();
      final ByteArrayOutputStream out = new ByteArrayOutputStream();
      final byte[] buf = new byte[65536];
      while(!d.finished()) {
        out.write(buf, 0, d.deflate(buf));
      }
      return out.toByteArray();
    } finally {
      d.end();
    }
  }

  // ---------------------------------------------------------------- L0 identity

  public static final String GENERATOR = "scvi-remastercheck 1";

  /** Bản L0 identity của một mô hình (mọi phần mode 1), không có biến thể. */
  public static Lrm identity(final TmdObjTable1c[] tables) {
    final Lrm l = new Lrm();
    l.level = 0;
    l.generator = GENERATOR;
    l.parts = new Part[tables.length];
    final byte[][] pks = new byte[tables.length][];
    for(int i = 0; i < tables.length; i++) {
      l.parts[i] = identityPart(tables[i]);
      pks[i] = l.parts[i].key;
    }
    l.modelKey = RefKey.modelKey(pks);
    return l;
  }

  public static Part identityPart(final TmdObjTable1c t) {
    final List<RefBuild.Face> faces = RefBuild.decode(t);
    final Part p = new Part();
    p.key = RefKey.partKey(t);
    p.srcFaceCount = faces.size();
    p.mode = 1;
    p.P = t.vert_top_00.length;
    p.pos = new float[3 * p.P];
    for(int i = 0; i < p.P; i++) {
      p.pos[3 * i] = t.vert_top_00[i].x;
      p.pos[3 * i + 1] = t.vert_top_00[i].y;
      p.pos[3 * i + 2] = t.vert_top_00[i].z;
    }
    int corners = 0;
    int tris = 0;
    for(final RefBuild.Face f : faces) {
      corners += f.vc;
      tris += f.quad ? 2 : 1;
    }
    p.C = corners;
    p.T = tris;
    p.cPos = new int[corners];
    p.cN = new float[3 * corners];
    p.cSrc = new int[corners];
    p.cS = new int[corners];
    p.cT = new int[corners];
    p.cNear = new int[corners];
    p.cRole = new int[corners];
    p.tri = new int[3 * tris];
    int ci = 0;
    int ti = 0;
    for(final RefBuild.Face f : faces) {
      final int base = ci;
      for(int k = 0; k < f.vc; k++) {
        p.cPos[ci] = f.vidx[k];
        if(f.lit) {
          final float[] n = RefBuild.normal(t, f.nidx[k]);
          p.cN[3 * ci] = n[0];
          p.cN[3 * ci + 1] = n[1];
          p.cN[3 * ci + 2] = n[2];
        }
        p.cSrc[ci] = f.index;
        p.cS[ci] = (k & 1) != 0 ? 65535 : 0;
        p.cT[ci] = (k & 2) != 0 ? 65535 : 0;
        p.cNear[ci] = f.vidx[k];
        ci++;
      }
      // TmdObjLoader: [v+2, v+3, v+1, v+3, v, v+3] -> tam giác (2, 1, 0); tứ giác thêm [v+1, v, v+2, v, v+3, v] -> (1, 2, 3)
      p.tri[ti++] = base + 2;
      p.tri[ti++] = base + 1;
      p.tri[ti++] = base;
      if(f.quad) {
        p.tri[ti++] = base + 1;
        p.tri[ti++] = base + 2;
        p.tri[ti++] = base + 3;
      }
    }
    return p;
  }
}
