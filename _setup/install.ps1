# Установка / обновление «Плагинов Archicad» (как «Плагины КОМПАС»).
# Запускается из «Установить.bat». Ставит/проверяет Tapir и uv, копирует плагины
# в C:\ArchicadPlugins (нельзя писать — %LOCALAPPDATA%\ArchicadPlugins), подключает
# папку к палитре Tapir, создаёт ярлыки «Менеджер плагинов Archicad» и автообновление.
param([switch]$ResetConfig)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'            # без «полосы» Invoke-WebRequest — так быстрее
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Src = Split-Path -Parent $Here                                      # папка установщика (= репозиторий)
$Log = Join-Path $env:TEMP "archicad_plugins_install.log"
$Problems = New-Object System.Collections.ArrayList
$Total = 7
try { Start-Transcript -Path $Log -Force | Out-Null } catch {}

# ------------------------------------------------------------------ вывод
function Read-Version($dir) {
    $f = Join-Path $dir "VERSION"
    if (Test-Path $f) { return (Get-Content $f -Raw).Trim() } else { return $null }
}
function Banner {
    Write-Host ""
    Write-Host "  ==================================================" -ForegroundColor DarkCyan
    Write-Host "     Плагины Archicad 30  —  установка" -ForegroundColor White
    Write-Host "     версия $(Read-Version $Src)" -ForegroundColor Gray
    Write-Host "  ==================================================" -ForegroundColor DarkCyan
}
function Step($n, $text) {
    Write-Host ""
    Write-Host ("  [{0}/{1}] " -f $n, $Total) -ForegroundColor Cyan -NoNewline
    Write-Host $text -ForegroundColor White
}
function Doing($text) { Write-Host "        ... $text" -ForegroundColor Gray }
function Ok($text)    { Write-Host "        [ OK ] " -ForegroundColor Green -NoNewline; Write-Host $text }
function Info($text)  { Write-Host "        [ -- ] $text" -ForegroundColor DarkGray }
function Bad($text)   {
    Write-Host "        [ !! ] $text" -ForegroundColor Yellow
    [void]$script:Problems.Add($text)
}

trap {
    Write-Host ""
    Write-Host "  [ОШИБКА] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  строка $($_.InvocationInfo.ScriptLineNumber): $($_.InvocationInfo.Line.Trim())" -ForegroundColor Red
    Write-Host "  Журнал: $Log" -ForegroundColor Red
    try { Stop-Transcript | Out-Null } catch {}
    exit 1
}

# файлы из сети/zip помечены «скачано из интернета» — снимаем пометку
Get-ChildItem $Src -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue

Banner

# ------------------------------------------------------------------ 1. Archicad
Step 1 "Проверяю Archicad 30"
$acDirs = @(Get-ChildItem "$env:ProgramFiles\Graphisoft" -Directory -Filter "Archicad 30*" -ErrorAction SilentlyContinue)
if ($acDirs.Count -eq 0) {
    Bad "Archicad 30 не найден в $env:ProgramFiles\Graphisoft — установите его и запустите установку снова"
} else {
    Ok "найден: $($acDirs[0].FullName)"
}
$acRunning = @(Get-Process archicad -ErrorAction SilentlyContinue).Count -gt 0
if ($acRunning) { Info "Archicad сейчас запущен — после установки его нужно перезапустить" }

