# LRM spec 1 — đặc tả chuẩn cho mô hình nhân vật remaster (route B)

Trạng thái: **đóng băng (WP0)**. Phiên bản: khoá `LRMK1`, file `LRM1` version 1, chỉ mục `LRMINDEX 1`.
Nguồn đối chiếu: Severed Chains `affcef0` (`Severed-Chains/src/main/java/...`) + sc-vi. Mọi số dòng dưới đây là của bản đó.

Tài liệu này chép lại các mục 3, 4, 5 của kiến trúc route B (giữ nguyên số mục §3.1–§3.9, §4, §5 để các gói việc
R1, R2, P1–P4, C1, T1, A1, K1 tham chiếu thẳng), bổ sung đủ kiểu, offset, giới hạn, và sửa các chỗ không nhất quán
đã phát hiện khi đối chiếu mã nguồn (Phụ lục B). Java (R1, R2) và Python (P1) cài đặt **độc lập** theo tài liệu này;
bản tham chiếu là `spec/ref_spec.py` (thư viện chuẩn + numpy), dữ liệu vàng ở Phụ lục A.

Từ khoá: PHẢI / KHÔNG ĐƯỢC = bắt buộc; NÊN = khuyến nghị. Tên định danh (trường, lớp, hằng) giữ tiếng Anh.

---

## §0. Quy ước chung

- Mọi số nguyên trong khoá, file `.lrm`, dòng băm: **little-endian**. (PNG theo chuẩn PNG, big-endian.)
- `u8/u16/u32` không dấu, `s16/s32` có dấu bù hai, `f32` = IEEE 754 binary32. Hex luôn viết **chữ thường**.
- SHA-1 theo FIPS 180-4. Khoá dạng chữ = 40 ký tự hex thường của 20 byte nhị phân.
- Phép toán `f32`: mỗi phép `+ - * /` làm tròn về binary32 ngay (ngữ nghĩa `float` của Java; `numpy.float32` từng
  phép trong Python). KHÔNG ĐƯỢC dùng FMA hay tính trung gian bằng double rồi mới làm tròn.
- Thuật ngữ:
  - **part** (phần) `i` = `model.modelParts_00[i].tmd_08` (một `TmdObjTable1c`), `i = 0 .. partCount-1`;
    `partCount = model.modelParts_00.length` = `nobj` của TMD (`Models.java:127`, `SMap.java:2865`, `Battle.java:2968`).
  - **run** = một `TmdObjTable1c.Primitive` trong `primitives_10` (các gói liên tiếp cùng mode + flag).
  - **packet đã làm phẳng** (flattened packet) / **source face** (`srcFace`): duyệt `primitives_10` theo thứ tự, trong
    mỗi run duyệt `data()` theo thứ tự. Đây đúng là thứ tự gói trong file TMD và thứ tự `TmdObjLoader.fromObjTable`
    duyệt. `srcFace` = chỉ số (0-based) trong phần. `srcFaceCount` = số gói đã làm phẳng của phần.
  - **textured face index** (`g`, toàn cục): phần theo thứ tự, rồi các gói có texture (bit `0x04` của id) theo thứ tự
    đã làm phẳng. `texturedFaceCount` = tổng trên mọi phần (kể cả phần `mode 0`).
  - **id** của gói = `header >>> 24`; `vc = 4` nếu `id & 0x08` (quad) ngược lại `3`.
  - **live**: giá trị trong bộ nhớ lúc `fromModel` chạy, tức là sau `Models.updateTmdPacketIlen` (lúc dựng
    `TmdObjTable1c`) và sau `UvAdjustmentMetrics14` (`Models.adjustModelUvs`). Không bao giờ dùng byte thô của file.
  - **corner** k = góc TMD thứ `k` (0..vc-1) của gói, theo thứ tự trong gói.
- Cờ đỉnh (TmdObjLoader.java:37-42): `LIT_FLAG 0x1`, `TEXTURED_FLAG 0x2`, `COLOURED_FLAG 0x4`, `TRANSLUCENT_FLAG 0x8`,
  `QUAD_FLAG 0x10`.

---

## §3.1. Khoá hình học LRMK1

Tính từ `TmdObjTable1c` trong bộ nhớ lúc `fromModel` (không có byte file thô ở thời điểm đó).

`partKey_i` = SHA-1 của dòng byte sau, theo đúng thứ tự:

| # | Trường | Kiểu | Giá trị |
|---|---|---|---|
| 1 | tag | 1 byte | `'P'` (0x50) |
| 2 | `n_vert` | u32 | `vert_top_00.length` |
| 3 | vertex[`n_vert`] | s16 x, s16 y, s16 z | Java: `(short)Math.round(vert_top_00[k].x)` …; = 6 byte đầu của bản ghi đỉnh 8 byte trong file |
| 4 | `n_normal` | u32 | `normal_top_08.length` |
| 5 | normal[`n_normal`] | s16 x, s16 y, s16 z | Java: `(short)Math.round(normal_top_08[k].x * 4096f)` …; chính xác vì `readSvec3_12` chia cho 4096 |
| 6 | `nPackets` | u32 | Σ `primitives_10[j].data().length` (= tổng `srcFaceCount` của phần) |
| 7 | packet[`nPackets`] | | theo thứ tự đã làm phẳng; mỗi gói gồm 7a, 7b (nếu có), 7c |
| 7a | header | u32 | `primitives_10[j].header() & 0xffff0000` (header của run chứa gói) |
| 7b | abr | u8 | **chỉ khi** gói có texture (`id & 0x04`): `(u16 tại data[6] >>> 5) & 3` |
| 7c | tail | u8[] | có texture: `data[4*vc .. size)`; không texture: `data[0 .. size)` |

`size = data.length = CtmdTransformer.primitivePacketSize(header)` (CtmdTransformer.java:263-299).

`modelKey` = SHA-1(`'LRMK1'` (5 byte ASCII) ‖ u16 `partCount` ‖ `partKey_0` ‖ … ‖ `partKey_{partCount-1}`).

Lý do các byte bị loại / giữ:
- 16 bit thấp của header bị `Models.updateTmdPacketIlen` ghi đè (số gói của run, Models.java:494-603); run được gom
  theo mode + flag = 16 bit cao, nên `header & 0xffff0000` của run bằng của từng gói trong run.
- `data[0 .. 4*vc)` của gói có texture (uv, clut, tpage) bị `UvAdjustmentMetrics14.apply` ghi đè
  (UvAdjustmentMetrics14.java:57-67; mặt nạ tpage `0xffe0ffff` và PNG `& 0x60ffff | 0x1800000` đều **giữ** bit abr
  `tpage >>> 5 & 3`), nên abr được đưa riêng vào 7b.

Mô hình hợp lệ cho khoá: gói có id `0x20..0x3f` (`TmdObjLoader.java:95`), không có cặp `textured && gradated` hay
`!textured && !lit` (`primitivePacketSize` ném lỗi), mọi lần đọc nằm trong file. Bản tham chiếu mô phỏng đúng trình tự
Java (`updateTmdPacketIlen` rồi vòng đọc run, `TmdObjTable1c.java:52-73`); trên toàn bộ dữ liệu US kết quả trùng cách
đọc từng gói theo header của chính nó (Phụ lục B).

