本地语音输入 LocalVoiceInput v1.2.0
==================================

双击 LocalVoiceInput.exe 启动；首次启动按引导选择麦克风与快捷键。

- 按住热键（默认 F9）说话，松开后文字插入当前输入框。
- 托盘菜单可切换：极速输入 / 智能精修 / 自动。
- 设置：托盘 → 设置…；也可以运行 LocalVoiceInput.exe --settings。
- 诊断：LocalVoiceInput.exe --diagnose
- 屏幕阅读 / 长文本：智能精修面板中确认后插入。
- 数据目录：%LOCALAPPDATA%\LocalVoiceInput（便携模式为程序目录下 data\）
- 安装目录：%LOCALAPPDATA%\Programs\LocalVoiceInput

全部语音识别与文本精修均在本机完成，不联网、不上传录音或文字。
模型与第三方许可证见 models\manifest.json 与 licenses\ 目录。

若目标窗口以管理员权限运行，本程序也需以管理员身份运行，Windows 才允许向其发送按键。
