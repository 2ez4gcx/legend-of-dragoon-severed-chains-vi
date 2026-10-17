# libsclauncher.so: SDL_main của bản Android (sclauncher.c). Gọi từ android/build_natives.ps1 (-Only launcher).
cmake_minimum_required(VERSION 3.22)
project(sclauncher C)
add_library(sclauncher SHARED sclauncher.c)
target_include_directories(sclauncher PRIVATE ${SDL_INCLUDE})
target_compile_options(sclauncher PRIVATE -O2 -Wall -Wextra -Wno-unused-parameter)
target_link_libraries(sclauncher PRIVATE ${SDL_LIB} log dl)
target_link_options(sclauncher PRIVATE -Wl,--no-undefined)
