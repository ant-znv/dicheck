@echo off
setlocal
cd /d "%~dp0"

REM --- 1. Python venv ---
if not exist ".venv\Scripts\python.exe" (
    echo [DI_Check] Sozdayu virtualnoe okruzhenie...
    python -m venv .venv
    if errorlevel 1 (
        echo [DI_Check] Oshibka: ne nayden Python. Ustanovite Python 3.12+ i dobavte v PATH.
        pause
        exit /b 1
    )
)

REM --- 2. Zavisimosti backend ---
if not exist ".venv\Lib\site-packagesastapi" (
    echo [DI_Check] Ustanavlivayu zavisimosti backend...
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [DI_Check] Oshibka ustanovki zavisimostey.
        pause
        exit /b 1
    )
)

REM --- 3. Build frontend ---
if not exist "frontend\dist\index.html" (
    echo [DI_Check] Sobirayu frontend, perviy zapusk zaymet paru minut...
    pushd frontend
    call npm install
    if errorlevel 1 (
        echo [DI_Check] Oshibka: ne nayden Node.js/npm. Ustanovite Node.js 20+ i dobavte v PATH.
        popd
        pause
        exit /b 1
    )
    call npm run build
    if errorlevel 1 (
        echo [DI_Check] Oshibka sborki frontend.
        popd
        pause
        exit /b 1
    )
    popd
)

REM --- 4. Zapusk ---
echo [DI_Check] Zapuskayu server: http://127.0.0.1:8787
start "" http://127.0.0.1:8787
.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8787
if errorlevel 1 (
    echo.
    echo [DI_Check] Server zavershilsya s oshibkoy. Sm. soobschenie vyshe.
    pause
)
endlocal
