# 模型清单与来源

清单文件：`models/manifest.json`（46 个文件，含每个文件的 size + SHA-256）。
运行期启动只做存在性/大小检查；完整 SHA-256 校验由 `--verify-models` 或设置页“校验模型”执行。

## 模型集版本

- `models/model-set.txt`：`2026-10-20.1`
- `models/manifest.json` 的 `model_set` 字段同值。
- 应用与增量安装器都校验该值；不匹配会拒绝启动识别/拒绝安装增量包。
- 模型集变化时必须提升该值，并发布完整安装包；增量包不能替代模型升级。

## 1. 流式主 ASR

| 项 | 值 |
|---|---|
| 名称 | sherpa-onnx X-ASR 480ms Streaming Zipformer Transducer (zh-en, punctuation) |
| 目录 | `models/streaming-asr/sherpa-onnx-x-asr-480ms-streaming-zipformer-transducer-zh-en-punct-int8-2026-06-05` |
| 来源 | https://github.com/Gilgamesh-J/X-ASR ；打包自 https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models |
| 版本/revision | 模型目录名固定为 `...-2026-06-05`；不使用 latest |
| 量化 | encoder INT8、joiner INT8、decoder FP32 |
| 许可证 | Apache-2.0 |
| 运行 | sherpa-onnx 1.13.8，CPU，16 kHz 单声道 |

| 文件 | 大小 (bytes) | SHA-256 |
|---|---:|---|
| encoder.int8.onnx | 155,278,641 | `908596dcc137a73b95be908ca55e88caa1b3dbbe8027c171615f4b0609c5eb1e` |
| decoder.onnx | 11,309,084 | `a1cbc9eac2d5e3fb6617a218c67ad6daaa7f4e0fd225f08b2c22ab0413c8c257` |
| joiner.int8.onnx | 2,581,422 | `aedb7fa697b2ab43f20499826fff7c997eea7d67db77be97769aeeeb726e63b3` |
| tokens.txt | 58,806 | `b818a60878b9aae9…`（完整值见 manifest） |

**实测**（本机 Xeon，4 线程）：10 秒中文音频，RTF 0.15–0.18；4 段测试语音均输出通顺中英混排文本；首字延迟 P50 约 0.97 s（详见性能报告）。
曾对比同系列 160ms 模型：首字约 0.81 s，但 RTF 0.35、识别质量下降（“礼拜二”误为“篱 Ba”），故不采用。

## 2. 复核 ASR

| 项 | 值 |
|---|---|
| 名称 | SenseVoice-Small（中文/英文/日文/韩文/粤语） |
| 目录 | `models/offline-asr/sense-voice` |
| 来源 | https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models ；上游 https://huggingface.co/FunAudioLLM/SenseVoiceSmall |
| 量化 | `model.int8.onnx`，INT8 |
| 许可证 | FunASR Model License 1.1（允许使用/复制/修改/分享，需保留来源与模型名） |
| 文件 | model.int8.onnx 239,233,841 B，SHA-256 `c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51`；tokens.txt 315,894 B |
| 实测 | 4–11 秒音频复核 0.24–0.53 s（RTF 0.03–0.06） |

复核不是“更正确”的同义词：相似度足够且未丢失数字/术语/英文词时才采用；否则保留流式结果并标记。

## 3. 本地 LLM

| 项 | 值 |
|---|---|
| 名称 | Qwen3.5-2B-Instruct |
| 量化文件 | `Qwen3.5-2B-Q4_K_M.gguf`（1,280,835,840 B） |
| 来源 | 官方 https://huggingface.co/Qwen/Qwen3.5-2B ；量化 https://huggingface.co/unsloth/Qwen3.5-2B-GGUF |
| SHA-256 | `aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223` |
| 许可证 | Apache-2.0 |
| 运行 | llama.cpp b11748 win-cpu-x64，CPU，仅 127.0.0.1 |
| 实测 | 加载 4.0–6.0 s（预热后）；首 token 269 ms；完整精修 P50 2.55 s（12 线程） |
| 关闭 thinking | `chat_template_kwargs: {"enable_thinking": false}`；未开启时输出为空/极慢 |

> 评测过 `Qwen3.5-0.8B`：下载源速度过慢未完成完整评测，不作为默认；`Qwen3.5-4B` 未默认常驻，避免首用内存/延迟过高。
> `Qwen3.5-2B` 官方仓库不提供 GGUF，使用 unsloth 的 Apache-2.0 量化文件，并在此记录来源与 SHA。

## 4. LLM 运行时

| 项 | 值 |
|---|---|
| 版本 | llama.cpp `b11748`（commit 3bb63cbcb） |
| 包 | `llama-b11748-bin-win-cpu-x64.zip` |
| 来源 | https://github.com/ggml-org/llama.cpp/releases/tag/b11748 |
| 许可证 | MIT |
| 打包文件 | llama-server.exe + 所需 DLL（含各 CPU 指令集后端） |
| 校验 | `llama-server.exe` SHA-256 `5611f4f8338f54d7fa409fc66f777349ebbd32bab48ebd0f0442db675612f781` |

## 5. 复现与校验

```powershell
# 构建期：下载缺失模型（已存在则跳过）
.venv\Scripts\python.exe -m voiceinput.download_models --download

# 生成/更新 SHA-256 清单
.venv\Scripts\python.exe -m voiceinput.download_models --manifest

# 按清单校验（安装前/发布前）
.venv\Scripts\python.exe -m voiceinput.download_models --verify
# 或运行安装后的 exe：
LocalVoiceInput.exe --verify-models
```

所有模型与运行库随安装包分发；安装完成后断网仍可运行。
