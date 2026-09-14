; Inno Setup definition for the TALOS Windows build.
; Run from the repository root after PyInstaller:
;   iscc /DMyAppVersion=2.2.0 packaging\windows-installer.iss
; The GitHub release workflow performs this step for every v* tag.

#define MyAppName "TALOS"
#define MyAppPublisher "TALOS"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif
#define MyAppExeName "talos.exe"
; SourcePath makes this work whether ISCC is launched from the repository root,
; a CI shell, or the Inno Setup GUI. These are compiler-time paths, not paths
; written into the installed application.
#ifndef MyAppRoot
  #define MyAppRoot SourcePath + "\..\dist\talos"
#endif
#ifndef MyIconFile
  #define MyIconFile SourcePath + "\..\assets\favicon.ico"
#endif
#ifndef MyLicenseFile
  #define MyLicenseFile SourcePath + "\..\LICENSE"
#endif
#ifndef MyOutputDir
  #define MyOutputDir SourcePath + "\..\dist\installer"
#endif

[Setup]
AppId={{B6F2E5A1-4C0D-4E7A-9C3F-1D2E8A7B5C11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/Mylittlestories/talos
AppSupportURL=https://github.com/Mylittlestories/talos/issues
AppUpdatesURL=https://github.com/Mylittlestories/talos/releases
; A per-user install avoids UAC and works on managed PCs. The portable ZIP
; remains available for users who do not want an installer at all.
DefaultDirName={localappdata}\Programs\TALOS
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#MyOutputDir}
OutputBaseFilename=TALOS-Setup-{#MyAppVersion}-x64
SetupIconFile={#MyIconFile}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile={#MyLicenseFile}
PrivilegesRequired=lowest
ChangesAssociations=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "fileassoc"; Description: "Open .pgn files with TALOS"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#MyAppRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Per-user association: compatible with the non-elevated installer and cleanly
; removed at uninstall rather than writing machine-wide registry keys.
Root: HKCU; Subkey: "Software\Classes\.pgn\OpenWithProgids"; ValueType: string; ValueName: "TALOS.pgn"; ValueData: ""; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\TALOS.pgn"; ValueType: string; ValueData: "TALOS PGN game"; Flags: uninsdeletekey; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\TALOS.pgn\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: fileassoc

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch TALOS"; Flags: nowait postinstall skipifsilent
