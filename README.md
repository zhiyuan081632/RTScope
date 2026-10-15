# RTScope

实时麦克风阵列采集 + Adobe Audition 风格波形显示工具。启动只进控制面板，由界面点「● 录音」才开始采集；每次录音在 `captures/cap_<时间戳>/` 下同时保存原始多通道与算法单通道波形，并自带一份完整运行日志。

## 功能

- **实时采集**：默认 6 通道声卡（关键字 `Source/Sink` 自动识别，WASAPI 优先），16kHz / block 256 低延迟；通道、采样率、块长、显示窗口均可在顶栏选择。
- **波束成形算法**：`nbf`（webrtc NonlinearBeamformer，默认）+ SoundConnect 系列（delaysum / diffuse / multi304 / mvdr）；录音前单选一种，保证 `proc.wav` 只对应一种算法。
- **双路录音**：`captures/cap_<时间戳>/raw.wav`（全通道原始）+ `proc.wav`（单通道算法输出）+ `run.log`（本次运行日志）。
- **Audition 风格界面**：
  - 顶部单行设置栏：声卡 / 通道 / 采样率 / 块长 / 窗口 / 算法 / 「显示：」+ 源切换按钮（算法 ↔ 直通）。
  - 中央黑底浅绿 min/max 包络波形 + 时间标尺 + 右侧竖直 RMS 标尺（dB 刻度、峰值保持、Audition 式横向参考线）。
  - 底部走带条：● 录音 / ▶ 播放 / ■ 停止（居中）；末行状态栏 + 保存路径超链接（点击直接打开 cap 目录）。
- **录制视图（类 Audition 填充式）**：波形自左向右生长（默认 10s 窗，标尺绝对时间）；填满后切换为左滚、新数据自右缘进入（标尺相对时间）。
- **编辑视图**：停止录音后整段自适应铺满、绝对标尺、暖黄播放头；鼠标点击定位（seek），▶ 从播放头回放。
- **显示源热切换**：算法波束 ↔ 直通 mic0；录制中算法处理器始终运行（保证收敛），切换只改显示/回放源。
- **运行日志**：启动即接管控制台输出；录音开始时挂载到当次 `cap_*` 目录的 `run.log`，并补写启动以来的历史行（硬件档案 / 算法 / 设备参数 / `[run]` / `[stop]` 统计 / 保存路径）。停止时若 raw 与 proc 帧数相对偏差 >2% 会在日志告警。
- **硬件档案**：`hardware.py` 集中登记麦阵（默认 bothlent 线性 4 麦、间距 3.5cm、Mic0→Mic3 左→右），`--hardware` 切换，驱动通道数、麦阵几何与 conf 前缀。

## 运行（conda py39）

```bash
conda activate py39
cd BF/RTScope
python main.py                 # 进控制面板 (不自动录音)
python main.py --list          # 列出音频设备后退出
python main.py --algorithm nbf --window 10
python main.py --no-record     # 只显示不录音
```

常用参数：`--hardware`（硬件档案）、`--device`（输入设备索引）、`--channels`、`--rate`、`--blocksize`、`--window`（显示窗口秒数，默认 10）、`--algorithm`、`--capture-dir`（录音根目录）、`--no-record`、`--list`。

## 目录结构

```
main.py              入口 (参数解析 + 启动日志 + Qt 事件循环)
session.py           会话控制 (设备枚举 / start / stop 有序收尾)
audio_engine.py      PortAudio 回调引擎 + raw/proc 双录音线程
algorithms.py        算法目录 (nbf 置顶; 界面隐藏 bypass)
processors.py        流式块处理器基类 (恒等/算法插件接口)
sc_processors.py     SoundConnect 算法封装 (conf 驱动)
webrtc_processors.py webrtc nbf DLL 封装
hardware.py          硬件档案 (麦阵几何 / conf 前缀)
scope_view.py        PyQt5 主窗口 (录制/编辑/回放三态)
playback.py          回放播放器 (sounddevice 输出流)
applog.py            运行日志 (Tee 控制台 + cap 目录 run.log)
conf/                SoundConnect 配置 (bothlent_line4mic_sc_*.conf)
lib/                 原生库 (SoundConnect.dll / webrtc_bf.dll)
sc_py/               SoundConnect Python 绑定 (SoundConnect.py)
webrtc_bf/           webrtc_bf DLL 源码与构建脚本 (CMake)
captures/            录音输出 (cap_<时间戳>/: raw.wav + proc.wav + run.log)
```

## 说明

- 启动不自动录音；在界面选声卡/参数/算法后点「● 录音」。
- 录制中顶栏设置锁定（显示窗口除外），停止后进入编辑态可回放/点选定位。
- 退出时有序收尾（停流 → join 录音线程 → 释放原生句柄），规避 Windows 退出崩溃。