---

## §3.2. Tham số góc (corner parameters) và đỉnh remaster

### §3.2.1. Ý nghĩa

Mỗi đỉnh remaster ("corner" của file LRM) mang `(srcFace, s, t)`, vị trí và pháp tuyến remaster, `nearestTmdVertex`.
`s`, `t` lưu dạng unorm16 (`S`, `T` là u16). Trọng số theo góc TMD của `srcFace`:
- tam giác: `(1 - s - t, s, t)` cho góc 0, 1, 2 (`s + t <= 1`);
- tứ giác: song tuyến theo thứ tự Z của PS1 — góc 0 = (s 0, t 0), 1 = (1, 0), 2 = (0, 1), 3 = (1, 1):
  `w0 = (1-s)(1-t)`, `w1 = s(1-t)`, `w2 = (1-s)t`, `w3 = st`.

uv, màu, tpage, clut **luôn dựng lại từ gói live** (không lưu trong file).

### §3.2.2. Công thức f32 chính xác (chuẩn)

```
s = (float)S / 65535f;  t = (float)T / 65535f
tam giác:  if (s + t > 1f) t = 1f - s
           w0 = (1f - s) - t;  w1 = s;  w2 = t
tứ giác:   w0 = (1f - s) * (1f - t);  w1 = s * (1f - t);  w2 = (1f - s) * t;  w3 = s * t
I(x)       = ((w0 * x0 + w1 * x1) + w2 * x2)            // tam giác
I(x)       = (((w0 * x0 + w1 * x1) + w2 * x2) + w3 * x3) // tứ giác
```
Mỗi phép làm tròn f32 (§0). Hệ quả: góc có `S, T ∈ {0, 65535}` cho đúng giá trị của góc TMD tương ứng (bản L0 identity
trùng từng bit với lưới retail, xem Phụ lục A).

### §3.2.3. 16 float của một đỉnh remaster (`VERTEX_SIZE = 16`, cùng bố cục `TmdObjLoader.createMesh`)

`f` = gói live của `corner.srcFace`; `g` = textured face index của `f`.

| Float | Thuộc tính | Giá trị |
|---|---|---|
| 0-2 | pos.xyz | `pos[corner.pos]` (f32 lưu trong file, không gian TMD-local) |
| 3 | pos.w | `(float)corner.nearestTmdVertex` |
| 4-6 | normal | `f` LIT: `(nx, ny, nz)` lưu trong file, giữ nguyên; không LIT: `0, 0, 0` |
| 7-8 | uv | có texture, bộ VRAM hoặc mặt LIVE: `I(u_k)`, `I(v_k)` với `u_k = (float)` byte uv live của góc k; nếu bpp live = 3 thì chia tiếp `/ (float)textureWidth`, `/ (float)textureHeight` (như TmdObjLoader.java:240-246). Có texture, bộ ATLAS, mặt không LIVE: `I(atlasUv[g][k][0])`, `I(atlasUv[g][k][1])`. Không texture: `0, 0` |
| 9 | tpage | có texture: `(float)tpage` live; bộ ATLAS, mặt không LIVE: `(float)((tpage & ~0x180) | 0x180)` (bpp = 3, giữ abr và bit trang). Không texture: `0` |
| 10 | clut | có texture: `(float)clut` live (cả bộ ATLAS). Không texture: `0` |
| 11-14 | colour rgba | `f` COLOURED: `I(c_k)` từng kênh, `c_k = (r/255f, g/255f, b/255f, m/255f)` của u32 màu góc k (`r = c & 0xff`, `g = c>>>8`, `b = c>>>16`, `m = c>>>24`), rồi `* 2f` cả 4 kênh nếu `f` có texture (nhân **trước** khi nội suy). Không COLOURED: `1, 1, 1, 1` |
| 15 | flags | `(float)(cờ live của f & ~QUAD_FLAG)` |

Cờ live và màu theo TmdObjLoader.java:89-186, 277-302 (`specialFlags = 0`): `lit = (id & 1) == 0`,
`textured = id & 4`, `translucent = id & 2`, `shaded = header & 0x40000` (gradated), `gourad = id & 0x10`,
`COLOURED = shaded || !lit || !textured`. Màu từng góc: `shaded || !lit` → một u32 mỗi góc; `lit && !textured &&
!shaded` → một u32 dùng cho cả vc góc. Chỉ số pháp tuyến ngoài phạm vi → pháp tuyến 0 (chỉ ảnh hưởng lưới retail).

---

## §3.3. FaceHash — danh tính texture và chốt chặn lúc chạy

### §3.3.1. Phạm vi

Mọi gói đã làm phẳng **có texture** với bpp live `b = (tpage >>> 7) & 3 ∈ {0, 1, 2}`. Mặt `b = 3` không được băm (LIVE,
§3.4 c).

### §3.3.2. Toạ độ

```
tpX = (tpage & 0xF) * 64;   tpY = (tpage & 0x10) != 0 ? 256 : 0
cx  = (clut & 0x3F) * 16;   cy  = clut >>> 6
umin..umax, vmin..vmax = min/max của các byte uv live của vc góc (bao gồm hai đầu)
V[y][x] = GPU.getPixel15(x & 1023, y & 511)   // 16 bit gồm bit STP (Gpu.java:605-608)
```
Mọi lần đọc VRAM PHẢI bọc toạ độ `x & 1023`, `y & 511` (Java: gọi `getPixel15` với toạ độ đã bọc; không để chỉ số
`y*1024 + x` tràn sang hàng sau hay ra ngoài mảng).

### §3.3.3. Duyệt texel

Vòng ngoài `v = vmin..vmax`, vòng trong `u = umin..umax`:
- `b = 0`: `idx = (V[tpY+v][tpX+(u>>2)] >> ((u&3)*4)) & 0xF`;  `px = V[cy][cx+idx]`
- `b = 1`: `idx = (V[tpY+v][tpX+(u>>1)] >> ((u&1)*8)) & 0xFF`; `px = V[cy][cx+idx]`
- `b = 2`: `px = V[tpY+v][tpX+u]`

(trùng công thức `tmd.fsh:71-89`; hộp bao uv nguyên, không xét tam giác).

### §3.3.4. Băm FNV-1a 32 bit

```
h = 0x811C9DC5
với mỗi px theo thứ tự trên:  h ^= px & 0xFF;  h *= 0x01000193;  h ^= px >>> 8;  h *= 0x01000193   (u32)
nếu h cuối = 0 thì h = 1
```
Giá trị `0` vì vậy không bao giờ là kết quả băm; nó được dành cho "không xác minh" (§3.3.5, §3.4 d).

### §3.3.5. Giá trị lưu trong biến thể (quy tắc bộ sinh)

