package scvi.remastercheck;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.SplittableRandom;

/**
 * Sinh đột biến file LRM1 (fuzz, mục (e)): cắt cụt, thừa byte, header (magic/version/flags/zero/generator/partCount/
 * variantCount 99/bodySize/level), modelKey, partKey, srcFaceCount, mode, P/C/T, NaN/Inf, chỉ số corner / tri ngoài phạm vi,
 * srcFace, role, nearestTmdVertex, thứ tự tam giác, biến thể (pngSha1 sai, w/h, texturedFaceCount, faceHash, atlasUv), thân zlib
 * (nén hợp lệ, cắt, thừa, lật byte, mất cờ). Đột biến có thể làm file sai (runtime phải đi đường gốc) HOẶC vẫn hợp lệ (runtime
 * phải dựng đúng file mới) — bộ kiểm không giả định, mà phân loại lại bằng {@link RefLrm#read} rồi so với lưới mong đợi tương ứng.
 * Mọi số ngẫu nhiên từ SplittableRandom có hạt cố định nên chạy lại ra cùng bộ đột biến.
 */
public final class Fuzz {
  private Fuzz() { }

  public record Mutation(String kind, byte[] data) { }

  /** Vị trí (tính từ đầu file) của bản ghi từng phần và từng biến thể trong file không nén. */
  static int[][] offsets(final RefLrm.Lrm l) {
    final int[] parts = new int[l.parts.length];
    int o = RefLrm.HEADER;
    for(int i = 0; i < l.parts.length; i++) {
      parts[i] = o;
      final RefLrm.Part p = l.parts[i];
      o += p.mode == 1 ? 40 + 12 * p.P + 32 * p.C + 12 * p.T : 28;
    }
    final int[] vars = new int[l.variants.length];
    for(int v = 0; v < l.variants.length; v++) {
      vars[v] = o;
      o += 28 + 36 * l.variants[v].n;
    }
    return new int[][] {parts, vars};
  }

