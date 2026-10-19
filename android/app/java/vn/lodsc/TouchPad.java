package vn.lodsc;

import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.view.HapticFeedbackConstants;
import android.view.MotionEvent;
import android.view.View;

import java.util.Arrays;

/**
 * Tay cầm ảo vẽ trên màn hình: D-pad trái, ○ × △ □ phải, L1/L2/R1/R2 trên, SELECT/START dưới L1/R1; giữa trên là ⚙ (cài đặt
 * phím, TouchSettings), nút ẩn/hiện và ▶▶ (tua nhanh).
 * Gửi trạng thái nút vào tay cầm ảo của SDL (libsclauncher.so: SDL_AttachVirtualJoystick kiểu gamepad, nút theo thứ tự
 * SDL_GamepadButton), SC nhận như tay cầm thật. Tua nhanh: nativeSetSpeed (0 = tắt, n = hệ số), game đọc mỗi khung
 * (sc-android: SdlWindow + AndroidBridge). Chạm ngoài các nút: chuyển cho SDL (chuột/cảm ứng của menu SC).
 * Tự ẩn khi có tay cầm thật bấm nút. Cài đặt (độ đậm, cỡ phím, rung, tốc độ tua nhanh) lưu trong SharedPreferences "touchpad".
 */
public final class TouchPad extends View {
  // SDL_GamepadButton
  static final int BUTTON_SOUTH = 0;
  static final int BUTTON_EAST = 1;
  static final int BUTTON_WEST = 2;
  static final int BUTTON_NORTH = 3;
  static final int BUTTON_BACK = 4;
  static final int BUTTON_START = 6;
  static final int BUTTON_LEFT_SHOULDER = 9;
  static final int BUTTON_RIGHT_SHOULDER = 10;
  static final int BUTTON_DPAD_UP = 11;
  static final int BUTTON_DPAD_DOWN = 12;
  static final int BUTTON_DPAD_LEFT = 13;
  static final int BUTTON_DPAD_RIGHT = 14;
  static final int BUTTON_COUNT = 26;
  // SDL_GamepadAxis
  static final int AXIS_LEFT_TRIGGER = 4;
  static final int AXIS_RIGHT_TRIGGER = 5;
  /** chỉ số giả cho L2/R2 (là trục trên tay cầm SDL) */
  private static final int L2 = 100;
  private static final int R2 = 101;
  /** nút của lớp phủ, không gửi vào game */
  private static final int TOGGLE = 200;
  private static final int SETTINGS = 201;
  private static final int FAST_FORWARD = 202;

  static final String PREFS = "touchpad";
  static final int DEFAULT_OPACITY = 60;
  static final int DEFAULT_SIZE = 100;
  static final int DEFAULT_FF_SPEED = 2;
  static final int MIN_OPACITY = 10;
  static final int MAX_OPACITY = 100;
  static final int MIN_SIZE = 70;
  /** lớn hơn thì D-pad chồng lên SELECT ở máy 20:9 */
  static final int MAX_SIZE = 120;

  static native void nativeSetButton(int button, boolean down);

  static native void nativeSetAxis(int axis, int value);

  static native void nativeSetSpeed(int speed);

  static void press(final int button, final boolean down) {
    try {
      if(button == L2 || button == R2) {
        nativeSetAxis(button == L2 ? AXIS_LEFT_TRIGGER : AXIS_RIGHT_TRIGGER, down ? 32767 : 0);
      } else {
        nativeSetButton(button, down);
      }
    } catch(final UnsatisfiedLinkError ignored) {
      // libsclauncher chưa nạp
    }
  }

  private static void sendSpeed(final int speed) {
    try {
      nativeSetSpeed(speed);
    } catch(final UnsatisfiedLinkError ignored) {
      // libsclauncher chưa nạp
    }
  }

  private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
  private final Paint stroke = new Paint(Paint.ANTI_ALIAS_FLAG);
  private final Paint text = new Paint(Paint.ANTI_ALIAS_FLAG);
  private final Path icon = new Path();
  /** nút đang giữ bởi từng ngón (pointer id -> danh sách nút) */
  private final int[][] held = new int[16][];
  private final boolean[] down = new boolean[256];
  private boolean visible = true;

