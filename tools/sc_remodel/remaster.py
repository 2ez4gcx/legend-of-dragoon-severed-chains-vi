"""remaster.py — thử "remaster tự động" mô hình nhân vật LoD trong Blender (chạy không giao diện), dựng ảnh gốc | remaster.

Cách gọi (từ thư mục gốc repo, Blender 5.2 portable ở deps/blender):
  deps/blender/blender-5.2.2-windows-x64/blender.exe -b --factory-startup --python tools/sc_remodel/remaster.py -- \
      work/upscale/remodel/dart_battle [--views full34,closeup,back34,face] [--yaw độ] [--engine eevee|cycles] [--samples 64]
      [--levels 2] [--split 20] [--hard 40] [--sharp 120] [--tip 200] [--hardmode crease|bevel] [--hard-crease 0.9] [--bevel 4]
      [--inflate -1] [--bump 0.25] [--res 900] [--only goc|remaster] [--no-export] [--az full34=-5,back34=160]
  --views: full34 (toàn thân 3/4 trước), closeup (nửa người trên/đầu), back34 (3/4 sau), face (mặt), front, turn (8 hướng,
           chỉ bản gốc). Mặc định full34,closeup,back34. Hướng mặt tự dò từ mặt 'đề can' mắt/miệng (texel trong suốt); không có
           đề can -> 0 (nhìn về -Y); --yaw ghi đè.
Đầu vào: <dir>/<name>.json (export_tmd.py), <dir>/<name>_atlas.png (texture gốc), <dir>/<name>_atlas_x4.png (upscale_atlas.py).
Đầu ra:  <dir>/remaster/<view>_goc.png, <view>_remaster.png (RGBA nền trong suốt; make_sheet.py ghép lên nền xám),
         <dir>/remaster/<name>_remaster.blend, <name>_remaster.glb (lưới đã áp modifier, mỗi phần một đối tượng, giữ pivot),
         <dir>/remaster/report.json (số tam giác, số cạnh theo loại, thời gian từng bước, thông số).

Hai bản dựng cùng cảnh, cùng máy quay, cùng 3 đèn (key/fill/rim), cùng toạ độ:
  GỐC     = lưới TMD nguyên bản (đỉnh dùng chung như TMD), pháp tuyến TMD từng góc (Gouraud như SC), texture nearest,
            backface culling như TmdObjLoader (mặt đục).
  REMASTER = mỗi phần: hàn đỉnh trùng -> định hướng mặt nhất quán (theo pháp tuyến TMD) -> phân loại cạnh:
            TMD tách pháp tuyến (>= --split) và góc nhị diện >= --hard: cạnh cứng (crease --hard-crease, hoặc Bevel 2 đoạn
            --bevel % nếu --hardmode bevel); tách nhẹ: crease 0.4; góc >= --sharp: crease 1 + sharp; đỉnh có tổng góc mặt < --tip:
            crease đỉnh (mũi tóc, mũi kiếm); đường nối UV -> seam (chỉ đánh dấu). (Chỉ dùng góc thì không được: ống 6 cạnh đã 60°.)
            -> "bơm thể tích": P1 = lồng có mặt giới hạn Catmull-Clark đi qua đỉnh gốc (lặp điểm bất động, use_limit_surface);
            lồng = P0 + f*(P1-P0), f chọn để thể tích lưới subdivision = thể tích TMD của phần (--inflate -1; tay chân không teo)
            -> Subdivision Surface (Catmull-Clark, --levels, crease, UV 'NONE' = nội suy tuyến tính, bố cục UV y nguyên)
            -> shade smooth + sharp. Mặt trùng tập đỉnh cùng chiều (đề can mắt/miệng) -> đối tượng con partNN_decal: subdivision
            + Shrinkwrap bám mặt remaster (bản gốc: đỉnh riêng đẩy ra 0.5 đơn vị PS1 thay cho thứ tự vẽ PS1). Mặt trùng tập đỉnh
            ngược chiều (mặt sau tấm hai mặt, layer 'back'): bản gốc giữ (đỉnh riêng, culling chọn mặt), remaster bỏ (vật liệu hai mặt).
            Vật liệu: atlas x4 lọc tuyến tính, alpha clip 0.5, bump nhẹ từ độ sáng texture (--bump, 0 = tắt).
  Pivot/thứ tự phần không đổi: đối tượng partNN, gốc toạ độ = gốc đối tượng TMD, matrix_world = khung 0 của hoạt cảnh.
Toạ độ: PS1 (x phải, y xuống, z vào) -> Blender (x, z, -y) * tỉ lệ (chiều cao mô hình = 1.8 m).
Ảnh suy ra từ dữ liệu Sony: chỉ để xem trên máy (work/upscale bị .gitignore), không commit, không phát hành.
"""
import argparse
import json
import math
import os
import sys
import time

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

T0 = time.perf_counter()
TIMES = {}


