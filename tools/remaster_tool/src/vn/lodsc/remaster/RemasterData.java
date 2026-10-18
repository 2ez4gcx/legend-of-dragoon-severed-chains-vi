package vn.lodsc.remaster;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * Kiểm nhẹ dữ liệu remaster/ do worker sinh (không thay verify_out.py): index.tsv đúng SPEC §3.7, mọi .lrm được chỉ
 * mục có header LRM1 version 1 và modelKey (offset 0x08, 20 byte) = tên file, mọi PNG trong textures/ có SHA-1 = tên
 * và header PNG/IHDR cỡ luỹ thừa 2 &lt;= 2048 (§3.6.1), manifest.json là JSON có format = 1. Dùng khi chép từ thư mục
 * game cũ (kiểm lại hash sau khi chép) và khi kiểm gói Android đã xuất (cùng quy tắc với vn.lodsc.RemasterImport).
 */
final class RemasterData {
    static final Pattern KEY = Pattern.compile("^[0-9a-f]{40}$");
    static final byte[] PNG_SIG = {(byte) 0x89, 'P', 'N', 'G', '\r', '\n', 0x1A, '\n'};

    record Summary(int models, int textures, long bytes, Map<String, String> labels) {
    }

    private RemasterData() {
    }

    /**
     * Đọc index.tsv (bytes UTF-8): {khoá: nhãn} theo thứ tự; sai định dạng → IOException. Chặt như app Android
     * (vn.lodsc.RemasterImport) để gói xuất ra không bị điện thoại từ chối: UTF-8 hợp lệ, không BOM, không CR, khoá
     * không trùng.
     */
    static Map<String, String> parseIndex(byte[] data) throws IOException {
        String text;
        try {
            text = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(data)).toString();
        } catch (CharacterCodingException e) {
            throw new IOException("index.tsv không phải UTF-8 hợp lệ");
        }
        if (text.startsWith("\uFEFF")) {
            throw new IOException("index.tsv không được có BOM");
        }
        String[] lines = text.split("\n", -1);
        if (!lines[0].equals("LRMINDEX\t1")) {
            throw new IOException("dòng 1 của index.tsv phải là LRMINDEX<TAB>1");
        }
        Map<String, String> out = new LinkedHashMap<>();
        for (int i = 1; i < lines.length; i++) {
            String ln = lines[i];
            if (ln.isEmpty()) {
                continue;
            }
            String[] c = ln.split("\t", -1);
            if (c.length != 3 || !KEY.matcher(c[0]).matches() || !c[1].equals("models/" + c[0] + ".lrm")
                    || ln.indexOf('\r') >= 0) {
                throw new IOException("dòng " + (i + 1) + " của index.tsv sai định dạng");
            }
            if (out.containsKey(c[0])) {
                throw new IOException("dòng " + (i + 1) + " của index.tsv: khoá trùng " + c[0]);
            }
            out.put(c[0], c[2]);
        }
        return out;
    }

    /** SPEC §3.6.1 (như app Android): chữ ký PNG, chunk đầu IHDR, rộng/cao luỹ thừa 2 trong 1..2048. */
    static void checkPngHeader(byte[] head, String name) throws IOException {
        if (head.length < 24) {
            throw new IOException("texture " + name + " ngắn hơn 24 byte");
        }
        for (int i = 0; i < PNG_SIG.length; i++) {
            if (head[i] != PNG_SIG[i]) {
                throw new IOException("texture " + name + " không phải PNG");
            }
        }
        if (head[12] != 'I' || head[13] != 'H' || head[14] != 'D' || head[15] != 'R') {
            throw new IOException("texture " + name + ": chunk đầu không phải IHDR");
        }
        long w = be32(head, 16);
        long h = be32(head, 20);
        if (!pow2(w) || !pow2(h)) {
            throw new IOException("texture " + name + ": cỡ " + w + "x" + h + " không phải luỹ thừa 2 trong 1..2048");
        }
    }

    private static boolean pow2(long v) {
        return v >= 1 && v <= 2048 && (v & (v - 1)) == 0;
    }

    private static long be32(byte[] b, int o) {
        return (b[o] & 0xFFL) << 24 | (b[o + 1] & 0xFFL) << 16 | (b[o + 2] & 0xFFL) << 8 | (b[o + 3] & 0xFFL);
    }

    /** Kiểm header LRM1 (đủ 0x40 byte đầu). */
    static void checkLrmHeader(byte[] head, String key) throws IOException {
        if (head.length < 0x40) {
            throw new IOException(key + ".lrm ngắn hơn 64 byte");
        }
        if (head[0] != 'L' || head[1] != 'R' || head[2] != 'M' || head[3] != '1') {
            throw new IOException(key + ".lrm sai magic LRM1");
        }
        int version = (head[4] & 0xFF) | (head[5] & 0xFF) << 8;
        if (version != 1) {
            throw new IOException(key + ".lrm version " + version + " (cần 1)");
        }
        byte[] k = new byte[20];
        System.arraycopy(head, 8, k, 0, 20);
        if (!Util.hex(k).equals(key)) {
            throw new IOException(key + ".lrm có modelKey khác tên file");
        }
    }

    static byte[] readHead(Path p) throws IOException {
        try (InputStream in = Files.newInputStream(p)) {
            return in.readNBytes(0x40);
        }
    }

    static void checkManifest(byte[] data) throws IOException {
        try {
            JsonElement e = JsonParser.parseString(new String(data, StandardCharsets.UTF_8));
            JsonObject o = e.getAsJsonObject();
            if (!o.has("format") || o.get("format").getAsInt() != 1) {
                throw new IOException("manifest.json: format phải là 1");
            }
        } catch (RuntimeException e) {
            throw new IOException("manifest.json hỏng: " + Util.msg(e));
        }
    }

    /** Kiểm cả thư mục remaster/ (đọc lại toàn bộ byte để băm). */
    static Summary check(Path dir) throws IOException {
        Path idx = dir.resolve("index.tsv");
        if (!Files.isRegularFile(idx)) {
            throw new IOException("thiếu " + idx);
        }
        Map<String, String> labels = parseIndex(Files.readAllBytes(idx));
        long bytes = Files.size(idx);
        for (String key : labels.keySet()) {
            Path p = dir.resolve("models").resolve(key + ".lrm");
            if (!Files.isRegularFile(p)) {
                throw new IOException("thiếu models/" + key + ".lrm");
            }
            checkLrmHeader(readHead(p), key);
            bytes += Files.size(p);
        }
        int tex = 0;
        Path td = dir.resolve("textures");
        if (Files.isDirectory(td)) {
            List<Path> pngs = new ArrayList<>();
            try (DirectoryStream<Path> ds = Files.newDirectoryStream(td, "*.png")) {
                ds.forEach(pngs::add);
            }
            for (Path p : pngs) {
                String name = p.getFileName().toString();
                String stem = name.substring(0, name.length() - 4);
                if (!KEY.matcher(stem).matches()) {
                    throw new IOException("tên texture lạ: " + name);
                }
                if (!Util.sha1(p).equals(stem)) {
                    throw new IOException("textures/" + name + " sai SHA-1 (file hỏng)");
                }
                checkPngHeader(readHead(p), name);
                bytes += Files.size(p);
                tex++;
            }
        }
        Path man = dir.resolve("manifest.json");
        if (!Files.isRegularFile(man)) {
            throw new IOException("thiếu manifest.json");
        }
        checkManifest(Files.readAllBytes(man));
        return new Summary(labels.size(), tex, bytes, labels);
    }
}
