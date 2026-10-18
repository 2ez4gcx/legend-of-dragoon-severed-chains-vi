package legend.scvi.remaster;

import legend.core.renderer.Texture;

import java.lang.reflect.Field;

import static legend.core.GameEngine.RENDERER;

/**
 * [sc-vi] Tải mức mip 1..n-1 của atlas lên GPU sau khi Texture.create đã tải mức 0 (LRM spec 1 §3.6.4): ngay sau create
 * gọi glActiveTexture(GL_TEXTURE0) (texture vừa tạo đang gắn ở đơn vị 0), glTexImage2D từng mức, BASE/MAX_LEVEL,
 * MIN_FILTER = NEAREST_MIPMAP_NEAREST, MAG_FILTER = NEAREST, WRAP = CLAMP_TO_EDGE.
 *
 * Bản cài chọn theo lớp của RENDERER.api(): GlesApi -&gt; AtlasUploadGles (GLES30), GlApi -&gt; AtlasUploadGl (GL11C/12C/13C);
 * nạp bằng tên lớp (phản chiếu) để lớp của binding không dùng không bao giờ được nạp. API khác (NoopApi trong bộ thử
 * không GL) -&gt; NONE: chỉ có mức 0, bộ lọc NEAREST mặc định của Texture.
 */
interface AtlasUpload {
  /** levels[k] = RGBA8 hàng đầu = v 0, cỡ w[k] × h[k]; levels[0] đã được tải bởi Texture.create. */
  void upload(Texture texture, byte[][] levels, int[] w, int[] h);

  AtlasUpload NONE = (texture, levels, w, h) -> { };

  static AtlasUpload forCurrentApi() {
    for(Class<?> c = RENDERER.api().getClass(); c != null; c = c.getSuperclass()) {
      final String impl = switch(c.getName()) {
        case "legend.core.renderer.opengles.GlesApi" -> "legend.scvi.remaster.AtlasUploadGles";
        case "legend.core.renderer.opengl.GlApi" -> "legend.scvi.remaster.AtlasUploadGl";
        default -> null;
      };

      if(impl != null) {
        try {
          return (AtlasUpload)Class.forName(impl).getDeclaredConstructor().newInstance();
        } catch(final ReflectiveOperationException e) {
          throw new IllegalStateException("cannot load " + impl, e);
        }
      }
    }

    return NONE;
  }

  /** Tên GL của GlTexture/GlesTexture (trường gói "id"), -1 nếu không đọc được. */
  static int textureId(final Texture texture) {
    try {
      final Field f = texture.getClass().getDeclaredField("id");
      f.setAccessible(true);
      return f.getInt(texture);
    } catch(final Throwable t) {
      return -1;
    }
  }
}
