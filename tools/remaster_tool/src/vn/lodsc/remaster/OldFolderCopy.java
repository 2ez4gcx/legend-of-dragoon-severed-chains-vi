package vn.lodsc.remaster;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.BasicFileAttributes;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.function.BooleanSupplier;
import java.util.function.Consumer;

/**
 * "Chép từ thư mục game cũ" (sau khi giải nén bản Việt hoá mới vào thư mục mới): chép rồi KIỂM LẠI hash ở nơi mới.
 * <ul>
 *   <li>remaster/ → remaster.import/ (kiểm index.tsv, header .lrm, SHA-1 từng PNG, manifest — {@link RemasterData}),
 *       đạt thì đổi chỗ nguyên tử: remaster → remaster.old, remaster.import → remaster, xoá remaster.old.</li>
 *   <li>remaster_tools/&lt;công cụ&gt;/ chỉ khi .installed.json của nơi cũ đúng bản ghim (zip_sha256 = pins.json) và
 *       verified; chép vào &lt;dir&gt;.tmp CHỈ các file ghi trong .installed.json (file lạ thêm vào sau không được chép),
 *       kiểm SHA-256 từng file (và pins.file_sha256), đạt thì thay thư mục. Real-ESRGAN: chọn + tự kiểm lại thư mục
 *       staging cho game mới.</li>
 *   <li>remaster.properties (trạng thái bật/tắt) khi đã chép được mô hình; ghi lại đúng 3 dòng chuẩn của {@link Toggle}.</li>
 * </ul>
 * Không chép remaster_work/ (bộ đệm; worker tạo lại) và remaster_export/.
 */
final class OldFolderCopy {
    record Result(boolean models, List<String> tools, List<String> problems) {
    }

    private OldFolderCopy() {
    }

    static void checkSource(Layout from, Layout to) throws IOException {
        Path a = from.game().toRealPath();
        Path b = to.game().toRealPath();
        if (a.equals(b)) {
            throw new IOException("Thư mục cũ trùng thư mục game hiện tại.");
        }
        if (a.startsWith(b) || b.startsWith(a)) {
            throw new IOException("Thư mục cũ và thư mục mới không được nằm trong nhau.");
        }
        if (!Files.isDirectory(from.remaster()) && !Files.isDirectory(from.tools())) {
            throw new IOException("Thư mục cũ không có remaster\\ hay remaster_tools\\ — chọn đúng thư mục game cũ"
                    + " (nơi có TAO_MO_HINH_HD.bat).");
        }
    }

    static Result copy(Layout from, Layout to, Pins pins, Consumer<String> log, BooleanSupplier cancelled) throws IOException {
        checkSource(from, to);
        List<String> tools = new ArrayList<>();
        List<String> problems = new ArrayList<>();
        boolean models = false;
        if (Files.isRegularFile(from.remaster().resolve("index.tsv"))) {
            Path imp = to.game().resolve("remaster.import");
            Util.deleteTree(imp);
            try {
                log.accept("Chép mô hình từ " + from.remaster() + " …");
                Util.copyTree(from.remaster(), imp, cancelled);
                log.accept("Kiểm lại hash mô hình và texture ở thư mục mới …");
                RemasterData.Summary s = RemasterData.check(imp);
                Path old = to.game().resolve("remaster.old");
                Util.deleteTree(old);
                if (Files.exists(to.remaster())) {
                    Files.move(to.remaster(), old);
                }
                Files.move(imp, to.remaster());
                Util.deleteTree(old);
                models = true;
                log.accept("Đã chép " + s.models() + " mô hình, " + s.textures() + " texture (" + Util.size(s.bytes()) + ").");
            } catch (IOException e) {
                Util.deleteTree(imp);
                problems.add("Mô hình: " + Util.msg(e));
                log.accept("Không chép được mô hình: " + Util.msg(e));
            }
            if (models && Files.isRegularFile(from.props())) {
                // chỉ lấy trạng thái bật/tắt + textures + log, ghi lại đúng 3 dòng chuẩn (không chép nguyên file lạ)
                Toggle.write(to, Toggle.read(from));
            }
        }
        for (Pins.Tool t : pins.tools) {
            Path src = from.toolDir(t);
            Path ij = src.resolve(".installed.json");
            if (!Files.isRegularFile(ij)) {
                continue;
            }
            try {
                JsonObject o = JsonParser.parseString(Files.readString(ij, StandardCharsets.UTF_8)).getAsJsonObject();
                if (!t.sha256.equals(o.get("zip_sha256").getAsString())) {
                    problems.add(t.name + ": thư mục cũ là bản khác (" + o.get("version").getAsString() + "), cần tải bản " + t.version);
                    continue;
                }
                if (!o.get("verified").getAsBoolean()) {
                    problems.add(t.name + ": bản ở thư mục cũ chưa kiểm xong, cần cài lại");
                    continue;
                }
                Path dst = to.toolDir(t);
                Path tmp = dst.resolveSibling(t.dir + ".tmp");
                Util.deleteTree(tmp);
                try {
                    log.accept("Chép và kiểm SHA-256 từng file của " + t.name + " …");
                    copyListed(t, src, tmp, o.getAsJsonObject("files"), cancelled);
                    o.addProperty("copied_from", from.game().toString());
                    o.addProperty("copied_date", Util.now());
                    Util.writeJson(tmp.resolve(".installed.json"), o);
                    Util.deleteTree(dst);
                    Files.move(tmp, dst);
                } catch (IOException | RuntimeException e) {
                    Util.deleteTree(tmp);
                    throw e;
                }
                tools.add(t.id);
                log.accept("Đã chép và kiểm " + t.name + ".");
            } catch (IOException | RuntimeException e) {
                problems.add(t.name + ": " + Util.msg(e));
                log.accept("Không chép được " + t.name + ": " + Util.msg(e));
            }
        }
        Installer.Listener il = new Installer.Listener() {
            @Override
            public void log(String msg) {
                log.accept(msg);
            }
        };
        if (tools.contains("realesrgan") && Installer.status(to, pins.esrgan()).ok()) {
            Staging.Result st = Staging.prepare(to, pins, il);
            log.accept(st.aiOk() ? "Real-ESRGAN chạy được ở " + st.dir() : "Real-ESRGAN không chạy được: " + st.detail());
        }
        if (tools.contains("blender")) {
            // file đã đúng hash; chạy lại blender --version + worker.py probe của bản Việt hoá MỚI ở chỗ mới
            log.accept("Kiểm lại Blender ở thư mục mới …");
            Installer.Status bs = Installer.recheck(to, pins, pins.blender(), il);
            if (!bs.ok()) {
                problems.add("Blender: " + bs.detail());
            }
        }
        return new Result(models, tools, problems);
    }

