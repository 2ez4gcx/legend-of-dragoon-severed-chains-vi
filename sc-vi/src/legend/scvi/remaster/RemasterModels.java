package legend.scvi.remaster;

import legend.core.gte.ModelPart10;
import legend.core.renderer.BufferUsage;
import legend.core.renderer.Mesh;
import legend.core.renderer.Obj;
import legend.core.renderer.Texture;
import legend.core.renderer.VertexOrder;
import legend.game.tmd.TmdObjLoader;
import legend.game.tmd.TmdObjTable1c;
import legend.game.types.Model124;

import static legend.core.GameEngine.RENDERER;

/**
 * [sc-vi] Điểm vào của mô hình HD (route B) — LRM spec 1 §4.1, §4.2, §5. Gọi từ bản ghi đè
 * legend.game.tmd.TmdObjLoader.fromModel (sc-vi/src): trước vòng lặp phần {@code RemasterModels.find(...)}, mỗi phần
 * {@code r.buildPart(i, part.tmd_08)}; null =&gt; đường gốc fromObjTable (byte y hệt retail).
 *
 * find đi đường gốc (trả null) khi: chế độ off / không có chỉ mục; tên không bắt đầu bằng "CombatantModel (",
 * "SobjModel (" hay "WmapEntityModel ("; khoá LRMK1 (tính &lt; 1 ms) không có trong chỉ mục (miss); file LRM sai bất kỳ điều
 * nào của §3.5.4 (fallback, log một lần mỗi khoá); mọi Throwable. Trúng: giải mã mọi phần (SrcFaces), tính LIVE a-c,
 * dựng sẵn mảng bộ VRAM của mọi phần mode 1 (lỗi dữ liệu =&gt; cả mô hình đường gốc), rồi nếu đồng thời chế độ full
 * (textures=hd), tw == th == 0, clutAnimations_a4 == null, variantCount &gt; 0: nạp atlas từng biến thể (AtlasCache; PNG lỗi
 * =&gt; biến thể đó không có bộ ATLAS) và dựng mảng bộ ATLAS. buildPart chỉ còn tạo lưới GL (makeMesh + 7 thuộc tính như
 * createMesh); lỗi GL =&gt; phần đó đường gốc. Không bao giờ sửa dữ liệu TmdObjTable1c.
 */
public final class RemasterModels {
  private RemasterModels() { }

  private static final String[] PREFIXES = {"CombatantModel (", "SobjModel (", "WmapEntityModel ("};

  /** Mô hình của lần find trước (để chốt "đã dựng xong" nếu vòng lặp phần bị ngắt giữa chừng). */
  private static RemasterModel previous;

  /** Gọi bởi RemasterConfig khi đọc lại cấu hình (engine state đổi). */
  static synchronized void onConfigReload(final RemasterConfig config) {
    RemasterLog.reset(config.log);
    LrmFile.clearCache();
    if(previous != null) {
      previous.state.finishBuilding();
      previous = null;
    }
    AtlasCache.sweep();
  }

  /** Không bao giờ ném: lỗi bất kỳ =&gt; null (đường gốc). */
  public static RemasterModel find(final String name, final Model124 model, final int textureWidth, final int textureHeight) {
    try {
      return find0(name, model, textureWidth, textureHeight);
    } catch(final Throwable t) {
      try {
        RemasterLog.warn("%s fallback(%s) variant=vram", name, RemasterLog.reason(t));
      } catch(final Throwable ignored) {
        // không gì cả
      }
      return null;
    }
  }

