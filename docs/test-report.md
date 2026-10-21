# 测试报告

> 日期：2026-10-20
> 环境：QEMU / Windows 10 19045 x64 / Xeon Gold 6230N 36 核 / 64 GB / 非管理员 / 仅 RDP 音频
> 目标环境（Windows 11 / ThinkPad X1 Carbon Gen 12 / Ultra 7 155H / Arc）**未测试**。

## 1. 测试执行总览

| 类型 | 命令 | 结果 |
|---|---|---|
| 单元测试 | `python -m pytest tests -q` | **71 passed** |
| UI 冒烟（Tk） | `VOICEINPUT_UI_TESTS=1 python -m pytest tests/test_ui_smoke.py -q` | **3 passed** |
| 真实模型集成 | `VOICEINPUT_RUN_INTEGRATION=1 python -m pytest tests/test_integration_real.py -q` | **2 passed**（24.3 s） |
| 真实音频自检 | `python -m voiceinput --selftest --llm-test` | 通过（流式/复核/LLM 均输出真实文本） |
| 断网审计 | `python tests/offline_run.py --selftest --wav ... --llm-test` | 通过，外部网络尝试：无 |
| 打包产物诊断 | `build\pkg\LocalVoiceInput\LocalVoiceInput.exe --diagnose` | 退出 0，全部模型 OK |
| 安装包安装 | `Setup.exe /VERYSILENT /DIR=...` | 退出 0，文件齐全 |
| 安装后 E2E | 安装目录 exe + 真实 WAV + 真实文本框 | 上一构建通过；最终构建的 `--selftest`/`--diagnose`/`--verify-models` 均退出 0（输入模块未改动） |
| 卸载 | `unins000.exe /VERYSILENT` | 退出 0，安装目录删除，用户数据保留 |
| 安装包 | 完整 Setup 静默安装/卸载 | 通过 |

## 2. 单元测试覆盖

| 模块 | 覆盖点 |
|---|---|
| `test_normalizer.py` | 中英术语大小写、空格、标点、数字保留、词库替换、受保护术语 |
| `test_vad.py` | 语音开始/结束、短停顿不切段、自适应噪声、无语音不触发 |
| `test_streaming_text.py` | 稳定前缀增长、单调不回退、英文半词不标稳定 |
| `test_merge.py` | 复核采用/冲突、数字丢失、受保护术语、英文词不一致保留流式 |
| `test_guard.py` | 数字篡改、新英文词（OSOS）、否定词、不确定性、长度异常、标点微调 |
| `test_storage.py` | 历史限制、词库 upsert/delete、onboarded、会话统计 |
| `test_refinement.py` | 忠实档不调 LLM、用户编辑优先、过期结果丢弃、守门回退、JSON 解析 |
| `test_input.py` | 目标缺失/失效/变化、重复提交幂等、载荷空格/换行、撤销无记录 |
| `test_ui_smoke.py` | 悬浮窗按钮、精修面板编辑、差异对照面板 |
| `test_compat.py` | 终端/Windows Terminal/经典控制台/普通编辑框输入策略 |
| `test_diff.py` | 逐条接受/拒绝修改、字符级 diff |
| `test_update.py` | 签名更新清单校验、版本比较、篡改拒绝 |
| `test_drafts.py` | 整理结果草稿保存/读取/清理 |
| `test_model_set.py` | 模型集 marker/manifest 匹配、旧版兼容、不匹配拒绝 |

## 3. 端到端（E2E）证据

### 场景 A：极速输入（真实应用 + 真实文本框）

- 使用真实 WAV `0.wav` 驱动完整管线（非模拟字符串）。
- 目标：真实 Tk 文本框（Win32 窗口，`tests/target_app.py`）。
- 结果：插入 `昨天是 monday。Today is 礼拜二。the day after tomorrow 是星期三。`
- 剪贴板：插入前 `PROTECTED_E2E`，插入后仍为 `PROTECTED_E2E`。
- 重复片段：3 段各提交一次，无重复文字。

### 场景 B：中英混合

- 4 段模型自带真实语音；包含 Monday / Today / the day after tomorrow / always / frequently / ES 等。
- 中英混排、大小写、空格由规范化处理；复核与流式英文词不一致时保留流式并标记。

### 场景 C：长文本精修

- 真实 WAV `1.wav` → 流式 + SenseVoice 复核 + Qwen3.5 精修。
- 面板显示原文/精修，可编辑、重新识别、重新精修、深度整理、复制、插入。
- 真实模型输出示例：`这是第一种，第二种叫呃与 always always 什么意思啊。`
- 注意：精修是“最小必要整理”，不保证消除所有口头禅；模型偶尔会保持原样。

### 场景 D：输入焦点改变

- 准备事务后切换到第二个文本框再提交。
- 结果：`status=target_changed`，第二个窗口没有收到文字；原文本保留。
- 用户显式选择“插入到原窗口”后，才恢复焦点并插入原目标。

