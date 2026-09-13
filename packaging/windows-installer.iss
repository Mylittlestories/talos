; Inno Setup script for the TALOS Windows build.
;   iscc packaging\windows-installer.iss
; Run from the repository root after: pyinstaller packaging\talos.spec

#define MyAppName "TALOS"
#define MyAppPublisher "TALOS"
#define MyAppVersion GetFileVersion("dist\talos\talos.exe")
#define MyAppExeName "talos.exe"
#define MyAppRoot "dist\talos"

[Setup]
AppId={{B6F2E5A1-4C0D-4E7A-9C3F-1D2E8A7B5C11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/USERNAME/TALOS
AppSupportURL=https://github.com/USERNAME/TALOS/issues
AppUpdatesURL=https://github.com/USERNAME/TALOS/releases
DefaultDirName={autopf}\TALOS
DefaultGroupName={#MyAppName}
OutputDir=dist\installer
OutputBaseFilename=TALOS-Setup
SetupIconFile=assets\favicon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=LICENSE
PrivilegesRequiredOverridesAllowed=dialog

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "fileassoc";   Description: "Open .pgn files with TALOS"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#MyAppRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCR; Subkey: ".pgn\OpenWithProgids"; ValueType: string; ValueName: "TALOS.pgn"; ValueData: ""; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCR; Subkey: "TALOS.pgn\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: fileassoc

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch TALOS"; Flags: nowait postinstall skipifsilent