  private static synchronized RemasterModel find0(final String name, final Model124 model, final int tw, final int th) {
    final RemasterConfig config = RemasterConfig.current();
    if(!config.active() || name == null || !allowed(name)) {
      return null;
    }

    if(previous != null) {
      previous.state.finishBuilding();
      previous = null;
    }

    final ModelPart10[] modelParts = model.modelParts_00;
    final int partCount = modelParts.length;
    if(partCount == 0) {
      return null;
    }

    // §3.1 khoá
    final TmdObjTable1c[] tables = new TmdObjTable1c[partCount];
    final byte[][] partKeys = new byte[partCount][];
    final int[] srcFaceCounts = new int[partCount];
    final int[] nVerts = new int[partCount];
    int textured = 0;
    for(int i = 0; i < partCount; i++) {
      tables[i] = modelParts[i].tmd_08;
      partKeys[i] = GeometryKey.partKey(tables[i]);
      srcFaceCounts[i] = GeometryKey.packetCount(tables[i]);
      nVerts[i] = tables[i].vert_top_00.length;
      textured += GeometryKey.texturedCount(tables[i]);
    }

    final byte[] modelKey = GeometryKey.modelKey(partKeys);
    final String key = RemasterLog.hex(modelKey);

    if(!config.index.contains(key)) {
      RemasterLog.miss(name, key);
      return null;
    }

    // §3.5.4
    final LrmFile lrm;
    try {
      lrm = LrmFile.load(key, new LrmFile.Runtime(modelKey, partKeys, srcFaceCounts, nVerts, textured, GeometryKey.texturedQuads(tables, textured)));
    } catch(final LrmFile.Invalid e) {
      RemasterLog.fallback(name, key, RemasterLog.reason(e)); // reason(): không để "(" ")" của thông điệp làm vỡ "fallback(...)"
      return null;
    }

    try {
      return build(name, key, model, tables, lrm, config, tw, th, textured);
    } catch(final Throwable t) {
      RemasterLog.fallback(name, key, RemasterLog.reason(t));
      return null;
    }
  }

  private static boolean allowed(final String name) {
    for(final String p : PREFIXES) {
      if(name.startsWith(p)) {
        return true;
      }
    }
    return false;
  }

