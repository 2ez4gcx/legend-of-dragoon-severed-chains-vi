package scvi.remastercheck;

import legend.core.renderer.BufferUsage;
import legend.core.renderer.Mesh;
import legend.core.renderer.RenderEngine;
import legend.core.renderer.Texture;
import legend.core.renderer.TextureDataFormat;
import legend.core.renderer.TextureDataType;
import legend.core.renderer.TextureInternalFormat;
import legend.core.renderer.Translucency;
import legend.core.renderer.VertexOrder;
import legend.core.renderer.noop.NoopApi;
import legend.core.renderer.opengl.GlApi;

import javax.annotation.Nullable;
import java.lang.reflect.Field;
import java.nio.Buffer;
import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.List;

/**
 * RenderApi không cần cửa sổ game (NoopApi của SC) ghi lại mọi thứ TmdObjLoader (gốc / sc-vi / MockRuntime) tạo ra:
 * <ul>
 *   <li>lưới: tên, kiểu đỉnh, overload + BufferUsage, bản sao mảng đỉnh và chỉ số, textured/translucent/translucency,
 *       các lệnh {@code attribute(...)}, số lần {@code update()}, {@code delete()}, lệnh vẽ ({@code draw});</li>
 *   <li>texture: tên, kích thước, định dạng; có ngữ cảnh GL (GlContext) thì tạo GlTexture THẬT qua GlApi để runtime tải các
 *       mức mip lên đúng texture (đọc lại được bằng glGetTexImage), không có thì NoopTexture;</li>
 *   <li>vi phạm D5: lưới / texture tạo ra trong lúc vẽ ({@link #renderPhase} = true).</li>
 * </ul>
 * RENDERER được tạo bằng constructor thật của RenderEngine (thuần Java), rồi gán trường riêng "api" bằng phản chiếu thay cho
 * RenderEngine.init() (cần cửa sổ). Khi tạo được ngữ cảnh GL ẩn, api đổi thành {@link Gl} (lớp con của GlApi thật, cùng cách
 * ghi lại) để runtime thấy đúng kiểu api của game PC. Dùng chung một luồng (luồng main của JVM thử).
 */
public class CaptureApi extends NoopApi {
  /** Một lưới đã ghi lại. Trả về cho người gọi chính đối tượng này (implements Mesh) để biết lưới nào được vẽ / xoá. */
  public static final class RecMesh implements Mesh {
    public final int id;
    public final String name;
    public final VertexOrder order;
    public final String overload;
    public final float[] vertices;
    public final int[] indices;
    public final boolean textured;
    public final boolean translucent;
    public final Translucency translucency;
    public final List<long[]> attributes = new ArrayList<>();
    public int draws;
    public int updates;
    public boolean deleted;

    RecMesh(final int id, final String name, final VertexOrder order, final String overload, final float[] vertices, final int[] indices,
            final boolean textured, final boolean translucent, @Nullable final Translucency translucency) {
      this.id = id;
      this.name = name;
      this.order = order;
      this.overload = overload;
      this.vertices = vertices;
      this.indices = indices;
      this.textured = textured;
      this.translucent = translucent;
      this.translucency = translucency;
    }

    @Override public void update() { this.updates++; }
    @Override public void delete() { this.deleted = true; }
    @Override public void attribute(final int index, final long offset, final int size, final int stride) { this.attributes.add(new long[] {index, offset, size, stride}); }
    @Override public void draw() { this.draws++; DRAWS.add(this); }
    @Override public void draw(final int start, final int count) { this.draws++; DRAWS.add(this); }
    @Override public float[] vertices() { return this.vertices; }
    @Override public boolean textured() { return this.textured; }
    @Override public boolean translucent() { return this.translucent; }
    @Override public Translucency translucencyMode() { return this.translucency; }
  }

  /** Texture đã tạo (NoopTexture hoặc GlTexture thật). */
  public record RecTexture(Texture texture, String name, int w, int h, TextureInternalFormat internalFormat, boolean duringRender) { }

  public static final List<RecMesh> MESHES = new ArrayList<>();
  public static final List<RecMesh> DRAWS = new ArrayList<>();
  public static final List<RecTexture> TEXTURES = new ArrayList<>();
  /** Lưới / texture tạo ra khi renderPhase = true (vi phạm D5). */
  public static int createdDuringRender;
  public static boolean renderPhase;
  private static int nextId;
  @Nullable private static GlApi glApi;

  public static RenderEngine renderer() {
    final RenderEngine engine = new RenderEngine();
    setApi(engine, new CaptureApi());
    return engine;
  }

