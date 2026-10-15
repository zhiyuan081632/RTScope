#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
offline_eval.py — 离线批量复现算法, 便于横向对比性能

给定一次录音目录 cap_*, 用「与实时录音完全相同」的处理器 (algorithms.build_algorithm)
逐块离线复现, 为每个支持的算法生成一条单通道波束音频, 统一落到 cap_*/offline/<alg>.wav,
并打印时长/RMS/峰值/削波对比表 (同时写 offline/summary.txt)。默认算法集包含第一路 mic
直通基线(mic1), 方便与各波束算法直接 A/B 试听对比。
输入音频优先取 gain.wav (录制时已施加前置增益、即实时真正送算法的信号), 无则回退 raw.wav;
故离线复现与实时 proc.wav 一致 (含增益)。

用法 (conda py39):
    python offline_eval.py <cap_dir>                 # 优先读 gain.wav (含录制时增益)
    python offline_eval.py captures/cap_20261015_160623
    python offline_eval.py <cap_dir> --algorithms mic1,nbf,dis_bf,mvdr
    python offline_eval.py <cap_dir> --blocksize 256 --hardware bothlent_line4mic
    python offline_eval.py <cap_dir> --gain-db 6     # 额外增益 (仅回退读 raw.wav 或想再加时用)
    python offline_eval.py <cap_dir>/gain.wav        # 也可直接给某个 .wav 路径

说明:
  * 复现路径 = reset(sr, 6ch) -> 逐块 process(float32) -> 拼接, 与 audio_engine
    实时回调喂数一致; 且默认读 gain.wav (实时真正送算法的信号), 故 offline/<alg>.wav
    应与当时实时的 proc.wav 高度一致 (含前置增益)。
  * mic1   = 直接取源音频第一路 mic (不经任何 DLL, 始终可用) 作绝对基线;
    dis_bf = 走完整 SoundConnect 链路但禁用波束(bf_algorithm=0, 由 bypass conf 构造),
             后续可在该链路上加 agc/ns 等做对比。二者相差数 dB 属 SC 链路增益/量化, 非 bug。
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

MIC1 = "mic1"                    # 第一路 mic (源[:,0], gain.wav 优先) 原样直通, 不经任何 DLL
DIS_BF = "dis_bf"                # 走完整 SC 链路但禁用波束(bf_algorithm=0); 便于后续加 agc 等对比
OFFLINE_SUBDIR = "offline"

# 展示名 -> build_algorithm 实际构造名 (dis_bf 由 SC 的 bypass conf 构造)
_BUILD_NAME = {DIS_BF: "bypass"}
# 若用户直接传 SC 原始名 bypass, 输出仍统一命名为 dis_bf
_DISPLAY_NAME = {"bypass": DIS_BF}


def _build_name(name):
    """展示名 -> 实际用于 build_algorithm 的构造名。"""
    return _BUILD_NAME.get(name, name)


def _display_name(name):
    """构造名/别名 -> 统一展示与输出文件名。"""
    return _DISPLAY_NAME.get(name, name)


def default_algorithm_set(hw):
    """默认算法集: mic1 直通 + nbf(若 DLL 就绪) + 所有 SoundConnect conf。

    其中 SC 的 bypass 统一以 dis_bf 命名 (禁用波束, 后续可加 agc/ns 等对比)。
    """
    names = [MIC1]
    if nbf_available():
        names.append(NBF)
    names.extend(_display_name(n) for n in list_sc_algorithms(hw.conf_prefix))
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


