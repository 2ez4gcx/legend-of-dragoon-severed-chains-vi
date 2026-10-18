package vn.lodsc.remaster;

import java.nio.file.Path;

/**
 * Bố cục thư mục game (SPEC kiến trúc §6). Mọi đường dẫn công cụ ghi đều nằm dưới đây (trừ thư mục staging ASCII của
 * Real-ESRGAN, xem {@link Staging}):
 * <pre>
 *   remaster.properties                    công tắc (§3.7)
 *   remaster/                              dữ liệu runtime: index.tsv, manifest.json, models/, textures/
 *   remaster_work/                         bộ nhớ đệm + log của worker và công cụ
 *   remaster_tools/                        công cụ tải về: blender-5.2.2-windows-x64/, realesrgan/, dl/ (zip đang tải)
 *   remaster_export/                       gói Android đã xuất
 *   vi/remaster/                           phần phát hành: lodsc-remaster.jar, py/worker.py, pins.json, catalog_v1.json
 * </pre>
 */
record Layout(Path game) {
    static final String SC_COMMIT = "affcef0cba71819515fdf05521c1fedb1d7a92f0";
    /** Tên mọi mục cấp cao do công cụ tạo (Gỡ hết xoá đúng các mục này). */
    static final String[] TOP_LEVEL = {"remaster", "remaster_work", "remaster_tools", "remaster_export",
            "remaster.properties", "remaster.properties.tmp", "remaster.import", "remaster.old"};

    Layout {
        game = game.toAbsolutePath().normalize();
    }

    Path remaster() {
        return game.resolve("remaster");
    }

    Path work() {
        return game.resolve("remaster_work");
    }

    Path logs() {
        return work().resolve("logs");
    }

    Path tools() {
        return game.resolve("remaster_tools");
    }

    Path downloads() {
        return tools().resolve("dl");
    }

    Path export() {
        return game.resolve("remaster_export");
    }

    Path props() {
        return game.resolve("remaster.properties");
    }

    Path viRemaster() {
        return game.resolve("vi").resolve("remaster");
    }

    Path worker() {
        String o = System.getProperty("lodsc.remaster.worker");
        return o != null ? Path.of(o) : viRemaster().resolve("py").resolve("worker.py");
    }

    Path catalog() {
        return viRemaster().resolve("catalog_v1.json");
    }

    Path scJar() {
        return game.resolve("lod-game-" + SC_COMMIT + ".jar");
    }

    Path toolDir(Pins.Tool t) {
        return tools().resolve(t.dir);
    }

    Path stagingInfo() {
        return tools().resolve("esrgan_staging.json");
    }

    boolean asciiPath() {
        return Util.isAscii(game.toString());
    }
}
