"""sc_hd_layers.py — dựng ảnh nền HD + các lớp tiền cảnh HD cho cảnh (submap) Severed Chains từ ảnh ghép đã upscale x4.

Cách gọi:
  python tools/sc_hd_layers.py DRGN21_25 DRGN21_37 [--goc work/upscale/goc] [--ai work/upscale/ai] [--out work/upscale/hd]
Đầu vào mỗi cảnh (tools/sc_bgdump + Real-ESRGAN):
  goc/<cảnh>_bg.png         nền gốc RGBA (alpha 0 = màu 0 trong suốt; dưới mỗi tiền cảnh là màu khoá xanh, KHÔNG upscale riêng)
  goc/<cảnh>_fg<k>.png      tiền cảnh gốc RGBA, alpha 0/255, cùng kích thước nền
  ai/<cảnh>_realesrgan-x4plus.png   x4 của ảnh ghép goc/<cảnh>_rgb.png (nền + mọi tiền cảnh)
Ra (đúng tên mà tools/sc_hdbg/HdBackgrounds.java nạp):
  out/<cảnh>.png            nền HD = ảnh ghép AI, alpha 255 (chỗ nền gốc trong suốt -> (0,0,0,0))
  out/<cảnh>_fg<k>.png      tiền cảnh HD = ảnh ghép AI trong mặt nạ (alpha gốc phóng 4x kiểu nearest), ngoài mặt nạ (0,0,0,0)
Lý do (SC affcef0 gfx/shaders/standard.fsh): lượt vẽ đặc chỉ bỏ texel có a==0 VÀ rgb==0, alpha lưng chừng vẫn vẽ đặc ->
  alpha phải 0/255, chỗ trong suốt phải đúng (0,0,0,0); tiền cảnh phải phủ cả khung, thẳng lưới với nền (quad uv 0..1).
Chỉ đúng cho cảnh có tiền cảnh đứng yên, luôn hiện (cut 7 = DRGN21_25, cut 11 = DRGN21_37: script không gọi 263, 264 chỉ mode 2).
Tự kiểm (exit 1 nếu sai): alpha nhị phân, trong suốt = (0,0,0,0), mặt nạ khớp alpha gốc, nền + tiền cảnh ghép lại == ảnh AI,
  kích thước = 4x nền gốc.
Ảnh suy ra từ đĩa gốc: chỉ để thử trên máy (work/upscale bị .gitignore), không commit, không phát hành.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')


def up4(mask):
    return np.repeat(np.repeat(mask, 4, 0), 4, 1)


def build(scene, goc, ai_dir, out):
    ok = True
    comp = np.asarray(Image.open(os.path.join(ai_dir, scene + '_realesrgan-x4plus.png')).convert('RGB'))
    bg0 = np.asarray(Image.open(os.path.join(goc, scene + '_bg.png')).convert('RGBA'))
    h, w = bg0.shape[:2]
    if comp.shape[:2] != (h * 4, w * 4):
        print('LOI %s: anh AI %s khong phai 4x nen goc %dx%d' % (scene, comp.shape[:2], w, h))
        return False

    opaque = up4(bg0[..., 3] > 0)
    bg = np.zeros((h * 4, w * 4, 4), np.uint8)
    bg[..., :3] = comp
    bg[..., 3] = 255
    bg[~opaque] = 0
    Image.fromarray(bg, 'RGBA').save(os.path.join(out, scene + '.png'))

    recomposite = bg.copy()
    k = 0
    while os.path.exists(path := os.path.join(goc, '%s_fg%d.png' % (scene, k))):
        a0 = np.asarray(Image.open(path).convert('RGBA'))[..., 3] > 0
        if a0.shape != (h, w):
            print('LOI %s fg%d: kich thuoc %s khac nen %dx%d' % (scene, k, a0.shape, w, h))
            ok = False
        mask = up4(a0)
        fg = np.zeros((h * 4, w * 4, 4), np.uint8)
        fg[mask, :3] = comp[mask]
        fg[mask, 3] = 255
        Image.fromarray(fg, 'RGBA').save(os.path.join(out, '%s_fg%d.png' % (scene, k)))

        if not set(np.unique(fg[..., 3]).tolist()) <= {0, 255}:
            print('LOI %s fg%d: alpha khong nhi phan' % (scene, k))
            ok = False
        if fg[fg[..., 3] == 0, :3].any():
            print('LOI %s fg%d: texel trong suot co rgb != 0' % (scene, k))
            ok = False
        if not np.array_equal(fg[1::4, 1::4, 3] > 0, a0):
            print('LOI %s fg%d: mat na khac alpha goc' % (scene, k))
            ok = False
        recomposite[mask] = fg[mask]
        k += 1

    same = np.array_equal(recomposite[..., :3][opaque], comp[opaque])
    if not same:
        print('LOI %s: nen + tien canh ghep lai khac anh AI' % scene)
    print('%s: %dx%d, %d tien canh, nen trong suot %d px HD, ghep lai == anh AI: %s' % (scene, w * 4, h * 4, k, np.count_nonzero(~opaque), same))
    return ok and same and k > 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('scenes', nargs='+')
    ap.add_argument('--goc', default=os.path.join(ROOT, 'work', 'upscale', 'goc'))
    ap.add_argument('--ai', default=os.path.join(ROOT, 'work', 'upscale', 'ai'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'work', 'upscale', 'hd'))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    ok = all([build(s, a.goc, a.ai, a.out) for s in a.scenes])
    print('DAT' if ok else 'LOI')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