  private static void setApi(final RenderEngine engine, final legend.core.renderer.RenderApi a) {
    try {
      final Field api = RenderEngine.class.getDeclaredField("api");
      api.setAccessible(true);
      api.set(engine, a);
    } catch(final ReflectiveOperationException e) {
      throw new RuntimeException("khong tao duoc RenderEngine gia", e);
    }
  }

  /**
   * Gọi sau khi GlContext.create() thành công: texture tạo sau đó là GlTexture thật, và RENDERER.api() đổi thành {@link Gl}
   * (lớp con của GlApi THẬT) để runtime đi đúng nhánh OpenGL như trong game PC (vd chọn AtlasUploadGl theo kiểu api,
   * §3.6.4). Lưới vẫn chỉ được ghi lại (không tạo VAO), texture là GlTexture thật.
   */
  public static void useGlTextures() {
    glApi = new GlApi();
    setApi(legend.core.GameEngine.RENDERER, new Gl());
  }

  /** Tên lớp của RENDERER.api() hiện tại (để ghi vào log JVM con). */
  public static String apiName() {
    return legend.core.GameEngine.RENDERER.api().getClass().getName();
  }

  /**
   * RenderApi khi có ngữ cảnh GL: kế thừa GlApi thật của SC (instanceof GlApi = true, như game PC) nhưng makeMesh chỉ ghi lại
   * như {@link CaptureApi}; makeTexture tạo GlTexture thật rồi ghi lại. Không gọi init() (debugEnabled = false, không đọc CONFIG).
   */
  public static final class Gl extends GlApi {
    @Override
    public Mesh makeMesh(final String name, final VertexOrder vertexOrder, final float[] vertexData, final int[] indices) {
      return record(name, vertexOrder, "indices", vertexData, indices, false, false, null);
    }

    @Override
    public Mesh makeMesh(final String name, final VertexOrder vertexOrder, final float[] vertexData, final int[] indices, final boolean textured, final boolean translucent, @Nullable final Translucency translucencyMode, final BufferUsage bufferUsage) {
      return record(name, vertexOrder, "indices+flags:" + bufferUsage, vertexData, indices, textured, translucent, translucencyMode);
    }

    @Override
    public Mesh makeMesh(final String name, final VertexOrder vertexOrder, final float[] vertexData, final int vertexCount) {
      return record(name, vertexOrder, "count", vertexData, null, false, false, null);
    }

    @Override
    public Mesh makeMesh(final String name, final VertexOrder vertexOrder, final float[] vertexData, final int vertexCount, final boolean textured, final boolean translucent, @Nullable final Translucency translucencyMode, final BufferUsage bufferUsage) {
      return record(name, vertexOrder, "count+flags:" + bufferUsage, vertexData, null, textured, translucent, translucencyMode);
    }

    @Override
    public Texture makeTexture(@Nullable final Buffer buffer, final String name, final int w, final int h, final TextureInternalFormat internalFormat, final TextureDataFormat dataFormat, final TextureDataType dataType, final boolean minFilter, final boolean magFilter, final boolean wrapS, final boolean wrapT) {
      return recordTexture(super.makeTexture(buffer, name, w, h, internalFormat, dataFormat, dataType, minFilter, magFilter, wrapS, wrapT), name, w, h, internalFormat);
    }
  }

  private static Texture recordTexture(final Texture t, final String name, final int w, final int h, final TextureInternalFormat internalFormat) {
    TEXTURES.add(new RecTexture(t, name, w, h, internalFormat, renderPhase));
    if(renderPhase) {
      createdDuringRender++;
    }
    return t;
  }

  public static boolean glTextures() {
    return glApi != null;
  }

  public static void reset() {
    MESHES.clear();
    DRAWS.clear();
    TEXTURES.clear();
    createdDuringRender = 0;
    renderPhase = false;
  }

  private static RecMesh record(final String name, final VertexOrder order, final String overload, final float[] vertexData, final int[] indices,
                                final boolean textured, final boolean translucent, @Nullable final Translucency translucency) {
    final RecMesh m = new RecMesh(nextId++, name, order, overload, vertexData.clone(), indices == null ? null : indices.clone(), textured, translucent, translucency);
    MESHES.add(m);
    if(renderPhase) {
      createdDuringRender++;
    }
    return m;
  }

  @Override
  public Mesh makeMesh(final String name, final VertexOrder vertexOrder, final float[] vertexData, final int[] indices) {
    return record(name, vertexOrder, "indices", vertexData, indices, false, false, null);
  }

