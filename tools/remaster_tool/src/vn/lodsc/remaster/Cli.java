package vn.lodsc.remaster;

import java.io.IOException;
import java.io.PrintStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Chế độ dòng lệnh (kiểm thử tự động, người dùng nâng cao). Cùng mã với giao diện.
 * <pre>
 * java -cp "vi/remaster/lodsc-remaster.jar;libs/gson-2.13.2.jar" vn.lodsc.remaster.Tool --cli [tuỳ chọn]
 *   --game &lt;dir&gt;            thư mục game (mặc định: thư mục hiện tại; đường dẫn có dấu: dùng "--game ." hoặc --args-file)
 *   --args-file &lt;f&gt;         đọc thêm tham số từ file UTF-8 (mỗi dòng một tham số)
 *   --pins &lt;f&gt;              pins.json khác (kiểm thử)
 *   --scope v1|v1+optional  --quality pc|mobile|both  --texture hd|ai|plain|retail (hd = ai)  --no-ai (= plain)
 *   --yes-download          ĐỒNG Ý tải Blender / Real-ESRGAN còn thiếu (không có cờ này thì không mở mạng)
 *   --blender-zip &lt;zip&gt;     --esrgan-zip &lt;zip&gt;   dùng zip đã tự tải (kiểm kích thước + SHA-256, không cần mạng)
 *   --install-only          chỉ tải/cài công cụ        --rebuild   worker clean rồi tạo lại từ đầu
 *   --enable                bật mô hình HD khi tạo xong (ghi remaster.properties)
 * Lệnh riêng (không chạy worker):
 *   --toggle on|off [--texture retail]   --export-android [--out &lt;zip&gt;]   --copy-from &lt;thư mục game cũ&gt;
 *   --uninstall models|tools|all          --status
 * Kiểm thử: --test-cancel-after &lt;n&gt;  huỷ (diệt cả cây tiến trình worker) sau n dòng @@P.
 * Mã thoát: 0 xong, 1 lỗi, 2 worker xong một phần, 3 cần đồng ý tải (--yes-download / --*-zip / --no-ai), 4 đã huỷ.
 * </pre>
 */
final class Cli {
    static final int OK = 0, ERROR = 1, PARTIAL = 2, NEED_CONSENT = 3, CANCELED = 4;
    private static final Set<String> FLAGS = Set.of("--cli", "--yes-download", "--no-ai", "--install-only", "--rebuild",
            "--enable", "--export-android", "--status");
    private static final Set<String> VALUED = Set.of("--game", "--pins", "--scope", "--quality", "--texture",
            "--blender-zip", "--esrgan-zip", "--toggle", "--out", "--copy-from", "--uninstall", "--test-cancel-after");

    private Cli() {
    }

    private static PrintStream out() {
        return System.out;
    }

    static int run(List<String> args) {
        for (int i = 0; i < args.size(); i++) {
            String a = args.get(i);
            if (VALUED.contains(a)) {
                if (i + 1 >= args.size()) {
                    out().println("Thiếu giá trị cho " + a);
                    return ERROR;
                }
                i++;
            } else if (!FLAGS.contains(a)) {
                out().println("Tham số lạ: " + a);
                return ERROR;
            }
        }
        try {
            return run0(args);
        } catch (IOException | RuntimeException e) {
            out().println("LỖI: " + Util.msg(e));
            return ERROR;
        }
    }

    private static Runner.Options options(List<String> args) {
        String tex = args.contains("--no-ai") ? "plain" : Tool.arg(args, "--texture");
        Runner.Texture t = switch (tex == null ? "hd" : tex) {
            case "hd", "ai", "auto" -> Runner.Texture.AI;
            case "plain" -> Runner.Texture.PLAIN;
            case "retail" -> Runner.Texture.RETAIL;
            default -> throw new IllegalArgumentException("--texture phải là hd, ai, plain hoặc retail");
        };
        String scope = Tool.arg(args, "--scope");
        String q = Tool.arg(args, "--quality");
        return new Runner.Options(scope == null ? "v1" : scope, q == null ? "pc" : q, t);
    }

