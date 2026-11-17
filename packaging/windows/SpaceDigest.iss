; Установщик Space Digest для Windows (Inno Setup 6).
; Сборка: iscc /DAppVersion=4.1.0 packaging\windows\SpaceDigest.iss
; Перед этим — PyInstaller (папка dist\SpaceDigest).

#ifndef AppVersion
  #define AppVersion "4.1.0"
#endif
#define AppName "Space Digest"
#define AppExe  "SpaceDigest.exe"

[Setup]
AppId={{8F2B6C1E-5D7A-4B8E-9C3F-2A1D6E7B9C40}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Space Digest
; Установка без прав администратора — в папку пользователя
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist
OutputBaseFilename=SpaceDigest-Setup-{#AppVersion}
SetupIconFile=..\icons\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\SpaceDigest\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; Данные пользователя (%APPDATA%\SpaceDigest) при удалении НЕ стираются —
; при переустановке/обновлении всё сохранится.
