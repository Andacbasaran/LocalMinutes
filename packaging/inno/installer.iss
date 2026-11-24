; LocalMinutes — Inno Setup 6 Windows Installer & Optional Clean-Uninstall Script (v1.0.0)
; Packages PyInstaller --onedir output (dist\LocalMinutes\*) into a clean Windows x64 installer.
;
; Build commands:
;   python scripts/build_exe.py --skip-zip
;   iscc /DMyAppVersion=1.0.0 packaging\inno\installer.iss

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "LocalMinutes"
#define MyAppPublisher "Andac Basaran"
#define MyAppURL "https://localminutes.andacbasaran.com"
#define MyAppRepo "https://github.com/Andacbasaran/LocalMinutes"
#define MyAppExeName "LocalMinutes.exe"

[Setup]
AppId={{6D41B8C2-9A7E-4F12-B35C-8E2D74A19F03}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppRepo}/issues
AppUpdatesURL={#MyAppRepo}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=LocalMinutes-Setup-v{#MyAppVersion}-Windows-x64
SetupIconFile=..\..\assets\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
DisableProgramGroupPage=yes
CloseApplications=force
RestartApplications=yes
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} — 100% Offline, Bot-Free Live Meeting & Lecture Transcription Studio
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\LocalMinutes\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#MyAppExeName}"; Flags: nowait skipifnotsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDataDir: String;
  PromptText: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    AppDataDir := ExpandConstant('{userappdata}\LocalMinutes');
    if not UninstallSilent and DirExists(AppDataDir) then
    begin
      if ActiveLanguage = 'turkish' then
        PromptText := 'LocalMinutes toplantı arşivinizi, SQLite veritabanınızı, ayarlarınızı ve önbelleğe alınmış Whisper modellerini de (' + AppDataDir + ') silmek istiyor musunuz?'
      else
        PromptText := 'Do you also want to remove your LocalMinutes meeting archive, SQLite database, settings, and cached Whisper models (' + AppDataDir + ')?';

      if MsgBox(PromptText, mbConfirmation, MB_YESNO) = IDYES then
      begin
        DelTree(AppDataDir, True, True, True);
      end;
    end;
  end;
end;
