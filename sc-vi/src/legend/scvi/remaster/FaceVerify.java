package legend.scvi.remaster;

import legend.game.tmd.UvAdjustmentMetrics14;
import legend.game.types.Model124;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;

import static legend.core.GameEngine.GPU;

/**
 * [sc-vi] FaceHash (LRM spec 1 §3.3) và tập mặt LIVE theo mô hình (§3.4 a-c) của mọi mặt có texture, đánh số theo
 * "textured face index" toàn cục (phần theo thứ tự, rồi gói có texture theo thứ tự đã làm phẳng; kể cả phần mode 0).
 *
 * FaceHash: hộp bao uv live (umin..umax × vmin..vmax, gồm hai đầu), vòng ngoài v, vòng trong u; bpp 0: chỉ số 4 bit trong
 * word V[tpY+v][tpX+(u&gt;&gt;2)], px = V[cy][cx+idx]; bpp 1: 8 bit; bpp 2: px = V[tpY+v][tpX+u]; mọi lần đọc bọc
 * (x &amp; 1023, y &amp; 511); px = 16 bit gồm STP (Gpu.getPixel15). FNV-1a 32: h = 0x811C9DC5; mỗi px: h ^= px &amp; 0xff;
 * h *= 0x01000193; h ^= px &gt;&gt;&gt; 8; h *= 0x01000193; kết quả 0 đổi thành 1. Mặt bpp 3 không băm (trả 0).
 * tpage/clut/uv lấy lúc fromModel (giá trị live mà lưới đang vẽ dùng).
 */
final class FaceVerify {
  /** Nguồn VRAM 1024×512 u16 (toạ độ đã bọc). */
  interface Vram {
    int pixel15(int x, int y);
  }

  static final Vram GPU_VRAM = (x, y) -> GPU.getPixel15(x, y);

  final int count;
  final int[] tpage;
  final int[] clut;
  final int[] umin;
  final int[] umax;
  final int[] vmin;
  final int[] vmax;

  FaceVerify(final SrcFaces[] parts) {
    int n = 0;
    for(final SrcFaces p : parts) {
      n += p.texturedCount;
    }

    this.count = n;
    this.tpage = new int[n];
    this.clut = new int[n];
    this.umin = new int[n];
    this.umax = new int[n];
    this.vmin = new int[n];
    this.vmax = new int[n];

    int g = 0;
    for(final SrcFaces p : parts) {
      for(int f = 0; f < p.count; f++) {
        if(!p.textured[f]) {
          continue;
        }

        this.tpage[g] = p.tpage[f];
        this.clut[g] = p.clut[f];
        int u0 = 255;
        int u1 = 0;
        int v0 = 255;
        int v1 = 0;
        for(int k = 0; k < p.vc[f]; k++) {
          u0 = Math.min(u0, p.u[f * 4 + k]);
          u1 = Math.max(u1, p.u[f * 4 + k]);
          v0 = Math.min(v0, p.v[f * 4 + k]);
          v1 = Math.max(v1, p.v[f * 4 + k]);
        }
        this.umin[g] = u0;
        this.umax[g] = u1;
        this.vmin[g] = v0;
        this.vmax[g] = v1;
        g++;
      }
    }
  }

  int bpp(final int g) {
    return this.tpage[g] >>> 7 & 3;
  }

  /** FaceHash §3.3.4 của mặt g; 0 nếu bpp 3. */
  int hash(final int g, final Vram vram) {
    final int bpp = this.bpp(g);
    if(bpp == 3) {
      return 0;
    }

    final int tp = this.tpage[g];
    final int tpX = (tp & 0xf) * 64;
    final int tpY = (tp & 0x10) != 0 ? 256 : 0;
    final int cx = (this.clut[g] & 0x3f) * 16;
    final int cy = this.clut[g] >>> 6;
    int h = 0x811c9dc5;

    for(int v = this.vmin[g]; v <= this.vmax[g]; v++) {
      final int y = tpY + v & 511;
      for(int u = this.umin[g]; u <= this.umax[g]; u++) {
        final int px;
        if(bpp == 0) {
          final int idx = vram.pixel15(tpX + (u >> 2) & 1023, y) >> ((u & 3) * 4) & 0xf;
          px = vram.pixel15(cx + idx & 1023, cy & 511) & 0xffff;
        } else if(bpp == 1) {
          final int idx = vram.pixel15(tpX + (u >> 1) & 1023, y) >> ((u & 1) * 8) & 0xff;
          px = vram.pixel15(cx + idx & 1023, cy & 511) & 0xffff;
        } else {
          px = vram.pixel15(tpX + u & 1023, y) & 0xffff;
        }

        h ^= px & 0xff;
        h *= 0x01000193;
        h ^= px >>> 8;
        h *= 0x01000193;
      }
    }

    return h != 0 ? h : 1;
  }

