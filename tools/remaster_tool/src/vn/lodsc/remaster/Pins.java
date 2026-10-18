package vn.lodsc.remaster;

import com.google.gson.JsonParseException;

import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * pins.json — phiên bản ghim của công cụ ngoài (Blender, Real-ESRGAN): URL chính thức, kích thước, SHA-256 của zip,
 * thư mục gốc trong zip, danh sách file được giải nén (null = tất cả), SHA-256 từng file, lệnh kiểm tra.
 * Mặc định đọc vi/remaster/pins.json (cạnh jar); --pins để thay (kiểm thử). Nội dung được kiểm chặt khi nạp: URL https
 * (http chỉ cho máy cục bộ khi kiểm thử), hex SHA-256 64 ký tự, tên file/thư mục không có "..", "/" đầu hay ổ đĩa.
 */
final class Pins {
    static final Pattern HEX64 = Pattern.compile("^[0-9a-f]{64}$");
    static final Pattern SAFE_REL = Pattern.compile("^(?!/)(?![A-Za-z]:)(?!.*(^|/)\\.\\.?(/|$))[A-Za-z0-9._ /+-]+$");
    static final Pattern SAFE_NAME = Pattern.compile("^[A-Za-z0-9._+-]+$");

    /** Một công cụ ghim. Tên trường giữ đúng khoá JSON. */
    static final class Tool {
        String id;
        String name;
        String version;
        String url;
        String file;
        long size;
        String sha256;
        String sha256_source;
        String github_api;
        String root;
        String dir;
        List<String> extract;
        Map<String, String> file_sha256;
        String exe;
        String python;
        List<String> verify;
        String expect;
        String selftest_model;
        long installed_size;
        boolean required;
        String license;
        String home;
        String host_label;

        boolean isBlender() {
            return "blender".equals(id);
        }

        boolean isEsrgan() {
            return "realesrgan".equals(id);
        }

        String rootPrefix() {
            return root == null || root.isEmpty() ? "" : root + "/";
        }
    }

    int format;
    List<Tool> tools;
    transient Path source;

    Tool get(String id) {
        for (Tool t : tools) {
            if (t.id.equals(id)) {
                return t;
            }
        }
        throw new IllegalArgumentException("pins.json thiếu công cụ " + id);
    }

    Tool blender() {
        return get("blender");
    }

    Tool esrgan() {
        return get("realesrgan");
    }

    /** Tìm pins.json: tham số --pins, rồi cạnh jar, rồi vi/remaster/ của game, rồi tools/remaster_tool/ (chạy dev). */
    static Path locate(Layout g, Path override) {
        if (override != null) {
            return override;
        }
        Path jarDir = vn.lodsc.remaster.Tool.jarDir();
        if (jarDir != null && Files.isRegularFile(jarDir.resolve("pins.json"))) {
            return jarDir.resolve("pins.json");
        }
        Path p = g.viRemaster().resolve("pins.json");
        if (Files.isRegularFile(p)) {
            return p;
        }
        return Path.of("tools", "remaster_tool", "pins.json");
    }

    static Pins load(Path p) throws IOException {
        Pins pins;
        try {
            pins = Util.GSON.fromJson(Files.readString(p, StandardCharsets.UTF_8), Pins.class);
        } catch (JsonParseException e) {
            throw new IOException("pins.json hỏng: " + Util.msg(e));
        }
        if (pins == null || pins.format != 1 || pins.tools == null) {
            throw new IOException("pins.json sai định dạng (cần format 1): " + p);
        }
        pins.source = p;
        for (Tool t : pins.tools) {
            validate(t);
        }
        pins.blender();
        pins.esrgan();
        return pins;
    }

    private static void need(boolean ok, Tool t, String what) throws IOException {
        if (!ok) {
            throw new IOException("pins.json: " + (t.id == null ? "?" : t.id) + ": " + what);
        }
    }

    static void validate(Tool t) throws IOException {
        need(t.id != null && (t.id.equals("blender") || t.id.equals("realesrgan")), t, "id phải là blender hoặc realesrgan");
        need(t.name != null && t.version != null, t, "thiếu name/version");
        need(t.url != null, t, "thiếu url");
        URI u;
        try {
            u = URI.create(t.url);
        } catch (IllegalArgumentException e) {
            throw new IOException("pins.json: url sai: " + t.url);
        }
        need("https".equals(u.getScheme()) || ("http".equals(u.getScheme()) && Downloader.testHost(u.getHost())), t,
                "url phải là https");
        need(t.file != null && SAFE_NAME.matcher(t.file).matches() && t.file.endsWith(".zip"), t, "file phải là tên .zip");
        need(t.size > 0, t, "size phải > 0");
        need(t.sha256 != null && HEX64.matcher(t.sha256).matches(), t, "sha256 phải là 64 ký tự hex thường");
        need(t.root != null && (t.root.isEmpty() || SAFE_NAME.matcher(t.root).matches()), t, "root sai");
        need(t.dir != null && SAFE_NAME.matcher(t.dir).matches(), t, "dir sai");
        need(t.exe != null && SAFE_REL.matcher(t.exe).matches(), t, "exe sai");
        if (t.isBlender()) {
            need(t.python != null && SAFE_REL.matcher(t.python).matches(), t, "python sai");
            need(t.verify != null && t.expect != null, t, "thiếu verify/expect");
        }
        if (t.isEsrgan()) {
            need(t.extract != null && !t.extract.isEmpty(), t, "Real-ESRGAN cần danh sách extract (chỉ giải nén file cần)");
            need(t.extract.contains(t.exe), t, "extract phải chứa exe");
            need(t.selftest_model != null && SAFE_NAME.matcher(t.selftest_model).matches(), t, "thiếu selftest_model");
        }
        if (t.extract != null) {
            for (String e : t.extract) {
                need(SAFE_REL.matcher(e).matches(), t, "mục extract sai: " + e);
            }
        }
        if (t.file_sha256 != null) {
            for (Map.Entry<String, String> e : t.file_sha256.entrySet()) {
                need(SAFE_REL.matcher(e.getKey()).matches(), t, "file_sha256: tên sai " + e.getKey());
                need(e.getValue() != null && HEX64.matcher(e.getValue()).matches(), t, "file_sha256: hash sai " + e.getKey());
                need(t.extract == null || t.extract.contains(e.getKey()), t, "file_sha256 ngoài extract: " + e.getKey());
            }
        }
        if (t.host_label == null) {
            t.host_label = u.getHost();
        }
    }
}
