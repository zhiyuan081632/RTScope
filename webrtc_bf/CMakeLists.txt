cmake_minimum_required(VERSION 3.10)
project(webrtc_bf C CXX)

# ---------------------------------------------------------------------------
# 在 Windows/MinGW-w64 下把 webrtc NonlinearBeamformer 编成流式 DLL: webrtc_bf.dll
#
# 与 mic2_bf/CMakeLists.txt (Linux) 的差异:
#   * 宏 WEBRTC_LINUX/WEBRTC_POSIX -> WEBRTC_WIN
#   * system_wrappers 的 *_posix.cc -> *_win.cc (rw_lock / trace)
#   * 只编 NonlinearBeamformer 的依赖闭包 (base + common_audio + signal_processing
#     + beamformer + system_wrappers), 不编 aec/agc/ns/isac/transient/vad/gflags,
#     既缩短编译, 又避开与波束无关模块在 Windows 下的移植风险。
#   * 静态链接 libgcc/libstdc++, 使 DLL 不依赖 MinGW 运行时, 便于自包含分发。
#
# 用法 (在 bfbuild conda 环境的 MinGW 下):
#   cmake -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Release -S . -B build
#   cmake --build build -j
# 产物: ../lib/webrtc_bf.dll
# ---------------------------------------------------------------------------

set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_C_STANDARD 99)

# webrtc 源码根: 该目录下应有 webrtc/webrtc/base/... 结构
if(NOT DEFINED WEBRTC_ROOT)
  set(WEBRTC_ROOT "D:/project/prjSE/src/BF/webrtc_nbf/mic2_bf/webrtc")
endif()
set(W "${WEBRTC_ROOT}/webrtc")

if(NOT EXISTS "${W}/modules/audio_processing/beamformer/nonlinear_beamformer.cc")
  message(FATAL_ERROR "未找到 webrtc 源码: ${W} (用 -DWEBRTC_ROOT=... 指定)")
endif()

include_directories(
  "${WEBRTC_ROOT}"
  "${W}/common_audio/signal_processing/include"
)

add_definitions(
  -DWEBRTC_WIN
  -DWEBRTC_NS_FLOAT
  -D_USE_MATH_DEFINES
  -D_CRT_SECURE_NO_WARNINGS
  -DWIN32_LEAN_AND_MEAN
  -DNOMINMAX
  -DUNICODE
  -D_UNICODE
  -D__STDC_FORMAT_MACROS
)

