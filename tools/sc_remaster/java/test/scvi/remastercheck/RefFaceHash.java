package scvi.remastercheck;

import legend.game.types.Model124;

import javax.annotation.Nullable;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.List;

/**
 * FaceHash (SPEC §3.3) và mặt LIVE (§3.4), viết lại độc lập từ SPEC.md.
 * <ul>
 *   <li>VRAM ảo 1024 x 512 u16 (gồm bit STP), khởi tạo 0; đặt TIM: {@link #placeNative} (rect gốc: trận / story / quái) hoặc
 *       {@link #placeAt} (ô sobj 0: ảnh (576, 256), CLUT (576, 368) — §3.3.7);</li>
 *   <li>{@link #faceHash}: hộp bao uv (v ngoài, u trong), mọi lần đọc bọc x & 1023, y & 511, FNV-1a 32 trên 2 byte LE mỗi texel,
 *       0 -> 1; mặt bpp 3 -> 0 (không băm);</li>
 *   <li>{@link #generatorHashes}: quy tắc bộ sinh §3.3.5 (0 cho bpp 3 và mặt đọc ngoài TIM đã đặt);</li>
 *   <li>{@link #liveModel}: LIVE a-c của mô hình; {@link #expectedVariant}: biến thể mà §4.4 phải chọn.</li>
 * </ul>
 */
public final class RefFaceHash {
  private RefFaceHash() { }

  public static final int W = 1024;
  public static final int H = 512;

  /** Nguồn texel: VRAM ảo của bộ kiểm hoặc GPU của game (getPixel15). */
  public interface Vram {
    int get(int x, int y);
  }

  public static final class IntVram implements Vram {
    public final int[] px = new int[W * H];

    @Override
    public int get(final int x, final int y) {
      return this.px[y * W + x];
    }

    public void put(final int x, final int y, final int w, final int h, final int[] data) {
      for(int j = 0; j < h; j++) {
        for(int i = 0; i < w; i++) {
          this.px[(y + j) * W + x + i] = data[j * w + i] & 0xffff;
        }
      }
    }
  }

  /** TIM: bpp (flags & 3), CLUT (có thể null) và ảnh, mỗi word u16. */
  public record Tim(int bpp, @Nullable int[] clut, int cx, int cy, int cw, int ch, int[] img, int ix, int iy, int iw, int ih) {
    /** Bề rộng texel (như Tim.getImageRect().w * widthDivisor của SC). */
    public int texelWidth() {
      return this.iw * (this.bpp == 0 ? 4 : this.bpp == 1 ? 2 : 1);
    }
  }

