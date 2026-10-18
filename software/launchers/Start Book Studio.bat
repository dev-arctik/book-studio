@echo off
rem Start Book Studio.bat - Book Studio launcher for Windows (double-click).
rem First start: downloads uv (the installer tool), which installs Python and the exact locked packages into .\runtime -
rem nothing is installed system-wide. Every start: applies a downloaded update if one is waiting, checks packages, opens the window.
rem Options: --apply-update (used by the app itself)   --setup-only (install everything, don't open the window)

setlocal
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
set "APP=%HERE%\app"
set "RUNTIME=%HERE%\runtime"
set "UV_VERSION=0.13.1"
set "UV_CACHE_DIR=%RUNTIME%\uv-cache"
set "UV_PYTHON_INSTALL_DIR=%RUNTIME%\python"
set "UV_PROJECT_ENVIRONMENT=%RUNTIME%\venv"
set "UV_PYTHON_PREFERENCE=only-managed"
if not exist "%RUNTIME%" mkdir "%RUNTIME%"

rem A finished update download waits in runtime\update\app: swap it in now that the window is closed
if /i "%~1"=="--apply-update" (
  timeout /t 3 /nobreak >nul
  if exist "%RUNTIME%\update\app\book_studio\__init__.py" (
    if exist "%RUNTIME%\app.old" rmdir /s /q "%RUNTIME%\app.old"
    move "%APP%" "%RUNTIME%\app.old" >nul
    move "%RUNTIME%\update\app" "%APP%" >nul
    rmdir /s /q "%RUNTIME%\update"
    rmdir /s /q "%RUNTIME%\app.old"
  )
)

if not exist "%RUNTIME%\uv\uv.exe" (
  echo.
  echo   Book Studio - first-time setup
  echo   This needs the internet once and takes about 5-10 minutes. Please leave this window open.
  echo.
  echo   Step 1 of 2: downloading the installer tool...
  set "TARGET=x86_64-pc-windows-msvc"
  if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "TARGET=aarch64-pc-windows-msvc"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol='Tls12'; $t=$env:TARGET; Invoke-WebRequest -UseBasicParsing -Uri ('https://github.com/astral-sh/uv/releases/download/' + $env:UV_VERSION + '/uv-' + $t + '.zip') -OutFile ($env:RUNTIME + '\uv.zip'); Expand-Archive -Force ($env:RUNTIME + '\uv.zip') ($env:RUNTIME + '\uv'); Remove-Item ($env:RUNTIME + '\uv.zip')"
  if errorlevel 1 goto failed
  echo   Step 2 of 2: installing Book Studio's parts ^(about 500 MB^)...
)

rem Installs exactly what uv.lock lists; when nothing changed this takes a moment and needs no internet
"%RUNTIME%\uv\uv.exe" sync --frozen --project "%APP%"
if errorlevel 1 goto failed

if /i "%~1"=="--setup-only" (
  echo   Book Studio is installed.
  exit /b 0
)

rem pythonw: the window opens without a black console window behind it
start "" /D "%APP%" "%RUNTIME%\venv\Scripts\pythonw.exe" -m book_studio
exit /b 0

:failed
echo.
echo   Setup could not finish. Check the internet connection and double-click "Start Book Studio" again.
echo   (Everything already downloaded is kept.)
pause
exit /b 1
