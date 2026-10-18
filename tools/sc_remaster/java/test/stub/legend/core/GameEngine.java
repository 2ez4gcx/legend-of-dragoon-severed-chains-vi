package legend.core;

import legend.core.gpu.Gpu;
import legend.core.renderer.RenderEngine;

/**
 * Lớp GIẢ, chỉ dùng cho bộ kiểm độc lập tools/sc_remaster/java (build.ps1 -Check): thư mục out/sc_remaster_test đứng trước
 * out/sc-vi.jar và jar game trên classpath của JVM thử. GameEngine thật khởi tạo cấu hình, SPU, âm thanh, cửa sổ SDL, mod...
 * — TmdObjLoader (gốc và bản ghi đè của sc-vi) chỉ cần:
 *   RENDERER.api().makeMesh(...) / makeTexture(...)  -> CaptureApi ghi lại lưới, lệnh vẽ, texture;
 *   GPU.getPixel15(x, y) / uploadData15(...)           -> Gpu thật của SC (thuần Java, mảng int[] VRAM 1024x512), bộ kiểm
 *                                                        tự đặt TIM vào VRAM rồi để FaceVerify của runtime đọc.
 * Bản gốc, bản ghi đè và bộ giả lập (MockRuntime) đều chạy với lớp giả này nên so sánh vẫn công bằng.
 * KHÔNG bao giờ được đóng gói vào out/sc-vi.jar.
 */
public final class GameEngine {
  private GameEngine() { }

  public static final boolean IS_WINDOWS = System.getProperty("os.name").startsWith("Windows");

  public static final RenderEngine RENDERER = scvi.remastercheck.CaptureApi.renderer();

  public static final Gpu GPU = new Gpu();
}