def tick(name, t):
    TIMES[name] = round(TIMES.get(name, 0.0) + time.perf_counter() - t, 3)


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    ap = argparse.ArgumentParser(prog='remaster.py')
    ap.add_argument('dir')
    ap.add_argument('--views', default='full34,closeup,back34')
    ap.add_argument('--yaw', type=float, default=None, help='do: huong mat nhan vat (mac dinh tu do bang mat de can mat/mieng)')
    ap.add_argument('--az', default='', help='ghi de goc may quay tung view: full34=-5,back34=160 (do)')
    ap.add_argument('--engine', choices=['eevee', 'cycles'], default='eevee')
    ap.add_argument('--samples', type=int, default=64)
    ap.add_argument('--levels', type=int, default=2)
    ap.add_argument('--hard', type=float, default=40.0, help='goc nhi dien toi thieu (do) cua canh cung khi TMD tach phap tuyen')
    ap.add_argument('--split', type=float, default=20.0, help='do lech phap tuyen TMD (do) coi la tach')
    ap.add_argument('--sharp', type=float, default=120.0, help='goc nhi dien (do) -> crease 1 + sharp du TMD chung phap tuyen')
    ap.add_argument('--hardmode', choices=['crease', 'bevel'], default='crease')
    ap.add_argument('--tip', type=float, default=200.0, help='tong goc mat quanh dinh (do) duoi nguong -> crease dinh (mui nhon)')
    ap.add_argument('--hard-crease', type=float, default=0.9, help='crease cho canh cung (hardmode crease)')
    ap.add_argument('--bevel', type=float, default=4.0, help='hardmode bevel: %% do dai canh ke')
    ap.add_argument('--inflate', type=float, default=-1.0, help='<0: tu chon de giu the tich; 0: tat; >0: he so co dinh')
    ap.add_argument('--bump', type=float, default=0.25)
    ap.add_argument('--res', type=int, default=900, help='chieu cao anh (px)')
    ap.add_argument('--no-export', action='store_true')
    ap.add_argument('--only', choices=['goc', 'remaster'], help='chi dung mot ban (thu nhanh)')
    return ap.parse_args(argv)


A = parse_args()
DIR = os.path.abspath(A.dir)
NAME = os.path.basename(DIR.rstrip('\\/'))
OUT = os.path.join(DIR, 'remaster')
os.makedirs(OUT, exist_ok=True)
DOC = json.load(open(os.path.join(DIR, NAME + '.json'), encoding='utf-8'))
M = Matrix(((1, 0, 0), (0, 0, 1), (0, -1, 0)))       # PS1 -> Blender (quay 90° quanh X, giữ chiều xoay mặt)
MN = np.array(M)
FLIP = bool(DOC.get('loop_reversed_for_outward'))
W_AT, H_AT = DOC['atlas_size']
REPORT = dict(name=NAME, blender=bpy.app.version_string, args=vars(A), source=DOC['source'])