def resolve_source(arg):
    """把入参解析为 (cap_dir, src_path, src_kind)。

    支持给 cap 目录或直接给某个 .wav 路径。给目录时优先 gain.wav (录制时已含前置
    增益、即实时真正送算法的信号), 无则回退 raw.wav (原始未加增益)。
    src_kind ∈ {'gain','raw'} 标明读到的是放大后还是原始。
    """
    p = os.path.abspath(arg)
    if os.path.isfile(p) and p.lower().endswith(".wav"):
        kind = "gain" if os.path.basename(p).lower() == "gain.wav" else "raw"
        return os.path.dirname(p), p, kind
    gain = os.path.join(p, "gain.wav")
    if os.path.isfile(gain):
        return p, gain, "gain"
    return p, os.path.join(p, "raw.wav"), "raw"


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="离线批量复现 cap_* 录音的各算法结果, 输出到 cap_*/offline/ 供对比")
    ap.add_argument("cap", help="cap_* 目录 (优先 gain.wav, 回退 raw.wav) 或直接给某个 .wav 路径")
    ap.add_argument("--algorithms", default=None,
                    help="逗号分隔的算法名子集 (默认: mic1 直通 + nbf + 所有 SC conf; 如 mic1,nbf,dis_bf,mvdr)")
    ap.add_argument("--blocksize", type=int, default=256,
                    help="逐块复现的块长帧数 (默认 256, 与实时一致)")
    ap.add_argument("--gain-db", dest="gain_db", type=float, default=0.0,
                    help="额外数字增益 dB (默认 0, 仅放大 mic 通道、ref 不变)。源默认取 gain.wav 已含录制时增益, "
                         "通常无需再设; 仅回退读 raw.wav 或想在 gain.wav 基础上再加增益时使用")
    ap.add_argument("--hardware", default=DEFAULT_HARDWARE,
                    help="硬件档案 key (默认 %s)" % DEFAULT_HARDWARE)
    ap.add_argument("--out-subdir", default=OFFLINE_SUBDIR,
                    help="输出子目录名 (默认 offline)")
    args = ap.parse_args(argv)

    cap_dir, src_path, src_kind = resolve_source(args.cap)
    if not os.path.isfile(src_path):
        print("[offline][ERR] 找不到输入音频 (gain.wav / raw.wav): %s" % src_path)
        return 2

    hw = get_profile(args.hardware)
    src, sr = read_raw(src_path)
    if args.gain_db:
        # 额外增益: 仅放大 mic 通道 (前 num_mics 路), ref 通道不变; 一般 gain.wav 已含录制增益无需再设
        n_mic = min(hw.num_mics, src.shape[1])
        src = src.copy()
        src[:, :n_mic] *= (10.0 ** (args.gain_db / 20.0))
    out_dir = os.path.join(cap_dir, args.out_subdir)
    os.makedirs(out_dir, exist_ok=True)

    if args.algorithms:
        algs = [a.strip() for a in args.algorithms.split(",") if a.strip()]
    else:
        algs = default_algorithm_set(hw)

    src_tag = "gain.wav (含录制时前置增益)" if src_kind == "gain" else "raw.wav (原始未加增益)"
    print("=" * 72)
    print("[offline] 输入:   %s  [%s]" % (src_path, src_tag))
    print("[offline] 硬件:   %s (%d mic, 间距 %.3fm, %dch)"
          % (hw.label, hw.num_mics, hw.spacing, hw.channels))
    print("[offline] 采样率: %d Hz | 源 %.2fs (%d 帧, %d ch) | 额外增益 %+.1f dB"
          % (sr, src.shape[0] / float(sr), src.shape[0], src.shape[1], args.gain_db))
    print("[offline] 输出到: %s" % out_dir)
    print("[offline] 算法:   %s" % ", ".join(_display_name(a) for a in algs))
    print("-" * 72)

    rows = []
    for name in algs:
        disp = _display_name(name)
        t0 = time.time()
        try:
            if name == MIC1:
                # 源音频第一路 mic 原样直通, 不经任何 DLL (gain.wav 优先, 即放大后)
                x = np.ascontiguousarray(src[:, 0]).astype(np.float32)
            else:
                x = run_processor(_build_name(name), hw, src, sr, args.blocksize)
        except Exception as e:
            print("  %-12s [ERR] %s" % (disp, e))
            rows.append((disp, None, None, str(e)))
            continue
        out_path = os.path.join(out_dir, "%s.wav" % disp)
        sf.write(out_path, x.reshape(-1, 1), sr, format="WAV", subtype="FLOAT")
        st = stats(x, sr)
        dt = time.time() - t0
        print("  %-12s -> %-16s %6.2fs  RMS %7.2f dB  peak %7.2f dB  clip %5d  (%.2fs)"
              % (disp, os.path.basename(out_path), st["sec"], st["rms_db"],
                 st["peak_db"], st["clip"], dt))
        rows.append((disp, st, dt, None))

    # summary.txt
    summary_path = os.path.join(out_dir, "summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("RTScope 离线算法对比  %s\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        f.write("输入: %s [%s]\n" % (src_path, src_tag))
        f.write("硬件: %s | 采样率 %d | 源 %.2fs (%d 帧, %d ch) | blocksize %d | 额外增益 %+.1f dB\n"
                % (hw.label, sr, src.shape[0] / float(sr), src.shape[0],
                   src.shape[1], args.blocksize, args.gain_db))
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