`faceHash[g]` của một biến thể = FaceHash §3.3.4 tính trên VRAM ảo (§3.3.7), **trừ** hai trường hợp ghi `0`:
- mặt `b = 3`;
- mặt đọc ra ngoài TIM đã đặt: dấu chân word ảnh `[tpX + (umin >> sh), tpX + (umax >> sh)] × [tpY + vmin, tpY + vmax]`
  (`sh = 2, 1, 0` cho `b = 0, 1, 2`) không nằm trọn trong rect ảnh đã đặt, hoặc (`b ∈ {0,1}`) dải CLUT
  `[cx, cx + 16)` (4bpp) / `[cx, cx + 256)` (8bpp) × hàng `cy` không nằm trọn trong rect CLUT đã đặt.
  Texel như vậy đến từ VRAM không thuộc TIM nên không thể xác minh (ví dụ DRGN0/468 có 12 mặt 8bpp trên TIM 4bpp).

### §3.3.6. Véc-tơ băm

`faceHashVectorSha1` = SHA-1 của `u32 faceHash[0] ‖ … ‖ u32 faceHash[texturedFaceCount-1]` theo textured face index.
Trong `spec/vectors.json` véc-tơ là **FaceHash thô** §3.3.4 cho mọi mặt (không áp quy tắc ghi 0 của §3.3.5 cho mặt
đọc ngoài TIM); riêng mặt `b = 3` không có FaceHash nên ghi `0` (cả véc-tơ runtime mà `-Dscvi.remasterLog` in ra để so
với Python cũng PHẢI ghi `0` cho mặt `b = 3`).

### §3.3.7. VRAM ảo của bộ sinh

VRAM 1024 × 512 u16, khởi tạo 0, đặt TIM đúng như `tools/sc_remodel/export_tmd.py`:
- **battle** (`characters/<c>/models/<form>/32` + `characters/<c>/textures/<form>`), **story** DRGN0 (mô hình `N`,
  TIM `N+1`), **quái** (`SECT/DRGN0.BIN/<3137+id>/32` + `monsters/<id>/textures/combat`): ảnh và CLUT tại **rect gốc**
  trong TIM (`load_battle`); không áp UvAdjust.
- **field / world map** (`SECT/DRGN2x.BIN/<cảnh>/<obj*33>` + `textures/<obj>`): ô sobj 0 — ảnh tại (576, 256), CLUT tại
  (576, 368) với kích thước CLUT của TIM (`load_field`); rồi áp `UvAdjustmentMetrics14(0, 576, 256)` **như
  `Models.adjustPartUvs`**: chỉ các run có `header & 0xff040000` ∈ {`0x34`, `0x35`, `0x36`, `0x37`, `0x3c`, `0x3d`,
  `0x3e`, `0x3f`}`<< 24` (Models.java:55-64; `export_tmd.py` áp cho mọi gói có texture — tương đương trên dữ liệu US vì
  không có gói phẳng có texture, Phụ lục B).
- FaceHash không phụ thuộc vị trí ô VRAM (chỉ băm giá trị texel), nên lúc chạy runtime đọc `GPU.getPixel15` ở bất kỳ ô
  nào game đã đặt TIM.

---

## §3.4. Mặt LIVE (chỉ quyết định lúc chạy)

Một mặt có texture là **LIVE** nếu một trong các điều sau đúng:

- **a)** `model.clutAnimations_a4 != null` → mọi mặt của mô hình LIVE (và không dựng bộ ATLAS, §4.2).
- **b)** `model.uvAdjustments_9d != UvAdjustmentMetrics14.NONE` và tồn tại `i ∈ 0..6` với
  `m = model.animationMetrics_d0[i] != null`, `m.length >= 5` (mục ngắn hơn, ví dụ `[1, -1]` có thật trong dữ liệu, bỏ
  qua), sao cho rect đích giao dấu chân word VRAM của mặt:
  - rect: `x = m[1] + tpageX`, `y = m[2] + tpageY`, `w = m[3] / 4` (chia nguyên Java, cắt về 0), `h = m[4]`, với
    `tpageX/Y = uvAdjustments_9d.tpageX/Y`; rect rỗng khi `w <= 0` hoặc `h <= 0` (Models.java:368-465).
  - dấu chân: `x = tpX + (umin >> sh) .. tpX + (umax >> sh)`, `y = tpY + vmin .. tpY + vmax` (bao gồm hai đầu; `sh = 2`
    4bpp, `1` 8bpp, `0` 15bpp; không bọc).
  - giao khi `fx0 < x + w && x <= fx1 && fy0 < y + h && y <= fy1`.
- **c)** bpp live = 3 (ghi đè PNG, `UvAdjustmentMetrics14.PNG`).
- **d)** *(bổ sung WP0)* trong biến thể `v`, `faceHash[g] == 0` → mặt `g` LIVE **cho riêng biến thể `v`**.

LIVE theo a–c là của mô hình; LIVE của bộ ATLAS `v` = LIVE(a–c) ∪ LIVE(d, v). Mặt LIVE bị bỏ qua khi xác minh và luôn
lấy mẫu VRAM (trong bộ ATLAS chúng có đúng 16 float như bộ VRAM).

---

## §3.5. File LRM1: `remaster/models/<modelKey>.lrm`

Little-endian. Header 0x40 byte rồi thân (body) `bodySize` byte (nếu `flags` bit 0: thân được nén zlib).

### §3.5.1. Header (0x40 byte)

| Offset | Cỡ | Kiểu | Trường | Quy tắc |
|---|---|---|---|---|
| 0x00 | 4 | char[4] | `magic` | `'LRM1'` |
| 0x04 | 2 | u16 | `version` | `1` |
| 0x06 | 2 | u16 | `flags` | bit 0 = thân nén zlib (RFC 1950, `java.util.zip.Inflater()` mặc định); mọi bit khác = 0 |
| 0x08 | 20 | u8[20] | `modelKey` | SHA-1 nhị phân; = tên file; = khoá runtime |
| 0x1C | 2 | u16 | `partCount` | 1..64; = `model.modelParts_00.length` |
| 0x1E | 2 | u16 | `variantCount` | 0..4 |
| 0x20 | 4 | u32 | `bodySize` | số byte thân **sau giải nén**; <= 0x10000000 (256 MiB) |
| 0x24 | 1 | u8 | `level` | 0, 1 hoặc 2 (L0 / L1 / L2) |
| 0x25 | 3 | u8[3] | zero | = 0 |
| 0x28 | 24 | char[24] | `generator` | ASCII 0x20..0x7E, đệm 0 ở cuối (sau byte 0 đầu tiên chỉ còn 0) |
| 0x40 | — | | thân | không nén: đúng `bodySize` byte tới hết file; nén: luồng zlib kết thúc đúng ở cuối file và giải ra đúng `bodySize` byte |

### §3.5.2. Thân: `part[partCount]` rồi `variant[variantCount]`

Bản ghi phần:

| Offset | Cỡ | Kiểu | Trường | Quy tắc |
|---|---|---|---|---|
| +0x00 | 20 | u8[20] | `partKey` | §3.1 |
| +0x14 | 4 | u32 | `srcFaceCount` | = `nPackets` runtime của phần |
| +0x18 | 1 | u8 | `mode` | 0 = giữ Obj gốc, 1 = thay |
| +0x19 | 3 | u8[3] | zero | = 0 |
| +0x1C | 4 | u32 | `P` | *(chỉ mode 1)* 1..200000 |
| +0x20 | 4 | u32 | `C` | *(mode 1)* 3..200000 |
| +0x24 | 4 | u32 | `T` | *(mode 1)* 1..200000 |
| +0x28 | 12·P | f32[P][3] | `pos` | *(mode 1)* đơn vị PS1, TMD-local, y hướng xuống — cùng không gian `vert_top_00`; hữu hạn |
| … | 32·C | corner[C] | `corner` | *(mode 1)* bảng dưới |
| … | 12·T | u32[T][3] | `tri` | *(mode 1)* chỉ số corner |

Bản ghi phần mode 0 dài 28 byte; mode 1 dài `40 + 12P + 32C + 12T` byte.

Bản ghi corner (32 byte):

| Offset | Cỡ | Kiểu | Trường | Quy tắc |
|---|---|---|---|---|
| +0 | 4 | u32 | `pos` | < `P` |
| +4 | 4 | f32 | `nx` | hữu hạn |
| +8 | 4 | f32 | `ny` | hữu hạn |
| +12 | 4 | f32 | `nz` | hữu hạn (không bắt buộc đơn vị) |
| +16 | 4 | u32 | `srcFace` | < `srcFaceCount` |
| +20 | 2 | u16 | `s` | `S` của §3.2 (mọi giá trị hợp lệ, kẹp lúc chạy) |
| +22 | 2 | u16 | `t` | `T` của §3.2 |
| +24 | 2 | u16 | `nearestTmdVertex` | < `n_vert` của phần (kiểm lúc chạy); ghi vào pos.w |
| +26 | 1 | u8 | `role` | 0 base, 1 decal, 2 back |
| +27 | 1 | u8 | zero | = 0 |
| +28 | 4 | u8[4] | reserved | = 0 (đệm cho đủ 32 byte, Phụ lục B) |

`tri[T][3]`: chỉ số corner `< C`, theo **thứ tự phát của SC** (thứ tự tam giác GL mà `TmdObjLoader` tạo: góc `(2,1,0)`
và `(1,2,3)`; tam giác con giữ cùng chiều mặt với tam giác gốc, mặt `back` có chiều ngược mặt `base`). Ba corner của
một tam giác PHẢI cùng `srcFace`. Tam giác xếp theo `srcFace` tăng dần (ổn định).

Bản ghi biến thể (`28 + 36·n` byte, `n = texturedFaceCount`):

| Offset | Cỡ | Kiểu | Trường | Quy tắc |
|---|---|---|---|---|
| +0 | 20 | u8[20] | `pngSha1` | file `remaster/textures/<hex>.png` |
| +20 | 2 | u16 | `w` | luỹ thừa 2, 1..2048; = chiều rộng PNG |
| +22 | 2 | u16 | `h` | luỹ thừa 2, 1..2048; = chiều cao PNG |
| +24 | 4 | u32 | `texturedFaceCount` | = số runtime (mọi phần); như nhau ở mọi biến thể |
| +28 | 4·n | u32[n] | `faceHash` | §3.3.5 (0 = không xác minh, LIVE §3.4 d) |
| … | 32·n | f32[n][4][2] | `atlasUv` | toạ độ chuẩn hoá [0,1], thứ tự góc TMD; tam giác: góc thứ 4 = (0, 0); hữu hạn |

### §3.5.3. Giới hạn

`partCount` 1..64; `variantCount` <= 4; `P`, `C`, `T` <= 200000 mỗi phần (mode 1: `P >= 1`, `C >= 3`, `T >= 1`);
`srcFaceCount` = số runtime; `bodySize` <= 256 MiB; PNG luỹ thừa 2, <= 2048.

### §3.5.4. Kiểm tra bắt buộc khi đọc (sai một điều → cả mô hình đi đường gốc, ghi log một lần mỗi khoá)

1. File >= 0x40 byte; `magic`, `version`, bit `flags` lạ, byte zero header, `generator`, `partCount`, `variantCount`,
   `level`, `bodySize` theo §3.5.1.
2. Thân: không nén → số byte còn lại = `bodySize`; nén → giải ra đúng `bodySize`, luồng kết thúc, không thừa byte.
3. Thân bị cắt giữa bản ghi, hoặc còn byte sau biến thể cuối.
4. SHA-1(`'LRMK1'` ‖ u16 `partCount` ‖ các `partKey`) ≠ `modelKey` (toàn vẹn); `modelKey` ≠ khoá runtime / tên file;
   `partCount` ≠ số phần runtime (`model.modelParts_00.length`; khoá khớp đã bao hàm điều này, nhưng bộ đọc PHẢI tự
   kiểm trước khi đánh chỉ số mảng theo phần).
5. `srcFaceCount` ≠ số gói runtime của phần.
6. `mode ∉ {0,1}`; giới hạn `P/C/T`; float NaN/Inf; `corner.pos >= P`; `corner.srcFace >= srcFaceCount`;
   `role > 2`; byte zero / reserved ≠ 0; `nearestTmdVertex >= n_vert`; chỉ số `tri >= C`; tam giác có corner khác
   `srcFace`; tam giác không xếp theo `srcFace` tăng dần.
7. `w`, `h` sai; `texturedFaceCount` ≠ runtime hoặc khác giữa các biến thể; `atlasUv` NaN/Inf hoặc ngoài [0, 1].

Không kiểm (hợp lệ): giá trị `faceHash`; giá trị `S`, `T`; độ dài pháp tuyến; corner không được tam giác nào dùng;
`atlasUv` góc thứ 4 của mặt tam giác (bộ ghi đặt (0, 0), runtime không đọc). Mục 3 PHẢI được kiểm **trước** khi cấp
phát mảng theo số đếm trong file (ví dụ `36·texturedFaceCount` <= số byte thân còn lại).

### §3.5.5. Ghi

- Bộ ghi xác định: cùng dữ liệu → cùng byte. `generator` ví dụ `"lodsc-remaster 1"`.
- Bản phát hành cho người chơi NÊN nén (bit 0, zlib mức 9). Byte nén phụ thuộc bản cài zlib (CPython 3.14 trên
  Windows dùng zlib-ng), nên "round-trip trùng byte" chỉ áp cho file không nén; với file nén so header + thân đã giải.

---

## §3.6. Atlas PNG: `remaster/textures/<SHA-1 của file>.png`

### §3.6.1. File

RGBA 8 bit; `w`, `h` luỹ thừa 2, <= 2048, bằng `w`, `h` của biến thể. Tên = 40 hex thường của SHA-1 toàn bộ byte file.
Quy ước alpha trong file (bộ ghi CHỈ dùng ba giá trị này):