def srgb_to_linear(c):
    c = np.asarray(c, float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


# ------------------------------------------------------------------ dựng lưới từ JSON
def posed_bbox(scale=1.0):
    pts = []
    for p in DOC['parts']:
        V = np.array(p['verts'], float)
        if len(V) == 0:
            continue
        R = np.array(p['kf0_matrix']); T = np.array(p['kf0_trans'], float)
        pts.append(((V @ R.T + T) @ MN.T) * scale)
    P = np.concatenate(pts)
    return P.min(0), P.max(0)


lo, hi = posed_bbox()
SCALE = 1.8 / float(hi[2] - lo[2])
REPORT['scale_m_per_psx'] = SCALE


def part_layers(part):
    """Tách mặt của phần: (base, decal, back, dropped). Mặt có cùng tập đỉnh và cùng chiều = lớp đề can (mắt/miệng vẽ chồng lên
    da: PS1 dựa vào thứ tự vẽ, z-buffer thì đánh nhau); cùng tập đỉnh nhưng ngược chiều = mặt sau của tấm hai mặt ('back').
    Lấy theo trường 'layer' của export_tmd.py; JSON cũ không có thì tự phân loại cùng quy tắc (mặt ít texel trong suốt nhất
    trong nhóm là nền)."""
    groups, order, dropped = {}, [], 0
    for f in part['faces']:
        loop = f['loop'][::-1] if FLIP else f['loop']
        vids = [f['vidx'][c] for c in loop]
        if len(set(vids)) != len(vids):
            dropped += 1
            continue
        key = tuple(sorted(vids))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(dict(f=f, loop=loop, vids=vids))
    out = dict(base=[], decal=[], back=[])
    for key in order:
        g = sorted(groups[key], key=lambda m: m['f'].get('transp_frac', 0.0) if m['f']['textured'] else -1.0)
        g0 = np.array(g[0]['f']['geo_normal'])
        for k, m in enumerate(g):
            layer = m['f'].get('layer')
            if layer not in out:
                layer = 'base' if k == 0 else ('back' if float(np.dot(g0, m['f']['geo_normal'])) < 0 else 'decal')
            out[layer].append(m)
    return out['base'], out['decal'], out['back'], dropped


def geo_normal_b(f):
    g = np.array(f['geo_normal']) @ MN.T
    g = -g if FLIP else g
    return g / (np.linalg.norm(g) + 1e-12)


def build_mesh(part, name, custom_normals, layers=('base', 'decal', 'back'), decal_offset=0.5):
    """Lưới Blender từ JSON. layers: 'base' dùng đỉnh chung như TMD; 'decal' = mặt đề can với đỉnh riêng, đẩy ra theo pháp tuyến
    decal_offset đơn vị PS1 (bản gốc: thay cho thứ tự vẽ của PS1); 'back' = mặt sau của tấm hai mặt, đỉnh riêng không đẩy
    (Blender không cho hai mặt cùng tập đỉnh; backface culling của bản gốc chọn mặt nào hiện)."""
    V = (np.array(part['verts'], float) @ MN.T) * SCALE
    base, decal, back, dropped = part_layers(part)
    verts = [tuple(v) for v in V]
    faces, metas = [], []
    if 'base' in layers:
        for m in base:
            faces.append(m['vids']); metas.append(m)
    for layer, ms, off in (('decal', decal, decal_offset), ('back', back, 0.0)):
        if layer not in layers:
            continue
        for m in ms:
            g = geo_normal_b(m['f'])
            ids = []
            for vid in m['vids']:
                ids.append(len(verts))
                verts.append(tuple(V[vid] + g * off * SCALE))
            faces.append(ids); metas.append(m)
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    nl = len(me.loops)
    uv = np.zeros((nl, 2)); col = np.ones((nl, 4)); nrm = np.zeros((nl, 3)); mat = np.zeros(len(faces), int)
    li = 0
    for poly, m in zip(me.polygons, metas):
        f, loop = m['f'], m['loop']
        assert poly.loop_total == len(loop)
        g = geo_normal_b(f)
        mat[poly.index] = 0 if f['textured'] else 1
        for k, c in enumerate(loop):
            if f['textured']:
                uv[li + k] = (f['uv'][c][0] / W_AT, 1.0 - f['uv'][c][1] / H_AT)
            if f['colours'] is not None:
                # TmdObjLoader: màu đỉnh của mặt CÓ texture tính theo thang 0..2 (0x80 = 1.0); tmd.fsh kẹp tích về [0,1]
                k2 = 2.0 if f['textured'] else 1.0
                col[li + k, :3] = srgb_to_linear(k2 * np.array(f['colours'][c]) / 255.0)
            n = np.array(f['normals'][c]) @ MN.T if f['normals'] is not None else g
            nrm[li + k] = n / np.linalg.norm(n) if np.linalg.norm(n) > 1e-9 else g
        li += poly.loop_total
    uvl = me.uv_layers.new(name='UVMap')
    uvl.data.foreach_set('uv', uv.reshape(-1))
    ca = me.color_attributes.new('Col', 'FLOAT_COLOR', 'CORNER')
    ca.data.foreach_set('color', col.reshape(-1))
    tn = me.attributes.new('tmd_n', 'FLOAT_VECTOR', 'CORNER')
    tn.data.foreach_set('vector', nrm.reshape(-1))
    me.polygons.foreach_set('material_index', mat)
    me.shade_smooth()
    if custom_normals:
        me.normals_split_custom_set([tuple(n) for n in nrm])
    me.update()
    return me, dict(dropped_degenerate=dropped, decal_faces=len(decal) if 'decal' in layers else 0,
                    back_faces=len(back) if 'back' in layers else 0, back_faces_all=len(back), faces=len(faces))


def part_matrix(part):
    R = Matrix(part['kf0_matrix'])
    T = Vector(part['kf0_trans'])
    return Matrix.Translation(M @ T * SCALE) @ (M @ R @ M.transposed()).to_4x4()


# ------------------------------------------------------------------ vật liệu
def principled(nt):
    for n in nt.nodes:
        if n.type == 'BSDF_PRINCIPLED':
            return n
    return nt.nodes.new('ShaderNodeBsdfPrincipled')


def set_input(node, names, value):
    for nm in names:
        if nm in node.inputs:
            node.inputs[nm].default_value = value
            return


def make_material(name, image=None, interp='Closest', bump=0.0, cull=True):
    mat = bpy.data.materials.new(name)
    if hasattr(mat, 'use_nodes'):
        try:
            mat.use_nodes = True
        except Exception:
            pass
    nt = mat.node_tree
    bsdf = principled(nt)
    set_input(bsdf, ['Roughness'], 0.55)
    set_input(bsdf, ['Specular IOR Level', 'Specular'], 0.3)
    colattr = nt.nodes.new('ShaderNodeVertexColor')
    colattr.layer_name = 'Col'
    if image is not None:
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = image
        tex.interpolation = interp
        tex.extension = 'EXTEND'
        mix = nt.nodes.new('ShaderNodeMix')
        mix.data_type = 'RGBA'
        mix.blend_type = 'MULTIPLY'
        mix.inputs['Factor'].default_value = 1.0
        mix.clamp_result = True   # như clamp(vertColour * texColour, 0, 1) của tmd.fsh
        nt.links.new(tex.outputs['Color'], mix.inputs[6])
        nt.links.new(colattr.outputs['Color'], mix.inputs[7])
        nt.links.new(mix.outputs[2], bsdf.inputs['Base Color'])
        gt = nt.nodes.new('ShaderNodeMath')
        gt.operation = 'GREATER_THAN'
        gt.inputs[1].default_value = 0.5
        nt.links.new(tex.outputs['Alpha'], gt.inputs[0])
        nt.links.new(gt.outputs[0], bsdf.inputs['Alpha'])
        if bump > 0:
            bw = nt.nodes.new('ShaderNodeRGBToBW')
            nt.links.new(tex.outputs['Color'], bw.inputs[0])
            bn = nt.nodes.new('ShaderNodeBump')
            bn.inputs['Strength'].default_value = bump
            bn.inputs['Distance'].default_value = 0.004
            nt.links.new(bw.outputs[0], bn.inputs['Height'])
            nt.links.new(bn.outputs['Normal'], bsdf.inputs['Normal'])
    else:
        nt.links.new(colattr.outputs['Color'], bsdf.inputs['Base Color'])
    mat.use_backface_culling = cull
    try:
        mat.surface_render_method = 'DITHERED'
    except Exception:
        pass
    return mat


# ------------------------------------------------------------------ remaster từng phần
def orient_components(bm):
    """Định hướng mặt nhất quán từng mảnh liên thông, rồi chọn chiều khớp đa số pháp tuyến TMD."""
    lay = bm.loops.layers.float_vector.get('tmd_n')
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    seen = set()
    flipped = 0
    for f0 in bm.faces:
        if f0.index in seen:
            continue
        comp, stack = [], [f0]
        seen.add(f0.index)
        while stack:
            f = stack.pop()
            comp.append(f)
            for e in f.edges:
                for g in e.link_faces:
                    if g.index not in seen:
                        seen.add(g.index); stack.append(g)
        score = 0.0
        for f in comp:
            n = Vector((0, 0, 0))
            for l in f.loops:
                n += Vector(l[lay])
            score += f.normal.dot(n) * f.calc_area()
        if score < 0:
            bmesh.ops.reverse_faces(bm, faces=comp)
            flipped += len(comp)
    return flipped


def loop_at(f, v):
    for l in f.loops:
        if l.vert == v:
            return l
    return None


def classify_edges(bm, stats):
    lay_n = bm.loops.layers.float_vector.get('tmd_n')
    uvl = bm.loops.layers.uv.active
    crease = bm.edges.layers.float.get('crease_edge') or bm.edges.layers.float.new('crease_edge')
    bev = bm.edges.layers.float.get('bevel_weight_edge') or bm.edges.layers.float.new('bevel_weight_edge')
    for e in bm.edges:
        e[crease] = 0.0; e[bev] = 0.0; e.smooth = True; e.seam = False
        lf = e.link_faces
        if len(lf) == 1:
            stats['boundary'] += 1
            continue
        if len(lf) > 2:
            e[crease] = 1.0; e.smooth = False
            stats['nonmanifold'] += 1
            continue
        f1, f2 = lf
        ang = math.degrees(f1.normal.angle(f2.normal, 0.0))
        nsplit = 0.0
        uvsplit = f1.material_index != f2.material_index
        for v in e.verts:
            l1, l2 = loop_at(f1, v), loop_at(f2, v)
            a, b = Vector(l1[lay_n]), Vector(l2[lay_n])
            if a.length > 1e-9 and b.length > 1e-9:
                nsplit = max(nsplit, math.degrees(a.angle(b, 0.0)))
            if (l1[uvl].uv - l2[uvl].uv).length > 1e-6:
                uvsplit = True
        if uvsplit:
            e.seam = True
            stats['uv_seam'] += 1
        # Quy tắc: TMD tách pháp tuyến = người làm gốc muốn cạnh cứng (chỉ góc nhị diện thì không phân biệt được: ống 6 cạnh
        # đã 60°). Cạnh chung pháp tuyến TMD = mượt, trừ khi quá nhọn (mũi tóc, lưỡi kiếm).
        if ang >= A.sharp:
            e[crease] = 1.0; e.smooth = False
            stats['sharp_crease'] += 1
        elif nsplit >= A.split and ang >= A.hard:
            if A.hardmode == 'bevel' and A.bevel > 0:
                e[bev] = 1.0
            else:
                e[crease] = A.hard_crease
                e.smooth = A.hard_crease < 1.0
            stats['hard'] += 1
        elif nsplit >= A.split and ang >= 15.0:
            e[crease] = 0.4
            stats['soft_crease'] += 1
        else:
            stats['smooth'] += 1
    # mũi nhọn (đầu chỏm tóc, mũi kiếm): tổng góc các mặt quanh đỉnh nhỏ -> crease đỉnh 1 để Catmull-Clark không làm tù
    vcrease = bm.verts.layers.float.get('crease_vert') or bm.verts.layers.float.new('crease_vert')
    for v in bm.verts:
        v[vcrease] = 0.0
        if v.is_boundary or not v.link_faces:
            continue
        total = math.degrees(sum(l.calc_angle() for l in v.link_loops))
        if total < A.tip:
            v[vcrease] = 1.0
            stats['tip_vertices'] += 1


def eval_coords(obj, n):
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get('co', co)
    ev.to_mesh_clear()
    return co.reshape(-1, 3)[:n]


def eval_volume(obj, centre):
    """Thể tích có dấu (nón từ tâm phần) của lưới đã áp modifier — dùng được cả với phần hở."""
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    vol = mesh_volume(me, centre)
    ev.to_mesh_clear()
    return vol


def mesh_volume(me, centre):
    me.calc_loop_triangles()
    co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', co); co = co.reshape(-1, 3) - centre
    tri = np.empty(len(me.loop_triangles) * 3, int); me.loop_triangles.foreach_get('vertices', tri); tri = tri.reshape(-1, 3)
    if len(tri) == 0:
        return 0.0
    a, b, c = co[tri[:, 0]], co[tri[:, 1]], co[tri[:, 2]]
    return float(np.einsum('ij,ij->i', a, np.cross(b, c)).sum() / 6.0)


def inflate(obj, stats, iters=8):
    """Bơm thể tích: P1 = lồng có mặt giới hạn Catmull-Clark đi qua đỉnh gốc (lặp điểm bất động, Subsurf use_limit_surface);
    lồng cuối = P0 + f*(P1 - P0) (mặt giới hạn tuyến tính theo lồng), f chọn bằng chia đôi để thể tích lưới subdivision
    (cùng --levels, chưa bevel) = thể tích TMD gốc của phần đó. --inflate < 0: tự động (mặc định); > 0: f cố định; 0: tắt."""
    me = obj.data
    n = len(me.vertices)
    if n == 0 or A.inflate == 0:
        return
    P0 = np.empty(n * 3); me.vertices.foreach_get('co', P0); P0 = P0.reshape(-1, 3)
    centre = P0.mean(0)
    v_orig = mesh_volume(me, centre)
    ev = np.empty(len(me.edges) * 2, int); me.edges.foreach_get('vertices', ev); ev = ev.reshape(-1, 2)
    el = np.linalg.norm(P0[ev[:, 0]] - P0[ev[:, 1]], axis=1)
    acc = np.zeros(n); cnt = np.zeros(n)
    np.add.at(acc, ev[:, 0], el); np.add.at(acc, ev[:, 1], el); np.add.at(cnt, ev[:, 0], 1); np.add.at(cnt, ev[:, 1], 1)
    avg = np.maximum(acc / np.maximum(cnt, 1), 1e-9)
    mod = obj.modifiers.new('tmp_limit', 'SUBSURF')
    mod.levels = 1; mod.render_levels = 1; mod.use_limit_surface = True; mod.use_creases = True
    mod.boundary_smooth = 'PRESERVE_CORNERS'; mod.quality = 3; mod.uv_smooth = 'NONE'
    L0 = eval_coords(obj, n)
    if np.any(np.linalg.norm(L0 - P0, axis=1) > 1.5 * avg):   # thứ tự đỉnh của lưới subdivision không như giả định
        stats['inflate_skipped'] += 1
        obj.modifiers.remove(mod)
        return
    P = P0.copy()
    for _ in range(iters):
        P = P + (P0 - eval_coords(obj, n))
        me.vertices.foreach_set('co', P.reshape(-1)); me.update()
    resid = np.linalg.norm(P0 - eval_coords(obj, n), axis=1) / avg
    D = P - P0
    lim = 0.6 * avg

    def cage(f):
        d = f * D
        dl = np.linalg.norm(d, axis=1)
        over = dl > lim
        d[over] *= (lim[over] / dl[over])[:, None]
        return P0 + d

    def vol_at(f):
        me.vertices.foreach_set('co', cage(f).reshape(-1)); me.update()
        return eval_volume(obj, centre)

    mod.levels = A.levels; mod.render_levels = A.levels
    v0 = vol_at(0.0)
    if A.inflate > 0:
        f = A.inflate
    elif abs(v_orig) < 1e-12 or v0 * v_orig <= 0:
        f = 0.5   # phần dẹt/hở không đo được thể tích: lấy giữa
        stats['inflate_fixed_half'] += 1
    else:
        sgn = 1.0 if v_orig > 0 else -1.0
        lo_f, hi_f = 0.0, 1.5
        if sgn * v0 >= sgn * v_orig:
            f = 0.0
        elif sgn * vol_at(hi_f) <= sgn * v_orig:
            f = hi_f
        else:
            for _ in range(10):
                mid = 0.5 * (lo_f + hi_f)
                if sgn * vol_at(mid) < sgn * v_orig:
                    lo_f = mid
                else:
                    hi_f = mid
            f = 0.5 * (lo_f + hi_f)
    v1 = vol_at(f)
    obj.modifiers.remove(mod)
    stats['parts_inflate'].append(dict(part=obj.name, f=round(f, 3), vol_ratio_plain=round(v0 / v_orig, 3) if v_orig else None,
                                       vol_ratio_final=round(v1 / v_orig, 3) if v_orig else None,
                                       limit_resid_rel=round(float(resid.max()), 3),
                                       max_move_rel=round(float(np.max(np.linalg.norm(cage(f) - P0, axis=1) / avg)), 3)))
    stats['vol_orig'] += abs(v_orig); stats['vol_plain'] += abs(v0); stats['vol_final'] += abs(v1)


def remaster_part(part, coll, mats, stats):
    me, info = build_mesh(part, part['name'] + '_remaster', custom_normals=False, layers=('base',))
    # mặt 'back' (mặt sau tấm hai mặt) không đưa vào remaster: vật liệu remaster hai mặt, mặt nền đã hiện cả hai phía
    stats['back_faces_skipped'] += info['back_faces_all']
    bm = bmesh.new()
    bm.from_mesh(me)
    nv0 = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=0.25 * SCALE)
    stats['merged_verts'] += nv0 - len(bm.verts)
    bmesh.ops.dissolve_degenerate(bm, edges=list(bm.edges), dist=1e-6)
    # mặt trùng tập đỉnh sau khi hàn (hai mặt lưng nhau) -> giữ một
    seen, dups = {}, []
    for f in bm.faces:
        k = tuple(sorted(v.index for v in f.verts))
        if k in seen:
            dups.append(f)
        else:
            seen[k] = f
    if dups:
        bmesh.ops.delete(bm, geom=dups, context='FACES_ONLY')
        stats['backtoback_removed'] += len(dups)
    bm.faces.ensure_lookup_table(); bm.verts.index_update(); bm.faces.index_update()
    stats['faces_flipped'] += orient_components(bm)
    bm.normal_update()
    classify_edges(bm, stats)
    for f in bm.faces:
        f.smooth = True
    bm.to_mesh(me)
    bm.free()
    if me.attributes.get('sharp_face'):
        me.attributes.remove(me.attributes['sharp_face'])
    obj = bpy.data.objects.new(part['name'] + '_remaster', me)
    coll.objects.link(obj)
    obj.matrix_world = part_matrix(part)
    obj.data.materials.append(mats['rem_tex']); obj.data.materials.append(mats['rem_vcol'])
    t = time.perf_counter()
    inflate(obj, stats)
    tick('inflate', t)
    if A.hardmode == 'bevel' and A.bevel > 0:
        b = obj.modifiers.new('Bevel', 'BEVEL')
        b.limit_method = 'WEIGHT'; b.offset_type = 'PERCENT'; b.width_pct = A.bevel; b.segments = 2
        b.use_clamp_overlap = True; b.profile = 0.5; b.miter_outer = 'MITER_ARC'
    s = obj.modifiers.new('Subdivision', 'SUBSURF')
    s.levels = A.levels; s.render_levels = A.levels; s.quality = 3; s.use_creases = True
    s.uv_smooth = 'NONE'; s.boundary_smooth = 'PRESERVE_CORNERS'; s.use_limit_surface = True; s.use_custom_normals = False
    obj['tmd_object'] = part['index']
    # lớp đề can: đối tượng con, subdivision rồi Shrinkwrap bám mặt remaster (cách bề mặt 0.5 đơn vị PS1)
    dme, dinfo = build_mesh(part, part['name'] + '_decal', custom_normals=False, layers=('decal',), decal_offset=0.0)
    if dinfo['decal_faces']:
        dob = bpy.data.objects.new(part['name'] + '_decal', dme)
        coll.objects.link(dob)
        dob.parent = obj
        dob.matrix_parent_inverse = Matrix.Identity(4)
        dme.materials.append(mats['rem_tex']); dme.materials.append(mats['rem_vcol'])
        ds = dob.modifiers.new('Subdivision', 'SUBSURF')
        ds.levels = A.levels; ds.render_levels = A.levels; ds.quality = 3; ds.uv_smooth = 'NONE'
        ds.boundary_smooth = 'PRESERVE_CORNERS'
        sw = dob.modifiers.new('Shrinkwrap', 'SHRINKWRAP')
        sw.target = obj; sw.wrap_method = 'NEAREST_SURFACEPOINT'; sw.wrap_mode = 'ABOVE_SURFACE'; sw.offset = 0.5 * SCALE
        dob['tmd_object'] = part['index']; dob['layer'] = 'decal'
        stats['decal_faces'] += dinfo['decal_faces']
        stats['decal_objects'].append(dob.name)
    return obj


