@echo off
setlocal
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo [!] 未找到 uv，请先安装：https://docs.astral.sh/uv/
    pause
    exit /b 1
)

if not exist ".venv" (
    echo [1/3] 创建虚拟环境 .venv ...
    uv venv .venv
)

echo [2/3] 安装依赖 ...
uv pip install --python ".venv\Scripts\python.exe" -r requirements.txt
if errorlevel 1 (
    echo [!] 依赖安装失败
    pause
    exit /b 1
)

echo [3/3] 下载 ASR 模型（首次需要联网，之后完全离线）...
".venv\Scripts\python.exe" -m voiceinput.download_models

echo.
echo 安装完成！运行 run.bat 启动。
pause
endlocal
