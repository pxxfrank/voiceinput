@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] 尚未安装，请先运行 setup.bat
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m voiceinput %*
endlocal
