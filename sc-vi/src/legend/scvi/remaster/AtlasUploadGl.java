package legend.scvi.remaster;

import legend.core.renderer.Texture;
import org.lwjgl.system.MemoryUtil;

import java.nio.ByteBuffer;

import static org.lwjgl.opengl.GL11C.GL_NEAREST;
import static org.lwjgl.opengl.GL11C.GL_NEAREST_MIPMAP_NEAREST;
import static org.lwjgl.opengl.GL11C.GL_RGBA;
import static org.lwjgl.opengl.GL11C.GL_RGBA8;
import static org.lwjgl.opengl.GL11C.GL_TEXTURE_2D;
import static org.lwjgl.opengl.GL11C.GL_TEXTURE_BINDING_2D;
import static org.lwjgl.opengl.GL11C.GL_TEXTURE_MAG_FILTER;
import static org.lwjgl.opengl.GL11C.GL_TEXTURE_MIN_FILTER;
import static org.lwjgl.opengl.GL11C.GL_TEXTURE_WRAP_S;
import static org.lwjgl.opengl.GL11C.GL_TEXTURE_WRAP_T;
import static org.lwjgl.opengl.GL11C.GL_UNSIGNED_BYTE;
import static org.lwjgl.opengl.GL11C.glBindTexture;
import static org.lwjgl.opengl.GL11C.glGetInteger;
import static org.lwjgl.opengl.GL11C.glTexImage2D;
import static org.lwjgl.opengl.GL11C.glTexParameteri;
import static org.lwjgl.opengl.GL12C.GL_CLAMP_TO_EDGE;
import static org.lwjgl.opengl.GL12C.GL_TEXTURE_BASE_LEVEL;
import static org.lwjgl.opengl.GL12C.GL_TEXTURE_MAX_LEVEL;
import static org.lwjgl.opengl.GL13C.GL_TEXTURE0;
import static org.lwjgl.opengl.GL13C.glActiveTexture;

/**
 * [sc-vi] AtlasUpload cho OpenGL (PC). Chỉ được nạp (bằng tên lớp) khi RENDERER.api() là GlApi. Xem AtlasUpload.
 */
final class AtlasUploadGl implements AtlasUpload {
  @Override
  public void upload(final Texture texture, final byte[][] levels, final int[] w, final int[] h) {
    glActiveTexture(GL_TEXTURE0);

    // Texture.create vừa gắn texture ở đơn vị 0 (bộ nhớ đệm gắn của SC cũng ghi như vậy); gắn lại tường minh cho chắc
    final int id = AtlasUpload.textureId(texture);
    if(id > 0) {
      glBindTexture(GL_TEXTURE_2D, id);
    } else if(glGetInteger(GL_TEXTURE_BINDING_2D) == 0) {
      throw new IllegalStateException("atlas texture is not bound on unit 0");
    }

    for(int k = 1; k < levels.length; k++) {
      final ByteBuffer buf = MemoryUtil.memAlloc(levels[k].length);
      try {
        buf.put(levels[k]).flip();
        glTexImage2D(GL_TEXTURE_2D, k, GL_RGBA8, w[k], h[k], 0, GL_RGBA, GL_UNSIGNED_BYTE, buf);
      } finally {
        MemoryUtil.memFree(buf);
      }
    }

    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_BASE_LEVEL, 0);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAX_LEVEL, levels.length - 1);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST_MIPMAP_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
  }
}
