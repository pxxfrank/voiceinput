# 架构说明

## 1. 技术栈与重构决策

本项目在**已有 Python 实现**上增量重构，而不是用 C#/WPF 推倒重来。

原因：

1. 原项目已具备可运行的麦克风采集、SenseVoice 离线识别、剪贴板上屏、托盘、设置与 PyInstaller 打包能力，属于可复用资产。
2. 开发机没有 .NET SDK（仅有运行时），全量 C# 重写风险高，且与最终用户“双击安装即用”的目标无关。
3. 最终用户不接触 Python：PyInstaller 自包含运行时 + Inno Setup 安装器，Python、native DLL、模型全部内置。

因此，交付形态是 **Python 3.14 自包含 Windows x64 应用 + Inno Setup 安装包**。
模块边界在包内独立文件中实现，ASR、复核、LLM、输入、存储均可替换。

## 2. 模块边界

```text
voiceinput/
  paths.py          安装目录 / 用户数据目录 / 便携模式
  config.py         配置默认值、迁移、校验、原子保存
  audio.py          WASAPI 共享采集、有界队列、soxr 流式重采样、拼音测试录音
  vad.py            自适应能量 VAD、端点检测
  streaming.py      sherpa-onnx 在线识别、稳定/未稳定文本、片段切分
  engines.py        SenseVoice / Paraformer / Whisper 离线复核（带超时/忙闲）
  asr_merge.py      流式与复核结果合并（数字/术语/英文词保护）
  normalizer.py     确定性文本规范化（标点、中英空格、术语大小写）
  terminology.py    用户词库与受保护术语
  llm.py            llama.cpp 子进程管理、Qwen3.5 精修、JSON 协议、看门狗
  guard.py          语义保护规则（数字、否定、不确定性、英文词、长度）
  refinement.py     片段版本、精修流水线、单 worker 调度、过期任务丢弃
  target.py         前台窗口/焦点控件捕获与恢复
  clipboard.py      剪贴板快照/恢复、序列号占用校验
  inject.py         输入事务、目标校验、Unicode 直输回退、撤销
  overlay.py        悬浮输入窗 + 精修面板（进程内 Tk）
  gui.py            八页设置窗口（独立进程）
  onboarding.py     首次使用引导（独立进程）
  tray.py           系统托盘
  storage.py        SQLite：历史 / 词库 / 会话统计 / 元数据
  app.py            双模式状态机与编排
  modelstore.py     模型定位、清单、SHA-256
  diagnostics.py    诊断报告
  download_models.py 构建期模型下载/校验（运行期不使用）
  llm_watchdog.py   主程序异常退出时回收 llama-server
```

## 3. 数据流

### 3.1 极速输入（fast）

```text
热键按下 → 捕获目标窗口/焦点
        → WASAPI 采集（有界队列）→ soxr 16 kHz
        → StreamingSession：VAD / 端点 / sherpa-onnx 在线识别
        → partial（稳定 + 未稳定）→ 悬浮窗
        → 端点：复核（可选）→ 合并 → 确定性规范化
        → InputTransaction：校验目标 → 剪贴板粘贴（或 Unicode 直输）
        → 提交成功；失败则保留文本、停止自动提交
```

- 默认不调用 LLM。
- 端点只结束当前片段，不结束会话；会话在热键松开/停止/取消时结束。
- 稳定文本单调增长；英文半词不会被标为稳定。
- 每个片段有 `commit_status`，防止重复提交。

### 3.2 智能精修（smart）

```text
持续语音 → 流式识别 → 片段缓存
        → 按需 SenseVoice 复核（超时/跳过）
        → 确定性规范化（词库、标点、术语）
        → 本地 Qwen3.5 精修（JSON + edits）
        → 语义守卫（数字/否定/不确定性/英文词/长度）
        → 精修面板：原文 / 精修 / 手动编辑 / 局部精修 / 深度整理
        → 用户确认 → 恢复原目标窗口 → 插入
```

- 精修失败或守卫拒绝：回退到确定性结果，保留原文，绝不清空。
- 用户编辑优先；异步结果带 revision，过期即丢弃。
- 深度整理只能由用户按钮显式触发，不自动覆盖忠实版本。
- 自动模式仅在超过时长阈值后转为精修，不自动改变表达风格。

## 4. 并发与资源

| 资源 | 策略 |
|---|---|
| 音频回调 | 只做有界入队，绝不阻塞 |
| 流式 ASR | 单线程解码，模型常驻 |
| 复核 ASR | 单 worker、忙则跳过、超时回退 |
| LLM | 单 worker 调度器 + llama-server 单实例；任务队列上限 8；过期任务丢弃 |
| UI | 主线程 Tk；所有后台事件经 `queue.Queue` 回到主线程 |
| 内存 | 片段音频上限 20 段；已提交片段立即释放音频；LLM 空闲可卸载 |
| 进程 | llama-server 仅监听 127.0.0.1；Job Object + 看门狗双重回收 |

## 5. 输入安全

- 会话开始时捕获 `hwnd + pid + exe + title + focus_hwnd`。
- 提交前检查窗口仍存在、前台窗口/焦点仍匹配。
- 目标变化：**不抢焦点、不向新窗口插入**；保留文本，提供“复制 / 插入到原窗口 / 放弃”。
- 剪贴板：先快照；含无法安全恢复的格式时改用 Unicode 直输，绝不覆盖原剪贴板。
- 粘贴后仅当剪贴板序列号仍属于本次操作时才恢复。
- 撤销是用户显式动作，有 60 秒窗口；不对 partial 做退格模拟。

## 6. 数据与隐私

- 安装目录只读；配置/数据库/日志/缓存位于 `%LOCALAPPDATA%\LocalVoiceInput`。
- 便携模式：程序目录下 `data\`。
- 默认不保存音频；历史可关闭/清空；日志不含原始录音。
- 运行期无任何外部网络请求；LLM HTTP 仅 127.0.0.1。

## 7. 打包

```text
Inno Setup (per-user, 无需管理员)
  %LOCALAPPDATA%\Programs\LocalVoiceInput\
    LocalVoiceInput.exe
    _internal\            PyInstaller 自包含 Python/依赖
    models\               流式 ASR / 复核 ASR / LLM / llama.cpp / manifest
    licenses\
```

用户数据在卸载时保留；安装目录整体删除。
