"""make_variants.py — dựng các bộ shader thử "hình nhân vật" cho Severed Chains (chỉ để thử, không phát hành nguyên trạng).

Đọc (chỉ đọc) 5 shader TMD gốc trong game/gfx/shaders (LF, SC affcef0) và 3 shader PN trong tools/sc_charfx/pn/, áp các
chỗ sửa bên dưới (mỗi chỗ khớp đúng 1 lần, sai là dừng), ghi mỗi bộ vào out/charfx_variants/<tên>/ gồm ĐÚNG 5 file
tmd.vsh, battle_tmd.vsh, tmd.gsh, tmd.fsh, battle_tmd.fsh (LF) + out/charfx_variants/manifest.json.
Áp một bộ vào game: powershell -File tools/sc_charfx/sc_fx.ps1 -Apply out\\charfx_variants\\<tên>, rồi F5 trong game.

Cách gọi:
  python tools/sc_charfx/make_variants.py [--out THƯ_MỤC] [--stock THƯ_MỤC] [--max-seg N]
    --max-seg N  giới hạn số đoạn PN mỗi cạnh (mặc định 4; 3 nếu driver GLES tính ngân sách GS theo ô vec4)
Exit 0 = đạt, 1 = lỗi (chỗ sửa không khớp, PN lệch so với shader gốc, vượt ngân sách GS).

Các bộ (tên dùng trong ab_scene.ps1):
  z_off  mọi phần mới đều biên dịch vào nhưng tắt lúc chạy: phải cho hình y hệt bản gốc, KỂ CẢ khi loader đã ghi bit PN
         (ENH_FORCE 0: PN, L2, T chỉ bật khi lights[modelIndex].backgroundColour.w > 0, SC gốc luôn ghi 0)
  pn     chỉ hình học PN (ánh sáng/texture gốc); số đoạn và độ cong đọc từ bit cờ đỉnh (không thêm uniform); ENH_FORCE 1 trong GS
         = PN chỉ theo bit của loader
  l2t    ánh sáng L2 (wrap + che tối mặt dưới + viền sáng) + lọc texture song phương theo bảng màu T (= lt_form_bilateral
         của đợt nghiên cứu trước, ép bật cho mọi model)
  all    PN + L2 + T gộp thành MỘT bộ 5 file thống nhất (GS xuất thêm biến cho L2/T ở mọi đỉnh con, ánh sáng theo điểm ảnh
         dùng pháp tuyến PN nội suy)
  _off, _pnraw  bộ tự kiểm cho lint/check_iface (không chụp): _off = mọi công tắc 0 trên nền gốc (phải dịch ra y hệt gốc),
         _pnraw = 3 file pn/ nguyên trạng + FS gốc (phải dịch ra y hệt bộ pn)

Công tắc (giống hệt nhau trong cả 5 file, vì chúng đổi giao diện VS_OUT/GS_OUT):
  ENH_PN        1 = tmd.vsh/battle_tmd.vsh/tmd.gsh dựng từ pn/ (PN-triangles; chỉ có tác dụng khi loader ghi bit PN)
  ENH_LIGHTING  ánh sáng theo điểm ảnh + wrap + che tối mặt dưới + viền sáng
  ENH_TEXFILTER lọc texture song phương theo bảng màu (đọc VRAM/CLUT sống)
  ENH_PACK      gộp vertTpage+vertClut (flat vec2 x2) thành 1 flat vec4 để GS_OUT <= 15 vị trí (mức tối thiểu GLES 3.2)
  ENH_FORCE     (trong FS và trong tmd.gsh của bộ PN; không đổi giao diện) 1 = bật L2/T cho mọi primitive đủ điều kiện, PN theo
                bit loader; 0 = thêm điều kiện theo model lights[modelIndex].backgroundColour.w > 0 (z_off: SC gốc luôn ghi 0)
Điều kiện L2 (giữ nguyên thiết kế nghiên cứu): lit && !translucent && projectionMode != 0, thêm !ctmd && !uniformLit
ở battle. Điều kiện T: vertBpp != 3 && lit (thêm !ctmd ở battle) && enhAmount() > 0.

Bit cờ đỉnh (inFlags, float nguyên, chính xác tới 2^24), loader (TmdObjLoader + PnEdgeFlags) ghi:
  0x01 LIT 0x02 TEXTURED 0x04 COLOURED 0x08 TRANSLUCENT 0x10 QUAD (gốc); bit 5-6 chỉ số góc; bit 7-10 cạnh thẳng;
  bit 11 bật PN; bit 12-14 số đoạn (min(.,4), <=1 = gốc); bit 15-17 độ cong theo 1/8 (0 = 1.0; loader ghi 8/8 thành
  0x40000 = bit 18 thì shader đọc 3 bit thấy 0 = 1.0, bit 18 bị bỏ qua); bit 24 do battle_tmd_pn.vsh đặt (số nguyên, trong VS)
  khi cả model vẽ trong suốt (ctmdFlags & 0x2). FS chỉ thấy 5 bit gốc (+0x20 của L2).
  Loader PHẢI coi primitive trong suốt (0x08) như flat (không bật PN, cạnh nối với nó là cạnh thẳng): GS không tessellate
  primitive trong suốt, nếu loader vẫn để cạnh cong ở primitive đục bên cạnh thì sẽ hở khe.

Không có uniform thường mới ở bất kỳ đâu (SC chỉ đặt uniform qua ShaderOptions, uniform mới sẽ không bao giờ được đặt):
FS chỉ khai báo lại uniform 'modelIndex' và khối 'lighting' sẵn có của chương trình; GS PN dùng modelIndex + các khối
transforms/transforms2/lighting sẵn có. check_iface.py kiểm tập uniform từng chương trình không đổi.

Ngân sách GS (GL_MAX_GEOMETRY_TOTAL_OUTPUT_COMPONENTS = 1024, mức tối thiểu GL và GLES): số thành phần mỗi đỉnh
(GS_OUT + gl_Position) x max_vertices <= 1024, với max_vertices = N*N + 2N. Tính theo thành phần (đúng chữ của đặc tả);
manifest ghi thêm cách tính theo ô vec4 (driver bảo thủ) để biết bộ nào cần --max-seg 3.
"""
import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
STOCK = os.path.join(ROOT, 'game', 'gfx', 'shaders')
PN_DIR = os.path.join(HERE, 'pn')
OUT = os.path.join(ROOT, 'out', 'charfx_variants')
FILES = ('tmd.vsh', 'battle_tmd.vsh', 'tmd.gsh', 'tmd.fsh', 'battle_tmd.fsh')
PN_FILES = {'tmd.vsh': 'tmd_pn.vsh', 'battle_tmd.vsh': 'battle_tmd_pn.vsh', 'tmd.gsh': 'tmd_pn.gsh'}
GS_TOTAL_COMPONENTS = 1024
GLES_MIN_VS_OUT = 16
GLES_MIN_FS_IN = 15

