package legend.core;

import legend.core.renderer.RenderEngine;

/**
 * Lớp GIẢ, chỉ dùng trong phép thử không cần GL của tools/sc_charfx/java/build.ps1 -Check (thư mục out/sc_charfx_test đứng
 * trước jar game trên classpath của JVM thử). GameEngine thật khởi tạo cấu hình, GPU, SPU, âm thanh, cửa sổ SDL, font ./gfx...
 * — TmdObjLoader chỉ cần GameEngine.RENDERER.api().makeMesh(...), nên lớp giả chỉ có RENDERER với RenderApi ghi lại lưới
 * (CaptureApi). Bản gốc và bản ghi đè chạy cùng lớp giả này nên so sánh vẫn công bằng. KHÔNG bao giờ vào out/sc-charfx.jar.
 */
public final class GameEngine {
  private GameEngine() { }

  public static final RenderEngine RENDERER = scvi.pncheck.CaptureApi.renderer();
}
