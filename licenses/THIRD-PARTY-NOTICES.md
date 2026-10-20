# Third-Party Notices / 第三方许可证

本安装包包含以下第三方组件与模型。各组件的许可证原文见同目录文件。

## 模型

| 组件 | 版本/文件 | 许可证 | 来源 |
|---|---|---|---|
| Streaming Zipformer (X-ASR 480ms zh-en punct, INT8) | `sherpa-onnx-x-asr-480ms-streaming-zipformer-transducer-zh-en-punct-int8-2026-06-05` | Apache-2.0 | https://github.com/Gilgamesh-J/X-ASR ; 打包自 https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models |
| SenseVoice-Small (INT8, 复核) | `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17` | FunASR Model License 1.1（允许使用/复制/修改/分享，需保留来源与模型名） | https://github.com/modelscope/FunASR ; https://huggingface.co/FunAudioLLM/SenseVoiceSmall |
| Qwen3.5-2B-Instruct GGUF (Q4_K_M) | `Qwen3.5-2B-Q4_K_M.gguf` | Apache-2.0 | https://huggingface.co/Qwen/Qwen3.5-2B ; 量化文件 https://huggingface.co/unsloth/Qwen3.5-2B-GGUF |

模型文件的精确 SHA-256 见安装目录 `models/manifest.json`。

## 运行时与库

| 组件 | 许可证 | 来源 |
|---|---|---|
| llama.cpp (b11748, win-cpu-x64) | MIT | https://github.com/ggml-org/llama.cpp |
| sherpa-onnx / sherpa-onnx-core 1.13.8 | Apache-2.0 | https://github.com/k2-fsa/sherpa-onnx |
| ONNX Runtime (随 sherpa-onnx 分发) | MIT | https://github.com/microsoft/onnxruntime |
| Python 3.14 (embedded runtime) | PSF License | https://www.python.org |
| NumPy | BSD-3-Clause | https://numpy.org |
| sounddevice / PortAudio | MIT | https://python-sounddevice.readthedocs.io |
| python-soxr / libsoxr | LGPL-2.1 | https://github.com/dofuuz/python-soxr |
| keyboard | MIT | https://github.com/boppreh/keyboard |
| pystray | LGPL-3.0 | https://github.com/moses-palmer/pystray |
| Pillow | HPND | https://python-pillow.org |
| PyYAML | MIT | https://pyyaml.org |
| Tcl/Tk | Tcl/Tk License | https://www.tcl.tk |
| Inno Setup (仅安装器) | Inno Setup License | https://jrsoftware.org |

## 声明

- 本项目不包含任何云端 ASR / 云端 LLM 调用。
- 模型权重与运行库均随安装包分发，安装后无需联网。
- 若再分发本安装包，请保留本目录及 `models/manifest.json` 中的来源与许可证信息。