  // cài đặt (TouchSettings)
  private final SharedPreferences prefs;
  /** độ đậm (%): 60 = như bản đầu */
  private int opacity;
  /** cỡ phím (%) */
  private int size;
  private boolean haptic;
  /** hệ số tốc độ khi bật tua nhanh */
  private int ffSpeed;
  private boolean ffOn;

  // hình học (tính lại khi đổi kích thước hoặc cỡ phím)
  private float dpadX;
  private float dpadY;
  private float dpadR;
  private float faceX;
  private float faceY;
  private float faceR;
  private float faceOff;
  private float textSize;
  private final RectF l1 = new RectF();
  private final RectF l2 = new RectF();
  private final RectF r1 = new RectF();
  private final RectF r2 = new RectF();
  private final RectF select = new RectF();
  private final RectF start = new RectF();
  private final RectF toggle = new RectF();
  private final RectF settings = new RectF();
  private final RectF fastForward = new RectF();

  public TouchPad(final Context c) {
    super(c);
    this.stroke.setStyle(Paint.Style.STROKE);
    this.text.setTextAlign(Paint.Align.CENTER);
    this.prefs = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    this.opacity = clamp(this.prefs.getInt("opacity", DEFAULT_OPACITY), MIN_OPACITY, MAX_OPACITY);
    this.size = clamp(this.prefs.getInt("size", DEFAULT_SIZE), MIN_SIZE, MAX_SIZE);
    this.haptic = this.prefs.getBoolean("haptic", true);
    this.ffSpeed = clamp(this.prefs.getInt("ff_speed", DEFAULT_FF_SPEED), 2, 4);
  }

  private static int clamp(final int v, final int min, final int max) {
    return Math.max(min, Math.min(max, v));
  }

  int opacity() {
    return this.opacity;
  }

  int size() {
    return this.size;
  }

  boolean haptic() {
    return this.haptic;
  }

  int fastForwardSpeed() {
    return this.ffSpeed;
  }

  void setOpacity(final int opacity) {
    this.opacity = clamp(opacity, MIN_OPACITY, MAX_OPACITY);
    this.prefs.edit().putInt("opacity", this.opacity).apply();
    this.invalidate();
  }

  void setSize(final int size) {
    this.size = clamp(size, MIN_SIZE, MAX_SIZE);
    this.prefs.edit().putInt("size", this.size).apply();
    this.relayout(this.getWidth(), this.getHeight());
    this.invalidate();
  }

  void setHaptic(final boolean haptic) {
    this.haptic = haptic;
    this.prefs.edit().putBoolean("haptic", haptic).apply();
  }

  void setFastForwardSpeed(final int speed) {
    this.ffSpeed = clamp(speed, 2, 4);
    this.prefs.edit().putInt("ff_speed", this.ffSpeed).apply();
    if(this.ffOn) {
      sendSpeed(this.ffSpeed);
    }
    this.invalidate();
  }

  /** màu trắng với độ đậm theo cài đặt (base = độ đậm ở mức mặc định 60%) */
  private int white(final int base) {
    return Color.argb(clamp(Math.round(base * this.opacity / (float)DEFAULT_OPACITY), 0, 255), 255, 255, 255);
  }

  private int pressedColor() {
    return Color.argb(clamp(Math.round(140 * Math.max(this.opacity, 40) / (float)DEFAULT_OPACITY), 0, 255), 255, 220, 120);
  }

  void setHiddenByController() {
    if(this.visible) {
      this.post(() -> {
        this.visible = false;
        this.releaseAll();
        this.invalidate();
      });
    }
  }

  @Override
  protected void onSizeChanged(final int w, final int h, final int ow, final int oh) {
    this.relayout(w, h);
  }

