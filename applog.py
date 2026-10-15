#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
applog.py — RTScope 运行日志 (镜像 AVSE/RAVEN/DEMO 的 _TeeStdout 机制)

作用: 所有 print 同时写「控制台 + utf-8 日志文件」, 每行自动加时间戳,
      用于跟踪: 用了什么硬件 / 哪种算法 / 设备与参数 / 运行状态 / 保存路径 /
      回放与热切换事件 / 异常。控制台为 GBK 等窄编码时, emoji/特殊符号降级替换,
      日志文件始终 utf-8 保留原字符。

用法 (main.py 启动引导):
    import applog
    applog.init_logging()          # 接管 sys.stdout (仅控制台 + 缓存历史行)
    applog.log("...")              # 等价 print, 会被 Tee 到日志
    ...
    applog.attach_file(<cap_dir>/run.log)   # 录音开始时挂载日志文件到 cap_* 目录
    ...
    applog.shutdown_logging()      # 退出前 flush/close 并恢复 sys.stdout

日志文件不单独建 logs/ 目录: 启动到挂载之间的历史行会在 attach_file 时一并
补写, 使每个 cap_* 目录自带一份从启动开始的完整运行日志 (run.log)。
"""

import os
import sys
import time
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))

_log_fp = None
_log_path = None
_orig_stdout = None
_history = deque(maxlen=20000)     # 启动以来的输出行 (挂载文件时补写)


class _TeeStdout(object):
    """Tee 输出: 每行前自动加时间戳, 同时写控制台和日志文件。"""

    def __init__(self, orig_stdout):
        self.orig = orig_stdout
        self._buf = ""

    @staticmethod
    def _ts():
        return time.strftime("%H:%M:%S") + ".%03d" % int((time.time() % 1) * 1000)

    def _emit(self, out):
        try:
            self.orig.write(out)
        except UnicodeEncodeError:
            # 控制台为 GBK 等窄编码时特殊符号无法输出, 降级替换
            # (日志文件 utf-8 仍保留原字符)
            enc = getattr(self.orig, "encoding", None) or "gbk"
            self.orig.write(out.encode(enc, errors="replace").decode(enc, errors="replace"))
        except Exception:
            pass
        _history.append(out)
        if _log_fp is not None:
            try:
                _log_fp.write(out)
            except Exception:
                pass

    def write(self, data):
        self._buf += data
        while "\n" in self._buf:
            idx = self._buf.index("\n")
            line = self._buf[:idx]
            self._buf = self._buf[idx + 1:]
            self._emit(("[%s] %s\n" % (self._ts(), line)) if line.strip() else "\n")

    def flush(self):
        if self._buf:
            self._emit(("[%s] %s" % (self._ts(), self._buf)) if self._buf.strip() else self._buf)
            self._buf = ""
        try:
            self.orig.flush()
        except Exception:
            pass
        if _log_fp is not None:
            try:
                _log_fp.flush()
            except Exception:
                pass

    # 让 logging / 第三方库探测文件描述符时不报错
    def isatty(self):
        try:
            return self.orig.isatty()
        except Exception:
            return False

    def fileno(self):
        return self.orig.fileno()


def set_log_fp(fp):
    """设置 _TeeStdout 使用的日志文件对象 (None = 仅控制台)。"""
    global _log_fp
    _log_fp = fp


def init_logging(log_path=None):
    """接管 sys.stdout (Tee 到控制台) 并开始缓存历史行; 返回当前日志路径。

    不再默认创建 logs/ 目录: 日志文件由 session.start() 在录音开始时调用
    attach_file(<cap_dir>/run.log) 挂载, 未挂载前仅控制台输出 (历史行已缓存)。
    重复调用幂等 (已接管则不重复包装 stdout)。
    """
    global _orig_stdout
    if _orig_stdout is None:
        _orig_stdout = sys.stdout
        sys.stdout = _TeeStdout(_orig_stdout)
    if log_path:
        attach_file(log_path)
    return _log_path


def attach_file(path):
    """把日志挂载到 path (utf-8, line-buffered), 并补写启动以来的历史行。

    用于把运行日志直接保存到当次录音的 cap_* 目录 (run.log)。
    重复调用会关闭旧文件并重新挂载 (每次录音一份自包含日志)。
    失败时退回仅控制台, 返回 None。
    """
    global _log_fp, _log_path
    if _log_fp is not None:
        try:
            _log_fp.flush()
            _log_fp.close()
        except Exception:
            pass
        _log_fp = None
    try:
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        fp = open(path, "w", encoding="utf-8", buffering=1)
    except Exception as e:
        sys.stderr.write("[applog] 无法打开日志文件 (%s), 仅控制台输出\n" % e)
        _log_path = None
        return None
    for line in _history:
        try:
            fp.write(line)
        except Exception:
            break
    _log_fp = fp
    _log_path = path
    return path


def shutdown_logging():
    """flush/close 日志文件并恢复 sys.stdout (幂等)。"""
    global _log_fp, _log_path, _orig_stdout
    try:
        sys.stdout.flush()
    except Exception:
        pass
    if _orig_stdout is not None:
        sys.stdout = _orig_stdout
        _orig_stdout = None
    if _log_fp is not None:
        try:
            _log_fp.flush()
            _log_fp.close()
        except Exception:
            pass
    _log_fp = None
    _log_path = None


def log(msg=""):
    """便捷日志: 等价 print, 会被 _TeeStdout 捕获写入文件。"""
    print(msg)


def log_path():
    return _log_path