# Shared by every variant (z_off must differ from 'all' ONLY in ENH_FORCE): = lt_form_bilateral of the earlier research
DEFAULTS = dict(ENH_PN=0, ENH_LIGHTING=0, ENH_TEXFILTER=0, ENH_PACK=0, ENH_FORCE=0,
                WRAP=0.35, HEMI=0.35, RIM=0.30, RIM_POWER=3.0, RIM_FACETED=0.35, RIM_LIGHT_MASK=0.6,
                TEX_MODE=3, TEX_SIGMA=0.30)

VARIANTS = {
  'z_off': dict(ENH_PN=1, ENH_LIGHTING=1, ENH_TEXFILTER=1, ENH_PACK=1, ENH_FORCE=0),
  'pn': dict(ENH_PN=1, ENH_FORCE=1),
  'l2t': dict(ENH_LIGHTING=1, ENH_TEXFILTER=1, ENH_PACK=1, ENH_FORCE=1),
  'all': dict(ENH_PN=1, ENH_LIGHTING=1, ENH_TEXFILTER=1, ENH_PACK=1, ENH_FORCE=1),
  # self-checks (lint/check_iface only)
  '_off': dict(),
}

HEADER = """#version 330 core

// [sc-vi charfx] tools/sc_charfx/make_variants.py. The ENH_* lines must be identical in tmd.vsh, battle_tmd.vsh, tmd.gsh,
// tmd.fsh and battle_tmd.fsh (they change the VS_OUT/GS_OUT interface). All 0 on the stock base = stock shader.
// ENH_PN 1: tmd.vsh / battle_tmd.vsh / tmd.gsh come from tools/sc_charfx/pn (PN-triangles, active only with the loader's PN bits;
// with ENH_FORCE 0 in tmd.gsh also only when lights[modelIndex].backgroundColour.w > 0)
#define ENH_PN {ENH_PN}
#define ENH_LIGHTING {ENH_LIGHTING}
#define ENH_TEXFILTER {ENH_TEXFILTER}
#define ENH_PACK {ENH_PACK}
"""

# ---------------------------------------------------------------- vertex shader, stock base (L2 = lt_form_bilateral)

VS_MEMBERS = """  smooth float depthOffset;
#if ENH_LIGHTING
  /** xyz: model-space normal (TMD), w: material red */
  smooth vec4 enhNormalMatR;
  /** xyz: model-space vector towards the eye (not normalised, linear in position), w: material green */
  smooth vec4 enhEyeMatG;
#endif
"""

VS_MAT_B = """#if ENH_LIGHTING
    // the fragment shaders always overwrite outColour.a, so vertColour.a can carry the material's blue channel
    vs_out.vertColour.a = inColour.b;
#endif
"""

VS_EYE = """  vs_out.viewspaceZ = gl_Position.z;

#if ENH_LIGHTING
  {
    // camera * model = model -> view space, eye at the origin (this is gl_Position before the PS1 H division and before
    // the projection matrix). cof = det(m) * inverse(m)^T, so transpose(cof) * v = det(m) * inverse(m) * v: the eye
    // vector in model space, where inNorm and the light rows of mat3(lightDirection) live.
    mat3 m = mat3(camera * t.model);
    mat3 cof = mat3(cross(m[1], m[2]), cross(m[2], m[0]), cross(m[0], m[1]));
    float detSign = dot(m[0], cof[0]) < 0.0 ? -1.0 : 1.0;
    vec3 toEye = projectionMode == 0 ? vec3(0.0, 0.0, -1.0) : -gl_Position.xyz;
    vs_out.enhNormalMatR = vec4(inNorm, inColour.r);
    vs_out.enhEyeMatG = vec4(transpose(cof) * toEye * detSign, inColour.g);
  }
#endif
"""

