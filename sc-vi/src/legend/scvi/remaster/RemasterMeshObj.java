package legend.scvi.remaster;

import legend.core.renderer.Mesh;
import legend.core.renderer.Texture;
import legend.core.renderer.Translucency;
import legend.game.tmd.TmdMeshObj;

import javax.annotation.Nullable;
import java.util.ArrayList;
import java.util.List;

/**
 * [sc-vi] Obj của một phần mode 1 (LRM spec 1 §4.2, §4.4): bộ VRAM = super.meshes (lớp/thứ tự như lưới retail nên
 * shouldRender/hasTranslucency của MeshObj vẫn đúng), thêm một bộ ATLAS cho mỗi biến thể dùng được, và trạng thái chung
 * của cả mô hình (ModelState, mọi phần cùng một đối tượng).
 *
 * render(): state.tick() (xác minh theo lịch), rồi ATLAS(v) -&gt; atlas.use(0) + atlasSets[v][layer]; mọi trạng thái khác -&gt;
 * bộ VRAM. Không tạo đối tượng GL và không mesh.update lúc vẽ (D5). performDelete xoá mọi bộ lưới và trả tham chiếu atlas.
 */
public final class RemasterMeshObj extends TmdMeshObj {
  /** [biến thể][lớp]; null = biến thể không dùng được. */
  private final Mesh[][] atlasSets;
  private final ModelState state;

  RemasterMeshObj(final String name, final Mesh[] vram, final boolean backfaceCulling, final Mesh[][] atlasSets, final ModelState state) {
    super(name, vram, backfaceCulling);
    this.atlasSets = atlasSets;
    this.state = state;
  }

  /** Bộ ATLAS của biến thể v (null nếu không có) — cho bộ thử. */
  public Mesh[] atlasMeshes(final int variant) {
    return this.atlasSets != null && variant >= 0 && variant < this.atlasSets.length ? this.atlasSets[variant] : null;
  }

  /** Biến thể đang vẽ (-1 = bộ VRAM) — cho bộ thử / gỡ lỗi. */
  public int currentVariant() {
    return this.state.variant;
  }

  /** Chạy xác minh ngay (bỏ qua lịch) — cho bộ thử. Trả biến thể sau khi xác minh (-1 = VRAM). */
  public int verifyNow() {
    this.state.nextCheck = System.nanoTime();
    return this.state.tick();
  }

  /** SHA-1 véc-tơ FaceHash runtime hiện tại (§3.3.6, mặt bpp 3 = 0) — cho bộ thử / so với Python. */
  public String faceHashVectorSha1() {
    return FaceVerify.vectorSha1(this.state.verify.vector(FaceVerify.GPU_VRAM));
  }

  boolean isMarkedDeleted() {
    return this.deleted;
  }

  private Mesh atlasMesh(final int layer) {
    final int v = this.state.tick();
    if(v >= 0 && this.atlasSets != null && v < this.atlasSets.length && this.atlasSets[v] != null) {
      return this.atlasSets[v][layer];
    }
    return null;
  }

  @Override
  public void render(final int layer, final int startVertex, final int vertexCount) {
    final Mesh atlas = this.atlasMesh(layer);
    if(atlas == null) {
      super.render(layer, startVertex, vertexCount);
      return;
    }

    this.state.atlasTexture().use(0);
    atlas.draw(startVertex, vertexCount);
  }

  @Override
  public void render(@Nullable final Translucency translucency, final int layer, final int startVertex, final int vertexCount) {
    final Mesh atlas = this.atlasMesh(layer);
    if(atlas == null) {
      super.render(translucency, layer, startVertex, vertexCount);
      return;
    }

    // như MeshObj.render(Translucency, ...)
    if(!atlas.translucent() && translucency == null || atlas.translucent() && atlas.translucencyMode() == translucency) {
      this.state.atlasTexture().use(0);
      atlas.draw(startVertex, vertexCount);
    }
  }

  @Override
  protected void performDelete() {
    super.performDelete();

    if(this.atlasSets != null) {
      for(final Mesh[] set : this.atlasSets) {
        if(set != null) {
          for(final Mesh mesh : set) {
            mesh.delete();
          }
        }
      }
    }

    this.state.partDeleted();
  }

