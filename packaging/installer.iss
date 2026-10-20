; 本地语音输入 LocalVoiceInput - Inno Setup 安装脚本
; 生成: LocalVoiceInput-Setup-x64.exe
; 采用 per-user 安装（无需管理员权限），用户数据与安装目录分离。

#define MyAppName "本地语音输入"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "LocalVoiceInput"
#define MyAppExeName "LocalVoiceInput.exe"
#define MyAppId "{{8E0C6B2A-5C4B-4F8E-9D2A-7B1C3D4E5F60}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://example.invalid/localvoiceinput
DefaultDirName={localappdata}\Programs\LocalVoiceInput
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=LocalVoiceInput-Setup-x64
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
Source: "..\build\pkg\LocalVoiceInput\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

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
