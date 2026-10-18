package legend.scvi.remaster;

import java.io.IOException;
import java.lang.ref.SoftReference;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;
import java.util.zip.DataFormatException;
import java.util.zip.Inflater;

/**
 * [sc-vi] Bộ đọc file LRM1 remaster/models/&lt;modelKey&gt;.lrm (LRM spec 1 §3.5) với mọi kiểm tra bắt buộc của §3.5.4.
 *
 * Header 0x40 byte (LE): 'LRM1', u16 version 1, u16 flags (bit 0 = thân zlib), u8[20] modelKey, u16 partCount (1..64),
 * u16 variantCount (0..4), u32 bodySize (&lt;= 256 MiB, sau giải nén), u8 level (0..2), u8[3] 0, char[24] generator (ASCII
 * 0x20..0x7e, đệm 0). Thân: part[partCount] (28 byte mode 0; mode 1: + u32 P, C, T + f32 pos[P][3] + corner[C] 32 byte +
 * u32 tri[T][3]) rồi variant[variantCount] (u8[20] pngSha1, u16 w, u16 h, u32 n, u32 faceHash[n], f32 atlasUv[n][4][2]).
 *
 * Kiểm: header; thân đúng bodySize (nén: luồng kết thúc đúng cuối file, giải đúng bodySize byte); thân bị cắt / thừa byte
 * (kiểm cắt TRƯỚC khi cấp phát theo số đếm trong file); SHA-1('LRMK1' ‖ partCount ‖ partKeys) = modelKey = khoá runtime,
 * partKey từng phần = runtime; partCount = số phần runtime (kiểm trước khi đánh chỉ số theo phần); srcFaceCount = runtime;
 * mode; giới hạn P/C/T; float hữu hạn; chỉ số corner.pos/srcFace/tri; role; byte 0 / dự trữ; nearestTmdVertex &lt; n_vert;
 * ba corner một tam giác cùng srcFace; tam giác xếp theo srcFace tăng dần; w/h luỹ thừa 2 &lt;= 2048; texturedFaceCount
 * = runtime và như nhau ở mọi biến thể; atlasUv hữu hạn trong [0, 1] (trừ góc thứ 4 của mặt tam giác: §3.5.4 không kiểm, cần
 * Runtime.texturedQuad; không có thì kiểm cả góc đó).
 * Sai một điều => Invalid (cả mô hình đi đường gốc). Kết quả đọc được giữ trong cache SoftReference theo khoá; lỗi được nhớ
 * theo khoá đến lần đọc lại cấu hình kế tiếp.
 */
public final class LrmFile {
  public static final int HEADER_SIZE = 0x40;
  public static final int MAX_PARTS = 64;
  public static final int MAX_VARIANTS = 4;
  public static final int MAX_PCT = 200_000;
  public static final int MAX_BODY = 0x1000_0000;
  public static final int MAX_TEX = 2048;
  /** Cỡ file tối đa chấp nhận (thân không nén tối đa + dư cho luồng zlib). */
  private static final long MAX_FILE = HEADER_SIZE + (long)MAX_BODY + (1L << 20);

  /** File / chỉ mục không hợp lệ: thông điệp là lý do ngắn (ASCII). */
  public static final class Invalid extends Exception {
    public Invalid(final String message) {
      super(message);
    }
  }

  /** Số liệu runtime của mô hình đang nạp để đối chiếu. */
  public static final class Runtime {
    final byte[] modelKey;
    final byte[][] partKeys;
    final int[] srcFaceCounts;
    final int[] nVerts;
    final int texturedFaceCount;
    /** [g] = mặt có texture g là tứ giác; null = không biết (khi đó kiểm cả góc thứ 4 của mọi mặt). */
    final boolean[] texturedQuad;

    public Runtime(final byte[] modelKey, final byte[][] partKeys, final int[] srcFaceCounts, final int[] nVerts, final int texturedFaceCount) {
      this(modelKey, partKeys, srcFaceCounts, nVerts, texturedFaceCount, null);
    }

    public Runtime(final byte[] modelKey, final byte[][] partKeys, final int[] srcFaceCounts, final int[] nVerts, final int texturedFaceCount, final boolean[] texturedQuad) {
      this.modelKey = modelKey;
      this.partKeys = partKeys;
      this.srcFaceCounts = srcFaceCounts;
      this.nVerts = nVerts;
      this.texturedFaceCount = texturedFaceCount;
      this.texturedQuad = texturedQuad != null && texturedQuad.length == texturedFaceCount ? texturedQuad : null;
    }
  }

