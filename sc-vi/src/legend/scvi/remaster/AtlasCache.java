package legend.scvi.remaster;

import legend.core.renderer.Texture;
import legend.core.renderer.TextureDataFormat;
import legend.core.renderer.TextureDataType;
import legend.core.renderer.TextureInternalFormat;
import org.lwjgl.stb.STBImage;
import org.lwjgl.system.MemoryStack;
import org.lwjgl.system.MemoryUtil;

import java.nio.ByteBuffer;
import java.nio.IntBuffer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.Iterator;
import java.util.Map;
import java.util.Set;

/**
 * [sc-vi] Texture atlas HD của mô hình remaster (LRM spec 1 §3.6, §4.2): remaster/textures/&lt;SHA-1 của file&gt;.png.
 *
 * Nạp: SHA-1 của byte file = tên, stbi_load_from_memory -&gt; RGBA8, cỡ = w × h của biến thể; đổi alpha theo quy ước file
 * (A &lt; 64 trong suốt, 64..191 STP = 1, &gt;= 192 STP = 0) sang dạng shader cần (trong suốt (0,0,0,0); STP 0 (R,G,B,0), đen
 * đổi thành (1,1,1); STP 1 (R,G,B,255)); chuỗi mip trên CPU tới 1×1 (khối 2×2: 2t &gt;= n -&gt; trong suốt; RGB =
 * floor((Σ + floor(o/2)) / o) trên o texel đục; STP = đa số, hoà -&gt; 1); mức 0 qua Texture.create (RGBA_8,
 * TextureBuilder.data, NEAREST, CLAMP), mức 1.. qua AtlasUpload. persistent = true (không bị Texture.clearTextureList(false)
 * xoá khi chuyển cảnh).
 * Đếm tham chiếu theo chủ sở hữu (trạng thái chung của một lần nạp mô hình): giải phóng khi mọi chủ sở hữu đã xoá
 * (performDelete của mọi phần), hoặc khi quét lúc đọc lại cấu hình (engine state đổi) thấy chủ sở hữu đã bị xoá / rò.
 * PNG hỏng / thiếu / sai SHA-1 / sai cỡ -&gt; null (biến thể đó không có bộ ATLAS; lỗi nhớ theo PNG đến lần đọc lại cấu hình).
 */
final class AtlasCache {
  private AtlasCache() { }

  private static final long MAX_PNG = 64L << 20;
  static final Path DIR = RemasterIndex.DIR.resolve("textures");

  private static final class Entry {
    final Texture texture;
    final Set<RemasterMeshObj.ModelState> owners = Collections.newSetFromMap(new IdentityHashMap<>());

    Entry(final Texture texture) {
      this.texture = texture;
    }
  }

  private static final Map<String, Entry> ENTRIES = new HashMap<>();
  private static final Map<String, String> FAILED = new HashMap<>();

  /** Texture của PNG (nạp nếu chưa có) và ghi nhận chủ sở hữu. Lỗi -&gt; LrmFile.Invalid với lý do. */
  static synchronized Texture acquire(final byte[] pngSha1, final int w, final int h, final RemasterMeshObj.ModelState owner) throws LrmFile.Invalid {
    final String hex = RemasterLog.hex(pngSha1);
    Entry entry = ENTRIES.get(hex);
    if(entry == null) {
      final String failed = FAILED.get(hex);
      if(failed != null) {
        throw new LrmFile.Invalid(failed);
      }

      try {
        entry = new Entry(load(hex, pngSha1, w, h));
      } catch(final LrmFile.Invalid e) {
        FAILED.put(hex, e.getMessage());
        throw e;
      } catch(final Throwable t) {
        final String reason = "png " + hex.substring(0, 8) + ": " + RemasterLog.reason(t);
        FAILED.put(hex, reason);
        throw new LrmFile.Invalid(reason);
      }

      ENTRIES.put(hex, entry);
    } else if(entry.texture.width != w || entry.texture.height != h) {
      throw new LrmFile.Invalid("png " + hex.substring(0, 8) + " size " + entry.texture.width + 'x' + entry.texture.height + " != " + w + 'x' + h);
    }

    entry.owners.add(owner);
    return entry.texture;
  }

