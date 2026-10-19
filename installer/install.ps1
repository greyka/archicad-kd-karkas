# Установка / обновление kd_plugin (КД каркаса) для Archicad 30.
param([switch]$ResetConfig)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'            # без «полосы» Invoke-WebRequest — так быстрее
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$PluginRoot = Join-Path (Split-Path -Parent $Here) "tapir-scripts"   # KD_Karkas_PDF.py + kd_plugin
$Repo = @{ owner = "greyka"; name = "archicad-kd-karkas"; loc = "tapir-scripts"; title = "КД каркаса" }
$Log = Join-Path $env:TEMP "kd_install.log"
$Problems = New-Object System.Collections.ArrayList
$Total = 6
try { Start-Transcript -Path $Log -Force | Out-Null } catch {}

# ------------------------------------------------------------------ вывод
function Get-PluginVersion($kdDir) {
    $f = Join-Path $kdDir "__init__.py"
    if (-not (Test-Path $f)) { return $null }
    $m = Select-String -Path $f -Pattern '__version__\s*=\s*"([^"]+)"' | Select-Object -First 1
    if ($m) { return $m.Matches[0].Groups[1].Value } else { return "0" }
}
function Banner {
    $v = Get-PluginVersion (Join-Path $PluginRoot "kd_plugin\kd")
    Write-Host ""
    Write-Host "  ==================================================" -ForegroundColor DarkCyan
    Write-Host "     КД каркаса для Archicad 30  —  установка" -ForegroundColor White
    Write-Host "     версия $v" -ForegroundColor Gray
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
Get-ChildItem $PluginRoot -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue

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
    foreach ($p in @("$env:LOCALAPPDATA\Microsoft\WinGet\Links\uv.exe", "$env:USERPROFILE\.local\bin\uv.exe")) {
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
        Doing "устанавливаю uv с astral.sh"
        powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" | Out-Null
    }
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    $uv = Find-Uv
    if ($uv) { Ok "uv установлен" } else { Bad "uv не установился — выполните вручную: winget install astral-sh.uv" }
}

# ------------------------------------------------------------------ 4. плагин
Step 4 "Подключаю плагин и обновления с GitHub"
$docs = [Environment]::GetFolderPath('MyDocuments')
$tdir = Join-Path $docs "Tapir"
$tcfg = Join-Path $tdir "config.json"
$cs = Join-Path $tdir "custom-scripts"
$userCfgDir = Join-Path $env:APPDATA "kd_plugin"
$userCfg = Join-Path $userCfgDir "config.json"

# старая установка (копия в custom-scripts): переносим настройки и убираем дубль кнопки
$oldCfg = Join-Path $cs "kd_plugin\config.json"
if ((Test-Path $oldCfg) -and -not (Test-Path $userCfg)) {
    New-Item -ItemType Directory -Force $userCfgDir | Out-Null
    Copy-Item $oldCfg $userCfg
    Doing "ваши настройки перенесены в $userCfg"
}
if ((Test-Path (Join-Path $cs "KD_Karkas_PDF.py")) -or (Test-Path (Join-Path $cs "kd_plugin"))) {
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $cs "KD_Karkas_PDF.py")
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $cs "kd_plugin")
    Doing "старая копия кнопки из custom-scripts убрана"
}

# репозиторий в настройках Tapir — палитра сама скачивает и обновляет скрипты
New-Item -ItemType Directory -Force $tdir | Out-Null
if (Test-Path $tcfg) {
    $j = Get-Content $tcfg -Raw -Encoding UTF8 | ConvertFrom-Json
} else {
    $j = [pscustomobject]@{
        repositories = @([pscustomobject]@{ displayName = "Tapir"; repoOwner = "ENZYME-APD"; repoName = "tapir-archicad-automation";
                                            relativeLoc = "builtin-scripts"; token = ""; excludeFromDownloadPattern = "";
                                            includePattern = ""; excludePattern = "" })
        localFolders = @(); askUpdatingAddOnBeforeEachExecution = $false; uvLocation = ""; pythonLocation = ""
    }
}
$repos = @($j.repositories)
if ($repos | Where-Object { $_.repoOwner -eq $Repo.owner -and $_.repoName -eq $Repo.name }) {
    Info "репозиторий $($Repo.owner)/$($Repo.name) уже подключён"
} else {
    $repos += [pscustomobject]@{ displayName = $Repo.title; repoOwner = $Repo.owner; repoName = $Repo.name;
                                 relativeLoc = $Repo.loc; token = ""; excludeFromDownloadPattern = "";
                                 includePattern = ""; excludePattern = "" }
    $j.repositories = $repos
    Doing "добавляю github.com/$($Repo.owner)/$($Repo.name) в палитру Tapir"
}
if ($uv -and -not $j.uvLocation) { $j.uvLocation = $uv; Doing "прописываю путь к uv в настройках Tapir" }
[IO.File]::WriteAllText($tcfg, ($j | ConvertTo-Json -Depth 10), (New-Object Text.UTF8Encoding $false))
Ok "плагин будет скачан и обновляться с GitHub палитрой Tapir"
if (Test-Path $userCfg) { Info "ваши настройки: $userCfg" }

# ------------------------------------------------------------------ 5. окружение
Step 5 "Готовлю Python и библиотеку PDF (pymupdf)"
if ($uv) {
    Doing "в первый раз скачивается ~40 МБ, 1-2 минуты"
    & $uv run --quiet --script (Join-Path $PluginRoot "KD_Karkas_PDF.py") --help 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Ok "окружение готово" } else { Bad "не удалось подготовить окружение (код $LASTEXITCODE) — см. журнал" }
} else {
    Info "пропущено — нет uv"
}

# ------------------------------------------------------------------ 6. шрифт
Step 6 "Проверяю шрифт ГОСТ 2.304 (для PDF)"
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
Write-Host "    3. Палитра Tapir -> в списке скриптов KD_Karkas_PDF.py (КД каркаса) -> Run"
Write-Host "       Если его нет в списке — кнопка обновления в палитре (скачает с GitHub)."
Write-Host "       Обновления плагина приходят сами, переустанавливать не нужно."
Write-Host ""
Write-Host "   Журнал установки: $Log" -ForegroundColor DarkGray
try { Stop-Transcript | Out-Null } catch {}
