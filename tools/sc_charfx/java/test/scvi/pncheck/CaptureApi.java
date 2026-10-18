package scvi.pncheck;

import legend.core.renderer.BufferUsage;
import legend.core.renderer.Mesh;
import legend.core.renderer.RenderEngine;
import legend.core.renderer.Translucency;
import legend.core.renderer.VertexOrder;
import legend.core.renderer.noop.NoopApi;

import javax.annotation.Nullable;
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.List;

/**
 * RenderApi không cần GL (NoopApi của SC) ghi lại mọi lưới TmdObjLoader tạo: tên, kiểu đỉnh, bản sao mảng đỉnh và chỉ số,
 * textured/translucent/translucency. Dùng cho PnCheck (build.ps1 -Check); RENDERER được tạo bằng constructor thật của
 * RenderEngine (thuần Java), rồi gán trường riêng "api" bằng phản chiếu thay cho RenderEngine.init() (cần cửa sổ).
 */
public class CaptureApi extends NoopApi {
  public record Captured(String name, VertexOrder order, float[] vertices, int[] indices, boolean textured, boolean translucent, @Nullable Translucency translucency) { }

  public static final List<Captured> MESHES = new ArrayList<>();

  public static RenderEngine renderer() {
    try {
      final RenderEngine engine = new RenderEngine();
      final Field api = RenderEngine.class.getDeclaredField("api");
      api.setAccessible(true);
      api.set(engine, new CaptureApi());
      return engine;
    } catch(final ReflectiveOperationException e) {
      throw new RuntimeException("khong tao duoc RenderEngine gia", e);
    }
  }

  @Override
  public Mesh makeMesh(final String name, final VertexOrder vertexOrder, final float[] vertexData, final int[] indices, final boolean textured, final boolean translucent, @Nullable final Translucency translucencyMode, final BufferUsage bufferUsage) {
    MESHES.add(new Captured(name, vertexOrder, vertexData.clone(), indices.clone(), textured, translucent, translucencyMode));
    return super.makeMesh(name, vertexOrder, vertexData, indices, textured, translucent, translucencyMode, bufferUsage);
  }
}