# ------------------------------------------------------------------ 2. Tapir
Step 2 "Проверяю аддон Tapir (команды API и палитра скриптов)"
$tapir = $null
foreach ($d in $acDirs) {
    $tapir = Get-ChildItem $d.FullName -Recurse -Filter "TapirAddOn_AC30*.apx" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($tapir) { break }
}
if ($tapir) {
    Ok "уже установлен"
} elseif ($acDirs.Count -gt 0) {
    $addons = @("Расширения Archicad", "Add-Ons") | ForEach-Object { Join-Path $acDirs[0].FullName $_ } |
              Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $addons) {
        Bad "не найдена папка расширений Archicad — поставьте Tapir вручную: github.com/ENZYME-APD/tapir-archicad-automation/releases"
    } else {
        try {
            Doing "ищу последнюю версию на GitHub"
            $rel = Invoke-RestMethod "https://api.github.com/repos/ENZYME-APD/tapir-archicad-automation/releases/latest" -Headers @{ 'User-Agent' = 'kd-plugin-installer' }
            $asset = $rel.assets | Where-Object { $_.name -like "TapirAddOn_AC30_Win*.apx" } | Select-Object -First 1
            if (-not $asset) { throw "в релизе $($rel.tag_name) нет файла для Archicad 30" }
            $tmp = Join-Path $env:TEMP $asset.name
            Doing ("скачиваю Tapir {0} ({1} МБ)" -f $rel.tag_name, [math]::Round($asset.size / 1MB, 1))
            Invoke-WebRequest $asset.browser_download_url -OutFile $tmp -UseBasicParsing
            $target = Join-Path $addons "Tapir"
            Doing "устанавливаю в папку Archicad (Windows спросит права администратора)"
            $cmd = "New-Item -ItemType Directory -Force '$target' | Out-Null; Copy-Item -Force '$tmp' '$target'"
            Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "-NoProfile", "-Command", $cmd
            if (Test-Path (Join-Path $target $asset.name)) { Ok "Tapir $($rel.tag_name) установлен" }
            else { Bad "не удалось скопировать Tapir в $target (нет прав администратора?)" }
        } catch {
            Bad "Tapir не установлен: $($_.Exception.Message)"
        }
    }
} else {
    Info "пропущено — нет Archicad 30"
}

# ------------------------------------------------------------------ 3. uv
Step 3 "Проверяю uv (запуск Python-скриптов из палитры Tapir)"
function Find-Uv {
    $c = Get-Command uv -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    foreach ($p in @("$env:LOCALAPPDATA\Microsoft\WinGet\Links\uv.exe", "$env:USERPROFILE\.local\bin\uv.exe",
                     "$env:LOCALAPPDATA\Programs\uv\uv.exe")) {
        if (Test-Path $p) { return $p }
    }
    $w = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter uv.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($w) { return $w.FullName }
    return $null
}
$uv = Find-Uv
if ($uv) {
    Ok "уже установлен"
} else {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Doing "устанавливаю uv через winget"
        winget install --id astral-sh.uv -e --silent --accept-source-agreements --accept-package-agreements | Out-Null
    } else {
        # скачиваем архив, а не выполняем скрипт из интернета — так спокойнее для антивирусов
        Doing "скачиваю uv с GitHub (astral-sh/uv)"
        $zip = Join-Path $env:TEMP "uv.zip"
        $uvDir = Join-Path $env:LOCALAPPDATA "Programs\uv"
        Invoke-WebRequest "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" -OutFile $zip -UseBasicParsing
        New-Item -ItemType Directory -Force $uvDir | Out-Null
        Expand-Archive $zip -DestinationPath $uvDir -Force
        $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
        if ($userPath -notlike "*$uvDir*") { [Environment]::SetEnvironmentVariable('Path', "$userPath;$uvDir", 'User') }
    }
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    $uv = Find-Uv
    if ($uv) { Ok "uv установлен" } else { Bad "uv не установился — выполните вручную: winget install astral-sh.uv" }
}