VS_LIT_LINE = ('    vs_out.vertColour.rgb = clamp(clamp(l.lightColour * clamp(l.lightDirection * vec4(inNorm, 1.0), 0.0, 8.0).rgb'
               ' + l.backgroundColour.rgb, 0.0, 8.0) * inColour.rgb, 0.0, range);\n')

# ---------------------------------------------------------------- geometry shader, both bases

GS_OUT_MEMBERS = """  smooth float depthOffset;
#if ENH_LIGHTING
  smooth vec4 enhNormalMatR;
  smooth vec4 enhEyeMatG;
#endif
#if ENH_TEXFILTER
  /** inclusive texel rect (minU, minV, maxU, maxV) retail nearest sampling can reach in this polygon */
  flat vec4 uvBounds;
#endif
"""

PACK_DECL_OLD = '  flat vec2 vertTpage;\n  flat vec2 vertClut;\n'
PACK_DECL = """#if ENH_PACK
  /** xy = vertTpage, zw = vertClut: one varying location instead of two (GLES 3.2 minimum = 15 fragment inputs) */
  flat vec4 enhTpageClut;
#else
  flat vec2 vertTpage;
  flat vec2 vertClut;
#endif
"""

PACK_EMIT_OLD = '  gs_out.vertTpage = vs_out[i].vertTpage;\n  gs_out.vertClut = vs_out[i].vertClut;\n'
PACK_EMIT = """#if ENH_PACK
  gs_out.enhTpageClut = vec4(vs_out[i].vertTpage, vs_out[i].vertClut);
#else
  gs_out.vertTpage = vs_out[i].vertTpage;
  gs_out.vertClut = vs_out[i].vertClut;
#endif
"""

GS_GLOBALS_COMMON = """#if ENH_LIGHTING
/** 0x20 = this face's vertex normals differ (smooth). Flat-lit primitives repeat normal 0 (TmdObjLoader.java:175-181). */
int enhFaceFlags;
#endif
#if ENH_TEXFILTER
vec4 polyUvBounds;
#endif
"""

GS_GLOBALS_PN_EYE = """#if ENH_LIGHTING
/** camera * model and det(m) * inverse(m) of its 3x3 part (sign-corrected), set once per primitive */
mat4 enhModelView;
mat3 enhEyeM;

/** Model-space vector towards the eye (not normalised), the same value the L2 vertex shader computes per corner */
vec3 enhEye(vec3 p) {
  vec3 toEye = projectionMode == 0 ? vec3(0.0, 0.0, -1.0) : -(enhModelView * vec4(p, 1.0)).xyz;
  return enhEyeM * toEye;
}
#endif
"""

GS_PRE_EMIT = """  avgDepth /= vertexCount;

#if ENH_LIGHTING
  enhFaceFlags = any(notEqual(vs_out[0].enhNormalMatR.xyz, vs_out[2].enhNormalMatR.xyz)) || any(notEqual(vs_out[0].enhNormalMatR.xyz, vs_out[4].enhNormalMatR.xyz)) ? 0x20 : 0;
#endif
#if ENH_TEXFILTER
  {
    // UV rect of the whole PS1 polygon; for quads adjacency slot 1 is the 4th vertex (TmdObjLoader.java:194-211)
    vec2 uvMin = min(min(vs_out[0].vertUv, vs_out[2].vertUv), vs_out[4].vertUv);
    vec2 uvMax = max(max(vs_out[0].vertUv, vs_out[2].vertUv), vs_out[4].vertUv);
    if((vs_out[0].vertFlags & 0x10) != 0) {
      uvMin = min(uvMin, vs_out[1].vertUv);
      uvMax = max(uvMax, vs_out[1].vertUv);
    }
    vec2 lo = floor(uvMin);
    polyUvBounds = vec4(lo, max(lo, ceil(uvMax) - 1.0));
  }
#endif
"""

GS_PRE_EMIT_PN_EYE = """#if ENH_LIGHTING
  {
    // = the L2 vertex shader's eye vector: cof = det(m) * inverse(m)^T of m = mat3(camera * model)
    enhModelView = camera * modelTransforms[int(modelIndex)].model;
    mat3 m = mat3(enhModelView);
    mat3 cof = mat3(cross(m[1], m[2]), cross(m[2], m[0]), cross(m[0], m[1]));
    float detSign = dot(m[0], cof[0]) < 0.0 ? -1.0 : 1.0;
    enhEyeM = transpose(cof) * detSign;
  }
#endif
"""

# stock base: emit() copies the per-corner L2 data of the vertex shader (bits above 0x1f never reach the FS: the PN
# loader writes corner/edge bits there and 0x20 is the L2 face flag)
GS_EMIT_FLAGS_STOCK = """#if ENH_LIGHTING
  gs_out.vertFlags = (vs_out[i].vertFlags & 0x1f) | enhFaceFlags;
  gs_out.enhNormalMatR = vs_out[i].enhNormalMatR;
  gs_out.enhEyeMatG = vs_out[i].enhEyeMatG;
#else
  gs_out.vertFlags = vs_out[i].vertFlags;
#endif
#if ENH_TEXFILTER
  gs_out.uvBounds = polyUvBounds;
#endif
"""