# ------------------------------------------------------------------ cảnh, đèn, máy quay
def setup_scene():
    sc = bpy.context.scene
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    import warnings
    warnings.filterwarnings('ignore', category=DeprecationWarning)
    if A.engine == 'cycles':
        sc.render.engine = 'CYCLES'
        try:
            prefs = bpy.context.preferences.addons['cycles'].preferences
            for dev in ('OPTIX', 'CUDA'):
                try:
                    prefs.compute_device_type = dev
                    prefs.get_devices()
                    if any(d.type == dev for d in prefs.devices):
                        for d in prefs.devices:
                            d.use = d.type == dev
                        sc.cycles.device = 'GPU'
                        REPORT['cycles_device'] = dev
                        break
                except Exception:
                    continue
        except Exception as e:
            REPORT['cycles_device'] = 'CPU (%s)' % e
        sc.cycles.samples = A.samples
        sc.cycles.use_denoising = True
    else:
        sc.render.engine = 'BLENDER_EEVEE'
        sc.eevee.taa_render_samples = A.samples
        try:
            sc.eevee.use_raytracing = True
            sc.eevee.use_shadows = True
        except Exception:
            pass
    sc.render.film_transparent = True
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGBA'
    sc.view_settings.view_transform = 'Standard'
    sc.view_settings.look = 'None'
    world = bpy.data.worlds.new('grey')
    sc.world = world
    try:
        world.use_nodes = True
    except Exception:
        pass
    bg = world.node_tree.nodes.get('Background') or world.node_tree.nodes.new('ShaderNodeBackground')
    bg.inputs['Color'].default_value = (0.5, 0.5, 0.5, 1)
    bg.inputs['Strength'].default_value = 0.3
    return sc


