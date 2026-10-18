package vn.lodsc.remaster;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Consumer;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * "Xuất gói Android": gọi worker export-android --out remaster_export/LoD-SC-VN-MoHinhHD-&lt;thời điểm&gt;.zip (bộ
 * "mobile" L1 + atlas 2x, worker quyết định nội dung), rồi kiểm zip đúng như app Android sẽ kiểm khi nhập
 * (vn.lodsc.RemasterImport): chỉ các mục remaster/index.tsv, remaster/manifest.json,
 * remaster/models/&lt;40 hex&gt;.lrm, remaster/textures/&lt;40 hex&gt;.png, DOC_TRUOC.txt (và mục thư mục của chúng);
 * không "..", không trùng tên; tối đa 4096 mục; index.tsv, manifest.json &lt;= 4 MB (app đọc hết vào bộ nhớ),
 * DOC_TRUOC.txt &lt;= 1 MB, mục khác &lt;= 64 MB,
 * tổng &lt;= 1 GB; index.tsv đúng §3.7 (UTF-8 hợp lệ, khoá không trùng); mọi .lrm được chỉ mục có trong zip với header
 * LRM1 v1 đúng khoá; mọi PNG có SHA-1 = tên, chữ ký PNG và IHDR luỹ thừa 2 &lt;= 2048. Zip sai → bị xoá. Gói chỉ để
 * dùng riêng, không chia sẻ.
 */
final class AndroidExport {
    static final Pattern ALLOWED = Pattern.compile(
            "^(remaster/(index\\.tsv|manifest\\.json|models/[0-9a-f]{40}\\.lrm|textures/[0-9a-f]{40}\\.png)|DOC_TRUOC\\.txt)$");
    static final Set<String> DIRS = Set.of("remaster/", "remaster/models/", "remaster/textures/");
    static final String NOTE = "DOC_TRUOC.txt";
    static final long MAX_ENTRY = 64L << 20;
    static final long MAX_INDEX = 4L << 20;
    static final long MAX_NOTE = 1L << 20;
    static final long MAX_TOTAL = 1L << 30;
    static final int MAX_ENTRIES = 4096;

    record Report(int models, int textures, long bytes) {
    }

    private AndroidExport() {
    }

    static Path defaultOut(Layout g) {
        return g.export().resolve("LoD-SC-VN-MoHinhHD-"
                + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd-HHmm")) + ".zip");
    }

    /** Tạo Runner cho export-android (người gọi chạy runner.run() rồi validate). */
    static Runner runner(Layout g, Pins pins, Path out, Runner.Listener l) throws IOException {
        Files.createDirectories(out.getParent());
        List<String> cmd = Runner.workerCommand(g, pins, "export-android", List.of("--out", out.toString()));
        return new Runner(cmd, g.game(), Runner.newLogFile(g, "android"), l);
    }

    /** Chạy xuất + kiểm. Trả báo cáo; lỗi → IOException (zip sai đã bị xoá). */
    static Report export(Layout g, Pins pins, Path out, Runner.Listener l, Consumer<Runner> started) throws IOException {
        Files.deleteIfExists(out);
        Runner r = runner(g, pins, out, l);
        if (started != null) {
            started.accept(r);
        }
        Runner.Result res = r.run();
        if (res.outcome() == Runner.Outcome.CANCELED) {
            Files.deleteIfExists(out);
            throw new IOException("Đã huỷ xuất gói.");
        }
        if (res.outcome() != Runner.Outcome.DONE || !Files.isRegularFile(out)) {
            Files.deleteIfExists(out);
            throw new IOException("worker export-android lỗi (mã " + res.exit() + "), xem log " + res.log());
        }
        try {
            return validate(out);
        } catch (IOException e) {
            Files.deleteIfExists(out);
            throw new IOException("Gói Android không hợp lệ, đã xoá: " + Util.msg(e));
        }
    }

    static Report validate(Path zip) throws IOException {
        Set<String> seen = new HashSet<>();
        Map<String, byte[]> lrmHeads = new HashMap<>();
        byte[] index = null;
        byte[] manifest = null;
        int textures = 0;
        long total = 0;
        int entries = 0;
        try (ZipInputStream z = new ZipInputStream(new BufferedInputStream(Files.newInputStream(zip), 1 << 16))) {
            for (ZipEntry e; (e = z.getNextEntry()) != null; ) {
                String n = e.getName();
                if (++entries > MAX_ENTRIES) {
                    throw new IOException("gói có quá " + MAX_ENTRIES + " mục");
                }
                if (!seen.add(n)) {
                    throw new IOException("mục trùng tên: " + n);
                }
                if (e.isDirectory()) {
                    if (!DIRS.contains(n)) {
                        throw new IOException("thư mục lạ trong gói: " + n);
                    }
                    continue;
                }
                if (!ALLOWED.matcher(n).matches()) {
                    throw new IOException("mục không được phép trong gói: " + n);
                }
                MessageDigest sha1 = Util.md("SHA-1");
                ByteArrayOutputStream keep = new ByteArrayOutputStream();
                boolean keepAll = n.equals("remaster/index.tsv") || n.equals("remaster/manifest.json");
                long cap = n.equals(NOTE) ? MAX_NOTE : keepAll ? MAX_INDEX : MAX_ENTRY;
                long size = 0;
                byte[] buf = new byte[1 << 16];
                for (int k; (k = z.read(buf)) > 0; ) {
                    size += k;
                    total += k;
                    if (size > cap || total > MAX_TOTAL) {
                        throw new IOException("gói quá lớn (index.tsv, manifest.json <= 4 MB, DOC_TRUOC.txt <= 1 MB, mỗi mục khác"
                                + " <= 64 MB, tổng <= 1 GB): " + n);
                    }
                    sha1.update(buf, 0, k);
                    if (keepAll || keep.size() < 0x40) {
                        keep.write(buf, 0, k);
                    }
                }
                if (n.equals("remaster/index.tsv")) {
                    index = keep.toByteArray();
                } else if (n.equals("remaster/manifest.json")) {
                    manifest = keep.toByteArray();
                } else if (n.startsWith("remaster/models/")) {
                    String key = n.substring("remaster/models/".length(), n.length() - 4);
                    byte[] h = keep.toByteArray();
                    lrmHeads.put(key, h.length > 0x40 ? java.util.Arrays.copyOf(h, 0x40) : h);
                } else if (n.startsWith("remaster/textures/")) {
                    String stem = n.substring("remaster/textures/".length(), n.length() - 4);
                    if (!Util.hex(sha1.digest()).equals(stem)) {
                        throw new IOException("texture " + stem + " sai SHA-1");
                    }
                    RemasterData.checkPngHeader(keep.toByteArray(), stem + ".png");
                    textures++;
                }
            }
        }
        if (index == null) {
            throw new IOException("thiếu remaster/index.tsv");
        }
        if (manifest == null) {
            throw new IOException("thiếu remaster/manifest.json");
        }
        RemasterData.checkManifest(manifest);
        Map<String, String> labels = RemasterData.parseIndex(index);
        for (String key : labels.keySet()) {
            if (!lrmHeads.containsKey(key)) {
                throw new IOException("thiếu remaster/models/" + key + ".lrm");
            }
        }
        // như app: MỌI .lrm trong gói (kể cả không có trong index.tsv) phải đúng header
        for (Map.Entry<String, byte[]> e : lrmHeads.entrySet()) {
            RemasterData.checkLrmHeader(e.getValue(), e.getKey());
        }
        return new Report(labels.size(), textures, Files.size(zip));
    }
}
