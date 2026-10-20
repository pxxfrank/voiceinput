# Development Progress

> 唯一持续开发检查点。Last updated: 2026-10-20 11:20 (Asia/Shanghai)

## 1. 现有项目审查（Phase 0，完成）

原项目：Python 3.14 + tkinter + sherpa-onnx 1.13.8 + sounddevice + pystray + keyboard，
已有 SenseVoice 离线转写、热键、悬浮字幕、托盘、设置、PyInstaller onedir。

**决策：保留 Python，增量重构；不重写 C#/WPF。**

1. 指令要求优先增量重构，不得无理由推倒重来；原项目音频/上屏/托盘能力可复用。
2. 开发机无 .NET SDK（仅运行时），全量重写风险高且与最终交付无关。
3. 最终用户不接触 Python：PyInstaller 自包含 + Inno Setup 安装器。
4. 模块边界用独立模块实现，ASR/LLM/输入/存储可替换。

详细见 `docs/architecture.md`。

## 2. 阶段状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | 审查、决策、进度文件 | ✅ |
| P1 | 基础层：paths/config/storage/normalizer/terminology | ✅ |
| P2 | 流式 ASR + VAD + 端点 + 合并 + 单测 | ✅ |
| P3 | 复核 ASR 集成（超时/忙闲/冲突） | ✅ |
| P4 | 本地 LLM + 结构化输出 + 语义保护 + 单测/集成 | ✅ |
| P5 | 安全输入：目标跟踪/剪贴板保护/事务 | ✅ |
| P6 | 双模式编排 + 悬浮窗 + 精修面板 + 设置 + 引导 + 托盘 | ✅ |
| P7 | 集成/UI/E2E/性能 | ✅（部分性能未达标，见报告） |
| P8 | 打包 + 安装器 + 安装/卸载验证 | ✅ |

## 3. 实际构建与测试命令

```powershell
# 开发运行
.venv\Scripts\python.exe -m voiceinput
.venv\Scripts\python.exe -m voiceinput --settings
.venv\Scripts\python.exe -m voiceinput --diagnose
.venv\Scripts\python.exe -m voiceinput --selftest --llm-test

# 单元 / UI / 集成
.venv\Scripts\python.exe -m pytest tests -q
$env:VOICEINPUT_UI_TESTS="1"; .venv\Scripts\python.exe -m pytest tests/test_ui_smoke.py -q
$env:VOICEINPUT_RUN_INTEGRATION="1"; .venv\Scripts\python.exe -m pytest tests/test_integration_real.py -q

# 性能
.venv\Scripts\python.exe scripts\perf_harness.py

# 一键构建
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1
```

## 4. 已验证结果与证据

| 项 | 结果 | 证据 |
|---|---|---|
| 单元测试 | 69 passed | 终端输出；`docs/test-report.md` |
| UI 冒烟（Tk） | 3 passed | `tests/test_ui_smoke.py` |
| 真实模型集成 | 2 passed / 24.3 s | `tests/test_integration_real.py` |
| 流式 ASR | RTF P50 0.15；首字 P50 968 ms | `docs/perf-results.json` |
| 复核 ASR | P50 321 ms；超时回退 | 性能报告 |
| LLM | 首 token 264 ms；精修 P50 2660 ms | 性能报告 |
| 极速输入 E2E | 真实 WAV → 真实 Tk 文本框，剪贴板恢复 | 测试报告 |
| 智能精修 E2E | 真实 WAV → 复核 → LLM → 面板 | 测试报告 |
| 打包 exe | `--diagnose` / `--selftest` / 真实 WAV 上屏 | 测试报告 |
| 安装包 | 静默安装/卸载退出 0；开始菜单快捷方式；数据保留 | `docs/deployment-report.md` |
| Portable ZIP | testzip 通过；diagnose 0；portable=True | 部署报告 |
| 焦点变化 | `target_changed`，不向新窗口插入 | 测试报告 |
| 非文本剪贴板 | 图片保留，改用 Unicode 直输 | 测试报告 |
| LLM 缺失 | 回退确定性文本，文本不丢失 | 测试报告 |
| 断网审计 | 外部网络尝试：无 | `tests/offline_run.py` |
| 模型集校验 | marker/manifest 匹配、旧版兼容、不匹配拒绝 | `tests/test_model_set.py` |
| 签名更新 | Ed25519 清单校验、篡改拒绝、版本比较 | `tests/test_update.py` |
| 输入兼容矩阵 | 终端/控制台/普通编辑框策略 | `tests/test_compat.py` |
| 精修差异审阅 | 字符级 diff、逐条接受/拒绝 | `tests/test_diff.py` |

## 5. 最终产物

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| `release/LocalVoiceInput-Setup-x64.exe` | 1546.5 MB | `54c5b0e2e385f2dcdb66683d165a9a243c4084a15f636eba8eac266801d24165` |
| `release/LocalVoiceInput-Portable-x64.zip` | 1768.2 MB | `209ca7c6c0dc7e70c70c0f2f78ae8cf1fb91ba5b29a42026d3596f68dbe533e0` |
| `release/LocalVoiceInput-Update-x64.exe` | 42.8 MB | `da2022f644d2f964d3c46f1dfb69c1a4f4318b8e920cf922033d51f567a7b266` |
| `release/SHA256SUMS.txt` | — | 上述 + ReleaseNotes |

## 6. 未解决 / 未验证

- 真实物理麦克风：本机仅有 RDP 音频（静音）与虚拟阵列（全零），**未验证**。
- Windows 11 / 目标 ThinkPad X1 Carbon Gen 12 / Ultra 7 155H / Arc / NPU：**未测试**。
- 干净虚拟机（无 Python/.NET/VC++/Ollama）：安装包自包含，但未在全新 VM 执行。
- 连续 3 小时长稳：**未执行**。
- 首字延迟 P50 968 ms（目标 800 ms）→ 未达标。
- LLM 精修 P50 2660 ms（目标 1–2 s）→ 未完全达标。
- 智能模式内存约 2.5 GB（基础模式 559 MB 达标）→ 未达 1.5 GB。
- 安装包未代码签名；SmartScreen 可能提示。
- 非管理员无法向管理员窗口注入（Windows UIPI）。
- 共享桌面中其他 topmost 应用可能遮挡面板。

## 7. 下一步（若继续）

1. 在目标 ThinkPad / Windows 11 上复跑 `scripts/perf_harness.py` 与真实麦克风 E2E。
2. 若必须满足 800 ms 首字：评估 160 ms 模型 + 更强 VAD（需接受 RTF/精度权衡），或用 0.8B/2B 双模型分级。
3. 若必须满足 1.5 GB：将默认 LLM 改为 0.8B 或默认不预加载，并把 2B 作为可选下载/切换。
4. 增加 3 小时循环长稳脚本与内存曲线。
5. 购买代码签名证书并签名 Setup.exe。
