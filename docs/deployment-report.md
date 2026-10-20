# 部署与发布报告

## 1. 交付产物

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| `release/LocalVoiceInput-Setup-x64.exe` | 1546.5 MB | `54c5b0e2e385f2dcdb66683d165a9a243c4084a15f636eba8eac266801d24165` |
| `release/LocalVoiceInput-Portable-x64.zip` | 1768.2 MB | `209ca7c6c0dc7e70c70c0f2f78ae8cf1fb91ba5b29a42026d3596f68dbe533e0` |
| `release/LocalVoiceInput-Update-x64.exe` | 42.8 MB | `da2022f644d2f964d3c46f1dfb69c1a4f4318b8e920cf922033d51f567a7b266` |
| `release/update.json` | 1.1 KB | `49257b7cb659ff8d877f7b8c0a74a15937e28441b4199dbdaafc48461637e7d3` |
| `release/SHA256SUMS.txt` | — | 上述两行 |

- 版本：**1.1.0**
- Release：<https://github.com/pxxfrank/voiceinput/releases/tag/v1.1.0>
- 更新清单：<https://github.com/pxxfrank/voiceinput/releases/latest/download/update.json>
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

## 5. 增量更新包（不含模型）

已支持“首次安装带模型、后续更新不带模型”的构建方式：

```powershell
# 完整安装包（含全部模型，用于首次安装/修复）
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1

# 增量更新包（不含 models，复用已安装模型）
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1 -NoModels -SkipZip
```

产物：

- `release\LocalVoiceInput-Setup-x64.exe`：完整包（约 1.5 GB）
- `release\LocalVoiceInput-Update-x64.exe`：增量包（当前约 **40 MB**）
- `release\SHA256SUMS-update.txt`：增量包校验值

增量安装器在 `PrepareToInstall` 中检查目标目录已有的
`models\manifest.json`、流式 ASR、复核 ASR、LLM GGUF 与 llama-server；
缺失时中止并提示先安装完整包。Inno Setup 升级不会删除新安装包中未列出的旧文件，
因此 `models\` 会保留；安装前会清理旧的 `_internal`、`licenses` 与应用文件，避免旧版本残留叠加。
卸载仍会删除整个安装目录（含模型）。

> 首次安装、卸载后重装、模型版本升级仍需使用完整包。
> 增量包只适用于“已安装完整版且模型未变”的升级场景。

### 5.1 模型集校验

- `models/model-set.txt` 与 `manifest.json` 的 `model_set` 当前为 `2026-10-20.1`。
- 应用启动时校验；增量安装器读取 `model-set.txt` 校验；不匹配时拒绝启动识别/拒绝安装。
- 旧版 v1.0.0 没有 marker 时按兼容迁移处理，后续版本必须携带 marker。

### 5.2 签名更新清单

```powershell
# 构建增量包后生成签名清单（需要 keys/update_ed25519.pem）
python scripts\make_update_manifest.py --version 1.1.0 `
  --update-exe release\LocalVoiceInput-Update-x64.exe `
  --full-exe release\LocalVoiceInput-Setup-x64.exe `
  --out release\update.json

# 发布时把 update.json 一起上传；应用默认读取
# https://github.com/pxxfrank/voiceinput/releases/latest/download/update.json
```

- 清单使用 Ed25519 签名，公钥硬编码在 `voiceinput/update.py`；私钥仅构建机持有，**必须离线备份**。
- 应用下载后校验清单签名 + 更新包 SHA-256，再退出并启动安装器。
- 私钥丢失后需重新生成并在新版本中替换公钥；旧版本将无法验证新清单。

## 6. 实际部署验证

| 步骤 | 结果 |
|---|---|
| Setup 静默安装到测试目录 | 退出 0，文件齐全（1768 MB） |
| 开始菜单快捷方式 | 已创建（主程序/设置/卸载） |
| 安装目录 `--version` | `LocalVoiceInput 1.1.0` |
| 安装目录 `--diagnose` | 退出 0，全部模型 OK |
| 安装目录 `--verify-models` | 退出 0（45/45） |
| 安装目录 `--selftest --llm-test` | 退出 0（真实流式/复核/LLM） |
| 安装目录真实 WAV → 真实文本框 | 通过（上一构建；输入模块未变） |
| 剪贴板恢复 | 通过 |
| 卸载 | 退出 0，安装目录删除，开始菜单快捷方式移除 |
| 用户数据保留 | 通过（`%LOCALAPPDATA%\LocalVoiceInput` 仍存在） |
| Portable ZIP 完整性 | `testzip` 无错误 |
| Portable 解压运行 | 退出 0，`portable=True`，数据在 `data\` |

## 7. 未完成/风险

- 未在全新 Windows 11 虚拟机（无 Python/.NET/VC++/Ollama）上安装验证；安装包自包含，但该环境验收未执行。
- 未在目标 ThinkPad 硬件上验证。
- 安装包未代码签名，Windows SmartScreen 可能提示；正式外部分发建议购买代码签名证书。
- 安装器为 per-user，不使用 `Program Files`；符合无管理员场景，但与“Program Files”建议路径不同。
- 安装包约 1.5 GB，主要来自 Qwen3.5-2B（1.22 GB）与两个 ASR 模型（约 0.4 GB）。

## 8. 回滚

- 重新运行旧版本 Setup 即可覆盖安装；用户数据保留。
- 卸载不会删除用户数据；如需完全清除，手动删除 `%LOCALAPPDATA%\LocalVoiceInput`。
