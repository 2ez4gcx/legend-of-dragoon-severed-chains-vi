package vn.lodsc.remaster;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.BufferedInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * Cài công cụ từ zip đã kiểm SHA-256 (pins.json) vào remaster_tools/&lt;dir&gt;.
 * <ol>
 *   <li>Kiểm lại kích thước + SHA-256 của zip.</li>
 *   <li>ZipInputStream giải vào &lt;dir&gt;.tmp: bỏ thư mục gốc (pins.root), chặn zip-slip (tên tuyệt đối, ổ đĩa, "..",
 *       "\", đường dẫn chuẩn hoá ra ngoài thư mục đích → huỷ cả bản cài), chỉ giải các file trong danh sách
 *       pins.extract (Real-ESRGAN: exe, vcomp140.dll, bin/param của realesrgan-x4plus-anime và realesrgan-x4plus).
 *       Giới hạn tổng dung lượng giải nén (chống zip bom).</li>
 *   <li>Kiểm SHA-256 từng file theo pins.file_sha256; đổi tên &lt;dir&gt;.tmp → &lt;dir&gt;.</li>
 *   <li>Blender: chạy lệnh kiểm (blender -b --factory-startup --version, phải có "Blender 5.2.2") rồi
 *       "worker.py probe". Real-ESRGAN: chọn + tự kiểm thư mục staging ASCII ({@link Staging}).</li>
 *   <li>Ghi &lt;dir&gt;/.installed.json {tool, version, zip_sha256, files{tên: sha256}, verified, ...}; xoá zip
 *       (chỉ zip do công cụ tải, không xoá file người chơi tự chọn).</li>
 * </ol>
 * Kiểm tra thất bại → giữ zip để thử lại không phải tải lại; thư mục cài không có .installed.json verified=true thì coi
 * như chưa cài.
 */
final class Installer {
    enum State { MISSING, INSTALLED, UNVERIFIED, MISMATCH }

    record Status(State state, String detail) {
        boolean ok() {
            return state == State.INSTALLED;
        }
    }

    interface Listener {
        void log(String msg);

        default void progress(long done, long total) {
        }
    }

    /** Lỗi zip độc hại / sai cấu trúc: cả bản cài bị huỷ. */
    static final class BadZipException extends IOException {
        BadZipException(String msg) {
            super(msg);
        }
    }

    private Installer() {
    }

    static Path installedJson(Layout g, Pins.Tool t) {
        return g.toolDir(t).resolve(".installed.json");
    }

    static Status status(Layout g, Pins.Tool t) {
        Path dir = g.toolDir(t);
        if (!Files.isDirectory(dir)) {
            return new Status(State.MISSING, "Chưa có");
        }
        Path ij = installedJson(g, t);
        if (!Files.isRegularFile(ij)) {
            return new Status(State.UNVERIFIED, "Thư mục có nhưng chưa kiểm xong — hãy cài lại");
        }
        try {
            JsonObject o = JsonParser.parseString(Files.readString(ij, StandardCharsets.UTF_8)).getAsJsonObject();
            if (!t.sha256.equals(o.get("zip_sha256").getAsString())) {
                return new Status(State.MISMATCH, "Sai bản (không phải " + t.version + ") — hãy cài lại");
            }
            if (!o.get("verified").getAsBoolean()) {
                return new Status(State.UNVERIFIED, "Đã giải nén nhưng kiểm tra lỗi: "
                        + (o.has("error") ? o.get("error").getAsString() : "?"));
            }
            if (!Files.isRegularFile(dir.resolve(t.exe))) {
                return new Status(State.UNVERIFIED, "Thiếu " + t.exe + " — hãy cài lại");
            }
            return new Status(State.INSTALLED, "Đã cài và kiểm (" + t.version + ")");
        } catch (IOException | RuntimeException e) {
            return new Status(State.UNVERIFIED, ".installed.json hỏng — hãy cài lại");
        }
    }

    /** Đường dẫn trong zip → đường dẫn tương đối sau khi bỏ gốc; null = bỏ qua (mục thư mục gốc). */
    static String relName(Pins.Tool t, String name) throws BadZipException {
        if (name.isEmpty() || name.indexOf('\\') >= 0 || name.indexOf('\0') >= 0 || name.startsWith("/")
                || (name.length() >= 2 && name.charAt(1) == ':')) {
            throw new BadZipException("Mục zip bị từ chối (đường dẫn tuyệt đối hoặc ký tự lạ): " + name);
        }
        for (String seg : name.split("/", -1)) {
            if (seg.equals("..") || seg.equals(".")) {
                throw new BadZipException("Mục zip bị từ chối (zip-slip \"..\"): " + name);
            }
        }
        String root = t.rootPrefix();
        if (!root.isEmpty()) {
            if (name.equals(root)) {
                return null;
            }
            if (!name.startsWith(root)) {
                throw new BadZipException("Mục zip nằm ngoài thư mục gốc " + t.root + ": " + name);
            }
            name = name.substring(root.length());
        }
        return name.isEmpty() ? null : name;
    }

    /**
     * Giải zip vào tmp (thư mục rỗng mới tạo). Trả {tên tương đối: sha256} của các file đã giải.
     * Mọi mục (kể cả mục không được giải) đều qua kiểm zip-slip.
     */
    static Map<String, String> extract(Pins.Tool t, Path zip, Path tmp, Listener l) throws IOException {
        Path base = tmp.toAbsolutePath().normalize();
        Files.createDirectories(base);
        Path realBase = base.toRealPath();
        Map<String, String> files = new TreeMap<>();
        long cap = Math.max(t.installed_size, 1L << 20) + (t.installed_size / 10) + (64L << 20);
        long total = 0;
        int skipped = 0;
        long zipSize = Files.size(zip);
        try (CountingInput cin = new CountingInput(new BufferedInputStream(Files.newInputStream(zip), 1 << 16));
             ZipInputStream zin = new ZipInputStream(cin, StandardCharsets.UTF_8)) {
            for (ZipEntry e; (e = zin.getNextEntry()) != null; ) {
                String rel = relName(t, e.getName());
                if (rel == null) {
                    continue;
                }
                boolean dir = e.isDirectory() || rel.endsWith("/");
                String relFile = dir ? rel.substring(0, rel.length() - 1) : rel;
                Path out = base.resolve(relFile).normalize();
                if (!out.startsWith(base) || out.equals(base)) {
                    throw new BadZipException("Mục zip bị từ chối (ra ngoài thư mục đích): " + e.getName());
                }
                if (dir) {
                    if (t.extract == null) {
                        Files.createDirectories(out);
                        if (!out.toRealPath().startsWith(realBase)) {
                            throw new BadZipException("Mục zip bị từ chối (thư mục ra ngoài đích): " + e.getName());
                        }
                    }
                    continue;
                }
                if (t.extract != null && !t.extract.contains(relFile)) {
                    skipped++;
                    continue;
                }
                if (files.containsKey(relFile)) {
                    throw new BadZipException("Mục zip trùng tên: " + e.getName());
                }
                Files.createDirectories(out.getParent());
                Path realParent = out.getParent().toRealPath();
                if (!realParent.startsWith(realBase)) {
                    throw new BadZipException("Mục zip bị từ chối (thư mục cha ra ngoài đích): " + e.getName());
                }
                MessageDigest md = Util.md("SHA-256");
                try (OutputStream os = Files.newOutputStream(out)) {
                    byte[] buf = new byte[1 << 16];
                    for (int n; (n = zin.read(buf)) > 0; ) {
                        total += n;
                        if (total > cap) {
                            throw new BadZipException("Zip giải ra quá lớn (> " + Util.size(cap) + ")");
                        }
                        os.write(buf, 0, n);
                        md.update(buf, 0, n);
                    }
                }
                files.put(relFile, Util.hex(md.digest()));
                l.progress(cin.count, zipSize);
            }
        }
        if (skipped > 0) {
            l.log("Bỏ qua " + skipped + " file không cần trong zip (chỉ giải danh sách cho phép).");
        }
        return files;
    }

    /** Lệnh chạy một chương trình trong thư mục công cụ (.cmd/.bat được ProcessBuilder chạy qua cmd). */
    static List<String> command(Path exe, List<String> args) {
        List<String> c = new ArrayList<>();
        c.add(exe.toString());
        c.addAll(args);
        return c;
    }

    static Path blenderExe(Layout g, Pins pins) {
        return g.toolDir(pins.blender()).resolve(pins.blender().exe).toAbsolutePath();
    }

    static Path python(Layout g, Pins pins) {
        return g.toolDir(pins.blender()).resolve(pins.blender().python).toAbsolutePath();
    }

    /** Chạy blender --version (pins.verify), đầu ra phải chứa pins.expect. */
    static Util.ExecResult verifyBlender(Layout g, Pins pins) throws IOException {
        Pins.Tool t = pins.blender();
        long sec = Long.getLong("lodsc.remaster.verifyTimeout", 120);
        Util.ExecResult r = Util.exec(command(blenderExe(g, pins), t.verify), g.toolDir(t), Duration.ofSeconds(sec), null);
        if (r.ok() && !r.output().contains(t.expect)) {
            return new Util.ExecResult(99, r.output(), false);
        }
        return r;
    }

    /** worker.py probe --game &lt;g&gt; --blender &lt;exe&gt; bằng Python của Blender (-I). */
    static Util.ExecResult probe(Layout g, Pins pins) throws IOException {
        List<String> args = new ArrayList<>(List.of("--blender", blenderExe(g, pins).toString()));
        Staging.Result st = Staging.load(g, pins);
        if (st != null && st.aiOk()) {
            args.add("--esrgan");
            args.add(st.dir().toString());
        }
        long sec = Long.getLong("lodsc.remaster.verifyTimeout", 120);
        return Util.exec(Runner.workerCommand(g, pins, "probe", args), g.game(), Duration.ofSeconds(sec), null);
    }

    /**
     * Cài t từ zip (đã tải hoặc người chơi tự chọn). ownsZip = zip do công cụ tải về (xoá sau khi cài xong).
     */
    static Status install(Layout g, Pins pins, Pins.Tool t, Path zip, boolean ownsZip, Listener l) throws IOException {
        l.log("Kiểm SHA-256 của " + zip.getFileName() + " …");
        Downloader.checkManualZip(t, zip);
        Path dir = g.toolDir(t);
        Path tmp = dir.resolveSibling(t.dir + ".tmp");
        Util.deleteTree(tmp);
        Map<String, String> files;
        try {
            l.log("Giải nén " + t.name + " …");
            files = extract(t, zip, tmp, l);
            List<String> problems = new ArrayList<>();
            if (t.extract != null) {
                for (String e : t.extract) {
                    if (!files.containsKey(e)) {
                        problems.add("thiếu " + e);
                    }
                }
            }
            if (t.file_sha256 != null) {
                for (Map.Entry<String, String> e : t.file_sha256.entrySet()) {
                    String got = files.get(e.getKey());
                    if (got == null) {
                        problems.add("thiếu " + e.getKey());
                    } else if (!got.equals(e.getValue())) {
                        problems.add("SHA-256 sai: " + e.getKey());
                    }
                }
            }
            if (!files.containsKey(t.exe)) {
                problems.add("thiếu " + t.exe);
            }
            if (t.isBlender() && !files.containsKey(t.python)) {
                problems.add("thiếu " + t.python);
            }
            if (!problems.isEmpty()) {
                throw new BadZipException("Zip không đúng bản ghim: " + String.join("; ", problems));
            }
            Util.deleteTree(dir);
            Files.move(tmp, dir);
        } catch (IOException | RuntimeException e) {
            Util.deleteTree(tmp);
            throw e;
        }
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("tool", t.id);
        info.put("version", t.version);
        info.put("zip_sha256", t.sha256);
        info.put("zip_size", t.size);
        info.put("date", Util.now());
        info.put("verified", false);
        info.put("file_count", files.size());
        info.put("files", files);
        String error = null;
        if (t.isBlender()) {
            l.log("Chạy thử Blender (" + String.join(" ", t.verify) + ") …");
            Util.ExecResult r = verifyBlender(g, pins);
            info.put("verify_output", tail(r.output(), 400));
            if (!r.ok()) {
                error = r.timedOut() ? "Blender không phản hồi (quá giờ). Máy có thể thiếu SSE4.2 hoặc bị phần mềm diệt virus chặn."
                        : "Blender không chạy được (mã " + r.exit() + "): " + tail(r.output(), 300);
            } else if (Files.isRegularFile(g.worker())) {
                l.log("Kiểm môi trường Python của Blender (worker.py probe) …");
                Util.ExecResult p = probe(g, pins);
                info.put("probe_output", tail(p.output(), 2000));
                if (!p.ok()) {
                    error = "worker.py probe lỗi (mã " + p.exit() + "): " + tail(p.output(), 300);
                }
            } else {
                l.log("Chưa có " + g.worker() + " — bỏ qua bước probe.");
                info.put("probe_output", "bỏ qua: thiếu worker.py");
            }
        }
        if (error == null) {
            info.put("verified", true);
        } else {
            info.put("error", error);
        }
        Util.writeJson(installedJson(g, t), info);
        if (error != null) {
            l.log("LỖI: " + error);
            return new Status(State.UNVERIFIED, error);
        }
        if (t.isEsrgan()) {
            Staging.Result st = Staging.prepare(g, pins, l);
            l.log(st.aiOk() ? "Real-ESRGAN chạy được ở " + st.dir()
                    : "Real-ESRGAN không chạy được (" + st.detail() + ") — sẽ phóng to texture thường (không AI).");
        }
        if (ownsZip) {
            Files.deleteIfExists(zip);
        }
        l.log("Đã cài " + t.name + " " + t.version + ".");
        return status(g, t);
    }

    /** Chạy lại bước kiểm (Blender: --version + probe; Real-ESRGAN: staging + tự kiểm) mà không giải nén lại. */
    static Status recheck(Layout g, Pins pins, Pins.Tool t, Listener l) throws IOException {
        Path ij = installedJson(g, t);
        if (!Files.isRegularFile(ij)) {
            return status(g, t);
        }
        JsonObject o;
        try {
            o = JsonParser.parseString(Files.readString(ij, StandardCharsets.UTF_8)).getAsJsonObject();
            if (!t.sha256.equals(o.get("zip_sha256").getAsString()) || !o.get("files").isJsonObject()) {
                return status(g, t);
            }
        } catch (IOException | RuntimeException e) {
            // .installed.json hỏng (mất điện giữa chừng, sửa tay): không kiểm lại được — báo "cài lại" để người gọi
            // chuyển sang tải / chọn zip, không ném lỗi chặn đường cài lại
            l.log(".installed.json của " + t.name + " hỏng — cần cài lại.");
            return status(g, t);
        }
        String error = null;
        if (t.isBlender()) {
            Util.ExecResult r = verifyBlender(g, pins);
            if (!r.ok()) {
                error = "Blender không chạy được: " + tail(r.output(), 300);
            } else if (Files.isRegularFile(g.worker())) {
                Util.ExecResult p = probe(g, pins);
                if (!p.ok()) {
                    error = "worker.py probe lỗi: " + tail(p.output(), 300);
                }
            }
        } else {
            Staging.prepare(g, pins, l);
        }
        o.addProperty("verified", error == null);
        o.remove("error");
        if (error != null) {
            o.addProperty("error", error);
            l.log("LỖI: " + error);
        }
        Util.writeJson(ij, o);
        return status(g, t);
    }

    static String tail(String s, int n) {
        s = s.strip();
        return s.length() <= n ? s : "…" + s.substring(s.length() - n);
    }

    /** Đếm byte đã đọc của zip (tiến độ giải nén). */
    private static final class CountingInput extends java.io.FilterInputStream {
        long count;

        CountingInput(InputStream in) {
            super(in);
        }

        @Override
        public int read() throws IOException {
            int b = super.read();
            if (b >= 0) {
                count++;
            }
            return b;
        }

        @Override
        public int read(byte[] b, int off, int len) throws IOException {
            int n = super.read(b, off, len);
            if (n > 0) {
                count += n;
            }
            return n;
        }

        @Override
        public long skip(long n) throws IOException {
            long s = super.skip(n);
            count += s;
            return s;
        }
    }
}
