"""check_export.py — kiểm tra độc lập (trong Blender) file glTF của export_tmd.py và GLB remaster của remaster.py.

Cách gọi (từ thư mục gốc repo):
  deps/blender/blender-5.2.2-windows-x64/blender.exe -b --factory-startup --python tools/sc_remodel/check_export.py -- \
      work/upscale/remodel/dart_battle [work/upscale/remodel/dart_field ...]
Với mỗi thư mục <name>: nạp <name>.json làm chuẩn rồi
  1. nhập <name>.gltf bằng bộ nhập glTF của Blender: đủ một đối tượng partNN mỗi phần TMD (+ partNN_decal / partNN_back khi
     JSON có mặt layer đó), tổng tam giác =
     số tam giác TMD, ma trận thế giới mỗi phần = khung 0 (quay M·R·Mᵀ, dời M·T·0.001; M: PS1 -> Blender (x, z, -y)),
     UV mọi góc mặt textured khớp texel atlas/kích thước (đọc lại theo vị trí đỉnh);
  2. nhập remaster/<name>_remaster.glb: đủ partNN_remaster (+ partNN_decal khi JSON có mặt đề can), gốc toạ độ từng phần = pivot
     TMD (M·T·tỉ lệ, tỉ lệ = 1.8 m / chiều cao mô hình) và hướng quay = khung 0, mọi UV nằm trong [0,1], mọi UV góc mặt TMD vẫn có
     trong lưới GLB của phần đó (uv_smooth NONE: bố cục atlas giữ nguyên), số tam giác = report.json.
  3. atlas: <name>_atlas_x4.png đúng 4x kích thước <name>_atlas.png.
In từng lỗi; exit 0 = đạt, 1 = lỗi.
"""
import json
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector

M = Matrix(((1, 0, 0), (0, 0, 1), (0, -1, 0)))
MN = np.array(M)


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for m in list(bpy.data.meshes):
        bpy.data.meshes.remove(m)


def tris(o):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = o.evaluated_get(dg)
    me = ev.to_mesh()
    me.calc_loop_triangles()
    n = len(me.loop_triangles)
    ev.to_mesh_clear()
    return n