  static void put32(final byte[] b, final int o, final int v) {
    ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN).putInt(o, v);
  }

  static void put16(final byte[] b, final int o, final int v) {
    ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN).putShort(o, (short)v);
  }

  static void putF(final byte[] b, final int o, final float v) {
    ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN).putFloat(o, v);
  }

  static final float[] BAD = {Float.NaN, Float.POSITIVE_INFINITY, Float.NEGATIVE_INFINITY, Float.intBitsToFloat(0x7fc00001)};

  /** Danh sách loại đột biến dùng được cho file này (có / không có biến thể, phần mode 1). */
  public static List<String> kinds(final RefLrm.Lrm l) {
    final List<String> k = new ArrayList<>(List.of(
      "truncate", "truncate", "append", "magic", "version", "flags", "hdrzero", "generator", "partCount", "variantCount99",
      "bodySize", "level", "modelKey", "partKey", "partKeyRekey", "partsRekey", "srcFaceCount", "modeBad", "partZero",
      "deflate", "deflateTrunc", "deflateTrail", "deflateFlip", "deflateNoFlag", "deflateBodySize"));
    boolean mode1 = false;
    for(final RefLrm.Part p : l.parts) {
      mode1 |= p.mode == 1;
    }
    if(mode1) {
      k.addAll(List.of("toMode0", "pctLimit", "pctCount", "posNaN", "posFinite", "normNaN", "normFinite", "cornerPos", "cornerSrcRange",
        "cornerSrc", "st", "st", "nearBad", "near", "roleBad", "role", "cornerZero", "triIndex", "triSwap", "triOther", "triOrder"));
    }
    if(l.variants.length > 0) {
      k.addAll(List.of("pngSha", "sizeBad", "sizeOther", "tfc", "tfcHuge", "faceHash", "faceHashZero", "atlasNaN", "atlasRange", "atlasIn",
        "atlas4th", "variantDrop", "variantDup"));
    }
    return k;
  }

  /** base: file hợp lệ KHÔNG nén; l = base đã đọc. */
  public static Mutation mutate(final byte[] base, final RefLrm.Lrm l, final RefLrm.Runtime rt, final String kind, final SplittableRandom r) {
    byte[] b = base.clone();
    final int[][] off = offsets(l);
    final List<Integer> m1 = new ArrayList<>();
    for(int i = 0; i < l.parts.length; i++) {
      if(l.parts[i].mode == 1) {
        m1.add(i);
      }
    }
    final int pi = m1.isEmpty() ? r.nextInt(l.parts.length) : m1.get(r.nextInt(m1.size()));
    final RefLrm.Part p = l.parts[pi];
    final int po = off[0][pi];
    final int posO = po + 40;
    final int cornerO = posO + 12 * p.P;
    final int triO = cornerO + 32 * p.C;
    final int ci = p.C > 0 ? r.nextInt(p.C) : 0;
    final int ti = p.T > 0 ? r.nextInt(p.T) : 0;
    switch(kind) {
      case "truncate" -> b = Arrays.copyOf(b, r.nextInt(b.length));
      case "append" -> {
        final int n = 1 + r.nextInt(8);
        b = Arrays.copyOf(b, b.length + n);
        for(int i = b.length - n; i < b.length; i++) {
          b[i] = (byte)r.nextInt(256);
        }
      }
      case "magic" -> b[r.nextInt(4)] ^= (byte)(1 + r.nextInt(255));
      case "version" -> put16(b, 4, new int[] {0, 2, 0xffff}[r.nextInt(3)]);
      case "flags" -> put16(b, 6, 1 << r.nextInt(16));
      case "hdrzero" -> b[0x25 + r.nextInt(3)] = (byte)(1 + r.nextInt(255));
      case "generator" -> {
        final int g = 0x28 + r.nextInt(24);
        b[g] = (byte)new int[] {0x7f, 0x19, 0x80, 0xff, 0x01}[r.nextInt(5)];
      }
      case "partCount" -> put16(b, 0x1c, new int[] {0, 65, l.parts.length + 1, l.parts.length - 1, 0xffff}[r.nextInt(5)]);
      case "variantCount99" -> put16(b, 0x1e, r.nextInt(4) == 0 ? 5 : 99);
      case "bodySize" -> put32(b, 0x20, new int[] {(int)l.bodySize + 1, (int)l.bodySize - 1, 0x1000_0001, -1, 0}[r.nextInt(5)]);
      case "level" -> b[0x24] = (byte)(3 + r.nextInt(253));
      case "modelKey" -> b[8 + r.nextInt(20)] ^= (byte)(1 << r.nextInt(8));
      case "partKey" -> b[po + r.nextInt(20)] ^= (byte)(1 << r.nextInt(8));
      case "partKeyRekey" -> {
        final RefLrm.Lrm x = l.copy();
        x.parts[pi].key[r.nextInt(20)] ^= 1;
        final byte[][] pks = Arrays.stream(x.parts).map(q -> q.key).toArray(byte[][]::new);
        x.modelKey = RefKey.modelKey(pks);
        b = RefLrm.write(x, false);
      }
      // file tự nhất quán (toàn vẹn modelKey đúng với partKey của chính nó) nhưng số phần != runtime: bỏ phần cuối / chép phần 0
      // thêm -> runtime phải từ chối (modelKey != khoá runtime, partCount != số phần) trước khi đánh chỉ số mảng theo phần (WP0)
      case "partsRekey" -> {
        final RefLrm.Lrm x = l.copy();
        if(x.parts.length > 1 && (x.parts.length >= RefLrm.MAX_PARTS || r.nextBoolean())) {
          x.parts = Arrays.copyOf(x.parts, x.parts.length - 1);
        } else {
          x.parts = Arrays.copyOf(x.parts, x.parts.length + 1);
          x.parts[x.parts.length - 1] = x.parts[0].copy();
        }
        x.modelKey = RefKey.modelKey(Arrays.stream(x.parts).map(q -> q.key).toArray(byte[][]::new));
        b = RefLrm.write(x, false);
      }
      case "srcFaceCount" -> put32(b, po + 20, (int)p.srcFaceCount + (r.nextBoolean() ? 1 : -1));
      case "modeBad" -> b[po + 24] = (byte)(2 + r.nextInt(254));
      case "partZero" -> b[po + 25 + r.nextInt(3)] = (byte)(1 + r.nextInt(255));
      case "toMode0" -> {
        final RefLrm.Lrm x = l.copy();
        x.parts[pi].mode = 0;
        b = RefLrm.write(x, false);
      }
      case "pctLimit" -> put32(b, po + 28 + 4 * r.nextInt(3), new int[] {0, 200_001, -1}[r.nextInt(3)]);
      case "pctCount" -> {
        final int f = r.nextInt(3);
        final int cur = f == 0 ? p.P : f == 1 ? p.C : p.T;
        put32(b, po + 28 + 4 * f, cur + (r.nextBoolean() ? 1 : -1));
      }
      case "posNaN" -> putF(b, posO + 4 * r.nextInt(3 * p.P), BAD[r.nextInt(BAD.length)]);
      case "posFinite" -> putF(b, posO + 4 * r.nextInt(3 * p.P), (float)(r.nextDouble() * 400 - 200));
      case "normNaN" -> putF(b, cornerO + 32 * ci + 4 + 4 * r.nextInt(3), BAD[r.nextInt(BAD.length)]);
      case "normFinite" -> putF(b, cornerO + 32 * ci + 4 + 4 * r.nextInt(3), (float)(r.nextDouble() * 4 - 2));
      case "cornerPos" -> put32(b, cornerO + 32 * ci, p.P + r.nextInt(3));
      case "cornerSrcRange" -> put32(b, cornerO + 32 * ci + 16, (int)p.srcFaceCount + r.nextInt(3));
      case "cornerSrc" -> put32(b, cornerO + 32 * ci + 16, r.nextInt((int)Math.max(1, p.srcFaceCount)));
      case "st" -> {
        put16(b, cornerO + 32 * ci + 20, r.nextInt(65536));
        put16(b, cornerO + 32 * ci + 22, r.nextInt(65536));
      }
      case "nearBad" -> put16(b, cornerO + 32 * ci + 24, rt.nVerts()[pi] + r.nextInt(3));
      case "near" -> put16(b, cornerO + 32 * ci + 24, r.nextInt(Math.max(1, rt.nVerts()[pi])));
      case "roleBad" -> b[cornerO + 32 * ci + 26] = (byte)(3 + r.nextInt(253));
      case "role" -> b[cornerO + 32 * ci + 26] = (byte)r.nextInt(3);
      case "cornerZero" -> b[cornerO + 32 * ci + 27 + r.nextInt(5)] = (byte)(1 + r.nextInt(255));
      case "triIndex" -> put32(b, triO + 12 * ti + 4 * r.nextInt(3), p.C + r.nextInt(3));
      case "triSwap" -> {
        final int a = p.tri[3 * ti + 1];
        put32(b, triO + 12 * ti + 4, p.tri[3 * ti + 2]);
        put32(b, triO + 12 * ti + 8, a);
      }
      case "triOther" -> put32(b, triO + 12 * ti + 4 * r.nextInt(3), r.nextInt(p.C));
      case "triOrder" -> {
        if(p.T > 1) {
          final int tj = r.nextInt(p.T);
          for(int k = 0; k < 3; k++) {
            put32(b, triO + 12 * ti + 4 * k, p.tri[3 * tj + k]);
            put32(b, triO + 12 * tj + 4 * k, p.tri[3 * ti + k]);
          }
        }
      }
      case "pngSha" -> b[off[1][r.nextInt(l.variants.length)] + r.nextInt(20)] ^= (byte)(1 << r.nextInt(8));
      case "sizeBad" -> put16(b, off[1][r.nextInt(l.variants.length)] + 20 + 2 * r.nextInt(2), new int[] {0, 3, 4096, 100, 0xffff}[r.nextInt(5)]);
      case "sizeOther" -> {
        final int v = r.nextInt(l.variants.length);
        final int f = r.nextInt(2);
        final int cur = f == 0 ? l.variants[v].w : l.variants[v].h;
        put16(b, off[1][v] + 20 + 2 * f, cur >= 2048 ? cur / 2 : cur * 2);
      }
      case "tfc" -> put32(b, off[1][r.nextInt(l.variants.length)] + 24, l.variants[0].n + (r.nextBoolean() ? 1 : -1));
      // số đếm khổng lồ: runtime phải từ chối trước khi cấp phát 36·n byte (§3.5.4 mục 3)
      case "tfcHuge" -> put32(b, off[1][r.nextInt(l.variants.length)] + 24, new int[] {0x7fff_ffff, -1, 0x1000_0000, 0x0800_0001}[r.nextInt(4)]);
      case "faceHash" -> {
        final int v = r.nextInt(l.variants.length);
        put32(b, off[1][v] + 28 + 4 * r.nextInt(Math.max(1, l.variants[v].n)), r.nextInt());
      }
      case "faceHashZero" -> {
        final int v = r.nextInt(l.variants.length);
        put32(b, off[1][v] + 28 + 4 * r.nextInt(Math.max(1, l.variants[v].n)), 0);
      }
      case "atlasNaN", "atlasRange", "atlasIn", "atlas4th" -> {
        final int v = r.nextInt(l.variants.length);
        final int n = l.variants[v].n;
        int g = r.nextInt(Math.max(1, n));
        int corner = r.nextInt(4);
        if("atlas4th".equals(kind)) {
          corner = 3;
          for(int k = 0; k < n; k++) {
            if(rt.texturedVc()[(g + k) % n] == 3) {
              g = (g + k) % n;
              break;
            }
          }
        } else if(rt.texturedVc()[g] == 3) {
          corner = r.nextInt(3);
        }
        final float val = switch(kind) {
          case "atlasNaN", "atlas4th" -> BAD[r.nextInt(BAD.length)];
          case "atlasRange" -> r.nextBoolean() ? -0.25f - (float)r.nextDouble() : 1.0001f + (float)r.nextDouble();
          default -> (float)r.nextDouble();
        };
        putF(b, off[1][v] + 28 + 4 * n + 32 * g + 8 * corner + 4 * r.nextInt(2), val);
      }
      case "variantDrop" -> {
        final RefLrm.Lrm x = l.copy();
        x.variants = Arrays.copyOf(x.variants, x.variants.length - 1);
        b = RefLrm.write(x, false);
      }
      case "variantDup" -> {
        final RefLrm.Lrm x = l.copy();
        if(x.variants.length < RefLrm.MAX_VARIANTS) {
          x.variants = Arrays.copyOf(x.variants, x.variants.length + 1);
          x.variants[x.variants.length - 1] = x.variants[0].copy();
        }
        b = RefLrm.write(x, false);
      }
      case "deflate" -> b = RefLrm.write(l, true);
      case "deflateTrunc" -> {
        final byte[] z = RefLrm.write(l, true);
        b = Arrays.copyOf(z, RefLrm.HEADER + r.nextInt(z.length - RefLrm.HEADER));
      }
      case "deflateTrail" -> {
        final byte[] z = RefLrm.write(l, true);
        b = Arrays.copyOf(z, z.length + 1 + r.nextInt(4));
      }
      case "deflateFlip" -> {
        b = RefLrm.write(l, true);
        b[RefLrm.HEADER + r.nextInt(b.length - RefLrm.HEADER)] ^= (byte)(1 << r.nextInt(8));
      }
      case "deflateNoFlag" -> {
        b = RefLrm.write(l, true);
        put16(b, 6, 0);
      }
      case "deflateBodySize" -> {
        b = RefLrm.write(l, true);
        put32(b, 0x20, (int)l.bodySize + (r.nextBoolean() ? 1 : -1));
      }
      default -> throw new IllegalArgumentException(kind);
    }
    return new Mutation(kind, b);
  }
}
