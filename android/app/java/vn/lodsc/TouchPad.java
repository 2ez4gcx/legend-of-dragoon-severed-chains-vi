package vn.lodsc;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.view.MotionEvent;
import android.view.View;

import java.util.Arrays;

/**
 * Tay cầm ảo vẽ trên màn hình: D-pad trái, ○ × △ □ phải, L1/L2/R1/R2 trên, SELECT/START dưới; nút ẩn/hiện ở giữa trên.
 * Gửi trạng thái nút vào tay cầm ảo của SDL (libsclauncher.so: SDL_AttachVirtualJoystick kiểu gamepad, nút theo thứ tự
 * SDL_GamepadButton), SC nhận như tay cầm thật. Chạm ngoài các nút: chuyển cho SDL (chuột/cảm ứng của menu SC).
 * Tự ẩn khi có tay cầm thật bấm nút.
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
  private static final int TOGGLE = 200;

  static native void nativeSetButton(int button, boolean down);

  static native void nativeSetAxis(int axis, int value);

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

  private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
  private final Paint stroke = new Paint(Paint.ANTI_ALIAS_FLAG);
  private final Paint text = new Paint(Paint.ANTI_ALIAS_FLAG);
  /** nút đang giữ bởi từng ngón (pointer id -> danh sách nút) */
  private final int[][] held = new int[16][];
  private final boolean[] down = new boolean[256];
  private boolean visible = true;

  // hình học (tính lại khi đổi kích thước)
  private float dpadX;
  private float dpadY;
  private float dpadR;
  private float faceX;
  private float faceY;
  private float faceR;
  private float faceOff;
  private final RectF l1 = new RectF();
  private final RectF l2 = new RectF();
  private final RectF r1 = new RectF();
  private final RectF r2 = new RectF();
  private final RectF select = new RectF();
  private final RectF start = new RectF();
  private final RectF toggle = new RectF();

  public TouchPad(final Context c) {
    super(c);
    this.stroke.setStyle(Paint.Style.STROKE);
    this.text.setTextAlign(Paint.Align.CENTER);
    this.text.setColor(Color.argb(200, 255, 255, 255));
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
    final float u = Math.min(w, h);
    this.dpadR = u * 0.20f;
    this.dpadX = this.dpadR * 1.25f;
    this.dpadY = h - this.dpadR * 1.25f;
    this.faceR = u * 0.075f;
    this.faceOff = u * 0.13f;
    this.faceX = w - this.faceOff - this.faceR * 1.6f;
    this.faceY = h - this.faceOff - this.faceR * 1.6f;
    final float bw = u * 0.20f;
    final float bh = u * 0.10f;
    final float m = u * 0.03f;
    this.l2.set(m, m, m + bw, m + bh);
    this.l1.set(m, m * 2 + bh, m + bw, m * 2 + bh * 2);
    this.r2.set(w - m - bw, m, w - m, m + bh);
    this.r1.set(w - m - bw, m * 2 + bh, w - m, m * 2 + bh * 2);
    this.select.set(w / 2f - bw - m, h - m - bh * 0.8f, w / 2f - m, h - m);
    this.start.set(w / 2f + m, h - m - bh * 0.8f, w / 2f + bw + m, h - m);
    this.toggle.set(w / 2f - bh * 0.6f, 0, w / 2f + bh * 0.6f, bh * 0.7f);
    this.text.setTextSize(bh * 0.45f);
    this.stroke.setStrokeWidth(Math.max(2f, u * 0.006f));
  }

  @Override
  protected void onDraw(final Canvas c) {
    this.fill.setColor(Color.argb(60, 255, 255, 255));
    this.stroke.setColor(Color.argb(140, 255, 255, 255));
    this.drawRect(c, this.toggle, this.visible ? "▼" : "▲", false);
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
    this.fill.setColor(this.down[button] ? Color.argb(140, 255, 220, 120) : Color.argb(50, 255, 255, 255));
    c.drawCircle(x, y, this.dpadR * 0.32f, this.fill);
    c.drawText(s, x, y + this.text.getTextSize() * 0.35f, this.text);
  }

  private void face(final Canvas c, final float x, final float y, final String s, final int button) {
    this.fill.setColor(this.down[button] ? Color.argb(140, 255, 220, 120) : Color.argb(60, 255, 255, 255));
    c.drawCircle(x, y, this.faceR, this.fill);
    c.drawCircle(x, y, this.faceR, this.stroke);
    final float old = this.text.getTextSize();
    this.text.setTextSize(this.faceR * 1.1f);
    c.drawText(s, x, y + this.faceR * 0.38f, this.text);
    this.text.setTextSize(old);
  }

  private void drawRect(final Canvas c, final RectF r, final String s, final boolean pressed) {
    this.fill.setColor(pressed ? Color.argb(140, 255, 220, 120) : Color.argb(60, 255, 255, 255));
    final float rad = r.height() * 0.3f;
    c.drawRoundRect(r, rad, rad, this.fill);
    c.drawRoundRect(r, rad, rad, this.stroke);
    c.drawText(s, r.centerX(), r.centerY() + this.text.getTextSize() * 0.35f, this.text);
  }

  /** nút dưới điểm (x, y), null nếu không có */
  private int[] hit(final float x, final float y) {
    if(this.toggle.contains(x, y)) {
      return new int[] {TOGGLE};
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

  @Override
  public boolean onTouchEvent(final MotionEvent e) {
    final int action = e.getActionMasked();
    final int idx = e.getActionIndex();
    if(action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_POINTER_DOWN) {
      final int[] b = this.hit(e.getX(idx), e.getY(idx));
      if(b == null) {
        return false; // để SDL xử lý (chạm vào menu của SC)
      }
      if(b.length == 1 && b[0] == TOGGLE) {
        this.visible = !this.visible;
        this.releaseAll();
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
          this.setHeld(id, b == null || (b.length == 1 && b[0] == TOGGLE) ? new int[0] : b);
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
    for(int b = 0; b < now.length; b++) {
      if(now[b] != this.down[b]) {
        this.down[b] = now[b];
        press(b, now[b]);
        changed = true;
      }
    }
    if(changed) {
      this.invalidate();
    }
  }
}
