package legend.game.modding.coremod.config;

import legend.game.saves.BoolConfigEntry;
import legend.game.saves.ConfigCategory;
import legend.game.saves.ConfigStorageLocation;

/**
 * [sc-vi] Tự bỏ khung hình khi máy chậm. Logic game của Severed Chains chạy đúng một lần mỗi khung hình vẽ ra, không bù giờ:
 * máy (nhất là điện thoại) không vẽ kịp 60 khung/giây thì cả game chậm lại như quay chậm. Khi bật, RenderEngine theo dõi lịch
 * chạy và bỏ vẽ những khung bị trễ (vẫn chạy logic) để game giữ đúng tốc độ. Máy đủ mạnh không bao giờ bị bỏ khung.
 */
public class AutoFrameSkipConfigEntry extends BoolConfigEntry {
  public AutoFrameSkipConfigEntry() {
    super(true, ConfigStorageLocation.GLOBAL, ConfigCategory.GRAPHICS);
  }

  @Override
  public boolean hasHelp() {
    return true;
  }
}