  private void relayout(final int w, final int h) {
    if(w == 0 || h == 0) {
      return;
    }
    final float base = Math.min(w, h);
    final float u = base * this.size / 100f;
    this.dpadR = u * 0.20f;
    this.dpadX = this.dpadR * 1.25f;
    this.dpadY = h - this.dpadR * 1.25f;
    this.faceR = u * 0.075f;
    this.faceOff = u * 0.13f;
    this.faceX = w - this.faceOff - this.faceR * 1.6f;
    this.faceY = h - this.faceOff - this.faceR * 1.6f;
    final float bw = u * 0.20f;
    final float bh = u * 0.10f;
    final float m = base * 0.03f;
    this.l2.set(m, m, m + bw, m + bh);
    this.l1.set(m, m * 2 + bh, m + bw, m * 2 + bh * 2);
    this.r2.set(w - m - bw, m, w - m, m + bh);
    this.r1.set(w - m - bw, m * 2 + bh, w - m, m * 2 + bh * 2);
    // SELECT/START ở hai cột bên (dưới L1/R1): giữa đáy màn hình là dòng ghi công/bản quyền của màn tựa
    this.select.set(m, m * 3 + bh * 2, m + bw, m * 3 + bh * 2.8f);
    this.start.set(w - m - bw, m * 3 + bh * 2, w - m, m * 3 + bh * 2.8f);
    // hàng giữa trên: ⚙ | ẩn/hiện | ▶▶ — cỡ cố định, không theo cài đặt cỡ phím
    final float tb = base * 0.10f;
    final float tw = tb * 1.2f;
    final float gap = tb * 0.15f;
    this.toggle.set(w / 2f - tw / 2f, 0, w / 2f + tw / 2f, tb * 0.7f);
    this.settings.set(this.toggle.left - gap - tw, 0, this.toggle.left - gap, tb * 0.7f);
    this.fastForward.set(this.toggle.right + gap, 0, this.toggle.right + gap + tw * 1.3f, tb * 0.7f);
    this.textSize = bh * 0.45f;
    this.stroke.setStrokeWidth(Math.max(2f, base * 0.006f));
  }

  @Override
  protected void onDraw(final Canvas c) {
    this.text.setTextSize(this.textSize);
    this.text.setColor(this.white(200));
    this.stroke.setColor(this.white(140));
    this.drawRect(c, this.toggle, this.visible ? "▼" : "▲", false);
    this.drawRect(c, this.settings, null, false);
    this.gear(c, this.settings);
    this.drawRect(c, this.fastForward, null, this.ffOn);
    this.fastForwardIcon(c, this.fastForward);
    if(!this.visible) {
      return;
    }
    // D-pad
    c.drawCircle(this.dpadX, this.dpadY, this.dpadR, this.stroke);
    final float a = this.dpadR * 0.55f;
    this.arrow(c, this.dpadX, this.dpadY - a, "▲", BUTTON_DPAD_UP);
    this.arrow(c, this.dpadX, this.dpadY + a, "▼", BUTTON_DPAD_DOWN);
    this.arrow(c, this.dpadX - a, this.dpadY, "◀", BUTTON_DPAD_LEFT);
    this.arrow(c, this.dpadX + a, this.dpadY, "▶", BUTTON_DPAD_RIGHT);
    // ○ × △ □ (PlayStation: × xác nhận = SOUTH, ○ hủy = EAST)
    this.face(c, this.faceX, this.faceY - this.faceOff, "△", BUTTON_NORTH);
    this.face(c, this.faceX + this.faceOff, this.faceY, "○", BUTTON_EAST);
    this.face(c, this.faceX, this.faceY + this.faceOff, "×", BUTTON_SOUTH);
    this.face(c, this.faceX - this.faceOff, this.faceY, "□", BUTTON_WEST);
    this.drawRect(c, this.l1, "L1", this.down[BUTTON_LEFT_SHOULDER]);
    this.drawRect(c, this.l2, "L2", this.down[L2]);
    this.drawRect(c, this.r1, "R1", this.down[BUTTON_RIGHT_SHOULDER]);
    this.drawRect(c, this.r2, "R2", this.down[R2]);
    this.drawRect(c, this.select, "SELECT", this.down[BUTTON_BACK]);
    this.drawRect(c, this.start, "START", this.down[BUTTON_START]);
  }

  private void arrow(final Canvas c, final float x, final float y, final String s, final int button) {
    this.fill.setColor(this.down[button] ? this.pressedColor() : this.white(50));
    c.drawCircle(x, y, this.dpadR * 0.32f, this.fill);
    c.drawText(s, x, y + this.text.getTextSize() * 0.35f, this.text);
  }

