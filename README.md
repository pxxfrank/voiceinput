# 本地语音输入 LocalVoiceInput

Windows 11 x64 本地离线语音输入法：流式识别、识别复核、本地 LLM 精修、全局安全上屏。
**不联网、不上传录音或文字**；安装包内置全部运行时与模型。

## 直接使用

1. 双击 `release\LocalVoiceInput-Setup-x64.exe`，按向导安装（per-user，无需管理员）。
2. 启动后按引导选择麦克风、快捷键、默认模式。
3. 把光标放进任意输入框，**按住 `F9`** 说话，松开。

不需要安装 Python、.NET、VC++、CUDA、ONNX Runtime、llama.cpp、Ollama、FFmpeg、Git 或任何模型。

便携版：解压 `LocalVoiceInput-Portable-x64.zip`，运行 `LocalVoiceInput.exe`；数据保存在程序目录 `data\`。

## 功能

- **双模式**：极速输入（边说边出字、片段结束即上屏，不调用 LLM）；智能精修（长口述，面板确认后插入）。
- **流式 ASR**：sherpa-onnx 在线 Zipformer（中英混排 + 标点，INT8，CPU）。
- **识别复核**：SenseVoice-Small INT8，按需调用、超时回退，不假设复核一定更正确。
- **本地 LLM**：Qwen3.5-2B Q4_K_M + llama.cpp 子进程；结构化 JSON、语义守卫、版本校验、失败回退。
- **安全输入**：目标窗口/焦点校验；焦点变化不误插入；剪贴板快照/占用校验；非文本剪贴板自动改用 Unicode 直输；终端/控制台兼容矩阵。
- **精修审阅**：原文/精修差异高亮，逐条接受/拒绝 LLM 修改。
- **签名更新**：模型集版本校验；Ed25519 签名清单 + SHA-256 校验；无模型增量包 + 退出后安装。
- **UI**：不抢焦点的置顶悬浮窗、精修对照面板、八页设置、首次引导、托盘、深/浅色、高 DPI。
- **数据**：SQLite 历史/词库/统计；安装目录与用户数据分离；便携模式。

## 项目结构

```text
voiceinput/            应用源码（audio/asr/refine/input/storage/ui）
models/                流式 ASR、复核 ASR、Qwen3.5 GGUF、llama.cpp、manifest.json
packaging/             Inno Setup 安装脚本、版本信息、README
scripts/               build-release.ps1、perf_harness.py、make_zip.py 等
tests/                 单元测试、真实模型集成测试、E2E 辅助
docs/                  架构、模型清单、测试/性能/部署报告、使用指南
release/               Setup.exe、Portable ZIP、SHA256SUMS、ReleaseNotes
```

## 开发

```powershell
# 环境（开发机需要；最终用户不需要）
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt

# 运行
.venv\Scripts\python.exe -m voiceinput
.venv\Scripts\python.exe -m voiceinput --settings
.venv\Scripts\python.exe -m voiceinput --diagnose
.venv\Scripts\python.exe -m voiceinput --selftest --llm-test

# 测试
.venv\Scripts\python.exe -m pytest tests -q
$env:VOICEINPUT_RUN_INTEGRATION="1"; .venv\Scripts\python.exe -m pytest tests/test_integration_real.py -q

# 一键构建（测试 → PyInstaller → 模型整理 → Portable ZIP → Setup.exe → SHA256）
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1

# 后续小版本更新（不含模型，复用已安装 models，约 40 MB）
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1 -NoModels -SkipZip

# 性能
.venv\Scripts\python.exe scripts\perf_harness.py
```

模型下载/校验（构建期联网，运行期不联网）：

```powershell
.venv\Scripts\python.exe -m voiceinput.download_models --download
.venv\Scripts\python.exe -m voiceinput.download_models --verify
```

## 文档

- [架构说明](docs/architecture.md)
- [模型清单](docs/model-manifest.md)
- [用户指南](docs/user-guide.md)
- [测试报告](docs/test-report.md)
- [性能报告](docs/performance-report.md)
- [部署报告](docs/deployment-report.md)
- [更新签名与发布](docs/update-signing.md)
- [依赖许可证](docs/dependency-licenses.md)

## 验证状态（诚实说明）

- 已实际验证：安装/卸载、Portable、真实模型流式识别、复核、LLM 精修、真实文本框插入、剪贴板恢复、焦点变化保护、非文本剪贴板回退、模型缺失回退、断网审计。
- 未验证：真实物理麦克风、Windows 11、目标 ThinkPad 硬件、3 小时长稳、干净虚拟机环境。
- 部分性能目标未达标：首字延迟 P50 约 0.97 s（目标 0.8 s）；LLM 精修 P50 约 2.66 s（目标 1–2 s）；智能模式内存约 2.5 GB（基础模式 559 MB 达标）。详见性能报告。

## 许可证

第三方模型/库的来源与许可证见 `licenses/` 与 `docs/model-manifest.md`。
