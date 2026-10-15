#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
hardware.py — 麦克风阵列硬件档案 (hardware profile)

不同硬件的麦阵几何、通道布局、SoundConnect conf 命名前缀在此集中登记，
main.py 通过 --hardware 选择 (默认 bothlent 线性 4 麦)。新增硬件只需在
PROFILES 里加一条，无需改动采集/算法代码。

约定:
  * 麦阵为线性阵，Mic0 -> Mic(N-1) 从左到右排列 (面向阵列时)。
  * webrtc Point 用笛卡尔 (x, y, z) 米；以阵列几何中心为原点、沿 x 轴展开，
    故 mic i 的 x = (i - (N-1)/2) * spacing，左右对称。
  * SoundConnect conf 以 profile.conf_prefix 开头 (如 bothlent_line4mic_sc_*.conf)。
"""

from collections import OrderedDict


class HardwareProfile(object):
    """一个麦阵硬件的完整描述。"""

    def __init__(self, key, label, num_mics, spacing, channels,
                 conf_prefix, ref_channels=None):
        self.key = key
        self.label = label
        self.num_mics = num_mics          # 参与波束的麦克风数
        self.spacing = float(spacing)     # 相邻麦间距 (米)
        self.channels = channels          # 采集总通道数 (mic + ref)
        self.conf_prefix = conf_prefix    # SoundConnect conf 文件名前缀
        self.mic_channels = list(range(num_mics))
        self.ref_channels = list(ref_channels or range(num_mics, channels))

    def mic_positions(self):
        """线阵几何: 中心为原点、沿 x 轴、Mic0->MicN-1 左->右。返回 [(x,y,z)] 米。"""
        n = self.num_mics
        s = self.spacing
        return [((i - (n - 1) / 2.0) * s, 0.0, 0.0) for i in range(n)]


# ---- 已登记硬件 -------------------------------------------------------------
PROFILES = OrderedDict()

# bothlent 四麦线阵 + 摄像头一体化模组 (摄像头无内置麦):
#   USB 6ch = ch0-3 mic (Mic0->Mic3 左->右) + ch4-5 ref; 麦间距 3.5cm。
PROFILES["bothlent_line4mic"] = HardwareProfile(
    key="bothlent_line4mic",
    label="Bothlent 线性4麦 (Mic0→Mic3 左→右, 间距3.5cm)",
    num_mics=4,
    spacing=0.035,
    channels=6,
    conf_prefix="bothlent_line4mic_sc_",
)

DEFAULT_HARDWARE = "bothlent_line4mic"


def get_profile(key=None):
    """按 key 取硬件档案; key 为空/未知时返回默认 (bothlent 线性4麦)。"""
    key = key or DEFAULT_HARDWARE
    if key not in PROFILES:
        raise KeyError("未知硬件 '%s'; 可选: %s"
                       % (key, ", ".join(PROFILES.keys())))
    return PROFILES[key]


def profile_keys():
    return list(PROFILES.keys())
