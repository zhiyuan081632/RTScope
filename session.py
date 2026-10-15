#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
session.py — 采集会话控制器 (启动只进界面, 由用户点「开始」才录音)

职责:
  * 枚举输入声卡, 给出默认选中项 (关键字 Source/Sink, WASAPI 优先)。
  * 提供当前硬件下可选算法名列表 (nbf 置顶为默认)。
  * start(): 校验设备/采样率 -> 只构造选中的单个算法处理器 -> 建 raw/proc 双录音
             -> 建并启动 AudioEngine。运行中锁定算法 (第 6 点)。
  * stop():  有序幂等收尾 (先停并 close 流, 再 join 录音线程, 最后 release 原生句柄),
             在解释器 finalize 之前完成, 规避退出 0xc0000142。

不自动启动: 构造 SessionController 只做只读枚举, 不打开任何音频流。
"""

import os

import sounddevice as sd

import applog
from audio_engine import (AudioEngine, WavRecorder, default_capture_dir,
                          resolve_device)
from algorithms import build_algorithm, default_algorithm, list_algorithms
from hardware import DEFAULT_HARDWARE, get_profile, profile_keys
from processors import IdentityProcessor


class SessionController(object):
    def __init__(self, hardware=DEFAULT_HARDWARE, record=True, capture_dir=None):
        self.hw = get_profile(hardware)
        self.record = record                  # 是否录音 (可由 --no-record 关闭)
        self.capture_dir = capture_dir        # 录音根目录 (None=每次 captures/cap_<ts>)
        self.engine = None
        self.processor = None
        self.recorder = None
        self.proc_recorder = None
        self.gain_recorder = None
        self.cap_dir = None
        self.algorithm = None
        self.channels = self.hw.channels
        self.rate = 16000
        self.blocksize = 256
        self.gain_db = 20.0                 # 数字前置增益 (dB) 默认值, 仅录音开始前设置
        self.last_stats = None              # 上次 stop() 的统计 (供界面 toast / 日志)

    # ---- 只读目录信息 (供界面初始化下拉框) --------------------------------
    @property
    def hardware(self):
        return self.hw

    def hardware_keys(self):
        return profile_keys()

    def set_hardware(self, key):
        if self.running:
            raise RuntimeError("运行中不可切换硬件")
        self.hw = get_profile(key)

    def set_gain_db(self, db):
        """设置数字前置增益 (dB); 仅录音开始前调用 (录制中界面锁定), 作为下次录音初值。"""
        self.gain_db = float(db)
        if self.running and self.engine is not None:
            self.engine.set_gain_db(self.gain_db)

    def algorithm_names(self):
        return list_algorithms(self.hw)

    def default_algorithm(self):
        return default_algorithm(self.hw)

    def input_devices(self, min_channels=None):
        """返回 [(index, label)], 仅含输入通道 >= min_channels 的设备。"""
        min_ch = min_channels or self.hw.channels
        out = []
        for idx, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] >= min_ch:
                host = sd.query_hostapis(d["hostapi"])["name"]
                out.append((idx, "%d: %s (%s, %din)"
                            % (idx, d["name"], host, d["max_input_channels"])))
        return out

    def default_device(self, channels=None):
        """自动选中的输入设备 index (关键字 Source/Sink); 失败返回 None。"""
        ch = channels or self.hw.channels
        try:
            idx, _ = resolve_device(None, ch)
            return idx
        except Exception:
            return None

    @property
    def running(self):
        return self.engine is not None

    # ---- 生命周期 ----------------------------------------------------------
    def start(self, device=None, channels=None, rate=16000, blocksize=256,
              algorithm=None, record=True, capture_dir=None, gain_db=None):
        """开始采集; 返回 dict(status/info)。失败抛 RuntimeError。"""
        if self.running:
            raise RuntimeError("已在运行中, 请先停止")

        channels = int(channels or self.hw.channels)
        rate = int(rate)
        blocksize = int(blocksize)

        # 设备解析 + 通道校验
        if device is None:
            device, info = resolve_device(None, channels)
        else:
            device = int(device)
            info = sd.query_devices()[device]
            if info["max_input_channels"] < channels:
                raise RuntimeError("设备 %d (%s) 只有 %d 路输入 < 要求的 %d 路"
                                   % (device, info["name"],
                                      info["max_input_channels"], channels))

        # 采样率: 不可用则回退设备默认
        try:
            sd.check_input_settings(device=device, channels=channels, samplerate=rate)
        except Exception as e:
            new_rate = int(info["default_samplerate"])
            print("[warn] %dHz 不可用 (%s), 回退 %dHz" % (rate, e, new_rate))
            rate = new_rate

        # 算法: 只构造选中的这一个 (不热切换)
        algorithm = algorithm or self.default_algorithm()
        if algorithm:
            processor = build_algorithm(algorithm, self.hw)
            if processor is None:
                raise RuntimeError("算法 '%s' 初始化失败, 无法开始" % algorithm)
        else:
            processor = IdentityProcessor()
            algorithm = "(恒等直通)"
        proc_channels = processor.out_channels or channels

        # 数字前置增益: 仅麦克风通道放大 (ref 不变) 再送算法/显示, 并额外保存 gain.wav
        gain_db = self.gain_db if gain_db is None else float(gain_db)
        self.gain_db = gain_db

        # 录音: captures/cap_<ts>/ 下 raw.wav(原始) + gain.wav(mic 放大后) + proc.wav(算法输出)
        recorder = proc_recorder = gain_recorder = None
        cap_dir = None
        if record:
            cap_dir = capture_dir or default_capture_dir()
            os.makedirs(cap_dir, exist_ok=True)
            # 运行日志直接存到当次 cap_* 目录 (补写启动以来的历史行)
            applog.attach_file(os.path.join(cap_dir, "run.log"))
            recorder = WavRecorder(os.path.join(cap_dir, "raw.wav"), rate, channels)
            gain_recorder = WavRecorder(os.path.join(cap_dir, "gain.wav"), rate, channels)
            proc_recorder = WavRecorder(os.path.join(cap_dir, "proc.wav"), rate, proc_channels)
            recorder.start()
            gain_recorder.start()
            proc_recorder.start()

        # 引擎
        engine = AudioEngine(device, rate, channels, blocksize,
                             processor=processor, recorder=recorder,
                             proc_recorder=proc_recorder,
                             gain_recorder=gain_recorder, gain_db=gain_db,
                             gain_channels=self.hw.num_mics)
        try:
            engine.start()
        except Exception as e:
            self._teardown(engine, processor, recorder, proc_recorder, gain_recorder)
            raise RuntimeError("音频流启动失败: %s" % e)

        self.engine = engine
        self.processor = processor
        self.recorder = recorder
        self.proc_recorder = proc_recorder
        self.gain_recorder = gain_recorder
        self.cap_dir = cap_dir
        self.algorithm = algorithm
        self.channels = channels
        self.rate = rate
        self.blocksize = blocksize

        print("[run] device=%d (%s) rate=%d ch=%d block=%d alg=%s gain=%+.1fdB"
              % (device, info["name"], rate, channels, blocksize, algorithm, gain_db))
        if cap_dir:
            print("[run] 录音 -> %s (raw.wav %dch + gain.wav %dch + proc.wav %dch)"
                  % (cap_dir, channels, channels, proc_channels))
        return {"device": device, "device_name": info["name"], "rate": rate,
                "channels": channels, "blocksize": blocksize, "algorithm": algorithm,
                "proc_channels": proc_channels, "cap_dir": cap_dir, "gain_db": gain_db}

    def stop(self):
        """有序幂等收尾并清空引用; 记录运行统计与保存路径。"""
        if not self.running:
            return
        engine, proc = self.engine, self.processor
        rec, prec, grec = self.recorder, self.proc_recorder, self.gain_recorder
        elapsed = engine.elapsed if engine is not None else 0.0
        xrun = engine.xrun_count if engine is not None else 0
        cap_dir, algorithm, rate = self.cap_dir, self.algorithm, self.rate
        gain_db = self.gain_db
        self.engine = None
        self.processor = None
        self.recorder = None
        self.proc_recorder = None
        self.gain_recorder = None
        self._teardown(engine, proc, rec, prec, grec)

        raw_frames = rec.frames_written if rec is not None else 0
        proc_frames = prec.frames_written if prec is not None else 0
        gain_frames = grec.frames_written if grec is not None else 0
        sr = float(rate or 16000)
        self.last_stats = {
            "elapsed": elapsed, "xrun": xrun, "cap_dir": cap_dir,
            "algorithm": algorithm, "rate": rate, "gain_db": gain_db,
            "raw_frames": raw_frames, "proc_frames": proc_frames,
            "gain_frames": gain_frames,
            "raw_sec": raw_frames / sr, "proc_sec": proc_frames / sr,
        }
        print("[stop] 运行 %.1fs | xrun=%d | 算法 %s | 增益 %+.1fdB | raw %.2fs(%d帧) gain %.2fs(%d帧) proc %.2fs(%d帧)"
              % (elapsed, xrun, algorithm or "-", gain_db,
                 raw_frames / sr, raw_frames, gain_frames / sr, gain_frames,
                 proc_frames / sr, proc_frames))
        if raw_frames and proc_frames:
            # 允许不足一块的内部缓冲尾巴; 相对偏差 >2% 才告警 (捕获旧 0.75× 打包 bug)
            rel = abs(raw_frames - proc_frames) / float(raw_frames)
            if rel > 0.02:
                print("[stop][warn] raw 与 proc 长度偏差 %.1f%% (raw %d / proc %d 帧), 请检查处理器打包"
                      % (rel * 100, raw_frames, proc_frames))
        if cap_dir:
            print("[stop] 数据已保存 -> %s" % cap_dir)

    @staticmethod
    def _teardown(engine, processor, recorder, proc_recorder, gain_recorder=None):
        """先停并 close PortAudio 流 -> join 录音线程 -> release 原生句柄。

        顺序关键: 确保不再有回调进入 SoundConnect.dll / webrtc_bf.dll 后才销毁
        原生句柄, 且在解释器 finalize 之前完成, 规避退出 0xc0000142。
        """
        try:
            if engine is not None:
                engine.stop()
        except Exception:
            pass
        for rec in (recorder, proc_recorder, gain_recorder):
            try:
                if rec is not None:
                    rec.stop()
                    rec.join(timeout=2.0)
            except Exception:
                pass
        try:
            if processor is not None and hasattr(processor, "release"):
                processor.release()
        except Exception:
            pass
