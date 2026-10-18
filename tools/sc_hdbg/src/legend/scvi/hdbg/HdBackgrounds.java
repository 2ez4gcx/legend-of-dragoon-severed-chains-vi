package legend.scvi.hdbg;

import legend.core.memory.types.IntRef;
import legend.core.renderer.Texture;
import legend.core.renderer.TextureDataFormat;
import legend.core.renderer.TextureDataType;
import legend.core.renderer.TextureInternalFormat;
import legend.game.modding.events.submap.SubmapEnvironmentTextureEvent;
import legend.game.submap.RetailSubmap;
import legend.game.types.NewRootStruct;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.legendofdragoon.modloader.events.EventListener;

import java.lang.reflect.Field;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * HdBackgrounds — THỬ NGHIỆM, chỉ PC: thay ảnh nền cảnh (submap) bằng ảnh upscale x4 (Real-ESRGAN x4plus).
 *
 * <p>Bật: {@code -Dscvi.hdbg=<thư mục PNG>} (tools/run_sc.ps1 -HdBg &lt;thư mục&gt;); không đặt = không làm gì.
 * Ảnh do tools/sc_hd_layers.py dựng:
 * <pre>
 *   &lt;dir&gt;/DRGN2&lt;đĩa&gt;_&lt;thư mục env&gt;.png       nền (vd DRGN21_25.png = cut 7, DRGN21_37.png = cut 11)
 *   &lt;dir&gt;/DRGN2&lt;đĩa&gt;_&lt;env&gt;_fg&lt;k&gt;.png         lớp tiền cảnh k, phủ cả khung, alpha 0/255, trong suốt = (0,0,0,0)
 * </pre>
 * Thay cả bộ hoặc không thay: ô tiền cảnh nào để null thì SC tự dựng bản 384 px kéo giãn lên nền HD (lốm đốm).
 *
 * <p>Vì sao chạy được (SC affcef0): sự kiện bắn trong RetailSubmap.prepareEnv trên luồng "Hardware" (có GL context) nên tạo
 * Texture ở đây an toàn; quad nền/tiền cảnh vẽ theo backgroundRect với uv 0..1 nên ảnh lớn gấp 4 vẫn đúng chỗ.
 * SC giữ và xoá các texture này khi rời cảnh (RetailSubmap.unload, Texture.clearTextureList) -> mỗi lần tạo mới, không cache.
 * Listener tĩnh: lớp thuộc gói "legend" trong một jar trên classpath (có mục thư mục, dựng bằng tools/sc_hdbg/build.ps1);
 * EventManager quét ClasspathHelper.forPackage("legend") sau mỗi bootMods, không cần @Mod. Mọi phương thức @EventListener
 * của lớp gắn @EventListener phải public static (phương thức thường làm EventManager.initialize văng lỗi lúc khởi động).
 */
@EventListener
public final class HdBackgrounds {
  private static final Logger LOGGER = LogManager.getFormatterLogger(HdBackgrounds.class);
  private static final String DIR = System.getProperty("scvi.hdbg", "");
  private static Field newRootField;

  private HdBackgrounds() { }

  @EventListener
  public static void onEnvironmentTexture(final SubmapEnvironmentTextureEvent event) {
    if(DIR.isEmpty()) {
      return;
    }

    final int env = envIndex(event);
    LOGGER.info("hdbg: disk %d cut %d env %d, %d foregrounds", event.disk, event.submapCut, env, event.foregrounds.length);
    if(env < 0) {
      return;
    }

    final String base = "DRGN2" + event.disk + '_' + env;
    final Path bg = Path.of(DIR, base + ".png");
    final Path[] fgs = new Path[event.foregrounds.length];
    for(int i = 0; i < fgs.length; i++) {
      fgs[i] = Path.of(DIR, base + "_fg" + i + ".png");
    }

    if(!Files.isRegularFile(bg)) {
      return;
    }
    for(final Path fg : fgs) {
      if(!Files.isRegularFile(fg)) {
        LOGGER.warn("hdbg: %s thieu %s, giu anh goc", base, fg.getFileName());
        return;
      }
    }

    // Nền: lọc LINEAR (thu nhỏ/kéo theo camera mượt), CLAMP (LINEAR + REPEAT lấy màu mép đối diện vào cột đầu/cuối)
    event.background = Texture.create("HD submap background " + base, builder -> {
      builder.png(bg);
      builder.internalFormat(TextureInternalFormat.RGBA_8);
      builder.dataFormat(TextureDataFormat.RGBA);
      builder.dataType(TextureDataType.UBYTE);
      builder.minFilter(true);
      builder.magFilter(true);
      builder.wrapS(false);
      builder.wrapT(false);
    });

    // Tiền cảnh: giữ NEAREST — standard.fsh chỉ bỏ texel (0,0,0,0), LINEAR tạo texel alpha lưng chừng vẽ đặc thành viền tối
    for(int i = 0; i < fgs.length; i++) {
      final Path fg = fgs[i];
      event.foregrounds[i] = Texture.create("HD submap foreground " + base + ' ' + i, builder -> {
        builder.png(fg);
        builder.internalFormat(TextureInternalFormat.RGBA_8);
        builder.dataFormat(TextureDataFormat.RGBA);
        builder.dataType(TextureDataType.UBYTE);
        builder.wrapS(false);
        builder.wrapT(false);
      });
    }

    LOGGER.info("hdbg: %s -> nen %dx%d + %d tien canh", base, event.background.width, event.background.height, fgs.length);
  }

  /**
   * Thư mục env trong DRGN2&lt;disk&gt; của cut này, tính lại bằng chính NewRootStruct.getDrgnFile như RetailSubmap.loadEnv
   * (loadEnv đã đặt drgnBinIndex_800bc058 = event.disk nên lần gọi lại chọn cùng bản sớm/muộn; chỉ có thể lệch khi bản sớm
   * và bản muộn khác nhau mà nằm cùng một đĩa — NEWROOT.RDT affcef0 không có cut nào như vậy, và RetailSubmap.loadAssets
   * cũng gọi lại y như thế). -1 nếu không xác định (không phải RetailSubmap, lỗi phản chiếu, hoặc đĩa không khớp).
   */
  private static int envIndex(final SubmapEnvironmentTextureEvent event) {
    if(!(event.getSubmap() instanceof final RetailSubmap submap)) {
      return -1;
    }

    try {
      if(newRootField == null) {
        final Field f = RetailSubmap.class.getDeclaredField("newRoot");
        f.setAccessible(true);
        newRootField = f;
      }

      final IntRef drgn = new IntRef();
      final IntRef file = new IntRef();
      ((NewRootStruct)newRootField.get(submap)).getDrgnFile(event.submapCut, drgn, file);
      return drgn.get() == event.disk ? file.get() : -1;
    } catch(final ReflectiveOperationException | RuntimeException e) {
      LOGGER.warn("hdbg: khong tinh duoc thu muc env cua cut %d", event.submapCut, e);
      return -1;
    }
  }
}
