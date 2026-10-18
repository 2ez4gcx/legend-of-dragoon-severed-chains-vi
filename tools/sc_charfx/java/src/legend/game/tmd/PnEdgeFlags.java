package legend.game.tmd;

import legend.core.IoHelper;
import org.joml.Vector3f;

import java.util.HashMap;
import java.util.Map;

/**
 * PnEdgeFlags — bước tính trước lúc nạp mô hình cho làm mịn PN-triangles chạy trong geometry shader (jar thử sc-charfx).
 *
 * Dựng bảng cạnh của MỘT TmdObjTable1c (một phần cứng của mô hình) theo chỉ số đỉnh TMD — chỉ số này dùng chung giữa các
 * primitive trong một phần (TmdObjLoader nhân bản đỉnh theo primitive nhưng giữ chỉ số TMD ở pos.w).
 * Trả về các bit OR vào float cờ theo đỉnh mà TmdObjLoader vốn ghi:
 *   bit 5-6   chỉ số góc cục bộ (0..3) trong primitive
 *   bit 7-10  "cạnh tới góc cục bộ j là cạnh thẳng" (không uốn)
 *   bit 11    bật PN (primitive lit + gouraud + đục, và mô hình được chọn)
 * Cạnh thẳng khi là biên (đường nối giữa các phần), không đa tạp (>2 mặt), chạm primitive phẳng/không chiếu sáng/trong suốt,
 * là nếp gấp (pháp tuyến hai bên khác nhau) hoặc gập quá MAX_DIHEDRAL_DEG. Quyết định theo từng cạnh nên hai mặt
 * chung cạnh luôn giống nhau -> bề mặt sau khi chia vẫn kín.
 * Primitive trong suốt ((id | specialFlags) & 0b10, giống TmdObjLoader) không bật PN: tmd_pn.gsh vẽ mặt TRANSLUCENT theo
 * đường gốc (phẳng), nên cạnh chung với mặt đục phải thẳng ở cả hai bên, nếu không sẽ hở (Dart chiến đấu có 1 mặt như vậy).
 * Tứ giác TMD: góc 0,1,2,3 theo hình chữ Z, vòng biên 0-1-3-2, đường chéo trong là 1-2 (TmdObjLoader dựng tam giác 2,1,0 và 1,2,3).
 * Số liệu đối chiếu (kiểm trong PnCheck): Dart chiến đấu 1954 góc / 1950 góc PN / 1378 bit cạnh thẳng (PnCount của bước
 * nghiên cứu ra 1360 bit vì khi đó còn bật PN cho mặt trong suốt).
 */
public final class PnEdgeFlags {
  private PnEdgeFlags() { }

  public static final int PN_ENABLE = 0x800;
  public static final int LOCAL_SHIFT = 5;
  public static final int LINEAR_SHIFT = 7;
  public static final float MAX_DIHEDRAL_DEG = 100.0f;
  private static final float COS_MAX_DIHEDRAL = (float)Math.cos(Math.toRadians(MAX_DIHEDRAL_DEG));

  private static final class EdgeUse {
    int faces;
    boolean linear;
    int nA = -1, nB = -1; // chỉ số pháp tuyến ở (đỉnh nhỏ, đỉnh lớn) của mặt đầu tiên
    final Vector3f faceNormal = new Vector3f();
  }

