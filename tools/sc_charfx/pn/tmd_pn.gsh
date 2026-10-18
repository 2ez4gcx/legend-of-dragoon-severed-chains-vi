#version 330 core
// [sc-vi charfx] Runtime PN-triangle tessellation (Vlachos et al. 2001) for Severed Chains TMD models (SC affcef0).
// Drop-in replacement for gfx/shaders/tmd.gsh, which is shared by the "TMD" and "Battle TMD" programs
// (RenderEngine.java:174 and :198). Needs tmd_pn.vsh / battle_tmd_pn.vsh (VS_OUT + enhNormalMatR + enhPosMatG).
// tmd.fsh / battle_tmd.fsh are unchanged: GS_OUT is identical to retail.
//
// No uniform of its own (the uniforms of a program are set by SC's ShaderOptions only; a new uniform would never be set).
// Control = the per-corner flags float written by TmdObjLoader (inFlags, integral, exact up to 2^24):
//   0x01 LIT  0x02 TEXTURED  0x04 COLOURED  0x08 TRANSLUCENT  0x10 QUAD   (retail)
//   bits 5-6    local corner index inside the TMD primitive (0..3)
//   bits 7-10   "edge to local corner j is linear" (boundary / crease / non-manifold / flat / bends > 100 degrees)
//   bit  11     PN enabled for this primitive (lit + gouraud + opaque + model opted in)
//   bits 12-14  segments per edge (0 or 1 = retail; clamped to PN_MAX_SEG)
//   bits 15-17  strength in eighths of the classic PN offset (0 = 1.0; a loader writing 8 as 0x40000 = bit 18 also reads 1.0)
//   bit  24     set (as an int, inside the VS) by battle_tmd_pn.vsh when the whole model is drawn translucent
//               (ctmdFlags & 0x2); above anything the loader can write exactly in the float
// Segments and strength must be the same for every primitive of a model (shared edges are then sampled the same way).
// Primitives without bit 11, unlit, translucent or with segments <= 1 take the retail tmd.gsh path (emitRetail).
// The fragment shaders only ever see the retail bits (& RETAIL_FLAGS).
layout (triangles_adjacency) in;
layout (triangle_strip, max_vertices = 24) out; // N*N + 2N vertices for N = PN_MAX_SEG segments per edge

in VS_OUT {
  smooth vec2 vertUv;
  flat vec2 vertTpage;
  flat vec2 vertClut;
  flat int vertBpp;
  smooth vec4 vertColour;
  flat int vertFlags;

  flat int translucency;

  flat float widthMultiplier;
  flat int widthMask;
  flat int indexShift;
  flat int indexMask;

  smooth float viewspaceZ;

  smooth float depth;
  smooth float depthOffset;

  // [sc-vi PN] untransformed TMD data. Material blue rides in vertColour.a on lit primitives.
  /** xyz: model-space TMD normal (inNorm), w: material red (inColour.r) */
  smooth vec4 enhNormalMatR;
  /** xyz: model-space position (inPos.xyz), w: material green (inColour.g) */
  smooth vec4 enhPosMatG;
} vs_out[];

out GS_OUT {
  smooth vec2 vertUv;
  flat vec2 vertTpage;
  flat vec2 vertClut;
  flat int vertBpp;
  smooth vec4 vertColour;
  flat int vertFlags;

  flat int translucency;

  flat float widthMultiplier;
  flat int widthMask;
  flat int indexShift;
  flat int indexMask;

  smooth float depth;
  smooth float depthOffset;
} gs_out;

struct ModelTransforms {
  mat4 model;
  vec4 screenOffset;
};

struct Light {
  mat4 lightDirection;
  mat3 lightColour;
  vec4 backgroundColour;
};

layout(std140) uniform transforms {
  mat4 camera;
  mat4 projection;
};

/** 20-float (80-byte) stride */
layout(std140) uniform transforms2 {
  ModelTransforms[128] modelTransforms;
};

/** 32-float (128-byte) stride */
layout(std140) uniform lighting {
  Light[128] lights;
};

layout(std140) uniform projectionInfo {
  float znear;
  /** PS1 projection plane distance (H) */
  float zfar;
  float zdiffInv;
  /** 0: ortho, 1: PS1 perspective, 2: modern perspective */
  float projectionMode;
};

uniform int usePs1Depth;
uniform float modelIndex; // same uniform as the vertex shader

const int PN_MAX_SEG = 4;      // max_vertices above must be >= PN_MAX_SEG * PN_MAX_SEG + 2 * PN_MAX_SEG
const int PN_ENABLE = 0x800;
const int PN_BLOCK = 0x1000000;
const int RETAIL_FLAGS = 0x1f; // LIT TEXTURED COLOURED TRANSLUCENT QUAD: all the fragment shaders read

void emitRetail(int, float);
void emitPN(float, float, float);

