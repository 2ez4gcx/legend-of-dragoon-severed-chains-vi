"""Sinh ffi.h + fficonfig.h của libffi cho Android arm64-v8a / x86_64 (thay cho ./configure, không chạy được trên Windows).

Cách gọi:
    python android/natives/gen_ffi_headers.py <thư mục nguồn libffi-3.8.0> <thư mục ra> [arm64-v8a|x86_64]
Ghi <ra>/ffi.h (từ include/ffi.h.in), <ra>/ffitarget.h (chép src/aarch64|x86/ffitarget.h), <ra>/fficonfig.h.
Giá trị theo ABI của Android (AArch64 và x86-64 giống nhau ở đây): long double 128 bit, size_t 8 byte; không dùng trampoline tĩnh/bảng trampoline
(LWJGL 3.4 trên Java 25 làm upcall bằng FFM, chỉ dùng libffi cho mô tả kiểu FFICIF).
"""
import os
import re
import shutil
import sys

VERSION = '3.8.0'


def main():
    src, out = sys.argv[1], sys.argv[2]
    abi = sys.argv[3] if len(sys.argv) > 3 else 'arm64-v8a'
    target, tdir = {'arm64-v8a': ('AARCH64', 'aarch64'), 'x86_64': ('X86_64', 'x86')}[abi]
    os.makedirs(out, exist_ok=True)
    tpl = open(os.path.join(src, 'include', 'ffi.h.in'), encoding='utf-8').read()
    major, minor, patch = (int(x) for x in VERSION.split('.'))
    values = {
        'VERSION': VERSION,
        'TARGET': target,
        'HAVE_LONG_DOUBLE': '1',
        'FFI_VERSION_STRING': VERSION,
        'FFI_VERSION_NUMBER': str(major * 10000 + minor * 100 + patch),
        'FFI_EXEC_TRAMPOLINE_TABLE': '0',
    }
    missing = sorted(set(re.findall(r'@([A-Z_]+)@', tpl)) - set(values))
    if missing:
        sys.exit('LOI: ffi.h.in co bien chua biet: %s' % missing)
    hdr = re.sub(r'@([A-Z_]+)@', lambda m: values[m.group(1)], tpl)
    open(os.path.join(out, 'ffi.h'), 'w', encoding='utf-8', newline='\n').write(hdr)
    shutil.copy(os.path.join(src, 'src', tdir, 'ffitarget.h'), os.path.join(out, 'ffitarget.h'))
    cfg = '''/* fficonfig.h cho Android %s (android/natives/gen_ffi_headers.py) */
#define EH_FRAME_FLAGS "a"
#define HAVE_ALLOCA_H 1
#define HAVE_AS_CFI_PSEUDO_OP 1
#define HAVE_DLFCN_H 1
#define HAVE_HIDDEN_VISIBILITY_ATTRIBUTE 1
#define HAVE_INT128 1
#define HAVE_INTTYPES_H 1
#define HAVE_LONG_DOUBLE 1
#define HAVE_MEMCPY 1
#define HAVE_STDINT_H 1
#define HAVE_STDIO_H 1
#define HAVE_STDLIB_H 1
#define HAVE_STRINGS_H 1
#define HAVE_STRING_H 1
#define HAVE_SYS_STAT_H 1
#define HAVE_SYS_TYPES_H 1
#define HAVE_UNISTD_H 1
#define SIZEOF_DOUBLE 8
#define SIZEOF_LONG_DOUBLE 16
#define SIZEOF_SIZE_T 8
#define STDC_HEADERS 1
#define VERSION "%s"
#ifdef HAVE_HIDDEN_VISIBILITY_ATTRIBUTE
#ifdef LIBFFI_ASM
#define FFI_HIDDEN(name) .hidden name
#else
#define FFI_HIDDEN __attribute__ ((visibility ("hidden")))
#endif
#else
#ifdef LIBFFI_ASM
#define FFI_HIDDEN(name)
#else
#define FFI_HIDDEN
#endif
#endif
''' % (abi, VERSION)
    if abi == 'x86_64':
        cfg += '#define HAVE_AS_X86_PCREL 1\n#define HAVE_AS_X86_64_UNWIND_SECTION_TYPE 1\n'
    open(os.path.join(out, 'fficonfig.h'), 'w', encoding='utf-8', newline='\n').write(cfg)
    print('ffi headers -> %s' % out)


if __name__ == '__main__':
    main()
