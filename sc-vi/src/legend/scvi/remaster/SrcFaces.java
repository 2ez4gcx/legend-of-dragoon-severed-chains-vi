package legend.scvi.remaster;

import legend.core.IoHelper;
import legend.game.tmd.TmdObjLoader;
import legend.game.tmd.TmdObjTable1c;

/**
 * [sc-vi] Giải mã các gói (source face) của một phần đúng như TmdObjLoader.fromObjTable (affcef0 TmdObjLoader.java:89-186,
 * specialFlags = 0): cùng cờ, cùng lớp lưới, cùng quy tắc backfaceCulling (:291-296). Đọc dữ liệu LIVE (sau
 * updateTmdPacketIlen và UvAdjustmentMetrics14), không bao giờ sửa.
 *
 * Mặt thứ f = gói thứ f theo thứ tự đã làm phẳng (run theo thứ tự, data[] theo thứ tự). Lớp lưới: CLASS_OPAQUE,
 * CLASS_UNTEXTURED_TRANSLUCENT, 2 + abr (Translucency.of(tpage &gt;&gt;&gt; 5 &amp; 3)) cho mặt có texture + trong mờ.
 */
final class SrcFaces {
  static final int CLASS_OPAQUE = 0;
  static final int CLASS_UNTEXTURED_TRANSLUCENT = 1;
  /** 2 lớp không-Translucency + 4 Translucency. */
  static final int CLASS_COUNT = 6;

  final int count;
  final int nVert;
  final boolean[] quad;
  final boolean[] textured;
  final boolean[] lit;
  final boolean[] coloured;
  final int[] vc;
  /** cờ đỉnh retail (LIT/TEXTURED/COLOURED/TRANSLUCENT/QUAD). */
  final int[] flags;
  final int[] meshClass;
  final int[] tpage;
  final int[] clut;
  /** [f * 4 + k] */
  final int[] u;
  final int[] v;
  final int[] colour;
  /** chỉ số đỉnh TMD của góc k (để kiểm như Java: vượt n_vert thì ném). */
  final int[] vertexIndex;
  final boolean backfaceCulling;
  final boolean anyTextured;
  final int texturedCount;

  private SrcFaces(final int count, final int nVert) {
    this.count = count;
    this.nVert = nVert;
    this.quad = new boolean[count];
    this.textured = new boolean[count];
    this.lit = new boolean[count];
    this.coloured = new boolean[count];
    this.vc = new int[count];
    this.flags = new int[count];
    this.meshClass = new int[count];
    this.tpage = new int[count];
    this.clut = new int[count];
    this.u = new int[count * 4];
    this.v = new int[count * 4];
    this.colour = new int[count * 4];
    this.vertexIndex = new int[count * 4];
    this.backfaceCulling = true;
    this.anyTextured = false;
    this.texturedCount = 0;
  }

  private SrcFaces(final SrcFaces src, final boolean backfaceCulling, final boolean anyTextured, final int texturedCount) {
    this.count = src.count;
    this.nVert = src.nVert;
    this.quad = src.quad;
    this.textured = src.textured;
    this.lit = src.lit;
    this.coloured = src.coloured;
    this.vc = src.vc;
    this.flags = src.flags;
    this.meshClass = src.meshClass;
    this.tpage = src.tpage;
    this.clut = src.clut;
    this.u = src.u;
    this.v = src.v;
    this.colour = src.colour;
    this.vertexIndex = src.vertexIndex;
    this.backfaceCulling = backfaceCulling;
    this.anyTextured = anyTextured;
    this.texturedCount = texturedCount;
  }

