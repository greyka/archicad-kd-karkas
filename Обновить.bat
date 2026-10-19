@echo off
rem ASCII only (cmd misreads UTF-8 Cyrillic). Update Archicad plugins from GitHub.
setlocal
set "ROOT=%~dp0"
set "UV=uv"
where uv >nul 2>nul || if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe" set "UV=%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe"
if exist "%LOCALAPPDATA%\Programs\uv\uv.exe" set "UV=%LOCALAPPDATA%\Programs\uv\uv.exe"
"%UV%" run --quiet --script "%ROOT%_setup\update.py" --root "%ROOT:~0,-1%" %*
if errorlevel 1 echo. & echo   [!!] Update failed. Run the setup .bat first. & pause
