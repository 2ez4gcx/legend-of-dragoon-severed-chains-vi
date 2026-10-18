package legend.scvi.remaster;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * [sc-vi] Chỉ mục mô hình HD remaster/index.tsv (LRM spec 1 §3.7).
 *
 * UTF-8 (giải mã chặt, không BOM), xuống dòng LF. Dòng 1 đúng "LRMINDEX\t1"; mỗi dòng sau không rỗng:
 * "&lt;modelKey&gt;\tmodels/&lt;modelKey&gt;.lrm\t&lt;nhãn&gt;" (khoá = 40 hex thường, nhãn không chứa TAB/CR/LF). Dòng rỗng bỏ
 * qua; một dòng sai định dạng => coi như không có chỉ mục (tắt cả tính năng). Bộ sinh ghi file này cuối cùng (điểm commit).
 */
final class RemasterIndex {
  static final Path DIR = Path.of("remaster");
  static final Path FILE = DIR.resolve("index.tsv");
  /** Giới hạn cỡ file chỉ mục (vài nghìn dòng là tối đa thực tế). */
  private static final long MAX_SIZE = 16L << 20;
  private static final Pattern KEY = Pattern.compile("[0-9a-f]{40}");

  private final Map<String, String> labels;

  private RemasterIndex(final Map<String, String> labels) {
    this.labels = labels;
  }

  int size() {
    return this.labels.size();
  }

  boolean contains(final String key) {
    return this.labels.containsKey(key);
  }

  String label(final String key) {
    return this.labels.get(key);
  }

  static Path modelPath(final String key) {
    return DIR.resolve("models").resolve(key + ".lrm");
  }

  /** Thiếu file -&gt; null (tắt, không lỗi). Sai định dạng -&gt; ném Invalid (tắt, có ghi log). */
  static RemasterIndex load() throws IOException, LrmFile.Invalid {
    if(!Files.isRegularFile(FILE)) {
      return null;
    }

    if(Files.size(FILE) > MAX_SIZE) {
      throw new LrmFile.Invalid("index.tsv too large");
    }

    return parse(Files.readAllBytes(FILE));
  }

  static RemasterIndex parse(final byte[] data) throws LrmFile.Invalid {
    final String text;
    try {
      text = StandardCharsets.UTF_8.newDecoder()
        .onMalformedInput(CodingErrorAction.REPORT)
        .onUnmappableCharacter(CodingErrorAction.REPORT)
        .decode(ByteBuffer.wrap(data))
        .toString();
    } catch(final CharacterCodingException e) {
      throw new LrmFile.Invalid("index.tsv is not valid UTF-8");
    }

    final String[] lines = text.split("\n", -1);
    if(!"LRMINDEX\t1".equals(lines[0])) {
      throw new LrmFile.Invalid("index.tsv line 1 must be LRMINDEX<TAB>1");
    }

    final Map<String, String> labels = new HashMap<>();
    for(int i = 1; i < lines.length; i++) {
      final String line = lines[i];
      if(line.isEmpty()) {
        continue;
      }

      final String[] cols = line.split("\t", -1);
      if(cols.length != 3 || !KEY.matcher(cols[0]).matches() || !cols[1].equals("models/" + cols[0] + ".lrm") || cols[2].indexOf('\r') >= 0) {
        throw new LrmFile.Invalid("index.tsv line " + (i + 1) + " malformed");
      }

      labels.put(cols[0], cols[2]);
    }

    return new RemasterIndex(labels);
  }
}
