@echo off
rem ===========================================================================
rem  CiteDock launcher (Windows only)
rem
rem  How Python is located:
rem    1. .python-path file in this folder  (machine-local, not in version control)
rem    2. CITEDOCK_PYTHON environment variable
rem    3. pythonw.exe on PATH
rem
rem  We deliberately do NOT hardcode any absolute Python path here - that is
rem  useless to others and leaks this machine's layout.
rem
rem  This file is intentionally ASCII-only: non-ASCII text in a .bat is
rem  fragile across Windows codepages (tried UTF-8 and UTF-8-with-BOM, both
rem  produced mojibake on a Chinese-locale console).
rem ===========================================================================
setlocal
set "HERE=%~dp0"

rem ---- 1. find Python ----
set "PYW="
if exist "%HERE%.python-path" set /p PYW=<"%HERE%.python-path"
if not defined PYW if defined CITEDOCK_PYTHON set "PYW=%CITEDOCK_PYTHON%"
if not defined PYW for /f "delims=" %%P in ('where pythonw.exe 2^>nul') do if not defined PYW set "PYW=%%P"
if not defined PYW goto :no_python

rem ---- 2. can this Python actually import PySide6? ----
"%PYW%" -c "import PySide6" >nul 2>&1
if errorlevel 1 goto :no_dep

rem ---- 3. is the shared package present? ----
if not exist "%HERE%..\citedock_kit\__init__.py" goto :no_kit

rem ---- 4. launch ----
start "" "%PYW%" "%HERE%run.py"
exit /b 0


:no_python
echo [CiteDock] Python not found.
echo.
echo   Python 3.10 or newer is required. Install it, then double-click this again.
echo   You can also point the launcher at an interpreter in either of these ways:
echo     - create a .python-path file in this folder, containing the full path
echo     - set the CITEDOCK_PYTHON environment variable
echo.
pause
exit /b 1


:no_dep
echo [CiteDock] This Python is missing the PySide6 dependency.
echo.
echo   Interpreter:
echo     %PYW%
echo.
echo   Run this in a terminal to install dependencies:
echo     "%PYW%" -m pip install -r "%HERE%requirements.txt"
echo.
pause
exit /b 1


:no_kit
echo [CiteDock] Shared package "citedock_kit" not found.
echo.
echo   It must sit next to cite-dock, like this:
echo     %HERE%..\citedock_kit\
echo.
echo   If you downloaded cite-dock alone, also download citedock_kit next to it.
echo.
pause
exit /b 1