set(SRC
  # ---- base ----
  ${W}/base/buffer.cc
  ${W}/base/checks.cc
  ${W}/base/criticalsection.cc
  ${W}/base/event.cc
  ${W}/base/event_tracer.cc
  ${W}/base/logging.cc
  ${W}/base/platform_file.cc
  ${W}/base/platform_thread.cc
  ${W}/base/stringencode.cc
  ${W}/base/thread_checker_impl.cc
  ${W}/base/timeutils.cc
  # ---- common_audio ----
  ${W}/common_audio/audio_util.cc
  ${W}/common_audio/audio_ring_buffer.cc
  ${W}/common_audio/blocker.cc
  ${W}/common_audio/channel_buffer.cc
  ${W}/common_audio/fft4g.c
  ${W}/common_audio/fir_filter.cc
  ${W}/common_audio/fir_filter_sse.cc
  ${W}/common_audio/lapped_transform.cc
  ${W}/common_audio/real_fourier.cc
  ${W}/common_audio/real_fourier_ooura.cc
  ${W}/common_audio/ring_buffer.c
  ${W}/common_audio/sparse_fir_filter.cc
  ${W}/common_audio/window_generator.cc
  # ---- common_audio/signal_processing (纯 C, 全量纳入, 体积小且可移植) ----
  ${W}/common_audio/signal_processing/auto_correlation.c
  ${W}/common_audio/signal_processing/auto_corr_to_refl_coef.c
  ${W}/common_audio/signal_processing/complex_bit_reverse.c
  ${W}/common_audio/signal_processing/complex_fft.c
  ${W}/common_audio/signal_processing/copy_set_operations.c
  ${W}/common_audio/signal_processing/cross_correlation.c
  ${W}/common_audio/signal_processing/division_operations.c
  ${W}/common_audio/signal_processing/dot_product_with_scale.c
  ${W}/common_audio/signal_processing/downsample_fast.c
  ${W}/common_audio/signal_processing/energy.c
  ${W}/common_audio/signal_processing/filter_ar.c
  ${W}/common_audio/signal_processing/filter_ar_fast_q12.c
  ${W}/common_audio/signal_processing/filter_ma_fast_q12.c
  ${W}/common_audio/signal_processing/get_hanning_window.c
  ${W}/common_audio/signal_processing/get_scaling_square.c
  ${W}/common_audio/signal_processing/ilbc_specific_functions.c
  ${W}/common_audio/signal_processing/levinson_durbin.c
  ${W}/common_audio/signal_processing/lpc_to_refl_coef.c
  ${W}/common_audio/signal_processing/min_max_operations.c
  ${W}/common_audio/signal_processing/randomization_functions.c
  ${W}/common_audio/signal_processing/real_fft.c
  ${W}/common_audio/signal_processing/refl_coef_to_lpc.c
  ${W}/common_audio/signal_processing/resample.c
  ${W}/common_audio/signal_processing/resample_48khz.c
  ${W}/common_audio/signal_processing/resample_by_2.c
  ${W}/common_audio/signal_processing/resample_by_2_internal.c
  ${W}/common_audio/signal_processing/resample_fractional.c
  ${W}/common_audio/signal_processing/spl_init.c
  ${W}/common_audio/signal_processing/spl_sqrt.c
  ${W}/common_audio/signal_processing/spl_sqrt_floor.c
  ${W}/common_audio/signal_processing/splitting_filter.c
  ${W}/common_audio/signal_processing/sqrt_of_one_minus_x_squared.c
  ${W}/common_audio/signal_processing/vector_scaling_operations.c
  # ---- audio_processing 公共 ----
  ${W}/common_types.cc
  # ---- beamformer ----
  ${W}/modules/audio_processing/beamformer/array_util.cc
  ${W}/modules/audio_processing/beamformer/covariance_matrix_generator.cc
  ${W}/modules/audio_processing/beamformer/nonlinear_beamformer.cc
  # ---- system_wrappers (Windows 变体) ----
  ${W}/system_wrappers/source/aligned_malloc.cc
  ${W}/system_wrappers/source/cpu_features.cc
  ${W}/system_wrappers/source/condition_variable_event_win.cc
  ${W}/system_wrappers/source/file_impl.cc
  ${W}/system_wrappers/source/trace_impl.cc
  ${W}/system_wrappers/source/rw_lock.cc
  ${W}/system_wrappers/source/rw_lock_win.cc
  ${W}/system_wrappers/source/rw_lock_winxp_win.cc
  ${W}/system_wrappers/source/trace_win.cc
  # ---- 本工程 C-ABI 封装 ----
  ${CMAKE_CURRENT_LIST_DIR}/webrtc_bf_dll.cc
)

add_library(webrtc_bf SHARED ${SRC})

target_link_libraries(webrtc_bf winmm)

set_target_properties(webrtc_bf PROPERTIES
  PREFIX ""
  OUTPUT_NAME "webrtc_bf"
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_LIST_DIR}/../lib"
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_LIST_DIR}/../lib"
)

# 静态链接 C/C++ 运行时与 winpthread, 使 DLL 仅依赖系统库 (kernel32/msvcrt/winmm),
# 避免依赖 MinGW 的 libgcc_s / libstdc++ / libwinpthread-1.dll, 保证自包含分发。
target_link_options(webrtc_bf PRIVATE -static -static-libgcc -static-libstdc++)
