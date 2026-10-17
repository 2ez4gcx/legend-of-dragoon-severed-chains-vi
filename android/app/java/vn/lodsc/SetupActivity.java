package vn.lodsc;

import android.app.Activity;
import android.content.ClipData;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.UriPermission;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.system.Os;
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
 */
public class SetupActivity extends Activity {
  private static final int PICK_DISCS = 1;
  private static final String PREFS = "discs";

  /** Tệp đĩa đang mở: giữ sống suốt tiến trình để đường dẫn /proc/self/fd/N còn dùng được */
  static final List<ParcelFileDescriptor> OPEN_DISCS = new ArrayList<>();

  private TextView status;
  private ProgressBar progress;
  private Button pick;
  private Button play;

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
    this.pick.setOnClickListener(v -> this.pickDiscs());
    box.addView(this.pick);

    this.play = new Button(this);
    this.play.setText(R.string.play);
    this.play.setOnClickListener(v -> this.launchGame());
    box.addView(this.play);

    final ScrollView scroll = new ScrollView(this);
    scroll.setBackgroundColor(Color.rgb(24, 18, 14));
    scroll.addView(box);
    this.setContentView(scroll);

    this.pick.setEnabled(false);
    this.play.setEnabled(false);
    this.status.setText(R.string.preparing);
    new Thread(this::prepare, "Payload").start();
  }

  private void prepare() {
    try {
      Payload.ensure(this, (done, total) -> this.runOnUiThread(() -> {
        this.progress.setVisibility(View.VISIBLE);
        this.progress.setProgress((int)(1000L * done / Math.max(1, total)));
        this.status.setText(this.getString(R.string.extracting, (int)(100L * done / Math.max(1, total))));
      }));
      this.runOnUiThread(this::afterPayload);
    } catch(final Throwable t) {
      this.runOnUiThread(() -> this.status.setText(this.getString(R.string.extract_failed, String.valueOf(t))));
    }
  }

  private void afterPayload() {
    this.progress.setVisibility(View.GONE);
    this.pick.setEnabled(true);
    final List<Uri> discs = this.savedDiscs();
    if(discs.size() == 4) {
      this.status.setText(R.string.ready);
      this.play.setEnabled(true);
      if(!this.getIntent().getBooleanExtra("setup", false)) {
        this.launchGame();
      }
    } else {
      this.status.setText(R.string.need_discs);
    }
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
