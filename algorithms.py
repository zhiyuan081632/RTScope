#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
algorithms.py — 统一算法目录 (SoundConnect 多算法 + webrtc nbf)

界面在开始录音前从这里取「可选算法名」列表, 用户选定唯一一个后由
build_algorithm() 只构造该算法的处理器实例 (不再热切换), 保证 proc 录音
只对应一种算法。

约定:
  * nbf  = webrtc NonlinearBeamformer (Windows DLL), 始终置顶为默认算法。
  * 其余 = SoundConnect conf (bothlent_line4mic_sc_<name>.conf)。
  * 所有算法输出均为单通道波束 (out_channels=1), 供单轨显示与 proc.wav。
"""

import os

from sc_processors import build_sc_processor, list_sc_algorithms
from webrtc_processors import LIB_PATH as WEBRTC_LIB, build_webrtc_processor

# webrtc 非线性波束成形在界面上的显示名
NBF = "nbf"


def nbf_available():
    """webrtc_bf.dll 是否就绪 (决定 nbf 是否出现在算法列表)。"""
    return os.path.isfile(WEBRTC_LIB)


# 界面下拉框中隐藏的算法 (仍可由 build_algorithm 直接构造, 仅供调试)
HIDDEN_ALGORITHMS = {"bypass"}


def list_algorithms(hw):
    """返回可选算法名列表 (界面下拉), nbf 置顶, 隐藏 HIDDEN_ALGORITHMS。"""
    names = []
    if nbf_available():
        names.append(NBF)
    names.extend(n for n in list_sc_algorithms(hw.conf_prefix)
                 if n not in HIDDEN_ALGORITHMS)
    return names


def default_algorithm(hw):
    """默认算法: 优先 nbf, 不可用时退回 SoundConnect 首个, 再不可用返回 None。"""
    names = list_algorithms(hw)
    return names[0] if names else None


def build_algorithm(name, hw):
    """构造选中算法 name 的单个处理器; 失败返回 None。

    name == 'nbf' -> webrtc NonlinearBeamformer (用硬件档案的麦阵几何)
    其它          -> SoundConnect 对应 conf
    """
    if name == NBF:
        return build_webrtc_processor(name=NBF, mic_positions=hw.mic_positions())
    return build_sc_processor(name, conf_prefix=hw.conf_prefix)