GS_FLAGS_PN = """#if ENH_LIGHTING
  gs_out.vertFlags = (vs_out[i].vertFlags & RETAIL_FLAGS) | enhFaceFlags;
#else
  gs_out.vertFlags = vs_out[i].vertFlags & RETAIL_FLAGS;
#endif
#if ENH_TEXFILTER
  gs_out.uvBounds = polyUvBounds;
#endif
"""

GS_RETAIL_L2 = """#if ENH_LIGHTING
  gs_out.enhNormalMatR = vs_out[i].enhNormalMatR;
  gs_out.enhEyeMatG = vec4(enhEye(vs_out[i].enhPosMatG.xyz), vs_out[i].enhPosMatG.w);
#endif
"""

# PN base only: the per-model runtime gate of z_off (ENH_FORCE does not change the interface, so it may differ between files)
GS_PN_FORCE = """// [sc-vi charfx] ENH_FORCE 1: PN follows the loader bits only. 0 (z_off): PN also needs lights[modelIndex].backgroundColour.w
// > 0, which stock SC never writes (QueuedModelTmd/BattleTmd.backgroundColour(): set(colour, 0.0f)) -> retail path
#define ENH_FORCE {ENH_FORCE}
"""

GS_PN_GATE_OLD = '(flags & (0x8 | PN_BLOCK)) != 0) {\n'
GS_PN_GATE = """(flags & (0x8 | PN_BLOCK)) != 0
#if !ENH_FORCE
     || lights[int(modelIndex)].backgroundColour.w <= 0.0
#endif
    ) {
"""

GS_PN_COMMENT_OLD = '// tmd.fsh / battle_tmd.fsh are unchanged: GS_OUT is identical to retail.\n'
GS_PN_COMMENT = ('// GS_OUT is identical to retail unless make_variants.py turns ENH_LIGHTING / ENH_TEXFILTER / ENH_PACK on (the fragment\n'
                 '// shaders of the same set then declare the same members).\n')

GS_PN_L2 = """#if ENH_LIGHTING
  // per-pixel lighting interpolates the PN normals of the sub-vertices (fragment shader enhLight)
  gs_out.enhNormalMatR = vec4(n, mat.r);
  gs_out.enhEyeMatG = vec4(enhEye(pos), mat.g);
#endif
"""

# ---------------------------------------------------------------- fragment shaders

