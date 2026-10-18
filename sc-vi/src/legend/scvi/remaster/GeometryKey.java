package legend.scvi.remaster;

import legend.game.tmd.TmdObjTable1c;
import org.joml.Vector3f;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/**
 * [sc-vi] Khoá hình học LRMK1 (LRM spec 1 §3.1), tính từ TmdObjTable1c trong bộ nhớ lúc fromModel (sau
 * Models.updateTmdPacketIlen và UvAdjustmentMetrics14 — các byte bị ghi đè đều bị loại khỏi khoá).
 *
 * partKey_i = SHA-1( 'P' ‖ u32 n_vert ‖ (s16 x, y, z)[n_vert] ‖ u32 n_normal ‖ (s16 x, y, z)[n_normal] ‖ u32 nPackets ‖
 *                    mỗi gói đã làm phẳng: u32 (header run &amp; 0xffff0000) ‖ [có texture: u8 abr = (u16 data[6] &gt;&gt;&gt; 5) &amp; 3 ‖
 *                    data[4*vc ..]] | [không texture: data[0 ..]] )
 *   đỉnh: (short)Math.round(vert_top_00[k].x) …; pháp tuyến: (short)Math.round(normal_top_08[k].x * 4096f) …
 * modelKey = SHA-1( "LRMK1" ‖ u16 partCount ‖ partKey_0 ‖ … ). Mọi số nguyên little-endian.
 * Chỉ đọc, không bao giờ sửa dữ liệu của TmdObjTable1c.
 */
public final class GeometryKey {
  private GeometryKey() { }

  private static MessageDigest sha1() {
    try {
      return MessageDigest.getInstance("SHA-1");
    } catch(final NoSuchAlgorithmException e) {
      throw new IllegalStateException(e);
    }
  }

  /** Số gói đã làm phẳng của phần (= srcFaceCount). */
  public static int packetCount(final TmdObjTable1c table) {
    int n = 0;
    for(final TmdObjTable1c.Primitive run : table.primitives_10) {
      n += run.data().length;
    }
    return n;
  }

  /** Số gói có texture (bit 0x04 của id) của phần. */
  public static int texturedCount(final TmdObjTable1c table) {
    int n = 0;
    for(final TmdObjTable1c.Primitive run : table.primitives_10) {
      if((run.header() >>> 24 & 0x4) != 0) {
        n += run.data().length;
      }
    }
    return n;
  }

  /** [g] = mặt có texture thứ g (chỉ số toàn cục: phần theo thứ tự, rồi gói đã làm phẳng) là tứ giác (bit 0x08 của id). */
  static boolean[] texturedQuads(final TmdObjTable1c[] tables, final int texturedCount) {
    final boolean[] out = new boolean[texturedCount];
    int g = 0;
    for(final TmdObjTable1c table : tables) {
      for(final TmdObjTable1c.Primitive run : table.primitives_10) {
        final int id = run.header() >>> 24;
        if((id & 0x4) != 0) {
          for(int k = 0; k < run.data().length; k++) {
            out[g++] = (id & 0x8) != 0;
          }
        }
      }
    }
    return out;
  }

  public static byte[] partKey(final TmdObjTable1c table) {
    final Vector3f[] verts = table.vert_top_00;
    final Vector3f[] normals = table.normal_top_08;

    long size = 1 + 4 + 6L * verts.length + 4 + 6L * normals.length + 4;
    for(final TmdObjTable1c.Primitive run : table.primitives_10) {
      final int header = run.header() & 0xffff_0000;
      final int id = header >>> 24;
      final boolean textured = (id & 0x4) != 0;
      final int vc = (id & 0x8) != 0 ? 4 : 3;

      for(final byte[] data : run.data()) {
        size += 4;
        if(textured) {
          if(data.length < Math.max(8, 4 * vc)) {
            throw new IllegalStateException("textured packet too short");
          }
          size += 1 + data.length - 4L * vc;
        } else {
          size += data.length;
        }
      }
    }

    if(size > Integer.MAX_VALUE - 16) {
      throw new IllegalStateException("part too large for key");
    }

    final ByteBuffer buf = ByteBuffer.allocate((int)size).order(ByteOrder.LITTLE_ENDIAN);
    buf.put((byte)'P');
    buf.putInt(verts.length);
    for(final Vector3f v : verts) {
      buf.putShort((short)Math.round(v.x));
      buf.putShort((short)Math.round(v.y));
      buf.putShort((short)Math.round(v.z));
    }

    buf.putInt(normals.length);
    for(final Vector3f n : normals) {
      buf.putShort((short)Math.round(n.x * 4096.0f));
      buf.putShort((short)Math.round(n.y * 4096.0f));
      buf.putShort((short)Math.round(n.z * 4096.0f));
    }

    buf.putInt(packetCount(table));
    for(final TmdObjTable1c.Primitive run : table.primitives_10) {
      final int header = run.header() & 0xffff_0000;
      final int id = header >>> 24;
      final boolean textured = (id & 0x4) != 0;
      final int vc = (id & 0x8) != 0 ? 4 : 3;

      for(final byte[] data : run.data()) {
        buf.putInt(header);
        if(textured) {
          final int tpage = data[6] & 0xff | (data[7] & 0xff) << 8;
          buf.put((byte)(tpage >>> 5 & 3));
          buf.put(data, 4 * vc, data.length - 4 * vc);
        } else {
          buf.put(data);
        }
      }
    }

    final MessageDigest md = sha1();
    md.update(buf.array(), 0, buf.position());
    return md.digest();
  }

  public static byte[] modelKey(final byte[][] partKeys) {
    final MessageDigest md = sha1();
    md.update("LRMK1".getBytes(StandardCharsets.US_ASCII));
    md.update((byte)(partKeys.length & 0xff));
    md.update((byte)(partKeys.length >>> 8 & 0xff));
    for(final byte[] k : partKeys) {
      md.update(k);
    }
    return md.digest();
  }

  static byte[] sha1(final byte[] data, final int off, final int len) {
    final MessageDigest md = sha1();
    md.update(data, off, len);
    return md.digest();
  }
}
