#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
offline_eval.py — 离线批量复现算法, 便于横向对比性能

给定一次录音目录 cap_* (含 raw.wav 全通道原始), 用「与实时录音完全相同」的
处理器 (algorithms.build_algorithm) 对 raw 逐块离线复现, 为每个支持的算法生成
一条单通道波束音频, 统一落到 cap_*/offline/<alg>.wav, 并打印时长/RMS/峰值/削波
对比表 (同时写 offline/summary.txt)。默认算法集包含「单路直通(mic0)」基线,
方便与各波束算法直接 A/B 试听对比。

用法 (conda py39):
    python offline_eval.py <cap_dir>
    python offline_eval.py captures/cap_20261015_160623
    python offline_eval.py <cap_dir> --algorithms passthrough,nbf,bypass,mvdr
    python offline_eval.py <cap_dir> --blocksize 256 --hardware bothlent_line4mic
    python offline_eval.py <cap_dir>/raw.wav        # 也可直接给 raw.wav 路径

说明:
  * 复现路径 = reset(sr, 6ch) -> 逐块 process(float32) -> 拼接, 与 audio_engine
    实时回调喂数一致, 故 offline/<alg>.wav 应与当时实时的 proc.wav 高度一致。
  * passthrough 为不经任何 DLL 的 mic0 直通基线 (始终可用); SC 的 bypass 走完整
    SoundConnect 链路但 bf_algorithm=0 (不处理), 二者应近似, 可互为交叉校验。
  * 输出为 FLOAT 子类型单声道 WAV, 与 proc.wav 一致。
