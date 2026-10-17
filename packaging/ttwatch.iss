; Per-user installer for ttwatch (Inno Setup 6). The release zip stays the channel the in-app updater uses;
; this installer only gives people a normal install: Start Menu entry, uninstall entry, a fixed folder.
#ifndef MyAppVersion
  #error Pass the version: ISCC /DMyAppVersion=1.2.3 ttwatch.iss
#endif

[Setup]
; Never change AppId: Windows and the next installer recognise an existing install by it.
AppId={{48F3A59C-4F54-46F3-95DA-C3C43E3A4F25}
AppName=ttwatch
AppVersion={#MyAppVersion}
AppPublisher=huuhungn
AppPublisherURL=https://github.com/huuhungn/ttwatch
AppSupportURL=https://github.com/huuhungn/ttwatch/issues
; A folder the user can write to, so the in-app self-update can replace the program files without admin rights.
DefaultDirName={localappdata}\Programs\ttwatch
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=ttwatch-v{#MyAppVersion}-Setup
SetupIconFile=app.ico
UninstallDisplayIcon={app}\ttwatch.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes
UsePreviousTasks=yes

[Tasks]
Name: "desktopicon"; Description: "Tạo biểu tượng ngoài Desktop"; GroupDescription: "Biểu tượng bổ sung:"; Flags: unchecked

; The runtime is replaced as a whole: a leftover .dll/.pyd of another version stops the app from starting.
; Only _internal is cleared. The data folder TheoDoiKenhTiktok_data sits next to the exe and is never listed here.
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\ttwatch\*"; DestDir: "{app}"; Excludes: "LICENSE"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\ttwatch"; Filename: "{app}\ttwatch.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\ttwatch"; Filename: "{app}\ttwatch.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; Creates nothing; removes the "Start with Windows" entry of the app when ttwatch is uninstalled.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "ttwatch"; ValueType: none; Flags: dontcreatekey uninsdeletevalue

; The self-update leaves files Setup never installed; remove the runtime and update leftovers, never the data folder.
[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\.update"

[Run]
Filename: "{app}\ttwatch.exe"; Description: "Chạy ttwatch ngay"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
// Ask a running ttwatch (a tray app without a window) to quit so its files can be replaced or removed.
// It listens on one of the ports 8765-8774.
// shortcut: this also stops a portable copy running from another folder; fine, the tool is a single-user app.
procedure StopRunningApp();
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -Command "foreach ($p in 8765..8774) { try { Invoke-RestMethod -Method Post -Uri (''http://127.0.0.1:'' + $p + ''/api/shutdown'') -TimeoutSec 2 | Out-Null } catch {} }; Start-Sleep -Seconds 3"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then StopRunningApp();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then StopRunningApp();
end;
