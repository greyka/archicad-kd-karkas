# Сборка «Менеджер плагинов Archicad.exe» в корень папки плагинов (csc из .NET Framework 4.x).
# Запуск: powershell -ExecutionPolicy Bypass -File _setup\manager\build.ps1
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$out = Join-Path (Split-Path -Parent (Split-Path -Parent $here)) 'Менеджер плагинов Archicad.exe'
& $csc /nologo /codepage:65001 /target:winexe /optimize+ "/win32icon:$here\icon.ico" "/out:$out" `
    /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.Web.Extensions.dll /r:System.Core.dll "$here\Manager.cs"
if ($LASTEXITCODE -ne 0) { throw "csc: ошибка сборки ($LASTEXITCODE)" }
Write-Host "Собрано: $out"
