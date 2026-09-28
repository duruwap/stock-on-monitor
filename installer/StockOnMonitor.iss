; ─────────────────────────────────────────────────────────────────────────────
; StockOnMonitor 설치 프로그램 (Inno Setup 6.3 이상)
;
; 직접 컴파일하지 말고 packaging\build.ps1 을 사용하세요.
; build.ps1 이 src\stockonmonitor\meta.py 의 값을 /D 인자로 넘겨 줍니다.
;
; 주요 동작
;  - 기본은 관리자 권한 없이 사용자 계정에 설치 (%LOCALAPPDATA%\Programs\StockOnMonitor)
;    → 회사 PC처럼 관리자 권한이 없는 환경에서도 설치 가능. 필요하면 "모든 사용자" 설치도 선택 가능
;  - 첫 설치 때 데이터(설정·종목) 저장 위치를 고르고, 폴더를 미리 만든다
;  - 업그레이드 시 실행 중인 앱을 안전하게 종료하고, 데이터 위치는 그대로 유지한다
;  - 제거 시 데이터를 지울지 물어본다 (자동 제거/무인 제거에서는 데이터 보존)
;
; 무인 설치 예:  StockOnMonitor-Setup-2.0.0.exe /VERYSILENT /DATADIR="D:\Data\StockOnMonitor"
;               /TASKS="desktopicon,autostart"   (기본값: 두 작업 모두 선택)
; ─────────────────────────────────────────────────────────────────────────────

#ifndef AppVersion
  #error "packaging\build.ps1 로 빌드하세요 (AppVersion 정의 필요)"
#endif
#ifndef AppURL
  #define AppURL ""
#endif
#ifndef SupportURL
  #define SupportURL ""
#endif
#ifndef SourceDir
  #define SourceDir "..\build\dist\StockOnMonitor"
#endif
#ifndef OutputDir
  #define OutputDir "..\build\installer"
#endif