FS_COMMON = """layout(location = 0) out vec4 outColour;

#if ENH_PACK
#define vertTpage enhTpageClut.xy
#define vertClut enhTpageClut.zw
#endif

#if ENH_LIGHTING || ENH_TEXFILTER
#define ENH_FORCE {ENH_FORCE} // 1 = every eligible primitive (preview, no Java). 0 = per model, see enhAmount()

uniform float modelIndex; // same uniform as the vertex shader (no new uniform)

struct Light {
  mat4 lightDirection;
  mat3 lightColour;
  vec4 backgroundColour;
};

/** 32-float (128-byte) stride, same block as the vertex shader */
layout(std140) uniform lighting {
  Light[128] lights;
};

/** Per-model switch/strength: lights[modelIndex].backgroundColour.w. Stock SC always writes 0 there
    (QueuedModelTmd/BattleTmd/Standard.backgroundColour(): set(colour, 0.0f)) -> stock output. */
float enhAmount() {
  return ENH_FORCE != 0 ? 1.0 : lights[int(modelIndex)].backgroundColour.w;
}
#endif

#if ENH_LIGHTING
const float ENH_WRAP = {WRAP:.4f};           // light wrap: 0 = PS1 Lambert
const float ENH_HEMI = {HEMI:.4f};           // ground occlusion: ambient x (1 - HEMI) on faces turned fully away from the lights
const float ENH_RIM = {RIM:.4f};             // rim strength (fraction of the scene's total light colour)
const float ENH_RIM_POWER = {RIM_POWER:.4f}; // higher = thinner rim
const float ENH_RIM_FACETED = {RIM_FACETED:.4f}; // rim factor on faces with 3 identical normals
const float ENH_RIM_LIGHT_MASK = {RIM_LIGHT_MASK:.4f}; // 0 = rim all round, 1 = rim only where the lights reach

/** Per-pixel version of the vertex shader's PS1 light equation + wrap + ground occlusion + rim. false = untouched. */
bool enhLight(bool textured, inout vec4 colour) {
  Light l = lights[int(modelIndex)];
  float amount = enhAmount();

  vec3 n = enhNormalMatR.xyz;
  vec3 e = enhEyeMatG.xyz;
  float nn = dot(n, n);
  float ee = dot(e, e);

  if(amount <= 0.0 || nn < 1.0e-8 || ee < 1.0e-12) {
    return false;
  }

  n *= inversesqrt(nn);
  e *= inversesqrt(ee);

  // Rows of mat3(lightDirection) = light vectors (towards the light) in model space, scaled like the PS1 LW matrix
  mat3 ld = mat3(l.lightDirection);
  mat3 ldT = transpose(ld);
  vec3 dots = ld * n;
  vec3 lens = vec3(length(ldT[0]), length(ldT[1]), length(ldT[2]));
  float wrap = ENH_WRAP * amount;
  vec3 intensity = clamp((dots + wrap * lens) / (1.0 + wrap), 0.0, 8.0); // wrap 0 = clamp(dots, 0, 8) as in the VS

  vec3 lum = vec3(dot(l.lightColour[0], vec3(1.0)), dot(l.lightColour[1], vec3(1.0)), dot(l.lightColour[2], vec3(1.0)));
  float lumSum = dot(lum, vec3(1.0));

  // Ground occlusion: darken the ambient on faces turned away from the brightness-weighted light axis
  // (default field light = straight up, so undersides of arms/chin/legs get darker; tops stay as stock)
  vec3 keyAxis = ldT * lum;
  float keyLen = length(keyAxis);
  float away = keyLen > 1.0e-6 ? min(dot(n, keyAxis) / keyLen, 0.0) : 0.0;
  vec3 light = l.lightColour * intensity + l.backgroundColour.rgb * (1.0 + ENH_HEMI * amount * away);

  // Rim along the silhouette, tinted by the scene's light colours (abs: inward-facing TMD normals)
  float ndv = min(abs(dot(n, e)), 1.0);
  float rim = pow(1.0 - ndv, ENH_RIM_POWER) * ENH_RIM * amount;
  if((vertFlags & 0x20) == 0) {
    rim *= ENH_RIM_FACETED;
  }
  float facing = dot(lum, min(intensity, vec3(1.0))) / max(lumSum, 1.0e-4);
  rim *= mix(1.0, facing, ENH_RIM_LIGHT_MASK);
  light += rim * 0.5 * (l.lightColour * vec3(1.0) + l.backgroundColour.rgb);

  vec3 material = vec3(enhNormalMatR.w, enhEyeMatG.w, colour.a);
  colour.rgb = clamp(clamp(light, 0.0, 8.0) * material, 0.0, textured ? 2.0 : 1.0);
  return true;
}
#endif

#if ENH_TEXFILTER
#define ENH_TEX_MODE {TEX_MODE}             // 2 = bilinear, 3 = bilateral (edge preserving), 4 = sharp bilinear
const float ENH_TEX_SIGMA = {TEX_SIGMA:.4f}; // bilateral: RGB distance where a neighbour's weight drops to 1/e
const float ENH_TEX_SHARP = 0.30;            // mode 4: blend half-width in texels

/** Raw PS1 colour (CLUT applied for 4/8bpp) of integer texel t (tpage-relative), from the LIVE VRAM and CLUT */
uint enhRawTexel(ivec2 t) {
  ivec2 page = ivec2(vertTpage);

  if(vertBpp == 2) {
    return texelFetch(tex15, page + t, 0).r;
  }

  int wordShift = 2 - vertBpp;
  uint word = texelFetch(tex15, ivec2(page.x + (t.x >> wordShift), page.y + t.y), 0).r;
  int p = int(word >> uint((t.x & widthMask) << indexShift)) & indexMask;
  return texelFetch(tex15, ivec2(int(vertClut.x) + p, int(vertClut.y)), 0).r;
}

vec3 enhRgb15(uint px) {
  return vec3(float(px & 31u), float(px >> 5u & 31u), float(px >> 10u & 31u)) * (1.0 / 31.0);
}

/** 2x2 palette-aware filter. rgb = blend, a = STP bit (0/1) of the retail texel. centre = raw retail texel (0 = discard) */
vec4 enhSampleFiltered(vec2 uv, out uint centre) {
  ivec2 lo = ivec2(floor(uvBounds.xy + uvOffset));
  ivec2 hi = ivec2(floor(uvBounds.zw + uvOffset));

  vec2 t = uv - 0.5;
  vec2 tb = floor(t);
  vec2 f = t - tb;
  ivec2 b = ivec2(tb);
  ivec2 ci = ivec2(step(vec2(0.5), f)); // which tap is floor(uv) = the texel retail sampling uses

  uvec4 r = uvec4(
    enhRawTexel(clamp(b,               lo, hi)),
    enhRawTexel(clamp(b + ivec2(1, 0), lo, hi)),
    enhRawTexel(clamp(b + ivec2(0, 1), lo, hi)),
    enhRawTexel(clamp(b + ivec2(1, 1), lo, hi))
  );

  centre = r[ci.x + ci.y * 2];

  if(centre == 0u) {
    return vec4(0.0);
  }

  if(ENH_TEX_MODE == 4) {
    f = smoothstep(vec2(0.5 - ENH_TEX_SHARP), vec2(0.5 + ENH_TEX_SHARP), f);
  }

  vec4 w = vec4((1.0 - f.x) * (1.0 - f.y), f.x * (1.0 - f.y), (1.0 - f.x) * f.y, f.x * f.y);
  uint stp = centre >> 15u;
  vec3 cc = enhRgb15(centre);
  vec3 acc = vec3(0.0);
  float ws = 0.0;

  for(int i = 0; i < 4; i++) {
    float wi = w[i];

    // never pull in transparent texels or texels of the other translucency pass
    if(r[i] == 0u || (r[i] >> 15u) != stp) {
      wi = 0.0;
    }

    vec3 c = enhRgb15(r[i]);

    if(ENH_TEX_MODE == 3) {
      vec3 d = c - cc;
      wi *= exp(-dot(d, d) / (ENH_TEX_SIGMA * ENH_TEX_SIGMA));
    }

    acc += wi * c;
    ws += wi;
  }

  // ws >= the centre weight (>= 1/16 after the bilateral factor of 1), never 0
  return vec4(acc / ws, float(stp));
}
#endif
"""

