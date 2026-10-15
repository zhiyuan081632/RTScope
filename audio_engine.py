#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
audio_engine.py — 多通道实时采集引擎（直通 + 算法双路径）+ WAV 录音

设计要点
--------
- sounddevice.InputStream 回调线程只做「拷贝 -> processor -> 入队」，绝不做重活。
- 双路径：每个采集块同时保留 raw(直通) 与 proc(算法处理后) 两路，
  上层视图可实时切换显示。当前 processor 为恒等，proc == raw。
- 采集数据原样保留：不做 mute / 置零 / 归一化（遵循项目"采过来什么就是什么"约定）。
- 录音落 float32 WAV，保留原始精度。
"""

import os
import queue
import threading
import time
from datetime import datetime

import numpy as np
import sounddevice as sd
import soundfile as sf

from processors import ProcessorBase, IdentityProcessor


# ----------------------------------------------------------------------------
# 设备解析
# ----------------------------------------------------------------------------
def resolve_device(device_arg, channels, keyword="Source/Sink"):
    """返回 (device_index, device_info)。

    device_arg 为 None 时按关键字自动识别满足通道数要求的输入设备，WASAPI 优先。
    """
    devs = sd.query_devices()
    if device_arg is not None:
        info = devs[device_arg]
        if info["max_input_channels"] < channels:
            raise RuntimeError(
                "设备 %d (%s) 只有 %d 路输入，少于要求的 %d 路"
                % (device_arg, info["name"], info["max_input_channels"], channels))
        return int(device_arg), info

    candidates = []
    for idx, d in enumerate(devs):
        if d["max_input_channels"] >= channels and keyword.lower() in d["name"].lower():
            host = sd.query_hostapis(d["hostapi"])["name"]
            prio = 0 if "WASAPI" in host else (1 if "DirectSound" in host else 2)
            candidates.append((prio, idx, d, host))
    if not candidates:
        raise RuntimeError(
            "未找到名称含 '%s' 且输入通道 >= %d 的设备，请用 --list 查看后手动 --device 指定"
            % (keyword, channels))
    candidates.sort(key=lambda x: x[0])
    _, idx, info, host = candidates[0]
    print("[auto] 选中设备 %d: %s (%s), %d in"
          % (idx, info["name"], host, info["max_input_channels"]))
    return idx, info


# ----------------------------------------------------------------------------
# 录音线程：从队列取 block 写 soundfile（float32 WAV）
# ----------------------------------------------------------------------------
class WavRecorder(threading.Thread):
    def __init__(self, path, samplerate, channels):
        super().__init__(daemon=True)
        self.path = path
        self.samplerate = samplerate
        self.channels = channels
        self.q = queue.Queue()
        self._stop_evt = threading.Event()
        self.frames_written = 0

    def put(self, block):
        self.q.put(block)

    def stop(self):
        self._stop_evt.set()

    def run(self):
        d = os.path.dirname(os.path.abspath(self.path))
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        with sf.SoundFile(self.path, mode="w", samplerate=self.samplerate,
                          channels=self.channels, format="WAV", subtype="FLOAT") as f:
            while True:
                try:
                    block = self.q.get(timeout=0.2)
                except queue.Empty:
                    if self._stop_evt.is_set() and self.q.empty():
                        break
                    continue
                if block is None:
                    break
                f.write(block)
                self.frames_written += block.shape[0]
                self.q.task_done()
        print("[rec] 已写入 %s (%.2f s)"
              % (self.path, self.frames_written / float(self.samplerate)))


# ----------------------------------------------------------------------------
# 采集引擎
# ----------------------------------------------------------------------------
class AudioEngine(object):
    """InputStream -> processor -> (raw, proc) 双路入队 + 录音。

    显示队列元素为 (raw_block, proc_block)，均 float32 (frames, ch)。
    """

    def __init__(self, device, samplerate, channels, blocksize,
                 processor=None, recorder=None, proc_recorder=None):
        self.device = device
        self.samplerate = samplerate
        self.channels = channels
        self.blocksize = blocksize
        self.processor = processor or IdentityProcessor()
        self.recorder = recorder                # 原始直通录音 (raw)
        self.proc_recorder = proc_recorder      # 算法处理后录音 (proc)

        self.processor.reset(samplerate, channels)
        self.proc_channels = self.processor.out_channels or channels

        self.disp_q = queue.Queue(maxsize=4000)
        self.xrun_count = 0
        self._t0 = None
        self._stopped = False
        self.stream = sd.InputStream(
            samplerate=samplerate, blocksize=blocksize, device=device,
            channels=channels, dtype="float32", callback=self._callback)

    def _callback(self, indata, frames, time_info, status):
        if self._t0 is None:
            self._t0 = time.time()
        if status:
            self.xrun_count += 1
        raw = np.array(indata, copy=True)
        # 录音落直通原始数据
        if self.recorder is not None:
            self.recorder.put(raw)
        # 算法路径
        try:
            proc = self.processor.process(raw)
        except Exception as e:  # 算法异常不拖垮采集
            proc = raw
            self._proc_err = str(e)
        # 录音落算法处理后数据 (当前选中算法的波束输出)
        if self.proc_recorder is not None and proc is not None and proc.shape[0] > 0:
            self.proc_recorder.put(np.asarray(proc, dtype=np.float32))
        try:
            self.disp_q.put_nowait((raw, proc))
        except queue.Full:
            try:
                self.disp_q.get_nowait()
                self.disp_q.put_nowait((raw, proc))
            except queue.Empty:
                pass

    def start(self):
        self.stream.start()

    def stop(self):
        # 幂等: closeEvent 与 main.finally 可能各调一次, 重复关闭不得抛错/崩溃
        if self._stopped:
            return
        self._stopped = True
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass

    @property
    def elapsed(self):
        return 0.0 if self._t0 is None else (time.time() - self._t0)

    @property
    def algorithm_name(self):
        """当前处理器名 (单选算法), 供界面显示; 恒等时返回 None。"""
        return getattr(self.processor, "name", None)


def default_capture_dir(base=None):
    """本次采集目录: captures/cap_<YYYYMMDD_HHMMSS>/ (raw 与 proc 两个 wav 同放于此)。"""
    base = base or os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(base, "cap_%s" % ts)


def default_output_path(subdir="rec"):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(subdir, "rt_capture_%s.wav" % ts)


def default_channel_labels(n_channels):
    if n_channels == 6:
        return ["MIC0", "MIC1", "MIC2", "MIC3", "REF0", "REF1"]
    return ["CH%d" % i for i in range(n_channels)]
