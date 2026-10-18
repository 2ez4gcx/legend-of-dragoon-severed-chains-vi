package vn.lodsc.remaster;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.BasicFileAttributes;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Thư mục staging ASCII cho Real-ESRGAN (realesrgan-ncnn-vulkan 20220424 sập với đường dẫn không ASCII, kể cả khi chỉ
 * thư mục làm việc có dấu — mã 0xC0000409). Thứ tự ứng viên (chỉ nhận đường dẫn ASCII, ghi được):
 * <ol>
 *   <li>remaster_tools/realesrgan nếu đường dẫn tuyệt đối toàn ASCII (không cần chép);</li>
 *   <li>%PUBLIC%\LoD-SC-VN\realesrgan;</li>
 *   <li>&lt;ổ của game&gt;:\LoD-SC-VN-tools\realesrgan, rồi &lt;ổ hệ thống&gt;:\LoD-SC-VN-tools\realesrgan.</li>
 * </ol>
 * Kiểm thử thay 2–3 bằng -Dlodsc.remaster.staging=dir1;dir2. Ứng viên ngoài game được chép các file đã ghim (kiểm
 * SHA-256), bị xoá mọi mục lạ (thư mục %PUBLIC% ai cũng ghi được: chặn DLL cài sẵn cạnh exe) và có file đánh dấu
 * .lodsc-staging (đường dẫn game, UTF-8) để "Xoá công cụ" chỉ xoá thư mục do mình tạo; ứng viên mà chính nó hoặc thư
 * mục cha là symlink/junction bị bỏ qua (không bao giờ xoá "mục lạ" qua liên kết sang nơi khác). Trước mỗi lần chạy worker
 * ({@link #forRun}) thư mục được kiểm lại đủ file, đúng SHA-256, không mục lạ; sai thì chép lại + tự kiểm lại.
 * Tự kiểm: ảnh PNG 64x64 sinh ra → exe -i selftest\in.png -o selftest\out.png -m models -n &lt;model&gt; -s 4 -f png
 * (cwd = staging, đường dẫn tương đối), quá giờ thì diệt cả cây tiến trình, lỗi thì thử lại với -t 64; đạt khi mã 0
 * và out.png 256x256. Kết quả ghi remaster_tools/esrgan_staging.json {dir, ai_ok, detail, date}.
 */
final class Staging {
    static final String MARKER = ".lodsc-staging";

    record Result(Path dir, boolean aiOk, String detail) {
    }

    private Staging() {
    }

    static List<Path> candidates(Layout g, Pins.Tool t) {
        List<Path> c = new ArrayList<>();
        Path own = g.toolDir(t).toAbsolutePath();
        if (Util.isAscii(own.toString())) {
            c.add(own);
        }
        String prop = System.getProperty("lodsc.remaster.staging");
        if (prop != null) {
            for (String s : prop.split(";")) {
                if (!s.isBlank()) {
                    c.add(Path.of(s.trim()).toAbsolutePath());
                }
            }
        } else {
            String pub = System.getenv("PUBLIC");
            if (pub != null) {
                c.add(Path.of(pub, "LoD-SC-VN", "realesrgan"));
            }
            Path root = g.game().getRoot();
            if (root != null) {
                c.add(root.resolve("LoD-SC-VN-tools").resolve("realesrgan"));
            }
            String sys = System.getenv("SystemDrive");
            if (sys != null) {
                Path s = Path.of(sys + "\\", "LoD-SC-VN-tools", "realesrgan");
                if (!c.contains(s)) {
                    c.add(s);
                }
            }
        }
        c.removeIf(p -> !Util.isAscii(p.toString()));
        return c;
    }

    private static boolean insideGame(Layout g, Path p) {
        return p.toAbsolutePath().normalize().startsWith(g.game());
    }

    /**
     * Các mục lạ (không thuộc danh sách extract, không phải file đánh dấu) trong thư mục staging ngoài game — ví dụ DLL
     * do người dùng khác cài vào %PUBLIC% để exe nạp nhầm. Trả đường dẫn tương đối ('/').
     */
    static List<String> extras(Pins.Tool t, Path dir) throws IOException {
        Set<String> files = new HashSet<>(t.extract);
        files.add(MARKER);
        Set<String> dirs = new HashSet<>();
        for (String e : t.extract) {
            for (int i = e.indexOf('/'); i > 0; i = e.indexOf('/', i + 1)) {
                dirs.add(e.substring(0, i));
            }
        }
        List<String> out = new ArrayList<>();
        walkExtras(dir, "", files, dirs, out);
        return out;
    }

    private static void walkExtras(Path cur, String prefix, Set<String> files, Set<String> dirs, List<String> out)
            throws IOException {
        List<Path> kids = new ArrayList<>();
        try (DirectoryStream<Path> ds = Files.newDirectoryStream(cur)) {
            ds.forEach(kids::add);
        }
        for (Path k : kids) {
            String rel = prefix + k.getFileName().toString();
            BasicFileAttributes a = Files.readAttributes(k, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            if (a.isDirectory() && !a.isSymbolicLink() && !a.isOther() && dirs.contains(rel)) {
                walkExtras(k, rel + "/", files, dirs, out);
            } else if (!(a.isRegularFile() && files.contains(rel))) {
                out.add(rel);
            }
        }
    }

    /** SHA-256 mong đợi của một file Real-ESRGAN: pins.file_sha256, nếu không có thì hash ghi lúc cài (.installed.json). */
    private static String expected(Layout g, Pins.Tool t, String rel) {
        String want = t.file_sha256 != null ? t.file_sha256.get(rel) : null;
        if (want != null) {
            return want;
        }
        try {
            JsonObject o = JsonParser.parseString(Files.readString(Installer.installedJson(g, t), StandardCharsets.UTF_8))
                    .getAsJsonObject();
            JsonElement f = o.getAsJsonObject("files").get(rel);
            return f == null ? null : f.getAsString();
        } catch (IOException | RuntimeException e) {
            return null;
        }
    }

    /** Thư mục staging còn nguyên: đủ file, đúng SHA-256; ngoài game thì không có mục lạ. */
    static boolean intact(Layout g, Pins.Tool t, Path dir) {
        try {
            if (!insideGame(g, dir) && !extras(t, dir).isEmpty()) {
                return false;
            }
            for (String rel : t.extract) {
                Path f = dir.resolve(rel);
                String want = expected(g, t, rel);
                if (!Files.isRegularFile(f, LinkOption.NOFOLLOW_LINKS) || want == null || !Util.sha256(f).equals(want)) {
                    return false;
                }
            }
            return true;
        } catch (IOException | RuntimeException e) {
            return false;
        }
    }

    /**
     * Thư mục staging cho một lần chạy worker (--esrgan): kết quả đã lưu nếu tự kiểm đạt và thư mục còn nguyên
     * ({@link #intact}); thiếu / bị đổi → chép lại + tự kiểm lại; lần tự kiểm trước không đạt (không Vulkan, treo) →
     * null, không thử lại mỗi lần (nút "Tự kiểm AI lại" để thử lại). null = chạy --no-ai.
     */
    static Path forRun(Layout g, Pins pins, Installer.Listener l) throws IOException {
        if (!Installer.status(g, pins.esrgan()).ok()) {
            return null;
        }
        Result st = load(g, pins);
        if (st != null && !st.aiOk()) {
            return null;
        }
        if (st != null && intact(g, pins.esrgan(), st.dir())) {
            return st.dir();
        }
        l.log("Thư mục chạy Real-ESRGAN thiếu hoặc bị thay đổi — chép lại và tự kiểm …");
        st = prepare(g, pins, l);
        return st.aiOk() ? st.dir() : null;
    }

    /**
     * Thư mục staging ngoài game (và thư mục cha LoD-SC-VN…) không được là symlink/junction: %PUBLIC% ai cũng ghi được,
     * một junction cài sẵn "...\LoD-SC-VN\realesrgan → thư mục khác" sẽ khiến bước xoá mục lạ xoá dữ liệu ở nơi khác.
     */
    private static void refuseLinks(Path dir) throws IOException {
        for (Path p : new Path[]{dir.getParent(), dir}) {
            if (p != null && p.getFileName() != null && Files.exists(p, LinkOption.NOFOLLOW_LINKS) && Util.isLinkLike(p)) {
                throw new IOException(p + " là liên kết (symlink/junction) — không dùng làm thư mục chạy Real-ESRGAN");
            }
        }
    }

    /** Chép các file đã ghim từ remaster_tools/realesrgan sang dir (bỏ qua file đã đúng SHA-256), xoá mục lạ. */
    private static void populate(Layout g, Pins.Tool t, Path dir) throws IOException {
        Path src = g.toolDir(t);
        refuseLinks(dir);
        Files.createDirectories(dir);
        refuseLinks(dir);
        for (String rel : extras(t, dir)) {
            Util.deleteTree(dir.resolve(rel));
        }
        Files.writeString(dir.resolve(MARKER), g.game().toString(), StandardCharsets.UTF_8);
        for (String rel : t.extract) {
            Path s = src.resolve(rel);
            Path d = dir.resolve(rel);
            String want = t.file_sha256 != null ? t.file_sha256.get(rel) : null;
            if (want == null) {
                want = Util.sha256(s);
            }
            if (Files.isRegularFile(d) && Util.sha256(d).equals(want)) {
                continue;
            }
            Files.createDirectories(d.getParent());
            Files.copy(s, d, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            if (!Util.sha256(d).equals(want)) {
                throw new IOException("Chép " + rel + " sang " + dir + " bị sai SHA-256");
            }
        }
    }

    /** Tự kiểm exe trong dir (cwd = dir, đường dẫn tương đối). */
    static Util.ExecResult selftest(Pins.Tool t, Path dir) throws IOException {
        Path st = dir.resolve("selftest");
        Util.deleteTree(st);
        Files.createDirectories(st);
        BufferedImage img = new BufferedImage(64, 64, BufferedImage.TYPE_INT_RGB);
        for (int y = 0; y < 64; y++) {
            for (int x = 0; x < 64; x++) {
                int r = x * 4, gg = y * 4, b = ((x / 8 + y / 8) & 1) * 200;
                img.setRGB(x, y, (r << 16) | (gg << 8) | b);
            }
        }
        ImageIO.write(img, "png", st.resolve("in.png").toFile());
        long sec = Long.getLong("lodsc.remaster.selftestTimeout", 120);
        List<String> base = new ArrayList<>(List.of(dir.resolve(t.exe).toString(), "-i", "selftest\\in.png", "-o",
                "selftest\\out.png", "-m", "models", "-n", t.selftest_model, "-s", "4", "-f", "png"));
        Util.ExecResult r = null;
        try {
            for (int attempt = 0; attempt < 2; attempt++) {
                List<String> cmd = new ArrayList<>(base);
                if (attempt == 1) {
                    cmd.add("-t");
                    cmd.add("64");
                }
                Files.deleteIfExists(st.resolve("out.png"));
                r = Util.exec(cmd, dir, Duration.ofSeconds(sec), null);
                if (r.ok() && Files.isRegularFile(st.resolve("out.png"))) {
                    BufferedImage out = ImageIO.read(st.resolve("out.png").toFile());
                    if (out != null && out.getWidth() == 256 && out.getHeight() == 256) {
                        return r;
                    }
                    r = new Util.ExecResult(98, r.output() + "\n(ảnh ra không phải 256x256)", false);
                }
                if (r.timedOut()) {
                    break;
                }
            }
            return r;
        } finally {
            Util.deleteTree(st);
        }
    }

    /**
     * Chọn thư mục staging, chép file, tự kiểm. Không ứng viên nào dùng được → aiOk=false (worker chạy --no-ai).
     */
    static Result prepare(Layout g, Pins pins, Installer.Listener l) throws IOException {
        Pins.Tool t = pins.esrgan();
        Result res = null;
        StringBuilder why = new StringBuilder();
        for (Path cand : candidates(g, t)) {
            try {
                if (!insideGame(g, cand)) {
                    populate(g, t, cand);
                }
            } catch (IOException e) {
                why.append(cand).append(": ").append(Util.msg(e)).append("; ");
                l.log("Không dùng được thư mục " + cand + ": " + Util.msg(e));
                continue;
            }
            l.log("Tự kiểm Real-ESRGAN ở " + cand + " …");
            Util.ExecResult r = selftest(t, cand);
            if (r.ok()) {
                res = new Result(cand, true, "tự kiểm đạt");
            } else {
                String d = r.timedOut() ? "quá giờ khi tự kiểm (máy hai card đồ hoạ?)"
                        : "mã " + r.exit() + " — có thể máy không hỗ trợ Vulkan: " + Installer.tail(r.output(), 200);
                res = new Result(cand, false, d);
            }
            break;
        }
        if (res == null) {
            res = new Result(null, false, "không tìm được thư mục ASCII ghi được (" + why + ")");
        }
        Map<String, Object> o = new LinkedHashMap<>();
        o.put("dir", res.dir() == null ? null : res.dir().toString());
        o.put("ai_ok", res.aiOk());
        o.put("detail", res.detail());
        o.put("zip_sha256", t.sha256);
        o.put("date", Util.now());
        Util.writeJson(g.stagingInfo(), o);
        return res;
    }

    /** Kết quả đã lưu (null nếu chưa có / sai bản / thư mục hoặc exe không còn đúng). */
    static Result load(Layout g, Pins pins) {
        Pins.Tool t = pins.esrgan();
        try {
            if (!Files.isRegularFile(g.stagingInfo())) {
                return null;
            }
            JsonObject o = JsonParser.parseString(Files.readString(g.stagingInfo(), StandardCharsets.UTF_8)).getAsJsonObject();
            if (!t.sha256.equals(o.get("zip_sha256").getAsString()) || o.get("dir").isJsonNull()) {
                return null;
            }
            Path dir = Path.of(o.get("dir").getAsString());
            if (!Files.isRegularFile(dir.resolve(t.exe))) {
                return null;
            }
            String want = t.file_sha256 != null ? t.file_sha256.get(t.exe) : null;
            if (want != null && !insideGame(g, dir) && !Util.sha256(dir.resolve(t.exe)).equals(want)) {
                return null;
            }
            return new Result(dir, o.get("ai_ok").getAsBoolean(), o.get("detail").getAsString());
        } catch (IOException | RuntimeException e) {
            return null;
        }
    }

    /**
     * Đường dẫn trong file đánh dấu có chỉ đúng thư mục game này không. Windows không phân biệt hoa/thường ("D:\Games"
     * gõ thành "d:\games" khi chạy --game) → so bằng Path (WindowsPath.equals bỏ qua hoa/thường), rồi bằng đường dẫn
     * thật khi cả hai còn tồn tại.
     */
    static boolean sameDir(String owner, Path game) {
        try {
            Path o = Path.of(owner).toAbsolutePath().normalize();
            if (o.equals(game)) {
                return true;
            }
            return Files.exists(o) && o.toRealPath().equals(game.toRealPath());
        } catch (IOException | RuntimeException e) {
            return false;
        }
    }

    /** Xoá thư mục staging ngoài game nếu do game này tạo (file đánh dấu trùng đường dẫn game). Trả đường dẫn đã xoá. */
    static Path remove(Layout g, Pins pins) throws IOException {
        Path dir = null;
        if (Files.isRegularFile(g.stagingInfo())) {
            try {
                JsonObject o = JsonParser.parseString(Files.readString(g.stagingInfo(), StandardCharsets.UTF_8)).getAsJsonObject();
                if (!o.get("dir").isJsonNull()) {
                    dir = Path.of(o.get("dir").getAsString());
                }
            } catch (RuntimeException ignored) {
                dir = null;
            }
        }
        List<Path> check = new ArrayList<>();
        if (dir != null) {
            check.add(dir);
        }
        if (pins != null) {
            for (Path c : candidates(g, pins.esrgan())) {
                if (!check.contains(c)) {
                    check.add(c);
                }
            }
        }
        Path removed = null;
        for (Path d : check) {
            if (insideGame(g, d) || !Files.isRegularFile(d.resolve(MARKER))) {
                continue;
            }
            String owner = Files.readString(d.resolve(MARKER), StandardCharsets.UTF_8).strip();
            if (!sameDir(owner, g.game())) {
                continue;
            }
            Util.deleteTree(d);
            removed = d;
            Path parent = d.getParent();
            if (parent != null && parent.getFileName() != null
                    && parent.getFileName().toString().startsWith("LoD-SC-VN")) {
                boolean empty;
                try (var ds = Files.newDirectoryStream(parent)) {
                    empty = !ds.iterator().hasNext();
                }
                if (empty) {
                    Files.deleteIfExists(parent);
                }
            }
        }
        return removed;
    }
}