  public static final class Part {
    public final byte[] key;
    public final int srcFaceCount;
    public final int mode;
    public final int pCount;
    public final int cCount;
    public final int tCount;
    /** f32[P][3] */
    public final float[] pos;
    public final int[] cornerPos;
    /** f32[C][3] */
    public final float[] cornerNormal;
    public final int[] cornerSrc;
    public final int[] cornerS;
    public final int[] cornerT;
    public final int[] cornerNear;
    public final byte[] cornerRole;
    /** u32[T][3] */
    public final int[] tri;

    Part(final byte[] key, final int srcFaceCount, final int mode, final int p, final int c, final int t, final float[] pos, final int[] cornerPos, final float[] cornerNormal, final int[] cornerSrc, final int[] cornerS, final int[] cornerT, final int[] cornerNear, final byte[] cornerRole, final int[] tri) {
      this.key = key;
      this.srcFaceCount = srcFaceCount;
      this.mode = mode;
      this.pCount = p;
      this.cCount = c;
      this.tCount = t;
      this.pos = pos;
      this.cornerPos = cornerPos;
      this.cornerNormal = cornerNormal;
      this.cornerSrc = cornerSrc;
      this.cornerS = cornerS;
      this.cornerT = cornerT;
      this.cornerNear = cornerNear;
      this.cornerRole = cornerRole;
      this.tri = tri;
    }
  }

  public static final class Variant {
    public final byte[] pngSha1;
    public final int w;
    public final int h;
    public final int[] faceHash;
    /** f32[n][4][2] */
    public final float[] atlasUv;

    Variant(final byte[] pngSha1, final int w, final int h, final int[] faceHash, final float[] atlasUv) {
      this.pngSha1 = pngSha1;
      this.w = w;
      this.h = h;
      this.faceHash = faceHash;
      this.atlasUv = atlasUv;
    }
  }

  public final byte[] modelKey;
  public final int level;
  public final String generator;
  public final boolean deflated;
  public final Part[] parts;
  public final Variant[] variants;

  private LrmFile(final byte[] modelKey, final int level, final String generator, final boolean deflated, final Part[] parts, final Variant[] variants) {
    this.modelKey = modelKey;
    this.level = level;
    this.generator = generator;
    this.deflated = deflated;
    this.parts = parts;
    this.variants = variants;
  }

  // ---------------------------------------------------------------- cache

  private static final Map<String, SoftReference<LrmFile>> CACHE = new HashMap<>();
  private static final Map<String, String> FAILED = new HashMap<>();

  static synchronized void clearCache() {
    CACHE.clear();
    FAILED.clear();
  }

  /** Đọc + kiểm file của khoá (cache theo khoá). Lỗi => Invalid (lý do được nhớ đến lần đọc lại cấu hình). */
  static LrmFile load(final String keyHex, final Runtime runtime) throws Invalid {
    synchronized(LrmFile.class) {
      final String failed = FAILED.get(keyHex);
      if(failed != null) {
        throw new Invalid(failed);
      }

      final SoftReference<LrmFile> ref = CACHE.get(keyHex);
      final LrmFile cached = ref != null ? ref.get() : null;
      if(cached != null) {
        try {
          cached.checkRuntime(runtime);
          return cached;
        } catch(final Invalid e) {
          FAILED.put(keyHex, e.getMessage());
          throw e;
        }
      }
    }

    final LrmFile file;
    try {
      file = read(RemasterIndex.modelPath(keyHex), runtime);
    } catch(final Invalid e) {
      synchronized(LrmFile.class) {
        FAILED.put(keyHex, e.getMessage());
      }
      throw e;
    } catch(final IOException | RuntimeException | OutOfMemoryError e) {
      final String reason = RemasterLog.reason(e);
      synchronized(LrmFile.class) {
        FAILED.put(keyHex, reason);
      }
      throw new Invalid(reason);
    }

    synchronized(LrmFile.class) {
      CACHE.put(keyHex, new SoftReference<>(file));
    }
    return file;
  }

  static LrmFile read(final Path path, final Runtime runtime) throws IOException, Invalid {
    if(!Files.isRegularFile(path)) {
      throw new Invalid("lrm file missing");
    }

    if(Files.size(path) > MAX_FILE) {
      throw new Invalid("lrm file too large");
    }

    return parse(Files.readAllBytes(path), runtime);
  }

