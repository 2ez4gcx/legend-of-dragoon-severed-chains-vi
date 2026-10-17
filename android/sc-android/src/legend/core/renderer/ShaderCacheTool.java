package legend.core.renderer;

import legend.core.memory.types.IntRef;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Stream;

/**
 * [sc-android] Transpiles every shader in gfx/shaders to GLSL ES 3.20 the way the retail GLES renderer does at run time
 * (ShaderManager.transpileUncached: shaderc + SPIRV-Cross) and writes the cache read by ShaderManager.transpileShader:
 * gfx/shaders_es/&lt;key&gt;.glsl ("// uniforms=N" + source). Run on a PC (Windows natives of lwjgl-shaderc/spvc) from the game
 * directory: {@code java -cp sc-android.jar;lod-game-<commit>.jar;libs/* legend.core.renderer.ShaderCacheTool [out dir]}.
 * Stage by extension: .vsh vertex, .gsh geometry, .fsh fragment (GlesShader).
 */
public final class ShaderCacheTool {
  private ShaderCacheTool() { }

  public static void main(final String[] args) throws Exception {
    final Path out = args.length > 0 ? Path.of(args[0]) : ShaderManager.ES_CACHE;
    Files.createDirectories(out);
    final List<Path> files = new ArrayList<>();
    try(final Stream<Path> s = Files.list(Path.of("gfx", "shaders"))) {
      s.filter(Files::isRegularFile).sorted().forEach(files::add);
    }

    int n = 0;
    for(final Path file : files) {
      final String name = file.getFileName().toString();
      final ShaderStage stage;
      if(name.endsWith(".vsh")) {
        stage = ShaderStage.VERTEX;
      } else if(name.endsWith(".gsh")) {
        stage = ShaderStage.GEOMETRY;
      } else if(name.endsWith(".fsh")) {
        stage = ShaderStage.FRAGMENT;
      } else {
        continue;
      }

      final String source = Files.readString(file);
      final IntRef uniforms = new IntRef();
      final String es = ShaderManager.transpileUncached(source, stage, uniforms);
      final String key = ShaderManager.cacheKey(source, stage);
      Files.writeString(out.resolve(key + ".glsl"), "// uniforms=" + uniforms.get() + '\n' + es, StandardCharsets.UTF_8);
      System.out.println(name + " " + stage + " uniforms=" + uniforms.get() + " -> " + key + ".glsl");
      n++;
    }

    System.out.println(n + " shader(s) -> " + out);
  }
}
