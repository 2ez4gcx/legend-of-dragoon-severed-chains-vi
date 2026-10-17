# Thư viện native LWJGL 3.4.3 cho Android arm64-v8a: liblwjgl.so (core + libffi tĩnh), liblwjgl_opengles.so, liblwjgl_stb.so.
# Theo đúng tập tệp/cờ của config/linux/build.xml trong mã nguồn LWJGL (LWJGL_LINUX, _GNU_SOURCE), trừ:
#   - liburing (LibURing/LibIOURing: SC không dùng), mã freebsd/macos/windows;
#   - libffi: dựng từ libffi 3.8.0 chính thức (cùng bản LWJGL 3.4.3 dùng, có ffi_call_plan), tiêu đề sinh bởi
#     gen_ffi_headers.py. ABI: arm64-v8a (phát hành) hoặc x86_64 (giả lập).
# Gọi từ android/build_natives.ps1 (-DLWJGL_SRC=... -DFFI_SRC=... -DFFI_INC=...).
cmake_minimum_required(VERSION 3.22)
project(lwjgl_android C ASM)

set(CORE ${LWJGL_SRC}/modules/lwjgl/core/src)
set(GLES ${LWJGL_SRC}/modules/lwjgl/opengles/src)
set(STB ${LWJGL_SRC}/modules/lwjgl/stb/src)

if(ANDROID_ABI STREQUAL "x86_64")
  set(LWJGL_ARCH -DLWJGL_x64 -DX86_64)
  set(FFI_ARCH_DIR ${FFI_SRC}/src/x86)
  set(FFI_ARCH_SRC ${FFI_ARCH_DIR}/ffi64.c ${FFI_ARCH_DIR}/unix64.S ${FFI_ARCH_DIR}/ffiw64.c ${FFI_ARCH_DIR}/win64.S)
  set(FFI_ASM ${FFI_ARCH_DIR}/unix64.S ${FFI_ARCH_DIR}/win64.S)
else()
  set(LWJGL_ARCH -DLWJGL_arm64)
  set(FFI_ARCH_DIR ${FFI_SRC}/src/aarch64)
  set(FFI_ARCH_SRC ${FFI_ARCH_DIR}/ffi.c ${FFI_ARCH_DIR}/sysv.S)
  set(FFI_ASM ${FFI_ARCH_DIR}/sysv.S)
endif()

set(LWJGL_FLAGS -O3 -fPIC -pthread -DNDEBUG -DLWJGL_LINUX ${LWJGL_ARCH} -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0
    -D_GNU_SOURCE -D_FILE_OFFSET_BITS=64 -Wno-unused-parameter)

# libffi (tĩnh)
add_library(ffi STATIC
  ${FFI_SRC}/src/prep_cif.c ${FFI_SRC}/src/types.c ${FFI_SRC}/src/raw_api.c ${FFI_SRC}/src/java_raw_api.c
  ${FFI_SRC}/src/closures.c ${FFI_SRC}/src/tramp.c ${FFI_ARCH_SRC})
target_include_directories(ffi PRIVATE ${FFI_INC} ${FFI_SRC}/include ${FFI_ARCH_DIR})
target_compile_options(ffi PRIVATE -O2 -fPIC -fvisibility=hidden)
set_source_files_properties(${FFI_ASM} PROPERTIES COMPILE_FLAGS "-DLIBFFI_ASM")

# liblwjgl.so
file(GLOB CORE_MAIN ${CORE}/main/c/*.c)
file(GLOB CORE_GEN ${CORE}/generated/c/*.c)
file(GLOB CORE_GEN_LINUX ${CORE}/generated/c/linux/*.c)
list(FILTER CORE_GEN_LINUX EXCLUDE REGEX "liburing")
add_library(lwjgl SHARED ${CORE_MAIN} ${CORE_GEN} ${CORE_GEN_LINUX})
target_include_directories(lwjgl PRIVATE ${FFI_INC} ${CORE}/main/c ${CORE}/main/c/linux)
target_compile_options(lwjgl PRIVATE ${LWJGL_FLAGS} -std=gnu11)
target_link_libraries(lwjgl PRIVATE ffi dl log m)
target_link_options(lwjgl PRIVATE -Wl,--no-undefined)

# liblwjgl_opengles.so (build_simple module="opengles")
file(GLOB GLES_GEN ${GLES}/generated/c/*.c)
add_library(lwjgl_opengles SHARED ${GLES_GEN})
target_include_directories(lwjgl_opengles PRIVATE ${CORE}/main/c ${CORE}/main/c/linux ${GLES}/main/c)
target_compile_options(lwjgl_opengles PRIVATE ${LWJGL_FLAGS} -std=gnu11)
target_link_libraries(lwjgl_opengles PRIVATE dl)

# liblwjgl_stb.so
file(GLOB STB_GEN ${STB}/generated/c/*.c)
add_library(lwjgl_stb SHARED ${STB_GEN})
target_include_directories(lwjgl_stb PRIVATE ${CORE}/main/c ${CORE}/main/c/linux)
target_compile_options(lwjgl_stb PRIVATE ${LWJGL_FLAGS} -std=gnu11 -isystem ${STB}/main/c)
target_link_libraries(lwjgl_stb PRIVATE m)