  /** Kiểm số liệu runtime (gọi cả khi lấy từ cache; rẻ). */
  void checkRuntime(final Runtime rt) throws Invalid {
    if(!Arrays.equals(this.modelKey, rt.modelKey)) {
      throw new Invalid("modelKey != runtime key");
    }

    if(this.parts.length != rt.partKeys.length || this.parts.length != rt.srcFaceCounts.length || this.parts.length != rt.nVerts.length) {
      throw new Invalid("partCount " + this.parts.length + " != runtime " + rt.partKeys.length);
    }

    for(int i = 0; i < this.parts.length; i++) {
      final Part p = this.parts[i];
      if(!Arrays.equals(p.key, rt.partKeys[i])) {
        throw new Invalid("partKey " + i + " != runtime");
      }

      if(p.srcFaceCount != rt.srcFaceCounts[i]) {
        throw new Invalid("part " + i + " srcFaceCount " + Integer.toUnsignedString(p.srcFaceCount) + " != runtime " + rt.srcFaceCounts[i]);
      }

      if(p.mode == 1) {
        for(int c = 0; c < p.cCount; c++) {
          if(p.cornerNear[c] >= rt.nVerts[i]) {
            throw new Invalid("part " + i + " nearestTmdVertex >= n_vert");
          }
        }
      }
    }

    for(final Variant v : this.variants) {
      if(v.faceHash.length != rt.texturedFaceCount) {
        throw new Invalid("texturedFaceCount " + v.faceHash.length + " != runtime " + rt.texturedFaceCount);
      }
    }
  }

  // ---------------------------------------------------------------- đọc

