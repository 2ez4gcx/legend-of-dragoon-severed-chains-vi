package vn.lodsc.remaster;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Chạy worker Python theo đúng hợp đồng SPEC §3.9 (công cụ chỉ nói chuyện với worker qua dòng lệnh này):
 * <pre>
 *   &lt;blender&gt;/5.2/python/bin/python.exe -I -X utf8 &lt;game&gt;/vi/remaster/py/worker.py run --game &lt;g&gt; --blender &lt;exe&gt;
 *       [--esrgan &lt;thư mục ASCII&gt; | --no-ai] [--scope v1|v1+optional] [--quality pc|mobile|both]
 *       [--texture hd|retail] [--resume]
 *   lệnh con khác: probe, export-android --out &lt;zip&gt;, clean (công cụ luôn thêm --game &lt;g&gt;)
 * </pre>
 * Đọc stdout (UTF-8, gộp stderr) từng dòng: "@@P {stage,i,n,label}" → tiến độ, "@@E {key,stage,msg}" → lỗi từng mô
 * hình, "@@DONE {ok,failed,skipped,minutes}" → tổng kết; dòng khác vào log. Mã thoát 0 = xong, 2 = một phần,
 * 1 = lỗi nặng. Huỷ / Tạm dừng = diệt cả cây tiến trình (python + blender + realesrgan con); lần chạy sau dùng
 * --resume. Toàn bộ đầu ra được ghi remaster_work/logs/tool-&lt;thời điểm&gt;.log (UTF-8).
 */
final class Runner {
    enum Texture { AI, PLAIN, RETAIL }

    /** Tuỳ chọn người chơi chọn ở màn Tuỳ chọn. */
    record Options(String scope, String quality, Texture texture) {
        static final Options DEFAULT = new Options("v1", "pc", Texture.AI);

        Options {
            if (!scope.equals("v1") && !scope.equals("v1+optional")) {
                throw new IllegalArgumentException("scope phải là v1 hoặc v1+optional");
            }
            if (!quality.equals("pc") && !quality.equals("mobile") && !quality.equals("both")) {
                throw new IllegalArgumentException("quality phải là pc, mobile hoặc both");
            }
        }
    }

    record Progress(String stage, int i, int n, String label) {
    }

    record Done(int ok, int failed, int skipped, double minutes) {
    }

    enum Outcome { DONE, PARTIAL, FAILED, CANCELED }

    record Result(Outcome outcome, int exit, Done done, List<String> errors, Path log) {
    }

    interface Listener {
        default void progress(Progress p) {
        }

        default void error(String key, String stage, String msg) {
        }

        default void line(String s) {
        }
    }

    private final List<String> cmd;
    private final Path cwd;
    private final Path logFile;
    private final Listener listener;
    private final AtomicBoolean cancelled = new AtomicBoolean();
    /** Cây tiến trình worker đang chạy (null khi chưa chạy / đã xong). */
    private volatile Util.ProcTree tree;

    Runner(List<String> cmd, Path cwd, Path logFile, Listener listener) {
        this.cmd = List.copyOf(cmd);
        this.cwd = cwd;
        this.logFile = logFile;
        this.listener = listener;
    }

    List<String> command() {
        return cmd;
    }

    /**
     * Lệnh worker: python -I -X utf8 worker.py &lt;sub&gt; --game &lt;g&gt; &lt;args&gt;. "-X utf8" (tuỳ chọn trình thông dịch,
     * không đổi tham số của worker): -I bỏ qua mọi biến PYTHON* (PYTHONUTF8, PYTHONIOENCODING) nên Python 3.13 của Blender
     * ghi stdout ống bằng cp1252 và ngã (UnicodeEncodeError) ngay khi in đường dẫn game có dấu như "Trò chơi" — đã thử
     * trên blender-5.2.2/5.2/python/bin/python.exe. Với -X utf8 stdout/stderr/open() mặc định UTF-8, khớp cách công cụ đọc.
     */
    static List<String> workerCommand(Layout g, Pins pins, String sub, List<String> args) {
        List<String> c = new ArrayList<>();
        c.add(Installer.python(g, pins).toString());
        c.add("-I");
        c.add("-X");
        c.add("utf8");
        c.add(g.worker().toAbsolutePath().toString());
        c.add(sub);
        c.add("--game");
        c.add(g.game().toString());
        c.addAll(args);
        return c;
    }

