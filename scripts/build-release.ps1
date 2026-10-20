# LocalVoiceInput 一键构建
# 用途：依赖检查 → 单元测试 → PyInstaller → 模型/许可证整理 → Portable ZIP → Setup.exe → SHA256
# 构建期可联网（模型已存在时不会重复下载）；最终运行完全离线。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1
#   ... -SkipTests -NoInstaller
#   ... -NoModels          # 生成增量更新包（不含模型，复用已安装模型）
#   ... -NoModels -SkipZip # 只生成 Update.exe

param(
    [switch]$SkipTests,
    [switch]$NoInstaller,
    [switch]$SkipZip,
    [switch]$NoModels
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "缺少 .venv，请先创建虚拟环境并安装 requirements-dev.txt" }

Write-Host "== 1/8 检查依赖 =="
& $python -c "import sherpa_onnx, sounddevice, soxr, keyboard, pystray, PIL, yaml, PyInstaller; print('deps ok')"
if ($LASTEXITCODE -ne 0) { throw "运行依赖不完整" }

Write-Host "== 2/8 校验模型清单 =="
& $python -m voiceinput.download_models --verify
if ($LASTEXITCODE -ne 0) { throw "模型校验失败：请运行 python -m voiceinput.download_models --download --manifest" }

if (-not $SkipTests) {
    Write-Host "== 3/8 单元测试 =="
    & $python -m pytest tests -q
    if ($LASTEXITCODE -ne 0) { throw "单元测试失败" }
} else {
    Write-Host "== 3/8 单元测试（已跳过）=="
}

Write-Host "== 4/8 PyInstaller 打包 =="
if (Test-Path "build\voiceinput") { Remove-Item "build\voiceinput" -Recurse -Force }
if (Test-Path "dist\LocalVoiceInput") { Remove-Item "dist\LocalVoiceInput" -Recurse -Force }
& $python -m PyInstaller --noconfirm --clean voiceinput.spec
if (-not (Test-Path "dist\LocalVoiceInput\LocalVoiceInput.exe")) { throw "PyInstaller 未生成 exe" }

Write-Host "== 5/8 整理发布目录 =="
$stage = "build\pkg\LocalVoiceInput"
if (Test-Path "build\pkg") { Remove-Item "build\pkg" -Recurse -Force }
New-Item -ItemType Directory -Force $stage | Out-Null
Copy-Item "dist\LocalVoiceInput\*" $stage -Recurse -Force
if (-not $NoModels) {
    Copy-Item "models" (Join-Path $stage "models") -Recurse -Force
}
Copy-Item "licenses" (Join-Path $stage "licenses") -Recurse -Force
Copy-Item "packaging\README.txt" (Join-Path $stage "README.txt") -Force
Copy-Item "docs\user-guide.md" (Join-Path $stage "使用说明.md") -Force -ErrorAction SilentlyContinue

Write-Host "== 6/8 发布目录自检 =="
if ($NoModels) {
    if (Test-Path (Join-Path $stage "models")) { throw "增量更新包不应包含 models 目录" }
    Write-Host "增量更新包：复用目标目录中已有的 models/，跳过模型自检"
} else {
    & (Join-Path $stage "LocalVoiceInput.exe") --diagnose | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "发布目录自检失败（模型缺失或不可用）" }
}

Write-Host "== 7/8 生成 Portable ZIP =="
New-Item -ItemType Directory -Force "release" | Out-Null
if ($NoModels) {
    Write-Host "增量更新包不生成 Portable ZIP（Portable 首次使用必须带模型）"
} elseif (-not $SkipZip) {
    & $python "scripts\make_zip.py" $stage "release\LocalVoiceInput-Portable-x64.zip"
    if ($LASTEXITCODE -ne 0) { throw "Portable ZIP 生成失败" }
}

if (-not $NoInstaller) {
    Write-Host "== 8/8 Inno Setup 安装程序 =="
    $iscc = $env:ISCC
    if (-not $iscc) {
        $iscc = Join-Path $root "tools\innosetup\app\ISCC.exe"
    }
    if (-not (Test-Path $iscc)) { throw "未找到 ISCC.exe；请设置 ISCC 环境变量或安装 Inno Setup" }
    $isccArgs = @("/Qp")
    if ($NoModels) { $isccArgs += "/DNoModels=1" }
    $isccArgs += "packaging\installer.iss"
    & $iscc @isccArgs
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup 编译失败" }
}

Write-Host "== 计算校验值 =="
$hashes = @()
$files = @("release\LocalVoiceInput-Setup-x64.exe", "release\LocalVoiceInput-Portable-x64.zip")
if ($NoModels) { $files = @("release\LocalVoiceInput-Update-x64.exe", "release\ReleaseNotes.md") }
foreach ($file in $files) {
    if (Test-Path $file) {
        $h = (Get-FileHash $file -Algorithm SHA256).Hash.ToLower()
        $hashes += "$h  $([IO.Path]::GetFileName($file))"
        Write-Host "$file  $h"
    }
}
$sumFile = if ($NoModels) { "release\SHA256SUMS-update.txt" } else { "release\SHA256SUMS.txt" }
$hashes | Set-Content $sumFile -Encoding ASCII
Write-Host "构建完成：release\ $(if ($NoModels) { '（增量更新包）' } else { '' })"