FS_CALL = """  outColour = vertColour;

#if ENH_LIGHTING
  if({GATE}) {
    enhLight(textured, outColour);
  }
#endif
"""

FS_TEX = """#if ENH_TEXFILTER
    uint enhCentre;
    if({TEXGATE} && enhAmount() > 0.0) {
      texColour = enhSampleFiltered(vertUv + uvOffset, enhCentre);
      if(enhCentre == 0u) {
        discard;
      }
    } else
#endif
    if(vertBpp == 0 || vertBpp == 1) {
      // Calculate CLUT index"""

GATES = {
  'tmd.fsh': ('(vertFlags & 0x1) != 0 && !translucent && projectionMode != 0',
              'vertBpp != 3 && (vertFlags & 0x1) != 0'),
  'battle_tmd.fsh': ('(vertFlags & 0x1) != 0 && !translucent && !ctmd && !uniformLit && projectionMode != 0',
                     'vertBpp != 3 && (vertFlags & 0x1) != 0 && !ctmd'),
}

COMPONENTS = {'float': 1, 'int': 1, 'uint': 1, 'bool': 1, 'vec2': 2, 'ivec2': 2, 'uvec2': 2, 'vec3': 3, 'ivec3': 3,
              'uvec3': 3, 'vec4': 4, 'ivec4': 4, 'uvec4': 4}


class Fail(Exception):
    pass


def fill(template, p):
    """Replaces {KEY} / {KEY:fmt} for KEY in p only (GLSL braces are left alone)."""
    def sub(m):
        if m.group(1) not in p:
            return m.group(0)
        return format(p[m.group(1)], (m.group(2) or ':')[1:])
    return re.sub(r'\{([A-Z_]+)(:[^}]*)?\}', sub, template)


def rep(s, old, new, where):
    n = s.count(old)
    if n != 1:
        raise Fail('%s: chuoi can sua xuat hien %d lan (can dung 1): %r' % (where, n, old[:70]))
    return s.replace(old, new)


def rep_in_block(s, start, end, old, new, where):
    """rep() limited to the first block that starts with `start` and ends at the next `end`."""
    i = s.find(start)
    if i < 0:
        raise Fail('%s: khong thay khoi %r' % (where, start))
    j = s.find(end, i)
    if j < 0:
        raise Fail('%s: khoi %r khong co %r' % (where, start, end))
    return s[:i] + rep(s[i:j], old, new, where + ' ' + start) + s[j:]


def build_vs(name, src, p, pn):
    s = rep(src, '#version 330 core\n', fill(HEADER, p), name)
    if pn:
        return s  # the PN vertex shader already carries everything L2/T/PN need (normal, position, material)
    s = rep(s, '  smooth float depthOffset;\n} vs_out;', VS_MEMBERS + '} vs_out;', name)
    s = rep(s, VS_LIT_LINE, VS_LIT_LINE + VS_MAT_B, name)
    s = rep(s, '  vs_out.viewspaceZ = gl_Position.z;\n', VS_EYE, name)
    return s


def build_gs(src, p, pn, max_seg):
    name = 'tmd.gsh'
    s = rep(src, '#version 330 core\n', fill(HEADER, p), name)
    s = rep_in_block(s, 'out GS_OUT {', '} gs_out;', '  smooth float depthOffset;\n', GS_OUT_MEMBERS, name)
    s = rep_in_block(s, 'out GS_OUT {', '} gs_out;', PACK_DECL_OLD, PACK_DECL, name)
    s = rep(s, PACK_EMIT_OLD, PACK_EMIT, name)
    if not pn:
        s = rep(s, '  smooth float depthOffset;\n} vs_out[];', VS_MEMBERS + '} vs_out[];', name)
        s = rep(s, 'void emit(int, float);\n', 'void emit(int, float);\n\n' + GS_GLOBALS_COMMON, name)
        s = rep(s, '  avgDepth /= vertexCount;\n', GS_PRE_EMIT, name)
        s = rep(s, '  gs_out.vertFlags = vs_out[i].vertFlags;\n', GS_EMIT_FLAGS_STOCK, name)
        return s
    protos = 'void emitRetail(int, float);\nvoid emitPN(float, float, float);\n'
    s = rep(s, GS_PN_COMMENT_OLD, GS_PN_COMMENT, name)
    s = rep(s, 'const int PN_ENABLE = 0x800;\n', fill(GS_PN_FORCE, p) + 'const int PN_ENABLE = 0x800;\n', name)
    s = rep(s, GS_PN_GATE_OLD, GS_PN_GATE, name)
    s = rep(s, protos, protos + '\n' + GS_GLOBALS_COMMON + GS_GLOBALS_PN_EYE, name)
    s = rep(s, '  avgDepth /= vertexCount;\n', GS_PRE_EMIT + GS_PRE_EMIT_PN_EYE, name)
    s = rep(s, '  gs_out.vertFlags = vs_out[i].vertFlags & RETAIL_FLAGS;\n', GS_FLAGS_PN, name)
    s = rep(s, '  gs_out.depthOffset = vs_out[i].depthOffset;\n', '  gs_out.depthOffset = vs_out[i].depthOffset;\n' + GS_RETAIL_L2, name)
    s = rep(s, '  gs_out.vertColour = colour;\n', '  gs_out.vertColour = colour;\n' + GS_PN_L2, name)
    return set_segments(s, choose_segments(s, p, max_seg), name)