  /** Bỏ mọi tham chiếu của chủ sở hữu; texture không còn ai giữ thì delete(). */
  static synchronized void release(final RemasterMeshObj.ModelState owner) {
    for(final Iterator<Entry> it = ENTRIES.values().iterator(); it.hasNext(); ) {
      final Entry e = it.next();
      if(e.owners.remove(owner) && e.owners.isEmpty()) {
        e.texture.delete();
        it.remove();
      }
    }
  }

  /** Quét chủ sở hữu đã bị xoá / rò (gọi khi đọc lại cấu hình), rồi xoá lỗi đã nhớ. */
  static synchronized void sweep() {
    for(final Iterator<Entry> it = ENTRIES.values().iterator(); it.hasNext(); ) {
      final Entry e = it.next();
      e.owners.removeIf(owner -> {
        if(owner.isGone()) {
          owner.markReleased();
          return true;
        }
        return false;
      });
      if(e.owners.isEmpty()) {
        e.texture.delete();
        it.remove();
      }
    }

    FAILED.clear();
  }

  static synchronized int size() {
    return ENTRIES.size();
  }

  private static Texture load(final String hex, final byte[] sha1, final int w, final int h) throws Exception {
    final String tag = "png " + hex.substring(0, 8);
    final Path path = DIR.resolve(hex + ".png");
    if(!Files.isRegularFile(path)) {
      throw new LrmFile.Invalid(tag + " missing");
    }

    if(Files.size(path) > MAX_PNG) {
      throw new LrmFile.Invalid(tag + " too large");
    }

    final byte[] bytes = Files.readAllBytes(path);
    if(!Arrays.equals(GeometryKey.sha1(bytes, 0, bytes.length), sha1)) {
      throw new LrmFile.Invalid(tag + " sha1 mismatch");
    }

    final byte[] rgba = decodePng(bytes, w, h, tag);
    final int[] ws = new int[levelCount(w, h)];
    final int[] hs = new int[ws.length];
    final byte[][] mips = runtimeMips(rgba, w, h, ws, hs);

    final ByteBuffer level0 = MemoryUtil.memAlloc(mips[0].length);
    final Texture texture;
    try {
      level0.put(mips[0]).flip();
      texture = Texture.create("Remaster atlas " + hex.substring(0, 8), builder -> {
        builder.data(level0, w, h);
        builder.internalFormat(TextureInternalFormat.RGBA_8);
        builder.dataFormat(TextureDataFormat.RGBA);
        builder.dataType(TextureDataType.UBYTE);
        builder.minFilter(false);
        builder.magFilter(false);
        builder.wrapS(false);
        builder.wrapT(false);
      });
    } finally {
      MemoryUtil.memFree(level0);
    }

    try {
      AtlasUpload.forCurrentApi().upload(texture, mips, ws, hs);
    } catch(final Throwable t) {
      texture.delete();
      throw t;
    }

    texture.persistent = true;
    return texture;
  }

  /** PNG -&gt; RGBA8 (stb_image, 4 kênh), kiểm cỡ. */
  static byte[] decodePng(final byte[] bytes, final int w, final int h, final String tag) throws LrmFile.Invalid {
    final ByteBuffer src = MemoryUtil.memAlloc(bytes.length);
    try(final MemoryStack stack = MemoryStack.stackPush()) {
      src.put(bytes).flip();
      final IntBuffer x = stack.mallocInt(1);
      final IntBuffer y = stack.mallocInt(1);
      final IntBuffer comp = stack.mallocInt(1);
      final ByteBuffer img = STBImage.stbi_load_from_memory(src, x, y, comp, 4);
      if(img == null) {
        throw new LrmFile.Invalid(tag + " decode failed");
      }

      try {
        if(x.get(0) != w || y.get(0) != h) {
          throw new LrmFile.Invalid(tag + " size " + x.get(0) + 'x' + y.get(0) + " != " + w + 'x' + h);
        }

        final byte[] rgba = new byte[w * h * 4];
        img.get(0, rgba);
        return rgba;
      } finally {
        STBImage.stbi_image_free(img);
      }
    } finally {
      MemoryUtil.memFree(src);
    }
  }