  @Override
  public Mesh makeMesh(final String name, final VertexOrder vertexOrder, final float[] vertexData, final int[] indices, final boolean textured, final boolean translucent, @Nullable final Translucency translucencyMode, final BufferUsage bufferUsage) {
    return record(name, vertexOrder, "indices+flags:" + bufferUsage, vertexData, indices, textured, translucent, translucencyMode);
  }

  @Override
  public Mesh makeMesh(final String name, final VertexOrder vertexOrder, final float[] vertexData, final int vertexCount) {
    return record(name, vertexOrder, "count", vertexData, null, false, false, null);
  }

  @Override
  public Mesh makeMesh(final String name, final VertexOrder vertexOrder, final float[] vertexData, final int vertexCount, final boolean textured, final boolean translucent, @Nullable final Translucency translucencyMode, final BufferUsage bufferUsage) {
    return record(name, vertexOrder, "count+flags:" + bufferUsage, vertexData, null, textured, translucent, translucencyMode);
  }

  @Override
  public Texture makeTexture(@Nullable final Buffer buffer, final String name, final int w, final int h, final TextureInternalFormat internalFormat, final TextureDataFormat dataFormat, final TextureDataType dataType, final boolean minFilter, final boolean magFilter, final boolean wrapS, final boolean wrapT) {
    return recordTexture(glApi != null
      ? glApi.makeTexture(buffer, name, w, h, internalFormat, dataFormat, dataType, minFilter, magFilter, wrapS, wrapT)
      : super.makeTexture(buffer, name, w, h, internalFormat, dataFormat, dataType, minFilter, magFilter, wrapS, wrapT), name, w, h, internalFormat);
  }

  // ---------- trường riêng của Texture / GlTexture (đọc bằng phản chiếu) ----------

  static boolean textureDeleted(final Texture t) {
    try {
      final Field f = Texture.class.getDeclaredField("deleted");
      f.setAccessible(true);
      return f.getBoolean(t);
    } catch(final ReflectiveOperationException e) {
      throw new RuntimeException(e);
    }
  }

  /** id GL của GlTexture, -1 nếu không phải GlTexture. */
  static int glTextureId(final Texture t) {
    try {
      final Field f = t.getClass().getDeclaredField("id");
      f.setAccessible(true);
      return f.getInt(t);
    } catch(final ReflectiveOperationException e) {
      return -1;
    }
  }

  // ---------- ngữ cảnh OpenGL ẩn (SDL3, như SdlWindow của SC) ----------

  /**
   * Cửa sổ SDL ẩn + ngữ cảnh OpenGL 3.3 core trên luồng hiện tại. Cần cho chế độ FULL: runtime tải atlas bằng lệnh GL trực tiếp
   * (AtlasUploadGl), mà LWJGL gọi hàm GL khi không có ngữ cảnh thì JVM bị huỷ (FatalError), không bắt được bằng try/catch.
   */
  public static final class GlContext {
    private GlContext() { }

    private static boolean ok;

    public static boolean create() {
      if(ok) {
        return true;
      }
      try {
        if(!org.lwjgl.sdl.SDLInit.SDL_Init(org.lwjgl.sdl.SDLInit.SDL_INIT_VIDEO)) {
          System.out.println("GL: SDL_Init loi: " + org.lwjgl.sdl.SDLError.SDL_GetError());
          return false;
        }
        org.lwjgl.sdl.SDLVideo.SDL_GL_SetAttribute(org.lwjgl.sdl.SDLVideo.SDL_GL_CONTEXT_MAJOR_VERSION, 3);
        org.lwjgl.sdl.SDLVideo.SDL_GL_SetAttribute(org.lwjgl.sdl.SDLVideo.SDL_GL_CONTEXT_MINOR_VERSION, 3);
        org.lwjgl.sdl.SDLVideo.SDL_GL_SetAttribute(org.lwjgl.sdl.SDLVideo.SDL_GL_CONTEXT_PROFILE_MASK, org.lwjgl.sdl.SDLVideo.SDL_GL_CONTEXT_PROFILE_CORE);
        final long window = org.lwjgl.sdl.SDLVideo.SDL_CreateWindow("scvi-remastercheck", 16, 16, org.lwjgl.sdl.SDLVideo.SDL_WINDOW_OPENGL | org.lwjgl.sdl.SDLVideo.SDL_WINDOW_HIDDEN);
        if(window == 0) {
          System.out.println("GL: SDL_CreateWindow loi: " + org.lwjgl.sdl.SDLError.SDL_GetError());
          return false;
        }
        final long context = org.lwjgl.sdl.SDLVideo.SDL_GL_CreateContext(window);
        if(context == 0 || !org.lwjgl.sdl.SDLVideo.SDL_GL_MakeCurrent(window, context)) {
          System.out.println("GL: khong tao duoc ngu canh: " + org.lwjgl.sdl.SDLError.SDL_GetError());
          return false;
        }
        final org.lwjgl.opengl.GLCapabilities caps = org.lwjgl.opengl.GL.createCapabilities();
        if(!caps.OpenGL33) {
          System.out.println("GL: khong co OpenGL 3.3");
          return false;
        }
        ok = true;
        return true;
      } catch(final Throwable t) {
        System.out.println("GL: " + t);
        return false;
      }
    }

