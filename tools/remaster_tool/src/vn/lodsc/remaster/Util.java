package vn.lodsc.remaster;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.DosFileAttributeView;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;

/**
 * Tiện ích dùng chung của công cụ "Tạo mô hình HD": băm SHA, xoá/chép cây thư mục an toàn (không bao giờ đi theo
 * symlink hay junction ra ngoài), ghi file nguyên tử, chạy tiến trình con có giới hạn thời gian và diệt cả cây tiến
 * trình (ProcessHandle.descendants).
 */
final class Util {
    static final Gson GSON = new GsonBuilder().setPrettyPrinting().disableHtmlEscaping().create();
    static final Gson GSON_LINE = new GsonBuilder().disableHtmlEscaping().create();

    private Util() {
    }

    static MessageDigest md(String alg) {
        try {
            return MessageDigest.getInstance(alg);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    static String hex(byte[] b) {
        StringBuilder sb = new StringBuilder(b.length * 2);
        for (byte x : b) {
            sb.append(Character.forDigit((x >> 4) & 0xF, 16)).append(Character.forDigit(x & 0xF, 16));
        }
        return sb.toString();
    }

    static String digest(Path p, String alg) throws IOException {
        MessageDigest m = md(alg);
        try (InputStream in = Files.newInputStream(p)) {
            byte[] buf = new byte[1 << 16];
            for (int n; (n = in.read(buf)) > 0; ) {
                m.update(buf, 0, n);
            }
        }
        return hex(m.digest());
    }

    static String sha256(Path p) throws IOException {
        return digest(p, "SHA-256");
    }

    static String sha1(Path p) throws IOException {
        return digest(p, "SHA-1");
    }

    static boolean isAscii(String s) {
        for (int i = 0; i < s.length(); i++) {
            if (s.charAt(i) > 0x7E || s.charAt(i) < 0x20) {
                return false;
            }
        }
        return true;
    }

    /** Dung lượng dễ đọc: "386 MB", "1,4 GB" (MB = 2^20 byte). */
    static String size(long bytes) {
        if (bytes >= (1L << 30)) {
            return String.format(Locale.forLanguageTag("vi"), "%.1f GB", bytes / (double) (1L << 30));
        }
        if (bytes >= (1L << 20)) {
            return String.format(Locale.forLanguageTag("vi"), "%d MB", Math.round(bytes / (double) (1L << 20)));
        }
        if (bytes >= 1024) {
            return String.format(Locale.forLanguageTag("vi"), "%d KB", Math.round(bytes / 1024.0));
        }
        return bytes + " byte";
    }

    static String now() {
        return LocalDateTime.now().withNano(0).format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);
    }

    static String stamp() {
        return LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss"));
    }

    /** true nếu p là symlink hoặc junction/điểm reparse khác (Windows: junction có isOther() == true). */
    static boolean isLinkLike(Path p) throws IOException {
        BasicFileAttributes a = Files.readAttributes(p, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
        return a.isSymbolicLink() || a.isOther();
    }

    private static void clearReadOnly(Path p) {
        try {
            DosFileAttributeView v = Files.getFileAttributeView(p, DosFileAttributeView.class, LinkOption.NOFOLLOW_LINKS);
            if (v != null && v.readAttributes().isReadOnly()) {
                v.setReadOnly(false);
            }
        } catch (IOException ignored) {
            // không đổi được thuộc tính: để Files.delete báo lỗi thật
        }
    }

    /**
     * Xoá cả cây thư mục. Symlink/junction bên trong chỉ bị gỡ liên kết, KHÔNG đi vào (không xoá dữ liệu ngoài cây).
     * Không có p → không làm gì.
     */
    static void deleteTree(Path p) throws IOException {
        BasicFileAttributes a;
        try {
            a = Files.readAttributes(p, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
        } catch (NoSuchFileException e) {
            return;
        }
        if (a.isDirectory() && !a.isSymbolicLink() && !a.isOther()) {
            List<Path> kids = new ArrayList<>();
            try (DirectoryStream<Path> ds = Files.newDirectoryStream(p)) {
                for (Path k : ds) {
                    kids.add(k);
                }
            }
            for (Path k : kids) {
                deleteTree(k);
            }
        }
        clearReadOnly(p);
        Files.deleteIfExists(p);
    }

    /** Chép cây src → dst (dst chưa có hoặc rỗng); bỏ qua symlink/junction. Trả số byte đã chép. */
    static long copyTree(Path src, Path dst, java.util.function.BooleanSupplier cancelled) throws IOException {
        long total = 0;
        Files.createDirectories(dst);
        List<Path> kids = new ArrayList<>();
        try (DirectoryStream<Path> ds = Files.newDirectoryStream(src)) {
            for (Path k : ds) {
                kids.add(k);
            }
        }
        kids.sort(null);
        for (Path k : kids) {
            if (cancelled != null && cancelled.getAsBoolean()) {
                throw new IOException("Đã huỷ.");
            }
            BasicFileAttributes a = Files.readAttributes(k, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            if (a.isSymbolicLink() || a.isOther()) {
                continue;
            }
            Path t = dst.resolve(k.getFileName().toString());
            if (a.isDirectory()) {
                total += copyTree(k, t, cancelled);
            } else {
                Files.copy(k, t, StandardCopyOption.REPLACE_EXISTING);
                total += a.size();
            }
        }
        return total;
    }

    /** Ghi file nguyên tử: <tên>.tmp rồi đổi tên đè lên file cũ. */
    static void writeAtomic(Path p, byte[] data) throws IOException {
        Files.createDirectories(p.toAbsolutePath().getParent());
        Path tmp = p.resolveSibling(p.getFileName().toString() + ".tmp");
        Files.write(tmp, data);
        moveReplace(tmp, p);
    }

    static void moveReplace(Path from, Path to) throws IOException {
        try {
            Files.move(from, to, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
        } catch (AtomicMoveNotSupportedException e) {
            Files.move(from, to, StandardCopyOption.REPLACE_EXISTING);
        }
    }

    static void writeJson(Path p, Object o) throws IOException {
        writeAtomic(p, (GSON.toJson(o) + "\n").getBytes(StandardCharsets.UTF_8));
    }

    /** Kết quả chạy một lệnh ngắn (kiểm tra, tự kiểm). */
    record ExecResult(int exit, String output, boolean timedOut) {
        boolean ok() {
            return !timedOut && exit == 0;
        }
    }

    /**
     * Chạy lệnh, gộp stderr vào stdout (đọc UTF-8), chờ tối đa timeout; quá giờ → diệt cả cây tiến trình; đã thoát mà
     * con cháu mồ côi còn giữ ống đầu ra → diệt chúng ({@link ProcTree}). Đầu ra giữ tối đa 64 KB cuối.
     */
    static ExecResult exec(List<String> cmd, Path cwd, Duration timeout, Map<String, String> env) throws IOException {
        ProcessBuilder pb = new ProcessBuilder(cmd).redirectErrorStream(true);
        if (cwd != null) {
            pb.directory(cwd.toFile());
        }
        cleanEnv(pb.environment());
        if (env != null) {
            pb.environment().putAll(env);
        }
        Process p = pb.start();
        ProcTree t = new ProcTree(p);
        LIVE.add(t);
        try {
            return collect(p, t, cmd, timeout);
        } finally {
            LIVE.remove(t);
        }
    }

    /**
     * Tiến trình con đang chạy qua {@link #exec} (tự kiểm Real-ESRGAN, kiểm Blender, probe) — diệt khi thoát công cụ,
     * để Real-ESRGAN treo (máy hai card đồ hoạ) không sống mãi sau khi người chơi đóng cửa sổ.
     */
    private static final Set<ProcTree> LIVE = ConcurrentHashMap.newKeySet();

    /** Diệt cả cây mọi tiến trình con đang chạy qua {@link #exec} (gọi khi đóng cửa sổ / JVM tắt). */
    static void killAllExec() {
        for (ProcTree t : List.copyOf(LIVE)) {
            t.kill();
        }
    }

    private static ExecResult collect(Process p, ProcTree t, List<String> cmd, Duration timeout) throws IOException {
        p.getOutputStream().close();
        ByteArrayOutputStream bo = new ByteArrayOutputStream();
        Thread reader = new Thread(() -> {
            try (InputStream in = p.getInputStream()) {
                byte[] buf = new byte[8192];
                for (int n; (n = in.read(buf)) > 0; ) {
                    synchronized (bo) {
                        bo.write(buf, 0, n);
                        if (bo.size() > 1 << 20) {
                            byte[] keep = bo.toByteArray();
                            bo.reset();
                            bo.write(keep, keep.length - (64 << 10), 64 << 10);
                        }
                    }
                }
            } catch (IOException ignored) {
                // tiến trình bị diệt: luồng đóng
            }
        }, "exec-reader");
        reader.setDaemon(true);
        reader.start();
        boolean finished;
        try {
            finished = t.await(timeout.toMillis());
        } catch (InterruptedException e) {
            t.kill();
            Thread.currentThread().interrupt();
            throw new IOException("Bị ngắt khi đang chạy " + cmd.get(0));
        }
        if (!finished) {
            t.kill();
        }
        try {
            reader.join(finished ? 2000 : 5000);
            if (reader.isAlive()) {
                // tiến trình đã thoát nhưng con cháu mồ côi còn giữ ống đầu ra: diệt, không để sống sau lệnh ngắn này
                t.kill();
                reader.join(3000);
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        String out;
        synchronized (bo) {
            out = bo.toString(StandardCharsets.UTF_8);
        }
        if (out.length() > 64 << 10) {
            out = out.substring(out.length() - (64 << 10));
        }
        return new ExecResult(finished ? p.exitValue() : -1, out, !finished);
    }

    /** Bỏ biến môi trường Python có thể làm worker nạp mã lạ (worker còn chạy với -I). */
    static void cleanEnv(Map<String, String> env) {
        env.keySet().removeIf(k -> {
            String u = k.toUpperCase(Locale.ROOT);
            return u.equals("PYTHONPATH") || u.equals("PYTHONHOME") || u.equals("PYTHONSTARTUP");
        });
        env.put("PYTHONIOENCODING", "utf-8");
        env.put("PYTHONUTF8", "1");
    }

    /**
     * Con cháu của h sinh KHÔNG SỚM HƠN start. Windows tái dùng PID: một tiến trình lạ (sinh trước h) có thể mang ppid
     * trùng PID của h, và khi h đã chết ProcessHandle.descendants() không còn lọc theo thời điểm sinh nữa — lọc ở đây để
     * không bao giờ diệt nhầm chương trình khác của người chơi. start null (không đọc được): h còn sống thì dùng
     * descendants() của JDK (tự lọc theo thời điểm sinh của h đang sống), h đã chết → danh sách rỗng.
     */
    static List<ProcessHandle> descendantsSince(ProcessHandle h, Instant start) {
        try {
            if (start == null) {
                return h.isAlive() ? h.descendants().toList() : List.of();
            }
            return h.descendants().filter(x -> x.info().startInstant().map(s -> !s.isBefore(start)).orElse(false)).toList();
        } catch (RuntimeException e) {
            return List.of();
        }
    }

    /**
     * Diệt tiến trình CÒN SỐNG h và mọi con cháu của nó (lọc theo thời điểm sinh, {@link #descendantsSince}). Chụp danh
     * sách con trước khi diệt gốc, rồi lặp trên từng con để bắt cả cháu sinh muộn; chờ tối đa 5 giây cho tất cả thoát.
     * h đã chết → chỉ diệt được các con đã biết qua {@link ProcTree}.
     */
    static void killTree(ProcessHandle root) {
        Instant rootStart = root.info().startInstant().orElse(null);
        Set<Long> seen = new HashSet<>();
        Deque<ProcessHandle> todo = new ArrayDeque<>(descendantsSince(root, rootStart));
        List<ProcessHandle> killed = new ArrayList<>();
        root.destroyForcibly();
        killed.add(root);
        todo.addAll(descendantsSince(root, rootStart));
        seen.add(root.pid());
        while (!todo.isEmpty()) {
            ProcessHandle h = todo.poll();
            if (!seen.add(h.pid()) || !h.isAlive()) {
                continue;
            }
            todo.addAll(descendantsSince(h, h.info().startInstant().orElse(null)));
            h.destroyForcibly();
            killed.add(h);
        }
        awaitExit(killed);
    }

    private static void awaitExit(List<ProcessHandle> killed) {
        long end = System.nanoTime() + Duration.ofSeconds(5).toNanos();
        for (ProcessHandle h : killed) {
            long left = end - System.nanoTime();
            if (left <= 0) {
                break;
            }
            try {
                h.onExit().get(left, TimeUnit.NANOSECONDS);
            } catch (Exception ignored) {
                // đã thoát hoặc hết giờ
            }
        }
    }

    /**
     * Cây tiến trình của một Process do công cụ khởi chạy (worker, lệnh kiểm). Trong lúc chờ, cứ mỗi giây chụp lại danh
     * sách con cháu (ProcessHandle giữ cả thời điểm sinh nên an toàn khi PID bị tái dùng), để khi tiến trình trung gian đã
     * chết (python.cmd → python → blender, worker chết giữa chừng) vẫn diệt được cháu mồ côi đang giữ ống stdout.
     */
    static final class ProcTree {
        private final Process p;
        private final Instant start;
        private final Set<ProcessHandle> seen = ConcurrentHashMap.newKeySet();

        ProcTree(Process p) {
            this.p = p;
            this.start = p.toHandle().info().startInstant().orElse(null);
            snapshot();
        }

        /** Ghi nhận con cháu hiện có (chỉ khi gốc còn sống: lúc đó descendants() lọc đúng theo thời điểm sinh). */
        void snapshot() {
            if (p.isAlive() && seen.size() < 4096) {
                seen.addAll(descendantsSince(p.toHandle(), start));
            }
        }

        /**
         * Chờ gốc thoát, chụp cây định kỳ (100 ms trong 2 giây đầu — tiến trình trung gian chết sớm vẫn kịp ghi nhận —,
         * 250 ms tới giây thứ 10, sau đó mỗi giây); true = đã thoát, false = hết millis.
         */
        boolean await(long millis) throws InterruptedException {
            long t0 = System.nanoTime();
            long end = millis == Long.MAX_VALUE ? Long.MAX_VALUE : t0 + TimeUnit.MILLISECONDS.toNanos(millis);
            while (true) {
                long now = System.nanoTime();
                long step = TimeUnit.MILLISECONDS.toNanos(now - t0 < TimeUnit.SECONDS.toNanos(2) ? 100
                        : now - t0 < TimeUnit.SECONDS.toNanos(10) ? 250 : 1000);
                long left = end == Long.MAX_VALUE ? step : end - now;
                if (left <= 0) {
                    return !p.isAlive();
                }
                if (p.waitFor(Math.min(left, step), TimeUnit.NANOSECONDS)) {
                    return true;
                }
                snapshot();
            }
        }

        /** Diệt gốc (nếu còn) và mọi con cháu còn sống đã biết hoặc tìm được lúc này. Trả số con cháu bị diệt. */
        int kill() {
            snapshot();
            Set<ProcessHandle> all = new LinkedHashSet<>(seen);
            all.addAll(descendantsSince(p.toHandle(), start));
            if (p.isAlive()) {
                killTree(p.toHandle());
            }
            all.addAll(descendantsSince(p.toHandle(), start));
            int n = 0;
            for (ProcessHandle h : all) {
                if (h.isAlive()) {
                    killTree(h);
                    n++;
                }
            }
            return n;
        }
    }

    /** Thông báo lỗi ngắn cho người chơi (không in stack). */
    static String msg(Throwable t) {
        String m = t.getMessage();
        if (m == null || m.isBlank()) {
            m = t.getClass().getSimpleName();
        }
        return m;
    }
}
