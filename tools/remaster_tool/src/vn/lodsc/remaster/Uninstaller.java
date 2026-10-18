package vn.lodsc.remaster;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/**
 * Xoá dữ liệu của tính năng Mô hình HD, chỉ đúng các mục cấp cao trong thư mục game (Layout.TOP_LEVEL) và thư mục
 * staging ASCII ngoài game có file đánh dấu của game này. Không đi theo symlink/junction (Util.deleteTree).
 * <ul>
 *   <li>Xoá mô hình đã tạo: remaster/, remaster_work/ (+ remaster.import/, remaster.old/ còn sót). Giữ remaster_export/
 *       (gói Android người chơi có thể còn cần chép) và remaster.properties, nhưng ghi enabled=false (giữ textures/log)
 *       nếu đang bật — game không còn tìm chỉ mục.</li>
 *   <li>Xoá công cụ đã tải: remaster_tools/ (Blender, Real-ESRGAN, zip đang tải) + thư mục staging.</li>
 *   <li>Gỡ hết: tất cả ở trên + remaster_export/ + remaster.properties → thư mục game như bản gốc
 *       (vi/remaster/ là phần của gói Việt hoá, giữ nguyên).</li>
 * </ul>
 */
final class Uninstaller {
    private Uninstaller() {
    }

    private static void del(Path p, List<Path> done) throws IOException {
        if (Files.exists(p, LinkOption.NOFOLLOW_LINKS)) {
            Util.deleteTree(p);
            done.add(p);
        }
    }

    static List<Path> deleteModels(Layout g) throws IOException {
        List<Path> done = new ArrayList<>();
        // tắt công tắc TRƯỚC khi xoá (giữ textures/log): game không còn đọc chỉ mục / ghi cảnh báo "thiếu index.tsv" mỗi
        // lần chuyển cảnh, và màn Quản lý không báo "BẬT" khi không còn mô hình nào
        if (Files.isRegularFile(g.props()) && Toggle.read(g).enabled()) {
            Toggle.setEnabled(g, false);
        }
        del(g.remaster(), done);
        del(g.work(), done);
        del(g.game().resolve("remaster.import"), done);
        del(g.game().resolve("remaster.old"), done);
        return done;
    }

    static List<Path> deleteTools(Layout g, Pins pins) throws IOException {
        List<Path> done = new ArrayList<>();
        Path st = Staging.remove(g, pins);
        if (st != null) {
            done.add(st);
        }
        del(g.tools(), done);
        return done;
    }

    static List<Path> removeAll(Layout g, Pins pins) throws IOException {
        List<Path> done = new ArrayList<>(deleteModels(g));
        done.addAll(deleteTools(g, pins));
        for (String n : Layout.TOP_LEVEL) {
            del(g.game().resolve(n), done);
        }
        return done;
    }

    /** Các mục remaster* còn ở cấp cao của thư mục game (để kiểm "gỡ sạch"). */
    static List<Path> leftovers(Layout g) throws IOException {
        List<Path> out = new ArrayList<>();
        try (var ds = Files.newDirectoryStream(g.game(), "remaster*")) {
            ds.forEach(out::add);
        }
        return out;
    }
}
