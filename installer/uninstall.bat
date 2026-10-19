@echo off
rem ASCII only: cmd misreads UTF-8 Cyrillic in .bat files.
title KD karkas for Archicad 30 - uninstall
powershell -NoProfile -ExecutionPolicy Bypass -Command "$cs = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Tapir\custom-scripts'; Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $cs 'KD_Karkas_PDF.py'); Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $cs 'kd_plugin'); Write-Host ''; Write-Host '   [ OK ] Plugin removed (Tapir and uv are kept).' -ForegroundColor Green"
echo.
pause