  private static RemasterModel build(final String name, final String key, final Model124 model, final TmdObjTable1c[] tables, final LrmFile lrm, final RemasterConfig config, final int tw, final int th, final int texturedCount) {
    final int partCount = tables.length;
    if(lrm.parts.length != partCount) { // §3.5.4 mục 4: tự kiểm trước khi đánh chỉ số theo phần
      throw new IllegalStateException("partCount mismatch");
    }

    final SrcFaces[] faces = new SrcFaces[partCount];
    final int[] texBase = new int[partCount];
    int g = 0;
    boolean anyMode1 = false;
    for(int i = 0; i < partCount; i++) {
      faces[i] = SrcFaces.decode(tables[i]);
      if(faces[i].count != lrm.parts[i].srcFaceCount) {
        throw new IllegalStateException("srcFaceCount mismatch part " + i);
      }
      texBase[i] = g;
      g += faces[i].texturedCount;
      anyMode1 |= lrm.parts[i].mode == 1;
    }

    if(g != texturedCount) {
      throw new IllegalStateException("texturedFaceCount mismatch");
    }

    if(!anyMode1) {
      RemasterLog.hit(name, key, -1, "no mode-1 part, retail meshes");
      return null;
    }

    // bộ VRAM (luôn có)
    final RemasterBuilder.PartSets[] sets = new RemasterBuilder.PartSets[partCount];
    final RemasterBuilder.MeshData[][] vram = new RemasterBuilder.MeshData[partCount][];
    for(int i = 0; i < partCount; i++) {
      if(lrm.parts[i].mode == 1) {
        vram[i] = RemasterBuilder.buildVram(faces[i], lrm.parts[i], tw, th);
      }
    }

    final FaceVerify verify = new FaceVerify(faces);
    final boolean[] liveModel = verify.liveModel(model);
    final boolean verbose = RemasterLog.verbose();
    final int variantCount = lrm.variants.length;

    // §4.2: điều kiện dựng bộ ATLAS
    String noAtlas = null;
    if(config.mode != RemasterConfig.Mode.FULL) {
      noAtlas = "geometry mode";
    } else if(tw != 0 || th != 0) {
      noAtlas = "texture override";
    } else if(model.clutAnimations_a4 != null) {
      noAtlas = "clut animation";
    } else if(variantCount == 0) {
      noAtlas = "no variants";
    }

    // trạng thái chung tạo trước để làm chủ sở hữu atlas; mảng atlas / stored điền ngay sau, rồi state.init()
    final Texture[] atlas = new Texture[variantCount];
    final int[][] stored = new int[variantCount][];
    final RemasterMeshObj.ModelState state = new RemasterMeshObj.ModelState(name, key, verify, liveModel, stored, atlas, verbose, FaceVerify.GPU_VRAM);

    if(noAtlas == null) {
      final StringBuilder errors = new StringBuilder();
      int loaded = 0;

      try {
        for(int v = 0; v < variantCount; v++) {
          final LrmFile.Variant variant = lrm.variants[v];
          try {
            atlas[v] = AtlasCache.acquire(variant.pngSha1, variant.w, variant.h, state);
            stored[v] = variant.faceHash;
            loaded++;
          } catch(final LrmFile.Invalid e) {
            if(!errors.isEmpty()) {
              errors.append("; ");
            }
            errors.append("variant ").append(v).append(": ").append(e.getMessage());
          }
        }

        if(loaded == 0) {
          noAtlas = "atlas unavailable: " + errors;
        } else if(!errors.isEmpty()) {
          RemasterLog.warn("%s key=%s %s", name, key, errors.toString().replace('(', '[').replace(')', ']'));
        }

        // bộ ATLAS từng biến thể dùng được; LIVE của biến thể = LIVE a-c của mô hình ∪ mặt có faceHash 0 (§3.4 d)
        if(noAtlas == null) {
          final boolean[][] liveByVariant = new boolean[variantCount][];
          for(int v = 0; v < variantCount; v++) {
            if(atlas[v] != null) {
              liveByVariant[v] = liveModel.clone();
              final int[] fh = lrm.variants[v].faceHash;
              for(int k = 0; k < fh.length; k++) {
                liveByVariant[v][k] |= fh[k] == 0;
              }
            }
          }

          for(int i = 0; i < partCount; i++) {
            if(vram[i] == null) {
              continue;
            }

            final RemasterBuilder.MeshData[][] atlasSets = new RemasterBuilder.MeshData[variantCount][];
            for(int v = 0; v < variantCount; v++) {
              if(atlas[v] != null) {
                atlasSets[v] = RemasterBuilder.buildAtlas(vram[i], faces[i], lrm.parts[i], texBase[i], liveByVariant[v], lrm.variants[v].atlasUv);
              }
            }

            sets[i] = new RemasterBuilder.PartSets(vram[i], atlasSets, faces[i].backfaceCulling);
          }
        }
      } catch(final Throwable t) {
        AtlasCache.release(state);
        throw t;
      }
    }

    if(noAtlas != null) {
      // không có bộ ATLAS: chỉ bộ VRAM
      AtlasCache.release(state);
      java.util.Arrays.fill(atlas, null);
      java.util.Arrays.fill(stored, null);
      for(int i = 0; i < partCount; i++) {
        sets[i] = vram[i] != null ? new RemasterBuilder.PartSets(vram[i], null, faces[i].backfaceCulling) : null;
      }
      RemasterLog.hit(name, key, -1, noAtlas);
    } else if(verbose) {
      RemasterLog.info("%s key=%s hit variant=pending (%d variant(s), %d live face(s))", name, key, variantCount, count(liveModel));
    }

    state.init();
    final RemasterModel result = new RemasterModel(name, key, tables, sets, state);
    previous = result;
    return result;
  }

  private static int count(final boolean[] flags) {
    int n = 0;
    for(final boolean f : flags) {
      if(f) {
        n++;
      }
    }
    return n;
  }

  /** Kết quả find: tạo Obj cho từng phần (TmdObjLoader gọi buildPart(i, ...) cho mọi i theo thứ tự). */
  public static final class RemasterModel {
    private final String name;
    private final String key;
    private final TmdObjTable1c[] tables;
    private final RemasterBuilder.PartSets[] sets;
    final RemasterMeshObj.ModelState state;

    RemasterModel(final String name, final String key, final TmdObjTable1c[] tables, final RemasterBuilder.PartSets[] sets, final RemasterMeshObj.ModelState state) {
      this.name = name;
      this.key = key;
      this.tables = tables;
      this.sets = sets;
      this.state = state;
    }

