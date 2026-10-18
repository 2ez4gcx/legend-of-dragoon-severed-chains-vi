package vn.lodsc.remaster;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Optional;

/**
 * Màn "Kiểm tra": điều kiện trước khi tải/tạo. FAIL chặn, WARN chỉ cảnh báo.
 * <ul>
 *   <li>Windows 64-bit; JDK 25 trong jdk25\ (và tiến trình hiện tại chạy Java &gt;= 25);</li>
 *   <li>đúng jar SC lod-game-affcef0….jar; đĩa đã giải nén (files\characters\dart\models\combat\32,
 *       files\SECT\DRGN21.BIN); có vi\remaster\py\worker.py;</li>
 *   <li>ghi được vào thư mục game; cảnh báo nếu nằm trong Program Files hoặc OneDrive, hoặc đường dẫn dài hơn 75 ký tự
 *       (file sâu nhất của Blender khi đó vượt MAX_PATH 260 của Windows);</li>
 *   <li>dung lượng trống so với ước tính; game không chạy (ProcessHandle: tiến trình jdk25\bin\java.exe của thư mục
 *       này, trừ chính công cụ).</li>
 * </ul>
 * Ước tính thời gian/dung lượng: số mô hình từ vi\remaster\catalog_v1.json (tier core / optional), mặc định 107 + 9.
 */
final class Prereq {
    enum Level { OK, WARN, FAIL }

    record Check(String title, Level level, String detail) {
    }

    record Estimate(int models, int minLow, int minHigh, long outBytes, long workBytes, long toolBytes) {
        long totalBytes() {
            return outBytes + workBytes + toolBytes + (300L << 20);
        }
    }

    private Prereq() {
    }

    /** Số mô hình theo phạm vi: [core, optional] từ catalog_v1.json nếu đọc được. */
    static int[] catalogCounts(Layout g) {
        int core = 107, opt = 9;
        try {
            if (Files.isRegularFile(g.catalog())) {
                JsonElement e = JsonParser.parseString(Files.readString(g.catalog(), StandardCharsets.UTF_8));
                JsonArray a = e.isJsonArray() ? e.getAsJsonArray()
                        : e.getAsJsonObject().has("entries") ? e.getAsJsonObject().getAsJsonArray("entries") : null;
                if (a != null) {
                    int c = 0, o = 0;
                    for (JsonElement x : a) {
                        String tier = x.getAsJsonObject().has("tier") ? x.getAsJsonObject().get("tier").getAsString() : "core";
                        if (tier.equals("optional")) {
                            o++;
                        } else {
                            c++;
                        }
                    }
                    if (c + o > 0) {
                        core = c;
                        opt = o;
                    }
                }
            }
        } catch (IOException | RuntimeException ignored) {
            // dùng số mặc định
        }
        return new int[]{core, opt};
    }

    static Estimate estimate(Layout g, Pins pins, Runner.Options o) {
        int[] cnt = catalogCounts(g);
        int n = cnt[0] + (o.scope().equals("v1+optional") ? cnt[1] : 0);
        double sec = 8 + switch (o.texture()) {
            case AI -> 4;
            case PLAIN -> 1.5;
            case RETAIL -> 0;
        };
        if (o.quality().equals("both")) {
            sec *= 1.3;
        }
        int low = (int) Math.max(1, Math.round(n * sec / 60.0 * 0.7));
        int high = (int) Math.max(2, Math.round(n * sec / 60.0 * 2.0));
        boolean tex = o.texture() != Runner.Texture.RETAIL;
        long pc = tex ? (2L << 20) : (800L << 10);
        long mobile = tex ? (600L << 10) : (250L << 10);
        long per = switch (o.quality()) {
            case "mobile" -> mobile;
            case "both" -> pc + mobile;
            default -> pc;
        };
        long out = n * per;
        long work = n * (3L << 20);
        long tools = 0;
        for (Pins.Tool t : pins.tools) {
            if (t.isEsrgan() && o.texture() != Runner.Texture.AI) {
                continue;
            }
            if (!Installer.status(g, t).ok()) {
                tools += t.size + t.installed_size;
            }
        }
        return new Estimate(n, low, high, out, work, tools);
    }

    static boolean ok(List<Check> checks) {
        return checks.stream().noneMatch(c -> c.level() == Level.FAIL);
    }

    /** Có tiến trình game (jdk25\bin\java.exe của thư mục này) đang chạy không (trừ chính công cụ). */
    static boolean gameRunning(Layout g) {
        Path java = g.game().resolve("jdk25").resolve("bin").resolve("java.exe");
        String want = java.toString().toLowerCase(Locale.ROOT);
        long self = ProcessHandle.current().pid();
        return ProcessHandle.allProcesses().anyMatch(ph -> {
            if (ph.pid() == self) {
                return false;
            }
            Optional<String> c = ph.info().command();
            return c.isPresent() && c.get().toLowerCase(Locale.ROOT).equals(want);
        });
    }

