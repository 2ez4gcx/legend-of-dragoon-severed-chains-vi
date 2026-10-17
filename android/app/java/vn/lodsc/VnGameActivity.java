package vn.lodsc;

import android.app.ActivityManager;
import android.content.Context;
import android.os.Bundle;
import android.os.Process;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;

import org.libsdl.app.SDLActivity;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;

/**
 * Activity chạy game: SDL3 (SDLActivity) nạp libSDL3.so + libsclauncher.so rồi gọi SDL_main của libsclauncher, nơi tạo máy
 * ảo HotSpot (JRE trong filesDir/jre) và chạy legend.game.Main với thư mục làm việc filesDir/game. Lớp phủ TouchPad là
 * tay cầm ảo; nút Quay lại của Android = nút ○ (hủy/quay lại trong game).
 * HotSpot không khởi động lại được trong cùng tiến trình -> khi activity đóng thì kết thúc tiến trình.
 */
public class VnGameActivity extends SDLActivity {
  private TouchPad pad;

  @Override
  protected String[] getLibraries() {
    return new String[] {"SDL3", "sclauncher"};
  }

  @Override
  protected String getMainFunction() {
    return "SDL_main";
  }

  @Override
  protected String[] getArguments() {
    final File game = Payload.gameDir(this);
    final List<String> args = new ArrayList<>();
    args.add("game=" + game.getAbsolutePath());
    args.add("jre=" + Payload.jreDir(this).getAbsolutePath());
    args.add("lib=" + this.getApplicationInfo().nativeLibraryDir);
    args.add("tmp=" + this.getCacheDir().getAbsolutePath());
    args.add("xmx=" + heapMb(this));
    try {
      // classpath tuyệt đối: JNI_CreateJavaVM không mở rộng "libs/*" như trình chạy java
      final StringBuilder cp = new StringBuilder();
      for(final String line : Files.readAllLines(new File(game, "android-classpath.txt").toPath(), StandardCharsets.UTF_8)) {
        if(!line.trim().isEmpty()) {
          if(cp.length() > 0) {
            cp.append(':');
          }
          cp.append(new File(game, line.trim()).getAbsolutePath());
        }
      }
      args.add("cp=" + cp);
      // tuỳ chọn JVM thêm để gỡ lỗi (mỗi dòng một tuỳ chọn "-D..."/"-X..."), không có trong bản phát hành
      final File extra = new File(game, "android-jvm.txt");
      if(extra.isFile()) {
        for(final String line : Files.readAllLines(extra.toPath(), StandardCharsets.UTF_8)) {
          if(line.trim().startsWith("-")) {
            args.add(line.trim());
          }
        }
      }
    } catch(final IOException e) {
      throw new RuntimeException(e);
    }
    return args.toArray(new String[0]);
  }

  /** heap Java: SC trên máy tính dùng mặc định 1/4 RAM; ở đây 1/4 RAM, kẹp 1024..2048 MB */
  static int heapMb(final Context c) {
    final ActivityManager.MemoryInfo mi = new ActivityManager.MemoryInfo();
    ((ActivityManager)c.getSystemService(Context.ACTIVITY_SERVICE)).getMemoryInfo(mi);
    final long quarter = mi.totalMem / 4 / (1024 * 1024);
    return (int)Math.max(1024, Math.min(2048, quarter));
  }

  @Override
  protected void onCreate(final Bundle state) {
    super.onCreate(state);
    this.getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    if(mLayout != null) {
      this.pad = new TouchPad(this);
      mLayout.addView(this.pad);
    }
    this.hideSystemBars();
  }

  @Override
  public void onWindowFocusChanged(final boolean hasFocus) {
    super.onWindowFocusChanged(hasFocus);
    if(hasFocus) {
      this.hideSystemBars();
    }
  }

  private void hideSystemBars() {
    final WindowInsetsController c = android.os.Build.VERSION.SDK_INT >= 30 ? this.getWindow().getInsetsController() : null;
    if(c != null) {
      c.hide(WindowInsets.Type.systemBars());
      c.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
    } else {
      this.getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
        | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
    }
  }

  @Override
  public boolean dispatchKeyEvent(final KeyEvent event) {
    if(event.getKeyCode() == KeyEvent.KEYCODE_BACK) {
      if(event.getAction() == KeyEvent.ACTION_DOWN && event.getRepeatCount() == 0) {
        TouchPad.press(TouchPad.BUTTON_EAST, true);
      } else if(event.getAction() == KeyEvent.ACTION_UP) {
        TouchPad.press(TouchPad.BUTTON_EAST, false);
      }
      return true;
    }
    if(this.pad != null && (event.getSource() & android.view.InputDevice.SOURCE_GAMEPAD) == android.view.InputDevice.SOURCE_GAMEPAD) {
      this.pad.setHiddenByController();
    }
    return super.dispatchKeyEvent(event);
  }

  @Override
  protected void onDestroy() {
    super.onDestroy();
    Process.killProcess(Process.myPid());
  }
}
