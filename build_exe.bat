@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] 请先运行 setup.bat
    pause
    exit /b 1
)

echo [1/3] 安装 PyInstaller ...
uv pip install --python ".venv\Scripts\python.exe" pyinstaller
if errorlevel 1 ( echo [!] 安装失败 & pause & exit /b 1 )

echo [2/3] 生成图标 ...
".venv\Scripts\python.exe" -m voiceinput.make_icon

echo [3/3] 打包（onedir）...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --name voiceinput ^
  --icon voiceinput.ico ^
  --collect-all sherpa_onnx ^
  --collect-all sounddevice ^
  --hidden-import pystray._win32 ^
  --hidden-import voiceinput.gui ^
  --hidden-import voiceinput.devices ^
  --hidden-import voiceinput.history ^
  --hidden-import voiceinput.hud ^
  --hidden-import voiceinput.download_models ^
  main.py
if errorlevel 1 ( echo [!] 打包失败 & pause & exit /b 1 )

echo.
echo 打包完成：dist\voiceinput\voiceinput.exe
echo 请把 config.yaml 和 models\ 复制到 dist\voiceinput\ 下（models 很大，可改 config.yaml 里的 model_dir 为绝对路径指向原目录）。
pause
endlocal
