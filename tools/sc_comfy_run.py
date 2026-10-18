"""sc_comfy_run.py — chạy AI "vẽ thêm chi tiết" cho ảnh nền cảnh qua ComfyUI (máy chủ cục bộ 127.0.0.1:8188, chỉ API).

Cách gọi (ComfyUI portable đã chạy: python_embeded\\python.exe -s ComfyUI\\main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch):
  python tools/sc_comfy_run.py seedvr2 DRGN21_25 --name seedvr2 [--src goc|x4plus] [--seed 42] [--color none|lab|wavelet|adain]
  python tools/sc_comfy_run.py sdxl DRGN21_25 --name sdxl25 --denoise 0.25 [--prompt "..."] [--steps 28] [--cfg 5] [--strength 0.8]
Đầu vào: work/upscale/goc/<cảnh>_rgb.png (gốc 1x) hoặc work/upscale/ai/<cảnh>_realesrgan-x4plus.png (x4).
Ra: work/upscale/ai/<cảnh>_<name>.raw.png (ảnh AI thô, x4) + <cảnh>_<name>.raw.json (thời gian, VRAM cao nhất, tham số).
Bước sau: python tools/sc_hd_lock.py <cảnh> --in work/upscale/ai/<cảnh>_<name>.raw.png --model <name>  (khoá màu + khoá hình + QA)
          python tools/sc_hd_layers.py <cảnh> --model <name>                                          (tách lớp cho mod)

Đồ thị:
  seedvr2  = mẫu chính thức "SeedVR2 3B Int8: Upscale Image" của ComfyUI 0.41 (utility_seedvr2_3b_int8_upscale_image.json)
             trải phẳng: LoadImage -> ResizeImageMaskNode (lanczos, x4 nếu --src goc, x1 nếu x4plus) -> SeedVR2Preprocess ->
             VAEEncodeTiled -> SeedVR2Conditioning -> KSampler (1 bước, euler/simple, denoise 1) -> VAEDecodeTiled ->
             SeedVR2PostProcessing -> SaveImage. Mô hình: diffusion_models/seedvr2_3b_int8_convrot.safetensors,
             vae/seedvr2_ema_vae_fp16.safetensors (huggingface.co/Comfy-Org/SeedVR2, Apache-2.0).
  sdxl     = img2img trên ảnh x4plus: CheckpointLoaderSimple (sd_xl_base_1.0) + ControlNet Tile (xinsir, điều kiện = chính ảnh)
             -> VAEEncodeTiled -> KSampler (dpmpp_2m/karras, denoise thấp) -> VAEDecodeTiled -> SaveImage.
Chỉ dùng thư viện chuẩn. Ảnh suy ra từ đĩa gốc: chỉ để thử trên máy (work/upscale bị .gitignore), không commit, không phát hành.
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SERVER = 'http://127.0.0.1:8188'


def api(path, data=None, ctype='application/json'):
    req = urllib.request.Request(SERVER + path, data=data, headers={'Content-Type': ctype} if data is not None else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    return json.loads(body) if body[:1] in (b'{', b'[') else body


def upload(path):
    boundary = uuid.uuid4().hex
    name = 'lodsc_' + os.path.basename(path)
    with open(path, 'rb') as f:
        content = f.read()
    body = (('--%s\r\nContent-Disposition: form-data; name="image"; filename="%s"\r\nContent-Type: image/png\r\n\r\n' % (boundary, name)).encode()
            + content + ('\r\n--%s\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n--%s--\r\n' % (boundary, boundary)).encode())
    r = api('/upload/image', body, 'multipart/form-data; boundary=' + boundary)
    return r['name']


def graph_seedvr2(image, multiplier, seed, color):
    return {
        '1': {'class_type': 'LoadImage', 'inputs': {'image': image}},
        '57': {'class_type': 'ResizeImageMaskNode', 'inputs': {'input': ['1', 0], 'resize_type': 'scale by multiplier',
                                                               'resize_type.multiplier': multiplier, 'scale_method': 'lanczos'}},
        '58': {'class_type': 'SeedVR2Preprocess', 'inputs': {'resized_images': ['57', 0]}},
        '51': {'class_type': 'VAELoader', 'inputs': {'vae_name': 'seedvr2_ema_vae_fp16.safetensors'}},
        '52': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'seedvr2_3b_int8_convrot.safetensors', 'weight_dtype': 'default'}},
        '48': {'class_type': 'VAEEncodeTiled', 'inputs': {'pixels': ['58', 0], 'vae': ['51', 0], 'tile_size': 512, 'overlap': 128,
                                                          'temporal_size': 4096, 'temporal_overlap': 8}},
        '61': {'class_type': 'SeedVR2Conditioning', 'inputs': {'model': ['52', 0], 'vae_conditioning': ['48', 0]}},
        '54': {'class_type': 'KSampler', 'inputs': {'model': ['52', 0], 'positive': ['61', 0], 'negative': ['61', 1], 'latent_image': ['48', 0],
                                                    'seed': seed, 'steps': 1, 'cfg': 1.0, 'sampler_name': 'euler', 'scheduler': 'simple',
                                                    'denoise': 1.0}},
        '55': {'class_type': 'VAEDecodeTiled', 'inputs': {'samples': ['54', 0], 'vae': ['51', 0], 'tile_size': 512, 'overlap': 128,
                                                          'temporal_size': 4096, 'temporal_overlap': 8}},
        '59': {'class_type': 'SeedVR2PostProcessing', 'inputs': {'images': ['55', 0], 'original_resized_images': ['57', 0],
                                                                 'color_correction_method': color}},
        '9': {'class_type': 'SaveImage', 'inputs': {'images': ['59', 0], 'filename_prefix': 'lodsc/out'}},
    }


def graph_sdxl(image, a):
    return {
        '1': {'class_type': 'LoadImage', 'inputs': {'image': image}},
        '2': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': 'sd_xl_base_1.0.safetensors'}},
        '3': {'class_type': 'CLIPTextEncode', 'inputs': {'text': a.prompt, 'clip': ['2', 1]}},
        '4': {'class_type': 'CLIPTextEncode', 'inputs': {'text': a.negative, 'clip': ['2', 1]}},
        '5': {'class_type': 'ControlNetLoader', 'inputs': {'control_net_name': 'xinsir_controlnet_tile_sdxl_1.0.safetensors'}},
        '6': {'class_type': 'ControlNetApplyAdvanced', 'inputs': {'positive': ['3', 0], 'negative': ['4', 0], 'control_net': ['5', 0],
                                                                  'image': ['1', 0], 'strength': a.strength, 'start_percent': 0.0,
                                                                  'end_percent': 1.0, 'vae': ['2', 2]}},
        '7': {'class_type': 'VAEEncodeTiled', 'inputs': {'pixels': ['1', 0], 'vae': ['2', 2], 'tile_size': 1024, 'overlap': 64,
                                                         'temporal_size': 64, 'temporal_overlap': 8}},
        '8': {'class_type': 'KSampler', 'inputs': {'model': ['2', 0], 'positive': ['6', 0], 'negative': ['6', 1], 'latent_image': ['7', 0],
                                                   'seed': a.seed, 'steps': a.steps, 'cfg': a.cfg, 'sampler_name': 'dpmpp_2m',
                                                   'scheduler': 'karras', 'denoise': a.denoise}},
        '9': {'class_type': 'VAEDecodeTiled', 'inputs': {'samples': ['8', 0], 'vae': ['2', 2], 'tile_size': 1024, 'overlap': 64,
                                                         'temporal_size': 64, 'temporal_overlap': 8}},
        '10': {'class_type': 'SaveImage', 'inputs': {'images': ['9', 0], 'filename_prefix': 'lodsc/out'}},
    }


class VramSampler(threading.Thread):
    """Đo VRAM đang dùng của cả GPU (nvidia-smi) mỗi 0,5 s; peak = cao nhất (gồm cả ứng dụng khác)."""

    def __init__(self):
        super().__init__(daemon=True)
        self.peak = 0
        self.stop = False

    def run(self):
        while not self.stop:
            try:
                out = subprocess.run(['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'],
                                     capture_output=True, text=True, timeout=5).stdout
                self.peak = max(self.peak, int(out.strip().splitlines()[0]))
            except Exception:
                pass
            time.sleep(0.5)


def run(graph, out_png, meta):
    client = uuid.uuid4().hex
    sampler = VramSampler()
    sampler.start()
    t0 = time.time()
    pid = api('/prompt', json.dumps({'prompt': graph, 'client_id': client}).encode())['prompt_id']
    while True:
        time.sleep(1.0)
        hist = api('/history/' + pid)
        if pid in hist:
            h = hist[pid]
            break
        if time.time() - t0 > 3600:
            sys.exit('LOI: qua 1 gio chua xong')
    sampler.stop = True
    elapsed = time.time() - t0
    status = h.get('status', {})
    if status.get('status_str') != 'success':
        msgs = [m for m in status.get('messages', []) if m[0] == 'execution_error']
        print('LOI ComfyUI:', json.dumps(msgs, ensure_ascii=False)[:2000])
        sys.exit(1)
    imgs = [img for o in h['outputs'].values() for img in o.get('images', [])]
    q = urllib.parse.urlencode({'filename': imgs[0]['filename'], 'subfolder': imgs[0]['subfolder'], 'type': imgs[0]['type']})
    data = api('/view?' + q)
    with open(out_png, 'wb') as f:
        f.write(data)
    meta.update({'seconds': round(elapsed, 1), 'peak_vram_mib': sampler.peak})
    with open(out_png[:-4] + '.json', 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print('%s: %.1f s, VRAM cao nhat %d MiB -> %s' % (meta['scene'], elapsed, sampler.peak, out_png))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['seedvr2', 'sdxl'])
    ap.add_argument('scene')
    ap.add_argument('--name', required=True)
    ap.add_argument('--src', choices=['goc', 'x4plus'], default=None)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--color', default='none', choices=['none', 'lab', 'wavelet', 'adain'])
    ap.add_argument('--denoise', type=float, default=0.25)
    ap.add_argument('--steps', type=int, default=28)
    ap.add_argument('--cfg', type=float, default=5.0)
    ap.add_argument('--strength', type=float, default=0.8)
    ap.add_argument('--prompt', default='detailed photograph, natural light, sharp focus, realistic textures, high detail')
    ap.add_argument('--negative', default='painting, cartoon, blurry, text, watermark, people, oversaturated, lowres')
    ap.add_argument('--goc', default=os.path.join(ROOT, 'work', 'upscale', 'goc'))
    ap.add_argument('--ai', default=os.path.join(ROOT, 'work', 'upscale', 'ai'))
    a = ap.parse_args()

    src = a.src or ('goc' if a.mode == 'seedvr2' else 'x4plus')
    if a.mode == 'sdxl' and src != 'x4plus':
        sys.exit('LOI: sdxl can anh x4plus lam dau vao (--src x4plus)')
    path = os.path.join(a.goc, a.scene + '_rgb.png') if src == 'goc' else os.path.join(a.ai, a.scene + '_realesrgan-x4plus.png')
    if not os.path.isfile(path):
        sys.exit('LOI: khong thay ' + path)
    image = upload(path)
    meta = {k: v for k, v in vars(a).items() if k not in ('goc', 'ai')}
    meta['src'] = src
    if a.mode == 'seedvr2':
        graph = graph_seedvr2(image, 4.0 if src == 'goc' else 1.0, a.seed, a.color)
    else:
        graph = graph_sdxl(image, a)
    run(graph, os.path.join(a.ai, '%s_%s.raw.png' % (a.scene, a.name)), meta)


if __name__ == '__main__':
    main()