  /**
   * Trạng thái chung của một lần nạp mô hình (§4.4): PENDING (vẽ VRAM) -&gt; ATLAS(v) khi mọi mặt có texture không LIVE khớp
   * faceHash của biến thể v (thử 0, 1, ...; bỏ mặt LIVE a-c và mặt có faceHash 0; dừng ở mặt sai đầu tiên). PENDING kiểm
   * khoảng mỗi 4 khung (66 ms) trong 2 s rồi mỗi 1 s; ATLAS kiểm lại toàn bộ mỗi 1 s, sai -&gt; PENDING. Chống nhấp nháy: sau 3
   * lần ATLAS -&gt; PENDING thì khoá ở VRAM (log một lần). Không có bộ ATLAS -&gt; luôn VRAM (chỉ có thể in véc-tơ FaceHash khi
   * nhật ký chi tiết).
   */
  static final class ModelState {
    static final long FAST_INTERVAL = 66_000_000L;
    static final long FAST_WINDOW = 2_000_000_000L;
    static final long SLOW_INTERVAL = 1_000_000_000L;
    static final int MAX_TRIPS = 3;

    final String name;
    final String key;
    final FaceVerify verify;
    final boolean[] liveModel;
    /** [biến thể][g]; dòng null = biến thể không dùng được (không có atlas). */
    final int[][] storedHash;
    final Texture[] atlas;
    final boolean verbose;
    final FaceVerify.Vram vram;
    private boolean hasAtlas;
    private boolean dumpOnly;

    int variant = -1;
    long nextCheck;
    private long pendingSince;
    private boolean announced;
    private boolean everAtlas;
    private boolean locked;
    private int trips;
    private boolean firstCheckDone;
    private String lastDump;

    private final List<RemasterMeshObj> parts = new ArrayList<>();
    private boolean buildingDone;
    private int deletedParts;
    private boolean released;

    ModelState(final String name, final String key, final FaceVerify verify, final boolean[] liveModel, final int[][] storedHash, final Texture[] atlas, final boolean verbose, final FaceVerify.Vram vram) {
      this.name = name;
      this.key = key;
      this.verify = verify;
      this.liveModel = liveModel;
      this.storedHash = storedHash;
      this.atlas = atlas;
      this.verbose = verbose;
      this.vram = vram;
      this.locked = true; // tới khi init()
    }

    /** Gọi sau khi mảng atlas / storedHash đã điền xong (atlas[v] != null &lt;=&gt; storedHash[v] != null). */
    void init() {
      boolean any = false;
      for(int v = 0; v < this.atlas.length; v++) {
        any |= this.atlas[v] != null && this.storedHash[v] != null;
      }

      this.hasAtlas = any;
      this.dumpOnly = !any && this.verbose;
      this.locked = false;

      final long now = System.nanoTime();
      this.pendingSince = now;
      this.nextCheck = this.dumpOnly ? now + FAST_WINDOW : now;
    }

    Texture atlasTexture() {
      return this.atlas[this.variant];
    }

    // ---------------------------------------------------------------- vòng đời

    void addPart(final RemasterMeshObj obj) {
      this.parts.add(obj);
    }

    void finishBuilding() {
      if(this.buildingDone) {
        return;
      }

      this.buildingDone = true;
      if(this.parts.isEmpty() || this.deletedParts >= this.parts.size()) {
        this.release();
      }
    }

    void partDeleted() {
      this.deletedParts++;
      if(this.buildingDone && this.deletedParts >= this.parts.size()) {
        this.release();
      }
    }

    /** Mọi phần đã bị đánh dấu xoá (kể cả bị Obj.clearObjList bỏ mà không gọi performDelete). */
    boolean isGone() {
      if(this.released) {
        return true;
      }

      if(!this.buildingDone) {
        return false;
      }

      for(final RemasterMeshObj p : this.parts) {
        if(!p.isMarkedDeleted()) {
          return false;
        }
      }
      return true;
    }

    private void release() {
      if(!this.released) {
        this.released = true;
        AtlasCache.release(this);
      }
    }

    /**
     * AtlasCache.sweep đã bỏ chủ sở hữu này (mọi phần bị đánh dấu xoá, kể cả rò): từ giờ chỉ vẽ bộ VRAM để một Obj rò lỡ
     * còn được vẽ cũng không dùng texture atlas đã delete().
     */
    void markReleased() {
      this.released = true;
      this.variant = -1;
    }

    // ---------------------------------------------------------------- xác minh

    /** Gọi trong render(): chạy xác minh khi tới lịch; trả biến thể cần vẽ (-1 = VRAM). Không bao giờ ném. */
    int tick() {
      if(this.locked || this.released || !this.hasAtlas && !this.dumpOnly) {
        return this.locked || this.released ? -1 : this.variant;
      }

      final long now = System.nanoTime();
      if(now - this.nextCheck < 0) {
        return this.variant;
      }

      try {
        this.check(now);
      } catch(final Throwable t) {
        this.variant = -1;
        this.locked = true;
        RemasterLog.warn("%s key=%s verify error (%s), locked to vram", this.name, this.key, RemasterLog.reason(t));
      }

      return this.variant;
    }