"""

import argparse
import os
import sys
import time
from datetime import datetime

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from algorithms import NBF, build_algorithm, nbf_available
from hardware import DEFAULT_HARDWARE, get_profile
from sc_processors import list_sc_algorithms

PASSTHROUGH = "passthrough"      # 不经 DLL 的 mic0 直通基线
OFFLINE_SUBDIR = "offline"


def default_algorithm_set(hw):
    """默认算法集: 单路直通 + nbf(若 DLL 就绪) + 所有 SoundConnect conf(含 bypass)。"""
    names = [PASSTHROUGH]
    if nbf_available():
        names.append(NBF)
    names.extend(list_sc_algorithms(hw.conf_prefix))
    # 去重保序
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def read_raw(raw_path):
    """读 raw.wav -> (float32 (frames, ch), samplerate)。"""
    data, sr = sf.read(raw_path, dtype="float32", always_2d=True)
    return np.ascontiguousarray(data), int(sr)


def run_processor(name, hw, raw, sr, blocksize):
    """用与实时相同的处理器离线复现 name 算法; 返回单通道 float32 (frames,)。"""
    proc = build_algorithm(name, hw)
    if proc is None:
        raise RuntimeError("算法 '%s' 构造失败 (缺 DLL / conf / 初始化错误)" % name)
    channels = raw.shape[1]
    proc.reset(sr, channels)
    outs = []
    try:
        for i in range(0, raw.shape[0], blocksize):
            block = raw[i:i + blocksize]
            o = proc.process(block)
            if o is not None and o.shape[0] > 0:
                outs.append(np.asarray(o, dtype=np.float32).reshape(-1))
    finally:
        if hasattr(proc, "release"):
            try:
                proc.release()
            except Exception:
                pass
    if not outs:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(outs).astype(np.float32)


def stats(x, sr):
    """返回对比统计 dict: 时长/RMS dBFS/峰值 dBFS/削波数。"""
    n = x.shape[0]
    if n == 0:
        return {"sec": 0.0, "rms_db": -np.inf, "peak_db": -np.inf, "clip": 0}
    eps = 1e-12
    rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))
    peak = float(np.max(np.abs(x)))
    clip = int(np.sum(np.abs(x) >= 0.999))
    return {
        "sec": n / float(sr),
        "rms_db": 20.0 * np.log10(rms + eps),
        "peak_db": 20.0 * np.log10(peak + eps),
        "clip": clip,
    }


def resolve_paths(arg):
    """把入参解析为 (cap_dir, raw_path)。支持给 cap 目录或直接给 raw.wav。"""
    p = os.path.abspath(arg)
    if os.path.isfile(p) and p.lower().endswith(".wav"):
        return os.path.dirname(p), p
    raw = os.path.join(p, "raw.wav")
    return p, raw


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="离线批量复现 cap_* 录音的各算法结果, 输出到 cap_*/offline/ 供对比")
    ap.add_argument("cap", help="cap_* 目录 (含 raw.wav) 或直接给 raw.wav 路径")
    ap.add_argument("--algorithms", default=None,
                    help="逗号分隔的算法名子集 (默认: 单路直通 + nbf + 所有 SC conf)")
    ap.add_argument("--blocksize", type=int, default=256,
                    help="逐块复现的块长帧数 (默认 256, 与实时一致)")
    ap.add_argument("--hardware", default=DEFAULT_HARDWARE,
                    help="硬件档案 key (默认 %s)" % DEFAULT_HARDWARE)
    ap.add_argument("--out-subdir", default=OFFLINE_SUBDIR,
                    help="输出子目录名 (默认 offline)")
    args = ap.parse_args(argv)

    cap_dir, raw_path = resolve_paths(args.cap)
    if not os.path.isfile(raw_path):
        print("[offline][ERR] 找不到 raw.wav: %s" % raw_path)
        return 2

    hw = get_profile(args.hardware)
    raw, sr = read_raw(raw_path)
    out_dir = os.path.join(cap_dir, args.out_subdir)
    os.makedirs(out_dir, exist_ok=True)

    if args.algorithms:
        algs = [a.strip() for a in args.algorithms.split(",") if a.strip()]
    else:
        algs = default_algorithm_set(hw)

    print("=" * 72)
    print("[offline] 输入:   %s" % raw_path)
    print("[offline] 硬件:   %s (%d mic, 间距 %.3fm, %dch)"
          % (hw.label, hw.num_mics, hw.spacing, hw.channels))
    print("[offline] 采样率: %d Hz | raw %.2fs (%d 帧, %d ch)"
          % (sr, raw.shape[0] / float(sr), raw.shape[0], raw.shape[1]))
    print("[offline] 输出到: %s" % out_dir)
    print("[offline] 算法:   %s" % ", ".join(algs))
    print("-" * 72)

    rows = []
    for name in algs:
        t0 = time.time()
        try:
            if name == PASSTHROUGH:
                # 不经任何 DLL 的 mic0 直通基线
                x = np.ascontiguousarray(raw[:, 0]).astype(np.float32)
            else:
                x = run_processor(name, hw, raw, sr, args.blocksize)
        except Exception as e:
            print("  %-12s [ERR] %s" % (name, e))
            rows.append((name, None, None, str(e)))
            continue
        out_path = os.path.join(out_dir, "%s.wav" % name)
        sf.write(out_path, x.reshape(-1, 1), sr, format="WAV", subtype="FLOAT")
        st = stats(x, sr)
        dt = time.time() - t0
        print("  %-12s -> %-16s %6.2fs  RMS %7.2f dB  peak %7.2f dB  clip %5d  (%.2fs)"
              % (name, os.path.basename(out_path), st["sec"], st["rms_db"],
                 st["peak_db"], st["clip"], dt))
        rows.append((name, st, dt, None))

    # summary.txt
    summary_path = os.path.join(out_dir, "summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("RTScope 离线算法对比  %s\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        f.write("输入: %s\n" % raw_path)
        f.write("硬件: %s | 采样率 %d | raw %.2fs (%d 帧, %d ch) | blocksize %d\n"
                % (hw.label, sr, raw.shape[0] / float(sr), raw.shape[0],
                   raw.shape[1], args.blocksize))
        f.write("-" * 72 + "\n")
        f.write("%-12s %8s %10s %10s %8s %8s\n"
                % ("algorithm", "sec", "rms_dB", "peak_dB", "clip", "cost_s"))
        for name, st, dt, err in rows:
            if st is None:
                f.write("%-12s [ERR] %s\n" % (name, err))
            else:
                f.write("%-12s %8.2f %10.2f %10.2f %8d %8.2f\n"
                        % (name, st["sec"], st["rms_db"], st["peak_db"], st["clip"], dt))
    print("-" * 72)
    ok = sum(1 for _, st, _, _ in rows if st is not None)
    print("[offline] 完成: %d/%d 条, 输出于 %s (含 summary.txt)" % (ok, len(algs), out_dir))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