| A | Nghĩa | RGB |
|---|---|---|
| 0 | trong suốt | (0, 0, 0) |
| 255 | đục, STP = 0 | màu |
| 128 | đục, STP = 1 | màu |

Bộ đọc chịu sai lệch: `A < 64` → trong suốt; `64 <= A < 192` → STP = 1; `A >= 192` → STP = 0. STP được lưu cho mọi
texel đục của mọi mặt (cờ ctmd `0x2` trong trận có thể làm mọi mặt trong mờ).

Gốc toạ độ: hàng đầu của PNG = `v = 0`; `atlasUv (0, 0)` = góc trên trái ảnh; texel `(x, y)` phủ
`[x/w, (x+1)/w) × [y/h, (y+1)/h)`.

### §3.6.2. Đổi sang dạng shader cần (mỗi mức mip)

- trong suốt → `(0, 0, 0, 0)` (shader bỏ texel RGBA = 0, `tmd.fsh:95`);
- STP = 0 → `(R, G, B, 0)`; nếu `(R, G, B) = (0, 0, 0)` thì đổi thành `(1, 1, 1)` để không bị bỏ;
- STP = 1 → `(R, G, B, 255)` (`tmd.fsh:100`: `alpha != 0` = bit STP).

### §3.6.3. Mip trên CPU

Mức 0 = ảnh file (đã chuẩn hoá theo §3.6.1). Mức `k+1` có cỡ `max(1, w/2) × max(1, h/2)`; texel `(x, y)` lấy khối các
texel `(2x+i, 2y+j)`, `i, j ∈ {0, 1}`, nằm trong mức `k` (khối 4, 2 hoặc 1 texel). Với `n` = số texel khối,
`t` = số texel trong suốt:
- `2t >= n` → trong suốt (khối đủ 4: từ 2 texel trong suốt trở lên);
- ngược lại, `o = n - t` texel đục: mỗi kênh `RGB = floor((Σ kênh + floor(o/2)) / o)` (RGB file, trước khi đổi
  (0,0,0) → (1,1,1)); `STP = 1` nếu số texel STP=1 >= số texel STP=0 (hoà → 1), ngược lại 0.

Chuỗi mip tới 1×1: `floor(log2(max(w, h))) + 1` mức; mỗi mức đổi theo §3.6.2 rồi tải.

### §3.6.4. Tải lên GPU

Mức 0: `Texture.create` RGBA_8 qua `TextureBuilder.data`; ngay sau đó `glActiveTexture(GL_TEXTURE0)`; mức 1..n-1:
`glTexImage2D(GL_TEXTURE_2D, level, GL_RGBA8, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, …)`. `MIN_FILTER =
NEAREST_MIPMAP_NEAREST`, `MAG_FILTER = NEAREST`, `WRAP_S/T = CLAMP_TO_EDGE`. Lấy mẫu ở đơn vị 0 (`tex24`) qua đường
bpp 3 có sẵn của shader (không sửa shader).

---

## §3.7. Chỉ mục và công tắc

- `remaster/index.tsv`: UTF-8 không BOM, xuống dòng LF. Dòng 1 đúng `LRMINDEX<TAB>1`. Mỗi dòng sau (không rỗng):
  `<modelKey><TAB>models/<modelKey>.lrm<TAB><label>` — khoá 40 hex thường, nhãn UTF-8 không chứa TAB/CR/LF (có thể
  rỗng). Dòng rỗng bỏ qua; dòng sai định dạng → coi như không có chỉ mục (tắt).
- Bộ sinh ghi `index.tsv` **cuối cùng** (`index.tsv.tmp` rồi đổi tên); đó là điểm commit.
- `<game>/remaster.properties` (định dạng `java.util.Properties`): `enabled = true|false` (thiếu → false),
  `textures = hd|retail` (thiếu → hd), `log = true|false` (thiếu → false).
- Ghi đè: `-Dscvi.remaster = off|geometry|full`, `-Dscvi.remasterLog = true`. Thứ tự ưu tiên: thuộc tính `-D`, rồi
  `remaster.properties`, rồi tắt. Chế độ: `off`; `geometry` (= `enabled=true, textures=retail`: chỉ bộ VRAM);
  `full` (= `enabled=true, textures=hd`).
- Thiếu file hoặc thư mục → tính năng tắt.

---

## §3.8. File chỉ công cụ dùng (runtime không đọc)

- `remaster/manifest.json`: `{format: 1, tool, pipeline, created, sc_commit, vi_version,
  blender {version, zip_sha256}, upscaler {name, model, zip_sha256}, quality: "pc"|"mobile", params, params_hash,
  models: [{key, label, char, form, src, level, tris, variants: [{png, method, psnr_min}], qa}], failed: []}`.
- `catalog_v1.json`: `[{id, char, form, tier: "core"|"optional", confidence, label_vi,
  sources: [{kind: "battle"|"field"|"story"|"monster", model, tim}], expect: {nobj, tris}, key_us}]`.
- Trung gian của worker trong `remaster_work/`:
  - `scan.json`: khoá, cặp (khoá, TIM), véc-tơ face-hash, nguồn;
  - `export/<job>/`: JSON theo lược đồ `export_tmd.py` + `_atlas.png` + `_atlas_pad.png`;
  - `geom/<key>/geom_L1.npz`, `geom_L2.npz`: mỗi phần `pos f32[P,3]`, `corner_pos u32[C]`, `corner_n f32[C,3]`,
    `corner_face u32[C]`, `corner_st u16[C,2]`, `corner_near u16[C]`, `corner_role u8[C]`, `tri u32[T,3]`, `mode u8`;
    kèm `qa.json`;
  - `tex/<variant>/`: `atlas_4x.png`, `atlas_2x.png`, `atlas.json {w, h, faceUv[textured face index][4][2]}`.

## §3.9. Dòng lệnh worker (hợp đồng giữa C-TOOL và C-GEN)

- `<blender>/5.2/python/bin/python.exe -I <game>/vi/remaster/py/worker.py run --game <g> --blender <exe>
  [--esrgan <thư mục ASCII> | --no-ai] [--scope v1|v1+optional] [--quality pc|mobile|both] [--texture hd|retail]
  [--resume]`.
- Lệnh con khác: `probe`, `export-android --out <zip>`, `clean`.
- Dòng stdout: `@@P {json: stage, i, n, label}`; `@@E {json: key, stage, msg}`;
  `@@DONE {json: ok, failed, skipped, minutes}`.
- Mã thoát: 0 = xong, 2 = một phần, 1 = lỗi nặng.
- Worker chỉ ghi dưới `<game>/remaster`, `<game>/remaster_work` và thư mục staging ASCII; chỉ đọc `files/` và
  `vi/files`.

---

## §4. Thuật toán runtime

### §4.1. `TmdObjLoader.fromModel(String name, Model124 model, int tw, int th)`

