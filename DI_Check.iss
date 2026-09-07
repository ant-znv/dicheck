; Inno Setup скрипт установщика DI_Check.
; Сборка: iscc /DMyAppVersion=X.Y.Z DI_Check.iss (локально — build_exe.bat, в CI — workflow).
; Требует предварительно собранной портативной версии в dist\DI_Check\ (build_exe.bat шаги 1-3).
; Уроки BusyBar (GIT_AUTOUPDATE_RECOMMENDATIONS.md) учтены: чистка _PYI_* в PrepareToInstall,
; taskkill без /T, [Run] с skipifnotsilent для тихого самообновления.

#define MyAppName "DI_Check"
#define MyAppExeName "DI_Check.exe"
#define MyAppPublisher "DI_Check"
; версию передаёт CI: iscc /DMyAppVersion=1.2.3
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
; VersionInfoVersion — только числа (ресурсы exe не принимают суффиксы вида -dev)
#define MyAppVersionNum Copy(MyAppVersion, 1, Pos("-", MyAppVersion + "-") - 1)

[Setup]
; фиксированный AppId — не менять, иначе обновления/удаление потеряют связь с установленной копией
AppId={{9C1F4B7E-52D4-4E9A-B6C3-71A8F2D5E013}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
VersionInfoVersion={#MyAppVersionNum}
VersionInfoCompany={#MyAppPublisher}
VersionInfoProductName={#MyAppName}
AppPublisher={#MyAppPublisher}
; установка без прав администратора: %LOCALAPPDATA%\Programs\DI_Check
; (обязательно для тихого самообновления — иначе UAC-промпт «зависнет» в фоне)
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=resources\app.ico
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
; стабильное имя файла: апдейтер ищет asset релиза по точному имени
OutputDir=dist\installer
OutputBaseFilename=DI_Check_setup
; если приложение запущено — предложить закрыть перед установкой
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; \
    GroupDescription: "Дополнительно:"

[Files]
Source: "dist\DI_Check\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon

[Run]
; обычная установка: галочка «Запустить» в финале мастера
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; \
    Flags: nowait postinstall skipifsilent
; тихое самообновление: новая версия должна перезапуститься сама
Filename: "{app}\{#MyAppExeName}"; Flags: nowait skipifnotsilent

[Code]
const
  AppExe = 'DI_Check.exe';

// Inno не умеет задавать переменные окружения — зовём kernel32 напрямую.
// lpValue=0 (NULL) удаляет переменную.
procedure SetEnvironmentVariableW(lpName: string; lpValue: Longint);
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

procedure DelEnv(const Name: string);
begin
  SetEnvironmentVariableW(Name, 0);
end;

// PyInstaller-бутлоадер помечает окружение _PYI_*/PYINSTALLER_*; если их унаследует
// запускаемый из setup exe, он падает с "Security validation failure".
// Чистим здесь, чтобы лечить обновления СО СТАРЫХ версий, где приложение
// ещё не чистит окружение само (см. updater._clean_env).
procedure CleanPyInstallerEnv();
begin
  DelEnv('_PYI_APPLICATION_HOME_DIR');
  DelEnv('_PYI_ARCHIVE_FILE');
  DelEnv('_PYI_PARENT_PROCESS_LEVEL');
  DelEnv('_PYI_ONEDIR_MODE');
  DelEnv('_PYI_SPLASH_IPC');
  DelEnv('_PYI_CONFIG_DIR');
  DelEnv('PYINSTALLER_RESET_ENVIRONMENT');
  DelEnv('PYINSTALLER_STRICT_BUNDLE_VALIDATION');
end;

// ВАЖНО: без /T — убийство дерева процессов снесёт и сам установщик
// (он запущен дочерним процессом приложения при самообновлении).
// Код 128 («процесс не найден») — норма: приложение могло быть не запущено.
procedure KillApp();
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{cmd}'), '/C taskkill /F /IM ' + AppExe, '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  CleanPyInstallerEnv();
  KillApp();
end;

function InitializeUninstall: Boolean;
begin
  KillApp();
  Result := True;  // False отменило бы удаление
end;
