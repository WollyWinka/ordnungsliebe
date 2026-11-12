; Inno-Setup-Skript für Ordnungsliebe
; Installiert ohne Administratorrechte nach %LOCALAPPDATA%\Programs\Ordnungsliebe.

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#define MyAppName "Ordnungsliebe"
#define MyAppExe "Ordnungsliebe.exe"
#define Root ".."

[Setup]
AppId={{7C1E2F3A-5B6D-4E8F-9A0B-1C2D3E4F5A6B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=Ordnungsliebe
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir={#Root}\dist
OutputBaseFilename=Ordnungsliebe-Setup
SetupIconFile={#Root}\build\icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes
ShowLanguageDialog=no

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Messages]
de.WelcomeLabel2=Ordnungsliebe sortiert deine Dokumente mit einer KI, die nur auf deinem Computer läuft.%n%nKlicke auf „Weiter“, um die Installation zu starten.

[Tasks]
Name: "desktopicon"; Description: "Ein Symbol auf dem Desktop anlegen"; GroupDescription: "Zusätzlich:"

[Files]
Source: "{#Root}\dist\Ordnungsliebe\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Root}\tools\*"; DestDir: "{app}\tools"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Root}\deps\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsWebView2

[Icons]
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Anzeige-Komponente von Windows wird eingerichtet …"; Check: NeedsWebView2; Flags: waituntilterminated
Filename: "{app}\{#MyAppExe}"; Description: "Ordnungsliebe jetzt starten"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#MyAppExe}"; Flags: nowait; Check: IsUpdate

[Code]
const
  WV2Key = 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WV2KeyWow = 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function HasWV2(Root: Integer; Key: String): Boolean;
var
  V: String;
begin
  Result := RegQueryStringValue(Root, Key, 'pv', V) and (V <> '') and (V <> '0.0.0.0');
end;

function IsUpdate: Boolean;
begin
  Result := Pos('/UPDATE', UpperCase(GetCmdTail)) > 0;
end;

function NeedsWebView2: Boolean;
begin
  Result := not (HasWV2(HKLM, WV2KeyWow) or HasWV2(HKLM, WV2Key) or HasWV2(HKCU, WV2Key));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if MsgBox('Soll auch die heruntergeladene KI (mehrere Gigabyte) samt Zwischenspeicher gelöscht werden?' + #13#10 + #13#10 +
              'Deine Dokumente und Sicherungen bleiben in jedem Fall erhalten.', mbConfirmation, MB_YESNO) = IDYES then
    begin
      DelTree(ExpandConstant('{localappdata}\Ordnungsliebe\Modelle'), True, True, True);
      DelTree(ExpandConstant('{localappdata}\Ordnungsliebe\Zwischenspeicher'), True, True, True);
      DelTree(ExpandConstant('{localappdata}\Ordnungsliebe\webview'), True, True, True);
    end;
  end;
end;