  /** @return flags[nhóm primitive][gói][góc] */
  public static int[][][] compute(final TmdObjTable1c objTable, final int specialFlags, final boolean optIn) {
    final Map<Long, EdgeUse> edges = new HashMap<>();
    final int[][][] out = new int[objTable.primitives_10.length][][];
    final int[] v = new int[4];
    final int[] n = new int[4];

    // Lượt 1: gom cạnh
    for(int g = 0; g < objTable.primitives_10.length; g++) {
      final TmdObjTable1c.Primitive primitive = objTable.primitives_10[g];
      final int command = (primitive.header() | specialFlags) & 0xff04_0000;
      final int id = command >>> 24;
      final boolean quad = (id & 0b1000) != 0;
      final boolean smooth = smooth(id, specialFlags);
      final int count = quad ? 4 : 3;
      final int[] ring = quad ? new int[] {0, 1, 3, 2} : new int[] {0, 1, 2};
      out[g] = new int[primitive.data().length][count];

      for(final byte[] data : primitive.data()) {
        decode(command, data, v, n);
        final Vector3f fn = faceNormal(objTable, v);

        for(int e = 0; e < ring.length; e++) {
          final int a = ring[e];
          final int b = ring[(e + 1) % ring.length];
          final int lo = Math.min(v[a], v[b]);
          final int hi = Math.max(v[a], v[b]);
          final int nLo = v[a] <= v[b] ? n[a] : n[b];
          final int nHi = v[a] <= v[b] ? n[b] : n[a];
          final EdgeUse use = edges.computeIfAbsent((long)lo << 32 | hi, k -> new EdgeUse());
          use.faces++;

          if(!smooth) {
            use.linear = true;
          } else if(use.faces == 1) {
            use.nA = nLo;
            use.nB = nHi;
            use.faceNormal.set(fn);
          } else if(use.faces == 2) {
            if(!sameNormal(objTable, use.nA, nLo) || !sameNormal(objTable, use.nB, nHi) || use.faceNormal.dot(fn) < COS_MAX_DIHEDRAL) {
              use.linear = true;
            }
          }
        }
      }
    }

    // Lượt 2: bit theo góc
    for(int g = 0; g < objTable.primitives_10.length; g++) {
      final TmdObjTable1c.Primitive primitive = objTable.primitives_10[g];
      final int command = (primitive.header() | specialFlags) & 0xff04_0000;
      final int id = command >>> 24;
      final boolean quad = (id & 0b1000) != 0;
      final boolean smooth = smooth(id, specialFlags);
      final int count = quad ? 4 : 3;

      for(int p = 0; p < primitive.data().length; p++) {
        decode(command, primitive.data()[p], v, n);

        for(int k = 0; k < count; k++) {
          int f = k << LOCAL_SHIFT;

          if(optIn && smooth) {
            f |= PN_ENABLE;
          }

          for(int j = 0; j < count; j++) {
            if(j == k) {
              continue;
            }

            final boolean diagonal = quad && (j + k == 3) && j != 0 && k != 0; // góc 1-2: đường chéo trong tứ giác
            final boolean ringEdge = !quad || !(j + k == 3);

            if(diagonal) {
              if(!smooth) {
                f |= 1 << LINEAR_SHIFT + j;
              }
            } else if(ringEdge) {
              final EdgeUse use = edges.get((long)Math.min(v[k], v[j]) << 32 | Math.max(v[k], v[j]));
              if(!smooth || use == null || use.faces != 2 || use.linear) {
                f |= 1 << LINEAR_SHIFT + j;
              }
            }
          }

          out[g][p][k] = f;
        }
      }
    }

    return out;
  }

  /** lit && gouraud && đục; trong suốt theo đúng công thức của TmdObjLoader: ((primitiveId | specialFlags) & 0b10) != 0. */
  static boolean smooth(final int id, final int specialFlags) {
    final boolean translucent = ((id | specialFlags) & 0b10) != 0;
    return (id & 0b1) == 0 && (id & 0b1_0000) != 0 && !translucent;
  }

  private static boolean sameNormal(final TmdObjTable1c objTable, final int a, final int b) {
    if(a == b) {
      return true;
    }

    if(a < 0 || b < 0 || a >= objTable.normal_top_08.length || b >= objTable.normal_top_08.length) {
      return false;
    }

    return objTable.normal_top_08[a].distanceSquared(objTable.normal_top_08[b]) < 4e-6f;
  }

  private static Vector3f faceNormal(final TmdObjTable1c objTable, final int[] v) {
    final Vector3f a = objTable.vert_top_00[v[0]];
    final Vector3f b = new Vector3f(objTable.vert_top_00[v[1]]).sub(a);
    final Vector3f c = new Vector3f(objTable.vert_top_00[v[2]]).sub(a);
    final Vector3f nrm = b.cross(c);
    final float len = nrm.length();
    return len > 1e-6f ? nrm.div(len) : nrm;
  }

  /** Đi gói giống TmdObjLoader (đọc uv/clut/tpage, màu, pháp tuyến, đỉnh); điền chỉ số đỉnh và pháp tuyến TMD (-1 nếu không chiếu sáng). */
  static void decode(final int command, final byte[] data, final int[] v, final int[] n) {
    final int id = command >>> 24;
    final boolean shaded = (command & 0x4_0000) != 0;
    final boolean gouraud = (id & 0b1_0000) != 0;
    final boolean quad = (id & 0b1000) != 0;
    final boolean textured = (id & 0b100) != 0;
    final boolean lit = (id & 0b1) == 0;
    final int count = quad ? 4 : 3;
    int o = 0;

    if(textured) {
      o += count * 4;
    }

    if(shaded || !lit) {
      o += count * 4;
    } else if(!textured) {
      o += 4;
    }

    for(int k = 0; k < count; k++) {
      if(lit) {
        if(gouraud || k == 0) {
          n[k] = IoHelper.readUShort(data, o);
          o += 2;
        } else {
          n[k] = n[0];
        }
      } else {
        n[k] = -1;
      }

      v[k] = IoHelper.readUShort(data, o);
      o += 2;
    }
  }
}