    private static int run0(List<String> args) throws IOException {
        Layout g = new Layout(Tool.gameFromArgs(args));
        Path pinsPath = Pins.locate(g, Tool.argPath(args, "--pins"));
        Pins pins = Pins.load(pinsPath);
        out().println("Thư mục game: " + g.game());
        Runner.Options o = options(args);

        if (args.contains("--status")) {
            return status(g, pins);
        }
        String tog = Tool.arg(args, "--toggle");
        if (tog != null) {
            if (!tog.equals("on") && !tog.equals("off")) {
                throw new IllegalArgumentException("--toggle phải là on hoặc off");
            }
            Toggle.State s = Toggle.set(g, tog.equals("on"), o.texture() != Runner.Texture.RETAIL);
            out().print("Đã ghi remaster.properties:\n" + Toggle.content(s));
            return OK;
        }
        String un = Tool.arg(args, "--uninstall");
        if (un != null) {
            if (Prereq.gameRunning(g)) {
                out().println("Game đang chạy — hãy tắt game trước.");
                return ERROR;
            }
            List<Path> done = switch (un) {
                case "models" -> Uninstaller.deleteModels(g);
                case "tools" -> Uninstaller.deleteTools(g, pins);
                case "all" -> Uninstaller.removeAll(g, pins);
                default -> throw new IllegalArgumentException("--uninstall phải là models, tools hoặc all");
            };
            done.forEach(p -> out().println("Đã xoá " + p));
            return OK;
        }
        Path from = Tool.argPath(args, "--copy-from");
        if (from != null) {
            if (Prereq.gameRunning(g)) {
                out().println("Game đang chạy — hãy tắt game trước.");
                return ERROR;
            }
            OldFolderCopy.Result r = OldFolderCopy.copy(new Layout(from), g, pins, out()::println, () -> false);
            r.problems().forEach(p -> out().println("VẤN ĐỀ: " + p));
            return r.models() || !r.tools().isEmpty() ? OK : ERROR;
        }
        if (args.contains("--export-android")) {
            Path z = Tool.argPath(args, "--out");
            if (z == null) {
                z = AndroidExport.defaultOut(g);
            }
            AndroidExport.Report rep = AndroidExport.export(g, pins, z, printer(), null);
            out().println("Đã xuất " + z + ": " + rep.models() + " mô hình, " + rep.textures() + " texture, "
                    + Util.size(rep.bytes()) + ". Gói chỉ dùng cho máy của bạn — KHÔNG chia sẻ.");
            return OK;
        }

        // ---- chạy: kiểm tra → công cụ → worker
        List<Prereq.Check> checks = Prereq.run(g, pins, o);
        for (Prereq.Check c : checks) {
            out().println("[" + c.level() + "] " + c.title() + ": " + c.detail());
        }
        if (!Prereq.ok(checks)) {
            out().println("Chưa đủ điều kiện, dừng.");
            return ERROR;
        }
        boolean consent = args.contains("--yes-download");
        int r = ensure(g, pins, pins.blender(), Tool.argPath(args, "--blender-zip"), consent);
        if (r != OK) {
            return r;
        }
        Path esrganDir = null;
        if (o.texture() == Runner.Texture.AI) {
            r = ensure(g, pins, pins.esrgan(), Tool.argPath(args, "--esrgan-zip"), consent);
            if (r != OK) {
                return r;
            }
            esrganDir = Staging.forRun(g, pins, Cli::log);
            if (esrganDir != null) {
                out().println("Real-ESRGAN: " + esrganDir);
            } else {
                Staging.Result st = Staging.load(g, pins);
                out().println("CẢNH BÁO: Real-ESRGAN không chạy được (" + (st == null ? "chưa có thư mục chạy" : st.detail())
                        + ") — dùng phóng to thường (--no-ai).");
            }
        }
        if (args.contains("--install-only")) {
            out().println("Đã cài xong công cụ.");
            return OK;
        }
        if (args.contains("--rebuild")) {
            Runner clean = new Runner(Runner.workerCommand(g, pins, "clean", List.of()), g.game(),
                    Runner.newLogFile(g, "clean"), printer());
            Runner.Result cr = clean.run();
            if (cr.outcome() != Runner.Outcome.DONE) {
                out().println("worker clean lỗi (mã " + cr.exit() + ").");
                return ERROR;
            }
        }
        boolean resume = !args.contains("--rebuild") && Runner.shouldResume(g);
        List<String> cmd = Runner.workerCommand(g, pins, "run", Runner.runArgs(g, pins, o, esrganDir, resume));
        AtomicReference<Runner> ref = new AtomicReference<>();
        int cancelAfter = Tool.arg(args, "--test-cancel-after") == null ? -1 : Integer.parseInt(Tool.arg(args, "--test-cancel-after"));
        AtomicInteger seen = new AtomicInteger();
        Runner.Listener pl = new Runner.Listener() {
            @Override
            public void progress(Runner.Progress p) {
                out().println("[" + p.stage() + " " + p.i() + "/" + p.n() + "] " + p.label());
                if (cancelAfter >= 0 && seen.incrementAndGet() >= cancelAfter) {
                    out().println("(kiểm thử) huỷ sau " + cancelAfter + " dòng tiến độ");
                    ref.get().cancel();
                }
            }

            @Override
            public void error(String key, String stage, String msg) {
                out().println("LỖI MÔ HÌNH " + stage + " " + key + ": " + msg);
            }

            @Override
            public void line(String s) {
                out().println("  " + s);
            }
        };
        Runner runner = new Runner(cmd, g.game(), Runner.newLogFile(g, "run"), pl);
        ref.set(runner);
        Thread hook = new Thread(runner::cancel, "cancel-on-exit");
        Runtime.getRuntime().addShutdownHook(hook);
        out().println("Chạy worker" + (resume ? " (tiếp tục lần trước)" : "") + " …");
        Runner.Result res;
        try {
            res = runner.run();
        } finally {
            try {
                Runtime.getRuntime().removeShutdownHook(hook);
            } catch (IllegalStateException ignored) {
                // đang tắt JVM
            }
        }
        if (res.done() != null) {
            out().println("Tổng kết: xong " + res.done().ok() + ", lỗi " + res.done().failed() + ", bỏ qua "
                    + res.done().skipped() + ", " + res.done().minutes() + " phút.");
        }
        out().println("Log: " + res.log());
        switch (res.outcome()) {
            case CANCELED -> {
                out().println("Đã huỷ. Chạy lại sẽ tiếp tục từ chỗ dừng.");
                return CANCELED;
            }
            case FAILED -> {
                out().println("Worker lỗi (mã " + res.exit() + ").");
                return ERROR;
            }
            default -> {
                if (args.contains("--enable")) {
                    Toggle.State s = Toggle.set(g, true, o.texture() != Runner.Texture.RETAIL);
                    out().print("Đã bật mô hình HD:\n" + Toggle.content(s));
                }
                return res.outcome() == Runner.Outcome.DONE ? OK : PARTIAL;
            }
        }
    }