Đi **đường gốc** (byte-y-hệt retail) khi một trong các điều: chế độ `off`; `name` không bắt đầu bằng
`"CombatantModel ("`, `"SobjModel ("` hay `"WmapEntityModel ("`; không có chỉ mục. Ngược lại tính `partKey`,
`modelKey` (< 1 ms); khoá không có trong chỉ mục → đường gốc. Trúng → `LrmFile.load` (cache `SoftReference`) kiểm
§3.5.4; lỗi bất kỳ → cả mô hình đi đường gốc, log một lần mỗi khoá.

### §4.2. Mỗi phần

- `mode 0` → `fromObjTable` gốc.
- `mode 1` → `SrcFaces`: giải mã chép từ TmdObjLoader.java:89-186 (cùng lớp lưới, thứ tự, quy tắc `backfaceCulling`
  :291-296, đảo thứ tự lưới :322-326). Rồi:
  - dựng **bộ VRAM** (mọi mặt lấy mẫu VRAM live) — luôn luôn;
  - dựng thêm **một bộ ATLAS cho mỗi biến thể** khi đồng thời: chế độ `full`, `textures = hd`, `tw == th == 0`,
    `model.clutAnimations_a4 == null`, `variantCount > 0`. Trong bộ ATLAS, mặt có texture **không LIVE** (§3.4 cho biến
    thể đó) nhận `tpage' = (tpage & ~0x180) | 0x180` và uv `I(atlasUv)` (§3.2.3);
  - lưới tạo bằng `RENDERER.api().makeMesh(…, VertexOrder.TRIANGLES_ADJACENCY, vertices, indices, textured,
    translucent, translucency, BufferUsage.STATIC)` với đúng 7 thuộc tính như `createMesh` (:329-359);
  - Obj của phần = `RemasterMeshObj` (bộ VRAM = `super.meshes`, các bộ ATLAS, `backfaceCulling`, trạng thái chung của
    mô hình cho mọi phần).
- `AtlasCache` giữ texture: đếm tham chiếu theo `pngSha1`, `persistent = true`, giải phóng khi mọi chủ sở hữu bị xoá
  hoặc khi engine state đổi.
- D5: mọi đối tượng GPU tạo lúc nạp trong `fromModel`; `render()` chỉ chọn bộ và bind atlas; không tạo GL object giữa
  lúc vẽ, không `mesh.update`.

### §4.3. Phát lưới của một phần mode 1 (chuẩn — Phụ lục B)

1. Lớp lưới của mặt (như `getTranslucencySizes`): có texture + trong mờ → lớp `Translucency.of(tpage >>> 5 & 3)`;
   không texture + trong mờ → `untextured translucent`; còn lại → `opaque`. Thứ tự: `opaque`, `untextured
   translucent`, `Translucency` theo ordinal (`HALF_B_PLUS_HALF_F`, `B_PLUS_F`, `B_MINUS_F`, `B_PLUS_QUARTER_F`); chỉ
   lớp có ít nhất một tam giác remaster; rồi **đảo** thứ tự (như :324-326).
2. Tham số `makeMesh`: `opaque` → `(textured = anyTextured, translucent = false, null)`; `untextured translucent` →
   `(false, true, null)`; lớp `Translucency` → `(anyTextured, true, translucency)`; `anyTextured` = phần có ít nhất một
   gói có texture. `backfaceCulling` của Obj = false nếu phần có gói trong mờ không texture (trên **mọi** gói của phần).
3. Đỉnh của lưới lớp `L`: mọi corner `c` (theo chỉ số tăng dần) có lớp(`c.srcFace`) = `L`; mỗi corner một đỉnh 16 float
   (§3.2.3). Bộ VRAM và mọi bộ ATLAS có cùng thứ tự đỉnh và cùng chỉ số; chỉ float 7-9 của mặt có texture khác nhau.
4. Chỉ số của lưới lớp `L`: duyệt `tri` theo thứ tự file, giữ tam giác có lớp = `L`, phát `[a, a, b, a, c, a]` (a, b, c =
   chỉ số đỉnh cục bộ). Không đặt `QUAD_FLAG` nên shader hình học chỉ dùng ba đỉnh 0, 2, 4 (`tmd.gsh:60-91`).

### §4.4. `render()` và xác minh

- `state.tick()` chạy xác minh. Khi **PENDING**: `FaceVerify` khoảng mỗi 4 khung trong 2 s, sau đó khoảng mỗi 1 s, trên
  các mặt có texture không LIVE, dừng ở mặt sai đầu tiên. Biến thể được thử theo thứ tự 0, 1, …; nếu mọi mặt khớp biến
  thể `v` (bỏ qua mặt LIVE a–c và mặt có `faceHash[v][g] == 0`) → **ATLAS(v)**.
- Trong ATLAS: kiểm lại toàn bộ khoảng mỗi 1 s (ngân sách trung bình 0.2 ms/khung). Sai → về PENDING (vẽ bộ VRAM).
  Khuyến nghị chống nhấp nháy (RISKS): sau 3 lần ATLAS → PENDING trong đời một mô hình, khoá ở VRAM và log một lần.
- ATLAS(v) vẽ: `atlas.use(0)` rồi `atlasSets[v][layer]`; mọi trạng thái khác vẽ `vramSet[layer]`.
- `FaceVerify` đọc `GPU.getPixel15` theo §3.3 với tpage/clut/uv **live** của gói.
- `performDelete` xoá mọi bộ lưới và trả tham chiếu atlas.
- Log (`RemasterLog`): một dòng mỗi khoá `scvi-remaster: <name> key=<k> hit|miss|fallback(<reason>) variant=<v>|vram`;
  với `-Dscvi.remasterLog=true` thêm mặt sai đầu tiên (chỉ số, hash runtime, hash mong đợi) và SHA-1 véc-tơ face-hash
  runtime (§3.3.6) để so với Python.

## §5. Dự phòng (không bao giờ sập, không bao giờ sai màu)

- Mọi `Throwable` → đường gốc.
- PNG hỏng / thiếu / sai SHA-1 / sai kích thước → bộ VRAM.
- Xác minh không bao giờ đạt → hình học remaster với đúng texel retail. Gồm combatant VRAM riêng (`charSlot >= 3`,
  Battle.java:2801-2806), ghi đè PNG, TIM lạ.
- Chế độ `geometry` hoặc `textures = retail` → chỉ bộ VRAM.

---

## Phụ lục A — dữ liệu vàng và công cụ tham chiếu (WP0)

Chạy từ gốc repo với `PYTHONIOENCODING=utf-8`. Mọi lệnh exit 0 = đạt, 1 = lỗi; chỉ đọc `game/files`.

