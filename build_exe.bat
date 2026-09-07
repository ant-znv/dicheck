@echo off
setlocal
cd /d "%~dp0"

REM --- 1. Frontend build ---
echo [DI_Check] Sborka frontend...
pushd frontend
call npm run build
if errorlevel 1 (
    echo [DI_Check] Oshibka sborki frontend.
    popd
    pause
    exit /b 1
)
popd

REM --- 2. PyInstaller in venv ---
if not exist ".venv\Lib\site-packages\PyInstaller" (
    echo [DI_Check] Ustanovka PyInstaller v venv...
    .venv\Scripts\python.exe -m pip install pyinstaller
    if errorlevel 1 (
        echo [DI_Check] Oshibka ustanovki PyInstaller.
        pause
        exit /b 1
    )
)

REM --- 3. Exe build (onedir) ---
echo [DI_Check] Sborka exe (eto zaymet paru minut)...
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean DI_Check.spec
if errorlevel 1 (
    echo [DI_Check] Oshibka sborki exe.
    pause
    exit /b 1
)

REM --- 4. README + zip ---
copy /y README.md dist\DI_Check\README.md >nul
echo [DI_Check] Upakovka v DI_Check_portable.zip...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\DI_Check\*' -DestinationPath 'DI_Check_portable.zip' -Force"
if errorlevel 1 (
    echo [DI_Check] Oshibka upakovki zip.
    pause
    exit /b 1
)

echo.
echo [DI_Check] Gotovo:
echo   Papka:        dist\DI_Check\  (zapustit DI_Check.exe)
echo   Arhiv:        DI_Check_portable.zip  (rasprostranenie)
endlocal
