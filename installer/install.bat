@echo off
rem ASCII only: cmd misreads UTF-8 Cyrillic in .bat files. All messages are in install.ps1.
setlocal
title KD karkas for Archicad 30 - setup

set "SRC=%~dp0"
if not exist "%SRC%setup\install.ps1" goto :broken
if not exist "%SRC%tapir-scripts\kd_plugin\kd\__main__.py" goto :broken

rem Network folder (\\server\share): install from a local copy
if not "%SRC:~0,2%"=="\\" goto :run
echo.
echo   Copying setup from network folder to %TEMP%\KD_karkas_setup ...
set "SRC=%TEMP%\KD_karkas_setup\"
if exist "%SRC%" rmdir /s /q "%SRC%"
robocopy "%~dp0." "%SRC%." /e /xd __pycache__ /nfl /ndl /njh /njs /np >nul
if not exist "%SRC%setup\install.ps1" goto :broken

:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%SRC%setup\install.ps1" %*
if errorlevel 1 echo. & echo   [!!] Setup failed. Log: %TEMP%\kd_install.log
goto :end

:broken
echo.
echo   [!!] Setup files are missing (setup\install.ps1, tapir-scripts\).
echo        Copy the whole KD_karkas_setup folder and run the .bat from it.

:end
echo.
pause