    static List<Check> run(Layout g, Pins pins, Runner.Options o) {
        List<Check> out = new ArrayList<>();
        String os = System.getProperty("os.name", "");
        String arch = System.getProperty("os.arch", "");
        boolean win64 = os.startsWith("Windows") && (arch.equals("amd64") || arch.equals("x86_64"));
        out.add(new Check("Windows 64-bit", win64 ? Level.OK : Level.FAIL,
                win64 ? os : "Chỉ hỗ trợ Windows 10/11 64-bit (đang là " + os + " " + arch + ")."));

        boolean jdk = Files.isRegularFile(g.game().resolve("jdk25").resolve("bin").resolve("javaw.exe"))
                || Files.isRegularFile(g.game().resolve("jdk25").resolve("bin").resolve("java.exe"));
        boolean rt = Runtime.version().feature() >= 25;
        out.add(new Check("Java 25 (jdk25)", jdk && rt ? Level.OK : Level.FAIL, jdk && rt ? "Có jdk25" :
                "Không thấy jdk25\\ — hãy chạy launch-vi.bat một lần trước (tự tải Java)."));

        boolean scJar = Files.isRegularFile(g.scJar());
        out.add(new Check("Severed Chains đúng bản (" + Layout.SC_COMMIT.substring(0, 7) + ")", scJar ? Level.OK : Level.FAIL,
                scJar ? g.scJar().getFileName().toString()
                        : "Không thấy " + g.scJar().getFileName() + " — đây không phải thư mục gói Việt hoá, hoặc SC đã bị cập nhật."));

        Path files = g.game().resolve("files");
        boolean unpacked = Files.exists(files.resolve("characters").resolve("dart").resolve("models").resolve("combat").resolve("32"))
                && Files.exists(files.resolve("SECT").resolve("DRGN21.BIN"));
        out.add(new Check("Đĩa đã giải nén (files\\)", unpacked ? Level.OK : Level.FAIL, unpacked ? "Có files\\SECT, files\\characters"
                : "Hãy chạy launch-vi.bat và chờ giải nén đĩa xong (tới màn tựa) rồi mở lại công cụ."));

        boolean worker = Files.isRegularFile(g.worker());
        out.add(new Check("Bộ tạo mô hình (vi\\remaster\\py)", worker ? Level.OK : Level.FAIL, worker ? "Có worker.py"
                : "Thiếu vi\\remaster\\py\\worker.py — hãy giải nén lại gói Việt hoá."));

        boolean writable;
        String wdetail;
        Path probe = g.game().resolve(".lodsc_write_test_" + ProcessHandle.current().pid() + ".tmp");
        try {
            Files.writeString(probe, "x");
            Files.delete(probe);
            writable = true;
            wdetail = "Ghi được";
        } catch (IOException e) {
            writable = false;
            wdetail = "Không ghi được vào thư mục game (" + Util.msg(e) + "). Hãy chép game ra thư mục khác, ví dụ D:\\Games.";
        }
        out.add(new Check("Quyền ghi thư mục game", writable ? Level.OK : Level.FAIL, wdetail));

        String low = g.game().toString().toLowerCase(Locale.ROOT);
        String where = null;
        for (String env : new String[]{"ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"}) {
            String v = System.getenv(env);
            if (v != null && !v.isBlank() && low.startsWith(v.toLowerCase(Locale.ROOT))) {
                where = "Program Files";
            }
        }
        for (String env : new String[]{"OneDrive", "OneDriveConsumer", "OneDriveCommercial"}) {
            String v = System.getenv(env);
            if (v != null && !v.isBlank() && low.startsWith(v.toLowerCase(Locale.ROOT))) {
                where = "OneDrive";
            }
        }
        if (where == null && low.contains("\\onedrive")) {
            where = "OneDrive";
        }
        out.add(new Check("Vị trí thư mục", where == null ? Level.OK : Level.WARN, where == null ? g.game().toString()
                : "Thư mục game nằm trong " + where + ": có thể chậm, bị đồng bộ hoặc bị chặn ghi. Nên chép game ra D:\\Games."));

        // file sâu nhất của Blender 5.2.2: 142 ký tự sau remaster_tools\blender-5.2.2-windows-x64\ (41) → MAX_PATH 259
        int len = g.game().toString().length();
        out.add(new Check("Độ dài đường dẫn", len <= 75 ? Level.OK : Level.WARN, len <= 75 ? len + " ký tự"
                : "Đường dẫn thư mục game dài " + len + " ký tự: vài file của Blender sẽ vượt giới hạn 260 ký tự của"
                + " Windows. Công cụ vẫn cài được, nhưng nên chuyển game ra thư mục ngắn hơn, ví dụ D:\\Games\\LoD."));

        Estimate est = estimate(g, pins, o);
        long free;
        try {
            free = Files.getFileStore(g.game()).getUsableSpace();
        } catch (IOException e) {
            free = -1;
        }
        Level fl = free < 0 ? Level.WARN : free >= est.totalBytes() ? Level.OK : Level.FAIL;
        out.add(new Check("Dung lượng trống", fl, (free < 0 ? "Không đọc được dung lượng trống" : "Trống " + Util.size(free))
                + ", cần khoảng " + Util.size(est.totalBytes()) + (fl == Level.FAIL ? " — hãy dọn bớt ổ đĩa." : "")));

        boolean running = gameRunning(g);
        out.add(new Check("Game đang tắt", running ? Level.FAIL : Level.OK, running
                ? "Game đang chạy từ thư mục này — hãy tắt game trước." : "Không thấy game chạy"));
        return out;
    }
}
