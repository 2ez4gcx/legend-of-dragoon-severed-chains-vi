package vn.lodsc.remaster;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Tải công cụ ghim trong pins.json — CHỈ sau khi người chơi đồng ý (tham số consent; sai → lỗi trước khi mở mạng).
 * <ul>
 *   <li>java.net.http, chỉ HTTPS, chỉ các máy trong danh sách cho phép {@link #ALLOWED_HOSTS}; tự đi theo chuyển hướng
 *       (tối đa 8 lần) và kiểm từng đích trước khi kết nối.</li>
 *   <li>Ghi vào &lt;file&gt;.part, nhớ ETag/Last-Modified trong &lt;file&gt;.part.json; lần sau tải tiếp bằng
 *       Range + If-Range (máy chủ trả 200 → tải lại từ đầu).</li>
 *   <li>Băm SHA-256 theo luồng (phần đã có được băm lại trước khi tải tiếp); kích thước và SHA-256 phải đúng pins.json,
 *       sai → xoá file. Lỗi → thử lại 1 lần, rồi báo để người chơi chọn file zip tự tải.</li>
 *   <li>Đứng yên 60 giây không nhận byte nào → ngắt và thử lại.</li>
 * </ul>
 * Kiểm thử: thuộc tính -Dlodsc.remaster.testHosts=127.0.0.1 cho phép thêm máy CỤC BỘ (127.0.0.1, localhost, ::1),
 * kể cả qua http; mọi tên khác trong thuộc tính bị bỏ qua.
 */
final class Downloader {
    static final Set<String> ALLOWED_HOSTS = Set.of("download.blender.org", "github.com",
            "objects.githubusercontent.com", "release-assets.githubusercontent.com");
    private static final Set<String> LOOPBACK = Set.of("127.0.0.1", "localhost", "::1", "[::1]");
    private static final Pattern CONTENT_RANGE = Pattern.compile("^bytes (\\d+)-(\\d+)/(\\d+|\\*)$");
    static final String USER_AGENT = "LoD-SC-VN-remaster-tool/1";

    interface Listener {
        void progress(long done, long total);

        void log(String msg);
    }

    /** Lỗi tải; kind cho biết có nên mời người chơi chọn zip tự tải không. */
    static final class DownloadException extends IOException {
        enum Kind { HOST, HTTP, NETWORK, SIZE, HASH, CANCELED, CONSENT }

        final Kind kind;

        DownloadException(Kind kind, String msg) {
            super(msg);
            this.kind = kind;
        }
    }

    private final Listener listener;
    private final AtomicBoolean cancelled = new AtomicBoolean();
    private volatile InputStream current;

    Downloader(Listener listener) {
        this.listener = listener;
    }

    void cancel() {
        cancelled.set(true);
        InputStream in = current;
        if (in != null) {
            try {
                in.close();
            } catch (IOException ignored) {
                // đang đóng
            }
        }
    }

    /** Máy kiểm thử cục bộ được bật bằng -Dlodsc.remaster.testHosts (chỉ địa chỉ vòng lặp). */
    static boolean testHost(String host) {
        if (host == null) {
            return false;
        }
        String prop = System.getProperty("lodsc.remaster.testHosts", "");
        String h = host.toLowerCase(Locale.ROOT);
        for (String s : prop.split(",")) {
            String x = s.trim().toLowerCase(Locale.ROOT);
            if (!x.isEmpty() && LOOPBACK.contains(x) && x.equals(h)) {
                return true;
            }
        }
        return false;
    }

    /** Kiểm một URI trước khi kết nối: https + máy trong danh sách cho phép (hoặc máy kiểm thử cục bộ). */
    static URI checkUri(URI u) throws DownloadException {
        String scheme = u.getScheme() == null ? "" : u.getScheme().toLowerCase(Locale.ROOT);
        String host = u.getHost() == null ? "" : u.getHost().toLowerCase(Locale.ROOT);
        boolean test = testHost(host);
        if (!scheme.equals("https") && !(scheme.equals("http") && test)) {
            throw new DownloadException(DownloadException.Kind.HOST, "Chỉ tải qua HTTPS, từ chối: " + u);
        }
        if (!ALLOWED_HOSTS.contains(host) && !test) {
            throw new DownloadException(DownloadException.Kind.HOST, "Máy chủ không nằm trong danh sách cho phép: " + host);
        }
        if (u.getUserInfo() != null) {
            throw new DownloadException(DownloadException.Kind.HOST, "URL không được chứa thông tin đăng nhập");
        }
        return u;
    }

    /**
     * Tải công cụ t vào thư mục dir; trả đường dẫn file zip đã kiểm đúng kích thước + SHA-256.
     *
     * @param consent người chơi đã đánh dấu đồng ý tải công cụ này (thiếu → lỗi, không mở mạng)
     */
    Path fetch(Pins.Tool t, Path dir, boolean consent) throws IOException {
        if (!consent) {
            throw new DownloadException(DownloadException.Kind.CONSENT,
                    "Chưa đồng ý tải " + t.name + " — không kết nối mạng.");
        }
        URI start = checkUri(URI.create(t.url));
        Files.createDirectories(dir);
        Path fin = dir.resolve(t.file);
        Path part = dir.resolve(t.file + ".part");
        Path meta = dir.resolve(t.file + ".part.json");
        if (Files.isRegularFile(fin)) {
            if (Files.size(fin) == t.size && Util.sha256(fin).equals(t.sha256)) {
                listener.log("Đã có " + t.file + " (đúng SHA-256), không tải lại.");
                return fin;
            }
            Files.delete(fin);
        }
        IOException last = null;
        for (int attempt = 1; attempt <= 2; attempt++) {
            if (cancelled.get()) {
                throw new DownloadException(DownloadException.Kind.CANCELED, "Đã huỷ tải.");
            }
            try {
                String sha = fetchOnce(t, start, part, meta);
                if (sha == null) {
                    continue;
                }
                if (!sha.equals(t.sha256)) {
                    Files.deleteIfExists(part);
                    Files.deleteIfExists(meta);
                    throw new DownloadException(DownloadException.Kind.HASH, "SHA-256 của " + t.file
                            + " không khớp (nhận " + sha + ", cần " + t.sha256 + "). Đã xoá file tải hỏng.");
                }
                Util.moveReplace(part, fin);
                Files.deleteIfExists(meta);
                listener.log("Tải xong và kiểm đúng SHA-256: " + t.file);
                return fin;
            } catch (DownloadException e) {
                if (e.kind == DownloadException.Kind.CANCELED || e.kind == DownloadException.Kind.HOST
                        || e.kind == DownloadException.Kind.CONSENT) {
                    throw e;
                }
                last = e;
            } catch (IOException e) {
                if (cancelled.get()) {
                    throw new DownloadException(DownloadException.Kind.CANCELED, "Đã huỷ tải (phần đã tải được giữ để tải tiếp).");
                }
                last = new DownloadException(DownloadException.Kind.NETWORK, "Lỗi mạng khi tải " + t.file + ": " + Util.msg(e));
            }
            listener.log("Lần tải " + attempt + " lỗi: " + Util.msg(last) + (attempt == 1 ? " — thử lại." : ""));
        }
        throw last != null ? last : new DownloadException(DownloadException.Kind.NETWORK, "Tải không thành công.");
    }

    /** Một lượt tải (tiếp). Trả SHA-256 của file .part khi đã đủ size byte, null nếu cần lượt khác. */
    private String fetchOnce(Pins.Tool t, URI start, Path part, Path meta) throws IOException {
        long offset = 0;
        String validator = null;
        if (Files.isRegularFile(part) && Files.isRegularFile(meta)) {
            try {
                JsonObject m = JsonParser.parseString(Files.readString(meta, StandardCharsets.UTF_8)).getAsJsonObject();
                if (t.url.equals(m.get("url").getAsString()) && t.sha256.equals(m.get("sha256").getAsString())) {
                    validator = m.has("etag") ? m.get("etag").getAsString()
                            : m.has("last_modified") ? m.get("last_modified").getAsString() : null;
                }
            } catch (RuntimeException ignored) {
                validator = null;
            }
            offset = validator != null ? Files.size(part) : 0;
        }
        if (offset > t.size) {
            offset = 0;
        }
        if (offset == 0) {
            Files.deleteIfExists(part);
            Files.deleteIfExists(meta);
        }
        MessageDigest md = Util.md("SHA-256");
        if (offset > 0) {
            try (InputStream in = Files.newInputStream(part)) {
                byte[] buf = new byte[1 << 16];
                long left = offset;
                for (int n; left > 0 && (n = in.read(buf, 0, (int) Math.min(buf.length, left))) > 0; ) {
                    md.update(buf, 0, n);
                    left -= n;
                }
            }
            if (offset == t.size) {
                return Util.hex(md.digest());
            }
            listener.log("Tải tiếp " + t.file + " từ " + Util.size(offset) + ".");
        }
        HttpClient client = HttpClient.newBuilder().followRedirects(HttpClient.Redirect.NEVER)
                .version(HttpClient.Version.HTTP_1_1).connectTimeout(Duration.ofSeconds(30)).build();
        try {
            return request(t, start, part, meta, client, offset, validator, md);
        } finally {
            client.shutdownNow();
        }
    }

    private String request(Pins.Tool t, URI start, Path part, Path meta, HttpClient client, long offset,
                           String validator, MessageDigest md) throws IOException {
        URI uri = start;
        HttpResponse<InputStream> resp = null;
        for (int hop = 0; hop <= 8; hop++) {
            checkUri(uri);
            HttpRequest.Builder rb = HttpRequest.newBuilder(uri).GET().timeout(Duration.ofSeconds(60))
                    .header("User-Agent", USER_AGENT);
            if (offset > 0) {
                rb.header("Range", "bytes=" + offset + "-").header("If-Range", validator);
            }
            try {
                resp = client.send(rb.build(), HttpResponse.BodyHandlers.ofInputStream());
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new DownloadException(DownloadException.Kind.CANCELED, "Bị ngắt.");
            }
            int code = resp.statusCode();
            if (code == 301 || code == 302 || code == 303 || code == 307 || code == 308) {
                String loc = resp.headers().firstValue("Location").orElse(null);
                resp.body().close();
                if (loc == null) {
                    throw new DownloadException(DownloadException.Kind.HTTP, "Chuyển hướng không có Location");
                }
                try {
                    uri = uri.resolve(loc.trim());
                } catch (IllegalArgumentException e) {
                    throw new DownloadException(DownloadException.Kind.HTTP, "Chuyển hướng tới địa chỉ sai: " + loc);
                }
                resp = null;
                continue;
            }
            break;
        }
        if (resp == null) {
            throw new DownloadException(DownloadException.Kind.HTTP, "Quá nhiều lần chuyển hướng");
        }
        int code = resp.statusCode();
        try (InputStream body = resp.body()) {
            boolean append;
            if (code == 206 && offset > 0) {
                Matcher cr = CONTENT_RANGE.matcher(resp.headers().firstValue("Content-Range").orElse(""));
                if (!cr.matches() || Long.parseLong(cr.group(1)) != offset
                        || (!cr.group(3).equals("*") && Long.parseLong(cr.group(3)) != t.size)) {
                    Files.deleteIfExists(part);
                    Files.deleteIfExists(meta);
                    throw new DownloadException(DownloadException.Kind.HTTP, "Content-Range không khớp, tải lại từ đầu");
                }
                append = true;
            } else if (code == 200) {
                long cl = resp.headers().firstValueAsLong("Content-Length").orElse(-1);
                if (cl >= 0 && cl != t.size) {
                    Files.deleteIfExists(part);
                    Files.deleteIfExists(meta);
                    throw new DownloadException(DownloadException.Kind.SIZE, "Kích thước trên máy chủ (" + cl
                            + " byte) khác pins.json (" + t.size + " byte).");
                }
                if (offset > 0) {
                    listener.log("Máy chủ không cho tải tiếp (file đã đổi?) — tải lại từ đầu.");
                }
                offset = 0;
                md.reset();
                append = false;
                JsonObject m = new JsonObject();
                m.addProperty("url", t.url);
                m.addProperty("sha256", t.sha256);
                resp.headers().firstValue("ETag").ifPresent(v -> m.addProperty("etag", v));
                resp.headers().firstValue("Last-Modified").ifPresent(v -> m.addProperty("last_modified", v));
                Util.writeAtomic(meta, Util.GSON.toJson(m).getBytes(StandardCharsets.UTF_8));
            } else if (code == 416) {
                Files.deleteIfExists(part);
                Files.deleteIfExists(meta);
                return null;
            } else {
                throw new DownloadException(DownloadException.Kind.HTTP, "Máy chủ trả mã HTTP " + code + " cho " + resp.uri());
            }
            return stream(t, body, part, append, offset, md);
        }
    }

    private String stream(Pins.Tool t, InputStream body, Path part, boolean append, long offset, MessageDigest md)
            throws IOException {
        AtomicLong lastByte = new AtomicLong(System.nanoTime());
        AtomicBoolean stalled = new AtomicBoolean();
        ScheduledExecutorService wd = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread th = new Thread(r, "download-watchdog");
            th.setDaemon(true);
            return th;
        });
        long stallNanos = TimeUnit.SECONDS.toNanos(Long.getLong("lodsc.remaster.stallSeconds", 60));
        wd.scheduleAtFixedRate(() -> {
            if (System.nanoTime() - lastByte.get() > stallNanos) {
                stalled.set(true);
                try {
                    body.close();
                } catch (IOException ignored) {
                    // đóng để luồng đọc thoát
                }
            }
        }, 1, 1, TimeUnit.SECONDS);
        current = body;
        long done = offset;
        try (OutputStream out = Files.newOutputStream(part, append
                ? new StandardOpenOption[]{StandardOpenOption.CREATE, StandardOpenOption.APPEND, StandardOpenOption.WRITE}
                : new StandardOpenOption[]{StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE})) {
            byte[] buf = new byte[1 << 16];
            long lastReport = 0;
            for (int n; (n = body.read(buf)) > 0; ) {
                if (cancelled.get()) {
                    throw new DownloadException(DownloadException.Kind.CANCELED, "Đã huỷ tải (phần đã tải được giữ để tải tiếp).");
                }
                if (done + n > t.size) {
                    out.close();
                    Files.deleteIfExists(part);
                    throw new DownloadException(DownloadException.Kind.SIZE, "Máy chủ gửi nhiều hơn " + t.size + " byte — đã xoá.");
                }
                out.write(buf, 0, n);
                md.update(buf, 0, n);
                done += n;
                lastByte.set(System.nanoTime());
                if (done - lastReport >= (1 << 20) || done == t.size) {
                    listener.progress(done, t.size);
                    lastReport = done;
                }
            }
        } catch (IOException e) {
            if (cancelled.get() && !(e instanceof DownloadException)) {
                throw new DownloadException(DownloadException.Kind.CANCELED, "Đã huỷ tải (phần đã tải được giữ để tải tiếp).");
            }
            if (stalled.get()) {
                throw new DownloadException(DownloadException.Kind.NETWORK, "Không nhận được dữ liệu trong "
                        + TimeUnit.NANOSECONDS.toSeconds(stallNanos) + " giây");
            }
            throw e;
        } finally {
            current = null;
            wd.shutdownNow();
        }
        listener.progress(done, t.size);
        if (done != t.size) {
            throw new DownloadException(DownloadException.Kind.NETWORK, "Kết nối đóng sớm (" + done + "/" + t.size + " byte); sẽ tải tiếp.");
        }
        return Util.hex(md.digest());
    }

    /**
     * Kiểm một file zip người chơi tự tải (không cần mạng): đúng kích thước và SHA-256 trong pins.json.
     */
    static void checkManualZip(Pins.Tool t, Path zip) throws IOException {
        if (!Files.isRegularFile(zip)) {
            throw new DownloadException(DownloadException.Kind.SIZE, "Không thấy file " + zip);
        }
        long sz = Files.size(zip);
        if (sz != t.size) {
            throw new DownloadException(DownloadException.Kind.SIZE, "File " + zip.getFileName() + " có " + sz
                    + " byte, cần đúng " + t.size + " byte (" + t.file + ").");
        }
        String sha = Util.sha256(zip);
        if (!sha.equals(t.sha256)) {
            throw new DownloadException(DownloadException.Kind.HASH, "SHA-256 của " + zip.getFileName()
                    + " không khớp bản ghim (" + t.version + "). Hãy tải đúng file " + t.file + ".");
        }
    }
}