  static SrcFaces decode(final TmdObjTable1c objTable) {
    final SrcFaces out = new SrcFaces(GeometryKey.packetCount(objTable), objTable.vert_top_00.length);
    boolean backfaceCulling = true;
    boolean anyTextured = false;
    int texturedCount = 0;
    int f = 0;

    for(int primitiveIndex = 0; primitiveIndex < objTable.primitives_10.length; primitiveIndex++) {
      final TmdObjTable1c.Primitive primitive = objTable.primitives_10[primitiveIndex];

      // như TmdObjLoader.java:93-123 (specialFlags = 0)
      final int command = primitive.header() & 0xff04_0000;
      final int primitiveId = command >>> 24;
      if((primitiveId >>> 5 & 0b11) != 1) {
        throw new RuntimeException("Unsupported primitive type");
      }

      final boolean shaded = (command & 0x4_0000) != 0;
      final boolean gourad = (primitiveId & 0b1_0000) != 0;
      final boolean quad = (primitiveId & 0b1000) != 0;
      final boolean textured = (primitiveId & 0b100) != 0;
      final boolean translucent = (primitiveId & 0b10) != 0;
      final boolean lit = (primitiveId & 0b1) == 0;

      if(textured && shaded) {
        throw new RuntimeException("Invalid primitive type");
      }

      if(!textured && !lit) {
        throw new RuntimeException("Invalid primitive type");
      }

      final int vertexCount = quad ? 4 : 3;
      final boolean coloured = shaded || !lit || !textured;

      int flags = 0;
      if(lit) {
        flags |= TmdObjLoader.LIT_FLAG;
      }
      if(textured) {
        flags |= TmdObjLoader.TEXTURED_FLAG;
        anyTextured = true;
      }
      if(coloured) {
        flags |= TmdObjLoader.COLOURED_FLAG;
      }
      if(translucent) {
        flags |= TmdObjLoader.TRANSLUCENT_FLAG;
      }
      if(quad) {
        flags |= TmdObjLoader.QUAD_FLAG;
      }

      for(final byte[] data : primitive.data()) {
        out.quad[f] = quad;
        out.textured[f] = textured;
        out.lit[f] = lit;
        out.coloured[f] = coloured;
        out.vc[f] = vertexCount;
        out.flags[f] = flags;

        // như TmdObjLoader.java:127-186
        int primitivesOffset = 0;
        int meshClass = CLASS_OPAQUE;

        if(textured) {
          texturedCount++;
          for(int k = 0; k < vertexCount; k++) {
            out.u[f * 4 + k] = IoHelper.readUByte(data, primitivesOffset++);
            out.v[f * 4 + k] = IoHelper.readUByte(data, primitivesOffset++);

            if(k == 0) {
              out.clut[f] = IoHelper.readUShort(data, primitivesOffset);
            } else if(k == 1) {
              out.tpage[f] = IoHelper.readUShort(data, primitivesOffset);

              if(translucent) {
                meshClass = 2 + (out.tpage[f] >>> 5 & 0b11);
              }
            }

            primitivesOffset += 2;
          }
        } else if(translucent) {
          meshClass = CLASS_UNTEXTURED_TRANSLUCENT;
        }

        if(shaded || !lit) {
          for(int k = 0; k < vertexCount; k++) {
            out.colour[f * 4 + k] = IoHelper.readInt(data, primitivesOffset);
            primitivesOffset += 4;
          }
        } else if(!textured) {
          final int colour = IoHelper.readInt(data, primitivesOffset);
          primitivesOffset += 4;

          for(int k = 0; k < vertexCount; k++) {
            out.colour[f * 4 + k] = colour;
          }
        }

        for(int k = 0; k < vertexCount; k++) {
          if(lit && (gourad || k == 0)) {
            primitivesOffset += 2; // chỉ số pháp tuyến: remaster dùng pháp tuyến trong file LRM
          }

          final int vertexIndex = IoHelper.readUShort(data, primitivesOffset);
          primitivesOffset += 2;

          if(vertexIndex >= objTable.vert_top_00.length) {
            throw new ArrayIndexOutOfBoundsException("vertex index " + vertexIndex + " >= " + objTable.vert_top_00.length);
          }

          out.vertexIndex[f * 4 + k] = vertexIndex;
        }

        if(translucent && !textured) {
          backfaceCulling = false;
        }

        out.meshClass[f] = meshClass;
        f++;
      }
    }

    return new SrcFaces(out, backfaceCulling, anyTextured, texturedCount);
  }

  /** bpp live = (tpage &gt;&gt;&gt; 7) &amp; 3. */
  int bpp(final int face) {
    return this.tpage[face] >>> 7 & 3;
  }
}
