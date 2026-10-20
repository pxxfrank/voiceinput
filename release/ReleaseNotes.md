# Release Notes — LocalVoiceInput 1.1.0

发布日期：2026-10-20

## 下载

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| LocalVoiceInput-Setup-x64.exe | 1546.5 MB | `54c5b0e2e385f2dcdb66683d165a9a243c4084a15f636eba8eac266801d24165` |
| LocalVoiceInput-Portable-x64.zip | 1768.2 MB | `209ca7c6c0dc7e70c70c0f2f78ae8cf1fb91ba5b29a42026d3596f68dbe533e0` |
| LocalVoiceInput-Update-x64.exe（增量，不含模型） | 42.8 MB | `1a15ac2d8d67632a577cb92720a398f94ab81d0b2f4e6039ae51bf21da47629f` |
| update.json（签名更新清单） | 1.1 KB | `dd0415da164b63001d3f2d14b11d383c30dc861b69d9f6186a560c4f6b7e17f2` |

## 本轮增强

- 模型集版本校验（`model-set.txt` + manifest），应用与增量安装器双重校验。
- Ed25519 签名更新清单；托盘「检查更新…」下载、校验、退出后安装。
- 无模型增量更新包（约 43 MB），复用已安装模型。
- 输入兼容矩阵：Windows Terminal / 经典控制台 / 普通编辑框选择不同粘贴方式；管理员权限提前提示。
- 精修「差异对照」：原文/精修逐字高亮，支持逐条接受/拒绝 LLM 修改。

## 亮点

- 双模式：极速输入 / 智能精修 / 自动。
- 真流式识别：sherpa-onnx 在线 Zipformer（中英混排 + 标点，INT8，CPU），稳定/未稳定文本分色显示。
- 识别复核：SenseVoice-Small INT8，按需调用、超时/忙时回退，不假设复核一定更正确。
- 本地 LLM：Qwen3.5-2B Q4_K_M + llama.cpp；结构化 JSON、语义守卫、版本校验、失败回退、空闲卸载。
- 安全上屏：目标窗口/焦点校验；焦点变化不误插入；剪贴板快照/序列号保护；非文本剪贴板自动改用 Unicode 直输。
- 完整交付：自包含 Setup.exe（无需任何运行时）、Portable ZIP、模型清单/SHA-256、许可证、测试/性能/部署报告。
- 数据分离：安装目录只读；配置/历史/日志在 `%LOCALAPPDATA%\LocalVoiceInput`；卸载保留用户数据。

## 模型

| 角色 | 模型 | 设备 |
|---|---|---|
| 流式 ASR | X-ASR 480ms Streaming Zipformer zh-en punct INT8 | CPU |
| 复核 ASR | SenseVoice-Small INT8 | CPU |
| LLM | Qwen3.5-2B Q4_K_M (GGUF) | CPU (llama.cpp) |

## 验证摘要

- 单元测试 69 通过；UI 冒烟 3 通过；真实模型集成 2 通过。
- 安装/卸载、Portable、真实 WAV 上屏、剪贴板恢复、焦点变化保护、非文本剪贴板回退、模型缺失回退、断网审计均实际执行。
- 未验证：真实物理麦克风、Windows 11、目标 ThinkPad 硬件、3 小时长稳、全新干净虚拟机。

## 性能（本机虚拟机实测，非目标硬件）

| 指标 | 目标 | 实测 |
|---|---:|---:|
| 首字延迟 P50 | ≤800 ms | 968 ms（未达） |
| partial 更新 P50 | 100–300 ms | 242 ms |
| ASR RTF P50 | ≤0.3 | 0.15 |
| 复核延迟 P50 | — | 321 ms |
| LLM 首 token | — | 264 ms |
| LLM 精修 P50 | 1–2 s | 2660 ms（未达） |
| 基础模式内存 | ≤1.5 GB | 559 MB |
| 智能模式总内存 | ≤1.5 GB | 约 2.5 GB（未达） |
| 进程 CPU（整机折算） | ≤25% | 约 3.5–4.3%（36 核 VM） |

## 已知问题

1. 首字延迟未达 800 ms；480ms 模型固有延迟 + VAD/节流导致。
2. LLM 精修 P50 约 2.66 s，略高于 1–2 s。
3. 智能模式常驻 LLM 内存约 2.5 GB；基础模式 559 MB。
4. 非管理员程序无法向管理员窗口注入文字（Windows UIPI）。
5. 精修模型能力有限，语义守卫不能覆盖所有语义风险；无法确定时需用户确认。
6. 共享桌面中其他 topmost 应用可能遮挡面板；悬浮窗本身置顶。
7. 安装包未签名，可能出现 SmartScreen 提示。

## 安装

1. 双击 `LocalVoiceInput-Setup-x64.exe`，按向导完成（无需管理员）。
2. 启动，按引导选择麦克风/快捷键/模式。
3. 光标放入输入框，按住 `F9` 说话，松开。

完全离线；不需要 Python、.NET、VC++、CUDA、ONNX Runtime、llama.cpp、Ollama、FFmpeg、Git 或模型下载。