  /** Véc-tơ FaceHash thô của mọi mặt (bpp 3 = 0), §3.3.6. */
  int[] vector(final Vram vram) {
    final int[] out = new int[this.count];
    for(int g = 0; g < this.count; g++) {
      out[g] = this.hash(g, vram);
    }
    return out;
  }

  /** SHA-1 của u32 LE nối tiếp (§3.3.6), 40 hex thường. */
  static String vectorSha1(final int[] hashes) {
    final ByteBuffer buf = ByteBuffer.allocate(hashes.length * 4).order(ByteOrder.LITTLE_ENDIAN);
    for(final int h : hashes) {
      buf.putInt(h);
    }
    return RemasterLog.hex(GeometryKey.sha1(buf.array(), 0, buf.position()));
  }

  /**
   * LIVE theo mô hình (§3.4): a) clutAnimations_a4 != null =&gt; mọi mặt; b) uvAdjustments_9d != NONE và rect đích của
   * animationMetrics_d0[i] (i &lt; 7, length &gt;= 5: x = m1 + tpageX, y = m2 + tpageY, w = m3 / 4, h = m4; rỗng khi w &lt;= 0 hoặc
   * h &lt;= 0) giao dấu chân word VRAM của mặt; c) bpp live = 3.
   */
  boolean[] liveModel(final Model124 model) {
    final boolean[] live = new boolean[this.count];
    if(model.clutAnimations_a4 != null) {
      java.util.Arrays.fill(live, true);
      return live;
    }

    final int[][] rects = animRects(model);
    for(int g = 0; g < this.count; g++) {
      final int bpp = this.bpp(g);
      if(bpp == 3) {
        live[g] = true;
        continue;
      }

      final int sh = bpp == 0 ? 2 : bpp == 1 ? 1 : 0;
      final int tpX = (this.tpage[g] & 0xf) * 64;
      final int tpY = (this.tpage[g] & 0x10) != 0 ? 256 : 0;
      final int fx0 = tpX + (this.umin[g] >> sh);
      final int fx1 = tpX + (this.umax[g] >> sh);
      final int fy0 = tpY + this.vmin[g];
      final int fy1 = tpY + this.vmax[g];

      for(final int[] r : rects) {
        if(fx0 < r[0] + r[2] && r[0] <= fx1 && fy0 < r[1] + r[3] && r[1] <= fy1) {
          live[g] = true;
          break;
        }
      }
    }

    return live;
  }

  /** Rect đích hoạt cảnh texture (§3.4 b), chỉ rect không rỗng. */
  static int[][] animRects(final Model124 model) {
    final UvAdjustmentMetrics14 uv = model.uvAdjustments_9d;
    if(uv == null || uv == UvAdjustmentMetrics14.NONE) {
      return new int[0][];
    }

    final java.util.List<int[]> out = new java.util.ArrayList<>();
    for(int i = 0; i < 7 && i < model.animationMetrics_d0.length; i++) {
      final short[] m = model.animationMetrics_d0[i];
      if(m == null || m.length < 5) {
        continue;
      }

      final int x = m[1] + uv.tpageX;
      final int y = m[2] + uv.tpageY;
      final int w = m[3] / 4;
      final int h = m[4];
      if(w > 0 && h > 0) {
        out.add(new int[] {x, y, w, h});
      }
    }

    return out.toArray(int[][]::new);
  }
}
