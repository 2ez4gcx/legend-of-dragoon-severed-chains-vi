package legend.game.modding.coremod.config;

import legend.game.saves.BoolConfigEntry;
import legend.game.saves.ConfigCategory;
import legend.game.saves.ConfigStorageLocation;

/**
 * [sc-vi] Tiết kiệm pin. Khi bật, RenderEngine vẽ tối đa 30 khung hình mỗi giây; logic game vẫn chạy đủ nhịp nên tốc độ game
 * không đổi. Cảnh vẽ 60 Hz (đi lại trong các khu vực, bản đồ thế giới, menu) và lúc tua nhanh chỉ vẽ một nửa số khung: GPU làm
 * ít hơn, máy đỡ nóng, đỡ tốn pin; trận đánh (20–30 Hz) không đổi gì. Mặc định tắt.
 */
public class BatterySaverConfigEntry extends BoolConfigEntry {
  public BatterySaverConfigEntry() {
    super(false, ConfigStorageLocation.GLOBAL, ConfigCategory.GRAPHICS);
  }

  @Override
  public boolean hasHelp() {
    return true;
  }
}