def check_dir(d, errors):
    name = os.path.basename(d.rstrip('\\/'))
    doc = json.load(open(os.path.join(d, name + '.json'), encoding='utf-8'))
    W, H = doc['atlas_size']
    parts = doc['parts']
    # 1. glTF của export_tmd
    clear()
    bpy.ops.import_scene.gltf(filepath=os.path.join(d, name + '.gltf'))
    objs = {o.name: o for o in bpy.data.objects if o.type == 'MESH'}
    total = 0
    for p in parts:
        o = objs.get(p['name'])
        nt = sum(2 if f['quad'] else 1 for f in p['faces'])
        if nt == 0:
            continue
        if o is None:
            errors.append('%s.gltf: thieu %s' % (name, p['name']))
            continue
        total += tris(o)
        for layer in ('decal', 'back'):
            if objs.get(p['name'] + '_' + layer) is not None:
                total += tris(objs[p['name'] + '_' + layer])
            elif any(f.get('layer') == layer for f in p['faces']):
                errors.append('%s.gltf: thieu %s_%s (JSON co mat layer %s)' % (name, p['name'], layer, layer))
        R = Matrix(p['kf0_matrix'])
        want_t = M @ Vector(p['kf0_trans']) * 0.001
        want_r = M @ R @ M.transposed()
        mw = o.matrix_world
        if (mw.to_translation() - want_t).length > 1e-5:
            errors.append('%s.gltf %s: doi %s != %s' % (name, p['name'], tuple(mw.to_translation()), tuple(want_t)))
        r3 = mw.to_3x3().normalized()
        if max(abs(r3[i][j] - want_r[i][j]) for i in range(3) for j in range(3)) > 1e-4:
            errors.append('%s.gltf %s: quay sai' % (name, p['name']))
        # UV: mỗi góc của mặt textured -> tìm góc lưới nhập có cùng vị trí đỉnh và cùng UV
        me = o.data
        uvl = me.uv_layers.active
        if uvl is None:
            if any(f['textured'] for f in p['faces']):
                errors.append('%s.gltf %s: khong co UV' % (name, p['name']))
            continue
        co_l, luv_l, lv_l, off = [], [], [], 0
        for m_ in [me] + [objs[p['name'] + sfx].data for sfx in ('_decal', '_back') if p['name'] + sfx in objs]:
            if m_.uv_layers.active is None:
                continue
            co_l.append(np.array([v.co[:] for v in m_.vertices]))
            luv_l.append(np.array([d_.uv[:] for d_ in m_.uv_layers.active.data]))
            lv_l.append(np.array([l.vertex_index for l in m_.loops]) + off)
            off += len(m_.vertices)
        co, luv, lv = np.concatenate(co_l), np.concatenate(luv_l), np.concatenate(lv_l)
        V = np.array(p['verts'], float) @ np.diag([1.0, -1.0, -1.0]).T   # glTF Y lên (cục bộ), Blender nhập: (x, -z, y)
        Vb = np.stack([V[:, 0], -V[:, 2], V[:, 1]], 1)
        bad = 0
        for f in p['faces']:
            if not f['textured']:
                continue
            for c in range(len(f['vidx'])):
                pos = Vb[f['vidx'][c]]
                want = np.array([f['uv'][c][0] / W, 1.0 - f['uv'][c][1] / H])
                hit = np.nonzero(np.linalg.norm(co - pos, axis=1) < 1e-3)[0]
                ok = any(np.abs(luv[lv == h] - want).max(1).min() < 1e-5 for h in hit if (lv == h).any())
                bad += 0 if ok else 1
        if bad:
            errors.append('%s.gltf %s: %d goc UV khong khop' % (name, p['name'], bad))
    if total != doc['tris']:
        errors.append('%s.gltf: %d tam giac != TMD %d' % (name, total, doc['tris']))
    print('%s.gltf: %d phan, %d tam giac (TMD %d)' % (name, len(parts), total, doc['tris']))
    # 2. GLB remaster
    rep_p = os.path.join(d, 'remaster', 'report.json')
    glb = os.path.join(d, 'remaster', name + '_remaster.glb')
    if not os.path.isfile(glb):
        errors.append('thieu ' + glb)
        return
    rep = json.load(open(rep_p, encoding='utf-8'))
    scale = rep['scale_m_per_psx']
    clear()
    bpy.ops.import_scene.gltf(filepath=glb)
    objs = {o.name: o for o in bpy.data.objects if o.type == 'MESH'}
    total = 0
    for p in parts:
        o = objs.get(p['name'] + '_remaster')
        if o is None:
            if p['faces']:
                errors.append('%s.glb: thieu %s_remaster' % (name, p['name']))
            continue
        total += tris(o)
        want_t = M @ Vector(p['kf0_trans']) * scale
        if (o.matrix_world.to_translation() - want_t).length > 1e-4:
            errors.append('%s.glb %s: pivot %s != %s' % (name, p['name'], tuple(o.matrix_world.to_translation()), tuple(want_t)))
        want_r = M @ Matrix(p['kf0_matrix']) @ M.transposed()
        r3 = o.matrix_world.to_3x3().normalized()
        if max(abs(r3[i][j] - want_r[i][j]) for i in range(3) for j in range(3)) > 1e-4:
            errors.append('%s.glb %s: quay khac khung 0' % (name, p['name']))
        dec = objs.get(p['name'] + '_decal')
        if dec is None and any(f.get('layer') == 'decal' for f in p['faces']):
            errors.append('%s.glb: thieu %s_decal (JSON co mat de can)' % (name, p['name']))
        uvs = []
        for ob in [o] + ([dec] if dec else []):
            uvl = ob.data.uv_layers.active
            if uvl is not None and len(uvl.data):
                uv = np.array([x.uv[:] for x in uvl.data])
                uvs.append(uv)
                if uv.min() < -1e-4 or uv.max() > 1 + 1e-4:
                    errors.append('%s.glb %s: UV ngoai [0,1] (%.4f..%.4f)' % (name, ob.name, uv.min(), uv.max()))
        # bố cục UV giữ nguyên: uv_smooth NONE -> góc lưới con tại đỉnh gốc giữ đúng UV gốc; mọi UV góc mặt TMD phải có trong GLB
        # (bỏ mặt suy biến có đỉnh lặp: remaster.py bỏ chúng)
        # (bỏ mặt 'back' của tấm hai mặt: remaster.py không đưa vào remaster)
        want = np.array(sorted({(f['uv'][c][0] / W, 1.0 - f['uv'][c][1] / H) for f in p['faces']
                                if f['textured'] and f.get('layer') != 'back' and len(set(f['vidx'])) == len(f['vidx'])
                                for c in range(len(f['vidx']))}))
        if len(want):
            have = np.concatenate(uvs) if uvs else np.zeros((0, 2))
            miss = [w for w in want if not len(have) or np.abs(have - w).max(1).min() > 2e-5]
            if miss:
                errors.append('%s.glb %s: %d/%d UV goc TMD khong con trong GLB (vd %s)' % (name, p['name'], len(miss), len(want),
                                                                                        tuple(round(float(x), 5) for x in miss[0])))
        if dec is not None:
            total += tris(dec)
    if total != rep['tris_remaster']:
        errors.append('%s.glb: %d tam giac != report %d' % (name, total, rep['tris_remaster']))
    print('%s_remaster.glb: %d doi tuong luoi, %d tam giac (report %d)' % (name, len(objs), total, rep['tris_remaster']))
    # 3. atlas
    a1 = bpy.data.images.load(os.path.join(d, name + '_atlas.png'))
    a4p = os.path.join(d, name + '_atlas_x4.png')
    if os.path.isfile(a4p):
        a4 = bpy.data.images.load(a4p)
        if tuple(a4.size) != (a1.size[0] * 4, a1.size[1] * 4):
            errors.append('%s: atlas x4 %s != 4x %s' % (name, tuple(a4.size), tuple(a1.size)))
        print('%s: atlas %s -> x4 %s' % (name, tuple(a1.size), tuple(a4.size)))


def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    errors = []
    for d in argv:
        try:
            check_dir(os.path.abspath(d), errors)
        except Exception as e:   # Blender không trả mã lỗi khi script ném ngoại lệ -> tự bắt
            errors.append('%s: %s: %s' % (d, type(e).__name__, e))
    for e in errors:
        print('LOI:', e)
    if not argv:
        errors.append('chua chi thu muc nao')
    print('CHECK_EXPORT', 'DAT' if not errors else 'LOI (%d)' % len(errors))
    sys.exit(1 if errors else 0)


main()