// Patch, model space
vec3 P0, P1, P2;
vec3 N0, N1, N2;
vec3 b210, b120, b021, b012, b102, b201, b111;
vec3 n110, n011, n101;
mat4 modelView;
ModelTransforms tr;
bool texturedPrim;

vec3 safeNormalize(vec3 v) {
  float l = dot(v, v);
  return l > 1e-12 ? v * inversesqrt(l) : v;
}

/** Edge control point next to pi (towards pj). Linear edge: plain 1/3 point (no bulge, matches a flat neighbour). */
vec3 ctrl(vec3 pi, vec3 pj, vec3 ni, bool linear, float strength) {
  float w = linear ? 0.0 : strength * dot(pj - pi, ni);
  return (2.0 * pi + pj - w * ni) / 3.0;
}

/** Quadratic normal control point of an edge (reflected average); linear edge: plain average */
vec3 normalMid(vec3 pi, vec3 pj, vec3 ni, vec3 nj, bool linear) {
  vec3 s = ni + nj;
  if(!linear) {
    vec3 d = pj - pi;
    float dd = dot(d, d);
    if(dd > 1e-6) {
      s -= (2.0 * dot(d, s) / dd) * d;
    }
  }
  return safeNormalize(s);
}

/** Edge fa -> fb is linear: bit (7 + local corner index of fb) of fa. Set on both corners by the loader (per edge). */
bool edgeLinear(int fa, int fb) {
  int lb = (fb >> 5) & 0x3;
  return ((fa >> (7 + lb)) & 0x1) != 0;
}

void setupPatch(int flags) {
  P0 = vs_out[0].enhPosMatG.xyz; P1 = vs_out[2].enhPosMatG.xyz; P2 = vs_out[4].enhPosMatG.xyz;
  N0 = safeNormalize(vs_out[0].enhNormalMatR.xyz); N1 = safeNormalize(vs_out[2].enhNormalMatR.xyz); N2 = safeNormalize(vs_out[4].enhNormalMatR.xyz);

  int f0 = vs_out[0].vertFlags;
  int f1 = vs_out[2].vertFlags;
  int f2 = vs_out[4].vertFlags;
  bool l01 = edgeLinear(f0, f1);
  bool l12 = edgeLinear(f1, f2);
  bool l20 = edgeLinear(f2, f0);
  int eighths = (flags >> 15) & 0x7;
  float strength = eighths == 0 ? 1.0 : float(eighths) / 8.0;

  b210 = ctrl(P0, P1, N0, l01, strength); b120 = ctrl(P1, P0, N1, l01, strength);
  b021 = ctrl(P1, P2, N1, l12, strength); b012 = ctrl(P2, P1, N2, l12, strength);
  b102 = ctrl(P2, P0, N2, l20, strength); b201 = ctrl(P0, P2, N0, l20, strength);
  vec3 E = (b210 + b120 + b021 + b012 + b102 + b201) / 6.0;
  vec3 V = (P0 + P1 + P2) / 3.0;
  b111 = E + (E - V) * 0.5;

  n110 = normalMid(P0, P1, N0, N1, l01);
  n011 = normalMid(P1, P2, N1, N2, l12);
  n101 = normalMid(P2, P0, N2, N0, l20);

  tr = modelTransforms[int(modelIndex)];
  modelView = camera * tr.model;
  texturedPrim = (flags & 0x2) != 0;
}

// Same tail as tmd.vsh / battle_tmd.vsh (gl_Position = camera * model * pos ... projection * gl_Position)
vec4 project(vec3 p, out float depthOut) {
  vec4 g = modelView * vec4(p, 1.0);

  if(projectionMode == 1) {
    float z = clamp(g.z, 0, 65536);
    if(z != 0) {
      g.xy *= zfar / z;
    }
  }

  if(projectionMode != 2 && tr.screenOffset.z != 0) {
    g.z += tr.screenOffset.z;
  }

  g.xy += tr.screenOffset.xy;
  g = projection * g;
  depthOut = g.z;
  return g;
}

// Same as the lit branch of tmd.vsh / battle_tmd.vsh, with the curved normal
vec3 relight(vec3 n, vec3 mat) {
  Light l = lights[int(modelIndex)];
  float range = texturedPrim ? 2.0 : 1.0;
  return clamp(clamp(l.lightColour * clamp(l.lightDirection * vec4(n, 1.0), 0.0, 8.0).rgb + l.backgroundColour.rgb, 0.0, 8.0) * mat, 0.0, range);
}

void copyFlat(int i) {
  gs_out.vertTpage = vs_out[i].vertTpage;
  gs_out.vertClut = vs_out[i].vertClut;
  gs_out.vertBpp = vs_out[i].vertBpp;
  gs_out.vertFlags = vs_out[i].vertFlags & RETAIL_FLAGS;
  gs_out.translucency = vs_out[i].translucency;
  gs_out.widthMultiplier = vs_out[i].widthMultiplier;
  gs_out.widthMask = vs_out[i].widthMask;
  gs_out.indexShift = vs_out[i].indexShift;
  gs_out.indexMask = vs_out[i].indexMask;
}

