; BeCode Installer Script for Inno Setup
; https://jrsoftware.org/isinfo.php

; ╔══════════════════════════════════════════════════╗
; ║  Learned Workspace Facts                        ║
; ║  - [Languages] 节配置了三语言：chinesesimp      ║
; ║    （默认，排在首位）、chinesetrad（繁体中文）、 ║
; ║    english（英文）。Inno Setup 会使用第一个      ║
; ║    语言作为安装向导的默认显示语言。              ║
; ╚══════════════════════════════════════════════════╝

#define MyAppName "BeCode"
; 版本号由 build_installer.bat 通过 ISCC /d 命令行传入（从项目根目录 version 文件读取）
; 手动编译时请指定：ISCC /dMyAppVersion=X.Y.Z installer\becode_setup.iss
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
  #pragma message "Warning: MyAppVersion 未通过命令行定义，使用占位 0.0.0"
#endif
#define MyAppPublisher "Because66666(Individual Developer)"
#define MyAppURL "https://github.com/Because66666/BeCode"
#define MyAppExeName "becode.exe"

[Setup]
AppId={{B3E8F1A2-4D5C-4E7F-9A0B-1C2D3E4F5G6H}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=
OutputDir=..\dist
OutputBaseFilename=BeCode_Setup_v{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
DisableProgramGroupPage=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "chinesetrad"; MessagesFile: "compiler:Languages\ChineseTraditional.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: checkedonce

[Files]
Source: "..\dist\becode\becode.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\becode\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
; NOTE: Don't use "Flags: ignoreversion" on any shared system files

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Optional: run after install
Filename: "{app}\{#MyAppExeName}"; Description: "运行 {#MyAppName}"; Flags: postinstall nowait skipifsilent shellexec

[Registry]
; Add installation directory to system PATH (permanent, machine-wide)
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: expandsz; ValueName: "PATH"; \
    ValueData: "{olddata};{app}"; \
    Check: NeedsAddPath('{app}')

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKLM, 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'PATH', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  { Look for the path with a leading and trailing semicolon to avoid partial matches }
  Result := Pos(';' + Param + ';', ';' + OrigPath + ';') = 0;
end;