    /** Tên tương đối trong .installed.json "files" (đến từ thư mục cũ): chỉ nhận đường dẫn con an toàn. */
    static boolean safeRel(String name) {
        if (name == null || name.isEmpty() || name.startsWith("/") || name.indexOf('\\') >= 0 || name.indexOf(':') >= 0
                || name.indexOf('\0') >= 0) {
            return false;
        }
        for (String seg : name.split("/", -1)) {
            if (seg.isEmpty() || seg.equals(".") || seg.equals("..")) {
                return false;
            }
        }
        return true;
    }

    /**
     * Chép ĐÚNG các file ghi trong .installed.json "files" (không chép file lạ nằm thêm trong thư mục cũ, ví dụ DLL lạ
     * cạnh realesrgan-ncnn-vulkan.exe), băm SHA-256 trong lúc chép; mỗi file phải khớp hash đã ghi lúc cài và
     * pins.file_sha256 (nếu có); đủ exe / python / danh sách extract / file_sha256 của pins.json.
     */
    private static void copyListed(Pins.Tool t, Path src, Path tmp, JsonObject files, BooleanSupplier cancelled)
            throws IOException {
        if (files == null || files.isEmpty()) {
            throw new IOException(".installed.json không có danh sách file");
        }
        Path srcBase = src.toAbsolutePath().normalize();
        Path base = tmp.toAbsolutePath().normalize();
        Files.createDirectories(base);
        byte[] buf = new byte[1 << 16];
        for (Map.Entry<String, JsonElement> e : files.entrySet()) {
            if (cancelled != null && cancelled.getAsBoolean()) {
                throw new IOException("Đã huỷ.");
            }
            String rel = e.getKey();
            if (!safeRel(rel) || rel.equals(".installed.json")) {
                throw new IOException("tên file lạ trong .installed.json: " + rel);
            }
            Path s = srcBase.resolve(rel).normalize();
            Path d = base.resolve(rel).normalize();
            if (!s.startsWith(srcBase) || !d.startsWith(base)) {
                throw new IOException("tên file lạ trong .installed.json: " + rel);
            }
            String want = e.getValue().getAsString();
            String pin = t.file_sha256 != null ? t.file_sha256.get(rel) : null;
            if (pin != null && !pin.equals(want)) {
                throw new IOException("file " + rel + " không phải bản ghim");
            }
            BasicFileAttributes a;
            try {
                a = Files.readAttributes(s, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            } catch (IOException ex) {
                throw new IOException("thiếu file " + rel);
            }
            if (!a.isRegularFile()) {
                throw new IOException("file " + rel + " không phải file thường");
            }
            Files.createDirectories(d.getParent());
            MessageDigest md = Util.md("SHA-256");
            try (InputStream in = Files.newInputStream(s); OutputStream os = Files.newOutputStream(d)) {
                for (int n; (n = in.read(buf)) > 0; ) {
                    md.update(buf, 0, n);
                    os.write(buf, 0, n);
                }
            }
            if (!Util.hex(md.digest()).equals(want)) {
                throw new IOException("file " + rel + " sai SHA-256");
            }
        }
        List<String> need = new ArrayList<>();
        need.add(t.exe);
        if (t.isBlender()) {
            need.add(t.python);
        }
        if (t.extract != null) {
            need.addAll(t.extract);
        }
        if (t.file_sha256 != null) {
            need.addAll(t.file_sha256.keySet());
        }
        for (String k : need) {
            if (!files.has(k)) {
                throw new IOException("thiếu " + k);
            }
        }
    }
}
