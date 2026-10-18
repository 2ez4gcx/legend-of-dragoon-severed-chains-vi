package legend.scvi.remaster;

import legend.core.renderer.Translucency;
import legend.game.tmd.TmdObjLoader;

/**
 * [sc-vi] Dựng mảng đỉnh / chỉ số của một phần mode 1 (LRM spec 1 §3.2, §4.3). Thuần tính toán (không GL).
 *
 * Lớp lưới của mặt như getTranslucencySizes; thứ tự opaque, untextured translucent, Translucency theo ordinal, chỉ lớp có ít
 * nhất một tam giác remaster, rồi ĐẢO (TmdObjLoader.java:324-326). Đỉnh của lớp L = mọi corner (chỉ số tăng dần) có
 * lớp(srcFace) = L, 16 float mỗi đỉnh (bố cục createMesh); chỉ số = tam giác theo thứ tự file có lớp L, phát [a, a, b, a, c, a]
 * (không QUAD_FLAG nên tmd.gsh chỉ dùng đỉnh 0, 2, 4). Bộ VRAM và mọi bộ ATLAS cùng thứ tự đỉnh và chung mảng chỉ số; bộ
 * ATLAS chỉ khác float 7-9 của mặt có texture không LIVE: uv = I(atlasUv), tpage' = (tpage &amp; ~0x180) | 0x180.
 *
 * Phép f32 theo §3.2.2 (mỗi phép làm tròn float, không FMA): s = S / 65535f, t = T / 65535f; tam giác: nếu s + t &gt; 1 thì
 * t = 1 - s, w = ((1 - s) - t, s, t); tứ giác: w = ((1-s)(1-t), s(1-t), (1-s)t, st); I(x) = ((w0 x0 + w1 x1) + w2 x2) [+ w3 x3].
 */
final class RemasterBuilder {
  private RemasterBuilder() { }

  static final int STRIDE = TmdObjLoader.VERTEX_SIZE;

  /** Một lưới (một lớp) đã tính sẵn. */
  static final class MeshData {
    final int meshClass;
    final boolean textured;
    final boolean translucent;
    final Translucency translucency;
    final float[] vertices;
    final int[] indices;

    MeshData(final int meshClass, final boolean textured, final boolean translucent, final Translucency translucency, final float[] vertices, final int[] indices) {
      this.meshClass = meshClass;
      this.textured = textured;
      this.translucent = translucent;
      this.translucency = translucency;
      this.vertices = vertices;
      this.indices = indices;
    }

    String className() {
      return switch(this.meshClass) {
        case SrcFaces.CLASS_OPAQUE -> "opaque";
        case SrcFaces.CLASS_UNTEXTURED_TRANSLUCENT -> "untextured translucent";
        default -> this.translucency.toString();
      };
    }
  }

  /** Các bộ lưới của một phần: vram luôn có; atlas[v] = null khi biến thể v không dùng được. */
  static final class PartSets {
    final MeshData[] vram;
    final MeshData[][] atlas;
    final boolean backfaceCulling;

    PartSets(final MeshData[] vram, final MeshData[][] atlas, final boolean backfaceCulling) {
      this.vram = vram;
      this.atlas = atlas;
      this.backfaceCulling = backfaceCulling;
    }
  }

