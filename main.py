#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
main.py — RTScope 入口

启动只进控制面板 (Adobe Audition 风格), 不自动录音: 在界面里选声卡/参数/算法,
点「开始」才采集。显示为单通道算法波束 (默认 nbf), 黑底浅绿滚动波形 + 右侧 RMS 标尺。
录音存 captures/cap_<时间戳>/raw.wav (原始多通道) + gain.wav(放大后) + proc.wav (所选单一算法)。

用法（conda py39）
------------------
    python main.py --list                 # 列出音频设备后退出
    python main.py                        # bothlent 线性4麦, 启动控制面板，但不自动录音
    python main.py --algorithm nbf --window 10
    python main.py --no-record            # 只显示不录音
"""

import argparse
import os
import sys

# 保证以脚本所在目录为模块根
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sounddevice as sd  # noqa: E402

import applog  # noqa: E402
from hardware import DEFAULT_HARDWARE, profile_keys  # noqa: E402
from session import SessionController  # noqa: E402


def build_argparser():
    ap = argparse.ArgumentParser(
        description="RTScope — 实时麦阵采集 + Audition 风格波形显示")
    ap.add_argument("--hardware", type=str, default=DEFAULT_HARDWARE,
                    choices=profile_keys(),
                    help="麦克风阵列硬件 (默认 %s: bothlent 线性4麦)" % DEFAULT_HARDWARE)
    ap.add_argument("--device", type=int, default=None,
                    help="输入设备索引初值（默认按关键字 'Source/Sink' 自动识别）")
    ap.add_argument("--channels", type=int, default=None,
                    help="采集通道数初值（默认取所选硬件, bothlent 为 6）")
    ap.add_argument("--rate", type=int, default=16000, help="采样率初值（默认 16000）")
    ap.add_argument("--blocksize", type=int, default=256,
                    help="每块帧数初值（默认 256，@16k=16ms，低延迟）")
    ap.add_argument("--window", type=float, default=10.0,
                    help="显示窗口秒数初值（默认 10; 录制填充期波形自左向右生长）")
    ap.add_argument("--algorithm", type=str, default="nbf",
                    help="算法初值（默认 nbf; 可选见界面下拉）")
    ap.add_argument("--gain-db", dest="gain_db", type=float, default=20.0,
                    help="数字前置增益 dB 初值（默认 20; 原始信号先放大再送算法/显示/gain.wav; 仅录音开始前设置）")
    ap.add_argument("--capture-dir", type=str, default=None,
                    help="录音根目录（默认 captures/cap_<时间戳>/，内含 raw.wav + proc.wav）")
    ap.add_argument("--no-record", action="store_true", help="只显示波形，不录音")
    ap.add_argument("--list", action="store_true", help="列出音频设备后退出")
    return ap


def main():
    # Windows GBK 控制台：设备名含 ® 等非 GBK 字符时避免 UnicodeEncodeError
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass
    args = build_argparser().parse_args()
    if args.list:
        print(sd.query_devices())
        print("\n默认输入设备:", sd.default.device[0])
        return 0

    # 运行日志: 接管 stdout; 日志文件在录音开始时挂载到 cap_* 目录/run.log
    log_file = applog.init_logging()
    print("=" * 68)
    print("[RTScope] 启动  (日志: %s)"
          % (log_file or "随录音保存到 cap_* 目录/run.log"))
    print("[RTScope] Python %s | %s" % (sys.version.split()[0], sys.executable))

    # 会话控制器: 只做只读枚举, 不打开音频流 (由界面「开始」触发)
    controller = SessionController(hardware=args.hardware,
                                   record=not args.no_record,
                                   capture_dir=args.capture_dir)
    hw = controller.hardware
    print("[RTScope] 硬件档案: %s | %d 麦 间距 %.3fm | 采集 %dch | conf 前缀 %s"
          % (hw.label, hw.num_mics, hw.spacing, hw.channels, hw.conf_prefix))
    print("[RTScope] 可选算法: %s (默认 %s)"
          % (", ".join(controller.algorithm_names()) or "无",
             controller.default_algorithm() or "无"))

    initial = {
        "device": args.device,
        "channels": args.channels or controller.hardware.channels,
        "rate": args.rate,
        "blocksize": args.blocksize,
        "window": args.window,
        "algorithm": args.algorithm,
        "gain_db": args.gain_db,
    }
    print("[RTScope] 界面初值: %s" % initial)
    print("[RTScope] 录音: %s | 录音根目录: %s"
          % ("开" if controller.record else "关(--no-record)",
             controller.capture_dir or "captures/cap_<时间戳>/"))
    try:
        print("[RTScope] 默认输入设备 index=%s" % (controller.default_device(),))
    except Exception as e:
        print("[RTScope] 默认输入设备枚举失败: %s" % e)

    from PyQt5 import QtWidgets
    from scope_view import ScopeWindow
    app = QtWidgets.QApplication(sys.argv)
    win = ScopeWindow(controller, window_sec=args.window, initial=initial)
    win.show()
    print("[RTScope] 在界面选声卡/参数/算法后点「● 录音」; 关闭窗口退出")

    rc = 0
    try:
        rc = app.exec_()
    except KeyboardInterrupt:
        rc = 0
    finally:
        controller.stop()   # 幂等; 确保退出前有序收尾, 规避 0xc0000142
        print("[RTScope] 退出 (rc=%d)" % rc)
        applog.shutdown_logging()
    return rc


if __name__ == "__main__":
    sys.exit(main())
