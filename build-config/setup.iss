; SEE THE DOCUMENTATION FOR DETAILS ON CREATING INNO SETUP SCRIPT FILES!
; Note: Paths are relative to project root (one level up from build-config/)

#define MyAppName "ACIES Scheduler"
#ifndef MyAppVersion
#define MyAppVersion "0.0.7"
#endif
#define MyAppPublisher "ACIES Engineering"
#define MyAppURL "https://acies.net/"
#define MyAppExeName "ACIES Scheduler.exe"
#define MyAppAssocName MyAppName + " File"
#define MyAppAssocExt ".myp"
#define MyAppAssocKey StringChange(MyAppAssocName, " ", "") + MyAppAssocExt
#define SourcePath "..\dist\" + MyAppName

; Microsoft's WebView2 Runtime bootstrapper. build.ps1 downloads it before compiling.
; The app cannot show its window without the runtime, and a small number of Windows 10
; PCs do not have it, so Setup installs it when it is missing. Without the file the
; installer still builds but can only tell the user to install the runtime themselves.
#ifndef WebView2Bootstrapper
#define WebView2Bootstrapper "..\build\webview2\MicrosoftEdgeWebview2Setup.exe"
#endif
#ifexist WebView2Bootstrapper
#define HaveWebView2Bootstrapper
#endif

[Setup]
; NOTE: The value of AppId uniquely identifies this application. Do not use the same AppId value in installers for other applications.
; (To generate a new GUID, click Tools | Generate GUID inside the IDE.)
AppId={{C8DE22A3-3BD3-43F2-8A05-A35631A419D2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
;AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
; "ArchitecturesAllowed=x64compatible" specifies that Setup cannot run
; on anything but x64 and Windows 11 on Arm.
ArchitecturesAllowed=x64compatible
; The app's Python 3.13 runtime needs Windows 8.1 or newer and the Microsoft Edge
; WebView2 Runtime needs Windows 10 or newer. 10.0.14393 (version 1607) is the first
; Windows 10 build that includes the .NET Framework 4.6.2 the desktop window requires.
; Without this line Setup accepts Windows 7 and the app then fails to start.
MinVersion=10.0.14393
; "ArchitecturesInstallIn64BitMode=x64compatible" requests that the
; install be done in "64-bit mode" on x64 or Windows 11 on Arm,
; meaning it should use the native 64-bit Program Files directory and
; the 64-bit view of the registry.
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
DisableProgramGroupPage=yes
; Remove the following line to run in administrative install mode (install for all users).
PrivilegesRequired=lowest
OutputDir=..\dist\setup
OutputBaseFilename=acies-scheduler-setup
SetupIconFile=..\assets\acies.ico
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourcePath}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#ifdef HaveWebView2Bootstrapper
Source: "{#WebView2Bootstrapper}"; DestName: "MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy
#endif
; NOTE: Don't use "Flags: ignoreversion" on any shared system files

[Registry]
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocExt}\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppAssocKey}"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey}"; ValueType: string; ValueName: ""; ValueData: "{#MyAppAssocName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
const
  WebView2ClientKey = 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2DownloadUrl = 'https://developer.microsoft.com/microsoft-edge/webview2/';

// The runtime records its version ("pv") here. 0.0.0.0 or an empty value means it is not installed.
function WebView2VersionRecorded(RootKey: Integer): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(RootKey, WebView2ClientKey, 'pv', Version)
    and (Version <> '') and (Version <> '0.0.0.0');
end;

function WebView2RuntimeInstalled: Boolean;
begin
  // A per-user install is recorded under HKCU, a per-machine one in the 32-bit HKLM view.
  Result := WebView2VersionRecorded(HKCU) or WebView2VersionRecorded(HKLM32);
end;

procedure InstallWebView2RuntimeIfMissing;
var
  ResultCode: Integer;
begin
  if WebView2RuntimeInstalled then
    Exit;

#ifdef HaveWebView2Bootstrapper
  WizardForm.StatusLabel.Caption := 'Installing the Microsoft Edge WebView2 Runtime...';
  ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
  // Setup runs without administrator rights, so this installs the runtime for the current user.
  // The bootstrapper downloads the runtime from Microsoft, so it needs an internet connection.
  Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '',
    SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if WebView2RuntimeInstalled then
    Exit;
#endif

  SuppressibleMsgBox(
    'ACIES Scheduler was installed, but it also needs the Microsoft Edge WebView2 Runtime, ' +
    'and that could not be installed automatically (it needs an internet connection).' + #13#10#13#10 +
    'Download and install it from:' + #13#10 + WebView2DownloadUrl + #13#10#13#10 +
    'ACIES Scheduler will not open until it is installed.',
    mbError, MB_OK, IDOK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    InstallWebView2RuntimeIfMissing;
end;
