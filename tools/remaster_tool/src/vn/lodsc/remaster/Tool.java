package vn.lodsc.remaster;

import javax.swing.JOptionPane;
import javax.swing.SwingUtilities;
import java.io.IOException;
import java.net.URISyntaxException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * Công cụ "Tạo mô hình HD" cho bản Việt hoá The Legend of Dragoon trên Severed Chains (hướng B, LRM spec 1).
 * Chạy trên JDK 25 mà SC đã tải sẵn trong jdk25\, chỉ cần thêm libs\gson-2.13.2.jar của SC.
 *
 * <pre>
 * Giao diện (TAO_MO_HINH_HD.bat):
 *   jdk25\bin\javaw.exe -cp "vi/remaster/lodsc-remaster.jar;libs/gson-2.13.2.jar" vn.lodsc.remaster.Tool
 * Dòng lệnh (kiểm thử, xem Cli):
 *   java -cp ... vn.lodsc.remaster.Tool --cli --game . --scope v1 --yes-download --texture hd
 * Xem trước giao diện không cần cửa sổ (ảnh PNG từng màn, không mở mạng):
 *   java -Djava.awt.headless=true -cp ... vn.lodsc.remaster.Tool --render-screens &lt;thư mục&gt; [--game .] [--pins f]
 * </pre>
 * Thư mục game: --game (mặc định: suy từ vị trí jar &lt;game&gt;\vi\remaster\lodsc-remaster.jar, nếu không thì thư mục
 * hiện tại). Java trên Windows nhận tham số dòng lệnh theo bảng mã ANSI nên đường dẫn có dấu tiếng Việt bị hỏng: hãy
 * dùng --game . với thư mục làm việc là thư mục game, hoặc --args-file &lt;file UTF-8, mỗi dòng một tham số&gt;.
 */
public final class Tool {
    static final String VERSION = "1.0.0";

    private Tool() {
    }

    public static void main(String[] argv) {
        List<String> args;
        try {
            args = expandArgsFile(Arrays.asList(argv));
        } catch (IOException e) {
            System.err.println("Không đọc được --args-file: " + Util.msg(e));
            System.exit(1);
            return;
        }
        // thoát công cụ (đóng cửa sổ, Ctrl+C) → diệt cả cây các tiến trình con ngắn đang chạy (tự kiểm, probe)
        Runtime.getRuntime().addShutdownHook(new Thread(Util::killAllExec, "kill-children"));
        if (args.contains("--cli")) {
            System.exit(Cli.run(args));
            return;
        }
        if (args.contains("--render-screens")) {
            System.exit(MainWindow.renderScreens(args));
            return;
        }
        Path game = gameFromArgs(args);
        Path pins = argPath(args, "--pins");
        Thread.setDefaultUncaughtExceptionHandler((t, e) -> {
            e.printStackTrace();
            SwingUtilities.invokeLater(() -> JOptionPane.showMessageDialog(null,
                    "Lỗi không mong đợi: " + Util.msg(e), "Tạo mô hình HD", JOptionPane.ERROR_MESSAGE));
        });
        SwingUtilities.invokeLater(() -> MainWindow.open(new Layout(game), pins));
    }

    /** Thay "--args-file f" bằng các dòng (UTF-8, bỏ dòng rỗng và dòng bắt đầu bằng #) của f. */
    static List<String> expandArgsFile(List<String> in) throws IOException {
        List<String> out = new ArrayList<>();
        for (int i = 0; i < in.size(); i++) {
            if (in.get(i).equals("--args-file") && i + 1 < in.size()) {
                for (String ln : Files.readAllLines(Path.of(in.get(++i)), StandardCharsets.UTF_8)) {
                    String s = ln.replace("\uFEFF", "").strip();
                    if (!s.isEmpty() && !s.startsWith("#")) {
                        out.add(s);
                    }
                }
            } else {
                out.add(in.get(i));
            }
        }
        return out;
    }

    static String arg(List<String> args, String name) {
        int i = args.indexOf(name);
        return i >= 0 && i + 1 < args.size() ? args.get(i + 1) : null;
    }

    static Path argPath(List<String> args, String name) {
        String v = arg(args, name);
        return v == null ? null : Path.of(v).toAbsolutePath().normalize();
    }

    /** Thư mục chứa jar đang chạy (null nếu chạy từ thư mục lớp). */
    static Path jarDir() {
        try {
            var src = Tool.class.getProtectionDomain().getCodeSource();
            if (src == null) {
                return null;
            }
            Path p = Path.of(src.getLocation().toURI());
            return Files.isRegularFile(p) ? p.getParent() : null;
        } catch (URISyntaxException | RuntimeException e) {
            return null;
        }
    }

    static Path gameFromArgs(List<String> args) {
        Path g = argPath(args, "--game");
        if (g != null) {
            return g;
        }
        Path jd = jarDir();
        if (jd != null && jd.getFileName() != null && jd.getFileName().toString().equals("remaster")
                && jd.getParent() != null && jd.getParent().getFileName() != null
                && jd.getParent().getFileName().toString().equals("vi")) {
            return jd.getParent().getParent();
        }
        return Path.of("").toAbsolutePath();
    }
}