  public static Tim parseTim(final byte[] b) {
    final ByteBuffer d = ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN);
    if(d.getInt(0) != 0x10) {
      throw new IllegalArgumentException("khong phai TIM");
    }
    final int flags = d.getInt(4);
    int o = 8;
    int[] clut = null;
    int cx = 0;
    int cy = 0;
    int cw = 0;
    int ch = 0;
    if((flags & 8) != 0) {
      final int len = d.getInt(o);
      cx = d.getShort(o + 4) & 0xffff;
      cy = d.getShort(o + 6) & 0xffff;
      cw = d.getShort(o + 8) & 0xffff;
      ch = d.getShort(o + 10) & 0xffff;
      clut = new int[cw * ch];
      for(int i = 0; i < clut.length; i++) {
        clut[i] = d.getShort(o + 12 + 2 * i) & 0xffff;
      }
      o += len;
    }
    final int ix = d.getShort(o + 4) & 0xffff;
    final int iy = d.getShort(o + 6) & 0xffff;
    final int iw = d.getShort(o + 8) & 0xffff;
    final int ih = d.getShort(o + 10) & 0xffff;
    final int[] img = new int[iw * ih];
    for(int i = 0; i < img.length; i++) {
      img[i] = d.getShort(o + 12 + 2 * i) & 0xffff;
    }
    return new Tim(flags & 3, clut, cx, cy, cw, ch, img, ix, iy, iw, ih);
  }

  /** Rect đã đặt: {ix, iy, iw, ih, cx, cy, cw, ch} (cw = 0 khi không có CLUT). */
  public static int[] placeNative(final IntVram v, final Tim t) {
    v.put(t.ix(), t.iy(), t.iw(), t.ih(), t.img());
    if(t.clut() != null) {
      v.put(t.cx(), t.cy(), t.cw(), t.ch(), t.clut());
    }
    return new int[] {t.ix(), t.iy(), t.iw(), t.ih(), t.cx(), t.cy(), t.clut() == null ? 0 : t.cw(), t.ch()};
  }

  /** Ảnh tại (x, y), CLUT tại (cx, cy) bất kể rect trong TIM (export_tmd.py load_field: ô 0 = (576, 256) / (576, 368)). */
  public static int[] placeAt(final IntVram v, final Tim t, final int x, final int y, final int cx, final int cy) {
    v.put(x, y, t.iw(), t.ih(), t.img());
    if(t.clut() != null) {
      v.put(cx, cy, t.cw(), t.ch(), t.clut());
    }
    return new int[] {x, y, t.iw(), t.ih(), cx, cy, t.clut() == null ? 0 : t.cw(), t.ch()};
  }

  public static final int FNV_OFFSET = 0x811C9DC5;
  public static final int FNV_PRIME = 0x01000193;

  /** FaceHash §3.3.4 của một mặt có texture; 0 khi bpp = 3. */
  public static int faceHash(final Vram vram, final RefBuild.Face f) {
    final int bpp = f.bpp();
    if(bpp == 3) {
      return 0;
    }
    final int tpX = (f.tpage & 0xF) * 64;
    final int tpY = (f.tpage & 0x10) != 0 ? 256 : 0;
    final int cx = (f.clut & 0x3F) * 16;
    final int cy = f.clut >>> 6;
    int umin = 255;
    int umax = 0;
    int vmin = 255;
    int vmax = 0;
    for(int k = 0; k < f.vc; k++) {
      umin = Math.min(umin, f.u[k]);
      umax = Math.max(umax, f.u[k]);
      vmin = Math.min(vmin, f.v[k]);
      vmax = Math.max(vmax, f.v[k]);
    }
    int h = FNV_OFFSET;
    for(int v = vmin; v <= vmax; v++) {
      for(int u = umin; u <= umax; u++) {
        final int px;
        if(bpp == 0) {
          final int idx = vram.get(tpX + (u >> 2) & 1023, tpY + v & 511) >> ((u & 3) * 4) & 0xF;
          px = vram.get(cx + idx & 1023, cy & 511);
        } else if(bpp == 1) {
          final int idx = vram.get(tpX + (u >> 1) & 1023, tpY + v & 511) >> ((u & 1) * 8) & 0xFF;
          px = vram.get(cx + idx & 1023, cy & 511);
        } else {
          px = vram.get(tpX + u & 1023, tpY + v & 511);
        }
        h ^= px & 0xFF;
        h *= FNV_PRIME;
        h ^= px >>> 8 & 0xFF;
        h *= FNV_PRIME;
      }
    }
    return h == 0 ? 1 : h;
  }

  /** Véc-tơ FaceHash thô (§3.3.6: mọi mặt có texture theo textured face index; bpp 3 -> 0). */
  public static int[] rawVector(final Vram vram, final List<List<RefBuild.Face>> parts) {
    final int n = (int)parts.stream().flatMap(List::stream).filter(f -> f.textured).count();
    final int[] out = new int[n];
    int g = 0;
    for(final List<RefBuild.Face> faces : parts) {
      for(final RefBuild.Face f : faces) {
        if(f.textured) {
          out[g++] = faceHash(vram, f);
        }
      }
    }
    return out;
  }

  public static String vectorSha1(final int[] hashes) {
    final ByteBuffer b = ByteBuffer.allocate(4 * hashes.length).order(ByteOrder.LITTLE_ENDIAN);
    for(final int h : hashes) {
      b.putInt(h);
    }
    return RefKey.sha1Hex(b.array());
  }

  /** Dấu chân word VRAM (§3.4 b): {x0, x1, y0, y1}, không bọc; null khi bpp 3. */
  @Nullable
  public static int[] footprint(final RefBuild.Face f) {
    final int bpp = f.bpp();
    if(bpp == 3) {
      return null;
    }
    final int sh = bpp == 0 ? 2 : bpp == 1 ? 1 : 0;
    final int tpX = (f.tpage & 0xF) * 64;
    final int tpY = (f.tpage & 0x10) != 0 ? 256 : 0;
    int umin = 255;
    int umax = 0;
    int vmin = 255;
    int vmax = 0;
    for(int k = 0; k < f.vc; k++) {
      umin = Math.min(umin, f.u[k]);
      umax = Math.max(umax, f.u[k]);
      vmin = Math.min(vmin, f.v[k]);
      vmax = Math.max(vmax, f.v[k]);
    }
    return new int[] {tpX + (umin >> sh), tpX + (umax >> sh), tpY + vmin, tpY + vmax};
  }

  /** §3.3.5: mặt đọc ra ngoài rect ảnh / CLUT đã đặt (placed = {ix, iy, iw, ih, cx, cy, cw, ch}). */
  public static boolean outsideTim(final RefBuild.Face f, final int[] placed) {
    final int[] fp = footprint(f);
    if(fp == null) {
      return false;
    }
    if(fp[0] < placed[0] || fp[1] >= placed[0] + placed[2] || fp[2] < placed[1] || fp[3] >= placed[1] + placed[3]) {
      return true;
    }
    final int bpp = f.bpp();
    if((bpp == 0 || bpp == 1) && placed[6] > 0) {
      final int cx = (f.clut & 0x3F) * 16;
      final int cy = f.clut >>> 6;
      final int n = bpp == 0 ? 16 : 256;
      return cx < placed[4] || cx + n > placed[4] + placed[6] || cy < placed[5] || cy >= placed[5] + placed[7];
    }
    return false;
  }

  /** faceHash lưu trong biến thể theo quy tắc bộ sinh §3.3.5. */
  public static int[] generatorHashes(final Vram vram, final List<List<RefBuild.Face>> parts, final int[] placed) {
    final int[] raw = rawVector(vram, parts);
    int g = 0;
    for(final List<RefBuild.Face> faces : parts) {
      for(final RefBuild.Face f : faces) {
        if(f.textured) {
          if(f.bpp() == 3 || outsideTim(f, placed)) {
            raw[g] = 0;
          }
          g++;
        }
      }
    }
    return raw;
  }

  /** LIVE a-c (§3.4) theo textured face index, từ Model124 đúng như runtime thấy lúc fromModel. */
  public static boolean[] liveModel(final Model124 model, final List<List<RefBuild.Face>> parts) {
    final int n = (int)parts.stream().flatMap(List::stream).filter(f -> f.textured).count();
    final boolean[] live = new boolean[n];
    if(model.clutAnimations_a4 != null) {
      java.util.Arrays.fill(live, true);
      return live;
    }
    final List<int[]> rects = new java.util.ArrayList<>();
    if(model.uvAdjustments_9d != legend.game.tmd.UvAdjustmentMetrics14.NONE) {
      for(int i = 0; i < 7; i++) {
        final short[] m = model.animationMetrics_d0[i];
        if(m == null || m.length < 5) {
          continue;
        }
        final int x = m[1] + model.uvAdjustments_9d.tpageX;
        final int y = m[2] + model.uvAdjustments_9d.tpageY;
        final int w = m[3] / 4;
        final int h = m[4];
        if(w > 0 && h > 0) {
          rects.add(new int[] {x, y, w, h});
        }
      }
    }
    int g = 0;
    for(final List<RefBuild.Face> faces : parts) {
      for(final RefBuild.Face f : faces) {
        if(!f.textured) {
          continue;
        }
        final int[] fp = footprint(f);
        if(fp == null) {
          live[g] = true;
        } else {
          for(final int[] r : rects) {
            if(fp[0] < r[0] + r[2] && r[0] <= fp[1] && fp[2] < r[1] + r[3] && r[1] <= fp[3]) {
              live[g] = true;
              break;
            }
          }
        }
        g++;
      }
    }
    return live;
  }

  /** LIVE của bộ ATLAS biến thể v: LIVE(a-c) ∪ {g : faceHash[g] == 0} (§3.4 d). */
  public static boolean[] liveVariant(final boolean[] model, final int[] faceHash) {
    final boolean[] out = model.clone();
    for(int g = 0; g < out.length; g++) {
      if(faceHash[g] == 0) {
        out[g] = true;
      }
    }
    return out;
  }

  /** §4.4: biến thể đầu tiên mà mọi mặt không LIVE (a-c) và faceHash lưu != 0 trùng hash runtime; -1 nếu không có. */
  public static int expectedVariant(final int[] runtime, final int[][] variants, final boolean[] liveModel) {
    for(int v = 0; v < variants.length; v++) {
      boolean ok = true;
      for(int g = 0; g < runtime.length && ok; g++) {
        if(!liveModel[g] && variants[v][g] != 0 && variants[v][g] != runtime[g]) {
          ok = false;
        }
      }
      if(ok) {
        return v;
      }
    }
    return -1;
  }
}
