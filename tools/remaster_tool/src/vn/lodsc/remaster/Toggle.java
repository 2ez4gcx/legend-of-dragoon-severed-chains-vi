package vn.lodsc.remaster;

import java.io.IOException;
import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Locale;
import java.util.Properties;

/**
 * Công tắc &lt;game&gt;/remaster.properties (SPEC §3.7). Công cụ luôn ghi đúng 3 dòng ASCII, xuống dòng LF, theo thứ tự
 * cố định (cùng dạng bộ file mẫu của synth_cube.py):
 * <pre>
 * enabled=true|false
 * textures=hd|retail
 * log=true|false
 * </pre>
 * Đọc theo java.util.Properties đúng như runtime (sc-vi legend.scvi.remaster.RemasterConfig): thiếu file → tắt; thiếu
 * khoá → enabled=false, textures=hd, log=false; enabled/log lạ → false; textures lạ → retail (runtime dùng bộ VRAM).
 * Ghi nguyên tử (remaster.properties.tmp rồi đổi tên).
 */
final class Toggle {
    record State(boolean enabled, boolean hdTextures, boolean log) {
        static final State OFF = new State(false, true, false);
    }

    private Toggle() {
    }

    static String content(State s) {
        return "enabled=" + s.enabled() + "\ntextures=" + (s.hdTextures() ? "hd" : "retail") + "\nlog=" + s.log() + "\n";
    }

    static State read(Layout g) {
        Path p = g.props();
        if (!Files.isRegularFile(p)) {
            return State.OFF;
        }
        Properties pr = new Properties();
        try (Reader r = Files.newBufferedReader(p, StandardCharsets.ISO_8859_1)) {
            pr.load(r);
        } catch (IOException | IllegalArgumentException e) {
            return State.OFF;
        }
        boolean enabled = "true".equals(val(pr, "enabled"));
        // như runtime RemasterConfig: thiếu khoá hoặc "hd" → hd; "retail" hoặc giá trị lạ → retail (chỉ bộ VRAM)
        String tex = val(pr, "textures");
        boolean hd = tex == null || tex.equals("hd");
        boolean log = "true".equals(val(pr, "log"));
        return new State(enabled, hd, log);
    }

    private static String val(Properties pr, String k) {
        String v = pr.getProperty(k);
        return v == null ? null : v.trim().toLowerCase(Locale.ROOT);
    }

    static void write(Layout g, State s) throws IOException {
        Util.writeAtomic(g.props(), content(s).getBytes(StandardCharsets.US_ASCII));
    }

    /** Bật/tắt, giữ textures và log hiện có. */
    static State setEnabled(Layout g, boolean enabled) throws IOException {
        State cur = read(g);
        State s = new State(enabled, cur.hdTextures(), cur.log());
        write(g, s);
        return s;
    }

    /** Bật/tắt và đặt textures theo lựa chọn texture (Giữ texture gốc → retail). */
    static State set(Layout g, boolean enabled, boolean hdTextures) throws IOException {
        State cur = read(g);
        State s = new State(enabled, hdTextures, cur.log());
        write(g, s);
        return s;
    }
}