# ------------------------------------------------------------------ 4. файлы
function Test-Writable($dir) {
    try {
        New-Item -ItemType Directory -Force $dir | Out-Null
        $t = Join-Path $dir ".write_test"; Set-Content $t "x"; Remove-Item $t -Force; return $true
    } catch { return $false }
}
$Root = "C:\ArchicadPlugins"
if (-not (Test-Writable $Root)) { $Root = Join-Path $env:LOCALAPPDATA "ArchicadPlugins"; New-Item -ItemType Directory -Force $Root | Out-Null }
$newV = Read-Version $Src
$oldV = Read-Version $Root
if ($oldV) { Step 4 "Обновляю плагины в $Root : $oldV -> $newV" } else { Step 4 "Устанавливаю плагины $newV в $Root" }
if ((Resolve-Path $Src).Path.TrimEnd('\') -ne (Resolve-Path $Root).Path.TrimEnd('\')) {
    Doing "копирую файлы"
    robocopy $Src $Root /E /NFL /NDL /NJH /NJS /NP /XD .git out dist __pycache__ /XF settings.ini version.txt *.pyc | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy: ошибка копирования ($LASTEXITCODE)" }
}
[IO.File]::WriteAllText((Join-Path $Root "version.txt"), "v$newV`n$newV`nустановлено с $Src`n", (New-Object Text.UTF8Encoding $false))
if ($ResetConfig -and (Test-Path (Join-Path $Root "settings.ini"))) { Remove-Item (Join-Path $Root "settings.ini") -Force; Info "settings.ini сброшен" }
if (Test-Path (Join-Path $Root "settings.ini")) { Info "ваши настройки (settings.ini) сохранены" }
Ok "плагины в $Root"

# ------------------------------------------------------------------ 5. Tapir + ярлыки
Step 5 "Подключаю к палитре Tapir, ярлыки «Менеджер плагинов Archicad»"
if ($uv) {
    $out = & $uv run --quiet --script (Join-Path $Root "_setup\archicad_setup.py") --root $Root --uv $uv 2>&1
    $out | ForEach-Object { Doing "$_" }
    if ($LASTEXITCODE -eq 0) { Ok "палитра Tapir: папка $Root\tapir-scripts" }
    elseif ($LASTEXITCODE -eq 2) { Bad "Archicad открыт — палитра Tapir не подключена. Закройте Archicad и запустите установку снова" }
    else { Bad "не удалось подключить к Tapir (код $LASTEXITCODE) — см. журнал" }
} else {
    Info "пропущено — нет uv"
}

# ------------------------------------------------------------------ 6. окружение
Step 6 "Готовлю Python и библиотеку PDF (pymupdf)"
if ($uv) {
    Doing "в первый раз скачивается ~40 МБ, 1-2 минуты"
    & $uv run --quiet --script (Join-Path $Root "tapir-scripts\KD_Karkas_PDF.py") --help 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Ok "окружение готово" } else { Bad "не удалось подготовить окружение (код $LASTEXITCODE) — см. журнал" }
} else {
    Info "пропущено — нет uv"
}

# ------------------------------------------------------------------ 7. шрифт
Step 7 "Проверяю шрифт ГОСТ 2.304 (для PDF)"
$gost = @("$env:WINDIR\Fonts\GOST_B.TTF", "$env:WINDIR\Fonts\GOST_BU.ttf", "$env:LOCALAPPDATA\Microsoft\Windows\Fonts\GOST_B.TTF") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
if ($gost) { Ok "GOST type B найден" }
else { Info "GOST type B не найден — PDF без Archicad будет набран Arial (в Archicad шрифт берётся из мастер-макета)" }

# ------------------------------------------------------------------ итог
Write-Host ""
Write-Host "  ==================================================" -ForegroundColor DarkCyan
if ($Problems.Count -eq 0) {
    Write-Host "     ГОТОВО" -ForegroundColor Green
} else {
    Write-Host "     ГОТОВО С ЗАМЕЧАНИЯМИ:" -ForegroundColor Yellow
    foreach ($p in $Problems) { Write-Host "      - $p" -ForegroundColor Yellow }
}
Write-Host "  ==================================================" -ForegroundColor DarkCyan
Write-Host ""
Write-Host "   Как запустить:" -ForegroundColor White
if ($acRunning) { Write-Host "    1. Перезапустите Archicad 30" } else { Write-Host "    1. Запустите Archicad 30" }
Write-Host "    2. Откройте проект с каркасом ArchiFrame"
Write-Host "       (установлен ArchiFrame или проект .pla с вложенной библиотекой)"
Write-Host "    3. Палитра Tapir -> KD_Karkas_PDF.py (Плагины Archicad) -> Run"
Write-Host ""
Write-Host "   Настройки, версия, обновление: ярлык «Менеджер плагинов Archicad»"
Write-Host "   на рабочем столе. Обновления приходят сами при входе в Windows."
Write-Host "   После установки эту папку можно удалить — работает копия в $Root"
Write-Host ""
Write-Host "   Журнал установки: $Log" -ForegroundColor DarkGray
try { Stop-Transcript | Out-Null } catch {}
