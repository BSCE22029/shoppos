@echo off
rem ============================================================================
rem  Builds the Windows application (dist\ShopPOS\ShopPOS.exe)
rem  and the installer (dist\ShopPOS-Setup.exe).
rem  Needs: Python 3.10+ (python.org) with Tcl/Tk. Nothing else - PyInstaller is
rem  installed automatically into an isolated .venv-build folder.
rem  END USERS DO NOT NEED PYTHON: the exe is self-contained.
rem ============================================================================
setlocal
cd /d "%~dp0"

if not exist ".venv-build\Scripts\python.exe" (
    echo Creating build environment...
    python -m venv .venv-build || goto :fail
)
".venv-build\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check pyinstaller || goto :fail

echo Drawing icon...
".venv-build\Scripts\python.exe" tools\make_icon.py || goto :fail

echo Building application (this takes a minute)...
".venv-build\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed ^
    --name ShopPOS --icon assets\app.ico --add-data "assets;assets" ^
    --exclude-module numpy --exclude-module pandas --exclude-module matplotlib ^
    main.py || goto :fail

echo Verifying the packaged build (self-test)...
start "" /wait "dist\ShopPOS\ShopPOS.exe" --selftest
if errorlevel 1 goto :fail

echo Building installer...
".venv-build\Scripts\python.exe" tools\make_installer.py || goto :fail

echo.
echo DONE.
echo   Portable folder : dist\ShopPOS\   (run ShopPOS.exe)
echo   Installer       : dist\ShopPOS-Setup.exe
exit /b 0

:fail
echo.
echo BUILD FAILED - see the messages above.
exit /b 1