def add_light(name, kind, energy, size):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    if kind == 'AREA':
        ld.size = size
    ob = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def look_at(ob, target):
    d = Vector(target) - ob.location
    ob.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()


def sph(center, az, el, dist):
    a, e = math.radians(az), math.radians(el)
    return Vector(center) + dist * Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))


def place_view(cam, lights, center, height, az, el, aspect, lens=70.0):
    cam.data.lens = lens
    cam.data.sensor_fit = 'VERTICAL'
    cam.data.sensor_height = 24.0
    fov = 2 * math.atan(12.0 / lens)
    dist = (height * 0.5 * 1.12) / math.tan(fov / 2)
    cam.location = sph(center, az, el, dist)
    look_at(cam, center)
    cam.data.clip_start = dist * 0.05; cam.data.clip_end = dist * 10
    key, fill, rim = lights
    R = dist * 0.9
    key.location = sph(center, az - 40, 35, R); look_at(key, center)
    fill.location = sph(center, az + 50, 10, R); look_at(fill, center)
    rim.location = sph(center, az + 165, 40, R); look_at(rim, center)
    s = (R / 5.0) ** 2   # năng lượng tỉ lệ bình phương khoảng cách
    key.data.energy = 450 * s; fill.data.energy = 140 * s; rim.data.energy = 500 * s
    for l in lights:
        l.data.size = height * 0.6