  /** Đọc + kiểm toàn bộ §3.5.4 với số liệu runtime. */
  public static LrmFile parse(final byte[] file, final Runtime runtime) throws Invalid {
    if(file.length < HEADER_SIZE) {
      throw new Invalid("file shorter than header");
    }

    final ByteBuffer head = ByteBuffer.wrap(file, 0, HEADER_SIZE).order(ByteOrder.LITTLE_ENDIAN);
    if(file[0] != 'L' || file[1] != 'R' || file[2] != 'M' || file[3] != '1') {
      throw new Invalid("bad magic");
    }

    final int version = head.getShort(4) & 0xffff;
    final int flags = head.getShort(6) & 0xffff;
    if(version != 1) {
      throw new Invalid("version " + version + " != 1");
    }

    if((flags & ~1) != 0) {
      throw new Invalid("unknown flags");
    }

    final byte[] modelKey = Arrays.copyOfRange(file, 0x08, 0x1c);
    final int partCount = head.getShort(0x1c) & 0xffff;
    final int variantCount = head.getShort(0x1e) & 0xffff;
    final long bodySize = head.getInt(0x20) & 0xffff_ffffL;
    final int level = file[0x24] & 0xff;
    if(file[0x25] != 0 || file[0x26] != 0 || file[0x27] != 0) {
      throw new Invalid("header reserved bytes != 0");
    }

    int genLen = 24;
    while(genLen > 0 && file[0x28 + genLen - 1] == 0) {
      genLen--;
    }
    for(int i = 0; i < genLen; i++) {
      final int c = file[0x28 + i] & 0xff;
      if(c < 0x20 || c > 0x7e) {
        throw new Invalid("generator is not zero-padded ASCII");
      }
    }
    final String generator = new String(file, 0x28, genLen, StandardCharsets.US_ASCII);

    if(partCount < 1 || partCount > MAX_PARTS) {
      throw new Invalid("partCount " + partCount + " outside 1..64");
    }

    if(variantCount > MAX_VARIANTS) {
      throw new Invalid("variantCount " + variantCount + " > 4");
    }

    if(level > 2) {
      throw new Invalid("level " + level + " > 2");
    }

    if(bodySize > MAX_BODY) {
      throw new Invalid("bodySize > 256 MiB");
    }

    if(runtime != null) {
      if(!Arrays.equals(modelKey, runtime.modelKey)) {
        throw new Invalid("modelKey != runtime key");
      }

      if(partCount != runtime.partKeys.length || partCount != runtime.srcFaceCounts.length || partCount != runtime.nVerts.length) {
        throw new Invalid("partCount " + partCount + " != runtime " + runtime.partKeys.length);
      }
    }

    final boolean deflated = (flags & 1) != 0;
    final ByteBuffer body;
    if(deflated) {
      body = ByteBuffer.wrap(inflate(file, (int)bodySize)).order(ByteOrder.LITTLE_ENDIAN);
    } else {
      if(file.length - HEADER_SIZE != bodySize) {
        throw new Invalid("bodySize " + bodySize + " != " + (file.length - HEADER_SIZE) + " remaining bytes");
      }
      body = ByteBuffer.wrap(file, HEADER_SIZE, file.length - HEADER_SIZE).slice().order(ByteOrder.LITTLE_ENDIAN);
    }

    final Part[] parts = new Part[partCount];
    final byte[][] partKeys = new byte[partCount][];
    for(int pi = 0; pi < partCount; pi++) {
      need(body, 28, "part " + pi);
      final byte[] key = new byte[20];
      body.get(key);
      partKeys[pi] = key;
      final int sfc = body.getInt();
      final int mode = body.get() & 0xff;
      if(body.get() != 0 || body.get() != 0 || body.get() != 0) {
        throw new Invalid("part " + pi + " reserved bytes != 0");
      }

      if(mode != 0 && mode != 1) {
        throw new Invalid("part " + pi + " mode " + mode);
      }

      if(runtime != null && sfc != runtime.srcFaceCounts[pi]) {
        throw new Invalid("part " + pi + " srcFaceCount " + Integer.toUnsignedString(sfc) + " != runtime " + runtime.srcFaceCounts[pi]);
      }

      if(mode == 0) {
        parts[pi] = new Part(key, sfc, 0, 0, 0, 0, null, null, null, null, null, null, null, null, null);
        continue;
      }

      need(body, 12, "part " + pi + " counts");
      final long p = body.getInt() & 0xffff_ffffL;
      final long c = body.getInt() & 0xffff_ffffL;
      final long t = body.getInt() & 0xffff_ffffL;
      if(p > MAX_PCT || c > MAX_PCT || t > MAX_PCT) {
        throw new Invalid("part " + pi + " P/C/T > 200000");
      }

      if(p < 1 || c < 3 || t < 1) {
        throw new Invalid("part " + pi + " mode 1 with empty P/C/T");
      }

      final int P = (int)p;
      final int C = (int)c;
      final int T = (int)t;
      need(body, 12L * P + 32L * C + 12L * T, "part " + pi + " arrays");

      final float[] pos = new float[P * 3];
      for(int i = 0; i < pos.length; i++) {
        pos[i] = body.getFloat();
        if(!Float.isFinite(pos[i])) {
          throw new Invalid("part " + pi + " pos not finite");
        }
      }

      final int[] cPos = new int[C];
      final float[] cN = new float[C * 3];
      final int[] cSrc = new int[C];
      final int[] cS = new int[C];
      final int[] cT = new int[C];
      final int[] cNear = new int[C];
      final byte[] cRole = new byte[C];
      final long unsignedSfc = sfc & 0xffff_ffffL;
      for(int i = 0; i < C; i++) {
        cPos[i] = body.getInt();
        cN[i * 3] = body.getFloat();
        cN[i * 3 + 1] = body.getFloat();
        cN[i * 3 + 2] = body.getFloat();
        cSrc[i] = body.getInt();
        cS[i] = body.getShort() & 0xffff;
        cT[i] = body.getShort() & 0xffff;
        cNear[i] = body.getShort() & 0xffff;
        cRole[i] = body.get();
        final byte zero = body.get();
        final int reserved = body.getInt();

        if(Integer.compareUnsigned(cPos[i], P) >= 0) {
          throw new Invalid("part " + pi + " corner.pos out of range");
        }

        if(!Float.isFinite(cN[i * 3]) || !Float.isFinite(cN[i * 3 + 1]) || !Float.isFinite(cN[i * 3 + 2])) {
          throw new Invalid("part " + pi + " normal not finite");
        }

        if((cSrc[i] & 0xffff_ffffL) >= unsignedSfc) {
          throw new Invalid("part " + pi + " corner.srcFace out of range");
        }

        if((cRole[i] & 0xff) > 2 || zero != 0 || reserved != 0) {
          throw new Invalid("part " + pi + " corner role/reserved bytes");
        }

        if(runtime != null && cNear[i] >= runtime.nVerts[pi]) {
          throw new Invalid("part " + pi + " nearestTmdVertex >= n_vert");
        }
      }

      final int[] tri = new int[T * 3];
      int lastSrc = 0;
      for(int i = 0; i < T; i++) {
        final int a = body.getInt();
        final int b = body.getInt();
        final int d = body.getInt();
        if(Integer.compareUnsigned(a, C) >= 0 || Integer.compareUnsigned(b, C) >= 0 || Integer.compareUnsigned(d, C) >= 0) {
          throw new Invalid("part " + pi + " tri index out of range");
        }

        final int src = cSrc[a];
        if(cSrc[b] != src || cSrc[d] != src) {
          throw new Invalid("part " + pi + " triangle corners have different srcFace");
        }

        if(Integer.compareUnsigned(src, lastSrc) < 0) {
          throw new Invalid("part " + pi + " triangles not sorted by srcFace");
        }

        lastSrc = src;
        tri[i * 3] = a;
        tri[i * 3 + 1] = b;
        tri[i * 3 + 2] = d;
      }

      parts[pi] = new Part(key, sfc, 1, P, C, T, pos, cPos, cN, cSrc, cS, cT, cNear, cRole, tri);
    }

    final byte[] integrity = GeometryKey.modelKey(partKeys);
    if(!Arrays.equals(integrity, modelKey)) {
      throw new Invalid("modelKey != SHA-1(LRMK1 + partKeys)");
    }

    if(runtime != null) {
      for(int pi = 0; pi < partCount; pi++) {
        if(!Arrays.equals(partKeys[pi], runtime.partKeys[pi])) {
          throw new Invalid("partKey " + pi + " != runtime");
        }
      }
    }

    final Variant[] variants = new Variant[variantCount];
    int texturedCount = -1;
    for(int vi = 0; vi < variantCount; vi++) {
      need(body, 28, "variant " + vi);
      final byte[] sha = new byte[20];
      body.get(sha);
      final int w = body.getShort() & 0xffff;
      final int h = body.getShort() & 0xffff;
      final long n = body.getInt() & 0xffff_ffffL;
      if(w < 1 || h < 1 || w > MAX_TEX || h > MAX_TEX || (w & w - 1) != 0 || (h & h - 1) != 0) {
        throw new Invalid("variant " + vi + " size " + w + 'x' + h + " not a power of two <= 2048");
      }

      need(body, 36L * n, "variant " + vi + " (texturedFaceCount " + n + ')');

      if(texturedCount >= 0 && n != texturedCount) {
        throw new Invalid("variant " + vi + " texturedFaceCount differs from variant 0");
      }

      texturedCount = (int)n;
      if(runtime != null && n != runtime.texturedFaceCount) {
        throw new Invalid("variant " + vi + " texturedFaceCount " + n + " != runtime " + runtime.texturedFaceCount);
      }

      final int[] faceHash = new int[(int)n];
      for(int i = 0; i < faceHash.length; i++) {
        faceHash[i] = body.getInt();
      }

      final float[] uv = new float[(int)n * 8];
      final boolean[] quad = runtime != null ? runtime.texturedQuad : null;
      for(int i = 0; i < uv.length; i++) {
        final float f = body.getFloat();
        // §3.5.4 "không kiểm": atlasUv góc thứ 4 (float 6, 7 của mặt) của mặt TAM GIÁC — bộ ghi đặt (0, 0), runtime không đọc
        final boolean unchecked = quad != null && (i & 7) >= 6 && !quad[i >>> 3];
        if(!unchecked && (!Float.isFinite(f) || f < 0.0f || f > 1.0f)) {
          throw new Invalid("variant " + vi + " atlasUv outside [0,1]");
        }
        uv[i] = f;
      }

      variants[vi] = new Variant(sha, w, h, faceHash, uv);
    }

    if(body.hasRemaining()) {
      throw new Invalid(body.remaining() + " trailing body bytes");
    }

    return new LrmFile(modelKey, level, generator, deflated, parts, variants);
  }

