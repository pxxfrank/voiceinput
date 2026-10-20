# 部署与发布报告

## 1. 交付产物

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| `release/LocalVoiceInput-Setup-x64.exe` | 1543.7 MB | `d57e511e08a41395e19ab32935ab2d22e6e44c7bc5965432dd9db325e2d3dde0` |
| `release/LocalVoiceInput-Portable-x64.zip` | 1758.7 MB | `c96adf4c39f8ac1422546b12ddbfcbd9ac75cb5c648260a9fa833014d8efd33e` |
| `release/SHA256SUMS.txt` | — | 上述两行 |

- 版本：**1.0.0**
- 安装器：Inno Setup 7.1.0
- 发布模式：自包含（PyInstaller onedir + Python 3.14.5 + native DLL + 模型）

## 2. 安装方式

```text
双击 Setup.exe
  → per-user 安装到 %LOCALAPPDATA%\Programs\LocalVoiceInput
  → 创建开始菜单快捷方式（本地语音输入 / 设置 / 卸载）
  → 可选桌面快捷方式（默认不勾选）
  → 可选安装完成后启动
```

- **不需要管理员权限**，不会写入 `Program Files`。
- 不需要安装 Python、.NET Desktop Runtime、VC++ Redistributable、CUDA、ONNX Runtime、
  llama.cpp、Ollama、FFmpeg、Git、ASR/LLM 模型。
- 安装过程不联网；模型全部在安装包内。

## 3. 目录布局

安装目录：

```text
%LOCALAPPDATA%\Programs\LocalVoiceInput\
  LocalVoiceInput.exe
  _internal\                 PyInstaller 运行时与依赖
  models\
    streaming-asr\sherpa-onnx-x-asr-480ms-...\
    offline-asr\sense-voice\
    llm\Qwen3.5-2B-Q4_K_M.gguf
    llm-runtime\llama\
    manifest.json
  licenses\
  README.txt
  unins000.exe
```

用户数据（卸载保留）：

```text
%LOCALAPPDATA%\LocalVoiceInput\
  settings\config.yaml
  database\voiceinput.db
  logs\
  cache\
  runtime\
```

便携模式（ZIP 内 `portable.flag`）：数据保存在程序目录 `data\`。

## 4. 构建流程（可重复）

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1
```

脚本执行：

1. 检查运行依赖与模型清单（`models/manifest.json`，45 个文件 SHA-256）。
2. 运行单元测试（49 项）。
3. PyInstaller `--clean` 打包（`voiceinput.spec`）。
4. 整理发布目录：exe + `_internal` + `models` + `licenses` + `README`。
5. 发布目录 `--diagnose` 自检。
6. 生成 Portable ZIP（ZIP64，附加 `portable.flag`）。
7. Inno Setup 编译 `Setup.exe`。
8. 生成 `release/SHA256SUMS.txt`。

模型准备（构建期联网，已存在则跳过）：

```powershell
.venv\Scripts\python.exe -m voiceinput.download_models --download
.venv\Scripts\python.exe -m voiceinput.download_models --manifest
.venv\Scripts\python.exe -m voiceinput.download_models --verify
```

## 5. 实际部署验证

| 步骤 | 结果 |
|---|---|
| Setup 静默安装到测试目录 | 退出 0，文件齐全（1768 MB） |
| 开始菜单快捷方式 | 已创建（主程序/设置/卸载） |
| 安装目录 `--version` | `LocalVoiceInput 1.0.0` |
| 安装目录 `--diagnose` | 退出 0，全部模型 OK |
| 安装目录 `--verify-models` | 退出 0（45/45） |
| 安装目录 `--selftest --llm-test` | 退出 0（真实流式/复核/LLM） |
| 安装目录真实 WAV → 真实文本框 | 通过（上一构建；输入模块未变） |
| 剪贴板恢复 | 通过 |
| 卸载 | 退出 0，安装目录删除，开始菜单快捷方式移除 |
| 用户数据保留 | 通过（`%LOCALAPPDATA%\LocalVoiceInput` 仍存在） |
| Portable ZIP 完整性 | `testzip` 无错误 |
| Portable 解压运行 | 退出 0，`portable=True`，数据在 `data\` |

## 6. 未完成/风险

- 未在全新 Windows 11 虚拟机（无 Python/.NET/VC++/Ollama）上安装验证；安装包自包含，但该环境验收未执行。
- 未在目标 ThinkPad 硬件上验证。
- 安装包未代码签名，Windows SmartScreen 可能提示；正式外部分发建议购买代码签名证书。
- 安装器为 per-user，不使用 `Program Files`；符合无管理员场景，但与“Program Files”建议路径不同。
- 安装包约 1.5 GB，主要来自 Qwen3.5-2B（1.22 GB）与两个 ASR 模型（约 0.4 GB）。

## 7. 回滚

- 重新运行旧版本 Setup 即可覆盖安装；用户数据保留。
- 卸载不会删除用户数据；如需完全清除，手动删除 `%LOCALAPPDATA%\LocalVoiceInput`。
