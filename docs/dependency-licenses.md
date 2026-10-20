# 依赖与许可证

本文件列出最终安装包内的主要第三方组件。许可证原文位于安装目录 `licenses\`，
模型文件的 SHA-256 与来源见 `docs/model-manifest.md` 与 `models/manifest.json`。

## 运行时 / 库

| 组件 | 版本 | 许可证 | 来源 |
|---|---|---|---|
| Python | 3.14.5 | PSF License | https://www.python.org |
| sherpa-onnx / sherpa-onnx-core | 1.13.8 | Apache-2.0 | https://github.com/k2-fsa/sherpa-onnx |
| ONNX Runtime（随 sherpa-onnx） | - | MIT | https://github.com/microsoft/onnxruntime |
| NumPy | 2.5.3 | BSD-3-Clause | https://numpy.org |
| sounddevice | 0.5.6 | MIT | https://python-sounddevice.readthedocs.io |
| PortAudio（随 sounddevice） | - | MIT | https://www.portaudio.com |
| python-soxr / libsoxr | 1.1.0 | LGPL-2.1 | https://github.com/dofuuz/python-soxr |
| keyboard | 0.13.5 | MIT | https://github.com/boppreh/keyboard |
| pystray | 0.19.5 | LGPL-3.0 | https://github.com/moses-palmer/pystray |
| Pillow | 12.3.0 | HPND | https://python-pillow.org |
| PyYAML | 6.0.3 | MIT | https://pyyaml.org |
| Tcl/Tk（Python 自带） | - | Tcl/Tk License | https://www.tcl.tk |
| llama.cpp | b11748 | MIT | https://github.com/ggml-org/llama.cpp |
| Inno Setup（仅安装器） | 7.1.0 | Inno Setup License | https://jrsoftware.org |

## 模型

| 组件 | 许可证 | 来源 |
|---|---|---|
| Streaming X-ASR 480ms Zipformer (zh-en, punct, INT8) | Apache-2.0 | https://github.com/Gilgamesh-J/X-ASR |
| SenseVoice-Small (INT8) | FunASR Model License 1.1（保留来源与模型名） | https://github.com/modelscope/FunASR ; https://huggingface.co/FunAudioLLM/SenseVoiceSmall |
| Qwen3.5-2B-Instruct GGUF Q4_K_M | Apache-2.0 | https://huggingface.co/Qwen/Qwen3.5-2B ; https://huggingface.co/unsloth/Qwen3.5-2B-GGUF |

## 再分发注意事项

- **LGPL（soxr、pystray）**：以动态库/可替换形式随应用分发；许可证原文已包含。
- **FunASR Model License 1.1**：允许使用、复制、修改、分享；需要保留来源、作者与模型名称。
  本安装包保留 `models/offline-asr/sense-voice/LICENSE`、模型目录名与 `manifest.json` 来源字段。
- **Apache-2.0**：保留版权与许可证声明；安装包内 `licenses/APACHE-2.0.txt`。
- **MIT/BSD/HPND/PSF**：保留版权与许可证声明；见 `licenses/`。
- 若移除或替换模型，请同步更新 `models/manifest.json` 与本文档。

## 未包含

- 不包含 Python 源码解释器的开发头文件/静态库（仅运行时）。
- 不包含 CUDA、OpenVINO、Ollama、FFmpeg、Git 或任何云端服务 SDK。
