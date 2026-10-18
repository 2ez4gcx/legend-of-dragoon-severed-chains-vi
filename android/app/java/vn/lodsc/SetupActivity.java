package vn.lodsc;

import android.app.Activity;
import android.content.ClipData;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.UriPermission;
import android.content.pm.ApplicationInfo;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.system.Os;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

/**
 * Màn hình đầu: (1) lần đầu / sau khi cập nhật APK thì giải nén JRE + tệp game (Payload), (2) người chơi chọn 4 file .bin
 * đĩa gốc bằng trình chọn tệp của Android (giữ quyền đọc lâu dài, không chép đĩa), (3) mỗi lần chơi: mở 4 tệp, nối
 * game/isos/discN.bin -> /proc/self/fd/N (SC đọc đĩa mỗi lần khởi động) rồi mở VnGameActivity trong cùng tiến trình.
 *
 * <p>Mô hình HD (route B, tuỳ chọn): nút "Nhập mô hình HD (.zip)" (gói xuất từ công cụ "Tạo mô hình HD" trên máy tính,
 * {@link RemasterImport}) và nút bật/tắt ghi game/remaster.properties. Khi đã có đĩa, app đếm ngược
 * {@value #AUTO_LAUNCH_SECONDS} giây rồi mới tự vào game, để người chơi kịp bấm các nút này (bấm bất kỳ nút nào trừ Chơi
 * thì huỷ đếm ngược; Chơi = vào ngay). Mở bằng {@code --ez setup true} thì không tự vào game như trước.
 *
 * <p>Chỉ bản debuggable (x86_64 thử trên giả lập): {@code --es hd_test_zip <tệp trong filesDir>} nhập thẳng tệp đó
 * (không qua trình chọn tệp), kèm tuỳ chọn {@code --el hd_test_entry_cap / hd_test_total_cap / hd_test_reserve};
 * dùng bởi android/test/remaster_import.ps1.
 */
public class SetupActivity extends Activity {
  private static final int PICK_DISCS = 1;
  private static final int PICK_HD = 2;
  private static final int AUTO_LAUNCH_SECONDS = 3;
  private static final String PREFS = "discs";

  /** Tệp đĩa đang mở: giữ sống suốt tiến trình để đường dẫn /proc/self/fd/N còn dùng được */
  static final List<ParcelFileDescriptor> OPEN_DISCS = new ArrayList<>();

  private TextView status;
  private ProgressBar progress;
  private Button pick;
  private Button play;
  private Button importHd;
  private Button toggleHd;
  private boolean busy;
  /** màn hình đang hiện (giữa onStart và onStop): chỉ đếm ngược tự vào game khi người chơi đang nhìn */
  private boolean started;
  private final Handler ui = new Handler(Looper.getMainLooper());
  /** số giây còn lại trước khi tự vào game; -1 = không đếm */
  private int countdown = -1;
  private final Runnable tickTask = this::tick;
  /** gói chọn xong khi Activity (tạo lại) còn đang chuẩn bị payload: nhập sau afterPayload */
  private Uri pendingHd;
  /** đã qua afterPayload (payload sẵn sàng, RemasterImport.recover đã chạy) */
  private boolean payloadReady;

  @Override
  protected void onCreate(final Bundle state) {
    super.onCreate(state);
    final LinearLayout box = new LinearLayout(this);
    box.setOrientation(LinearLayout.VERTICAL);
    box.setGravity(Gravity.CENTER_HORIZONTAL);
    final int pad = (int)(24 * this.getResources().getDisplayMetrics().density);
    box.setPadding(pad, pad, pad, pad);
    box.setBackgroundColor(Color.rgb(24, 18, 14));

    final TextView title = new TextView(this);
    title.setText(R.string.app_name);
    title.setTextSize(24);
    title.setTextColor(Color.rgb(240, 200, 120));
    title.setGravity(Gravity.CENTER);
    box.addView(title);

    this.status = new TextView(this);
    this.status.setTextSize(16);
    this.status.setTextColor(Color.WHITE);
    this.status.setPadding(0, pad, 0, pad);
    box.addView(this.status);

    this.progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
    this.progress.setMax(1000);
    this.progress.setVisibility(View.GONE);
    box.addView(this.progress, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));

    this.pick = new Button(this);
    this.pick.setText(R.string.pick_discs);
    this.pick.setOnClickListener(v -> {
      this.cancelAutoLaunch();
      this.pickDiscs();
    });
    box.addView(this.pick);