def build_fs(name, src, p):
    gate, texgate = GATES[name]
    s = rep(src, '#version 330 core\n', fill(HEADER, p), name)
    s = rep_in_block(s, 'in GS_OUT {', '};', '  smooth float depthOffset;\n', GS_OUT_MEMBERS, name)
    s = rep_in_block(s, 'in GS_OUT {', '};', PACK_DECL_OLD, PACK_DECL, name)
    s = rep(s, 'layout(location = 0) out vec4 outColour;\n', fill(FS_COMMON, p), name)
    s = rep(s, '  outColour = vertColour;\n', FS_CALL.replace('{GATE}', gate), name)
    s = rep(s, '    if(vertBpp == 0 || vertBpp == 1) {\n      // Calculate CLUT index', FS_TEX.replace('{TEXGATE}', texgate), name)
    return s


def preprocess(src, p):
    """Tiny subset of the GLSL preprocessor for our own blocks: #if/#else/#endif with ENH_* names, ||, &&, !."""
    out, stack = [], []
    for line in src.split('\n'):
        t = line.strip()
        if t.startswith('#if '):
            expr = t[4:].replace('||', ' or ').replace('&&', ' and ').replace('!', ' not ')
            expr = re.sub(r'\b[A-Z_][A-Z0-9_]*\b', lambda m: str(int(p.get(m.group(0), 0))), expr)
            stack.append(bool(eval(expr, {'__builtins__': {}})))  # only digits/and/or/not after the substitution
            continue
        if t == '#else':
            stack[-1] = not stack[-1]
            continue
        if t == '#endif':
            stack.pop()
            continue
        if all(stack):
            out.append(line)
    if stack:
        raise Fail('#if khong dong')
    return '\n'.join(out)


def block_members(src, start, end):
    i = src.find(start)
    j = src.find(end, i)
    if i < 0 or j < 0:
        raise Fail('khong thay khoi ' + start)
    body = re.sub(r'/\*.*?\*/', '', src[i + len(start):j], flags=re.S)
    body = re.sub(r'//[^\n]*', '', body)
    members = []
    for decl in body.split(';'):
        w = decl.split()
        if not w:
            continue
        typ = w[-2]
        if typ not in COMPONENTS:
            raise Fail('kieu la trong khoi %s: %r' % (start, decl))
        members.append((typ, w[-1]))
    return members


def gs_budget(gs_src, p):
    """(GS_OUT locations, components per vertex incl. gl_Position, vec4-slot components incl. gl_Position)."""
    members = block_members(preprocess(gs_src, p), 'out GS_OUT {', '} gs_out;')
    comps = sum(COMPONENTS[t] for t, _ in members) + 4
    return len(members), comps, (len(members) + 1) * 4


def choose_segments(gs_src, p, max_seg):
    _, comps, _ = gs_budget(gs_src, p)
    for n in range(min(4, max_seg), 1, -1):
        if (n * n + 2 * n) * comps <= GS_TOTAL_COMPONENTS:
            return n
    raise Fail('GS_OUT %d thanh phan/dinh: khong du ngan sach cho PN 2 doan' % comps)


def set_segments(s, n, where):
    s = rep(s, 'max_vertices = 24) out;', 'max_vertices = %d) out;' % (n * n + 2 * n), where)
    return rep(s, 'const int PN_MAX_SEG = 4;', 'const int PN_MAX_SEG = %d;' % n, where)


def read_lf(path):
    with open(path, encoding='utf-8', newline='') as fh:
        return fh.read().replace('\r\n', '\n')


def check_pn_sources(stock, pn):
    """pn/*.vsh = stock + inserted lines only; pn/tmd_pn.gsh keeps the stock interface, culling and average depth."""
    for f in ('tmd.vsh', 'battle_tmd.vsh'):
        a, b = stock[f].split('\n'), pn[f].split('\n')
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag not in ('equal', 'insert'):
                raise Fail('pn/%s lech shader goc %s o dong goc %d-%d (%s): PN chi duoc chen dong' % (PN_FILES[f], f, i1 + 1, i2, tag))
    g, s = pn['tmd.gsh'], stock['tmd.gsh']
    i = s.index('  // If any vertex is too close')
    j = s.index('  avgDepth /= vertexCount;\n') + len('  avgDepth /= vertexCount;\n')
    if s[i:j] not in g:
        raise Fail('pn/tmd_pn.gsh: doan cull + avgDepth khong con giong tmd.gsh goc')
    if block_members(g, 'out GS_OUT {', '} gs_out;') != block_members(s, 'out GS_OUT {', '} gs_out;'):
        raise Fail('pn/tmd_pn.gsh: GS_OUT khac tmd.gsh goc')
    vs_pn = block_members(g, 'in VS_OUT {', '} vs_out[];')
    vs_stock = block_members(s, 'in VS_OUT {', '} vs_out[];')
    if vs_pn[:len(vs_stock)] != vs_stock:
        raise Fail('pn/tmd_pn.gsh: VS_OUT khong bat dau bang VS_OUT goc')
    for f in ('tmd.vsh', 'battle_tmd.vsh'):
        if block_members(pn[f], 'out VS_OUT {', '} vs_out;') != vs_pn:
            raise Fail('pn/%s: VS_OUT khac pn/tmd_pn.gsh' % PN_FILES[f])
    if 'max_vertices = 24) out;' not in g or 'const int PN_MAX_SEG = 4;' not in g:
        raise Fail('pn/tmd_pn.gsh: thieu max_vertices = 24 / PN_MAX_SEG = 4')