    public static boolean active() {
      return ok;
    }

    public static int error() {
      return ok ? org.lwjgl.opengl.GL11C.glGetError() : 0;
    }

    /** Đọc thông số một texture GL: {w0, h0, số mức có kích thước khác 0, MIN, MAG, WRAP_S, WRAP_T}. */
    public static int[] textureInfo(final int id) {
      org.lwjgl.opengl.GL11C.glBindTexture(org.lwjgl.opengl.GL11C.GL_TEXTURE_2D, id);
      int levels = 0;
      for(int level = 0; level < 16; level++) {
        if(org.lwjgl.opengl.GL11C.glGetTexLevelParameteri(org.lwjgl.opengl.GL11C.GL_TEXTURE_2D, level, org.lwjgl.opengl.GL11C.GL_TEXTURE_WIDTH) == 0) {
          break;
        }
        levels++;
      }
      return new int[] {
        org.lwjgl.opengl.GL11C.glGetTexLevelParameteri(org.lwjgl.opengl.GL11C.GL_TEXTURE_2D, 0, org.lwjgl.opengl.GL11C.GL_TEXTURE_WIDTH),
        org.lwjgl.opengl.GL11C.glGetTexLevelParameteri(org.lwjgl.opengl.GL11C.GL_TEXTURE_2D, 0, org.lwjgl.opengl.GL11C.GL_TEXTURE_HEIGHT),
        levels,
        org.lwjgl.opengl.GL11C.glGetTexParameteri(org.lwjgl.opengl.GL11C.GL_TEXTURE_2D, org.lwjgl.opengl.GL11C.GL_TEXTURE_MIN_FILTER),
        org.lwjgl.opengl.GL11C.glGetTexParameteri(org.lwjgl.opengl.GL11C.GL_TEXTURE_2D, org.lwjgl.opengl.GL11C.GL_TEXTURE_MAG_FILTER),
        org.lwjgl.opengl.GL11C.glGetTexParameteri(org.lwjgl.opengl.GL11C.GL_TEXTURE_2D, org.lwjgl.opengl.GL11C.GL_TEXTURE_WRAP_S),
        org.lwjgl.opengl.GL11C.glGetTexParameteri(org.lwjgl.opengl.GL11C.GL_TEXTURE_2D, org.lwjgl.opengl.GL11C.GL_TEXTURE_WRAP_T),
      };
    }

    /** RGBA8 của một mức (hàng đầu = v nhỏ nhất, như dữ liệu đã tải lên). */
    public static byte[] textureLevel(final int id, final int level) {
      org.lwjgl.opengl.GL11C.glBindTexture(org.lwjgl.opengl.GL11C.GL_TEXTURE_2D, id);
      final int w = org.lwjgl.opengl.GL11C.glGetTexLevelParameteri(org.lwjgl.opengl.GL11C.GL_TEXTURE_2D, level, org.lwjgl.opengl.GL11C.GL_TEXTURE_WIDTH);
      final int h = org.lwjgl.opengl.GL11C.glGetTexLevelParameteri(org.lwjgl.opengl.GL11C.GL_TEXTURE_2D, level, org.lwjgl.opengl.GL11C.GL_TEXTURE_HEIGHT);
      final ByteBuffer buf = org.lwjgl.BufferUtils.createByteBuffer(w * h * 4);
      org.lwjgl.opengl.GL11C.glPixelStorei(org.lwjgl.opengl.GL11C.GL_PACK_ALIGNMENT, 1);
      org.lwjgl.opengl.GL11C.glGetTexImage(org.lwjgl.opengl.GL11C.GL_TEXTURE_2D, level, org.lwjgl.opengl.GL11C.GL_RGBA, org.lwjgl.opengl.GL11C.GL_UNSIGNED_BYTE, buf);
      final byte[] out = new byte[w * h * 4];
      buf.get(out);
      return out;
    }
  }
}