    private static void log(String s) {
        System.out.println(s);
    }

    private static Runner.Listener printer() {
        return new Runner.Listener() {
            @Override
            public void progress(Runner.Progress p) {
                out().println("[" + p.stage() + " " + p.i() + "/" + p.n() + "] " + p.label());
            }

            @Override
            public void line(String s) {
                out().println("  " + s);
            }
        };
    }

    /** Bảo đảm công cụ t đã cài: zip tự chọn, hoặc tải khi có --yes-download; không thì trả NEED_CONSENT. */
    private static int ensure(Layout g, Pins pins, Pins.Tool t, Path zip, boolean consent) throws IOException {
        Installer.Status s = Installer.status(g, t);
        if (s.ok()) {
            out().println(t.name + ": " + s.detail());
            return OK;
        }
        Installer.Listener l = new Installer.Listener() {
            @Override
            public void log(String msg) {
                out().println(msg);
            }
        };
        if (s.state() == Installer.State.UNVERIFIED && zip == null && Files.isRegularFile(Installer.installedJson(g, t))) {
            out().println(t.name + ": " + s.detail() + " — kiểm tra lại (không cần tải) …");
            s = Installer.recheck(g, pins, t, l);
            if (s.ok()) {
                out().println(t.name + ": " + s.detail());
                return OK;
            }
        }
        if (zip != null) {
            s = Installer.install(g, pins, t, zip, false, l);
        } else if (consent) {
            Downloader d = new Downloader(new Downloader.Listener() {
                long last = -1;

                @Override
                public void progress(long done, long total) {
                    long pct = total > 0 ? done * 100 / total : 0;
                    if (pct / 10 != last / 10) {
                        out().println("  tải " + t.file + ": " + pct + "%");
                        last = pct;
                    }
                }

                @Override
                public void log(String msg) {
                    out().println(msg);
                }
            });
            Path got;
            try {
                got = d.fetch(t, g.downloads(), true);
            } catch (Downloader.DownloadException e) {
                out().println("Tải " + t.name + " không thành công: " + Util.msg(e));
                out().println("Có thể tự tải " + t.url + " rồi chạy lại với " + (t.isBlender() ? "--blender-zip" : "--esrgan-zip") + " <file>.");
                return ERROR;
            }
            s = Installer.install(g, pins, t, got, true, l);
        } else {
            out().println("Cần " + t.name + " " + t.version + " (" + Util.size(t.size) + ", giấy phép " + t.license
                    + ", từ " + t.host_label + "). Chạy lại với --yes-download để đồng ý tải, hoặc "
                    + (t.isBlender() ? "--blender-zip" : "--esrgan-zip") + " <file zip đã tải>"
                    + (t.isEsrgan() ? ", hoặc --no-ai để bỏ qua AI" : "") + ". Chưa kết nối mạng.");
            return NEED_CONSENT;
        }
        if (!s.ok()) {
            out().println(t.name + ": " + s.detail());
            return ERROR;
        }
        return OK;
    }

    private static int status(Layout g, Pins pins) throws IOException {
        Toggle.State s = Toggle.read(g);
        out().println("Mô hình HD: " + (Files.isRegularFile(g.props()) ? (s.enabled() ? "BẬT" : "TẮT") : "TẮT (chưa có remaster.properties)")
                + ", textures=" + (s.hdTextures() ? "hd" : "retail"));
        for (Pins.Tool t : pins.tools) {
            out().println(t.name + ": " + Installer.status(g, t).detail());
        }
        Staging.Result st = Staging.load(g, pins);
        out().println("Staging Real-ESRGAN: " + (st == null ? "chưa có" : st.dir() + " (" + (st.aiOk() ? "AI chạy được" : st.detail()) + ")"));
        if (Files.isDirectory(g.remaster())) {
            try {
                RemasterData.Summary sum = RemasterData.check(g.remaster());
                out().println("Đã tạo: " + sum.models() + " mô hình, " + sum.textures() + " texture, " + Util.size(sum.bytes()));
            } catch (IOException e) {
                out().println("remaster\\ có vấn đề: " + Util.msg(e));
            }
        } else {
            out().println("Chưa tạo mô hình.");
        }
        Uninstaller.leftovers(g).forEach(p -> out().println("  có: " + p.getFileName()));
        return OK;
    }
}