    private void check(final long now) {
      if(this.dumpOnly) {
        // không có bộ ATLAS: chỉ in véc-tơ FaceHash một lần (nhật ký chi tiết) sau cửa sổ 2 s
        this.dump(this.verify.vector(this.vram));
        this.locked = true;
        return;
      }

      final int[] runtime = new int[this.verify.count];
      final boolean[] computed = new boolean[this.verify.count];

      if(this.variant < 0) {
        int match = -1;
        for(int v = 0; v < this.storedHash.length && match < 0; v++) {
          if(this.storedHash[v] != null && this.firstMismatch(v, runtime, computed, this.verbose && !this.firstCheckDone) < 0) {
            match = v;
          }
        }

        if(this.verbose && !this.firstCheckDone) {
          this.dump(this.fill(runtime, computed));
        }
        this.firstCheckDone = true;

        if(match >= 0) {
          this.variant = match;
          if(!this.everAtlas || this.verbose) {
            RemasterLog.hit(this.name, this.key, match, this.everAtlas ? "re-verified" : null);
          }
          this.everAtlas = true;
          this.announced = true;
          if(this.verbose) {
            this.dump(this.fill(runtime, computed));
          }
          this.nextCheck = now + SLOW_INTERVAL;
          return;
        }

        final boolean fast = now - this.pendingSince < FAST_WINDOW;
        if(!fast && !this.announced) {
          this.announced = true;
          RemasterLog.hit(this.name, this.key, -1, "texture not verified, retail texels");
          if(this.verbose) {
            for(int v = 0; v < this.storedHash.length; v++) {
              if(this.storedHash[v] != null) {
                this.firstMismatch(v, runtime, computed, true);
              }
            }
            this.dump(this.fill(runtime, computed));
          }
        }

        this.nextCheck = now + (fast ? FAST_INTERVAL : SLOW_INTERVAL);
        return;
      }

      // ATLAS(v): kiểm lại toàn bộ
      if(this.firstMismatch(this.variant, runtime, computed, this.verbose) >= 0) {
        this.trips++;
        RemasterLog.warn("%s key=%s guard: variant %d no longer matches VRAM, back to vram (trip %d)", this.name, this.key, this.variant, this.trips);
        this.variant = -1;
        this.pendingSince = now;
        this.announced = true;

        if(this.trips >= MAX_TRIPS) {
          this.locked = true;
          RemasterLog.warn("%s key=%s guard tripped %d times, locked to vram", this.name, this.key, this.trips);
          return;
        }

        this.nextCheck = now + FAST_INTERVAL;
        return;
      }

      this.nextCheck = now + SLOW_INTERVAL;
    }

    /** Mặt sai đầu tiên của biến thể v (-1 = khớp hết). Hash runtime tính lười, dùng lại trong một lần kiểm. */
    private int firstMismatch(final int v, final int[] runtime, final boolean[] computed, final boolean log) {
      final int[] stored = this.storedHash[v];
      for(int g = 0; g < this.verify.count; g++) {
        if(this.liveModel[g] || stored[g] == 0) {
          continue;
        }

        if(!computed[g]) {
          runtime[g] = this.verify.hash(g, this.vram);
          computed[g] = true;
        }

        if(runtime[g] != stored[g]) {
          if(log) {
            RemasterLog.info("%s key=%s mismatch variant=%d face=%d runtime=%s expected=%s", this.name, this.key, v, g, RemasterLog.hex8(runtime[g]), RemasterLog.hex8(stored[g]));
          }
          return g;
        }
      }

      return -1;
    }

    private int[] fill(final int[] runtime, final boolean[] computed) {
      for(int g = 0; g < this.verify.count; g++) {
        if(!computed[g]) {
          runtime[g] = this.verify.hash(g, this.vram);
          computed[g] = true;
        }
      }
      return runtime;
    }

    /** "facehash n=N sha1=..." (chỉ khi khác lần in trước). */
    private void dump(final int[] vector) {
      final String sha = FaceVerify.vectorSha1(vector);
      if(!sha.equals(this.lastDump)) {
        this.lastDump = sha;
        RemasterLog.info("%s key=%s facehash n=%d sha1=%s", this.name, this.key, vector.length, sha);
      }
    }
  }
}
