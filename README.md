# voiceinput · 离线语音输入法

按住一个热键说话，松开后**在本机**把语音转成文字，并直接把文字输入到当前光标处。
程序常驻后台，只在按下热键时才工作。

- **完全离线**：ASR 模型跑在本地，识别过程不产生任何网络请求，语音/文字不出本机。
- **常驻后台**：启动后只有托盘图标，无窗口、无控制台；**按住热键说话，松开自动上屏**。
- **按住说话（push-to-talk）**：按下热键开始录音，松开立即转写并输入到光标处。
- **精度高、延迟低**：默认使用阿里 **SenseVoice-Small**，中文识别准确、带标点与数字规范化；本机 CPU 上 RTF ≈ 0.2（5 秒语音约 1 秒转写）。
- **何处都能用**：通过剪贴板粘贴上屏，兼容微信、浏览器、编辑器、终端与各类输入法环境。

## 环境要求

- Windows 10/11
- 一个可用的麦克风
- [uv](https://docs.astral.sh/uv/)（用于创建环境；也可自行用 pip）
- 首次运行需联网下载模型，之后完全离线

> 无需独立显卡，纯 CPU 推理；无需安装 PyTorch。

## 安装（一次性）

```bat
setup.bat
```
它会创建 `.venv`、安装依赖并下载模型（SenseVoice，约 1 GB）。

## 运行方式

### 方式 A：双击 `voiceinput.vbs` —— 静默常驻（推荐）

双击后**没有任何窗口**，只在右下角托盘出现一个麦克风图标，程序即常驻后台：

- 把光标放到任意输入框，**按住 `F9`** 说话，**松开** → 文字出现在光标处。
- 托盘图标颜色：灰=待机、红=录音、黄=转写。
- **退出**：右键托盘图标 →「退出」。

### 方式 B：`run.bat` —— 带控制台（调试用）

保留一个控制台窗口，方便看日志，用法同上。

### 方式 C：打包成独立 exe

```bat
build_exe.bat
```
产物在 `dist\voiceinput\voiceinput.exe`，双击即静默后台运行（无需 Python）。
把 `config.yaml` 放到 exe 同目录，并让其中的 `model_dir` 指向模型目录（可写绝对路径，
避免复制 1 GB 模型）。本仓库已预置 `dist\voiceinput\` 并配好 `config.yaml`，可直接双击运行。

## 开机自启

任选其一：

- 右键托盘图标 → 勾选「**开机自启**」（再点一次取消）。
- 命令行：`.venv\Scripts\python.exe -m voiceinput.autostart enable`（`disable` / `status`）。

原理是在「启动」文件夹写入一个静默启动脚本，删除该脚本即关闭自启。

## 使用

1. 把光标放到任意输入框（微信 / 浏览器 / IDE / 终端…）。
2. **按住 `F9`** 说话。
3. **松开 `F9`**，约 1 秒后文字自动出现在光标处。

- **录音中按 `Esc`**：丢弃本次录音（不上屏）。
- **按 `Ctrl+Alt+Z`**：撤销上一次上屏（删掉刚粘贴的内容，60 秒内有效）。
- **连续听写**：按一下 `F10` 开始持续录音（字幕会持续显示），再按一下停止并把整段文字上屏 —— 适合较长、边看字幕边说的场景。
- **无人说话自动停**：连续 30 秒没有语音输入会**自动停止录音并转写**（可在 `audio.silence_timeout` 调整，`0` 关闭）。
- 录音时屏幕底部中央出现**悬浮字幕窗**：状态圆点（红=录音、黄=转写）+ **两行字幕**（第一行=已经说过的话，第二行=正在说的话，随说话实时递进）。
- 每段结果都会记入历史（`history.jsonl`），在设置界面「历史」页可查看 / 复制。
- 想「按一下开始、再按一下结束」：在 `config.yaml` 里把 `hotkey.mode` 设为 `toggle`。
- 想纠正常错的词：在 `config.yaml` 的 `replacements` 里加「错词: 正词」。
- 提示音：开始（高音）、结束（低音）、出错 / 取消（长低音）。
- 程序同一时间只运行一个实例；重复启动会自动退出。

## 悬浮字幕窗

录音时，屏幕底部中央会出现一个悬浮小窗，显示**状态圆点 + 两行字幕**：

- 第一行（灰）＝ **已经说过的话**；第二行（白、更大）＝ **正在说的话**。
- 说话时第二行实时递进；说完一句（出现句末标点）后自动上移为第一行。
- 录制结束 / 空闲时自动隐藏；主程序退出后窗口自动关闭。

**右键托盘图标 →「字幕」** 可在几种显示方式间切换；**「字幕大小」** 可调浮层字号：

| 选项 | 效果 |
| --- | --- |
| 悬浮字幕（2 行） | 屏幕底部浮层：圆点 + 两行字幕（默认） |
| 字幕窗口（全部字幕） | **可自由缩放** 的窗口，实时刷新显示本次会话**全部字幕**：历史用**灰色**、正在说用**橙色**区分 |
| 仅录音指示点 | 只显示圆点，不显示字幕 |
| 关闭 | 不显示任何字幕窗 |

- 「字幕窗口」是个普通可缩放窗口（大小/位置会被记住，`transcript.geom`），适合长听写时回看整段文字。
- 「悬浮字幕」用鼠标拖动即可移动，位置记在 `hud.pos`。
- 字号也可在 `config.yaml` 的 `caption.font_size` 里调。
- 字幕由**本机现有模型**边录边解码生成（RTF ≈ 0.05，几乎不占额外资源），与最终上屏结果同源、完全一致。
  可调 `caption.interval`（越小越跟手）与 `caption.window`（参与字幕的音频上限秒数）。

## 设置界面（GUI）

本着「大多数人不该被配置项淹没」，界面**只保留最常用的几项**，其余一律使用内置最佳默认值、不在界面呈现。

- **右键托盘图标 →「设置…」**（默认双击托盘图标也会打开）。
- 或直接运行：`voiceinput.exe --settings` / `.venv\Scripts\python.exe -m voiceinput.gui`。

| 选项卡 | 作用 |
| --- | --- |
| 常规 | 按住说话热键、连续听写热键（点「捕获按键」后直接按一下）、麦克风（可「自动检测」）、开机自启 |
| 麦克风测试 | 录一段 → 立即识别 → 试听回放，验证麦克风与识别效果 |
| 历史 | 查看历史转录，一键复制 / 清空 |
| 关于 | 版本、路径、依赖版本；检查更新；一键复制信息；下载并切换模型 |

改完点「**保存并重启**」，程序会自动重启并应用；点「保存」则只写入 `config.yaml`，下次启动生效。

> 引擎、输出、日志等进阶参数已用最佳默认值，一般无需改动；确有需要的高级用户
> 可直接编辑 `config.yaml`（见下）。保存时会以规整格式重写该文件，手写注释会丢失。

## 配置文件（参考）

也可以直接编辑 `config.yaml`。常用项：

```yaml
engine: sensevoice      # sensevoice | paraformer | whisper
hotkey:
  key: f9               # 可换成 f10 / scroll lock / pause / right ctrl / right shift 等
  mode: hold            # hold 按住说话 | toggle 按一下开始/再按结束
  undo: ctrl+alt+z      # 撤销上屏；留空禁用
  continuous: f10       # 连续听写键（按一下开始 / 再按停止）；留空禁用
output:
  method: paste         # paste（推荐）| type（仅 ASCII）
  append_space: true    # 上屏后追加空格
audio:
  device: null          # 指定麦克风序号/名称；null 用系统默认
  min_duration: 0.3     # 短于此秒数的录音忽略
  max_duration: 300.0   # 最长录音秒数（安全上限）
  silence_timeout: 30.0 # 连续无语音多少秒就自动停止（0 = 不自动停）
feedback:
  beep: true
  tray: true
caption:
  mode: show            # show 两行字幕 | dot 仅指示点 | off 关闭
  font_size: 15         # 字幕字号（托盘「字幕大小」也可调）
history:
  enabled: true         # 记录转录历史到 history.jsonl
  max: 500
replacements: {}        # 转写后替换，如 { "未来": "蔚来" }
logging:
  level: INFO
  file: voiceinput.log  # 后台运行时的日志文件
```

## 引擎 / 模型选择

| engine | 模型 | 大小 | 特点 |
| --- | --- | --- | --- |
| `sensevoice`（默认） | SenseVoice-Small | ~1.0 GB | 中/英/日/韩/粤，中文精度高、速度快、自带标点 |
| `paraformer` | Paraformer-zh | ~230 MB | 中文高精度，体积更小 |
| `whisper` | faster-whisper | 视模型而定 | 多语种；需 `uv pip install faster-whisper` |

切换后按需下载对应模型：

```bat
.venv\Scripts\python.exe -m voiceinput.download_models paraformer
```

## 自检

用一段音频验证模型是否可用（不依赖麦克风）：

```bat
.venv\Scripts\python.exe -m voiceinput.selftest
.venv\Scripts\python.exe -m voiceinput.selftest 我的录音.wav
```

## 常见问题

- **按热键没反应**：确认程序在交互式桌面会话中运行；若目标窗口以管理员权限运行，本程序也需以管理员身份运行才能收到/发送按键。
- **双击 vbs / exe 没反应**：先看 `voiceinput.log`；确认 `config.yaml` 里 `model_dir` 指向正确的模型目录。
- **中文没有粘贴进去**：确认 `output.method: paste`（`type` 只适用于英文/ASCII）。
- **录音时长偏短或无声**：在 `config.yaml` 里把 `audio.device` 设为设备序号；远程/虚拟音频设备的默认采样率可能不是 16k，程序会自动重采样。
- **检查有哪些麦克风**：`python -c "import sounddevice as sd; print(sd.query_devices())"`。

## 目录结构

```
main.py             顶层入口（打包/直接运行）
voiceinput/          源码包
  __main__.py        命令行入口
  config.py          配置加载（含打包后的路径处理）
  app.py             编排：热键 → 录音 → 转写 → 上屏（含实时字幕）
  gui.py             图形化设置界面（tkinter，无第三方依赖）
  hud.py             悬浮字幕窗（独立进程 + 状态文件）
  recorder.py        麦克风录音、静音裁剪、录音中快照
  hotkey.py          全局按住说话热键（hold / toggle）
  inject.py          光标处插入文本
  engines.py         ASR 引擎（sherpa-onnx / faster-whisper）
  devices.py         麦克风枚举与信号自动检测
  history.py         转录历史（history.jsonl）
  tray.py            系统托盘（状态、字幕模式、开机自启等）
  autostart.py       开机自启管理
  download_models.py 模型下载
  make_icon.py       生成图标
  selftest.py        自检
config.yaml          用户配置
voiceinput.vbs       静默启动（双击即后台运行）
setup.bat            安装
run.bat              带控制台运行（调试）
build_exe.bat        打包成 exe
dist/                打包产物（git 忽略）
models/              本地模型（git 忽略）
```

## 隐私说明

- 除首次下载模型外，程序不会访问网络。
- 音频仅在内存中处理，不落盘（除非你自行保存）。
- 上屏使用剪贴板中转，粘贴完成后会还原你原来的剪贴板内容。
