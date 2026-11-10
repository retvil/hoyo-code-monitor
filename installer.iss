; Inno Setup script for HoYo Code Monitor
; Replaces the legacy NSIS (installer.nsi) now that the GitHub-hosted
; windows-latest runner no longer ships makensis.
;
; Version is passed from CI via -DMYAPPVERSION=<ver> and substituted below.

#define MyAppName "HoYo Code Monitor"
#define MyAppPublisher "HoYo Code Monitor Contributors"
#define MyAppURL "https://github.com/retvil/hoyo-code-monitor"
#define MyAppExeName "hoyo-code-monitor.exe"

; CI injects the real version; fall back to the last known release.
#ifndef MyAppVersion
  #define MyAppVersion "1.5.1"
#endif

[Setup]
AppId={{A1B2C3D4-5678-9E0F-1234-567890ABCDEF}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
VersionInfoVersion={#MyAppVersion}
DefaultDirName={localappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableDirPage=yes
; Per-user install, no admin rights (mirrors NSIS RequestExecutionLevel user).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..
; Emit the same artefact name as the NSIS build so the CI smoke test,
; artifact upload, and release-asset steps keep working unchanged.
OutputBaseFilename=hoyo-code-monitor-{#MyAppVersion}-setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\assets\icon.ico
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "autostart"; Description: "Launch {#MyAppName} automatically when you log in to Windows"; GroupDescription: "Startup:"

[Files]
; Ship the entire onedir PyInstaller build (mirrors NSIS File /r "dist\...").
Source: "dist\hoyo-code-monitor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs
; Branded icon referenced by the shortcuts.
Source: "assets\icon.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
; Runtime data directory so the app has somewhere to write.
Source: "config.toml"; DestDir: "{app}\data"; Flags: ignoreversion skipifsourcedoesntexist

[Dirs]
Name: "{app}\data"
Name: "{app}\logs"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "tray"; IconFilename: "{app}\assets\icon.ico"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "tray"; IconFilename: "{app}\assets\icon.ico"; Tasks: desktopicon

[Registry]
; Autostart on login (mirrors NSIS SEC_AUTOSTART; value name is "HoYoCodeMonitor"
; to stay compatible with src/autostart.py which reads the same key).
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "HoYoCodeMonitor"; ValueData: '"{app}\{#MyAppExeName}" tray'; Tasks: autostart

; Record the install location in HKCU\Software\HoYo Code Monitor so the
; NSIS-style InstallDirRegKey lookup keeps working for upgrades/reinstalls.
Root: HKA; Subkey: "Software\{#MyAppName}"; ValueType: string; ValueName: ""; ValueData: "{app}"

; Add the standard Windows uninstall entry (Add/Remove Programs) as NSIS did.
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppName}"; ValueType: string; ValueName: "DisplayName"; ValueData: "{#MyAppName} {#MyAppVersion}"
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppName}"; ValueType: string; ValueName: "UninstallString"; ValueData: """{uninstallexe}"""
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppName}"; ValueType: string; ValueName: "DisplayVersion"; ValueData: "{#MyAppVersion}"
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppName}"; ValueType: string; ValueName: "Publisher"; ValueData: "{#MyAppPublisher}"
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppName}"; ValueType: string; ValueName: "URLInfoAbout"; ValueData: "{#MyAppURL}"

[Run]
; Offer to launch the app after install (mirrors NSIS MUI_FINISHPAGE_RUN).
Filename: "{app}\{#MyAppExeName}"; Parameters: "tray"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Drop the app-local data/logs residue on uninstall.
Name: "{app}\data"
Name: "{app}\logs"