  /** floor(log2(max(w, h))) + 1 mức (tới 1×1). */
  static int levelCount(final int w, final int h) {
    return 32 - Integer.numberOfLeadingZeros(Math.max(1, Math.max(w, h)));
  }

  /**
   * Chuỗi mip §3.6.3 ở dạng runtime §3.6.2 (RGBA8, hàng đầu = v 0). ws/hs (độ dài = levelCount) nhận cỡ từng mức.
   * Công khai trong gói để bộ thử so với sample_cube.json (atlas[v].runtimeMips[k].sha1).
   */
  static byte[][] runtimeMips(final byte[] rgbaFile, final int w0, final int h0, final int[] ws, final int[] hs) {
    final int levels = ws.length;
    final byte[][] out = new byte[levels][];

    // mức 0 theo quy ước file: lớp 0 trong suốt, 1 STP = 0, 2 STP = 1; RGB của texel trong suốt = 0
    int w = w0;
    int h = h0;
    byte[] cls = new byte[w * h];
    byte[] rgb = new byte[w * h * 3];
    for(int i = 0; i < w * h; i++) {
      final int a = rgbaFile[i * 4 + 3] & 0xff;
      final byte c = (byte)(a < 64 ? 0 : a < 192 ? 2 : 1);
      cls[i] = c;
      if(c != 0) {
        rgb[i * 3] = rgbaFile[i * 4];
        rgb[i * 3 + 1] = rgbaFile[i * 4 + 1];
        rgb[i * 3 + 2] = rgbaFile[i * 4 + 2];
      }
    }

    for(int level = 0; level < levels; level++) {
      ws[level] = w;
      hs[level] = h;
      out[level] = toRuntime(cls, rgb, w * h);

      if(level == levels - 1) {
        break;
      }

      final int w2 = Math.max(1, w / 2);
      final int h2 = Math.max(1, h / 2);
      final byte[] cls2 = new byte[w2 * h2];
      final byte[] rgb2 = new byte[w2 * h2 * 3];

      for(int y = 0; y < h2; y++) {
        for(int x = 0; x < w2; x++) {
          int n = 0;
          int t = 0;
          int stp1 = 0;
          int sr = 0;
          int sg = 0;
          int sb = 0;

          for(int j = 0; j < 2; j++) {
            final int yy = 2 * y + j;
            if(yy >= h) {
              continue;
            }

            for(int i = 0; i < 2; i++) {
              final int xx = 2 * x + i;
              if(xx >= w) {
                continue;
              }

              final int p = yy * w + xx;
              n++;
              if(cls[p] == 0) {
                t++;
              } else {
                sr += rgb[p * 3] & 0xff;
                sg += rgb[p * 3 + 1] & 0xff;
                sb += rgb[p * 3 + 2] & 0xff;
                if(cls[p] == 2) {
                  stp1++;
                }
              }
            }
          }

          final int q = y * w2 + x;
          if(2 * t >= n) {
            continue; // trong suốt (cls 0, RGB 0)
          }

          final int o = n - t;
          rgb2[q * 3] = (byte)((sr + o / 2) / o);
          rgb2[q * 3 + 1] = (byte)((sg + o / 2) / o);
          rgb2[q * 3 + 2] = (byte)((sb + o / 2) / o);
          cls2[q] = (byte)(stp1 >= o - stp1 ? 2 : 1);
        }
      }

      w = w2;
      h = h2;
      cls = cls2;
      rgb = rgb2;
    }

    return out;
  }

  private static byte[] toRuntime(final byte[] cls, final byte[] rgb, final int n) {
    final byte[] out = new byte[n * 4];
    for(int i = 0; i < n; i++) {
      final int c = cls[i];
      if(c == 0) {
        continue;
      }

      byte r = rgb[i * 3];
      byte g = rgb[i * 3 + 1];
      byte b = rgb[i * 3 + 2];
      if(c == 1) {
        if(r == 0 && g == 0 && b == 0) {
          r = 1;
          g = 1;
          b = 1;
        }
        out[i * 4 + 3] = 0;
      } else {
        out[i * 4 + 3] = (byte)255;
      }

      out[i * 4] = r;
      out[i * 4 + 1] = g;
      out[i * 4 + 2] = b;
    }
    return out;
  }
}
