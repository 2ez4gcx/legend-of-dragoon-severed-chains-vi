package vn.lodsc;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;

/**
 * Nhập bản lưu (nút trong hộp ⚙ của tay cầm ảo): mở trình chọn tệp của Android, nhập tệp .zip bằng SaveTransfer, báo kết quả
 * rồi quay lại game. Là activity riêng vì VnGameActivity chạy singleInstance: activity con mở từ đó vào task khác và hệ thống
 * huỷ kết quả trả về (startActivityForResult nhận ngay RESULT_CANCELED).
 */
public class SaveImportActivity extends Activity {
  private static final int PICK_ZIP = 1;

  @Override
  protected void onCreate(final Bundle state) {
    super.onCreate(state);
    if(state == null) {
      final Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
      intent.addCategory(Intent.CATEGORY_OPENABLE);
      intent.setType("*/*");
      intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[] {"application/zip", "application/x-zip-compressed", "application/octet-stream"});
      this.startActivityForResult(intent, PICK_ZIP);
    }
  }

  @Override
  protected void onActivityResult(final int requestCode, final int resultCode, final Intent data) {
    super.onActivityResult(requestCode, resultCode, data);
    final Uri uri = resultCode == RESULT_OK && data != null ? data.getData() : null;
    if(requestCode != PICK_ZIP || uri == null) {
      this.backToGame();
      return;
    }

    new Thread(() -> {
      String msg;
      try {
        msg = SaveTransfer.importZip(this, uri);
      } catch(final Exception e) {
        msg = "Nhập bản lưu thất bại: " + e.getMessage();
      }
      final String text = msg;
      this.runOnUiThread(() -> new AlertDialog.Builder(this, android.R.style.Theme_DeviceDefault_Dialog_Alert)
        .setTitle("Nhập bản lưu")
        .setMessage(text)
        .setPositiveButton("OK", null)
        .setOnDismissListener(d -> this.backToGame())
        .show());
    }, "SaveImport").start();
  }

  private void backToGame() {
    if(VnGameActivity.isRunning()) {
      this.startActivity(new Intent(this, VnGameActivity.class));
    }
    this.finish();
  }
}