def build_variant(stock, pn, p, max_seg):
    use_pn = bool(p['ENH_PN'])
    base = pn if use_pn else stock
    out = {}
    for f in ('tmd.vsh', 'battle_tmd.vsh'):
        out[f] = build_vs(f, base[f], p, use_pn)
    out['tmd.gsh'] = build_gs(base['tmd.gsh'], p, use_pn, max_seg)
    for f in ('tmd.fsh', 'battle_tmd.fsh'):
        out[f] = build_fs(f, stock[f], p)
    return out


def info(files, p):
    gs = preprocess(files['tmd.gsh'], p)
    vs_n = len(block_members(gs, 'in VS_OUT {', '} vs_out[];'))
    gs_n, comps, slots = gs_budget(files['tmd.gsh'], p)
    m = re.search(r'max_vertices = (\d+)\)', files['tmd.gsh'])
    mv = int(m.group(1))
    return dict(vs_out_locations=vs_n, gs_out_locations=gs_n, gs_components_per_vertex=comps, gs_vec4_components_per_vertex=slots,
                max_vertices=mv, gs_total_components=comps * mv, gs_total_vec4_components=slots * mv)


def write_set(d, files):
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
    for f, text in files.items():
        with open(os.path.join(d, f), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text)
    return {f: hashlib.sha256(files[f].encode('utf-8')).hexdigest() for f in sorted(files)}


def main(argv):
    ap = argparse.ArgumentParser(description='dung bo shader thu charfx')
    ap.add_argument('--out', default=OUT)
    ap.add_argument('--stock', default=STOCK)
    ap.add_argument('--max-seg', type=int, default=4)
    a = ap.parse_args(argv)
    if not 2 <= a.max_seg <= 4:
        print('LOI: --max-seg phai la 2..4')
        return 1
    try:
        stock = {}
        for f in FILES:
            stock[f] = read_lf(os.path.join(a.stock, f))
            with open(os.path.join(a.stock, f), 'rb') as fh:
                if b'\r' in fh.read():
                    raise Fail('%s khong phai LF (shader trong game phai giu nguyen LF)' % f)
        pn = {f: read_lf(os.path.join(PN_DIR, PN_FILES[f])) for f in PN_FILES}
        check_pn_sources(stock, pn)

        os.makedirs(a.out, exist_ok=True)
        manifest = {'stock': a.stock, 'max_seg_limit': a.max_seg, 'variants': {}}
        for v, over in VARIANTS.items():
            p = dict(DEFAULTS, **over)
            files = build_variant(stock, pn, p, a.max_seg)
            row = info(files, p)
            if row['vs_out_locations'] > GLES_MIN_VS_OUT or row['gs_out_locations'] > GLES_MIN_FS_IN:
                raise Fail('%s: VS_OUT %d / GS_OUT %d vi tri, vuot muc toi thieu GLES 3.2 (%d / %d)' % (
                    v, row['vs_out_locations'], row['gs_out_locations'], GLES_MIN_VS_OUT, GLES_MIN_FS_IN))
            if row['gs_total_components'] > GS_TOTAL_COMPONENTS:
                raise Fail('%s: GS %d thanh phan > %d' % (v, row['gs_total_components'], GS_TOTAL_COMPONENTS))
            row['switches'] = {k: p[k] for k in ('ENH_PN', 'ENH_LIGHTING', 'ENH_TEXFILTER', 'ENH_PACK', 'ENH_FORCE')}
            row['sha256'] = write_set(os.path.join(a.out, v), files)
            manifest['variants'][v] = row
            print('%-6s PN=%d L=%d T=%d PACK=%d FORCE=%d  VS_OUT %2d  GS_OUT %2d  max_vertices %2d  GS %4d thanh phan (%4d theo o vec4)' % (
                v, p['ENH_PN'], p['ENH_LIGHTING'], p['ENH_TEXFILTER'], p['ENH_PACK'], p['ENH_FORCE'], row['vs_out_locations'],
                row['gs_out_locations'], row['max_vertices'], row['gs_total_components'], row['gs_total_vec4_components']))

        # _pnraw: the three pn/ files untouched (segments as in 'pn') + stock FS -> must transpile like 'pn'
        n_pn = manifest['variants']['pn']['max_vertices']
        raw = {f: pn[f] for f in PN_FILES}
        seg = {24: 4, 15: 3, 8: 2}[n_pn]
        raw['tmd.gsh'] = set_segments(raw['tmd.gsh'], seg, 'pn/tmd_pn.gsh')
        raw.update({f: stock[f] for f in ('tmd.fsh', 'battle_tmd.fsh')})
        manifest['variants']['_pnraw'] = {'sha256': write_set(os.path.join(a.out, '_pnraw'), raw), 'switches': None}
        print('_pnraw (3 file pn/ nguyen trang + FS goc, tu kiem)')

        with open(os.path.join(a.out, 'manifest.json'), 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(manifest, fh, indent=1, sort_keys=True)
        print('DAT: %d bo -> %s' % (len(manifest['variants']), a.out))
        return 0
    except (Fail, OSError) as e:
        print('LOI:', e)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
