# libopus.so cho Android giống thư viện opus của LWJGL 3.4.3 trên máy tính: Opus + opusfile (+ libogg tĩnh, không xuất ra).
# LWJGL tìm các hàm opusfile (op_open_memory, opus_head_parse, opus_tags_*...) trong chính thư viện "opus"
# (OpusFile.Functions dùng Opus.getLibrary()); thiếu chúng thì lần đầu phát XA (XaPlayer: phép rồng có giọng/tiếng XA như
# Bạo Viêm, Credits) ném "A required function is missing: opus_head_parse" và game văng.
# Không gồm libopusenc (OpusEnc của LWJGL; SC không mã hoá âm thanh) và http.c của opusfile (op_url_*: LWJGL không bind).
# Gọi từ android/build_natives.ps1 (-DOPUS_SRC=... -DOPUSFILE_SRC=... -DOGG_SRC=...).
cmake_minimum_required(VERSION 3.24)
project(opus_android C)

set(BUILD_SHARED_LIBS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(OPUS_BUILD_PROGRAMS OFF CACHE BOOL "" FORCE)
set(OPUS_BUILD_TESTING OFF CACHE BOOL "" FORCE)
set(INSTALL_DOCS OFF CACHE BOOL "" FORCE)
add_subdirectory(${OPUS_SRC} opus EXCLUDE_FROM_ALL)
add_subdirectory(${OGG_SRC} ogg EXCLUDE_FROM_ALL)
# chỉ xuất API (OPUS_EXPORT đặt visibility default khi OPUS_BUILD), như opus.dll của LWJGL
target_compile_options(opus PRIVATE -fvisibility=hidden)
target_compile_options(ogg PRIVATE -fvisibility=hidden)

# opusfile.h tự đặt visibility default cho API (pragma GCC visibility push), phần còn lại ẩn như unix/Makefile của opusfile
add_library(opus_bundle SHARED
  ${OPUSFILE_SRC}/src/info.c ${OPUSFILE_SRC}/src/internal.c ${OPUSFILE_SRC}/src/opusfile.c ${OPUSFILE_SRC}/src/stream.c)
set_target_properties(opus_bundle PROPERTIES OUTPUT_NAME opus)
target_include_directories(opus_bundle PRIVATE ${OPUSFILE_SRC}/include)
target_compile_definitions(opus_bundle PRIVATE OP_HAVE_LRINTF)
target_compile_options(opus_bundle PRIVATE -O2 -fvisibility=hidden -Wno-parentheses)
target_link_libraries(opus_bundle PRIVATE "$<LINK_LIBRARY:WHOLE_ARCHIVE,opus>" ogg m)
target_link_options(opus_bundle PRIVATE -Wl,--no-undefined)