  /**
   * Bộ VRAM của phần (luôn dựng). texBase = chỉ số toàn cục của mặt có texture đầu tiên của phần. tw/th = kích thước
   * texture PNG ghi đè của SC (0 nếu không có; mặt bpp 3 cần khác 0 như TmdObjLoader).
   */
  static MeshData[] buildVram(final SrcFaces faces, final LrmFile.Part part, final int tw, final int th) {
    final int corners = part.cCount;
    final int tris = part.tCount;

    // lớp của từng corner / tam giác
    final int[] cornerClass = new int[corners];
    for(int c = 0; c < corners; c++) {
      cornerClass[c] = faces.meshClass[part.cornerSrc[c]];
    }

    final boolean[] present = new boolean[SrcFaces.CLASS_COUNT];
    for(int t = 0; t < tris; t++) {
      present[cornerClass[part.tri[t * 3]]] = true;
    }

    int classCount = 0;
    for(final boolean p : present) {
      if(p) {
        classCount++;
      }
    }

    final MeshData[] out = new MeshData[classCount];
    int slot = classCount - 1; // thứ tự lớp tăng dần rồi đảo => ghi từ cuối mảng
    final int[] local = new int[corners];
    final float[] w = new float[4];

    for(int cls = 0; cls < SrcFaces.CLASS_COUNT; cls++) {
      if(!present[cls]) {
        continue;
      }

      int vertexCount = 0;
      for(int c = 0; c < corners; c++) {
        if(cornerClass[c] == cls) {
          local[c] = vertexCount++;
        } else {
          local[c] = -1;
        }
      }

      final float[] vertices = new float[vertexCount * STRIDE];
      int o = 0;
      for(int c = 0; c < corners; c++) {
        if(cornerClass[c] != cls) {
          continue;
        }

        writeVertex(vertices, o, faces, part, c, tw, th, w);
        o += STRIDE;
      }

      int triCount = 0;
      for(int t = 0; t < tris; t++) {
        if(cornerClass[part.tri[t * 3]] == cls) {
          triCount++;
        }
      }

      final int[] indices = new int[triCount * 6];
      int k = 0;
      for(int t = 0; t < tris; t++) {
        if(cornerClass[part.tri[t * 3]] != cls) {
          continue;
        }

        final int a = local[part.tri[t * 3]];
        final int b = local[part.tri[t * 3 + 1]];
        final int d = local[part.tri[t * 3 + 2]];
        indices[k++] = a;
        indices[k++] = a;
        indices[k++] = b;
        indices[k++] = a;
        indices[k++] = d;
        indices[k++] = a;
      }

      final boolean textured;
      final boolean translucent;
      final Translucency translucency;
      if(cls == SrcFaces.CLASS_OPAQUE) {
        textured = faces.anyTextured;
        translucent = false;
        translucency = null;
      } else if(cls == SrcFaces.CLASS_UNTEXTURED_TRANSLUCENT) {
        textured = false;
        translucent = true;
        translucency = null;
      } else {
        textured = faces.anyTextured;
        translucent = true;
        translucency = Translucency.values()[cls - 2];
      }

      out[slot--] = new MeshData(cls, textured, translucent, translucency, vertices, indices);
    }

    return out;
  }

  /**
   * Bộ ATLAS của một biến thể từ bộ VRAM: chép mảng đỉnh, sửa float 7-9 của corner thuộc mặt có texture không LIVE
   * (live[g] theo biến thể: LIVE a-c của mô hình hoặc faceHash[g] == 0). atlasUv = f32[n][4][2] của biến thể.
   */
  static MeshData[] buildAtlas(final MeshData[] vram, final SrcFaces faces, final LrmFile.Part part, final int texBase, final boolean[] live, final float[] atlasUv) {
    // chỉ số toàn cục của từng mặt có texture trong phần
    final int[] texIndex = new int[faces.count];
    int g = texBase;
    for(int f = 0; f < faces.count; f++) {
      texIndex[f] = faces.textured[f] ? g++ : -1;
    }

    final MeshData[] out = new MeshData[vram.length];
    final float[] w = new float[4];
    for(int m = 0; m < vram.length; m++) {
      final MeshData src = vram[m];
      final float[] vertices = src.vertices.clone();
      int o = 0;
      for(int c = 0; c < part.cCount; c++) {
        if(faces.meshClass[part.cornerSrc[c]] != src.meshClass) {
          continue;
        }

        final int f = part.cornerSrc[c];
        final int tg = texIndex[f];
        if(tg >= 0 && !live[tg]) {
          final int vc = faces.vc[f];
          weights(part.cornerS[c], part.cornerT[c], faces.quad[f], w);
          final int base = tg * 8;
          vertices[o + 7] = interp(w, vc, atlasUv[base], atlasUv[base + 2], atlasUv[base + 4], atlasUv[base + 6]);
          vertices[o + 8] = interp(w, vc, atlasUv[base + 1], atlasUv[base + 3], atlasUv[base + 5], atlasUv[base + 7]);
          vertices[o + 9] = (faces.tpage[f] & ~0x180) | 0x180;
        }

        o += STRIDE;
      }

      out[m] = new MeshData(src.meshClass, src.textured, src.translucent, src.translucency, vertices, src.indices);
    }

    return out;
  }

