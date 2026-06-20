; 🎫 ticketlink-bot Windows Installer (Inno Setup)
; 빌드 방법: iscc build/installer.iss
; Inno Setup 다운로드: https://jrsoftware.org/isdl.php

#define MyAppName "ticketlink-bot"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "ticketlink-bot"
#define MyAppURL "https://github.com/taehwan/ticketlink-bot"
#define MyAppExeName "ticketlink-bot.exe"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=..\dist
OutputBaseFilename=ticketlink-bot-setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
DisableProgramGroupPage=yes
DisableDirPage=no
UninstallDisplayIcon={app}\{#MyAppExeName}
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: desktopicon; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "바로가기:"; Flags: checkedonce

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}"; Permissions: users-modify

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} 설정 가이드"; Filename: "{app}\README.md"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent unchecked

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    MsgBox(
      '🎫 ticketlink-bot 설치 완료!' + #13#10 +
      #13#10 +
      '📌 선택 설치:' + #13#10 +
      '  1. Tesseract OCR (선택, 캡차 해결용)' + #13#10 +
      '     https://github.com/UB-Mannheim/tesseract/wiki' + #13#10 +
      #13#10 +
      '▶️ 사용법:' + #13#10 +
      '  ticketlink-bot            (GUI 실행)' + #13#10 +
      '  ticketlink-bot --standalone (CLI 독립형)',
      mbInformation, MB_OK
    );
  end;
end;