void main() {
  // If any vertex is too close to the camera, cull the whole face
  if(zfar >= vs_out[0].viewspaceZ * 2.0) {
    return;
  }

  if(zfar >= vs_out[2].viewspaceZ * 2.0) {
    return;
  }

  if(zfar >= vs_out[4].viewspaceZ * 2.0) {
    return;
  }

  float avgDepth = gl_in[0].gl_Position.z + gl_in[2].gl_Position.z + gl_in[4].gl_Position.z;
  int vertexCount = 3;

  // Quad, check adjacent vertex
  if((vs_out[0].vertFlags & 0x10) != 0) {
    if(zfar >= vs_out[1].viewspaceZ * 2.0) {
      return;
    }

    avgDepth += gl_in[1].gl_Position.z;
    vertexCount++;
  }

  avgDepth /= vertexCount;

  int flags = vs_out[0].vertFlags;
  int level = min((flags >> 12) & 0x7, PN_MAX_SEG);

  // PN only for opted-in, lit, opaque primitives. Culling and the PS1 average depth above use the ORIGINAL corners.
  if(level <= 1 || (flags & PN_ENABLE) == 0 || (flags & 0x1) == 0 || (flags & (0x8 | PN_BLOCK)) != 0) {
    emitRetail(0, avgDepth);
    emitRetail(2, avgDepth);
    emitRetail(4, avgDepth);
    EndPrimitive();
    return;
  }

  setupPatch(flags);

  // level strips; the first triangle of each strip is (base, +u, +v) = same winding as (c0, c1, c2) for backface culling
  float s = 1.0 / float(level);
  for(int r = 0; r < level; r++) {
    for(int c = 0; c <= level - r; c++) {
      emitPN(float(r) * s, float(c) * s, avgDepth);

      if(c < level - r) {
        emitPN(float(r + 1) * s, float(c) * s, avgDepth);
      }
    }

    EndPrimitive();
  }
}

/** = emit() of the retail tmd.gsh (flags masked to the retail bits) */
void emitRetail(int i, float depth) {
  gs_out.vertUv = vs_out[i].vertUv;
  copyFlat(i);
  gs_out.vertColour = vs_out[i].vertColour;
  gs_out.depth = vs_out[i].depth;
  gs_out.depthOffset = vs_out[i].depthOffset;

  gl_Position = gl_in[i].gl_Position;

  if(usePs1Depth != 0) {
    gl_Position.z = depth;
  }

  EmitVertex();
}

/** One patch vertex. u -> corner 1 (vs_out[2]), v -> corner 2 (vs_out[4]), w = 1 - u - v -> corner 0 (vs_out[0]) */
void emitPN(float u, float v, float avgDepth) {
  float w = 1.0 - u - v;

  vec3 pos = P0 * (w * w * w) + P1 * (u * u * u) + P2 * (v * v * v)
           + 3.0 * (b210 * (w * w * u) + b120 * (w * u * u) + b201 * (w * w * v)
                  + b021 * (u * u * v) + b102 * (w * v * v) + b012 * (u * v * v))
           + 6.0 * b111 * (w * u * v);
  vec3 n = safeNormalize(N0 * (w * w) + N1 * (u * u) + N2 * (v * v) + n110 * (w * u) + n011 * (u * v) + n101 * (w * v));
  // material = inColour.rgb, interpolated linearly like the retail Gouraud colour
  vec3 mat = vec3(vs_out[0].enhNormalMatR.w, vs_out[0].enhPosMatG.w, vs_out[0].vertColour.a) * w
           + vec3(vs_out[2].enhNormalMatR.w, vs_out[2].enhPosMatG.w, vs_out[2].vertColour.a) * u
           + vec3(vs_out[4].enhNormalMatR.w, vs_out[4].enhPosMatG.w, vs_out[4].vertColour.a) * v;

  gs_out.vertUv = vs_out[0].vertUv * w + vs_out[2].vertUv * u + vs_out[4].vertUv * v;
  copyFlat(0);
  // retail lit colour re-evaluated with the curved normal; a = material blue (dead in the fragment shaders)
  vec4 colour = vs_out[0].vertColour * w + vs_out[2].vertColour * u + vs_out[4].vertColour * v;
  colour.rgb = relight(n, mat);
  gs_out.vertColour = colour;
  gs_out.depthOffset = vs_out[0].depthOffset;

  float d;
  gl_Position = project(pos, d);
  gs_out.depth = d;

  if(usePs1Depth != 0) {
    gl_Position.z = avgDepth; // PS1 ordering table: every sub-vertex keeps the primitive's average depth
  }

  EmitVertex();
}
