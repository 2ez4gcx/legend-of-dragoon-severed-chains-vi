package vn.lodsc;

import android.content.Context;
import android.content.res.AssetFileDescriptor;

import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.FilterInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * Giải nén assets/payload.zip (JRE 25 + Severed Chains + bản Việt, dựng bởi android/make_apk.py) vào bộ nhớ riêng của app:
 * filesDir/jre, filesDir/game. Chỉ chạy khi assets/payload.version khác bản đã giải nén (lần đầu, sau khi cập nhật APK).
 * Giữ nguyên dữ liệu người chơi trong game/: files (tài nguyên SC đã giải nén từ đĩa), saves, config.dcnf, config.conf
 * (nếu đã có).
 */
final class Payload {
  private Payload() { }

  interface Progress {
    void update(long done, long total);
  }

  /** Thư mục/tệp chương trình trong game/ (xoá trước khi giải nén bản mới); mọi thứ khác là dữ liệu người chơi */
  private static final String[] PROGRAM = {"libs", "vi", "gfx", "lang", "patches", "log4j2.xml", "android-classpath.txt"};

  static File gameDir(final Context c) {
    return new File(c.getFilesDir(), "game");
  }

  static File jreDir(final Context c) {
    return new File(c.getFilesDir(), "jre");
  }

  static void ensure(final Context c, final Progress progress) throws IOException {
    final String version;
    try(InputStream in = c.getAssets().open("payload.version")) {
      final java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
      final byte[] b = new byte[256];
      int n;
      while((n = in.read(b)) > 0) {
        bo.write(b, 0, n);
      }
      version = new String(bo.toByteArray(), StandardCharsets.UTF_8).trim();
    }
    final File marker = new File(c.getFilesDir(), "payload.version");
    if(marker.isFile() && version.equals(new String(Files.readAllBytes(marker.toPath()), StandardCharsets.UTF_8).trim())) {
      return;
    }

    if(marker.exists() && !marker.delete()) {
      throw new IOException("delete " + marker);
    }
    deleteTree(jreDir(c));
    final File game = gameDir(c);
    for(final String p : PROGRAM) {
      deleteTree(new File(game, p));
    }
    final File[] top = game.listFiles((dir, name) -> name.endsWith(".jar"));
    if(top != null) {
      for(final File f : top) {
        deleteTree(f);
      }
    }

    final long total;
    try(AssetFileDescriptor afd = c.getAssets().openFd("payload.zip")) {
      total = afd.getLength();
    }
    final long[] done = {0};
    final File root = c.getFilesDir().getCanonicalFile();
    final byte[] buf = new byte[1 << 16];
    try(ZipInputStream zip = new ZipInputStream(new FilterInputStream(c.getAssets().open("payload.zip")) {
      private long last;

      @Override
      public int read(final byte[] b, final int off, final int len) throws IOException {
        final int n = super.read(b, off, len);
        if(n > 0) {
          done[0] += n;
          if(done[0] - this.last > (1 << 20)) {
            this.last = done[0];
            progress.update(done[0], total);
          }
        }
        return n;
      }
    })) {
      ZipEntry e;
      while((e = zip.getNextEntry()) != null) {
        final File out = new File(root, e.getName()).getCanonicalFile();
        if(!out.getPath().startsWith(root.getPath() + File.separator)) {
          throw new IOException("bad entry " + e.getName());
        }
        if(e.isDirectory()) {
          mkdirs(out);
          continue;
        }
        if((e.getName().equals("game/config.dcnf") || e.getName().equals("game/config.conf")) && out.isFile()) {
          continue; // giữ cài đặt của người chơi
        }
        mkdirs(out.getParentFile());
        try(OutputStream os = new BufferedOutputStream(new FileOutputStream(out), 1 << 16)) {
          int n;
          while((n = zip.read(buf)) > 0) {
            os.write(buf, 0, n);
          }
        }
      }
    }
    progress.update(total, total);
    Files.write(marker.toPath(), version.getBytes(StandardCharsets.UTF_8));
  }

  private static void mkdirs(final File d) throws IOException {
    if(!d.isDirectory() && !d.mkdirs()) {
      throw new IOException("mkdir " + d);
    }
  }

  private static void deleteTree(final File f) throws IOException {
    if(Files.isSymbolicLink(f.toPath())) {
      Files.delete(f.toPath());
      return;
    }
    final File[] kids = f.listFiles();
    if(kids != null) {
      for(final File k : kids) {
        deleteTree(k);
      }
    }
    if(f.exists() && !f.delete()) {
      throw new IOException("delete " + f);
    }
  }
}