[Setup]
AppId={#StringChange(AppId, "{", "{{")}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppCopyright={#AppCopyright}
#if AppURL != ""
AppPublisherURL={#AppURL}
AppUpdatesURL={#AppURL}
#endif
#if SupportURL != ""
AppSupportURL={#SupportURL}
#endif
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup

DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
DisableReadyPage=no
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}

PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
UsedUserAreasWarning=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

SetupMutex={#AppIdName}SetupMutex,Global\{#AppIdName}SetupMutex
; 실행 중인 앱 종료는 아래 [Code]에서 직접 처리 (뮤텍스 기반, 무인 업데이트 대응)
CloseApplications=no
RestartApplications=no

OutputDir={#OutputDir}
OutputBaseFilename={#AppIdName}-Setup-{#AppVersion}
SetupIconFile=..\assets\app.ico
WizardStyle=modern
WizardSizePercent=100
WizardSmallImageFile=..\assets\wizard-small.bmp,..\assets\wizard-small-200.bmp
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

#ifdef SignTool
SignTool={#SignTool}
SignedUninstaller=yes
#endif

[Languages]
#ifexist "compiler:Languages\Korean.isl"
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
#ifexist "compiler:Languages\Korean.isl"
korean.TaskAutostart=Windows 시작 시 자동 실행
korean.TaskGroupOptions=추가 옵션:
korean.DataDirCaption=데이터 저장 위치
korean.DataDirDescription=설정과 종목 정보를 어디에 저장할까요?
korean.DataDirSubCaption=설정·종목 목록·자동 백업·로그가 이 폴더에 저장됩니다. 다른 PC로 옮길 때는 이 폴더를 복사하면 됩니다.%n%n기본 위치를 그대로 사용하는 것을 권장합니다.
korean.DataDirInvalid=이 폴더를 만들 수 없습니다. 다른 위치를 선택해 주세요.
korean.AppRunning={#AppName}이(가) 실행 중입니다.%n%n[예]를 누르면 프로그램을 종료하고 계속합니다.
korean.AppStillRunning={#AppName}을(를) 종료하지 못했습니다. 작업 표시줄 오른쪽 아래 아이콘에서 직접 종료한 뒤 다시 시도해 주세요.
korean.RemoveData=설정과 종목 정보도 삭제할까요?%n%n%1%n%n[아니요]를 누르면 데이터를 남겨 두며, 다시 설치하면 그대로 이어서 사용할 수 있습니다.
#endif
english.TaskAutostart=Start automatically when Windows starts
english.TaskGroupOptions=Additional options:
english.DataDirCaption=Data location
english.DataDirDescription=Where should settings and holdings be stored?
english.DataDirSubCaption=Settings, holdings, automatic backups and logs are stored in this folder. Copy it to move to another PC.%n%nThe default location is recommended.
english.DataDirInvalid=This folder cannot be created. Please choose another location.
english.AppRunning={#AppName} is running.%n%nClick Yes to close it and continue.
english.AppStillRunning={#AppName} could not be closed. Please exit it from the tray icon and try again.
english.RemoveData=Also delete your settings and holdings?%n%n%1%n%nChoose No to keep them for a future reinstall.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:TaskGroupOptions}"
Name: "autostart"; Description: "{cm:TaskAutostart}"; GroupDescription: "{cm:TaskGroupOptions}"

[InstallDelete]
; 업그레이드 시 이전 버전의 라이브러리가 섞이지 않도록 먼저 비운다 (사용자 데이터는 다른 폴더라 안전)
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{code:GetDataDir}"; Flags: uninsneveruninstall
Name: "{code:GetDataDir}\backups"; Flags: uninsneveruninstall
Name: "{code:GetDataDir}\logs"; Flags: uninsneveruninstall

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; AppUserModelID: "{#AppUserModelId}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; AppUserModelID: "{#AppUserModelId}"; Tasks: desktopicon

[Registry]
; 앱이 데이터 폴더 위치를 읽는 곳
Root: HKCU; Subkey: "{#RegistryKey}"; ValueType: string; ValueName: "{#DataDirValue}"; ValueData: "{code:GetDataDir}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "{#RegistryKey}"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"
; 자동 실행 (설치 작업에서 선택한 경우). 앱 설정에서 켠 경우도 제거 시 함께 정리된다
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppIdName}"; ValueData: """{app}\{#AppExeName}"" --autostart"; Tasks: autostart; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "{#AppIdName}"; Flags: uninsdeletevalue

[Run]
; 일반 설치: 마지막 화면의 "실행" 체크박스
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; 자동 업데이트(무인 설치): 설치가 끝나면 바로 다시 실행
Filename: "{app}\{#AppExeName}"; Flags: nowait skipifnotsilent

[Code]
var
  DataDirPage: TInputDirWizardPage;
  UninstallDataDir: String;

function ExistingDataDir(): String;
begin
  Result := '';
  RegQueryStringValue(HKCU, '{#RegistryKey}', '{#DataDirValue}', Result);
end;

function DefaultDataDir(): String;
begin
  Result := ExistingDataDir();
  if Result = '' then
    Result := ExpandConstant('{userappdata}\{#AppIdName}');
  Result := ExpandConstant('{param:DATADIR|' + Result + '}');
end;

function GetDataDir(Param: String): String;
begin
  if DataDirPage <> nil then
    Result := DataDirPage.Values[0]
  else
    Result := DefaultDataDir();
end;

{ ── 실행 중인 앱 종료 ───────────────────────────────────────── }
function AppIsRunning(): Boolean;
begin
  Result := CheckForMutexes('{#AppMutex},Global\{#AppMutex}');
end;

function WaitForExit(TimeoutMs: Integer): Boolean;
var
  Waited: Integer;
begin
  Waited := 0;
  while AppIsRunning() and (Waited < TimeoutMs) do
  begin
    Sleep(250);
    Waited := Waited + 250;
  end;
  Result := not AppIsRunning();
end;

procedure ForceClose();
var
  Code: Integer;
begin
  { 현재 사용자의 프로세스만 종료 }
  Exec(ExpandConstant('{sys}\taskkill.exe'),
       '/F /IM "{#AppExeName}" /FI "USERNAME eq ' + GetUserNameString() + '"',
       '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

{ 앱을 종료시킨다. Silent=True(자동 업데이트)면 묻지 않는다. 성공하면 True }
function EnsureAppClosed(Silent: Boolean): Boolean;
begin
  { 자동 업데이트는 앱이 스스로 종료하는 중이므로 잠시 기다린다 }
  if WaitForExit(3000) then
  begin
    Result := True;
    exit;
  end;
  if not Silent then
    if MsgBox(CustomMessage('AppRunning'), mbConfirmation, MB_YESNO) <> IDYES then
    begin
      Result := False;
      exit;
    end;
  ForceClose();
  Result := WaitForExit(8000);
end;

{ ── 설치 ────────────────────────────────────────────────────── }
procedure InitializeWizard();
begin
  DataDirPage := CreateInputDirPage(wpSelectDir,
    CustomMessage('DataDirCaption'), CustomMessage('DataDirDescription'),
    CustomMessage('DataDirSubCaption'), False, '');
  DataDirPage.Add('');
  DataDirPage.Values[0] := DefaultDataDir();
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { 업그레이드이거나 명령줄에서 지정한 경우에는 데이터 위치를 다시 묻지 않는다 }
  Result := (DataDirPage <> nil) and (PageID = DataDirPage.ID) and
            ((ExistingDataDir() <> '') or (ExpandConstant('{param:DATADIR|}') <> ''));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (DataDirPage <> nil) and (CurPageID = DataDirPage.ID) then
    if not ForceDirectories(DataDirPage.Values[0]) then
    begin
      MsgBox(CustomMessage('DataDirInvalid'), mbError, MB_OK);
      Result := False;
    end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if AppIsRunning() and not EnsureAppClosed(WizardSilent()) then
    Result := CustomMessage('AppStillRunning');
end;

{ ── 제거 ────────────────────────────────────────────────────── }
function InitializeUninstall(): Boolean;
begin
  Result := True;
  UninstallDataDir := ExistingDataDir();  { 레지스트리가 지워지기 전에 기억 }
  if AppIsRunning() and not EnsureAppClosed(UninstallSilent()) then
  begin
    MsgBox(CustomMessage('AppStillRunning'), mbError, MB_OK);
    Result := False;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent()) and
     (UninstallDataDir <> '') and DirExists(UninstallDataDir) then
    if MsgBox(FmtMessage(CustomMessage('RemoveData'), [UninstallDataDir]), mbConfirmation, MB_YESNO) = IDYES then
      DelTree(UninstallDataDir, True, True, True);
end;