  /** 16 float của corner c (§3.2.3). */
  private static void writeVertex(final float[] out, final int o, final SrcFaces faces, final LrmFile.Part part, final int c, final int tw, final int th, final float[] w) {
    final int f = part.cornerSrc[c];
    final int vc = faces.vc[f];
    final int p = part.cornerPos[c] * 3;
    weights(part.cornerS[c], part.cornerT[c], faces.quad[f], w);

    out[o] = part.pos[p];
    out[o + 1] = part.pos[p + 1];
    out[o + 2] = part.pos[p + 2];
    out[o + 3] = part.cornerNear[c];

    if(faces.lit[f]) {
      out[o + 4] = part.cornerNormal[c * 3];
      out[o + 5] = part.cornerNormal[c * 3 + 1];
      out[o + 6] = part.cornerNormal[c * 3 + 2];
    }

    if(faces.textured[f]) {
      final int b = f * 4;
      float u = interp(w, vc, faces.u[b], faces.u[b + 1], faces.u[b + 2], faces.u[b + 3]);
      float v = interp(w, vc, faces.v[b], faces.v[b + 1], faces.v[b + 2], faces.v[b + 3]);

      if(faces.bpp(f) == 3) {
        if((tw | th) == 0) {
          throw new RuntimeException("24bpp textures must have texture width/height specified");
        }

        u = u / tw;
        v = v / th;
      }

      out[o + 7] = u;
      out[o + 8] = v;
      out[o + 9] = faces.tpage[f];
      out[o + 10] = faces.clut[f];
    }

    if(faces.coloured[f]) {
      final int b = f * 4;
      final boolean textured = faces.textured[f];
      for(int ch = 0; ch < 4; ch++) {
        final int shift = ch * 8; // r = byte 0, g = 1, b = 2, m = 3 (MathHelper.colourToFloat)
        out[o + 11 + ch] = interp(w, vc,
          channel(faces.colour[b], shift, textured),
          channel(faces.colour[b + 1], shift, textured),
          channel(faces.colour[b + 2], shift, textured),
          channel(faces.colour[b + 3], shift, textured));
      }
    } else {
      out[o + 11] = 1.0f;
      out[o + 12] = 1.0f;
      out[o + 13] = 1.0f;
      out[o + 14] = 1.0f;
    }

    out[o + 15] = faces.flags[f] & ~TmdObjLoader.QUAD_FLAG;
  }

  /** c_k của một kênh: byte / 255f, × 2f nếu mặt có texture (nhân trước khi nội suy). */
  private static float channel(final int colour, final int shift, final boolean textured) {
    final float x = (colour >>> shift & 0xff) / 255.0f;
    return textured ? x * 2.0f : x;
  }

  /** Trọng số §3.2.2 vào w[0..3]. */
  static void weights(final int S, final int T, final boolean quad, final float[] w) {
    final float s = (float)S / 65535.0f;
    float t = (float)T / 65535.0f;

    if(quad) {
      w[0] = (1.0f - s) * (1.0f - t);
      w[1] = s * (1.0f - t);
      w[2] = (1.0f - s) * t;
      w[3] = s * t;
    } else {
      if(s + t > 1.0f) {
        t = 1.0f - s;
      }

      w[0] = (1.0f - s) - t;
      w[1] = s;
      w[2] = t;
      w[3] = 0.0f;
    }
  }

  /** I(x) = ((w0 x0 + w1 x1) + w2 x2) [+ w3 x3], mỗi phép làm tròn f32. */
  static float interp(final float[] w, final int vc, final float x0, final float x1, final float x2, final float x3) {
    float acc = w[0] * x0;
    acc = acc + w[1] * x1;
    acc = acc + w[2] * x2;
    if(vc == 4) {
      acc = acc + w[3] * x3;
    }
    return acc;
  }
}