| Lệnh | Việc |
|---|---|
| `python tools/sc_remaster/spec/ref_spec.py keys [--game game/files] [--readonly-check]` | quét như `keyscan.py`; phải ra 6722 file trường → 551 khoá (532 trường + 19 trận), 19 khoá trận, 0 khoá trận trong file trường, khoá trùng nguyên mẫu ở mọi file |
| `python tools/sc_remaster/spec/ref_spec.py vectors [--check] [--dump [DIR]] [--readonly-check]` | tính `spec/vectors.json`; `--check` so với file đã commit; `--dump` ghi hash từng mặt vào `work/upscale/sc_remaster_spec/` (git bỏ qua) |
| `python tools/sc_remaster/spec/ref_spec.py roundtrip <file.lrm>` | đọc + kiểm §3.5.4 + ghi lại, phải trùng byte |
| `python tools/sc_remaster/spec/ref_spec.py selftest` | FNV, mip, alpha, PNG, `index.tsv` (kể cả nhãn có CR bị từ chối), LRM + 21 lỗi gieo, số phần runtime ≠ `partCount`, round-trip thân deflate, round-trip `sample_cube.lrm` |
| `python tools/sc_remaster/spec/synth_cube.py [--check] [--out DIR]` | sinh / kiểm `sample_cube.lrm` + `.json`; `--out` ghi thêm CContainer, TIM A–E, PNG và cây `remaster/` hoàn chỉnh |

`spec/vectors.json` (chỉ hash, số đếm, đường dẫn): 19 mô hình trận, 11 story DRGN0, 3 ô quái, 10 trường. Mỗi mục:
`id, char, kind, model, tim, placement (native | field_slot0), [aliases], partCount, modelKey, partKeys[],
srcFaceCount[], texturedFaceCount, tris, faceHashVectorSha1 (FaceHash thô §3.3.6), texAnimRects, liveFaceCount
(§3.4 a–c; a lấy gần đúng bằng CContainer `+4 != 0`, b chỉ có ở mẫu trường với ô 0), facesOutsideTim (số mặt §3.3.5
sẽ ghi 0)`.

`spec/sample_cube.lrm` + `spec/sample_cube.json` (mô hình tổng hợp, không phải dữ liệu Sony; ngữ cảnh
`SobjModel (index 0)`, `UvAdjustmentMetrics14(0, 576, 256)`, tw = th = 0):
- phần 0 "cube" (L0 identity, 11 mặt): GT4/GT3 4bpp hai hàng CLUT, GT4 trong mờ abr 1, G4 gradated, G3 có đèn, GT3 không
  đèn (màu × 2), GT3 trong rect hoạt cảnh texture (LIVE b), GT3 đọc ngoài TIM (`faceHash` 0, LIVE d);
- phần 1 "plate" (chia một lần, 6 mặt): GT4 nền + đề can (cùng tập đỉnh, cùng chiều) + mặt sau (thứ tự góc 1,0,3,2),
  GT3 trong mờ abr 1, G4, G3 không texture trong mờ (`backfaceCulling = false`);
- 2 biến thể: TIM A và TIM B (đổi màu CLUT hàng 0, atlas xếp khối ngược nên `atlasUv` khác);
- JSON ghi: byte CContainer + TIM A–E (hex, tổng hợp), khoá, `srcFaceCount`, mô tả từng mặt, tập LIVE, hash runtime
  từng TIM và hash lưu từng biến thể, kết quả xác minh mong đợi (A → 0, B → 1, C → không, D → không, E → 0), SHA-1 các
  mức mip đã đổi (§3.6.2–3), và bộ đệm 16 float + chỉ số của lưới retail, bộ VRAM và bộ ATLAS mỗi biến thể theo từng
  lớp lưới (float là giá trị f32 chính xác; kèm SHA-1 của f32 LE và u32 LE). Phần 0 của bộ VRAM được kiểm trùng từng bit
  với lưới retail trừ `QUAD_FLAG`.

---

## Phụ lục B — Ghi chú xác minh

Đối chiếu với mã nguồn SC `affcef0` (đường dẫn tính từ `Severed-Chains/src/main/java/legend/`) và dữ liệu US đã giải
nén (`game/files`, chỉ đọc). Kết quả chạy: `keys` 6722 / 551 / 19 / 0 (khoá trùng `keyscan.py` ở mọi file),
`vectors` 43 mẫu, `selftest` đạt.

### B.1. Đã xác minh đúng như kiến trúc

1. `TmdObjTable1c` (game/tmd/TmdObjTable1c.java:29-78): đỉnh `readSvec3_0` (s16, bước 8 byte), pháp tuyến
   `readSvec3_12` (s16 / 4096f), `updateTmdPacketIlen(primitives, n_primitive_14)` (:52) rồi đọc run: `count = header &
   0xffff`, mỗi gói `primitivePacketSize(header)` byte sau header 4 byte riêng, làm tròn 4 sau run (:54-73).
   `Primitive(offset, width, header, data)` giữ header **của gói đầu run** sau khi bị ghi đè.
2. `Models.updateTmdPacketIlen` (game/Models.java:494-603) gom theo `mode = h>>>24`, `flag = h>>>16 & 0xff` và chỉ
   `writeShort` 16 bit thấp ở đầu mỗi run. Bảng bước nhảy của nó khác `primitivePacketSize` ở 60 tổ hợp mode/flag hợp
   lệ (ví dụ `25/0`, `2d/0`, gói lit không pháp tuyến); **không** tổ hợp nào xuất hiện trong 6722 file trường (đếm
   bằng `keys`: 0 gói lệch bảng), nên làm phẳng theo Java trùng cách đọc từng gói.
3. `CtmdTransformer.primitivePacketSize` (game/unpacker/CtmdTransformer.java:263-299) như §3.1; ném lỗi với
   `textured && gradated` và `!textured && !lit`.
4. `UvAdjustmentMetrics14` (game/tmd/UvAdjustmentMetrics14.java): mặt nạ clut `0x3c3ffff` | ô, tpage `0xffe0ffff` | ô,
   cộng `uvOffset` vào word 0, 1, 2 (3 nếu quad) (:37-67); PNG: `& 0x60ffff | 0x1800000` (:11-18). Cả hai giữ abr.
   Chỉ chạm `data[0 .. 4*vc)`.
5. `TmdObjLoader.fromObjTable` (game/tmd/TmdObjLoader.java:82-327): bố cục 16 float, `colourToFloat` (`r/255f` …,
   kênh 4 = byte cao), `× 2f` cả 4 kênh khi có texture (:258-268), uv `u / textureWidth` khi bpp 3 (:240-246), lớp lưới
   và thứ tự đảo (:309-326), `backfaceCulling = false` khi gói trong mờ không texture (:291-296). Chỉ số retail:
   `[v+2, v+3, v+1, v+3, v, v+3]` (+ `[v+1, v, v+2, v, v+3, v]` cho quad).
6. `Gpu.getPixel15(x, y)` (core/gpu/Gpu.java:605-608) = `vram15[y * 1024 + x]` (int[] giữ u16 gồm STP; `uploadData15`
   ghi `readUShort` thô). Shader: `tmd.vsh:101-117`, `tmd.fsh:71-100`, `tmd.gsh:58-91`.
7. Một điểm vào: `fromModel` ở RetailSubmap.java:651/653, Battle.java:2979, WMap.java:949; tiền tố tên
   `"SobjModel ("`, `"CombatantModel ("`, `"WmapEntityModel ("`; loại `Shadow` (core/GameEngine.java:435) và
   `"BattleModel "` (Battle.java:5801).
