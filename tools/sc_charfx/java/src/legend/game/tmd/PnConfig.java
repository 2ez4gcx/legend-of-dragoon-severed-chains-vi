package legend.game.tmd;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

import java.util.Arrays;

/**
 * PnConfig — công tắc của jar thử sc-charfx (out/sc-charfx.jar, chỉ để thử trên PC, không phát hành): chọn mô hình nào được
 * TmdObjLoader ghi bit PN theo góc vào float cờ của từng đỉnh, để geometry shader (tmd.gsh dùng chung field/battle) làm mịn
 * PN-triangles. Điều khiển bằng thuộc tính hệ thống (tools/run_sc.ps1 -Pn n thêm -Dscvi.pn=n):
 *   -Dscvi.pn=n             0/không đặt = tắt (TmdObjLoader cho dữ liệu đỉnh giống hệt bản gốc); 1..4 -> mức 2..4 (số đoạn/cạnh)
 *   -Dscvi.pnStrength8=s    độ phồng theo phần tám, 1..8 (mặc định 8 = PN cổ điển)
 *   -Dscvi.pnModels=a,b     tiền tố tên mô hình được bật (mặc định CombatantModel,SobjModel,WmapEntityModel = tên SC affcef0 truyền
 *                           vào TmdObjLoader.fromModel cho nhân vật/quái trận đấu, đối tượng cảnh, thực thể bản đồ thế giới);
 *                           Shadow và Savepoint luôn bị loại; hiệu ứng (BattleModel, Particle, DustTmd...), sàn trận ("DRGN0/... obj i")
 *                           và lưới PolyBuilder/QuadBuilder (không qua TmdObjLoader) không bao giờ có bit PN theo mặc định
 *   -Dscvi.pnLog=true       ghi log số góc PN của từng phần mô hình
 * Bố cục float cờ (nguyên, chính xác vì < 2^24):
 *   0x01 LIT 0x02 TEXTURED 0x04 COLOURED 0x08 TRANSLUCENT 0x10 QUAD   (gốc)
 *   bit 5-6 góc cục bộ, bit 7-10 cạnh thẳng tới góc j, bit 11 bật PN  (PnEdgeFlags)
 *   bit 12-14 mức 2..4                                                 (LEVEL_SHIFT)
 *   bit 15-18 độ mạnh 1..8 phần tám                                    (STRENGTH_SHIFT; 8 = 0x40000 nằm ở bit 18 — shader chỉ đọc
 *             3 bit 15-17 sẽ thấy 0 và phải hiểu 0 = 8/8, đọc 4 bit 15-18 thấy 8; cả hai đều ra 1,0)
 * Bit mức/độ mạnh có ở MỌI góc của mô hình được bật; shader chỉ dùng khi bit 11 bật (primitive lit + gouraud + đục; mặt trong
 * suốt không bao giờ có bit 11 vì tools/sc_charfx/pn/tmd_pn.gsh vẽ chúng theo đường gốc).
 */
public final class PnConfig {
  private PnConfig() { }

  private static final Logger LOGGER = LogManager.getFormatterLogger(PnConfig.class);

  public static final int LEVEL_SHIFT = 12;
  public static final int STRENGTH_SHIFT = 15;

  public static final int LEVEL = level(Integer.getInteger("scvi.pn", 0));
  public static final int STRENGTH8 = Math.clamp(Integer.getInteger("scvi.pnStrength8", 8), 1, 8);
  private static final String[] MODELS = prefixes(System.getProperty("scvi.pnModels", "CombatantModel,SobjModel,WmapEntityModel"));
  private static final String[] NEVER = {"Shadow", "Savepoint"};
  private static final boolean LOG = Boolean.getBoolean("scvi.pnLog");

  static {
    if(LEVEL != 0) {
      LOGGER.info("scvi-pn: TmdObjLoader override active, level=%d strength8=%d models=%s", LEVEL, STRENGTH8, Arrays.toString(MODELS));
    }
  }

  /** 0 hoặc âm = tắt; còn lại kẹp vào 2..4 (giới hạn max_vertices của geometry shader). */
  static int level(final int value) {
    return value <= 0 ? 0 : Math.clamp(value, 2, 4);
  }

  private static String[] prefixes(final String list) {
    return Arrays.stream(list.split(",")).map(String::trim).filter(s -> !s.isEmpty()).toArray(String[]::new);
  }

  /** Mức PN cho mô hình tên {@code name} (tên TmdObjLoader nhận, ví dụ "CombatantModel (...) part 3"); 0 = không bật. */
  public static int levelFor(final String name) {
    if(LEVEL == 0 || name == null) {
      return 0;
    }

    for(final String p : NEVER) {
      if(name.startsWith(p)) {
        return 0;
      }
    }

    for(final String p : MODELS) {
      if(name.startsWith(p)) {
        return LEVEL;
      }
    }

    return 0;
  }

  /**
   * Bit OR vào cờ đỉnh, [nhóm primitive][gói][góc] theo đúng thứ tự TmdObjLoader đi; null = không ghi gì (đường gốc).
   * Tính một lần cho mỗi lần gọi TmdObjLoader.fromObjTable (một phần mô hình). Lỗi dữ liệu -> bỏ PN cho phần đó, không làm hỏng việc nạp.
   */
  public static int[][][] cornerFlags(final String name, final TmdObjTable1c objTable, final int specialFlags) {
    final int level = levelFor(name);

    if(level < 2) {
      return null;
    }

    final int[][][] flags;
    try {
      flags = PnEdgeFlags.compute(objTable, specialFlags, true);
    } catch(final RuntimeException e) {
      LOGGER.warn("scvi-pn: PN skipped for %s (%s)", name, e);
      return null;
    }

    final int extra = level << LEVEL_SHIFT | STRENGTH8 << STRENGTH_SHIFT;
    int corners = 0;
    int pn = 0;

    for(final int[][] group : flags) {
      for(final int[] packet : group) {
        for(int k = 0; k < packet.length; k++) {
          packet[k] |= extra;
          corners++;

          if((packet[k] & PnEdgeFlags.PN_ENABLE) != 0) {
            pn++;
          }
        }
      }
    }

    if(LOG) {
      LOGGER.info("scvi-pn: %s: %d/%d PN corners", name, pn, corners);
    }

    return flags;
  }
}
