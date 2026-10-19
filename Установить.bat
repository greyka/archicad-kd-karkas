@echo off
rem ASCII only: cmd misreads UTF-8 Cyrillic in .bat files. All messages are in _setup\install.ps1.
setlocal
title Archicad plugins - setup

set "SRC=%~dp0"
if not exist "%SRC%_setup\install.ps1" goto :broken
if not exist "%SRC%tapir-scripts\kd_plugin\kd\__main__.py" goto :broken

rem Network folder (\server\share): install from a local copy
if not "%SRC:~0,2%"=="\\" goto :run
echo.
echo   Copying setup from network folder to %TEMP%\ArchicadPlugins_setup ...
set "SRC=%TEMP%\ArchicadPlugins_setup\"
if exist "%SRC%" rmdir /s /q "%SRC%"
robocopy "%~dp0." "%SRC%." /e /xd .git __pycache__ /nfl /ndl /njh /njs /np >nul
if not exist "%SRC%_setup\install.ps1" goto :broken

:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%SRC%_setup\install.ps1" %*
if errorlevel 1 echo. & echo   [!!] Setup failed. Log: %TEMP%\archicad_plugins_install.log
goto :end

:broken
echo.
echo   [!!] Setup files are missing (_setup\install.ps1, tapir-scripts\).
echo        Copy the whole plugins folder and run the .bat from it.

:end
echo.
pause
