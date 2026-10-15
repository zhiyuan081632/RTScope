#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
webrtc_processors.py — webrtc NonlinearBeamformer 流式处理器 (Windows DLL)

与 sc_processors.SCBfProcessor 并列, 同样实现 ProcessorBase, 输出单通道波束,
可直接塞进 HotSwapBfProcessor 与 SoundConnect 各算法一起热切换。

依赖:
  lib/webrtc_bf.dll  —— 由 webrtc_bf/ 下的 C-ABI 封装 + MinGW CMake 编译得到
                        (导出 wbf_create/wbf_block_size/wbf_num_mics/wbf_process/wbf_destroy)。

麦阵几何:
  本板为 4 麦线阵, 间距 3.5cm。以阵列中心为原点、沿 x 轴排布:
      x = [-1.5, -0.5, +0.5, +1.5] * 0.035 = [-0.0525, -0.0175, 0.0175, 0.0525] m
  webrtc NonlinearBeamformer 默认指向 broadside (方位角 90°, 垂直于线阵)。
"""

import ctypes
import os

import numpy as np

from processors import ProcessorBase

HERE = os.path.dirname(os.path.abspath(__file__))
LIB_PATH = os.path.join(HERE, "lib", "webrtc_bf.dll")

# 4 麦线阵, 间距 3.5cm, 中心为原点, 沿 x 轴 (webrtc Point = 笛卡尔 x,y,z 米)
_SPACING = 0.035
DEFAULT_MIC_POSITIONS = [
    (-1.5 * _SPACING, 0.0, 0.0),
    (-0.5 * _SPACING, 0.0, 0.0),
    (+0.5 * _SPACING, 0.0, 0.0),
    (+1.5 * _SPACING, 0.0, 0.0),
]


class WebRtcBfProcessor(ProcessorBase):
    """webrtc 非线性波束成形, 流式块处理。输出 1 通道。"""

    out_channels = 1

    def __init__(self, name="nbf", lib_path=LIB_PATH,
                 mic_positions=None, chunk_ms=10, sample_rate=16000):
        self.name = name
        self.lib_path = lib_path
        self.chunk_ms = chunk_ms
        self.sample_rate = sample_rate
        self.mic_positions = [tuple(p) for p in (mic_positions or DEFAULT_MIC_POSITIONS)]
        self.num_mics = len(self.mic_positions)

        self._dll = ctypes.CDLL(lib_path)
        self._dll.wbf_create.argtypes = [
            ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_int, ctypes.c_int]
        self._dll.wbf_create.restype = ctypes.c_void_p
        self._dll.wbf_block_size.argtypes = [ctypes.c_void_p]
        self._dll.wbf_block_size.restype = ctypes.c_int
        self._dll.wbf_num_mics.argtypes = [ctypes.c_void_p]
        self._dll.wbf_num_mics.restype = ctypes.c_int
        self._dll.wbf_process.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_int16), ctypes.POINTER(ctypes.c_int16)]
        self._dll.wbf_process.restype = None
        self._dll.wbf_destroy.argtypes = [ctypes.c_void_p]
        self._dll.wbf_destroy.restype = None

        flat = (ctypes.c_float * (self.num_mics * 3))()
        for i, (x, y, z) in enumerate(self.mic_positions):
            flat[3 * i + 0] = x
            flat[3 * i + 1] = y
            flat[3 * i + 2] = z
        self._handle = self._dll.wbf_create(flat, self.num_mics, chunk_ms, sample_rate)
        if not self._handle:
            raise RuntimeError("wbf_create 失败 (返回 NULL)")

        self.frames = self._dll.wbf_block_size(self._handle)   # 160 @10ms/16k
        self._in = np.zeros(self.frames * self.num_mics, dtype=np.int16)
        self._out = np.zeros(self.frames, dtype=np.int16)
        self._in_p = self._in.ctypes.data_as(ctypes.POINTER(ctypes.c_int16))
        self._out_p = self._out.ctypes.data_as(ctypes.POINTER(ctypes.c_int16))
        self._acc = np.zeros((0, self.num_mics), dtype=np.int16)
        self.in_channels = 0

    def reset(self, samplerate, in_channels):
        super().reset(samplerate, in_channels)
        if samplerate != self.sample_rate:
            raise ValueError("webrtc bf 采样率 %d != 采集 %d"
                             % (self.sample_rate, samplerate))
        if in_channels < self.num_mics:
            raise ValueError("采集通道 %d < 麦阵 mic 数 %d"
                             % (in_channels, self.num_mics))
        self._acc = np.zeros((0, self.num_mics), dtype=np.int16)

    def process(self, block):
        # 只取前 num_mics 个 mic 通道 (采集为 4mic+2ref, ref 不参与 webrtc 波束)
        mics = block[:, :self.num_mics]
        i16 = np.clip(np.round(mics * 32767.0), -32768, 32767).astype(np.int16)
        self._acc = np.concatenate([self._acc, i16], axis=0) if len(self._acc) else i16

        outs = []
        nf = self.frames
        while self._acc.shape[0] >= nf:
            chunk = np.ascontiguousarray(self._acc[:nf].reshape(-1))  # 交织 [f*mics+m]
            self._in[:] = chunk
            self._dll.wbf_process(self._handle, self._in_p, self._out_p)
            outs.append(self._out.astype(np.float32) / 32768.0)
            self._acc = self._acc[nf:]
        if not outs:
            return np.zeros((0, 1), dtype=np.float32)
        return np.concatenate(outs).reshape(-1, 1)

    def release(self):
        if getattr(self, "_handle", None):
            self._dll.wbf_destroy(self._handle)
            self._handle = None


def build_webrtc_processor(lib_path=LIB_PATH, mic_positions=None, name="nbf"):
    """构造 WebRtcBfProcessor (界面显示名 nbf); DLL 缺失/初始化失败 → 返回 None。"""
    if not os.path.isfile(lib_path):
        print("[nbf] 未找到 webrtc_bf.dll: %s (先编译 webrtc_bf/)" % lib_path)
        return None
    try:
        p = WebRtcBfProcessor(name=name, lib_path=lib_path, mic_positions=mic_positions)
        print("[nbf] 已加载算法: %-9s (%d mic 线阵, block=%d)"
              % (name, p.num_mics, p.frames))
        return p
    except Exception as e:
        print("[nbf] 初始化失败: %s" % e)
        return None
