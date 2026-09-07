; Inno Setup скрипт установщика DI_Check.
; Сборка: ISCC.exe DI_Check.iss (пути/запуск — см. build_exe.bat).
; Требует предварительно собранной портативной версии в dist\DI_Check\ (build_exe.bat шаги 1-3).

#define MyAppName "DI_Check"
#define MyAppVersion "0.1.0"
#define MyAppExeName "DI_Check.exe"
#define MyAppPublisher "DI_Check"
#define MyAppURL "http://127.0.0.1:8787"

[Setup]
; фиксированный AppId — не менять, иначе обновления/удаление потеряют связь с установленной копией
AppId={{9C1F4B7E-52D4-4E9A-B6C3-71A8F2D5E013}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppSupportURL={#MyAppURL}
; установка без прав администратора: %LOCALAPPDATA%\Programs\DI_Check
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
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; \
    Flags: nowait postinstall skipifsilent
