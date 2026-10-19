package legend.game.modding.coremod.config;

import legend.core.Config;
import legend.game.saves.ConfigCategory;
import legend.game.saves.ConfigCollection;
import legend.game.saves.ConfigStorageLocation;
import legend.game.saves.EnumConfigEntry;

/**
 * [sc-vi] Tốc độ game trong Tùy chọn. Severed Chains có sẵn hệ số tốc độ (Config.gameSpeedMultiplier: logic, hoạt cảnh và
 * giới hạn FPS cùng nhân lên, nhạc nền giữ nguyên) nhưng bản gốc chỉ đổi được bằng phím tắt (+/-) hoặc trình gỡ lỗi. Mục này
 * lưu trong config.dcnf (chung cho mọi lượt chơi) và được áp lại sau khi nạp cấu hình (ConfigStorage). Nhãn:
 * lod_core.config.game_speed.X1..X4.
 */
public class GameSpeedConfigEntry extends EnumConfigEntry<GameSpeedConfigEntry.Speed> {
  public enum Speed {
    X1(1),
    X2(2),
    X3(3),
    X4(4),
    ;

    public final int multiplier;

    Speed(final int multiplier) {
      this.multiplier = multiplier;
    }
  }

  public GameSpeedConfigEntry() {
    super(Speed.class, Speed.X1, ConfigStorageLocation.GLOBAL, ConfigCategory.GAMEPLAY);
  }

  @Override
  public boolean hasHelp() {
    return true;
  }

  @Override
  public void onChange(final ConfigCollection configCollection, final Speed oldValue, final Speed newValue) {
    super.onChange(configCollection, oldValue, newValue);
    apply(newValue);
  }

  /** Đặt hệ số tốc độ đang chạy và hệ số "đã nạp" (phím đổi tốc độ / nút tua nhanh trả về giá trị này khi tắt). */
  public static void apply(final Speed speed) {
    Config.setGameSpeedMultiplier(speed.multiplier);
    Config.setLoadedGameSpeedMultiplier(speed.multiplier);
  }
}
