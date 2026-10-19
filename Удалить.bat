@echo off
rem ASCII only. Remove Archicad plugins: Tapir palette folder, shortcuts, C:\ArchicadPlugins (settings.ini is kept).
setlocal
title Archicad plugins - uninstall
set "UV=uv"
where uv >nul 2>nul || if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe" set "UV=%LOCALAPPDATA%\Microsoft\WinGet\Links\uv.exe"
if exist "%LOCALAPPDATA%\Programs\uv\uv.exe" set "UV=%LOCALAPPDATA%\Programs\uv\uv.exe"
for %%R in ("C:\ArchicadPlugins" "%LOCALAPPDATA%\ArchicadPlugins") do (
  if exist "%%~R\_setup\archicad_setup.py" (
    "%UV%" run --quiet --script "%%~R\_setup\archicad_setup.py" --root "%%~R" --uninstall
    for /d %%D in ("%%~R\*") do rmdir /s /q "%%~D"
    for %%F in ("%%~R\*") do if /i not "%%~nxF"=="settings.ini" del /q "%%~F"
    echo   Removed: %%~R  ^(settings.ini kept^)
  )
)
echo.
echo   Tapir and uv are kept.
pause
