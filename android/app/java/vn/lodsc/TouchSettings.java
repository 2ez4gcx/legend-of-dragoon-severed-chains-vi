package vn.lodsc;

import android.app.AlertDialog;
import android.content.Context;
import android.widget.CheckBox;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.TextView;

/**
 * Hộp cài đặt tay cầm ảo (nút ⚙ của TouchPad): độ đậm phím, cỡ phím, rung khi bấm, tốc độ của nút tua nhanh ▶▶.
 * Kéo/chọn là thấy ngay trên lớp phủ và lưu luôn (SharedPreferences của TouchPad). Trong lúc hộp mở, cửa sổ game mất tiêu
 * điểm nên SDL tạm dừng game; đóng hộp là chạy tiếp.
 */
final class TouchSettings {
  private TouchSettings() { }

  static void show(final Context c, final TouchPad pad) {
    final float dp = c.getResources().getDisplayMetrics().density;
    final int side = Math.round(24 * dp);
    final int gap = Math.round(12 * dp);

    final LinearLayout root = new LinearLayout(c);
    root.setOrientation(LinearLayout.VERTICAL);
    root.setPadding(side, gap, side, 0);

    final TextView opacityLabel = new TextView(c);
    final SeekBar opacity = new SeekBar(c);
    opacity.setMax((TouchPad.MAX_OPACITY - TouchPad.MIN_OPACITY) / 5);
    opacity.setProgress((pad.opacity() - TouchPad.MIN_OPACITY) / 5);
    final Runnable showOpacity = () -> opacityLabel.setText("Độ đậm phím: " + pad.opacity() + "%");
    showOpacity.run();
    opacity.setOnSeekBarChangeListener(new Seek(v -> {
      pad.setOpacity(TouchPad.MIN_OPACITY + v * 5);
      showOpacity.run();
    }));
    root.addView(opacityLabel);
    root.addView(opacity);

    final TextView sizeLabel = new TextView(c);
    final SeekBar size = new SeekBar(c);
    size.setMax((TouchPad.MAX_SIZE - TouchPad.MIN_SIZE) / 5);
    size.setProgress((pad.size() - TouchPad.MIN_SIZE) / 5);
    final Runnable showSize = () -> sizeLabel.setText("Cỡ phím: " + pad.size() + "%");
    showSize.run();
    size.setOnSeekBarChangeListener(new Seek(v -> {
      pad.setSize(TouchPad.MIN_SIZE + v * 5);
      showSize.run();
    }));
    sizeLabel.setPadding(0, gap, 0, 0);
    root.addView(sizeLabel);
    root.addView(size);

    final CheckBox haptic = new CheckBox(c);
    haptic.setText("Rung nhẹ khi bấm phím");
    haptic.setChecked(pad.haptic());
    haptic.setOnCheckedChangeListener((b, on) -> pad.setHaptic(on));
    haptic.setPadding(haptic.getPaddingLeft(), gap, 0, gap);
    root.addView(haptic);

    final TextView ffLabel = new TextView(c);
    ffLabel.setText("Tốc độ khi bấm nút tua nhanh ▶▶ (bấm lần nữa để về tốc độ thường):");
    root.addView(ffLabel);
    final RadioGroup ff = new RadioGroup(c);
    ff.setOrientation(RadioGroup.HORIZONTAL);
    for(int speed = 2; speed <= 4; speed++) {
      final RadioButton b = new RadioButton(c);
      b.setText("Nhanh gấp " + speed);
      b.setId(1000 + speed);
      b.setPadding(b.getPaddingLeft(), 0, gap * 2, 0);
      ff.addView(b);
    }
    ff.check(1000 + pad.fastForwardSpeed());
    ff.setOnCheckedChangeListener((g, id) -> pad.setFastForwardSpeed(id - 1000));
    root.addView(ff);

    final TextView hint = new TextView(c);
    hint.setText("Tốc độ thường của game: Tùy chọn → Lối chơi → Tốc độ game.\n"
      + "Game chạy chậm, giật: Tùy chọn → Đồ họa → Độ phân giải 720p hoặc 480p.");
    hint.setPadding(0, gap, 0, gap);
    hint.setAlpha(0.75f);
    root.addView(hint);

    final ScrollView scroll = new ScrollView(c);
    scroll.addView(root);

    final AlertDialog dialog = new AlertDialog.Builder(c)
      .setTitle("Tay cầm ảo")
      .setView(scroll)
      .setPositiveButton("Xong", null)
      .setNeutralButton("Mặc định", null)
      .create();
    dialog.setOnShowListener(d -> dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(v -> {
      // "Mặc định" không đóng hộp: trả các thanh về giá trị đầu, listener áp vào TouchPad
      opacity.setProgress((TouchPad.DEFAULT_OPACITY - TouchPad.MIN_OPACITY) / 5);
      size.setProgress((TouchPad.DEFAULT_SIZE - TouchPad.MIN_SIZE) / 5);
      haptic.setChecked(true);
      ff.check(1000 + TouchPad.DEFAULT_FF_SPEED);
    }));
    dialog.show();
  }

  /** SeekBar chỉ cần báo giá trị mới */
  private static final class Seek implements SeekBar.OnSeekBarChangeListener {
    interface Change {
      void apply(int value);
    }

    private final Change change;

    Seek(final Change change) {
      this.change = change;
    }

    @Override
    public void onProgressChanged(final SeekBar bar, final int value, final boolean fromUser) {
      this.change.apply(value);
    }

    @Override
    public void onStartTrackingTouch(final SeekBar bar) { }

    @Override
    public void onStopTrackingTouch(final SeekBar bar) { }
  }
}
