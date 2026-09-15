; 心电HRV采集分析 —— Windows 安装包脚本（Inno Setup 6）
; 由 GitHub Actions 云端构建时执行:
;   ISCC /DMyVersion=x.y.z packaging\installer.iss
; 本地（如需）: 安装 Inno Setup 后在 host_app 目录执行同样命令。

#ifndef MyVersion
#define MyVersion "1.0.0"
#endif

#define MyAppName "心电HRV采集分析"
#define MyAppNameEn "HeartHRV"
#define MyAppPublisher "HeartHRV"
#define MyAppExeName "HeartHRV.exe"

[Setup]
AppId={{8E7B6C1A-52D4-4B7E-9C3F-00A1B2C3D4E5}
AppName={#MyAppName}
AppVersion={#MyVersion}
AppVerName={#MyAppName} {#MyVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppNameEn}
DefaultGroupName={#MyAppName}
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
; 许可协议页（安装向导第二步"我接受"）
LicenseFile=EULA.txt
OutputDir=..\dist
OutputBaseFilename=心电HRV采集分析_安装包_v{#MyVersion}
SetupIconFile=app_icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
; 卸载时询问是否保留用户数据（文档\心电HRV数据）
Uninstallable=yes

[Languages]
Name: "chs"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; OnlyBelowVersion: 6.1; Check: not IsAdminInstallMode

[Files]
Source: "..\dist\HeartHRV\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 只清理程序目录；用户数据在"文档\心电HRV数据"，卸载不影响
Type: filesandordirs; Name: "{app}"