8. Hoạt cảnh texture: `animationMetrics_d0[i] = ptr_a8._00[i]`, `i < 7` (Models.java:87-93, SMap.java:2892-2893);
   `CContainerSubfile2` đọc `count` offset u32 rồi dãy s16 tới `-1` (game/types/CContainerSubfile2.java:11-29);
   rect đích `(m1 + tpageX, m2 + tpageY, m3 / 4, m4)` ở cả hai nhánh của `animateModelTextures` (Models.java:368-465).
   `clutAnimations_a4` đặt ở sc-vi `SMap.modelLoaded` (sc-vi SMap.java:1320-1350) khi CContainer `+4 != 0`.
9. Số liệu nguyên mẫu: 6722 file trường → 551 khoá **tổng** (532 khoá trường + 19 khoá trận); dòng `unique keys total`
   của `keyscan.py` đếm cả hai.

### B.2. Chỗ không nhất quán đã sửa trong đặc tả này

1. **Bản ghi corner 28 ≠ 32 byte.** Kiến trúc ghi "32 bytes each" nhưng các trường liệt kê chỉ có 28 byte. Chọn 32 byte:
   thêm `u8[4] reserved = 0` ở +28 (§3.5.2), giữ căn 4 byte và đúng cỡ đã công bố.
2. **UvAdjust chỉ áp cho gói gouraud có texture.** `Models.adjustPartUvs` (Models.java:55-64) chỉ gọi `apply` khi
   `header & 0xff040000` ∈ {0x34..0x37, 0x3c..0x3f}`<< 24`; `export_tmd.py load_field` áp cho mọi gói có texture. Đặc
   tả và `ref_spec.py` theo SC (§3.3.7). Trên dữ liệu US hai cách trùng nhau: 6722 file trường có 0 gói phẳng có texture
   (chỉ các mode 30, 32, 34–38, 3a, 3c–3f); 33 mẫu trận / story / quái của `vectors.json` cũng 0 gói phẳng có texture,
   0 gói lệch bảng `updateTmdPacketIlen`, không subfile2, không hoạt cảnh CLUT (combatant trận được UvAdjust theo ô VRAM
   lúc chạy nên điều này quan trọng cho tính độc lập vị trí của FaceHash). Hệ quả phụ: ghi đè PNG (§3.4 c) cũng chỉ
   đổi bpp của các gói gouraud có texture.
3. **Đọc VRAM ra ngoài 1024 × 512** (tpage trang 15 + u 8bpp/15bpp, hay `cx + idx` 8bpp, hay `clut >>> 6 > 511`) không
   được định nghĩa: Java `getPixel15` sẽ tràn sang hàng sau hoặc ném lỗi, shader `texelFetch` không xác định. Đặc tả bắt
   buộc bọc `x & 1023`, `y & 511` cho FaceHash (§3.3.2).
4. **`animationMetrics_d0` có mục ngắn.** Mọi CContainer có subfile2 trong dữ liệu có mục 1..6 = `[1, -1]` (2 short),
   không đủ `m[1..4]`. Quy tắc b chỉ xét mục `length >= 5`; `w = m[3] / 4` chia nguyên Java; rect rỗng khi `w <= 0` hoặc
   `h <= 0`; giao theo dấu chân bao gồm hai đầu (§3.4 b). Combatant trận có `uvAdjustments_9d` = ô VRAM (không phải NONE,
   BattleEntity27c.java:666-671) nhưng mô hình nhóm nhân vật trận không có subfile2 nên không có mặt LIVE b.
5. **Mặt đọc ngoài TIM.** DRGN0/468 (Kongol story, mức tin cậy trung bình) có 12 gói `tpage 0x0098` (8bpp) trên TIM 4bpp:
   dải CLUT 256 màu vượt rect CLUT 64 màu, texel đến từ VRAM không thuộc TIM. Nếu băm như thường, mô hình không bao giờ
   xác minh được. Thêm quy tắc bộ sinh §3.3.5 (ghi `faceHash = 0`) và quy tắc LIVE d §3.4 (mặt đó giữ VRAM trong bộ
   ATLAS của biến thể, bỏ qua khi xác minh). Giá trị 0 vốn đã được dành riêng (FNV "nếu 0 thì lưu 1").
6. **Thứ tự phát lưới remaster chưa được định nghĩa** (kiến trúc chỉ nói "cùng lớp, cùng thứ tự"). Bổ sung §4.3: đỉnh =
   corner theo chỉ số tăng dần trong từng lớp, chỉ số theo thứ tự `tri`, lớp rỗng bỏ, bộ VRAM / ATLAS cùng thứ tự — cần
   để R2 so "16 float mong đợi" của `sample_cube.json`.
7. **Phép tính float chưa đủ chặt** để Java và Python ra cùng bit: bổ sung §3.2.2 (thứ tự phép, kẹp tam giác
   `t = 1 - s` khi `s + t > 1`, nhân 2 trước khi nội suy màu) và §3.2.3 (mặt không texture: uv, tpage, clut = 0 như
   mảng retail để trống; mặt không LIT: pháp tuyến 0 dù file có lưu).
8. **Quy tắc mip ở cạnh ảnh không vuông và cách làm tròn** chưa định nghĩa: §3.6.3 (`2t >= n`, trung bình làm tròn
   `floor((Σ + floor(o/2)) / o)`, chuỗi tới 1×1). Ngưỡng alpha chịu sai lệch khi đọc (§3.6.1) và gốc toạ độ atlas
   (§3.6.1).
9. **Giới hạn bổ sung** để bộ đọc an toàn: `P <= 200000`, mode 1 `P >= 1, C >= 3, T >= 1`, `bodySize <= 256 MiB`,
   `level <= 2`, `atlasUv ∈ [0,1]`, `texturedFaceCount` bằng nhau giữa các biến thể, kiểm toàn vẹn
   `modelKey = SHA-1('LRMK1' ‖ partCount ‖ partKeys)` (khi khoá khớp runtime thì mọi `partKey` cũng khớp, nên không cần
   quy tắc "partKey sai → riêng phần đó dùng gốc").
10. **Byte nén không tái lập được giữa các bản zlib** (CPython 3.14 Windows: `zlib 1.3.1.zlib-ng`). `sample_cube.lrm`
    lưu không nén; PNG tổng hợp ghi bằng khối deflate "stored" (byte cố định); round-trip của file nén so phần thân đã
    giải (§3.5.5).
11. Kiến trúc §3.7 không nói giá trị mặc định khi `remaster.properties` thiếu khoá: `enabled` → false, `textures` → hd,
    `log` → false; `geometry` = `textures=retail` (§3.7).
12. Lớp phủ sc-vi `vi/files` (sc-vi/src/legend/game/unpacker/Loader.java:32-50) hiện chỉ có `SECT/DRGN0.BIN/4113` và `5695` (giao diện), không chạm mô
    hình hay TIM nhân vật; `ref_spec.py` vẫn đọc qua lớp phủ cho đúng hợp đồng.