### 场景 E：模型异常

- 将 `refine.model` 指向不存在的文件，智能模式运行真实 WAV。
- 结果：LLM 返回“本地 LLM 运行时不完整”，管线回退到确定性文本，文本仍成功插入；剪贴板恢复成功。
- 流式模型缺失时：程序启动但按热键提示“模型加载失败”，不会静默模拟识别。

### 场景 F：断网

- 在进程内安装审计钩子，拒绝一切非回环 `connect`/`getaddrinfo`。
- 运行真实流式、复核、LLM 自检：全部成功，`外部网络尝试： 无`。
- 说明：未在物理断网/全新虚拟机中执行；该测试证明运行期代码不需要外部网络。

### 场景 G：重复使用

- 连续多次开始/停止/取消；每次会话创建新流、释放音频；无重复上屏。
- 片段音频在提交后释放；>20 段丢弃最旧音频。
- 未执行 3 小时长稳测试。

## 4. 输入安全专项

| 测试 | 结果 |
|---|---|
| 剪贴板文本快照/恢复 | 通过（序列号证明仍由本次占用才恢复） |
| 剪贴板含图片（非文本格式） | 检测到 `complete=False`，改用 Unicode 直输；**原图片剪贴板保留**，文字成功输入 |
| 目标窗口关闭 | 拒绝提交，保留文字 |
| 目标焦点变化 | 拒绝自动提交，保留文字 |
| 管理员权限目标 | 提前检测 UIPI 并提示以管理员运行 |
| 终端兼容 | 单元测试验证 Windows Terminal/经典控制台选择不同粘贴快捷键 |
| 重复提交 | `commit_status=committed` 后幂等 |
| 撤销 | 无记录时提示；60 秒窗口；不对 partial 做无限退格 |

## 4.1 更新与精修审阅专项

| 测试 | 结果 |
|---|---|
| Ed25519 签名清单 | 通过；篡改版本后签名校验失败 |
| 版本比较/无更新 | 通过 |
| 模型集不匹配 | 应用启动拒绝加载；增量安装器拒绝安装 |
| 逐条接受/拒绝修改 | 通过；全部接受保留 LLM 文本，拒绝回退到原文/部分应用 |
| 差异高亮 | 通过；左右文本由字符级 diff 生成 |

## 5. 安装/卸载

- 安装器：Inno Setup 7.1.0，per-user，无需管理员。
- 安装目录：`build/install-test`（测试）/ 默认 `%LOCALAPPDATA%\Programs\LocalVoiceInput`。
- 安装后 `--version`、`--diagnose` 正常；`--diagnose` 全部模型 OK。
- 安装后真实 WAV → 真实文本框插入成功，剪贴板保留。
- 卸载后安装目录删除，`%LOCALAPPDATA%\LocalVoiceInput`（配置/历史/日志/缓存）保留。
- 开始菜单快捷方式在卸载后移除。

## 6. 未执行 / 未验证

- **真实物理麦克风**：本机只有 RDP 重定向音频（可出帧，静音）与虚拟阵列（全零），无法验证真人说话。
- **Windows 11**：本机为 Windows 10 19045。
- **目标硬件**：ThinkPad X1 Carbon Gen 12 / Ultra 7 155H / Arc / NPU 未测试。
- **干净环境**（无 Python/.NET/VC++/Ollama）安装：安装包自包含，但未在全新虚拟机执行。
- **3 小时连续运行**：未执行。
- **Windows UI Automation 全量点击**：悬浮窗/面板通过 Tk 冒烟与截图验证；未覆盖所有 DPI/多显示器组合。
- **非文本剪贴板的 100% 全格式还原**：不承诺；采用“检测不完整即不覆盖、改直输”的策略。
- **管理员权限目标窗口**：Windows UIPI 限制，普通权限程序无法注入；需以管理员运行本程序。

## 7. 已知问题

1. 首字延迟 P50 968 ms，未达 800 ms 目标。
2. LLM 精修 P50 2.66 s，高于 1–2 s 目标。
3. 智能模式常驻 LLM 时总内存约 2.5 GB，高于 1.5 GB 目标；基础模式 559 MB 达标。
4. 精修模型能力有限，可能保留口头禅或做轻微改写；语义守卫会拦截数字/英文词/术语/否定等高风险改动，但不能覆盖所有语义风险。
5. 非管理员运行时无法向管理员窗口插入。
6. 共享桌面中其他 always-on-top 应用可能遮挡精修面板/悬浮窗；悬浮窗本身为 topmost。
7. 真实麦克风与目标硬件未验证，不能声称已满足对应验收项。

## 8. 结论

可交付状态：**安装包、真实模型、真实上屏、剪贴板保护、安装/卸载均已实际验证；Portable 版本已停止发布**。
性能目标部分未达标（首字延迟、LLM 延迟、智能模式内存），已在性能报告中如实标记；
真实麦克风、Windows 11、目标硬件与 3 小时长稳未验证，不能视为已完成。