  private static void need(final ByteBuffer body, final long n, final String what) throws Invalid {
    if(n < 0 || n > body.remaining()) {
      throw new Invalid("body truncated at " + what);
    }
  }

  /** Giải thân zlib: phải ra đúng bodySize byte, luồng kết thúc, không thừa byte đầu vào. Bộ đệm lớn dần (không cấp trước bodySize). */
  private static byte[] inflate(final byte[] file, final int bodySize) throws Invalid {
    final Inflater inf = new Inflater();
    try {
      inf.setInput(file, HEADER_SIZE, file.length - HEADER_SIZE);
      final int cap = bodySize + 1;
      byte[] buf = new byte[Math.min(cap, Math.max(4096, (file.length - HEADER_SIZE) * 4))];
      int n = 0;

      while(true) {
        if(n == buf.length) {
          if(buf.length >= cap) {
            break;
          }
          buf = Arrays.copyOf(buf, (int)Math.min(cap, buf.length * 2L));
        }

        final int k = inf.inflate(buf, n, buf.length - n);
        n += k;

        if(inf.finished()) {
          break;
        }

        if(k == 0 && (inf.needsInput() || inf.needsDictionary())) {
          throw new Invalid("deflate stream truncated");
        }
      }

      if(!inf.finished() || n != bodySize || inf.getRemaining() != 0) {
        throw new Invalid("deflate body does not match bodySize / trailing bytes");
      }

      return n == buf.length ? buf : Arrays.copyOf(buf, n);
    } catch(final DataFormatException e) {
      throw new Invalid("deflate error");
    } finally {
      inf.end();
    }
  }
}
