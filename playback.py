#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
playback.py — RTScope 回放播放器 (Audition 式: 从头 / 点选位置播放)

用 sounddevice.OutputStream 把一维 float32 音频从指定样本位置送出到系统默认
输出设备; 回调只按读头拷贝, 播放头位置由累计帧数得到, 供界面画播放头竖线。

    p = Player(samplerate=16000)
    p.load(data_1d_float32)        # 载入编辑态波形 (proc 或 raw mic0)
    p.play(start_sample=0)         # 从指定位置开始播放
    ... p.position / p.playing     # 轮询播放头 (样本)
    p.stop()                        # 停止并关流
"""

import threading

import numpy as np
import sounddevice as sd


class Player(object):
    def __init__(self, samplerate=16000, device=None):
        self.samplerate = int(samplerate)
        self.device = device                 # None = 系统默认输出设备
        self.data = np.zeros(0, dtype=np.float32)
        self._head = 0
        self._stream = None
        self._lock = threading.Lock()
        self.finished = False                # 播放到底自然结束标志

    # ---- 载入 ------------------------------------------------------------
    def load(self, data_1d, samplerate=None):
        """载入一维 float32 音频 (会拷一份, 夹到 [-1,1])。"""
        if samplerate:
            self.samplerate = int(samplerate)
        arr = np.asarray(data_1d, dtype=np.float32).reshape(-1)
        self.data = np.clip(arr, -1.0, 1.0)
        self._head = 0
        self.finished = False

    @property
    def duration(self):
        return self.data.shape[0] / float(self.samplerate) if self.samplerate else 0.0

    @property
    def n_samples(self):
        return int(self.data.shape[0])

    @property
    def playing(self):
        return self._stream is not None

    @property
    def position(self):
        """当前播放头 (样本)。"""
        return min(self._head, self.n_samples)

    # ---- 播放 ------------------------------------------------------------
    def _callback(self, outdata, frames, time_info, status):
        with self._lock:
            n = self.n_samples
            start = self._head
            take = min(frames, max(0, n - start))
            if take > 0:
                outdata[:take, 0] = self.data[start:start + take]
                self._head = start + take
            if take < frames:
                outdata[take:, 0] = 0.0
            done = self._head >= n
        if done:
            self.finished = True
            raise sd.CallbackStop()

    def play(self, start_sample=0):
        """从 start_sample 开始播放; 若正在播放先停。"""
        self.stop()
        if self.n_samples == 0:
            return False
        with self._lock:
            self._head = max(0, min(int(start_sample), self.n_samples - 1))
            self.finished = False
        try:
            self._stream = sd.OutputStream(
                samplerate=self.samplerate, device=self.device,
                channels=1, dtype="float32", blocksize=512,
                callback=self._callback)
            self._stream.start()
        except Exception as e:
            self._stream = None
            print("[play] 无法打开输出流: %s" % e)
            return False
        return True

    def stop(self):
        """停止并关闭输出流 (幂等)。"""
        with self._lock:
            s = self._stream
            self._stream = None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