  private void face(final Canvas c, final float x, final float y, final String s, final int button) {
    this.fill.setColor(this.down[button] ? this.pressedColor() : this.white(60));
    c.drawCircle(x, y, this.faceR, this.fill);
    c.drawCircle(x, y, this.faceR, this.stroke);
    final float old = this.text.getTextSize();
    this.text.setTextSize(this.faceR * 1.1f);
    c.drawText(s, x, y + this.faceR * 0.38f, this.text);
    this.text.setTextSize(old);
  }

  private void drawRect(final Canvas c, final RectF r, final String s, final boolean pressed) {
    this.fill.setColor(pressed ? this.pressedColor() : this.white(60));
    final float rad = r.height() * 0.3f;
    c.drawRoundRect(r, rad, rad, this.fill);
    c.drawRoundRect(r, rad, rad, this.stroke);
    if(s != null) {
      c.drawText(s, r.centerX(), r.centerY() + this.text.getTextSize() * 0.35f, this.text);
    }
  }

  /** bánh răng vẽ bằng nét (ký tự ⚙ có máy hiện thành emoji màu) */
  private void gear(final Canvas c, final RectF r) {
    final float cx = r.centerX();
    final float cy = r.centerY();
    final float rad = r.height() * 0.26f;
    final float old = this.stroke.getStrokeWidth();
    this.stroke.setColor(this.white(200));
    this.stroke.setStrokeWidth(rad * 0.38f);
    c.drawCircle(cx, cy, rad * 0.78f, this.stroke);
    for(int i = 0; i < 8; i++) {
      final double ang = Math.PI / 4 * i;
      final float dx = (float)Math.cos(ang);
      final float dy = (float)Math.sin(ang);
      c.drawLine(cx + dx * rad * 0.9f, cy + dy * rad * 0.9f, cx + dx * rad * 1.35f, cy + dy * rad * 1.35f, this.stroke);
    }
    this.stroke.setStrokeWidth(old);
    this.stroke.setColor(this.white(140));
  }

  /** hai tam giác ▶▶ + hệ số tốc độ */
  private void fastForwardIcon(final Canvas c, final RectF r) {
    final float h = r.height() * 0.42f;
    final float w = h * 0.8f;
    final float x0 = r.left + r.width() * 0.16f;
    final float cy = r.centerY();
    this.icon.reset();
    for(int i = 0; i < 2; i++) {
      final float x = x0 + i * w;
      this.icon.moveTo(x, cy - h / 2);
      this.icon.lineTo(x + w, cy);
      this.icon.lineTo(x, cy + h / 2);
      this.icon.close();
    }
    this.fill.setColor(this.white(200));
    c.drawPath(this.icon, this.fill);
    final float old = this.text.getTextSize();
    this.text.setTextSize(r.height() * 0.5f);
    c.drawText("×" + this.ffSpeed, x0 + w * 2 + (r.right - x0 - w * 2) / 2f, cy + this.text.getTextSize() * 0.35f, this.text);
    this.text.setTextSize(old);
  }