    /** Obj remaster của phần i, hoặc null (mode 0, lỗi) =&gt; TmdObjLoader dùng đường gốc. Không bao giờ ném. */
    public Obj buildPart(final int i, final TmdObjTable1c table) {
      Mesh[] vram = null;
      Mesh[][] atlas = null;
      try {
        if(i < 0 || i >= this.sets.length || this.sets[i] == null || table != this.tables[i]) {
          return null;
        }

        final RemasterBuilder.PartSets set = this.sets[i];
        this.sets[i] = null;
        final String partName = this.name + " part " + i;

        vram = new Mesh[set.vram.length];
        for(int m = 0; m < vram.length; m++) {
          vram[m] = createMesh(partName + " (" + set.vram[m].className() + ')', set.vram[m]);
        }

        if(set.atlas != null) {
          atlas = new Mesh[set.atlas.length][];
          for(int v = 0; v < set.atlas.length; v++) {
            if(set.atlas[v] == null) {
              continue;
            }

            atlas[v] = new Mesh[set.atlas[v].length];
            for(int m = 0; m < atlas[v].length; m++) {
              atlas[v][m] = createMesh(partName + " (" + set.atlas[v][m].className() + ") atlas " + v, set.atlas[v][m]);
            }
          }
        }

        final RemasterMeshObj obj = new RemasterMeshObj(partName, vram, set.backfaceCulling, atlas, this.state);
        this.state.addPart(obj);
        return obj;
      } catch(final Throwable t) {
        // dọn và ghi log cũng không được ném ra khỏi điểm vào (null => TmdObjLoader đi đường gốc)
        try {
          deleteAll(vram);
          if(atlas != null) {
            for(final Mesh[] set : atlas) {
              deleteAll(set);
            }
          }
          RemasterLog.warn("%s key=%s part %d fallback(%s)", this.name, this.key, i, RemasterLog.reason(t));
        } catch(final Throwable ignored) {
          // bỏ qua
        }
        return null;
      } finally {
        if(i >= this.sets.length - 1) {
          try {
            this.state.finishBuilding();
          } catch(final Throwable ignored) {
            // bỏ qua
          }
        }
      }
    }

    private static void deleteAll(final Mesh[] meshes) {
      if(meshes == null) {
        return;
      }

      for(final Mesh mesh : meshes) {
        if(mesh != null) {
          try {
            mesh.delete();
          } catch(final Throwable ignored) {
            // bỏ qua
          }
        }
      }
    }
  }

  /** Như TmdObjLoader.createMesh (affcef0 :329-359): TRIANGLES_ADJACENCY, STATIC, 7 thuộc tính. */
  static Mesh createMesh(final String name, final RemasterBuilder.MeshData data) {
    final Mesh mesh = RENDERER.api().makeMesh(name, VertexOrder.TRIANGLES_ADJACENCY, data.vertices, data.indices, data.textured, data.translucent, data.translucency, BufferUsage.STATIC);

    mesh.attribute(0, 0L, TmdObjLoader.POS_SIZE, TmdObjLoader.VERTEX_SIZE);

    int meshIndex = 1;
    int meshOffset = TmdObjLoader.POS_SIZE;

    mesh.attribute(meshIndex, meshOffset, TmdObjLoader.NORM_SIZE, TmdObjLoader.VERTEX_SIZE);
    meshIndex++;
    meshOffset += TmdObjLoader.NORM_SIZE;

    mesh.attribute(meshIndex, meshOffset, TmdObjLoader.UV_SIZE, TmdObjLoader.VERTEX_SIZE);
    meshIndex++;
    meshOffset += TmdObjLoader.UV_SIZE;

    mesh.attribute(meshIndex, meshOffset, TmdObjLoader.TPAGE_SIZE, TmdObjLoader.VERTEX_SIZE);
    meshIndex++;
    meshOffset += TmdObjLoader.TPAGE_SIZE;

    mesh.attribute(meshIndex, meshOffset, TmdObjLoader.CLUT_SIZE, TmdObjLoader.VERTEX_SIZE);
    meshIndex++;
    meshOffset += TmdObjLoader.CLUT_SIZE;

    mesh.attribute(meshIndex, meshOffset, TmdObjLoader.COLOUR_SIZE, TmdObjLoader.VERTEX_SIZE);
    meshIndex++;
    meshOffset += TmdObjLoader.COLOUR_SIZE;

    mesh.attribute(meshIndex, meshOffset, TmdObjLoader.FLAGS_SIZE, TmdObjLoader.VERTEX_SIZE);
    return mesh;
  }
}
