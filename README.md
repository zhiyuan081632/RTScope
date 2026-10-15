# RTScope

实时麦克风阵列采集 + Adobe Audition 风格波形显示工具。启动后点「● 录音」才采集；每次录音在 `captures/cap_<时间戳>/` 保存原始多通道、放大后多通道、算法单通道波形与运行日志。

## 关键点

- **采集**：默认 6ch 声卡（关键字 `Source/Sink` 自动识别，WASAPI 优先），16kHz / block 256；通道、采样率、块长、窗口、算法、增益均在顶栏选择。
- **前置增益**：顶栏「增益」dB 编辑框（-20..60 dB，默认 **20**）；**仅录音开始前可设置**（录制中锁定）。**仅麦克风通道**（前 `num_mics` 路）按增益放大、**参考信号通道不变**，放大后送算法/直通显示；`raw.wav` 保留未加增益的采集原貌，放大后另存 `gain.wav`（mic 通道 `== raw × 10^(dB/20)`、ref 通道原样，FLOAT 无损）；直通显示的是放大后的 mic。
- **算法**：`nbf`（webrtc，默认）+ SoundConnect（delaysum / diffuse / multi304 / mvdr）；录音前单选一种。
- **多路录音**：`raw.wav`（全通道原始）+ `gain.wav`（mic 通道放大、ref 不变）+ `proc.wav`（算法单通道）+ `run.log`（本次运行日志，含硬件/算法/参数/增益/统计）。
- **界面**：顶部单行设置栏；中央黑底浅绿波形 + 时间标尺 + 右侧 RMS 标尺；底部走带条 ● 录音 / ▶ 播放 / ■ 停止 + 保存路径超链接。
- **三态视图**：录制=波形自左向右生长（默认 10s 窗）→ 填满后左滚；编辑=停止后整段铺满、点击定位、▶ 回放；可随时「算法 ↔ 直通」热切换显示/回放源（算法始终在跑）。
- **离线对比**：`offline_eval.py <cap_dir>` 用与实时相同的处理器复现「mic1 直通 + nbf + 所有 SC 算法」，输出到 `cap_*/offline/` 并生成 `summary.txt`（时长/RMS/峰值/削波）；**输入优先取 `gain.wav`**（即实时真正送算法、已含增益的信号），无则回退 `raw.wav`，故离线结果与实时 `proc.wav` 一致；`--gain-db`（默认 0，仅 mic 通道）为额外增益，仅在回退读 `raw.wav` 或想再加时用。
  - `mic1` = 取源音频（`gain.wav` 优先）第一路 mic 原样拷贝（不经 DLL）；`dis_bf` = 走完整 SC 链路但禁用波束（bf_algorithm=0），后续可在该链路加 agc/ns 等对比；二者相差数 dB 属 SC 链路增益/量化，非 bug。
- **硬件档案**：`hardware.py` 登记麦阵（默认 bothlent 线性 4 麦、间距 3.5cm），`--hardware` 切换。

## 运行

```bash
conda activate py39
cd BF/RTScope
python main.py                              # 进控制面板 (不自动录音)
python main.py --list                       # 列出音频设备
python offline_eval.py captures/cap_xxx     # 离线批量复现各算法 -> cap_xxx/offline/
```

`main.py` 常用参数：`--hardware` / `--device` / `--channels` / `--rate` / `--blocksize` / `--window`(默认10) / `--algorithm` / `--gain-db`(默认20) / `--capture-dir` / `--no-record` / `--list`。

## 目录结构

```
main.py / scope_view.py     入口 + PyQt5 主窗口 (录制/编辑/回放三态)
session.py / audio_engine.py 会话控制 + 采集引擎/双录音线程
algorithms.py               算法目录 (nbf + SoundConnect; 界面隐藏 bypass)
sc_processors.py / webrtc_processors.py / processors.py  算法处理器封装
hardware.py                 硬件档案 (麦阵几何 / conf 前缀)
playback.py / applog.py     回放播放器 / 运行日志
offline_eval.py             离线批量复现各算法 -> cap_*/offline/
conf/ lib/ sc_py/ webrtc_bf/  SC 配置 / 原生 DLL / SC 绑定 / webrtc DLL 源码
captures/                   录音输出 (cap_<时间戳>/: raw.wav + gain.wav + proc.wav + run.log)
```

## 说明

- 录制中顶栏设置锁定（窗口除外），停止后进编辑态可回放/点选定位。
- 退出时有序收尾（停流 → join 录音线程 → 释放原生句柄），规避 Windows 退出崩溃。