def face_yaw():
    """Hướng mặt nhân vật (độ, quy ước góc máy quay của sph) từ các mặt 'đề can' (mắt/miệng: texel trong suốt >= 20%):
    trung bình pháp tuyến TMD đã quay theo khung 0. Không có đề can -> 0 (mặt nhìn về -Y)."""
    acc = np.zeros(3)
    for part in DOC['parts']:
        R = np.array(part['kf0_matrix'])
        for f in part['faces']:
            if f.get('transp_frac', 0.0) >= 0.2 and f['normals'] is not None:
                acc += MN @ (R @ np.array(f['normals']).sum(0))
    if np.hypot(acc[0], acc[1]) < 1e-9:
        return 0.0, False
    return math.degrees(math.atan2(acc[0], -acc[1])), True


def head_part(objs_by_part):
    """Phần 'đầu': trong các phần có cạnh bbox < 40% chiều cao mô hình, phần có đỉnh bbox cao nhất."""
    lo2, hi2 = posed_bbox(SCALE)
    H = hi2[2] - lo2[2]
    best, bz = None, -1e9
    for i, part in enumerate(DOC['parts']):
        V = np.array(part['verts'], float)
        if len(V) == 0:
            continue
        R = np.array(part['kf0_matrix']); T = np.array(part['kf0_trans'], float)
        P = ((V @ R.T + T) @ MN.T) * SCALE
        ext = P.max(0) - P.min(0)
        if ext.max() < 0.4 * H and P[:, 2].max() > bz:
            best, bz = (i, P.min(0), P.max(0)), P[:, 2].max()
    return best


