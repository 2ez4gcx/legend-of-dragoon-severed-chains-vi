import legend.core.gpu.Rect4i;
import legend.core.gpu.VramTextureLoader;
import legend.core.gpu.VramTextureSingle;
import legend.game.submap.EnvironmentFile;
import legend.game.submap.EnvironmentTextureMetrics24;
import legend.game.tim.Tim;
import legend.game.unpacker.FileData;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * BgDump — xuất ảnh nền cảnh (submap) của Severed Chains ra PNG, ghép đúng như RetailSubmap.prepareEnv (SC affcef0):
 * các mảnh nền ghép thành một ảnh, mỗi lớp tiền cảnh (cutout) là một ảnh cùng kích thước có trong suốt.
 *
 * Cách gọi (tools/sc_bgdump.ps1 dịch và chạy):
 *   java -cp "BgDump;lod-game.jar;libs/*" BgDump <game/files> <thư mục ra> DRGN21/4 DRGN21/7 ...
 * Ra: <ra>/<DRGN>_<n>_bg.png (nền), _fg<k>.png (tiền cảnh), _all.png (nền + tiền cảnh, như lúc không có nhân vật).
 * Dữ liệu suy ra từ đĩa gốc: chỉ để xem/thử trên máy, không commit, không phát hành.
 */
public final class BgDump {
  private BgDump() { }

  public static void main(final String[] args) throws Exception {
    final Path files = Path.of(args[0]);
    final File out = new File(args[1]);
    out.mkdirs();

    for(int a = 2; a < args.length; a++) {
      final String[] parts = args[a].split("/");
      final Path dir = files.resolve("SECT").resolve(parts[0] + ".BIN").resolve(parts[1]);
      dump(dir, new File(out, parts[0] + '_' + parts[1]).getPath());
    }
  }

  private static void dump(final Path dir, final String prefix) throws Exception {
    final EnvironmentFile env = new EnvironmentFile(new FileData(Files.readAllBytes(dir.resolve("0"))));

    int timCount = 0;
    while(Files.exists(dir.resolve(String.valueOf(3 + timCount)))) {
      timCount++;
    }

    final Tim[] envTextures = new Tim[timCount];
    for(int i = 0; i < timCount; i++) {
      envTextures[i] = new Tim(new FileData(Files.readAllBytes(dir.resolve(String.valueOf(3 + i)))));
    }

    final int all = env.allTextureCount_14;
    final int bgCount = env.backgroundTextureCount_15;
    final int fgCount = env.foregroundTextureCount_16;
    final Tim[] tims = new Tim[all];
    final Rect4i[] rects = new Rect4i[all];

    for(int i = 0; i < all; i++) {
      final EnvironmentTextureMetrics24 m = env.environments_18[i];
      final int tpX = (m.tpage_20 & 0b1111) * 64;
      final int tpY = (m.tpage_20 & 0b10000) != 0 ? 256 : 0;

      for(final Tim texture : envTextures) {
        if(texture.getImageRect().contains(tpX, tpY)) {
          tims[i] = texture;
          rects[i] = new Rect4i(m.textureOffsetX_10, m.textureOffsetY_12, m.vramPos_08.w, m.vramPos_08.h);
          break;
        }
      }
    }

    // Rect4i.bound của SC không bỏ qua phần tử null
    int x0 = Integer.MAX_VALUE, y0 = Integer.MAX_VALUE, x1 = Integer.MIN_VALUE, y1 = Integer.MIN_VALUE;
    for(final Rect4i r : rects) {
      if(r != null) {
        x0 = Math.min(x0, r.x);
        y0 = Math.min(y0, r.y);
        x1 = Math.max(x1, r.x + r.w);
        y1 = Math.max(y1, r.y + r.h);
      }
    }
    final int w = x1 - x0;
    final int h = y1 - y0;

    final BufferedImage bg = new BufferedImage(w, h, BufferedImage.TYPE_INT_ARGB);
    final BufferedImage composite = new BufferedImage(w, h, BufferedImage.TYPE_INT_ARGB);

    for(int i = 0; i < bgCount; i++) {
      if(tims[i] != null) {
        blit(bg, tims[i], env.environments_18[i], rects[i], x0, y0);
      }
    }
    composite.getGraphics().drawImage(bg, 0, 0, null);

    for(int i = 0; i < fgCount; i++) {
      final int slot = bgCount + i;
      if(tims[slot] != null) {
        final BufferedImage fg = new BufferedImage(w, h, BufferedImage.TYPE_INT_ARGB);
        blit(fg, tims[slot], env.environments_18[slot], rects[slot], x0, y0);
        ImageIO.write(fg, "png", new File(prefix + "_fg" + i + ".png"));
        composite.getGraphics().drawImage(fg, 0, 0, null);
      }
    }

    ImageIO.write(bg, "png", new File(prefix + "_bg.png"));
    ImageIO.write(composite, "png", new File(prefix + "_all.png"));
    System.out.printf("%s: %dx%d, nen %d, tien canh %d%n", prefix, w, h, bgCount, fgCount);
  }

  private static void blit(final BufferedImage img, final Tim tim, final EnvironmentTextureMetrics24 m, final Rect4i rect, final int x0, final int y0) {
    final VramTextureSingle texture = VramTextureLoader.textureFromTim(tim);
    final VramTextureSingle palette = VramTextureLoader.palettesFromTim(tim)[0];
    final Rect4i applied = new Rect4i(m.vramPos_08.x, m.vramPos_08.y, rect.w, rect.h);

    // như prepareEnv: cutout vượt khỏi texture (DRGN21/712) thì cắt bớt
    if(applied.x + applied.w > texture.rect.w) {
      applied.w = texture.rect.w - applied.x;
    }
    if(applied.y + applied.h > texture.rect.h) {
      applied.h = texture.rect.h - applied.y;
    }

    final int[] data = texture.applyPalette(palette, applied);
    for(int y = 0; y < applied.h; y++) {
      for(int x = 0; x < applied.w; x++) {
        final int c = data[y * applied.w + x];
        if(c != 0) {
          // SC: số nguyên RGBA little-endian (R ở byte thấp); màu 0 = trong suốt
          final int argb = 0xff000000 | (c & 0xff) << 16 | (c >> 8 & 0xff) << 8 | (c >> 16 & 0xff);
          img.setRGB(rect.x - x0 + x, rect.y - y0 + y, argb);
        }
      }
    }
  }
}
