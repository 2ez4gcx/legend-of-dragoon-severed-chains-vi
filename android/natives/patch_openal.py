"""Vá OpenAL Soft 1.25.2 để biên dịch được bằng clang/libc++ của NDK r28 (lỗi "function 'operator|<...>' with deduced
return type cannot be used before it is defined" khi dùng std::views::drop/take trên al::FlexArray). Chỉ thay biểu thức
ranges bằng vòng lặp/thuật toán tương đương, không đổi hành vi. LWJGL 3.4.3 cần OpenAL Soft >= 1.25 (alGetProcAddressDirect,
AL_SOFT_*Direct): bản 1.24 làm AL.createCapabilities báo thiếu OpenAL10 và SC tắt âm thanh.

Cách gọi:  python android/natives/patch_openal.py <thư mục openal-soft-1.25.2>   (chạy lại nhiều lần vẫn an toàn)
"""
import os
import sys

PATCHES = [
    ('al/auxeffectslot.cpp',
     '    std::ranges::fill(*newarray | std::views::drop(newcount), nullptr);',
     '    std::fill(newarray->begin() + static_cast<std::ptrdiff_t>(newcount), newarray->end(), nullptr); /* NDK r28 */'),
    # <threads.h> của bionic chỉ có tss_*/thrd_* từ API 30; ta nhắm API 29 -> dùng nhánh pthread của OpenAL Soft
    ('common/althreads.h',
     '#elif defined(__STDC_NO_THREADS__) || !__has_include(<threads.h>)\n\n#include <pthread.h>',
     '#elif defined(__STDC_NO_THREADS__) || !__has_include(<threads.h>) || defined(__ANDROID__)\n\n#include <pthread.h>'),
    ('common/althreads.h',
     '#elif defined(__STDC_NO_THREADS__) || !__has_include(<threads.h>)\n\n    pthread_key_t mTss{};',
     '#elif defined(__STDC_NO_THREADS__) || !__has_include(<threads.h>) || defined(__ANDROID__)\n\n    pthread_key_t mTss{};'),
]


def replace_all(root, rel, old, new):
    """thay mọi chỗ (_mm_load_ps(&mCoeffs[j]) trong module C++: clang của NDK r28 không khớp được kiểu con trỏ)"""
    p = os.path.join(root, rel)
    s = open(p, encoding='utf-8').read()
    if old in s:
        open(p, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))
        print('va %s (%d cho)' % (rel, s.count(old)))


def main():
    root = sys.argv[1]
    # chỉ ảnh hưởng bản x86_64 (thử trên giả lập); arm64 dùng NEON
    replace_all(root, 'alsoft-modules/phase_shifter.cppm', '_mm_load_ps(&mCoeffs[j])',
                '_mm_loadu_ps(reinterpret_cast<const float*>(mCoeffs.data() + j))')
    for rel, old, new in PATCHES:
        p = os.path.join(root, rel)
        s = open(p, encoding='utf-8').read()
        if new in s:
            continue
        if old not in s:
            sys.exit('LOI: %s khong co doan can va' % rel)
        open(p, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))
        print('va %s' % rel)


if __name__ == '__main__':
    main()