# ------------------------------------------------------------------ main
def main():
    sc = setup_scene()
    t = time.perf_counter()
    img1 = bpy.data.images.load(os.path.join(DIR, NAME + '_atlas.png'))
    x4p = os.path.join(DIR, NAME + '_atlas_x4.png')
    img4 = bpy.data.images.load(x4p) if os.path.isfile(x4p) else img1
    REPORT['texture_remaster'] = os.path.basename(x4p) if os.path.isfile(x4p) else 'atlas 1x (khong co x4)'
    for im in (img1, img4):
        im.alpha_mode = 'STRAIGHT'
    mats = dict(orig_tex=make_material('orig_tex', img1, 'Closest', 0.0, True),
                orig_vcol=make_material('orig_vcol', None, cull=True),
                rem_tex=make_material('rem_tex', img4, 'Linear', A.bump, False),
                rem_vcol=make_material('rem_vcol', None, cull=False))
    c_orig = bpy.data.collections.new('goc'); sc.collection.children.link(c_orig)
    c_rem = bpy.data.collections.new('remaster'); sc.collection.children.link(c_rem)
    orig_objs, rem_objs = [], []
    build = dict(dropped_degenerate=0, decal_faces=0, back_faces=0)
    for part in DOC['parts']:
        me, info = build_mesh(part, part['name'], custom_normals=True)
        build['dropped_degenerate'] += info['dropped_degenerate']; build['decal_faces'] += info['decal_faces']
        build['back_faces'] += info['back_faces']
        ob = bpy.data.objects.new(part['name'], me)
        c_orig.objects.link(ob)
        ob.matrix_world = part_matrix(part)
        me.materials.append(mats['orig_tex']); me.materials.append(mats['orig_vcol'])
        ob['tmd_object'] = part['index']
        orig_objs.append(ob)
    tick('import_goc', t)
    REPORT['build_goc'] = build
    stats = dict(merged_verts=0, backtoback_removed=0, faces_flipped=0, boundary=0, nonmanifold=0, uv_seam=0, sharp_crease=0,
                 hard=0, soft_crease=0, smooth=0, inflate_skipped=0, inflate_fixed_half=0, vol_orig=0.0, vol_plain=0.0,
                 vol_final=0.0, parts_inflate=[], decal_faces=0, decal_objects=[], tip_vertices=0, back_faces_skipped=0)
    if A.only != 'goc':
        t = time.perf_counter()
        for part in DOC['parts']:
            rem_objs.append(remaster_part(part, c_rem, mats, stats))
        tick('remaster_build_total', t)
    REPORT['remaster_stats'] = stats

    # đếm tam giác
    def tri_count(objs):
        dg = bpy.context.evaluated_depsgraph_get()
        n = 0
        for o in objs:
            ev = o.evaluated_get(dg)
            m = ev.to_mesh()
            m.calc_loop_triangles()
            n += len(m.loop_triangles)
            ev.to_mesh_clear()
        return n
    t = time.perf_counter()
    REPORT['tris_goc'] = tri_count(orig_objs)
    rem_all = [o for r in rem_objs for o in [r] + list(r.children)]
    REPORT['tris_remaster'] = tri_count(rem_all) if rem_all else 0
    tick('evaluate_modifiers', t)
    REPORT['tris_tmd'] = DOC['tris']

    # máy quay + đèn
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
    sc.collection.objects.link(cam); sc.camera = cam
    lights = [add_light('key', 'AREA', 900, 1.0), add_light('fill', 'AREA', 300, 1.0), add_light('rim', 'AREA', 700, 1.0)]
    lo2, hi2 = posed_bbox(SCALE)
    center = (lo2 + hi2) / 2
    full_h = float(hi2[2] - lo2[2])
    head = head_part(None)
    yaw, auto = (A.yaw, False) if A.yaw is not None else face_yaw()
    REPORT['yaw'] = dict(degrees=round(yaw, 1), auto_from_decals=auto)
    AZ = {k: float(v) for k, v in (kv.split('=') for kv in A.az.split(',') if kv)}
    views = []
    for v in A.views.split(','):
        if v == 'full34':
            views.append(('full34', center, full_h * 1.02, AZ.get('full34', yaw - 35), 8, 0.75))
        elif v == 'front':
            views.append(('front', center, full_h * 1.02, AZ.get('front', yaw), 5, 0.75))
        elif v == 'back34':
            views.append(('back34', center, full_h * 1.02, AZ.get('back34', yaw + 180 - 35), 12, 0.75))
        elif v == 'closeup' and head:
            _, hlo, hhi = head
            hh = float(hhi[2] - hlo[2])
            c = Vector(((hlo[0] + hhi[0]) / 2, (hlo[1] + hhi[1]) / 2, hhi[2] - 1.15 * hh))
            views.append(('closeup', c, 2.5 * hh, AZ.get('closeup', yaw - 40), 8, 1.0))
        elif v == 'face' and head:
            _, hlo, hhi = head
            hh = float(hhi[2] - hlo[2])
            c = Vector(((hlo[0] + hhi[0]) / 2, (hlo[1] + hhi[1]) / 2, (hlo[2] + hhi[2]) / 2))
            views.append(('face', c, 1.4 * hh, AZ.get('face', yaw - 45), 4, 1.0))
        elif v == 'turn':
            for k in range(8):
                views.append(('turn%03d' % (k * 45), center, full_h * 1.02, k * 45.0, 8, 0.75))
    REPORT['head_part'] = head[0] if head else None
    renders = {}
    for (vname, c, h, az, el, aspect) in views:
        sc.render.resolution_y = A.res if not vname.startswith('turn') else 360
        sc.render.resolution_x = int(round(sc.render.resolution_y * aspect))
        place_view(cam, lights, c, h, az, el, aspect)
        for tag, coll in (('goc', c_orig), ('remaster', c_rem)):
            if vname.startswith('turn') and tag == 'remaster':
                continue
            if A.only and tag != A.only:
                continue
            c_orig.hide_render = tag != 'goc'
            c_rem.hide_render = tag != 'remaster'
            sc.render.filepath = os.path.join(OUT, '%s_%s.png' % (vname, tag))
            t = time.perf_counter()
            bpy.ops.render.render(write_still=True)
            renders['%s_%s' % (vname, tag)] = round(time.perf_counter() - t, 2)
            print('render', vname, tag, renders['%s_%s' % (vname, tag)], 's')
    REPORT['render_seconds'] = renders
    REPORT['views'] = [dict(name=v[0], azimuth=v[3], elevation=v[4]) for v in views]
    c_orig.hide_render = False; c_rem.hide_render = False

    if not A.no_export and rem_objs:
        t = time.perf_counter()
        try:
            bpy.ops.object.select_all(action='DESELECT')
            for o in rem_all:
                o.select_set(True)
            bpy.context.view_layer.objects.active = rem_objs[0]
            bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, NAME + '_remaster.glb'), export_format='GLB',
                                      use_selection=True, export_apply=True)
            REPORT['export_glb'] = NAME + '_remaster.glb'
        except Exception as e:
            REPORT['export_glb'] = 'LOI: %s' % e
        bpy.context.preferences.filepaths.save_version = 0   # không tạo .blend1
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, NAME + '_remaster.blend'))
        tick('export', t)
    TIMES['total'] = round(time.perf_counter() - T0, 2)
    REPORT['seconds'] = TIMES
    with open(os.path.join(OUT, 'report.json'), 'w', encoding='utf-8') as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=1)
    print('REMASTER_DONE', json.dumps({k: REPORT[k] for k in ('tris_tmd', 'tris_goc', 'tris_remaster')}), TIMES)


try:
    main()
except Exception:
    import traceback
    traceback.print_exc()
    sys.exit(1)