    this.play = new Button(this);
    this.play.setText(R.string.play);
    this.play.setOnClickListener(v -> {
      this.cancelAutoLaunch();
      this.launchGame();
    });
    box.addView(this.play);

    this.importHd = new Button(this);
    this.importHd.setText(R.string.hd_import);
    this.importHd.setOnClickListener(v -> {
      this.cancelAutoLaunch();
      this.pickHd();
    });
    box.addView(this.importHd);

    this.toggleHd = new Button(this);
    this.toggleHd.setText(R.string.hd_off);
    this.toggleHd.setOnClickListener(v -> {
      this.cancelAutoLaunch();
      this.toggleHd();
    });
    box.addView(this.toggleHd);

    final ScrollView scroll = new ScrollView(this);
    scroll.setBackgroundColor(Color.rgb(24, 18, 14));
    scroll.addView(box);
    this.setContentView(scroll);

    this.pick.setEnabled(false);
    this.play.setEnabled(false);
    this.importHd.setEnabled(false);
    this.toggleHd.setEnabled(false);
    this.busy = true;
    this.status.setText(R.string.preparing);
    new Thread(this::prepare, "Payload").start();
  }

  @Override
  protected void onStart() {
    super.onStart();
    this.started = true;
  }

  @Override
  protected void onStop() {
    super.onStop();
    this.started = false;
    this.cancelAutoLaunch(); // rời màn hình (mở app khác…) thì không tự vào game sau lưng người chơi
  }

  @Override
  protected void onDestroy() {
    this.ui.removeCallbacks(this.tickTask);
    super.onDestroy();
  }

  private void prepare() {
    try {
      Payload.ensure(this, (done, total) -> this.runOnUiThread(() -> {
        this.progress.setVisibility(View.VISIBLE);
        this.progress.setProgress((int)(1000L * done / Math.max(1, total)));
        this.status.setText(this.getString(R.string.extracting, (int)(100L * done / Math.max(1, total))));
      }));
      RemasterImport.recover(this);
      this.runOnUiThread(this::afterPayload);
    } catch(final Throwable t) {
      this.runOnUiThread(() -> this.status.setText(this.getString(R.string.extract_failed, String.valueOf(t))));
    }
  }

  private void afterPayload() {
    this.payloadReady = true;
    this.progress.setVisibility(View.GONE);
    this.setBusy(false);
    if(this.savedDiscs().size() == 4) {
      this.status.setText(R.string.ready);
      // rời màn hình trong lúc giải nén payload (onStop đã qua) thì không đếm ngược: không ai huỷ được nữa;
      // không tự vào game khi còn gói chờ nhập hay đang nhập dở (Activity tạo lại giữa lúc nhập)
      if(!this.getIntent().getBooleanExtra("setup", false) && this.started && this.pendingHd == null && !RemasterImport.running()) {
        this.countdown = AUTO_LAUNCH_SECONDS;
        this.tick();
      }
    } else {
      this.status.setText(R.string.need_discs);
    }
    if(this.pendingHd != null) {
      final Uri uri = this.pendingHd;
      this.pendingHd = null;
      this.startImport(uri, new RemasterImport.Limits());
      return;
    }
    this.debugImport();
  }

  /** Đếm ngược rồi tự vào game (như trước, chỉ trễ vài giây để người chơi kịp mở nút đĩa / mô hình HD) */
  private void tick() {
    if(this.countdown < 0) {
      return;
    }
    if(this.countdown == 0) {
      this.countdown = -1;
      this.launchGame();
      return;
    }
    this.status.setText(this.getString(R.string.auto_launch, this.countdown));
    this.countdown--;
    this.ui.postDelayed(this.tickTask, 1000);
  }

  private void cancelAutoLaunch() {
    if(this.countdown >= 0) {
      this.countdown = -1;
      this.ui.removeCallbacks(this.tickTask);
      this.status.setText(R.string.ready);
    }
  }

  // ---------------------------------------------------------------- mô hình HD

  private void refreshHd() {
    final boolean on = RemasterImport.isEnabled(this);
    this.toggleHd.setText(on ? R.string.hd_on : R.string.hd_off);
    // chưa nhập gói thì chỉ cho tắt (nếu đang bật), không cho bật; đang nhập thì khoá (setEnabled chờ khoá của luồng nhập)
    this.toggleHd.setEnabled(!this.busy && !RemasterImport.running() && (on || RemasterImport.hasData(this)));
  }

  private void toggleHd() {
    if(this.busy || RemasterImport.running()) {
      return;
    }
    try {
      RemasterImport.setEnabled(this, !RemasterImport.isEnabled(this));
    } catch(final IOException ex) {
      this.status.setText(this.getString(R.string.hd_failed, String.valueOf(ex)));
    }
    this.refreshHd();
  }

  private void pickHd() {
    final Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
    intent.addCategory(Intent.CATEGORY_OPENABLE);
    intent.setType("application/zip");
    intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[] {"application/zip", "application/x-zip-compressed", "application/x-zip"});
    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
    this.startActivityForResult(intent, PICK_HD);
  }

  private void setBusy(final boolean b) {
    this.busy = b;
    final boolean idle = !b && !RemasterImport.running();
    this.pick.setEnabled(idle);
    this.importHd.setEnabled(idle);
    this.play.setEnabled(idle && this.savedDiscs().size() == 4);
    this.refreshHd();
  }

  /** Giải nén + kiểm trên luồng riêng; tiến độ trên ProgressBar sẵn có; kết quả ở dòng trạng thái và log (tag LodscHd) */
  private void startImport(final Uri uri, final RemasterImport.Limits limits) {
    this.cancelAutoLaunch();
    this.setBusy(true);
    this.progress.setIndeterminate(false);
    this.progress.setProgress(0);
    this.progress.setVisibility(View.VISIBLE);
    this.status.setText(this.getString(R.string.hd_importing, 0));
    new Thread(() -> {
      String message;
      String result;
      try {
        final int models = RemasterImport.importZip(this, uri, limits, (done, total) -> this.runOnUiThread(() -> {
          if(total > 0) {
            this.progress.setIndeterminate(false);
            this.progress.setProgress((int)Math.min(1000L, 1000L * done / total));
            this.status.setText(this.getString(R.string.hd_importing, (int)Math.min(100L, 100L * done / total)));
          } else {
            this.progress.setIndeterminate(true);
            this.status.setText(this.getString(R.string.hd_importing_mb, (int)(done >> 20)));
          }
        }));
        message = this.getString(R.string.hd_ok, models);
        result = "result ok models=" + models;
      } catch(final RemasterImport.Failure f) {
        message = f.getMessage();
        result = "result fail code=" + f.code;
      } catch(final Throwable t) {
        Log.w(RemasterImport.TAG, "import", t);
        message = this.getString(R.string.hd_failed, String.valueOf(t));
        result = "result fail code=io";
      }
      final String m = message;
      final String r = result;
      this.runOnUiThread(() -> {
        this.progress.setIndeterminate(false);
        this.progress.setVisibility(View.GONE);
        this.status.setText(m);
        this.setBusy(false);
        Log.i(RemasterImport.TAG, r);
      });
    }, "RemasterImport").start();
  }

  /** Chỉ bản debuggable: nhập thẳng một tệp trong filesDir (android/test/remaster_import.ps1) */
  private void debugImport() {
    final Intent in = this.getIntent();
    final String path = in.getStringExtra("hd_test_zip");
    if(path == null || (this.getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) == 0) {
      return;
    }
    in.removeExtra("hd_test_zip");
    final File f = path.startsWith("/") ? new File(path) : new File(this.getFilesDir(), path);
    final RemasterImport.Limits limits = new RemasterImport.Limits();
    limits.entryCap = in.getLongExtra("hd_test_entry_cap", limits.entryCap);
    limits.totalCap = in.getLongExtra("hd_test_total_cap", limits.totalCap);
    limits.reserve = in.getLongExtra("hd_test_reserve", 0);
    this.startImport(Uri.fromFile(f), limits);
  }

  private List<Uri> savedDiscs() {
    final SharedPreferences prefs = this.getSharedPreferences(PREFS, MODE_PRIVATE);
    final List<Uri> out = new ArrayList<>();
    final List<UriPermission> granted = this.getContentResolver().getPersistedUriPermissions();
    for(int i = 0; i < 4; i++) {
      final String s = prefs.getString("disc" + i, null);
      if(s == null) {
        break;
      }
      final Uri uri = Uri.parse(s);
      boolean ok = false;
      for(final UriPermission p : granted) {
        if(p.getUri().equals(uri) && p.isReadPermission()) {
          ok = true;
        }
      }
      if(!ok) {
        break;
      }
      out.add(uri);
    }
    return out;
  }

  private void pickDiscs() {
    final Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
    intent.addCategory(Intent.CATEGORY_OPENABLE);
    intent.setType("*/*");
    intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
    this.startActivityForResult(intent, PICK_DISCS);
  }

  @Override
  protected void onActivityResult(final int requestCode, final int resultCode, final Intent data) {
    super.onActivityResult(requestCode, resultCode, data);
    if(requestCode == PICK_HD) {
      if(resultCode == RESULT_OK && data != null && data.getData() != null) {
        if(!this.payloadReady) {
          this.pendingHd = data.getData();   // Activity tạo lại, payload chưa xong: afterPayload nhập sau
        } else {
          this.startImport(data.getData(), new RemasterImport.Limits());
        }
      }
      return;
    }
    if(requestCode != PICK_DISCS || resultCode != RESULT_OK || data == null) {
      return;
    }

    final List<Uri> uris = new ArrayList<>();
    final ClipData clip = data.getClipData();
    if(clip != null) {
      for(int i = 0; i < clip.getItemCount(); i++) {
        uris.add(clip.getItemAt(i).getUri());
      }
    } else if(data.getData() != null) {
      uris.add(data.getData());
    }

    if(uris.size() != 4) {
      this.status.setText(this.getString(R.string.need_four, uris.size()));
      return;
    }

    final StringBuilder problems = new StringBuilder();
    for(final Uri uri : uris) {
      this.getContentResolver().takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION);
      final String problem = checkDisc(uri);
      if(problem != null) {
        problems.append(uri.getLastPathSegment()).append(": ").append(problem).append('\n');
      }
    }

    if(problems.length() > 0) {
      this.status.setText(this.getString(R.string.bad_discs, problems.toString()));
      return;
    }

    final SharedPreferences.Editor e = this.getSharedPreferences(PREFS, MODE_PRIVATE).edit();
    for(int i = 0; i < 4; i++) {
      e.putString("disc" + i, uris.get(i).toString());
    }
    e.apply();
    this.status.setText(R.string.ready);
    this.play.setEnabled(true);
  }

  /** null = trông giống ảnh đĩa CD BIN 2352 byte/sector (khối mô tả ISO9660 "CD001" ở sector 16); SC tự kiểm số đĩa/bản */
  private String checkDisc(final Uri uri) {
    try(ParcelFileDescriptor pfd = this.getContentResolver().openFileDescriptor(uri, "r")) {
      if(pfd == null) {
        return this.getString(R.string.cannot_open);
      }
      if(pfd.getStatSize() < 100L * 1024 * 1024) {
        return this.getString(R.string.too_small);
      }
      final byte[] b = new byte[8];
      try(FileInputStream in = new FileInputStream(pfd.getFileDescriptor())) {
        in.getChannel().position(16L * 2352 + 24);
        if(in.read(b) != b.length || b[1] != 'C' || b[2] != 'D' || b[3] != '0' || b[4] != '0' || b[5] != '1') {
          return this.getString(R.string.not_bin);
        }
      }
      return null;
    } catch(final IOException | SecurityException ex) {
      return String.valueOf(ex.getMessage());
    }
  }

  private void launchGame() {
    final List<Uri> discs = this.savedDiscs();
    if(discs.size() != 4) {
      this.status.setText(R.string.need_discs);
      return;
    }

    try {
      final File isos = new File(Payload.gameDir(this), "isos");
      if(!isos.isDirectory() && !isos.mkdirs()) {
        throw new IOException("mkdir " + isos);
      }
      final File[] old = isos.listFiles();
      if(old != null) {
        for(final File f : old) {
          if(f.getName().startsWith("disc") && !f.delete()) {
            throw new IOException("delete " + f);
          }
        }
      }
      for(final ParcelFileDescriptor p : OPEN_DISCS) {
        p.close();
      }
      OPEN_DISCS.clear();
      for(int i = 0; i < 4; i++) {
        final ParcelFileDescriptor pfd = this.getContentResolver().openFileDescriptor(discs.get(i), "r");
        if(pfd == null) {
          throw new IOException(this.getString(R.string.cannot_open));
        }
        OPEN_DISCS.add(pfd);
        Os.symlink("/proc/self/fd/" + pfd.getFd(), new File(isos, "disc" + (i + 1) + ".bin").getPath());
      }
    } catch(final Exception ex) {
      this.status.setText(this.getString(R.string.launch_failed, String.valueOf(ex)));
      return;
    }

    this.startActivity(new Intent(this, VnGameActivity.class));
    this.finish();
  }
}
