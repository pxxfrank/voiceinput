; 本地语音输入 LocalVoiceInput - Inno Setup 安装脚本
; 完整安装：LocalVoiceInput-Setup-x64.exe（内置模型）
; 增量更新：LocalVoiceInput-Update-x64.exe（不内置模型，复用已安装模型）
; 采用 per-user 安装（无需管理员权限），用户数据与安装目录分离。

#define MyAppName "本地语音输入"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "LocalVoiceInput"
#define MyAppExeName "LocalVoiceInput.exe"
#define MyAppId "{{8E0C6B2A-5C4B-4F8E-9D2A-7B1C3D4E5F60}"
#define RequiredModelSet "2026-10-20.1"

#ifdef NoModels
#define MyOutputBase "LocalVoiceInput-Update-x64"
#define MySetupTitle "本地语音输入 更新程序"
#else
#define MyOutputBase "LocalVoiceInput-Setup-x64"
#define MySetupTitle "本地语音输入"
#endif

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/pxxfrank/voiceinput
DefaultDirName={localappdata}\Programs\LocalVoiceInput
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename={#MyOutputBase}
SetupIconFile=..\voiceinput.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/fast
SolidCompression=no
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes
UsePreviousTasks=yes
AppMutex=Local\LocalVoiceInput-singleton
SetupLogging=yes
DisableWelcomePage=no
LicenseFile=..\licenses\THIRD-PARTY-NOTICES.md

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标："; Flags: unchecked

[Files]
; 应用本体（模型单独处理，避免增量更新重复打包）
Source: "..\build\pkg\LocalVoiceInput\*"; DestDir: "{app}"; Excludes: "models\*,models"; Flags: ignoreversion recursesubdirs createallsubdirs
#ifndef NoModels
Source: "..\build\pkg\LocalVoiceInput\models\*"; DestDir: "{app}\models"; Flags: ignoreversion recursesubdirs createallsubdirs
#else
; 旧版 v1.0.0 没有 model-set.txt；增量包只补 marker，不覆盖 models
Source: "..\models\model-set.txt"; DestDir: "{app}\models"; Flags: ignoreversion
#endif

[InstallDelete]
; 覆盖安装前清理旧应用文件，避免旧版本 _internal 残留；models 目录不动
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\licenses"
Type: files; Name: "{app}\{#MyAppExeName}"
Type: files; Name: "{app}\README.txt"
Type: files; Name: "{app}\使用说明.md"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\设置"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--settings"
Name: "{group}\卸载{#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动{#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 仅删除安装目录；用户配置/历史/日志位于 %LOCALAPPDATA%\LocalVoiceInput，保留。
Type: filesandordirs; Name: "{app}"

#ifdef NoModels
[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ModelSet: AnsiString;
begin
  Result := '';
  if not FileExists(ExpandConstant('{app}\models\manifest.json')) then
  begin
    Result := '未找到已安装的模型。' + #13#10 +
              '请先安装完整版 LocalVoiceInput-Setup-x64.exe，或把模型放回安装目录的 models 文件夹。';
    Exit;
  end;
  if FileExists(ExpandConstant('{app}\models\model-set.txt')) then
  begin
    if LoadStringFromFile(ExpandConstant('{app}\models\model-set.txt'), ModelSet) then
    begin
      if Trim(String(ModelSet)) <> '{#RequiredModelSet}' then
      begin
        Result := '已安装的模型集版本不匹配。' + #13#10 +
                  '需要：{#RequiredModelSet}' + #13#10 +
                  '实际：' + Trim(String(ModelSet)) + #13#10 +
                  '请安装本次发布的完整版安装包以更新模型。';
        Exit;
      end;
    end;
  end;
  if not FileExists(ExpandConstant('{app}\models\streaming-asr\sherpa-onnx-x-asr-480ms-streaming-zipformer-transducer-zh-en-punct-int8-2026-06-05\encoder.int8.onnx')) then
  begin
    Result := '已安装目录中缺少流式 ASR 模型。请先运行完整版安装包修复。';
    Exit;
  end;
  if not FileExists(ExpandConstant('{app}\models\offline-asr\sense-voice\model.int8.onnx')) then
  begin
    Result := '已安装目录中缺少复核 ASR 模型。请先运行完整版安装包修复。';
    Exit;
  end;
  if not FileExists(ExpandConstant('{app}\models\llm\Qwen3.5-2B-Q4_K_M.gguf')) then
  begin
    Result := '已安装目录中缺少 LLM 模型。请先运行完整版安装包修复。';
    Exit;
  end;
  if not FileExists(ExpandConstant('{app}\models\llm-runtime\llama\llama-server.exe')) then
  begin
    Result := '已安装目录中缺少 llama.cpp 运行时。请先运行完整版安装包修复。';
    Exit;
  end;
end;
#endif