  /** nút dưới điểm (x, y), null nếu không có */
  private int[] hit(final float x, final float y) {
    if(this.toggle.contains(x, y)) {
      return new int[] {TOGGLE};
    }
    if(this.settings.contains(x, y)) {
      return new int[] {SETTINGS};
    }
    if(this.fastForward.contains(x, y)) {
      return new int[] {FAST_FORWARD};
    }
    if(!this.visible) {
      return null;
    }
    final float dx = x - this.dpadX;
    final float dy = y - this.dpadY;
    if(dx * dx + dy * dy <= this.dpadR * this.dpadR * 1.3f) {
      final double ang = Math.toDegrees(Math.atan2(-dy, dx)); // 0 = phải, 90 = lên
      final int[] out = new int[2];
      int n = 0;
      if(Math.hypot(dx, dy) < this.dpadR * 0.2f) {
        return new int[0];
      }
      if(ang > 22.5 && ang < 157.5) {
        out[n++] = BUTTON_DPAD_UP;
      }
      if(ang < -22.5 && ang > -157.5) {
        out[n++] = BUTTON_DPAD_DOWN;
      }
      if(ang > 112.5 || ang < -112.5) {
        out[n++] = BUTTON_DPAD_LEFT;
      }
      if(ang < 67.5 && ang > -67.5) {
        out[n++] = BUTTON_DPAD_RIGHT;
      }
      return Arrays.copyOf(out, n);
    }
    final float[][] face = {{this.faceX, this.faceY - this.faceOff, BUTTON_NORTH}, {this.faceX + this.faceOff, this.faceY, BUTTON_EAST},
      {this.faceX, this.faceY + this.faceOff, BUTTON_SOUTH}, {this.faceX - this.faceOff, this.faceY, BUTTON_WEST}};
    for(final float[] f : face) {
      final float fx = x - f[0];
      final float fy = y - f[1];
      if(fx * fx + fy * fy <= this.faceR * this.faceR * 1.6f) {
        return new int[] {(int)f[2]};
      }
    }
    if(this.l1.contains(x, y)) {
      return new int[] {BUTTON_LEFT_SHOULDER};
    }
    if(this.l2.contains(x, y)) {
      return new int[] {L2};
    }
    if(this.r1.contains(x, y)) {
      return new int[] {BUTTON_RIGHT_SHOULDER};
    }
    if(this.r2.contains(x, y)) {
      return new int[] {R2};
    }
    if(this.select.contains(x, y)) {
      return new int[] {BUTTON_BACK};
    }
    if(this.start.contains(x, y)) {
      return new int[] {BUTTON_START};
    }
    return null;
  }

  private static boolean overlayButton(final int[] b) {
    return b != null && b.length == 1 && b[0] >= TOGGLE;
  }

  @Override
  public boolean onTouchEvent(final MotionEvent e) {
    final int action = e.getActionMasked();
    final int idx = e.getActionIndex();
    if(action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_POINTER_DOWN) {
      final int[] b = this.hit(e.getX(idx), e.getY(idx));
      if(b == null) {
        return false; // để SDL xử lý (chạm vào menu của SC)
      }
      if(overlayButton(b)) {
        this.feedback();
        if(b[0] == TOGGLE) {
          this.visible = !this.visible;
          this.releaseAll();
        } else if(b[0] == FAST_FORWARD) {
          this.ffOn = !this.ffOn;
          sendSpeed(this.ffOn ? this.ffSpeed : 0);
        } else {
          this.releaseAll();
          TouchSettings.show(this.getContext(), this);
        }
        this.invalidate();
        return true;
      }
      this.setHeld(e.getPointerId(idx), b);
      return true;
    }
    if(action == MotionEvent.ACTION_MOVE) {
      for(int i = 0; i < e.getPointerCount(); i++) {
        final int id = e.getPointerId(i);
        if(id < this.held.length && this.held[id] != null) {
          final int[] b = this.hit(e.getX(i), e.getY(i));
          this.setHeld(id, b == null || overlayButton(b) ? new int[0] : b);
        }
      }
      return true;
    }
    if(action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_POINTER_UP || action == MotionEvent.ACTION_CANCEL) {
      if(action == MotionEvent.ACTION_CANCEL) {
        this.releaseAll();
      } else {
        this.setHeld(e.getPointerId(idx), null);
      }
      return true;
    }
    return true;
  }

  private void feedback() {
    if(this.haptic) {
      this.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY);
    }
  }

  private void setHeld(final int pointer, final int[] buttons) {
    if(pointer >= this.held.length) {
      return;
    }
    this.held[pointer] = buttons;
    this.sync();
  }

  private void releaseAll() {
    Arrays.fill(this.held, null);
    this.sync();
  }

  private void sync() {
    final boolean[] now = new boolean[this.down.length];
    for(final int[] h : this.held) {
      if(h != null) {
        for(final int b : h) {
          now[b] = true;
        }
      }
    }
    boolean changed = false;
    boolean pressed = false;
    for(int b = 0; b < now.length; b++) {
      if(now[b] != this.down[b]) {
        this.down[b] = now[b];
        press(b, now[b]);
        changed = true;
        pressed |= now[b];
      }
    }
    if(pressed) {
      this.feedback();
    }
    if(changed) {
      this.invalidate();
    }
  }
}
