// webrtc_bf_dll.cc — 把 webrtc NonlinearBeamformer 包成流式 C-ABI DLL
//
// 设计要点:
//   * 与 SoundConnect 一致的“块流式”用法: create 一次, 之后每 10ms(160帧@16k)
//     喂一块交织 int16, 取一块单通道 int16 输出, 内部状态连续保持。
//   * 只用 NonlinearBeamformer + ChannelBuffer, 不依赖 gflags/tinyalsa/wav_file,
//     因此可脱离 bf_file/bf_2mic 的 CLI/ALSA 环境, 在 Windows 下作为纯算法 DLL。
//   * 输入交织顺序: [f0:m0,m1,..,mN-1, f1:m0,...] (与采集通道顺序一致)。
//   * int16 <-> float 归一化按 webrtc 约定 (÷/× 32768), 输出做对称削波。
//
// 供 Python ctypes 调用的导出符号见文件末尾 extern "C" 区块。

#include <cstdint>
#include <cstring>
#include <vector>

#include "webrtc/common_audio/channel_buffer.h"
#include "webrtc/modules/audio_processing/beamformer/array_util.h"
#include "webrtc/modules/audio_processing/beamformer/nonlinear_beamformer.h"

namespace {

struct WbfHandle {
  webrtc::NonlinearBeamformer* bf;
  webrtc::ChannelBuffer<float>* in_buf;
  webrtc::ChannelBuffer<float>* out_buf;
  int num_mics;
  int frames;  // 每块帧数 = sample_rate * chunk_ms / 1000
};

inline int16_t ClampToS16(float v) {
  // v 已是 ±32768 量级 (FloatS16)。对称削波后四舍五入。
  if (v > 32767.0f) v = 32767.0f;
  if (v < -32768.0f) v = -32768.0f;
  return static_cast<int16_t>(v >= 0.0f ? v + 0.5f : v - 0.5f);
}

}  // namespace

extern "C" {

// mic_positions: num_mics*3 个 float, 每个 mic 的 (x,y,z) 米坐标 (连续存放)。
// chunk_ms: 处理块长 (webrtc 要求 10)。sample_rate: 采样率 (16000)。
// 返回句柄; 失败返回 NULL。
__declspec(dllexport) void* wbf_create(const float* mic_positions,
                                       int num_mics,
                                       int chunk_ms,
                                       int sample_rate) {
  if (!mic_positions || num_mics < 2 || sample_rate <= 0 || chunk_ms <= 0) {
    return nullptr;
  }
  std::vector<webrtc::Point> geometry;
  geometry.reserve(num_mics);
  for (int i = 0; i < num_mics; ++i) {
    geometry.push_back(webrtc::Point(mic_positions[3 * i + 0],
                                     mic_positions[3 * i + 1],
                                     mic_positions[3 * i + 2]));
  }

  WbfHandle* h = new WbfHandle();
  h->num_mics = num_mics;
  h->frames = sample_rate * chunk_ms / 1000;
  // 默认指向 broadside (方位角 90°, 垂直于线阵), 与 bf_file 默认一致。
  h->bf = new webrtc::NonlinearBeamformer(geometry);
  h->bf->Initialize(chunk_ms, sample_rate);
  h->in_buf = new webrtc::ChannelBuffer<float>(h->frames, num_mics);
  h->out_buf = new webrtc::ChannelBuffer<float>(h->frames, 1);
  return h;
}

// 每块帧数 (Python 侧据此攒够样本再调用 process)。
__declspec(dllexport) int wbf_block_size(void* handle) {
  return handle ? static_cast<WbfHandle*>(handle)->frames : 0;
}

// 期望的输入 mic 数。
__declspec(dllexport) int wbf_num_mics(void* handle) {
  return handle ? static_cast<WbfHandle*>(handle)->num_mics : 0;
}

// 处理一块: in = frames*num_mics 交织 int16; out = frames 单通道 int16。
__declspec(dllexport) void wbf_process(void* handle,
                                       const int16_t* in,
                                       int16_t* out) {
  if (!handle || !in || !out) return;
  WbfHandle* h = static_cast<WbfHandle*>(handle);
  const int frames = h->frames;
  const int mics = h->num_mics;

  // int16 交织 -> ChannelBuffer 分通道 float (±1)
  for (int m = 0; m < mics; ++m) {
    float* dst = h->in_buf->channels()[m];
    for (int f = 0; f < frames; ++f) {
      dst[f] = static_cast<float>(in[f * mics + m]) * (1.0f / 32768.0f);
    }
  }

  h->bf->ProcessChunk(*h->in_buf, h->out_buf);

  // 单通道 float (±1) -> int16
  const float* src = h->out_buf->channels()[0];
  for (int f = 0; f < frames; ++f) {
    out[f] = ClampToS16(src[f] * 32768.0f);
  }
}

__declspec(dllexport) void wbf_destroy(void* handle) {
  if (!handle) return;
  WbfHandle* h = static_cast<WbfHandle*>(handle);
  delete h->bf;
  delete h->in_buf;
  delete h->out_buf;
  delete h;
}

}  // extern "C"
