package legend.core.platform;

/**
 * [sc-android] Cầu nối từ lớp phím cảm ứng Android (vn.lodsc.TouchPad, chạy trong máy ảo ART của ứng dụng) sang game
 * (máy ảo HotSpot chạy cùng tiến trình). TouchPad gọi nativeSetSpeed của libsclauncher.so, launcher giữ giá trị trong một
 * biến C và đăng ký (RegisterNatives) hàm fastForward() của lớp này ngay sau khi tạo máy ảo Java. SdlWindow đọc mỗi khung.
 */
final class AndroidBridge {
  private AndroidBridge() { }

  /** 0 = tắt tua nhanh; n >= 2 = hệ số tốc độ khi tua nhanh */
  static native int fastForward();
}