    /**
     * Tham số của "run". esrganDir = thư mục staging đã tự kiểm đạt, null = không AI.
     * Texture: AI → --esrgan dir (không có staging đạt → --no-ai); PLAIN → --no-ai; RETAIL → --no-ai --texture retail.
     */
    static List<String> runArgs(Layout g, Pins pins, Options o, Path esrganDir, boolean resume) {
        List<String> a = new ArrayList<>();
        a.add("--blender");
        a.add(Installer.blenderExe(g, pins).toString());
        if (o.texture() == Texture.AI && esrganDir != null) {
            a.add("--esrgan");
            a.add(esrganDir.toString());
        } else {
            a.add("--no-ai");
        }
        a.add("--scope");
        a.add(o.scope());
        a.add("--quality");
        a.add(o.quality());
        a.add("--texture");
        a.add(o.texture() == Texture.RETAIL ? "retail" : "hd");
        if (resume) {
            a.add("--resume");
        }
        return a;
    }

    /**
     * Có nên thêm --resume: đã có remaster_work/state.json (trạng thái từng giai đoạn của worker, P4) — lần chạy trước
     * bị dừng hoặc bộ nhớ đệm còn; worker tự kiểm bộ đệm theo hash nên --resume luôn an toàn.
     */
    static boolean shouldResume(Layout g) {
        return Files.isRegularFile(g.work().resolve("state.json"));
    }

    static Path newLogFile(Layout g, String what) {
        return g.logs().resolve("tool-" + what + "-" + Util.stamp() + ".log");
    }

    void cancel() {
        cancelled.set(true);
        Util.ProcTree t = tree;
        if (t != null) {
            t.kill();
        }
    }

    boolean isCancelled() {
        return cancelled.get();
    }

    /** Dấu hết dòng của luồng đọc stdout worker. */
    private static final Object EOF = new Object();

