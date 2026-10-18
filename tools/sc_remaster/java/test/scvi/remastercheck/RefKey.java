package scvi.remastercheck;

import legend.game.tmd.TmdObjTable1c;
import org.joml.Vector3f;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

/**
 * Khoá hình học LRMK1 (SPEC §3.1), viết lại độc lập từ SPEC.md — không dùng mã của sc-vi/legend/scvi/remaster.
 *
 * partKey = SHA-1('P' ‖ u32 n_vert ‖ s16 xyz × n_vert ‖ u32 n_normal ‖ s16 xyz × n_normal ‖ u32 nPackets ‖ gói...),
 * mỗi gói: u32 (header của run & 0xffff0000) ‖ [u8 abr = (u16 data[6] >>> 5) & 3 nếu id & 4] ‖ đuôi
 * (có texture: data[4*vc ..), không: data[0 ..)). modelKey = SHA-1('LRMK1' ‖ u16 partCount ‖ partKey...).
 * Tính trên TmdObjTable1c trong bộ nhớ (live: sau updateTmdPacketIlen và UvAdjust — các byte đó bị loại khỏi khoá).
 */
public final class RefKey {
  private RefKey() { }

  public static final HexFormat HEX = HexFormat.of();

  public static MessageDigest sha1() {
    try {
      return MessageDigest.getInstance("SHA-1");
    } catch(final NoSuchAlgorithmException e) {
      throw new RuntimeException(e);
    }
  }

  public static byte[] sha1(final byte[] data) {
    return sha1().digest(data);
  }

  public static String sha1Hex(final byte[] data) {
    return HEX.formatHex(sha1(data));
  }

  static void u16(final MessageDigest md, final int v) {
    md.update((byte)v);
    md.update((byte)(v >>> 8));
  }

  static void u32(final MessageDigest md, final int v) {
    md.update((byte)v);
    md.update((byte)(v >>> 8));
    md.update((byte)(v >>> 16));
    md.update((byte)(v >>> 24));
  }

  /** Số gói đã làm phẳng của một phần (= srcFaceCount). */
  public static int packetCount(final TmdObjTable1c t) {
    int n = 0;
    for(final TmdObjTable1c.Primitive p : t.primitives_10) {
      n += p.data().length;
    }
    return n;
  }

  public static byte[] partKey(final TmdObjTable1c t) {
    final MessageDigest md = sha1();
    md.update((byte)'P');
    u32(md, t.vert_top_00.length);
    for(final Vector3f v : t.vert_top_00) {
      u16(md, (short)Math.round(v.x));
      u16(md, (short)Math.round(v.y));
      u16(md, (short)Math.round(v.z));
    }
    u32(md, t.normal_top_08.length);
    for(final Vector3f n : t.normal_top_08) {
      u16(md, (short)Math.round(n.x * 4096.0f));
      u16(md, (short)Math.round(n.y * 4096.0f));
      u16(md, (short)Math.round(n.z * 4096.0f));
    }
    u32(md, packetCount(t));
    for(final TmdObjTable1c.Primitive p : t.primitives_10) {
      final int header = p.header() & 0xffff_0000;
      final int id = p.header() >>> 24;
      final boolean textured = (id & 0x04) != 0;
      final int vc = (id & 0x08) != 0 ? 4 : 3;
      for(final byte[] d : p.data()) {
        u32(md, header);
        if(textured) {
          final int tpage = d[6] & 0xff | (d[7] & 0xff) << 8;
          md.update((byte)(tpage >>> 5 & 3));
          md.update(d, 4 * vc, d.length - 4 * vc);
        } else {
          md.update(d);
        }
      }
    }
    return md.digest();
  }

  public static byte[] modelKey(final byte[][] partKeys) {
    final MessageDigest md = sha1();
    md.update("LRMK1".getBytes(java.nio.charset.StandardCharsets.US_ASCII));
    u16(md, partKeys.length);
    for(final byte[] k : partKeys) {
      md.update(k);
    }
    return md.digest();
  }

  public static byte[][] partKeys(final TmdObjTable1c[] parts) {
    final byte[][] keys = new byte[parts.length][];
    for(int i = 0; i < parts.length; i++) {
      keys[i] = partKey(parts[i]);
    }
    return keys;
  }

  public static String modelKeyHex(final TmdObjTable1c[] parts) {
    return HEX.formatHex(modelKey(partKeys(parts)));
  }
}
