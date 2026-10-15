#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
sc_processors.py — SoundConnect 流式波束成形处理器 (单选, 不热切换)

SCBfProcessor        单个 SoundConnect 实例 (一个 bf_algorithm conf) 的流式封装:
                     float32 多通道块 -> 内部按 SC block(320@16k) 累积 ->
                     processByte(int16) -> 取 ch0 波束输出 -> float32 (m,1)。

本工具不再做热切换: 界面上在开始录音前选定唯一算法, 只构造该算法的一个
实例, 保证 proc 录音只对应一种算法 (见 algorithms.py / session.py)。
  list_sc_algorithms(conf_prefix)  扫描 conf 目录返回可用算法名 (不实例化)
  build_sc_processor(name, ...)    只构造选中的那一个 SCBfProcessor

运行时约定:
  bothlent 系 conf 以 pilot 列作门控 (pilot=0 → 静音)。本工具无外部 VAD,
  故 pilot 列恒置 32767 (常开门), 使 bf 连续出数。
  输入 6ch (4mic+2ref) 补零到 conf 的 numIns=8 (col6=cam 占位, col7=pilot)。
"""

import os
import sys

import numpy as np

from processors import ProcessorBase

_PILOT_ON = 32767

# 工程自包含路径: DLL / 绑定 / conf 均位于 RTScope 下, 可独立拷贝使用
HERE = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(HERE, "lib")
SC_PY_DIR = os.path.join(HERE, "sc_py")
CONF_DIR = os.path.join(HERE, "conf")


def _load_binding(sc_dir):
    if sc_dir not in sys.path:
        sys.path.insert(0, sc_dir)
    from SoundConnect import SoundConnect
    return SoundConnect


class SCBfProcessor(ProcessorBase):
    """单个 SoundConnect bf 算法的流式块处理器。输出 1 通道 (波束 ch0)。"""

    out_channels = 1

    def __init__(self, name, lib_path, conf_path, sc_dir):
        self.name = name
        self.conf_path = conf_path
        SoundConnect = _load_binding(sc_dir)
        self._sc = SoundConnect(lib_path, conf_path)
        self.num_ins = self._sc.numIns()
        self.num_outs = self._sc.numOuts()
        self.num_pilots = self._sc.numPilots()
        self.block_in = self._sc.blockSizeIn()
        self.block_out = self._sc.blockSizeOut()
        self.sr_in = self._sc.sampleRateIn()
        self._bpbin = self._sc.bytesPerBlockIn()
        self._bpbout = self._sc.bytesPerBlockOut()
        import ctypes
        self._ctypes = ctypes
        self._bufin = (ctypes.c_char * self._bpbin)()
        self._bufout = (ctypes.c_char * self._bpbout)()
        self._inbuf = bytearray()
        self.in_channels = 0

    def reset(self, samplerate, in_channels):
        super().reset(samplerate, in_channels)
        if self.sr_in != samplerate:
            raise ValueError("SC %s 采样率 %d != 采集 %d"
                             % (self.name, self.sr_in, samplerate))
        self._inbuf.clear()

    def process(self, block):
        sc = self._sc
        i16 = np.clip(np.round(block * 32767.0), -32768, 32767).astype(np.int16)
        self._inbuf.extend(i16.tobytes())
        # 关键: 输入流只有 in_channels(6) 路, 需按真实通道数计 need/reshape,
        # 不能按 num_ins(8) —— 否则每块多等字节(5120 vs 3840)使输出降为 0.75×,
        # 且 6ch 交织字节被误当 8ch 重排 → mic/ref 通道错位 (proc.wav 音频不对)。
        inch = self.in_channels or i16.shape[1]
        frame_bytes = inch * 2
        need = self.block_in * frame_bytes
        nc = min(inch, self.num_ins - (1 if self.num_pilots else 0))
        outs = []
        while len(self._inbuf) >= need:
            chunk = np.frombuffer(bytes(self._inbuf[:need]), dtype=np.int16).reshape(
                self.block_in, inch)
            combined = np.zeros((self.block_in, self.num_ins), dtype=np.int16)
            combined[:, :nc] = chunk[:, :nc]
            if self.num_pilots:
                combined[:, self.num_ins - 1] = _PILOT_ON  # 常开门
            self._ctypes.memmove(self._bufin, combined.tobytes(), self._bpbin)
            sc.processByte(self._bufin, self._bufout)
            o = np.frombuffer(bytes(self._bufout), dtype=np.int16).reshape(
                self.block_out, self.num_outs)
            outs.append(o[:, 0].astype(np.float32) / 32768.0)
            self._inbuf = self._inbuf[need:]
        if not outs:
            return np.zeros((0, 1), dtype=np.float32)
        return np.concatenate(outs, axis=0).reshape(-1, 1)

    def release(self):
        sc = self._sc
        self._sc = None
        del sc


def default_sc_dir():
    """工程自带的 SoundConnect.py 绑定目录 (自包含, 不依赖外部仓库)。"""
    return SC_PY_DIR


def _sc_conf_files(conf_dir, conf_prefix):
    """返回 conf 目录下匹配前缀的 (算法名, 文件全路径), 按名排序。"""
    conf_dir = conf_dir or CONF_DIR
    if not os.path.isdir(conf_dir):
        return []
    out = []
    for f in sorted(os.listdir(conf_dir)):
        if f.startswith(conf_prefix) and f.endswith(".conf"):
            out.append((f[len(conf_prefix):-len(".conf")], os.path.join(conf_dir, f)))
    return out


def list_sc_algorithms(conf_prefix="bothlent_line4mic_sc_", conf_dir=None):
    """扫描 conf 目录, 返回可用 SoundConnect 算法名列表 (不实例化, 供界面下拉)。"""
    return [name for name, _ in _sc_conf_files(conf_dir, conf_prefix)]


def build_sc_processor(name, conf_prefix="bothlent_line4mic_sc_",
                       sc_dir=None, conf_dir=None):
    """只构造选中算法 name 的一个 SCBfProcessor; 缺库/缺 conf/失败 → None。"""
    sc_dir = sc_dir or default_sc_dir()
    lib = os.path.join(LIB_DIR, "SoundConnect.dll")
    if not os.path.isfile(lib):
        print("[sc] 未找到本地 SoundConnect.dll: %s" % lib)
        return None
    confs = dict(_sc_conf_files(conf_dir, conf_prefix))
    if name not in confs:
        print("[sc] 无算法 '%s' 对应的 conf (前缀 %s)" % (name, conf_prefix))
        return None
    try:
        p = SCBfProcessor(name, lib, confs[name], sc_dir)
        print("[sc] 已加载算法: %-9s (%s)" % (name, os.path.basename(confs[name])))
        return p
    except Exception as e:
        print("[sc] 算法 %s 初始化失败: %s" % (name, e))
        return None