    /**
     * Chạy worker tới khi thoát. Mọi lỗi giữa chừng (ghi log hỏng, listener ném lỗi, …) đều diệt cả cây tiến trình
     * worker trước khi ném tiếp — không bao giờ để worker + blender/realesrgan con chạy mồ côi.
     * <p>
     * stdout được đọc trên luồng riêng. Worker đã thoát mà ống stdout vẫn chưa đóng sau
     * {@code lodsc.remaster.orphanGraceSeconds} giây (mặc định 5) nghĩa là có tiến trình con mồ côi (blender/realesrgan
     * treo khi worker chết) đang giữ ống: diệt chúng ({@link Util.ProcTree#kill}); vẫn chưa đóng sau 5 giây nữa (con
     * cháu không tìm được) → thôi đọc và kết thúc theo mã thoát của worker, không bao giờ treo mãi ở màn "Đang tạo".
     */
    Result run() throws IOException {
        List<String> errors = new ArrayList<>();
        Done done = null;
        Util.ProcTree t = null;
        boolean exited = false;
        Files.createDirectories(logFile.getParent());
        try (BufferedWriter log = Files.newBufferedWriter(logFile, StandardCharsets.UTF_8)) {
            log.write("# " + Util.now() + "\n# cwd: " + cwd + "\n# " + String.join(" ", cmd) + "\n");
            log.flush();
            if (cancelled.get()) {
                return new Result(Outcome.CANCELED, -1, null, errors, logFile);
            }
            ProcessBuilder pb = new ProcessBuilder(cmd).directory(cwd.toFile()).redirectErrorStream(true);
            Util.cleanEnv(pb.environment());
            Process p = pb.start();
            t = new Util.ProcTree(p);
            tree = t;
            final Util.ProcTree wt = t;
            // chụp cây tiến trình con suốt đời worker (để còn tìm được cháu mồ côi khi tiến trình trung gian đã chết)
            Thread watch = new Thread(() -> {
                try {
                    wt.await(Long.MAX_VALUE);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }, "worker-tree-watch");
            watch.setDaemon(true);
            watch.start();
            p.getOutputStream().close();
            if (cancelled.get()) {
                t.kill();
            }
            BlockingQueue<Object> q = new LinkedBlockingQueue<>();
            Thread reader = new Thread(() -> {
                try (BufferedReader r = new BufferedReader(new InputStreamReader(p.getInputStream(), StandardCharsets.UTF_8))) {
                    for (String ln; (ln = r.readLine()) != null; ) {
                        q.add(ln);
                    }
                    q.add(EOF);
                } catch (IOException e) {
                    q.add(e);
                }
            }, "worker-reader");
            reader.setDaemon(true);
            reader.start();
            long grace = TimeUnit.SECONDS.toNanos(Long.getLong("lodsc.remaster.orphanGraceSeconds", 5));
            long exitSeen = 0;
            int orphans = -1;
            boolean abandoned = false;
            while (true) {
                Object o;
                try {
                    o = q.poll(200, TimeUnit.MILLISECONDS);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    t.kill();
                    break;
                }
                if (o == EOF) {
                    break;
                }
                if (o instanceof IOException e) {
                    if (!cancelled.get()) {
                        throw e;
                    }
                    break;
                }
                if (o instanceof String ln) {
                    Done d = line(ln.replace("\r", ""), log, errors);
                    if (d != null) {
                        done = d;
                    }
                    continue;
                }
                if (p.isAlive()) {
                    continue;
                }
                long now = System.nanoTime();
                if (exitSeen == 0) {
                    exitSeen = now;
                } else if (orphans < 0 && now - exitSeen > grace) {
                    orphans = t.kill();
                    exitSeen = now;
                    String m = "(công cụ) worker đã thoát nhưng ống đầu ra còn mở — đã diệt " + orphans
                            + " tiến trình con mồ côi.";
                    log.write("# " + m + "\n");
                    listener.line(m);
                } else if (orphans >= 0 && now - exitSeen > TimeUnit.SECONDS.toNanos(5)) {
                    abandoned = true;
                    break;
                }
            }
            if (abandoned) {
                String m = "(công cụ) ống đầu ra của worker vẫn bị một tiến trình khác giữ — thôi đọc, kết thúc theo mã thoát.";
                log.write("# " + m + "\n");
                listener.line(m);
            }
            int exit;
            try {
                exit = p.waitFor();
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                t.kill();
                exit = -1;
            }
            exited = true;
            Outcome oc = cancelled.get() ? Outcome.CANCELED
                    : exit == 0 ? Outcome.DONE : exit == 2 ? Outcome.PARTIAL : Outcome.FAILED;
            log.write("# exit " + exit + " -> " + oc + "\n");
            return new Result(oc, exit, done, errors, logFile);
        } finally {
            tree = null;
            if (t != null && !exited) {
                // thoát bất thường (lỗi đọc/ghi, RuntimeException từ listener): không để worker và con cháu sống tiếp
                t.kill();
            }
        }
    }

    /** Xử lý một dòng stdout của worker: ghi log, chuyển @@P/@@E cho listener; trả Done nếu là @@DONE hợp lệ. */
    private Done line(String ln, BufferedWriter log, List<String> errors) throws IOException {
        log.write(ln);
        log.write('\n');
        log.flush();
        if (ln.startsWith("@@P ")) {
            JsonObject o = json(ln.substring(4));
            if (o != null) {
                listener.progress(new Progress(str(o, "stage"), num(o, "i"), num(o, "n"), str(o, "label")));
                return null;
            }
        } else if (ln.startsWith("@@E ")) {
            JsonObject o = json(ln.substring(4));
            if (o != null) {
                String key = str(o, "key"), stage = str(o, "stage"), msg = str(o, "msg");
                errors.add(stage + " " + key + ": " + msg);
                listener.error(key, stage, msg);
                return null;
            }
        } else if (ln.startsWith("@@DONE ")) {
            JsonObject o = json(ln.substring(7));
            if (o != null) {
                return new Done(num(o, "ok"), num(o, "failed"), num(o, "skipped"), dbl(o, "minutes"));
            }
        }
        listener.line(ln);
        return null;
    }

    private static JsonObject json(String s) {
        try {
            JsonElement e = JsonParser.parseString(s.trim());
            return e.isJsonObject() ? e.getAsJsonObject() : null;
        } catch (RuntimeException e) {
            return null;
        }
    }

    private static String str(JsonObject o, String k) {
        JsonElement e = o.get(k);
        return e == null || e.isJsonNull() ? "" : e.isJsonPrimitive() ? e.getAsString() : e.toString();
    }

    private static int num(JsonObject o, String k) {
        try {
            JsonElement e = o.get(k);
            return e == null || e.isJsonNull() ? 0 : e.getAsInt();
        } catch (RuntimeException ex) {
            return 0;
        }
    }

    /** Số thực (minutes); thiếu, sai kiểu hay không hữu hạn → 0 (dòng @@DONE lạ không được làm hỏng lần chạy). */
    private static double dbl(JsonObject o, String k) {
        try {
            JsonElement e = o.get(k);
            double v = e == null || e.isJsonNull() || !e.isJsonPrimitive() ? 0 : e.getAsDouble();
            return Double.isFinite(v) ? v : 0;
        } catch (RuntimeException ex) {
            return 0;
        }
    }
}
