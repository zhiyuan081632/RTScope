#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
processors.py — 流式块处理器（算法插槽）

采集引擎逐块调用 processor.process(block)，得到「算法路径(PROC)」数据，
与「直通路径(RAW)」并行供视图切换显示。

阶段 1 只有 IdentityProcessor（恒等，PROC == RAW）。
阶段 2 再实现 SCBfProcessor：复用 AVSE demo 的流式 SoundConnect Python 绑定
        （AVSE/RAVEN/DEMO/SoundConnect.py / bf_engine.py），加载 BF conf，逐块喂入，
        取 ch0（含 numOuts>1 防御）作为波束输出。
"""

import numpy as np


class ProcessorBase(object):
    """流式块处理器契约。

    子类实现 process(block)：
        入参  block: (frames, in_channels) float32
        返回  out:   (frames, out_channels) float32
    out_channels 可与 in_channels 不同（如 BF 输出单波束）；置 None 表示与输入相同。

    注意：process() 运行在 PortAudio 回调线程。轻算法可直接算；重算法
    （SoundConnect/DeepFilterNet）应自带内部缓冲，或改由独立线程消费队列驱动，
    以免回调超时导致 xrun。
    """

    #: 输出通道数；None = 与输入相同
    out_channels = None

    def reset(self, samplerate, in_channels):
        """流开始时调用一次，初始化内部状态。"""
        self.samplerate = samplerate
        self.in_channels = in_channels

    def process(self, block):
        raise NotImplementedError


class IdentityProcessor(ProcessorBase):
    """恒等直通（阶段 1 占位）：PROC 路等同 RAW。"""

    def process(self, block):
        return block


# ----------------------------------------------------------------------------
# 阶段 2 预留：流式 SoundConnect 波束成形处理器
# ----------------------------------------------------------------------------
# class SCBfProcessor(ProcessorBase):
#     """复用 AVSE 流式 SoundConnect 绑定做实时 BF。
#
#     out_channels = 1  # 单波束（按 conf numOuts 实际值防御性取 ch0）
#
#     def __init__(self, conf_path, mic_channels=(0, 1, 2, 3), ref_channels=(4, 5)):
#         self.conf_path = conf_path
#         ...  # 加载 SoundConnect.py，按 conf 组装 chorder/nummics/numrefs
#
#     def reset(self, samplerate, in_channels):
#         super().reset(samplerate, in_channels)
#         ...  # 初始化 SC 引擎实例
#
#     def process(self, block):
#         ...  # 逐块喂 SC，取 ch0，reshape (frames, 1) 返回
#         return out
# ----------------------------------------------------------------------------
